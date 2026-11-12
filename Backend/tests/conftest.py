import logging
import os
import re
from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from ucts.adapters.persistence.models import AttendanceRow, Base, EventRow, ParticipantRow
from ucts.config import Settings
from ucts.main import create_app


@pytest.fixture
def engine():
    # Set TEST_DATABASE_URL for a dedicated PostgreSQL test database.
    url = os.environ.get("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    if not url.startswith("sqlite") and not url.rsplit("/", 1)[-1].startswith("ucts_zone_test"):
        raise ValueError("TEST_DATABASE_URL debe apuntar a una base exclusiva ucts_zone_test*")
    options = (
        {"connect_args": {"check_same_thread": False}, "poolclass": StaticPool}
        if url.startswith("sqlite")
        else {}
    )
    engine = create_engine(url, **options)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        database_url="sqlite+pysqlite:///:memory:",
        otp_secret="test-secret-long-enough-for-validation",
        auth_mode="local",
        cookie_secure=False,
        allowed_hosts=["testserver"],
        allowed_origins=["http://localhost:4200"],
    )


@pytest.fixture
def client(engine, settings):
    with TestClient(create_app(settings, engine=engine)) as client:
        yield client


@pytest.fixture
def seeded(engine):
    participant_id = str(uuid4())
    with Session(engine) as db:
        db.add(ParticipantRow(id=participant_id, name="Ana Pérez", email="ana@example.com"))
        db.add(
            EventRow(
                id="available",
                title="Tecnología e innovación",
                category="Taller",
                date=date(2026, 10, 18),
                hours=4,
            )
        )
        db.add(
            EventRow(
                id="pending",
                title="Investigación",
                category="Jornada",
                date=date(2026, 11, 5),
                hours=6,
            )
        )
        db.add(
            EventRow(
                id="other",
                title="Evento de otro usuario",
                category="Taller",
                date=date(2026, 9, 1),
                hours=2,
            )
        )
        db.flush()
        db.add(AttendanceRow(participant_id=participant_id, event_id="available", available=True))
        db.add(AttendanceRow(participant_id=participant_id, event_id="pending", available=False))
        db.commit()
    return participant_id


ORIGIN = {"Origin": "http://localhost:4200"}


def request_code(client, caplog, email="ana@example.com"):
    with caplog.at_level(logging.WARNING, logger="ucts.local_otp"):
        response = client.post("/api/auth/otp/request", json={"email": email}, headers=ORIGIN)
    assert response.status_code == 200, response.text
    code = re.findall(r"OTP para [^:]+: (\d{6})", caplog.text)[-1]
    return response.json()["challengeId"], code


def login(client, caplog, email="ana@example.com"):
    challenge, code = request_code(client, caplog, email)
    response = client.post(
        "/api/auth/otp/verify", json={"challengeId": challenge, "code": code}, headers=ORIGIN
    )
    assert response.status_code == 204, response.text
    return response
