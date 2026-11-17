import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from email_validator import EmailNotValidError, validate_email
from openpyxl import load_workbook
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ucts.adapters.persistence.models import (
    AttendanceRow,
    CertificateImportRow,
    CertificateRow,
    CertificateSourceRow,
    EventRow,
    ParticipantRow,
)

SHEETS = {
    "Unificado": ("identificacion", "tipo_asistencia", "nombre_taller"),
    "Posters": ("tipo_asistencia", "nombre_poster", "autores"),
    "Ganadores poster": ("lugar", "nombre_poster", "autores"),
}
CATEGORIES = {
    "simposio-II": "Simposio",
    "simposio-IV": "Simposio",
    "taller-simposio-IV": "Taller",
    "Poster": "Póster",
    "Poster Ganador": "Póster",
}


def canonical_email(value: str) -> str:
    return validate_email(value.strip(), check_deliverability=False).normalized.lower()


def stable_id(kind: str, *values: str) -> str:
    key = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
    return str(uuid5(NAMESPACE_URL, f"ucts:{kind}:{key}"))


@dataclass(frozen=True)
class Source:
    sheet: str
    row_number: int
    email: str
    name: str
    document: str
    title: str
    template: str
    role: str
    authors: str
    recorded_date: date

    @property
    def event_id(self) -> str:
        return stable_id("event", CATEGORIES[self.template], self.title)

    def certificate_id(self, participant_id: str) -> str:
        return stable_id(
            "certificate",
            participant_id,
            self.event_id,
            self.template,
            self.role,
            self.name,
            self.authors,
        )


def required_text(value: object, column: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise ValueError(f"valor inválido en {column}")
    return value.strip()


def read_source(sheet: str, number: int, row: dict) -> Source:
    raw_email = required_text(row["CORREO"], "CORREO", 254)
    try:
        email = canonical_email(raw_email)
    except EmailNotValidError:
        raise ValueError("correo inválido") from None
    template = required_text(row["template_id"], "template_id", 80)
    allowed = {
        "Unificado": {"simposio-II", "simposio-IV", "taller-simposio-IV"},
        "Posters": {"Poster"},
        "Ganadores poster": {"Poster Ganador"},
    }
    if template not in allowed[sheet]:
        raise ValueError("plantilla inesperada para la hoja")
    recorded = row["FECHA"]
    if isinstance(recorded, datetime):
        recorded = recorded.date()
    if not isinstance(recorded, date):
        raise ValueError("fecha inválida")
    title_column = "nombre_taller" if sheet == "Unificado" else "nombre_poster"
    role_column = "lugar" if sheet == "Ganadores poster" else "tipo_asistencia"
    document = ""
    authors = ""
    if sheet == "Unificado":
        raw_document = row["identificacion"]
        if not isinstance(raw_document, (int, str)) or not str(raw_document).strip():
            raise ValueError("identificación ausente o inválida")
        document = "".join(str(raw_document).split())
    else:
        authors = required_text(row["autores"], "autores", 2000)
    return Source(
        sheet,
        number,
        email,
        required_text(row["nombre"], "nombre", 200),
        document,
        required_text(row[title_column], title_column, 2000),
        template,
        required_text(row[role_column], role_column, 120),
        authors,
        recorded,
    )


def read_workbook(path: Path) -> tuple[str, list[Source], list[str]]:
    contents = path.read_bytes()
    checksum = hashlib.sha256(contents).hexdigest()
    records = []
    issues = []
    documents = defaultdict(set)
    workbook = load_workbook(BytesIO(contents), read_only=True, data_only=True)
    try:
        for sheet, extra in SHEETS.items():
            if sheet not in workbook.sheetnames:
                raise ValueError(f"Falta la hoja {sheet}.")
            values = workbook[sheet].values
            headers = next(values, ())
            required = {"FECHA", "nombre", "CORREO", "template_id", *extra}
            if any(headers.count(column) != 1 for column in required):
                raise ValueError(f"Encabezados ausentes o repetidos en {sheet}.")
            for number, cells in enumerate(values, 2):
                if all(cell in (None, "") for cell in cells):
                    continue
                try:
                    row = dict(zip(headers, cells))
                    source = read_source(sheet, number, row)
                    records.append(source)
                    if source.document:
                        documents[source.email].add(source.document)
                except ValueError as error:
                    issues.append(f"{sheet}, fila {number}: {error}")
    finally:
        workbook.close()

    valid = []
    for source in records:
        if len(documents[source.email]) > 1:
            issues.append(f"{source.sheet}, fila {source.row_number}: correo con varios documentos")
        else:
            valid.append(source)
    if not valid:
        raise ValueError("El libro no contiene filas que se puedan importar.")
    return checksum, valid, issues


def lock_certificate_admin(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(514875398)"))


def import_certificates(db: Session, checksum: str, records: list[Source]) -> bool:
    lock_certificate_admin(db)
    if db.get(CertificateImportRow, checksum):
        return False
    db.add(CertificateImportRow(sha256=checksum))
    db.flush()

    participants = {row.email: row for row in db.scalars(select(ParticipantRow))}
    events = {row.id: row for row in db.scalars(select(EventRow))}
    dates = defaultdict(set)
    for source in records:
        dates[source.event_id].add(source.recorded_date)
        if source.email not in participants:
            row = ParticipantRow(
                id=stable_id("participant", source.email), email=source.email, name=source.name
            )
            participants[source.email] = row
            db.add(row)
        elif not participants[source.email].name:
            participants[source.email].name = source.name

    for source in records:
        event_id = source.event_id
        if event_id not in events:
            event_dates = dates[event_id]
            event = EventRow(
                id=event_id,
                title=source.title,
                category=CATEGORIES[source.template],
                date=next(iter(event_dates)) if len(event_dates) == 1 else None,
            )
            events[event_id] = event
            db.add(event)
    db.flush()

    attendances = set(db.execute(select(AttendanceRow.participant_id, AttendanceRow.event_id)))
    for source in records:
        key = participants[source.email].id, source.event_id
        if key not in attendances:
            db.add(AttendanceRow(participant_id=key[0], event_id=key[1], available=False))
            attendances.add(key)
    db.flush()

    certificates = set(db.scalars(select(CertificateRow.id)))
    for source in records:
        participant_id = participants[source.email].id
        certificate_id = source.certificate_id(participant_id)
        if certificate_id not in certificates:
            db.add(
                CertificateRow(
                    id=certificate_id,
                    participant_id=participant_id,
                    event_id=source.event_id,
                    recipient_name=source.name,
                    template=source.template,
                    role=source.role,
                )
            )
            certificates.add(certificate_id)
    db.flush()

    db.add_all(
        CertificateSourceRow(
            import_sha256=checksum,
            sheet=source.sheet,
            row_number=source.row_number,
            recorded_date=source.recorded_date,
            certificate_id=source.certificate_id(participants[source.email].id),
        )
        for source in records
    )
    return True
