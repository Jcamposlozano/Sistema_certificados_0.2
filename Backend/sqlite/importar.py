"""Importa las asociaciones del Excel en la base local de certificados UCTS."""

import argparse
import hashlib
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile

from email_validator import EmailNotValidError, validate_email
from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

SCHEMA = Path(__file__).with_name("esquema.sql").read_text(encoding="utf-8")
DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "ucts_certificados.sqlite"
HEADERS = {
    "Usuarios": ("identificacion", "nombre"),
    "Correos": ("identificacion", "CORREO", "Principal"),
    "Certificados": ("identificacion", "template_id", "nombre_taller", "tipo_asistencia"),
    "Templates": ("template_id", "nombre_taller"),
}
TABLES = (
    "evento_head",
    "usuarios",
    "correos",
    "templates",
    "certificados",
    "importaciones",
    "importacion_filas",
)


class ImportValidationError(ValueError):
    pass


@dataclass
class Row:
    sheet: str
    number: int
    issues: list[str] = field(default_factory=list)
    document: str | None = None
    name: str | None = None
    email: str | None = None
    primary: bool | None = None
    template: tuple[str, str] | None = None
    role: str | None = None
    user_id: str | None = None
    email_id: str | None = None
    template_uuid: str | None = None
    certificate_id: str | None = None


def read_text(cell, column):
    value = cell.value
    if (
        cell.data_type in {"f", "e"}
        or not isinstance(value, str)
        or not value.strip()
        or "\x00" in value
    ):
        raise ValueError(f"{column} ausente o inválido")
    return value.strip()


def read_document(cell, column):
    value = cell.value
    if isinstance(value, str):
        return read_text(cell, column)
    if type(value) not in (int, float) or not 0 <= value < 10**15 or value != int(value):
        raise ValueError("identificación numérica ausente, inválida o de precisión incierta")
    digits = str(int(value))
    fmt = cell.number_format
    if re.fullmatch(r"0+", fmt):
        return digits.zfill(len(fmt))
    if fmt in {"General", "@"}:
        return digits
    raise ValueError("formato de identificación numérica ambiguo")


def read_email(cell, column):
    try:
        validated = validate_email(read_text(cell, column), check_deliverability=False)
        return validated.normalized.lower()
    except EmailNotValidError:
        raise ValueError("dirección de correo inválida") from None


def read_primary(cell, column):
    value = cell.value
    if cell.data_type not in {"f", "e"}:
        if type(value) is bool:
            return value
        if isinstance(value, str):
            flag = value.strip().casefold()
            if flag in {"true", "false", "sí", "si", "no"}:
                return flag in {"true", "sí", "si"}
        if type(value) is int and value in (0, 1):
            return bool(value)
    raise ValueError(f"indicador {column} ausente o inválido")


def parse_field(record, cells, column, parser=read_text):
    try:
        return parser(cells[column], column)
    except ValueError as error:
        record.issues.append(str(error))
        return None


def read_workbook(path):
    contents = path.read_bytes()
    checksum = hashlib.sha256(contents).hexdigest()
    records = {sheet: [] for sheet in HEADERS}
    with closing(load_workbook(BytesIO(contents), read_only=True)) as book:
        for sheet, required in HEADERS.items():
            if sheet == "Templates" and sheet not in book:
                continue
            if sheet not in book:
                raise ImportValidationError(f"Falta la hoja {sheet}.")
            rows = book[sheet].iter_rows()
            header = [
                cell.value.strip() if isinstance(cell.value, str) else cell.value
                for cell in next(rows, ())
            ]
            if any(header.count(column) != 1 for column in required):
                raise ImportValidationError(
                    f"Encabezados requeridos ausentes o repetidos en {sheet}."
                )
            columns = {column: header.index(column) for column in required}
            for number, cells in enumerate(rows, 2):
                if all(cell.value in (None, "") for cell in cells):
                    continue
                fields = {column: cells[index] for column, index in columns.items()}
                row = Row(sheet, number)
                records[sheet].append(row)
                if "identificacion" in fields:
                    row.document = parse_field(row, fields, "identificacion", read_document)
                if sheet == "Usuarios":
                    row.name = parse_field(row, fields, "nombre")
                if sheet == "Correos":
                    row.email = parse_field(row, fields, "CORREO", read_email)
                    row.primary = parse_field(row, fields, "Principal", read_primary)
                if "template_id" in fields:
                    template = parse_field(row, fields, "template_id")
                    workshop = parse_field(row, fields, "nombre_taller")
                    if template is not None and workshop is not None:
                        row.template = template, workshop
                if sheet == "Certificados":
                    row.role = parse_field(row, fields, "tipo_asistencia")
    return checksum, records


def group_by_document(rows):
    groups = defaultdict(list)
    for row in rows:
        if row.document is not None:
            groups[row.document].append(row)
    return groups


def validate(records):
    users = {}
    for document, rows in group_by_document(records["Usuarios"]).items():
        names = {row.name for row in rows if row.name is not None}
        if len(names) > 1:
            for row in rows:
                row.issues.append("identificación con nombres distintos en Usuarios")
        elif names:
            users[document] = next(iter(names))

    for sheet in ("Correos", "Certificados"):
        for row in records[sheet]:
            if row.document is not None and row.document not in users:
                row.issues.append("identificación sin coincidencia válida en Usuarios")

    templates = {row.template for row in records["Certificados"] if row.template is not None}
    for row in records["Templates"]:
        if row.template is not None and row.template not in templates:
            row.issues.append("combinación sin respaldo explícito en Certificados")

    emails = {}
    for document, rows in group_by_document(records["Correos"]).items():
        if document not in users:
            continue
        flags = defaultdict(set)
        for row in rows:
            if row.email is not None and row.primary is not None:
                flags[row.email].add(row.primary)
        primaries = {address for address, markers in flags.items() if True in markers}
        if any(len(markers) > 1 for markers in flags.values()):
            issue = "la misma dirección tiene marcas de principal contradictorias"
        elif any(row.primary is None or (row.primary and row.email is None) for row in rows):
            issue = "principal incierto por una fila inválida del grupo"
        elif len(primaries) != 1:
            issue = (
                "sin correo principal marcado"
                if not primaries
                else "más de un correo marcado como principal"
            )
        else:
            emails[document] = next(iter(primaries))
            continue
        for row in rows:
            if not row.issues:
                row.issues.append(issue)
    return users, templates, emails


def connect(path):
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute("PRAGMA foreign_keys = ON")
        if db.execute("PRAGMA foreign_keys").fetchone() != (1,):
            raise RuntimeError("No se pudieron activar las llaves foráneas.")
    except BaseException:
        db.close()
        raise
    return db


def schema_signature(db):
    return db.execute(
        "SELECT type, name, sql FROM sqlite_schema "
        "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
    ).fetchall()


def ensure_schema(db):
    # La primera sentencia de esquema activa las FK para uso directo del SQL.
    # Esta conexión ya las tiene activas antes de abrir la transacción.
    with closing(connect(":memory:")) as reference:
        reference.executescript(SCHEMA)
        expected = schema_signature(reference)
        app_id = reference.execute("PRAGMA application_id").fetchone()
        version = reference.execute("PRAGMA user_version").fetchone()
    actual = schema_signature(db)
    actual_app_id = db.execute("PRAGMA application_id").fetchone()
    actual_version = db.execute("PRAGMA user_version").fetchone()
    if not actual and actual_app_id == actual_version == (0,):
        # executescript() confirmaría una transacción abierta en sqlite3.
        statement = ""
        for line in SCHEMA.splitlines(keepends=True):
            statement += line
            if sqlite3.complete_statement(statement):
                db.execute(statement)
                statement = ""
        if statement.strip():
            raise RuntimeError("El esquema SQL contiene una sentencia incompleta.")
    elif (actual, actual_app_id, actual_version) != (expected, app_id, version):
        raise ImportValidationError("La base existente tiene un esquema ajeno o incompatible.")


def check_integrity(db):
    integrity = db.execute("PRAGMA integrity_check").fetchall()
    if integrity != [("ok",)] or db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise RuntimeError("Falló la comprobación de integridad de SQLite.")


def upsert_id(db, lookup, values, insert):
    found = db.execute(lookup, values).fetchone()
    if found is not None:
        return found[0]
    new_id = str(uuid4())
    db.execute(insert, (new_id, *values))
    return new_id


def load_users(db, records, users):
    identifiers = {}
    for document, name in users.items():
        current = db.execute(
            "SELECT id, nombre_completo FROM usuarios WHERE identificacion = ?", (document,)
        ).fetchone()
        if current is not None and current[1] != name:
            continue
        user_id = current[0] if current is not None else str(uuid4())
        if current is None:
            db.execute(
                "INSERT INTO usuarios (id, identificacion, nombre_completo) VALUES (?, ?, ?)",
                (user_id, document, name),
            )
        identifiers[document] = user_id

    for sheet in ("Usuarios", "Correos", "Certificados"):
        for row in records[sheet]:
            if row.document in users and row.document not in identifiers:
                row.issues.append("nombre en conflicto con el usuario existente")
            elif row.document in identifiers and (sheet != "Usuarios" or not row.issues):
                row.user_id = identifiers[row.document]


def load_emails(db, rows, primaries):
    for document, group in group_by_document(row for row in rows if not row.issues).items():
        user_id = group[0].user_id
        primary = primaries[document]
        current = db.execute(
            "SELECT c.direccion FROM usuarios u "
            "JOIN correos c ON c.id = u.correo_principal_id WHERE u.id = ?",
            (user_id,),
        ).fetchone()
        if current is not None and current[0].lower() != primary:
            for row in group:
                row.issues.append("principal en conflicto con el correo principal existente")
            continue
        primary_id = None
        for row in group:
            row.email_id = upsert_id(
                db,
                "SELECT id FROM correos WHERE usuario_id = ? AND direccion = ?",
                (user_id, row.email),
                "INSERT INTO correos (id, usuario_id, direccion) VALUES (?, ?, ?)",
            )
            if row.primary:
                primary_id = row.email_id
        if current is None:
            db.execute(
                "UPDATE usuarios SET correo_principal_id = ? WHERE id = ?", (primary_id, user_id)
            )


def load_records(db, records, users, templates, primaries):
    event_id = upsert_id(
        db,
        "SELECT id FROM evento_head WHERE codigo = ?",
        ("evento1",),
        "INSERT INTO evento_head (id, codigo, nombre) VALUES (?, ?, 'evento1')",
    )
    load_users(db, records, users)
    load_emails(db, records["Correos"], primaries)
    template_ids = {}
    for template in sorted(templates):
        template_ids[template] = upsert_id(
            db,
            "SELECT id FROM templates WHERE evento_id = ? AND template_id = ? "
            "AND nombre_taller = ?",
            (event_id, *template),
            "INSERT INTO templates (id, evento_id, template_id, nombre_taller) VALUES (?, ?, ?, ?)",
        )
    for sheet in ("Certificados", "Templates"):
        for row in records[sheet]:
            row.template_uuid = template_ids.get(row.template)
            if sheet == "Certificados" and not row.issues:
                row.certificate_id = upsert_id(
                    db,
                    "SELECT id FROM certificados WHERE usuario_id = ? AND evento_id = ? "
                    "AND template_uuid = ? AND tipo_asistencia = ?",
                    (row.user_id, event_id, row.template_uuid, row.role),
                    "INSERT INTO certificados (id, usuario_id, evento_id, template_uuid, "
                    "tipo_asistencia) VALUES (?, ?, ?, ?, ?)",
                )


def import_workbook(excel, database):
    checksum, records = read_workbook(excel)
    users, templates, primaries = validate(records)
    if not users:
        raise ImportValidationError(
            "Usuarios no contiene identificaciones con un nombre válido y único."
        )
    with closing(connect(database)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            ensure_schema(db)
            check_integrity(db)
            repeated = (
                db.execute("SELECT 1 FROM importaciones WHERE sha256 = ?", (checksum,)).fetchone()
                is not None
            )
            if not repeated:
                db.execute(
                    "INSERT INTO importaciones (sha256, archivo) VALUES (?, ?)",
                    (checksum, excel.name),
                )
                load_records(db, records, users, templates, primaries)
                db.executemany(
                    "INSERT INTO importacion_filas (sha256, hoja, fila, motivo, usuario_id, "
                    "correo_id, template_uuid, certificado_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        (
                            checksum,
                            row.sheet,
                            row.number,
                            " | ".join(row.issues) or None,
                            row.user_id,
                            row.email_id,
                            row.template_uuid,
                            row.certificate_id,
                        )
                        for rows in records.values()
                        for row in rows
                    ),
                )
                check_integrity(db)
            counts = {
                table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in TABLES
            }
            pending = db.execute(
                "SELECT hoja, fila, motivo FROM importacion_filas "
                "WHERE sha256 = ? AND motivo IS NOT NULL ORDER BY hoja, fila",
                (checksum,),
            ).fetchall()
            db.commit()
        except BaseException:
            db.rollback()
            raise
    return checksum, repeated, counts, pending


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("excel", type=Path)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    args = parser.parse_args()

    try:
        checksum, repeated, counts, pending = import_workbook(args.excel, args.db)
    except ImportValidationError as error:
        parser.exit(1, f"{error}\n")
    except (
        OSError,
        BadZipFile,
        InvalidFileException,
        sqlite3.Error,
        RuntimeError,
        ValueError,
    ) as error:
        # Evita que una excepción de lectura o SQL incluya valores del libro.
        parser.exit(1, f"No se completó la importación ({type(error).__name__}).\n")

    print(f"SHA-256 {checksum}")
    print("Archivo ya importado. Base sin cambios." if repeated else "Importación confirmada.")
    for table, total in counts.items():
        print(f"{table} {total}")
    sheets = Counter(sheet for sheet, _, _ in pending)
    print(f"Filas pendientes {len(pending)}")
    for sheet, total in sorted(sheets.items()):
        print(f"{sheet} {total}")
    for sheet, number, reason in pending:
        print(f"{sheet} fila {number} — {reason}")


if __name__ == "__main__":
    sys.exit(main())
