import hashlib
import hmac
import secrets
import time
from collections.abc import Callable

from ucts.application.ports import CertificateRenderer, IdentityProvider, UnitOfWork
from ucts.domain.models import AppError, Challenge, ErrorKind, Event, Participant, Session


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
    ):
        self.uow = uow
        self.provider = provider
        self.secret = secret
        self.otp_ttl = otp_ttl
        self.resend_after = resend_after
        self.session_ttl = session_ttl

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
                    raise AppError(
                        ErrorKind.RATE_LIMITED, "Demasiados intentos. Espera antes de continuar."
                    )
            state = self.provider.request(email)
            challenge = Challenge(secrets.token_urlsafe(32), email, state, now, now + self.otp_ttl)
            work.repo.add_challenge(challenge)
            work.commit()
            return challenge.id

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
                identity = self.provider.verify(challenge.email, challenge.provider_state, code)
                if identity.email.lower() != challenge.email:
                    raise AppError(ErrorKind.UNAUTHORIZED, "No fue posible verificar la identidad.")
                participant = work.repo.bind_identity(identity)
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
    def __init__(self, uow: Callable[[], UnitOfWork], renderer: CertificateRenderer):
        self.uow = uow
        self.renderer = renderer

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
            if not event.available:
                raise AppError(ErrorKind.FORBIDDEN, "El certificado todavía no está habilitado.")
        return self.renderer.render(participant, event)
