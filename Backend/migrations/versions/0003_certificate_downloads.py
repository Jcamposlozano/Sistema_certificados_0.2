"""Add an audit record for certificate downloads."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "certificate_downloads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("participant_id", sa.String(36), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("certificate_id", sa.String(36), nullable=True),
        sa.Column("downloaded_at_utc", sa.String(35), nullable=False),
    )
    op.create_index(
        "ix_certificate_downloads_participant_time",
        "certificate_downloads",
        ["participant_id", "downloaded_at_utc"],
    )
    op.create_index(
        "ix_certificate_downloads_certificate_id", "certificate_downloads", ["certificate_id"]
    )


def downgrade():
    op.drop_table("certificate_downloads")
