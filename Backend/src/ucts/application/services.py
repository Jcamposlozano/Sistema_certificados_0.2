import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable

from ucts.application.ports import (
    CertificateGenerator,
    CertificateRenderer,
    CertificateStore,
    IdentityProvider,
    UnitOfWork,
)
from ucts.domain.models import (
    AppError,
    Certificate,
    Challenge,
    ErrorKind,
    Event,
    Participant,
    Session,
)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class AuthService:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        provider: IdentityProvider,
        secret: str,
        otp_ttl: int,
        resend_after: int,
        session_ttl: int,
        *,
        persist_subject: bool = True,
    ):
        self.uow = uow
        self.provider = provider
        self.secret = secret
        self.otp_ttl = otp_ttl
        self.resend_after = resend_after
        self.session_ttl = session_ttl
        self.persist_subject = persist_subject

    def _key(self, value: str) -> str:
        return hmac.new(self.secret.encode(), value.encode(), "sha256").hexdigest()

    def request(self, email: str, ip: str) -> str:
        now = int(time.time())
        email = email.strip().lower()
        with self.uow() as work:
            # Shared database counters: limits survive restart and multiple API workers.
            limits = [
                ("ip", ip, 900, 20),
                ("email", email, self.resend_after, 1),
                ("email-hour", email, 3600, 10),
            ]
            for prefix, value, window, maximum in limits:
                key = f"{prefix}:{self._key(value)}"
                if not work.repo.throttle(key, maximum, now + window):
                    work.commit()
                    raise AppError(
                        ErrorKind.RATE_LIMITED, "Demasiados intentos. Espera antes de continuar."
                    )
            challenge_id = secrets.token_urlsafe(32)
            target = work.repo.auth_target(email)
            if target:
                try:
                    provider_state = self.provider.request(
                        email, target, work.repo.bound_subject(target)
                    )
                except AppError:
                    work.commit()
                    raise
                state = json.dumps({"participant_id": target, "provider_state": provider_state})
                challenge = Challenge(challenge_id, email, state, now, now + self.otp_ttl)
                work.repo.add_challenge(challenge)
            work.commit()
            return challenge_id

    def verify(self, challenge_id: str, code: str) -> str:
        now = int(time.time())
        with self.uow() as work:
            challenge = work.repo.challenge(challenge_id)
            if (
                not challenge
                or challenge.consumed
                or challenge.expires_at <= now
                or challenge.attempts >= 5
            ):
                raise AppError(
                    ErrorKind.UNAUTHORIZED, "Código inválido o vencido. Solicita uno nuevo."
                )
            challenge.attempts += 1
            try:
                try:
                    state = json.loads(challenge.provider_state)
                except (ValueError, TypeError):
                    state = {}
                if not isinstance(state, dict):
                    state = {}
                target = work.repo.auth_target(challenge.email)
                if not target or state.get("participant_id") != target:
                    raise AppError(ErrorKind.UNAUTHORIZED, "Código inválido o vencido.")
                identity = self.provider.verify(challenge.email, state["provider_state"], code)
                if identity.email.lower() != challenge.email:
                    raise AppError(ErrorKind.UNAUTHORIZED, "No fue posible verificar la identidad.")
                participant = work.repo.bind_identity(
                    identity, target, persist_subject=self.persist_subject
                )
            except AppError:
                work.repo.save_challenge(challenge)
                work.commit()
                raise
            challenge.consumed = True
            work.repo.save_challenge(challenge)
            token = secrets.token_urlsafe(48)
            work.repo.add_session(
                Session(token_hash(token), participant.id, now + self.session_ttl)
            )
            work.commit()
            return token

    def current(self, token: str | None) -> Participant:
        if not token or len(token) > 256:
            raise AppError(ErrorKind.UNAUTHORIZED, "Inicia sesión para continuar.")
        with self.uow() as work:
            session = work.repo.session(token_hash(token))
            if not session or session.expires_at <= int(time.time()):
                raise AppError(ErrorKind.UNAUTHORIZED, "Tu sesión ha vencido. Ingresa nuevamente.")
            participant = work.repo.participant(session.participant_id)
            if not participant:
                raise AppError(ErrorKind.UNAUTHORIZED, "Sesión inválida.")
            return participant

    def logout(self, token: str | None) -> None:
        if token:
            with self.uow() as work:
                work.repo.delete_session(token_hash(token))
                work.commit()


class CertificateService:
    def __init__(
        self,
        uow: Callable[[], UnitOfWork],
        renderer: CertificateRenderer | None,
        store: CertificateStore | None,
        generator: CertificateGenerator | None = None,
    ):
        self.uow = uow
        self.renderer = renderer
        self.store = store
        self.generator = generator

    def events(self, participant: Participant) -> list[Event]:
        with self.uow() as work:
            return work.repo.events(participant.id)

    def download(self, participant: Participant, event_id: str) -> bytes:
        with self.uow() as work:
            event = work.repo.event(participant.id, event_id)
            if not event:
                raise AppError(
                    ErrorKind.NOT_FOUND, "No se encontró el evento en tus participaciones."
                )
            if not (event.available and self.renderer and event.date and event.hours):
                raise AppError(ErrorKind.FORBIDDEN, "El certificado todavía no está habilitado.")
        data = self.renderer.render(participant, event)
        self._record_download(participant.id, event.id, None)
        return data

    def certificates(self, participant: Participant) -> list[Certificate]:
        with self.uow() as work:
            return work.repo.certificates(participant.id)

    def certificate_available(self, certificate: Certificate) -> bool:
        if certificate.generation is not None and self.generator is not None:
            return certificate.status == "pending" and self.generator.supports(certificate)
        return certificate.status == "published"

    def download_certificate(self, participant: Participant, certificate_id: str) -> bytes:
        with self.uow() as work:
            certificate = work.repo.certificate(participant.id, certificate_id)
        if not certificate:
            raise AppError(ErrorKind.NOT_FOUND, "No se encontró el certificado.")
        if not self.certificate_available(certificate):
            raise AppError(ErrorKind.FORBIDDEN, "El certificado no está habilitado.")
        if certificate.generation is not None and self.generator is not None:
            data = self.generator.generate(certificate)
        elif self.store and certificate.s3_bucket and certificate.s3_key:
            data = self.store.download(
                certificate.s3_bucket, certificate.s3_key, certificate.s3_version_id
            )
        else:
            raise AppError(ErrorKind.UNAVAILABLE, "El archivo no está disponible.")
        self._record_download(participant.id, certificate.event_id, certificate.id)
        return data

    def _record_download(self, participant_id: str, event_id: str, certificate_id: str | None):
        with self.uow() as work:
            work.repo.add_certificate_download(participant_id, event_id, certificate_id)
            work.commit()
