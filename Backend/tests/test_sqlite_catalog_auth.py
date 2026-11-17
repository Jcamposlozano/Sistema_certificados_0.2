import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ucts.adapters.documents.certificate_service import CertificateServiceGenerator
from ucts.adapters.persistence.sqlite_catalog import initialize_auth_tables
from ucts.domain.models import Identity
from ucts.main import create_app

ORIGIN = {"Origin": "http://localhost:4200"}


@dataclass
class Provider:
    requests: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    subject: str = "cognito-synthetic-subject"

    def request(self, email, participant_id, expected_subject=None):
        self.requests.append(email)
        return "challenge-state"

    def verify(self, email, state, code):
        assert (state, code) == ("challenge-state", "654321")
        self.checks.append(email)
        return Identity(self.subject, email)


@pytest.fixture
def catalog(tmp_path, settings, request):
    path = tmp_path / "catalog.sqlite"
    auth_url = f"sqlite:///{tmp_path / 'auth.sqlite'}"
    first, second, third, event, template, first_cert, other_cert = (str(uuid4()) for _ in range(7))
    primary, secondary, shared, shared_other = (str(uuid4()) for _ in range(4))
    with closing(sqlite3.connect(path)) as db:
        schema = Path(__file__).parents[1] / "sqlite" / "esquema.sql"
        db.executescript(schema.read_text())
        db.execute("INSERT INTO evento_head VALUES (?, 'evento1', 'evento1')", (event,))
        db.execute("INSERT INTO templates VALUES (?, ?, 'proveedor', 'Taller')", (template, event))
        for user_id, number, email_id in (
            (first, "0001", primary),
            (second, "0002", shared),
            (third, "0003", shared_other),
        ):
            db.execute(
                "INSERT INTO usuarios (id, identificacion, nombre_completo, correo_principal_id) "
                "VALUES (?, ?, 'Participante sintético', ?)",
                (user_id, number, email_id),
            )
        db.executemany(
            "INSERT INTO correos (id, usuario_id, direccion) VALUES (?, ?, ?)",
            [
                (primary, first, "principal@example.org"),
                (secondary, first, "secundario@example.org"),
                (shared, second, "compartido@example.org"),
                (shared_other, third, "compartido@example.org"),
            ],
        )
        db.executemany(
            "INSERT INTO certificados VALUES (?, ?, ?, ?, 'Asistente')",
            [(first_cert, first, event, template), (other_cert, second, event, template)],
        )
        db.commit()

    config = settings.model_copy(
        update={
            "auth_mode": "cognito",
            "database_url": auth_url,
            "certificate_catalog_sqlite": path,
            "cognito_client_id": "synthetic-client",
            "cognito_client_secret": "synthetic-secret",
        }
    )
    engine = create_engine(auth_url)
    initialize_auth_tables(engine)
    provider = Provider()
    generator = None
    if getattr(request, "param", False):
        generator = CertificateServiceGenerator(TemplateService(), "ucts")
    app = create_app(config, engine=engine, provider=provider, certificate_generator=generator)
    with TestClient(app) as client:
        yield client, provider, path, secondary, first_cert, other_cert


def request_otp(client, email):
    response = client.post("/api/auth/otp/request", headers=ORIGIN, json={"email": email})
    assert response.status_code == 200
    return response.json()["challengeId"]


def verify(client, challenge):
    return client.post(
        "/api/auth/otp/verify", headers=ORIGIN, json={"challengeId": challenge, "code": "654321"}
    )


def test_principal_unico_verifica_identidad_y_limita_certificados(catalog):
    client, provider, path, _, first_cert, other_cert = catalog
    original = path.read_bytes()
    assert client.get("/health/ready").status_code == 200
    for email in ("secundario@example.org", "compartido@example.org", "ajeno@example.org"):
        assert verify(client, request_otp(client, email)).status_code == 401
    assert provider.requests == provider.checks == []

    challenge = request_otp(client, "Principal@example.org")
    assert client.get("/api/me").status_code == 401
    response = verify(client, challenge)
    assert response.status_code == 204
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    assert provider.requests == provider.checks == ["principal@example.org"]
    assert verify(client, challenge).status_code == 401
    assert client.get("/api/me").json()["email"] == "principal@example.org"
    certificates = client.get("/api/me/certificates").json()
    assert [(row["id"], row["available"]) for row in certificates] == [(first_cert, False)]
    assert client.get(f"/api/me/certificates/{other_cert}").status_code == 404
    assert client.get(f"/api/me/certificates/{first_cert}").status_code == 403
    assert client.post("/api/auth/logout", headers=ORIGIN).status_code == 204
    assert client.get("/api/me").status_code == 401
    assert path.read_bytes() == original


def test_cambio_de_principal_revoca_acceso_y_conserva_vinculo_cognito(catalog):
    client, provider, path, secondary, *_ = catalog
    assert verify(client, request_otp(client, "principal@example.org")).status_code == 204
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("PRAGMA foreign_keys = ON")
        db.execute(
            "UPDATE usuarios SET correo_principal_id = ? WHERE identificacion = '0001'",
            (secondary,),
        )
    assert client.get("/api/me").status_code == 401
    provider.subject = "different-cognito-subject"
    response = verify(client, request_otp(client, "secundario@example.org"))
    assert response.status_code == 401
    assert client.get("/api/me").status_code == 401


class TemplateService:
    def __init__(self):
        self.template_repository = self
        self.invalid_pdf = False

    def get_template_config(self, institution_id, template_id):
        assert (institution_id, template_id) == ("ucts", "proveedor")
        return {"required_fields": ["nombre", "identificacion", "tipo_asistencia", "nombre_taller"]}

    def generate_pdf(self, *, institution_id, template_id, request_data):
        assert (institution_id, template_id) == ("ucts", "proveedor")
        assert request_data == {
            "nombre": "Participante sintético",
            "identificacion": "0001",
            "tipo_asistencia": "Asistente",
            "nombre_taller": "Taller",
        }
        return b"invalid" if self.invalid_pdf else b"%PDF-1.4 synthetic"


@pytest.mark.parametrize("catalog", [True], indirect=True)
def test_downloads_use_authenticated_catalog_and_record_audit(catalog):
    client, _, path, _, first_cert, other_cert = catalog
    target = f"/api/me/certificates/{first_cert}"
    assert client.get(target).status_code == 401
    assert verify(client, request_otp(client, "principal@example.org")).status_code == 204
    me = client.get("/api/me").json()["id"]
    listing = client.get("/api/me/certificates").json()
    assert listing[0]["available"] is True
    assert client.get(f"/api/me/certificates/{other_cert}").status_code == 404

    generator = client.app.state.certificates.generator.service
    generator.invalid_pdf = True
    assert client.get(target).status_code == 503
    generator.invalid_pdf = False

    start = datetime.now(UTC).replace(microsecond=0)
    for _ in range(2):
        response = client.get(target)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == b"%PDF-1.4 synthetic"

    with closing(sqlite3.connect(path.parent / "auth.sqlite")) as db:
        entries = db.execute(
            "SELECT participant_id, certificate_id, event_id, downloaded_at_utc "
            "FROM certificate_downloads ORDER BY downloaded_at_utc"
        ).fetchall()
    assert len(entries) == 2
    for participant_id, certificate_id, event_id, timestamp in entries:
        assert (participant_id, certificate_id, event_id) == (me, first_cert, listing[0]["eventId"])
        assert start <= datetime.fromisoformat(timestamp) <= datetime.now(UTC)
