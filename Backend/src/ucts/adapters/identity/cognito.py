import base64
import hashlib
import hmac
import json
import logging

from botocore.exceptions import BotoCoreError, ClientError

from ucts.domain.models import AppError, ErrorKind, Identity

logger = logging.getLogger(__name__)


class CognitoUserPool:
    def __init__(self, client, pool_id: str):
        self.client = client
        self.pool_id = pool_id

    def ensure_user(self, email: str, *, expected_subject: str | None = None) -> str | None:
        key = {"UserPoolId": self.pool_id, "Username": email}
        try:
            user = self._get_user(key)
            if user is None and expected_subject is None:
                try:
                    created = self.client.admin_create_user(
                        **key,
                        UserAttributes=[{"Name": "email", "Value": email}],
                        MessageAction="SUPPRESS",
                    )
                    user = created["User"]
                except self.client.exceptions.UsernameExistsException:
                    user = self._get_user(key)
        except ClientError as error:
            code = error.response["Error"]["Code"]
            logger.warning("Cognito administración falló (%s)", code)
            CognitoIdentityProvider._raise_provider_error(error)
            raise AssertionError("Unreachable") from None
        except BotoCoreError as error:
            logger.warning("Cognito administración no disponible (%s)", type(error).__name__)
            raise AppError(
                ErrorKind.UNAVAILABLE, "El servicio de autenticación no está disponible."
            ) from None
        if user is None:
            return None
        attrs = {
            item["Name"]: item["Value"]
            for item in user.get("UserAttributes", user.get("Attributes", []))
        }
        if (
            user.get("Enabled") is True
            and user.get("UserStatus") == "CONFIRMED"
            and attrs.get("email", "").lower() == email
            and (expected_subject is None or attrs.get("sub") == expected_subject)
        ):
            return attrs.get("sub") or None
        return None

    def _get_user(self, key: dict[str, str]) -> dict | None:
        try:
            return self.client.admin_get_user(**key)
        except self.client.exceptions.UserNotFoundException:
            return None


class CognitoIdentityProvider:
    def __init__(
        self,
        client,
        client_id: str,
        client_secret: str = "",
        *,
        use_participant_id: bool = False,
        user_pool: CognitoUserPool | None = None,
    ):
        self.client = client
        self.client_id = client_id
        self.client_secret = client_secret
        self.use_participant_id = use_participant_id
        self.user_pool = user_pool

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

    def request(
        self, email: str, participant_id: str = "", expected_subject: str | None = None
    ) -> str:
        login = participant_id if self.use_participant_id else email
        if self.user_pool is None:
            return self._request(login, None)
        try:
            subject = self.user_pool.ensure_user(email, expected_subject=expected_subject)
            if subject is not None:
                return self._request(login, subject)
        except AppError as error:
            # Provider failures must not distinguish catalog membership on the request endpoint.
            logger.warning("No se inició un desafío de Cognito (%s)", error.kind.value)
        return json.dumps({"unavailable": True})

    def _request(self, login: str, subject: str | None) -> str:
        try:
            result = self.client.initiate_auth(
                AuthFlow="USER_AUTH",
                ClientId=self.client_id,
                AuthParameters={
                    "USERNAME": login,
                    "PREFERRED_CHALLENGE": "EMAIL_OTP",
                    **self._secret_hash(login),
                },
            )
            parameters = result.get("ChallengeParameters", {})
            username = parameters.get("USER_ID_FOR_SRP") or parameters.get("USERNAME") or login
            if result.get("ChallengeName") == "SELECT_CHALLENGE":
                if "EMAIL_OTP" not in result.get("AvailableChallenges", []):
                    return json.dumps({"unavailable": True})
                result = self.client.respond_to_auth_challenge(
                    ClientId=self.client_id,
                    ChallengeName="SELECT_CHALLENGE",
                    Session=result["Session"],
                    ChallengeResponses={
                        "USERNAME": username,
                        "ANSWER": "EMAIL_OTP",
                        **self._secret_hash(username),
                    },
                )
            if result.get("ChallengeName") != "EMAIL_OTP" or not result.get("Session"):
                raise AppError(
                    ErrorKind.UNAVAILABLE, "El acceso por correo todavía no está configurado."
                )
            parameters = result.get("ChallengeParameters", {})
            username = parameters.get("USER_ID_FOR_SRP") or parameters.get("USERNAME") or username
            request_id = result.get("ResponseMetadata", {}).get("RequestId")
            if request_id:
                logging.getLogger("uvicorn.error").info(
                    "Cognito devolvió EMAIL_OTP (AWS RequestId=%s)", request_id
                )
            return json.dumps({"session": result["Session"], "username": username, "sub": subject})
        except ClientError as error:
            code = error.response["Error"]["Code"]
            logger.warning("Cognito autenticación falló (%s)", code)
            if code in {
                "UserNotFoundException",
                "UserNotConfirmedException",
                "NotAuthorizedException",
            }:
                # Same response shape and status: do not disclose user pool membership.
                return json.dumps({"unavailable": True})
            self._raise_provider_error(error)
        except BotoCoreError as error:
            logger.warning("Cognito autenticación no disponible (%s)", type(error).__name__)
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
            if challenge.get("sub") and attrs["sub"] != challenge["sub"]:
                raise AppError(ErrorKind.UNAUTHORIZED, "No fue posible verificar la identidad.")
            return Identity(attrs["sub"], attrs.get("email", "").lower())
        except ClientError as error:
            logger.warning("Cognito autenticación falló (%s)", error.response["Error"]["Code"])
            self._raise_provider_error(error)
        except BotoCoreError as error:
            logger.warning("Cognito autenticación no disponible (%s)", type(error).__name__)
            raise AppError(
                ErrorKind.UNAVAILABLE, "El servicio de autenticación no está disponible."
            ) from None
        raise AssertionError("Unreachable")
