import json

import boto3
import pytest
from botocore.stub import Stubber

from ucts.adapters.identity.cognito import CognitoIdentityProvider
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
