import csv
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from email_validator import EmailNotValidError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ucts.adapters.persistence.certificate_import import canonical_email, lock_certificate_admin
from ucts.adapters.persistence.models import CertificateRow, CertificateSourceRow, ParticipantRow


def publish_certificates(
    db: Session, checksum: str, manifest: Path, bucket: str, inspect: Callable[[str], str | None]
) -> int:
    lock_certificate_admin(db)
    assignments = {}
    owners = {}
    with manifest.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = ("hoja", "fila_excel", "correo", "s3_key")
        if any((reader.fieldnames or []).count(column) != 1 for column in columns):
            raise ValueError("El manifiesto requiere hoja,fila_excel,correo,s3_key.")
        for line, row in enumerate(reader, 2):
            try:
                source_number = int(row["fila_excel"] or "")
                email = canonical_email(row["correo"] or "")
            except (ValueError, EmailNotValidError):
                raise ValueError(f"Manifiesto, línea {line}: fila o correo inválido.") from None
            key = row["s3_key"] or ""
            if (
                not key.lower().endswith(".pdf")
                or not 1 <= len(key.encode("utf-8")) <= 1024
                or any(ord(char) < 32 for char in key)
            ):
                raise ValueError(f"Manifiesto, línea {line}: clave S3 inválida.")
            result = db.execute(
                select(CertificateRow, ParticipantRow.email)
                .join(
                    CertificateSourceRow, CertificateSourceRow.certificate_id == CertificateRow.id
                )
                .join(ParticipantRow, ParticipantRow.id == CertificateRow.participant_id)
                .where(
                    CertificateSourceRow.import_sha256 == checksum,
                    CertificateSourceRow.sheet == row["hoja"],
                    CertificateSourceRow.row_number == source_number,
                )
                .with_for_update(of=CertificateRow)
            ).one_or_none()
            if result is None or result.email != email:
                raise ValueError(f"Manifiesto, línea {line}: la fila y el correo no coinciden.")
            cert = result[0]
            if cert.id in assignments and assignments[cert.id][1] != key:
                raise ValueError(f"Manifiesto, línea {line}: dos objetos para un certificado.")
            if key in owners and owners[key] != cert.id:
                raise ValueError(f"Manifiesto, línea {line}: objeto asignado a otro certificado.")
            owners[key] = cert.id
            assignments[cert.id] = cert, key, line

    if not assignments:
        raise ValueError("El manifiesto está vacío.")
    new_publications = []
    for cert, key, line in assignments.values():
        if cert.status == "published" and (cert.s3_bucket, cert.s3_key) == (bucket, key):
            continue
        if cert.status != "pending":
            raise ValueError(f"Manifiesto, línea {line}: el certificado ya tiene un estado final.")
        current_owner = db.scalar(
            select(CertificateRow.id).where(
                CertificateRow.s3_bucket == bucket, CertificateRow.s3_key == key
            )
        )
        if current_owner is not None:
            raise ValueError(f"Manifiesto, línea {line}: objeto asignado a otro certificado.")
        new_publications.append((cert, key, line))

    for cert, key, line in new_publications:
        try:
            version = inspect(key)
        except ValueError as error:
            raise ValueError(f"Manifiesto, línea {line}: {error}") from None
        cert.s3_bucket = bucket
        cert.s3_key = key
        cert.s3_version_id = version
        cert.published_at = datetime.now(UTC)
        cert.status = "published"
    return len(new_publications)
