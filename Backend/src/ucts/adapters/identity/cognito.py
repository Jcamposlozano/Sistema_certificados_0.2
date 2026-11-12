import base64
import hashlib
import hmac
import json

from botocore.exceptions import BotoCoreError, ClientError

from ucts.domain.models import AppError, ErrorKind, Identity


class CognitoIdentityProvider:
    def __init__(self, client, client_id: str, client_secret: str = ""):
        self.client = client
        self.client_id = client_id
        self.client_secret = client_secret

    def _secret_hash(self, username: str) -> dict[str, str]:
        if not self.client_secret:
            return {}
        digest = hmac.new(
            self.client_secret.encode(), (username + self.client_id).encode(), hashlib.sha256
        ).digest()
        return {"SECRET_HASH": base64.b64encode(digest).decode()}

    @staticmethod
    def _raise_provider_error(error: ClientError) -> None:
        code = error.response["Error"]["Code"]
        if code in {"TooManyRequestsException", "LimitExceededException"}:
            raise AppError(
                ErrorKind.RATE_LIMITED, "Demasiados intentos. Espera antes de continuar."
            ) from None
        if code in {
            "NotAuthorizedException",
            "CodeMismatchException",
            "ExpiredCodeException",
            "UserNotFoundException",
            "UserNotConfirmedException",
        }:
            raise AppError(
                ErrorKind.UNAUTHORIZED, "Código inválido o vencido. Solicita uno nuevo."
            ) from None
        raise AppError(
            ErrorKind.UNAVAILABLE, "El servicio de autenticación no está disponible."
        ) from None

    def request(self, email: str) -> str:
        try:
            result = self.client.initiate_auth(
                AuthFlow="USER_AUTH",
                ClientId=self.client_id,
                AuthParameters={
                    "USERNAME": email,
                    "PREFERRED_CHALLENGE": "EMAIL_OTP",
                    **self._secret_hash(email),
                },
            )
            if result.get("ChallengeName") == "SELECT_CHALLENGE":
                result = self.client.respond_to_auth_challenge(
                    ClientId=self.client_id,
                    ChallengeName="SELECT_CHALLENGE",
                    Session=result["Session"],
                    ChallengeResponses={
                        "USERNAME": email,
                        "ANSWER": "EMAIL_OTP",
                        **self._secret_hash(email),
                    },
                )
            if result.get("ChallengeName") != "EMAIL_OTP" or not result.get("Session"):
                raise AppError(
                    ErrorKind.UNAVAILABLE, "El acceso por correo todavía no está configurado."
                )
            username = result.get("ChallengeParameters", {}).get("USERNAME", email)
            return json.dumps({"session": result["Session"], "username": username})
        except ClientError as error:
            if error.response["Error"]["Code"] in {
                "UserNotFoundException",
                "UserNotConfirmedException",
                "NotAuthorizedException",
            }:
                # Same response shape and status: do not disclose user pool membership.
                return json.dumps({"unavailable": True})
            self._raise_provider_error(error)
        except BotoCoreError:
            raise AppError(
                ErrorKind.UNAVAILABLE, "El servicio de autenticación no está disponible."
            ) from None
        raise AssertionError("Unreachable")

    def verify(self, email: str, state: str, code: str) -> Identity:
        challenge = json.loads(state)
        if challenge.get("unavailable"):
            raise AppError(ErrorKind.UNAUTHORIZED, "Código inválido o vencido.")
        username = challenge["username"]
        try:
            result = self.client.respond_to_auth_challenge(
                ClientId=self.client_id,
                ChallengeName="EMAIL_OTP",
                Session=challenge["session"],
                ChallengeResponses={
                    "USERNAME": username,
                    "EMAIL_OTP_CODE": code,
                    **self._secret_hash(username),
                },
            )
            authentication = result.get("AuthenticationResult", {})
            if not authentication.get("AccessToken"):
                raise AppError(ErrorKind.UNAUTHORIZED, "No fue posible completar la autenticación.")
            # Cognito validates this access token. No unverified JWT payloads are trusted.
            user = self.client.get_user(AccessToken=authentication["AccessToken"])
            attrs = {item["Name"]: item["Value"] for item in user["UserAttributes"]}
            if attrs.get("email_verified") != "true" or not attrs.get("sub"):
                raise AppError(ErrorKind.UNAUTHORIZED, "El correo debe estar verificado.")
            return Identity(attrs["sub"], attrs.get("email", "").lower())
        except ClientError as error:
            self._raise_provider_error(error)
        except BotoCoreError:
            raise AppError(
                ErrorKind.UNAVAILABLE, "El servicio de autenticación no está disponible."
            ) from None
        raise AssertionError("Unreachable")
