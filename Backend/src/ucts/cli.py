import argparse
import time
from datetime import date
from uuid import uuid4

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from ucts.adapters.persistence.models import (
    AttendanceRow,
    ChallengeRow,
    EventRow,
    ParticipantRow,
    RateRow,
    SessionRow,
)
from ucts.config import Settings


def main():
    parser = argparse.ArgumentParser(description="Administración local UCTS")
    parser.add_argument("command", choices=["seed", "cleanup"])
    args = parser.parse_args()
    settings = Settings()
    engine = create_engine(settings.database_url)
    with Session(engine) as db:
        if args.command == "cleanup":
            now = int(time.time())
            for model in (ChallengeRow, SessionRow, RateRow):
                db.execute(delete(model).where(model.expires_at <= now))
            print("Registros de autenticación vencidos eliminados.")
        else:
            if settings.app_env != "local" or settings.auth_mode != "local":
                parser.error("El seed solo se permite en entorno local y AUTH_MODE=local.")
            email = "demo@ucts.local"
            participant = db.scalar(select(ParticipantRow).where(ParticipantRow.email == email))
            if not participant:
                participant = ParticipantRow(
                    id=str(uuid4()), name="Participante de demostración", email=email
                )
                db.add(participant)
                db.flush()
            data = [
                (
                    "innovation",
                    "Encuentro de innovación y tecnología",
                    "Encuentro",
                    date(2026, 10, 18),
                    8,
                    True,
                ),
                ("leadership", "Liderazgo que transforma", "Taller", date(2026, 9, 24), 4, True),
                (
                    "research",
                    "Jornada de investigación UCTS",
                    "Jornada",
                    date(2026, 11, 5),
                    6,
                    False,
                ),
            ]
            for key, title, category, day, hours, available in data:
                if not db.get(EventRow, key):
                    db.add(EventRow(id=key, title=title, category=category, date=day, hours=hours))
                    db.flush()
                if not db.get(AttendanceRow, (participant.id, key)):
                    db.add(
                        AttendanceRow(
                            participant_id=participant.id, event_id=key, available=available
                        )
                    )
            print(f"Datos de ejemplo listos para {email}. El OTP se imprime en la terminal de API.")
        db.commit()
    engine.dispose()
