import argparse
import hashlib
import time
from datetime import date
from getpass import getpass
from pathlib import Path
from uuid import uuid4
from zipfile import BadZipFile

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import create_engine, delete, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ucts.adapters.documents.s3 import S3CertificateStore
from ucts.adapters.identity.cognito import CognitoUserPool
from ucts.adapters.persistence.certificate_import import import_certificates, read_workbook
from ucts.adapters.persistence.certificate_publish import publish_certificates
from ucts.adapters.persistence.models import (
    AttendanceRow,
    ChallengeRow,
    EventRow,
    ParticipantRow,
    RateRow,
    SessionRow,
)
from ucts.adapters.persistence.sqlite_catalog import (
    SqliteCatalogRepository,
    catalog_path,
    enable_sqlite_foreign_keys,
    initialize_auth_tables,
)
from ucts.config import Settings
from ucts.domain.models import AppError


def main():
    parser = argparse.ArgumentParser(description="Administración local UCTS")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed")
    commands.add_parser("cleanup")
    commands.add_parser("init-catalog-auth", help="Preparar SQLite para sesiones del catálogo")
    provision = commands.add_parser(
        "provision-cognito-user", help="Dar de alta un correo principal sin enviar invitación"
    )
    provision.add_argument("--pool-id", help="Alternativa a COGNITO_USER_POOL_ID")
    load = commands.add_parser("import-certificates", help="Importar el Excel de certificados")
    load.add_argument("--dry-run", action="store_true")
    load.add_argument("--workbook", type=Path, default=Path("data/raw/Datos.xlsx"))
    publish = commands.add_parser("publish-certificates", help="Vincular PDFs existentes en S3")
    publish.add_argument("--workbook", type=Path, default=Path("data/raw/Datos.xlsx"))
    publish.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    try:
        if args.command == "import-certificates":
            checksum, records, issues = read_workbook(args.workbook)
            certificates = {source.certificate_id(source.email) for source in records}
            print(
                f"SHA-256: {checksum}\nFilas válidas: {len(records)} · "
                f"Correos: {len({r.email for r in records})} · "
                f"Actividades: {len({r.event_id for r in records})} · "
                f"Certificados distintos: {len(certificates)} · Filas excluidas: {len(issues)}"
            )
            for issue in issues:
                print(issue)
            if args.dry_run:
                return
        elif args.command == "publish-certificates":
            checksum = hashlib.sha256(args.workbook.read_bytes()).hexdigest()
    except (ValueError, OSError, BadZipFile, InvalidFileException) as error:
        parser.error(str(error))

    settings = Settings()
    if args.command == "provision-cognito-user":
        if not settings.certificate_catalog_sqlite:
            parser.error("Configura CERTIFICATE_CATALOG_SQLITE.")
        pool_id = settings.cognito_user_pool_id or args.pool_id
        if not pool_id or not pool_id.startswith(f"{settings.aws_region}_"):
            parser.error("Configura COGNITO_USER_POOL_ID para AWS_REGION.")
        if args.pool_id and args.pool_id != pool_id:
            parser.error("--pool-id debe coincidir con COGNITO_USER_POOL_ID.")
        email = getpass("Correo principal a aprovisionar: ").strip().lower()
        try:
            catalog = catalog_path(settings.database_url, settings.certificate_catalog_sqlite)
            participant = SqliteCatalogRepository.unique_principal(catalog, email)
            if participant is None:
                parser.error("El correo no es principal de un único participante.")
            engine = create_engine(settings.database_url, hide_parameters=True)
            try:
                with Session(engine) as db:
                    subject = SqliteCatalogRepository(db, catalog=catalog).bound_subject(
                        participant.id
                    )
            finally:
                engine.dispose()
            cognito = boto3.client("cognito-idp", region_name=settings.aws_region)
            pool = CognitoUserPool(cognito, pool_id)
            if pool.ensure_user(email, expected_subject=subject) is None:
                parser.error("La cuenta de Cognito requiere revisión antes de iniciar sesión.")
        except (AppError, BotoCoreError, OSError, SQLAlchemyError, ValueError) as error:
            parser.error(f"No se pudo aprovisionar la cuenta ({type(error).__name__}).")
        print("Cuenta comprobada en Cognito. Solicita el código desde el portal.")
        return

    engine = create_engine(settings.database_url, hide_parameters=True)
    if settings.certificate_catalog_sqlite:
        try:
            catalog_path(settings.database_url, settings.certificate_catalog_sqlite)
        except (OSError, ValueError) as error:
            parser.error(str(error))
        if args.command in {"seed", "import-certificates", "publish-certificates"}:
            parser.error("Ese comando se ejecuta con el backend de certificados anterior.")
    if args.command == "init-catalog-auth":
        if not settings.certificate_catalog_sqlite or engine.dialect.name != "sqlite":
            parser.error("Configura CERTIFICATE_CATALOG_SQLITE y un DATABASE_URL SQLite separado.")
        enable_sqlite_foreign_keys(engine)
        initialize_auth_tables(engine)
        print("Tablas de autenticación preparadas.")
        engine.dispose()
        return
    if args.command == "import-certificates":
        with Session(engine) as db, db.begin():
            imported = import_certificates(db, checksum, records)
        print("Importación confirmada." if imported else "El libro ya está registrado.")
        engine.dispose()
        return
    if args.command == "publish-certificates":
        if not settings.certificate_s3_bucket:
            parser.error("Configura CERTIFICATE_S3_BUCKET.")
        store = S3CertificateStore(
            boto3.client(
                "s3",
                region_name=settings.aws_region,
                config=Config(connect_timeout=5, read_timeout=15),
            ),
            settings.certificate_s3_bucket,
        )
        try:
            with Session(engine) as db, db.begin():
                count = publish_certificates(
                    db, checksum, args.manifest, store.bucket, store.inspect
                )
        except (ValueError, OSError) as error:
            parser.error(str(error))
        finally:
            engine.dispose()
        print(f"Certificados publicados: {count}.")
        return

    with Session(engine) as db:
        if args.command == "cleanup":
            now = int(time.time())
            for model in (ChallengeRow, SessionRow, RateRow):
                db.execute(delete(model).where(model.expires_at <= now))
            print("Registros de autenticación vencidos eliminados.")
        else:
            if settings.app_env != "local" or settings.auth_mode != "local":
                parser.error("El seed solo se permite en entorno local y AUTH_MODE=local.")
            email = "demo@example.com"
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
