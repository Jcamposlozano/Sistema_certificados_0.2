import sqlite3
from contextlib import closing
from pathlib import Path

from sqlalchemy import delete, event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import IntegrityError

from ucts.adapters.persistence.models import (
    Base,
    CertificateDownloadRow,
    ChallengeRow,
    ParticipantRow,
    RateRow,
    SessionRow,
)
from ucts.adapters.persistence.repository import SqlRepository
from ucts.domain.models import (
    AppError,
    Certificate,
    CertificateGeneration,
    ErrorKind,
    Identity,
    Participant,
)


class SqliteCatalogRepository(SqlRepository):
    """Lee el catálogo importado y guarda estado de autenticación en otra base."""

    def __init__(self, db, *, catalog: Path):
        super().__init__(db)
        self.catalog = catalog

    @staticmethod
    def read(catalog: Path, sql: str, parameters=()):
        try:
            with closing(sqlite3.connect(f"{catalog.as_uri()}?mode=ro", uri=True)) as db:
                db.execute("PRAGMA foreign_keys = ON")
                return db.execute(sql, parameters).fetchall()
        except sqlite3.Error:
            raise AppError(
                ErrorKind.UNAVAILABLE, "Catálogo de participantes no disponible."
            ) from None

    def check_catalog(self):
        self.read(
            self.catalog,
            "SELECT usuario_id, direccion, principal FROM correos_con_principal LIMIT 0",
        )
        self.read(
            self.catalog, "SELECT certificado_id, usuario_id FROM certificados_detalle LIMIT 0"
        )

    @staticmethod
    def unique_principal(catalog: Path, email: str) -> Participant | None:
        rows = SqliteCatalogRepository.read(
            catalog,
            "SELECT usuario_id, nombre_completo, direccion FROM correos_con_principal "
            "WHERE principal = 1 AND direccion = ? COLLATE NOCASE LIMIT 2",
            (email,),
        )
        # Una dirección compartida por dos titulares no identifica a uno de ellos.
        return Participant(*rows[0]) if len(rows) == 1 else None

    def _principal(self, email: str) -> Participant | None:
        return self.unique_principal(self.catalog, email)

    def auth_target(self, email: str) -> str | None:
        principal = self._principal(email)
        return principal.id if principal else None

    def participant(self, participant_id: str) -> Participant | None:
        row = self.db.get(ParticipantRow, participant_id)
        if row is None or not row.enabled:
            return None
        principal = self._principal(row.email)
        return principal if principal and principal.id == row.id else None

    def bind_identity(
        self, identity: Identity, participant_id: str, *, persist_subject: bool
    ) -> Participant:
        principal = self._principal(identity.email)
        if principal is None or principal.id != participant_id:
            raise AppError(ErrorKind.UNAUTHORIZED, "No fue posible asociar la identidad.")
        binding = self.db.get(ParticipantRow, principal.id, with_for_update=True)
        if binding is not None and (
            not binding.enabled or (binding.subject and binding.subject != identity.subject)
        ):
            raise AppError(ErrorKind.UNAUTHORIZED, "No fue posible asociar la identidad.")
        try:
            with self.db.begin_nested():
                if binding is None:
                    binding = ParticipantRow(id=principal.id)
                    self.db.add(binding)
                if binding.email and binding.email != principal.email:
                    # Invalida las sesiones emitidas para el correo anterior.
                    self.db.execute(
                        delete(SessionRow).where(SessionRow.participant_id == principal.id)
                    )
                binding.email = principal.email
                binding.name = principal.name
                binding.subject = identity.subject if persist_subject else None
                self.db.flush()
        except IntegrityError:
            raise AppError(ErrorKind.UNAUTHORIZED, "No fue posible asociar la identidad.") from None
        return principal

    def certificates(self, participant_id: str) -> list[Certificate]:
        return self._certificates_for(participant_id)

    def certificate(self, participant_id: str, certificate_id: str) -> Certificate | None:
        results = self._certificates_for(participant_id, certificate_id)
        return results[0] if results else None

    def _certificates_for(
        self, participant_id: str, certificate_id: str | None = None
    ) -> list[Certificate]:
        rows = self.read(
            self.catalog,
            "SELECT certificado_id, evento_id, nombre_taller, evento_nombre, tipo_asistencia, "
            "template_id, nombre_completo, identificacion "
            "FROM certificados_detalle WHERE usuario_id = ? "
            "AND (? IS NULL OR certificado_id = ?) ORDER BY nombre_taller, certificado_id",
            (participant_id, certificate_id, certificate_id),
        )
        certificates = []
        for row in rows:
            certificate_id, event_id, title, category, role, template_id, name, identification = row
            certificates.append(
                Certificate(
                    certificate_id, event_id, title, category, role, "pending", None, None, None,
                    CertificateGeneration(template_id, name, identification),
                )
            )
        return certificates

    def challenge(self, challenge_id: str):
        if self.db.get_bind().dialect.name == "sqlite":
            self.db.connection().exec_driver_sql("BEGIN IMMEDIATE")
        return super().challenge(challenge_id)

    # Las asociaciones de SQLite se muestran en /me/certificates.
    def events(self, participant_id: str):
        return []

    def event(self, participant_id: str, event_id: str):
        return None


def catalog_path(database_url: str, catalog: Path) -> Path:
    catalog = catalog.resolve(strict=True)
    auth_url = make_url(database_url)
    if auth_url.get_backend_name() == "sqlite" and auth_url.query.get("uri") == "true":
        raise ValueError("Usa una ruta SQLite directa para el estado de autenticación.")
    if auth_url.get_backend_name() == "sqlite" and auth_url.database not in (None, ":memory:"):
        auth_file = Path(auth_url.database).resolve()
        if auth_file == catalog or (auth_file.exists() and auth_file.samefile(catalog)):
            raise ValueError("Usa un archivo SQLite separado para el estado de autenticación.")
    return catalog


def enable_sqlite_foreign_keys(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def on_connect(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys = ON")


def initialize_auth_tables(engine: Engine) -> None:
    models = (ParticipantRow, ChallengeRow, SessionRow, RateRow, CertificateDownloadRow)
    tables = [model.__table__ for model in models]
    Base.metadata.create_all(engine, tables=tables)
