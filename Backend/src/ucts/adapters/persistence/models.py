from datetime import date as DateValue
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ParticipantRow(Base):
    __tablename__ = "participants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=true())
    subject: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)


class EventRow(Base):
    __tablename__ = "events"
    __table_args__ = (CheckConstraint("hours > 0", name="positive_hours"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(80))
    date: Mapped[DateValue | None] = mapped_column(Date)
    hours: Mapped[int | None] = mapped_column(Integer)


class AttendanceRow(Base):
    __tablename__ = "attendances"
    __table_args__ = (Index("ix_attendances_event_id", "event_id"),)
    participant_id: Mapped[str] = mapped_column(
        ForeignKey("participants.id", ondelete="CASCADE"), primary_key=True
    )
    event_id: Mapped[str] = mapped_column(
        ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    available: Mapped[bool] = mapped_column(Boolean, default=False)


class CertificateRow(Base):
    __tablename__ = "certificates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["participant_id", "event_id"],
            ["attendances.participant_id", "attendances.event_id"],
            name="fk_certificates_attendance",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("s3_bucket", "s3_key", name="uq_certificates_s3_object"),
        CheckConstraint(
            "(status = 'pending' AND s3_bucket IS NULL AND s3_key IS NULL "
            "AND s3_version_id IS NULL AND published_at IS NULL) OR "
            "(status IN ('published', 'revoked') AND s3_bucket IS NOT NULL "
            "AND s3_key IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_certificates_publication",
        ),
        Index("ix_certificates_attendance", "participant_id", "event_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    participant_id: Mapped[str] = mapped_column(String(36))
    event_id: Mapped[str] = mapped_column(String(36))
    recipient_name: Mapped[str] = mapped_column(String(200))
    template: Mapped[str] = mapped_column(String(80))
    role: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(12), server_default="pending")
    s3_bucket: Mapped[str | None] = mapped_column(String(63))
    s3_key: Mapped[str | None] = mapped_column(String(1024))
    s3_version_id: Mapped[str | None] = mapped_column(String(1024))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CertificateImportRow(Base):
    __tablename__ = "certificate_imports"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class CertificateSourceRow(Base):
    __tablename__ = "certificate_sources"
    __table_args__ = (CheckConstraint("row_number >= 2", name="ck_certificate_sources_row"),)
    import_sha256: Mapped[str] = mapped_column(
        ForeignKey("certificate_imports.sha256", ondelete="RESTRICT"), primary_key=True
    )
    sheet: Mapped[str] = mapped_column(String(31), primary_key=True)
    row_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    certificate_id: Mapped[str] = mapped_column(
        ForeignKey("certificates.id", ondelete="RESTRICT"), index=True
    )
    recorded_date: Mapped[DateValue] = mapped_column(Date)


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


class CertificateDownloadRow(Base):
    __tablename__ = "certificate_downloads"
    __table_args__ = (
        Index("ix_certificate_downloads_participant_time", "participant_id", "downloaded_at_utc"),
        Index("ix_certificate_downloads_certificate_id", "certificate_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # IDs conservan la referencia histórica incluso después de borrar un vínculo de acceso.
    participant_id: Mapped[str] = mapped_column(String(36))
    event_id: Mapped[str] = mapped_column(String(36))
    certificate_id: Mapped[str | None] = mapped_column(String(36))
    downloaded_at_utc: Mapped[str] = mapped_column(String(35))
