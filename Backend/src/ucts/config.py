from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)
    app_env: Literal["local", "production"] = "local"
    database_url: str
    otp_secret: str = Field(min_length=32, repr=False)
    auth_mode: Literal["local", "cognito"] = "cognito"
    cookie_secure: bool = True
    allowed_origins: list[str] = ["http://localhost:4200", "http://localhost:8000"]
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    aws_region: str = "us-east-1"
    certificate_s3_bucket: str = Field(
        default="", pattern=r"^(?:[a-z0-9][a-z0-9.-]{1,61}[a-z0-9])?$"
    )
    certificate_catalog_sqlite: Path | None = None
    certificate_generator_enabled: bool = False
    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    cognito_client_secret: str = Field(default="", repr=False)
    otp_ttl_seconds: int = Field(default=180, ge=60, le=180)
    otp_resend_seconds: int = Field(default=60, ge=30, le=300)
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)

    @model_validator(mode="after")
    def validate_security(self) -> "Settings":
        if self.auth_mode == "cognito" and not self.cognito_client_id:
            raise ValueError("COGNITO_CLIENT_ID es obligatorio en modo cognito")
        if self.certificate_generator_enabled and not self.certificate_catalog_sqlite:
            raise ValueError("CERTIFICATE_GENERATOR_ENABLED requiere CERTIFICATE_CATALOG_SQLITE")
        if self.certificate_catalog_sqlite:
            if self.auth_mode != "cognito" or not self.cognito_client_secret:
                raise ValueError("El catálogo SQLite requiere Cognito con app client confidencial")
        if self.cognito_user_pool_id and (
            "_" not in self.cognito_user_pool_id
            or self.cognito_user_pool_id.split("_", 1)[0] != self.aws_region
        ):
            raise ValueError("COGNITO_USER_POOL_ID debe corresponder a AWS_REGION")
        if self.app_env == "production":
            if self.certificate_catalog_sqlite and not self.cognito_user_pool_id:
                raise ValueError(
                    "COGNITO_USER_POOL_ID es obligatorio para el catálogo en producción"
                )
            if self.auth_mode != "cognito" or not self.cookie_secure:
                raise ValueError("Producción requiere Cognito y cookies Secure")
            if self.otp_secret.startswith("change-"):
                raise ValueError("Configura un OTP_SECRET de producción")
            if any(not origin.startswith("https://") for origin in self.allowed_origins):
                raise ValueError("Los orígenes de producción deben usar HTTPS")
        return self
