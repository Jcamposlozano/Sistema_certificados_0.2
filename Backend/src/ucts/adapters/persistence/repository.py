import time
from dataclasses import asdict
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session as DbSession
from sqlalchemy.orm import sessionmaker

from ucts.adapters.persistence.models import (
    AttendanceRow,
    ChallengeRow,
    EventRow,
    ParticipantRow,
    RateRow,
    SessionRow,
)
from ucts.domain.models import AppError, Challenge, ErrorKind, Event, Identity, Participant, Session


class SqlRepository:
    def __init__(self, db: DbSession):
        self.db = db

    def throttle(self, key: str, limit: int, expires_at: int) -> bool:
        insert = pg_insert if self.db.get_bind().dialect.name == "postgresql" else sqlite_insert
        self.db.execute(
            insert(RateRow)
            .values(key=key, count=0, expires_at=expires_at)
            .on_conflict_do_nothing(index_elements=["key"])
        )
        row = self.db.scalar(select(RateRow).where(RateRow.key == key).with_for_update())
        assert row is not None
        if row.expires_at <= int(time.time()):
            row.count = 0
            row.expires_at = expires_at
        if row.count >= limit:
            return False
        row.count += 1
        self.db.flush()
        return True

    def add_challenge(self, challenge: Challenge) -> None:
        # An email has only one outstanding challenge, including resends.
        self.db.execute(delete(ChallengeRow).where(ChallengeRow.email == challenge.email))
        self.db.add(ChallengeRow(**asdict(challenge)))

    def challenge(self, challenge_id: str) -> Challenge | None:
        row = self.db.scalar(
            select(ChallengeRow).where(ChallengeRow.id == challenge_id).with_for_update()
        )
        return (
            Challenge(
                row.id,
                row.email,
                row.provider_state,
                row.created_at,
                row.expires_at,
                row.attempts,
                row.consumed,
            )
            if row
            else None
        )

    def save_challenge(self, challenge: Challenge) -> None:
        row = self.db.get(ChallengeRow, challenge.id)
        assert row is not None
        row.attempts = challenge.attempts
        row.consumed = challenge.consumed

    @staticmethod
    def _participant(row: ParticipantRow) -> Participant:
        return Participant(row.id, row.name, row.email, row.subject)

    def participant(self, participant_id: str) -> Participant | None:
        row = self.db.get(ParticipantRow, participant_id)
        return self._participant(row) if row else None

    def bind_identity(self, identity: Identity) -> Participant:
        # Email must be verified by the identity provider before associating an imported record.
        row = self.db.scalar(
            select(ParticipantRow).where(ParticipantRow.email == identity.email).with_for_update()
        )
        if not row:
            row = ParticipantRow(
                id=str(uuid4()), name="", email=identity.email, subject=identity.subject
            )
            self.db.add(row)
        elif row.subject and row.subject != identity.subject:
            raise AppError(ErrorKind.UNAUTHORIZED, "No fue posible asociar la identidad.")
        else:
            row.subject = identity.subject
        self.db.flush()
        return self._participant(row)

    def add_session(self, session: Session) -> None:
        self.db.add(SessionRow(**asdict(session)))

    def session(self, token_hash: str) -> Session | None:
        row = self.db.get(SessionRow, token_hash)
        return Session(row.token_hash, row.participant_id, row.expires_at) if row else None

    def delete_session(self, token_hash: str) -> None:
        self.db.execute(delete(SessionRow).where(SessionRow.token_hash == token_hash))

    def events(self, participant_id: str) -> list[Event]:
        result = self.db.execute(
            select(EventRow, AttendanceRow.available)
            .join(AttendanceRow)
            .where(AttendanceRow.participant_id == participant_id)
            .order_by(EventRow.date.desc(), EventRow.id)
        )
        return [
            Event(row.id, row.title, row.category, row.date, row.hours, available)
            for row, available in result
        ]

    def event(self, participant_id: str, event_id: str) -> Event | None:
        result = self.db.execute(
            select(EventRow, AttendanceRow.available)
            .join(AttendanceRow)
            .where(AttendanceRow.participant_id == participant_id, EventRow.id == event_id)
        ).first()
        if not result:
            return None
        row, available = result
        return Event(row.id, row.title, row.category, row.date, row.hours, available)


class SqlUnitOfWork:
    def __init__(self, factory: sessionmaker[DbSession]):
        self.factory = factory

    def __enter__(self) -> "SqlUnitOfWork":
        self.db = self.factory()
        self.repo = SqlRepository(self.db)
        return self

    def __exit__(self, *args: object) -> None:
        self.db.rollback()
        self.db.close()

    def commit(self) -> None:
        self.db.commit()
