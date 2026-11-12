import hashlib
import hmac
import logging
import secrets

from ucts.domain.models import AppError, ErrorKind, Identity

logger = logging.getLogger("ucts.local_otp")


class LocalIdentityProvider:
    """Only for local development. No email delivery; never enabled in production."""

    def __init__(self, secret: str):
        self.secret = secret.encode()

    def _digest(self, email: str, salt: str, code: str) -> str:
        return hmac.new(self.secret, f"{email}:{salt}:{code}".encode(), "sha256").hexdigest()

    def request(self, email: str) -> str:
        code = f"{secrets.randbelow(1_000_000):06d}"
        salt = secrets.token_hex(16)
        # Explicitly local: do not configure this logger in deployed environments.
        logger.warning("SOLO LOCAL · OTP para %s: %s", email, code)
        return f"{salt}:{self._digest(email, salt, code)}"

    def verify(self, email: str, state: str, code: str) -> Identity:
        salt, expected = state.split(":", 1)
        if not hmac.compare_digest(expected, self._digest(email, salt, code)):
            raise AppError(ErrorKind.UNAUTHORIZED, "Código inválido o vencido.")
        return Identity(f"local:{hashlib.sha256(email.encode()).hexdigest()}", email)
