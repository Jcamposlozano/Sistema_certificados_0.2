import json

from fastapi.testclient import TestClient

from ucts.config import Settings
from ucts.main import create_app


def test_production_trusted_hosts_preserve_health_and_api_routes(engine, monkeypatch):
    monkeypatch.setenv(
        "ALLOWED_HOSTS",
        json.dumps(["uctszone.net", "api.uctszone.net", "127.0.0.1", "localhost", "backend"]),
    )
    settings = Settings(
        _env_file=None,
        app_env="production",
        database_url="sqlite://",
        otp_secret="synthetic-otp-secret-for-host-validation",
        auth_mode="cognito",
        cognito_client_id="synthetic-app-client",
        cookie_secure=True,
        allowed_origins=["https://uctszone.net"],
        certificate_catalog_sqlite=None,
        certificate_s3_bucket="",
    )
    with TestClient(create_app(settings, engine=engine, provider=object())) as client:
        for host in settings.allowed_hosts:
            response = client.get("/health/ready", headers={"Host": host})
            assert response.status_code == 200
            assert response.json() == {"status": "ok"}

        unknown_host = {"Host": "desconocido.invalid"}
        assert client.get("/health/ready", headers=unknown_host).status_code == 400
        assert client.get("/api/me", headers=unknown_host).status_code == 400

        public_host = {"Host": "api.uctszone.net"}
        assert client.get("/health/live", headers=public_host).status_code == 200
        assert client.get("/api/me", headers=public_host).status_code == 401
        assert client.get("/api/me/certificates", headers=public_host).status_code == 401
        assert client.get("/api/health/ready", headers=public_host).status_code == 404
        assert client.get("/me", headers=public_host).status_code == 404

        otp_path = "/api/auth/otp/request"
        allowed_origin = {**public_host, "Origin": "https://uctszone.net"}
        unknown_origin = {**public_host, "Origin": "https://desconocido.invalid"}
        assert client.post(otp_path, headers=allowed_origin, json={}).status_code == 422
        assert client.post(otp_path, headers=unknown_origin, json={}).status_code == 403
