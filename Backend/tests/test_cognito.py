import json
from contextlib import closing

import boto3
import pytest
from botocore.stub import Stubber

from ucts.adapters.identity.cognito import CognitoIdentityProvider, CognitoUserPool
from ucts.config import Settings
from ucts.domain.models import AppError, ErrorKind


@pytest.fixture
def cognito():
    client = boto3.client(
        "cognito-idp",
        region_name="us-east-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",
    )
    with Stubber(client) as stub:
        yield CognitoIdentityProvider(client, "client123"), stub
        stub.assert_no_pending_responses()


def test_cognito_email_otp_challenge_and_verified_identity(cognito):
    provider, stub = cognito
    stub.add_response(
        "initiate_auth",
        {"ChallengeName": "EMAIL_OTP", "Session": "s" * 32},
        {
            "AuthFlow": "USER_AUTH",
            "ClientId": "client123",
            "AuthParameters": {"USERNAME": "ana@example.com", "PREFERRED_CHALLENGE": "EMAIL_OTP"},
        },
    )
    state = provider.request("ana@example.com")
    stub.add_response(
        "respond_to_auth_challenge",
        {"AuthenticationResult": {"AccessToken": "access-token"}},
        {
            "ClientId": "client123",
            "ChallengeName": "EMAIL_OTP",
            "Session": "s" * 32,
            "ChallengeResponses": {"USERNAME": "ana@example.com", "EMAIL_OTP_CODE": "123456"},
        },
    )
    stub.add_response(
        "get_user",
        {
            "Username": "user123",
            "UserAttributes": [
                {"Name": "sub", "Value": "subject123"},
                {"Name": "email", "Value": "ana@example.com"},
                {"Name": "email_verified", "Value": "true"},
            ],
        },
        {"AccessToken": "access-token"},
    )
    identity = provider.verify("ana@example.com", state, "123456")
    assert identity.subject == "subject123"
    assert identity.email == "ana@example.com"


def test_cognito_does_not_disclose_unknown_account(cognito):
    provider, stub = cognito
    stub.add_client_error("initiate_auth", service_error_code="UserNotFoundException")
    state = provider.request("unknown@example.com")
    assert json.loads(state)["unavailable"] is True
    with pytest.raises(AppError) as error:
        provider.verify("unknown@example.com", state, "123456")
    assert error.value.kind == ErrorKind.UNAUTHORIZED


def test_cognito_requires_verified_email(cognito):
    provider, stub = cognito
    stub.add_response(
        "respond_to_auth_challenge", {"AuthenticationResult": {"AccessToken": "access-token"}}
    )
    stub.add_response(
        "get_user",
        {
            "Username": "user123",
            "UserAttributes": [
                {"Name": "sub", "Value": "subject123"},
                {"Name": "email", "Value": "ana@example.com"},
                {"Name": "email_verified", "Value": "false"},
            ],
        },
    )
    with pytest.raises(AppError) as error:
        provider.verify(
            "ana@example.com", json.dumps({"session": "s" * 32, "username": "user123"}), "123456"
        )
    assert error.value.kind == ErrorKind.UNAUTHORIZED


def test_production_rejects_local_auth():
    with pytest.raises(ValueError, match="Producción requiere Cognito"):
        Settings(
            _env_file=None,
            database_url="sqlite://",
            otp_secret="a" * 32,
            app_env="production",
            auth_mode="local",
        )


def test_catalog_sign_in_uses_participant_uuid(cognito):
    provider, stub = cognito
    identifier = "00000000-0000-4000-8000-000000000001"
    catalog_provider = CognitoIdentityProvider(
        provider.client, "client123", use_participant_id=True
    )
    stub.add_response(
        "initiate_auth",
        {"ChallengeName": "EMAIL_OTP", "Session": "s" * 32},
        {
            "AuthFlow": "USER_AUTH",
            "ClientId": "client123",
            "AuthParameters": {"USERNAME": identifier, "PREFERRED_CHALLENGE": "EMAIL_OTP"},
        },
    )
    state = catalog_provider.request("principal@example.org", identifier)
    assert json.loads(state)["username"] == identifier


@pytest.mark.parametrize("collision", [False, True])
def test_provisions_email_without_password_or_invitation(cognito, collision):
    provider, stub = cognito
    pool = CognitoUserPool(provider.client, "us-east-2_synthetic")
    email = "principal@example.org"
    key = {"UserPoolId": pool.pool_id, "Username": email}
    attrs = [{"Name": "email", "Value": email}, {"Name": "sub", "Value": "subject123"}]
    user = {"Username": "canonical", "Enabled": True, "UserStatus": "CONFIRMED"}
    create = {**key, "MessageAction": "SUPPRESS", "UserAttributes": attrs[:1]}
    stub.add_client_error(
        "admin_get_user", service_error_code="UserNotFoundException", expected_params=key
    )
    if collision:
        stub.add_client_error(
            "admin_create_user",
            service_error_code="UsernameExistsException",
            expected_params=create,
        )
        stub.add_response("admin_get_user", {**user, "UserAttributes": attrs}, key)
    else:
        stub.add_response("admin_create_user", {"User": {**user, "Attributes": attrs}}, create)
    assert pool.ensure_user(email) == "subject123"
    stub.add_response("admin_get_user", {**user, "UserAttributes": attrs}, key)
    assert pool.ensure_user(email, expected_subject="another-subject") is None
    stub.add_client_error(
        "admin_get_user", service_error_code="UserNotFoundException", expected_params=key
    )
    assert pool.ensure_user(email, expected_subject="subject123") is None


def test_confidential_cognito_checks_account_and_hashes_each_challenge(cognito, caplog):
    import base64
    import hashlib
    import hmac

    client = cognito[0].client
    stub = cognito[1]
    pool = CognitoUserPool(client, "us-east-2_synthetic")
    provider = CognitoIdentityProvider(client, "client123", "test-secret", user_pool=pool)
    email = "principal@example.org"

    def digest(username):
        return base64.b64encode(
            hmac.new(b"test-secret", (username + "client123").encode(), hashlib.sha256).digest()
        ).decode()

    stub.add_response(
        "admin_get_user",
        {
            "Username": "canonical",
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserAttributes": [
                {"Name": "email", "Value": email},
                {"Name": "sub", "Value": "subject123"},
            ],
        },
        {"UserPoolId": pool.pool_id, "Username": email},
    )
    stub.add_response(
        "initiate_auth",
        {
            "ChallengeName": "SELECT_CHALLENGE",
            "Session": "a" * 32,
            "AvailableChallenges": ["EMAIL_OTP"],
            "ChallengeParameters": {"USERNAME": "canonical"},
        },
        {
            "AuthFlow": "USER_AUTH",
            "ClientId": "client123",
            "AuthParameters": {
                "USERNAME": email,
                "PREFERRED_CHALLENGE": "EMAIL_OTP",
                "SECRET_HASH": digest(email),
            },
        },
    )
    stub.add_response(
        "respond_to_auth_challenge",
        {
            "ChallengeName": "EMAIL_OTP",
            "Session": "s" * 32,
            "ResponseMetadata": {"RequestId": "aws-test-request-id"},
        },
        {
            "ClientId": "client123",
            "ChallengeName": "SELECT_CHALLENGE",
            "Session": "a" * 32,
            "ChallengeResponses": {
                "USERNAME": "canonical",
                "ANSWER": "EMAIL_OTP",
                "SECRET_HASH": digest("canonical"),
            },
        },
    )
    with caplog.at_level("INFO", logger="uvicorn.error"):
        state = provider.request(email, "uuid-local")
    assert "Cognito devolvió EMAIL_OTP (AWS RequestId=aws-test-request-id)" in caplog.text
    assert all(value not in caplog.text for value in (email, "s" * 32, "test-secret"))
    assert json.loads(state)["sub"] == "subject123"
    request = {
        "ClientId": "client123",
        "ChallengeName": "EMAIL_OTP",
        "Session": "s" * 32,
        "ChallengeResponses": {
            "USERNAME": "canonical",
            "EMAIL_OTP_CODE": "123456",
            "SECRET_HASH": digest("canonical"),
        },
    }
    for code in ("CodeMismatchException", "ExpiredCodeException"):
        stub.add_client_error(
            "respond_to_auth_challenge", service_error_code=code, expected_params=request
        )
        with pytest.raises(AppError) as error:
            provider.verify(email, state, "123456")
        assert error.value.kind == ErrorKind.UNAUTHORIZED

    for subject in ("different-pool-subject", "subject123"):
        stub.add_response(
            "respond_to_auth_challenge",
            {"AuthenticationResult": {"AccessToken": "test-token"}},
            request,
        )
        stub.add_response(
            "get_user",
            {
                "Username": "canonical",
                "UserAttributes": [
                    {"Name": "email", "Value": email},
                    {"Name": "email_verified", "Value": "true"},
                    {"Name": "sub", "Value": subject},
                ],
            },
            {"AccessToken": "test-token"},
        )
        if subject != "subject123":
            with pytest.raises(AppError, match="identidad"):
                provider.verify(email, state, "123456")
        else:
            assert provider.verify(email, state, "123456").subject == subject


def test_admin_failure_reports_unavailable_without_logging_credentials(cognito, caplog):
    provider, stub = cognito
    pool = CognitoUserPool(provider.client, "us-east-2_synthetic")
    email = "principal@example.org"
    stub.add_client_error(
        "admin_get_user",
        service_error_code="AccessDeniedException",
        service_message=f"mensaje de AWS con {email}",
        expected_params={"UserPoolId": pool.pool_id, "Username": email},
    )
    confidential = CognitoIdentityProvider(
        provider.client, "client123", "test-secret", user_pool=pool
    )
    with pytest.raises(AppError) as error:
        confidential.request(email, "uuid-local")
    assert error.value.kind == ErrorKind.UNAVAILABLE
    assert "AccessDeniedException" in caplog.text
    assert email not in caplog.text
    assert "test-secret" not in caplog.text


def test_standard_chain_is_resolved_at_request_time_with_explicit_region(monkeypatch):
    import botocore.session
    from botocore.credentials import CredentialProvider, Credentials

    from ucts.adapters.identity.cognito import administrative_client

    class InstanceRole(CredentialProvider):
        METHOD = "iam-role"
        available = False

        def load(self):
            if self.available:
                return Credentials(
                    "synthetic-key", "synthetic-secret", "synthetic-token", method=self.METHOD
                )
            return None

    role = InstanceRole()
    session_class = boto3.Session

    def session():
        core = botocore.session.get_session()
        core.get_component("credential_provider").providers = [role]
        return session_class(botocore_session=core)

    monkeypatch.setattr("ucts.adapters.identity.cognito.boto3.Session", session)
    from botocore.exceptions import NoCredentialsError

    with pytest.raises(NoCredentialsError):
        administrative_client("us-east-2")
    # Model the previous startup behavior: a signer constructed before IMDS was ready.
    with closing(session().client("cognito-idp", region_name="us-east-2")) as stale:
        assert stale._request_signer._credentials is None
        role.available = True
        assert stale._request_signer._credentials is None
        with closing(administrative_client("us-east-2")) as current:
            assert current.meta.region_name == "us-east-2"
            assert current._request_signer._credentials.method == "iam-role"


def test_missing_role_then_recovery_does_not_cache_unsigned_admin_client(cognito):
    from unittest.mock import Mock

    from botocore.exceptions import NoCredentialsError

    client, stub = cognito[0].client, cognito[1]
    factory = Mock(side_effect=[NoCredentialsError(), client])
    pool = CognitoUserPool(None, "us-east-2_synthetic", client_factory=factory)
    with pytest.raises(AppError) as error:
        pool.ensure_user("principal@example.org")
    assert error.value.kind == ErrorKind.UNAVAILABLE
    stub.add_response(
        "admin_get_user",
        {
            "Username": "canonical",
            "Enabled": True,
            "UserStatus": "CONFIRMED",
            "UserAttributes": [
                {"Name": "email", "Value": "principal@example.org"},
                {"Name": "sub", "Value": "subject123"},
            ],
        },
        {"UserPoolId": pool.pool_id, "Username": "principal@example.org"},
    )
    assert pool.ensure_user("principal@example.org") == "subject123"
    assert factory.call_count == 2


@pytest.mark.parametrize(
    "code,kind",
    [
        ("AccessDeniedException", ErrorKind.UNAVAILABLE),
        ("ResourceNotFoundException", ErrorKind.UNAVAILABLE),
        ("InvalidParameterException", ErrorKind.UNAVAILABLE),
        ("CodeDeliveryFailureException", ErrorKind.UNAVAILABLE),
        ("TooManyRequestsException", ErrorKind.RATE_LIMITED),
    ],
)
def test_aws_request_errors_are_diagnostic_and_not_success(cognito, caplog, code, kind):
    client, stub = cognito[0].client, cognito[1]
    provider = CognitoIdentityProvider(client, "client123")
    stub.add_client_error(
        "initiate_auth",
        service_error_code=code,
        service_message="sensitive-message-not-for-logs",
        response_meta={"RequestId": "request-id"},
    )
    with pytest.raises(AppError) as error:
        provider.request("principal@example.org")
    assert error.value.kind == kind
    entries = [
        json.loads(record.message) for record in caplog.records if record.message.startswith("{")
    ]
    assert {
        "event": "cognito_operation_failed",
        "operation": "initiate_auth",
        "code": code,
        "request_id": "request-id",
    } in entries
    assert "sensitive-message-not-for-logs" not in caplog.text
    assert "principal@example.org" not in caplog.text


def test_cognito_construction_defers_signed_credentials(engine, settings, monkeypatch, tmp_path):
    from unittest.mock import Mock

    from ucts.main import create_app

    catalog = tmp_path / "catalog.sqlite"
    catalog.touch()
    config = settings.model_copy(
        update={
            "auth_mode": "cognito",
            "certificate_catalog_sqlite": catalog,
            "cognito_client_id": "synthetic-client",
            "cognito_client_secret": "synthetic-secret",
            "cognito_user_pool_id": "us-east-2_synthetic",
            "aws_region": "us-east-2",
        }
    )
    deferred = Mock(side_effect=AssertionError("Credentials should be resolved by request"))
    monkeypatch.setattr("ucts.main.administrative_client", deferred)
    monkeypatch.setattr("ucts.main.boto3.client", Mock())
    app = create_app(config, engine=engine)
    assert app.state.auth.provider.user_pool.client is None
    deferred.assert_not_called()
