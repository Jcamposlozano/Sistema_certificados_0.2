"""Initial certificate and authentication schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "participants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("subject", sa.String(128), unique=True),
    )
    op.create_table(
        "events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(250), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("hours", sa.Integer(), nullable=False),
        sa.CheckConstraint("hours > 0", name="positive_hours"),
    )
    op.create_table(
        "attendances",
        sa.Column(
            "participant_id",
            sa.String(36),
            sa.ForeignKey("participants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "event_id",
            sa.String(36),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("available", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "otp_challenges",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("provider_state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("consumed", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_otp_challenges_email", "otp_challenges", ["email"])
    op.create_index("ix_otp_challenges_expires_at", "otp_challenges", ["expires_at"])
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column(
            "participant_id",
            sa.String(36),
            sa.ForeignKey("participants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_auth_sessions_participant_id", "auth_sessions", ["participant_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "rate_limits",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_rate_limits_expires_at", "rate_limits", ["expires_at"])


def downgrade():
    for table in (
        "rate_limits",
        "auth_sessions",
        "otp_challenges",
        "attendances",
        "events",
        "participants",
    ):
        op.drop_table(table)
