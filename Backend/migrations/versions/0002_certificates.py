"""Store imported certificates and their private S3 objects."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "participants", sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False)
    )
    with op.batch_alter_table("events") as batch:
        batch.alter_column("title", existing_type=sa.String(250), type_=sa.Text())
        batch.alter_column("date", existing_type=sa.Date(), nullable=True)
        batch.alter_column("hours", existing_type=sa.Integer(), nullable=True)
    op.create_index("ix_attendances_event_id", "attendances", ["event_id"])

    op.create_table(
        "certificates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("participant_id", sa.String(36), nullable=False),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("recipient_name", sa.String(200), nullable=False),
        sa.Column("template", sa.String(80), nullable=False),
        sa.Column("role", sa.String(120), nullable=False),
        sa.Column("status", sa.String(12), server_default="pending", nullable=False),
        sa.Column("s3_bucket", sa.String(63)),
        sa.Column("s3_key", sa.String(1024)),
        sa.Column("s3_version_id", sa.String(1024)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["participant_id", "event_id"],
            ["attendances.participant_id", "attendances.event_id"],
            name="fk_certificates_attendance",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("s3_bucket", "s3_key", name="uq_certificates_s3_object"),
        sa.CheckConstraint(
            "(status = 'pending' AND s3_bucket IS NULL AND s3_key IS NULL "
            "AND s3_version_id IS NULL AND published_at IS NULL) OR "
            "(status IN ('published', 'revoked') AND s3_bucket IS NOT NULL "
            "AND s3_key IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_certificates_publication",
        ),
    )
    op.create_index("ix_certificates_attendance", "certificates", ["participant_id", "event_id"])
    op.create_table(
        "certificate_imports",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column(
            "imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_table(
        "certificate_sources",
        sa.Column("import_sha256", sa.String(64), primary_key=True),
        sa.Column("sheet", sa.String(31), primary_key=True),
        sa.Column("row_number", sa.Integer(), primary_key=True),
        sa.Column("certificate_id", sa.String(36), nullable=False),
        sa.Column("recorded_date", sa.Date(), nullable=False),
        sa.CheckConstraint("row_number >= 2", name="ck_certificate_sources_row"),
        sa.ForeignKeyConstraint(
            ["import_sha256"], ["certificate_imports.sha256"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["certificate_id"], ["certificates.id"], ondelete="RESTRICT"),
    )
    op.create_index(
        "ix_certificate_sources_certificate_id", "certificate_sources", ["certificate_id"]
    )


def downgrade():
    connection = op.get_bind()
    # Keep the downgrade lossless. Imported rows require the new schema.
    for query in (
        "SELECT 1 FROM certificate_imports LIMIT 1",
        "SELECT 1 FROM certificates LIMIT 1",
        "SELECT 1 FROM events WHERE date IS NULL OR hours IS NULL OR length(title) > 250 LIMIT 1",
        "SELECT 1 FROM participants WHERE NOT enabled LIMIT 1",
    ):
        if connection.execute(sa.text(query)).first():
            raise RuntimeError("Existen datos que requieren la revisión 0002.")
    op.drop_table("certificate_sources")
    op.drop_table("certificate_imports")
    op.drop_table("certificates")
    op.drop_index("ix_attendances_event_id", table_name="attendances")
    with op.batch_alter_table("events") as batch:
        batch.alter_column("hours", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("date", existing_type=sa.Date(), nullable=False)
        batch.alter_column("title", existing_type=sa.Text(), type_=sa.String(250))
    op.drop_column("participants", "enabled")
