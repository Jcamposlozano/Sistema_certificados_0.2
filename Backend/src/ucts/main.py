from contextlib import asynccontextmanager
from functools import partial

import boto3
from botocore import UNSIGNED
from botocore.config import Config
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ucts.adapters.documents.certificate_service import CertificateServiceGenerator
from ucts.adapters.documents.pdf import PdfCertificateRenderer
from ucts.adapters.documents.s3 import S3CertificateStore
from ucts.adapters.http.api import router
from ucts.adapters.identity.cognito import CognitoIdentityProvider, CognitoUserPool
from ucts.adapters.identity.local import LocalIdentityProvider
from ucts.adapters.persistence.repository import SqlUnitOfWork
from ucts.adapters.persistence.sqlite_catalog import (
    SqliteCatalogRepository,
    catalog_path,
    enable_sqlite_foreign_keys,
)
from ucts.application.services import AuthService, CertificateService
from ucts.config import Settings
from ucts.domain.models import AppError, ErrorKind


def create_app(
    settings: Settings | None = None,
    *,
    engine=None,
    provider=None,
    certificate_store=None,
    certificate_generator=None,
) -> FastAPI:
    settings = settings or Settings()
    catalog = None
    if settings.certificate_catalog_sqlite:
        catalog = catalog_path(settings.database_url, settings.certificate_catalog_sqlite)
    engine = (
        engine
        if engine is not None
        else create_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    )
    factory = sessionmaker(engine, expire_on_commit=False)
    if catalog:
        if engine.dialect.name == "sqlite":
            enable_sqlite_foreign_keys(engine)
        uow = partial(SqlUnitOfWork, factory, partial(SqliteCatalogRepository, catalog=catalog))
    else:
        uow = partial(SqlUnitOfWork, factory)
    if provider is None:
        if settings.auth_mode == "local":
            provider = LocalIdentityProvider(settings.otp_secret)
        else:
            user_pool = None
            if catalog and settings.cognito_user_pool_id:
                user_pool = CognitoUserPool(
                    boto3.client(
                        "cognito-idp",
                        region_name=settings.aws_region,
                        config=Config(
                            connect_timeout=5, read_timeout=10, retries={"max_attempts": 0}
                        ),
                    ),
                    settings.cognito_user_pool_id,
                )
            provider = CognitoIdentityProvider(
                boto3.client(
                    "cognito-idp",
                    region_name=settings.aws_region,
                    config=Config(
                        signature_version=UNSIGNED,
                        connect_timeout=5,
                        read_timeout=10,
                        retries={"max_attempts": 0},
                    ),
                ),
                settings.cognito_client_id,
                settings.cognito_client_secret,
                use_participant_id=catalog is not None and user_pool is None,
                user_pool=user_pool,
            )

    if not catalog and certificate_store is None and settings.certificate_s3_bucket:
        certificate_store = S3CertificateStore(
            boto3.client(
                "s3",
                region_name=settings.aws_region,
                config=Config(connect_timeout=5, read_timeout=15),
            ),
            settings.certificate_s3_bucket,
        )

    if certificate_generator is None and settings.certificate_generator_enabled:
        certificate_generator = CertificateServiceGenerator.from_local_templates(
            settings.local_templates_dir, "ucts"
        )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(title="UCTS Zone API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.auth = AuthService(
        uow,
        provider,
        settings.otp_secret,
        settings.otp_ttl_seconds,
        settings.otp_resend_seconds,
        settings.session_ttl_seconds,
        persist_subject=settings.auth_mode == "cognito",
    )
    app.state.certificates = CertificateService(
        uow,
        PdfCertificateRenderer(local=True) if settings.auth_mode == "local" else None,
        certificate_store,
        certificate_generator,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(AppError)
    async def application_error(request: Request, error: AppError):
        status = {
            ErrorKind.UNAUTHORIZED: 401,
            ErrorKind.FORBIDDEN: 403,
            ErrorKind.NOT_FOUND: 404,
            ErrorKind.RATE_LIMITED: 429,
            ErrorKind.UNAVAILABLE: 503,
        }[error.kind]
        headers = {"Retry-After": str(settings.otp_resend_seconds)} if status == 429 else {}
        return JSONResponse(status_code=status, content={"detail": error.message}, headers=headers)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError):
        return JSONResponse(status_code=503, content={"detail": "Base de datos no disponible."})

    @app.get("/health/live", tags=["health"])
    def live():
        return {"status": "ok", "authMode": settings.auth_mode}

    @app.get("/health/ready", tags=["health"])
    def ready():
        if catalog:
            with uow() as work:
                work.repo.check_catalog()
                work.repo.db.execute(text("SELECT count(*) FROM auth_sessions WHERE 1 = 0"))
                work.repo.db.execute(text("SELECT count(*) FROM certificate_downloads WHERE 1 = 0"))
        else:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        return {"status": "ok"}

    app.include_router(router)
    return app
