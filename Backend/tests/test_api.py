import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from ucts.adapters.persistence.models import (
    ChallengeRow,
    ParticipantRow,
    RateRow,
    SessionRow,
)
from ucts.application.services import token_hash

from .conftest import ORIGIN, login, request_code


def test_authenticated_events_and_pdf(client, seeded, caplog):
    assert client.get("/api/me/events").status_code == 401
    response = login(client, caplog)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie and "Path=/api" in cookie
    assert client.get("/api/me").json()["name"] == "Ana Pérez"
    events = client.get("/api/me/events").json()
    assert [event["id"] for event in events] == ["pending", "available"]
    assert events[1]["date"] == "2026-10-18"
    pdf = client.get("/api/me/events/available/certificate")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"] == "no-store"
    assert "attachment" in pdf.headers["content-disposition"]
    assert pdf.content.startswith(b"%PDF-") and pdf.content.rstrip().endswith(b"%%EOF")
    assert client.get("/api/me/events/pending/certificate").status_code == 403
    assert client.get("/api/me/events/other/certificate").status_code == 404
    assert client.post("/api/auth/logout", headers=ORIGIN).status_code == 204
    assert client.get("/api/me/events").status_code == 401


def test_otp_is_single_use_and_sessions_are_hashed(client, engine, caplog):
    challenge, code = request_code(client, caplog)
    data = {"challengeId": challenge, "code": code}
    response = client.post("/api/auth/otp/verify", json=data, headers=ORIGIN)
    assert response.status_code == 204
    token = client.cookies.get("ucts_session")
    with Session(engine) as db:
        row = db.scalar(select(SessionRow))
        assert row.token_hash == token_hash(token)
        state = db.get(ChallengeRow, challenge).provider_state
        assert code not in state
    assert client.post("/api/auth/otp/verify", json=data, headers=ORIGIN).status_code == 401
    assert client.post("/api/auth/logout", headers=ORIGIN).status_code == 204
    # Server revocation still holds if a client replays the old cookie.
    assert client.get("/api/me", headers={"Cookie": f"ucts_session={token}"}).status_code == 401


def test_wrong_code_locks_challenge_after_five_attempts(client, caplog):
    challenge, code = request_code(client, caplog)
    wrong = "000001" if code == "000000" else "000000"
    for _ in range(5):
        assert (
            client.post(
                "/api/auth/otp/verify",
                headers=ORIGIN,
                json={"challengeId": challenge, "code": wrong},
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/auth/otp/verify", headers=ORIGIN, json={"challengeId": challenge, "code": code}
        ).status_code
        == 401
    )


def test_expired_otp_and_session(client, caplog, engine):
    challenge, code = request_code(client, caplog)
    with Session(engine) as db:
        db.get(ChallengeRow, challenge).expires_at = int(time.time()) - 1
        db.commit()
    assert (
        client.post(
            "/api/auth/otp/verify", headers=ORIGIN, json={"challengeId": challenge, "code": code}
        ).status_code
        == 401
    )
    with Session(engine) as db:
        for row in db.scalars(select(RateRow)):
            row.expires_at = int(time.time()) - 1
        db.commit()
    login(client, caplog)
    with Session(engine) as db:
        row = db.scalar(select(SessionRow))
        row.expires_at = int(time.time()) - 1
        db.commit()
    assert client.get("/api/me").status_code == 401


def test_resend_throttle_and_old_challenge_invalidation(client, caplog, engine):
    old_challenge, old_code = request_code(client, caplog)
    response = client.post(
        "/api/auth/otp/request", json={"email": "ana@example.com"}, headers=ORIGIN
    )
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    with Session(engine) as db:
        for row in db.scalars(select(RateRow)):
            row.expires_at = int(time.time()) - 1
        db.commit()
    new_challenge, new_code = request_code(client, caplog)
    assert new_challenge != old_challenge
    assert (
        client.post(
            "/api/auth/otp/verify",
            headers=ORIGIN,
            json={"challengeId": old_challenge, "code": old_code},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/otp/verify",
            headers=ORIGIN,
            json={"challengeId": new_challenge, "code": new_code},
        ).status_code
        == 204
    )


def test_origin_and_validation(client):
    assert (
        client.post("/api/auth/otp/request", json={"email": "ana@example.com"}).status_code == 403
    )
    assert (
        client.post(
            "/api/auth/otp/request",
            json={"email": "ana@example.com"},
            headers={"Origin": "https://evil.example"},
        ).status_code
        == 403
    )
    assert (
        client.post("/api/auth/otp/request", json={"email": "invalid"}, headers=ORIGIN).status_code
        == 422
    )
    assert client.post("/api/auth/logout", headers={"Origin": "null"}).status_code == 403
    assert client.get("/api/me", headers={"Host": "evil.example"}).status_code == 400


def test_unlisted_email_never_gets_a_challenge(client, engine, caplog):
    response = client.post(
        "/api/auth/otp/request", json={"email": "new@example.com"}, headers=ORIGIN
    )
    assert response.status_code == 200
    assert "OTP para" not in caplog.text
    assert (
        client.post(
            "/api/auth/otp/verify",
            headers=ORIGIN,
            json={"challengeId": response.json()["challengeId"], "code": "123456"},
        ).status_code
        == 401
    )
    with Session(engine) as db:
        assert db.scalar(select(ChallengeRow)) is None
        assert (
            db.scalar(select(ParticipantRow).where(ParticipantRow.email == "new@example.com"))
            is None
        )


def test_disabled_participant_loses_session(client, engine, seeded, caplog):
    login(client, caplog)
    with Session(engine) as db:
        db.get(ParticipantRow, seeded).enabled = False
        db.commit()
    assert client.get("/api/me").status_code == 401


def test_health_and_cors(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200
    response = client.options(
        "/api/me/events", headers={**ORIGIN, "Access-Control-Request-Method": "GET"}
    )
    assert response.headers["access-control-allow-origin"] == ORIGIN["Origin"]
    assert response.headers["access-control-allow-credentials"] == "true"


def test_parallel_verification_consumes_code_once(client, engine, caplog):
    if engine.dialect.name != "postgresql":
        pytest.skip("Row locking requires PostgreSQL")
    challenge, code = request_code(client, caplog)

    def verify(_):
        return client.post(
            "/api/auth/otp/verify", headers=ORIGIN, json={"challengeId": challenge, "code": code}
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(verify, range(2))) == [204, 401]
