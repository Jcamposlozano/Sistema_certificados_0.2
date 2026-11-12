from datetime import date

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ParticipantRow(Base):
    __tablename__ = "participants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    subject: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (CheckConstraint("hours > 0", name="positive_hours"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(250))
    category: Mapped[str] = mapped_column(String(80))
    date: Mapped[date] = mapped_column(Date)
    hours: Mapped[int] = mapped_column(Integer)


class AttendanceRow(Base):
    __tablename__ = "attendances"
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    available: Mapped[bool] = mapped_column(Boolean, default=False)


class ChallengeRow(Base):
    __tablename__ = "otp_challenges"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    provider_state: Mapped[str] = mapped_column(Text)
    created_at: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)


class SessionRow(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)


class RateRow(Base):
    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[int] = mapped_column(BigInteger, index=True)
