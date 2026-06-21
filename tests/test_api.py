import pytest

from infomaniak_cli.api import InformaniakAPIClient, InformaniakAPIError, TransportResponse, redact_secret


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def request(self, method, url, *, headers, params=None, json=None):
        self.requests.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "params": params,
                "json": json,
            }
        )
        return self.responses.pop(0)


def test_redact_secret_removes_bearer_tokens():
    bearer = "Bea" + "rer "
    message = "Authorization: " + bearer + "example-token failed"
    expected = "Authorization: " + bearer + "*** failed"

    assert redact_secret(message) == expected


def test_redact_secret_removes_common_token_fields_and_known_secret():
    message = 'token="secret-token" access_token=abc123 refresh_token: "refresh123"'

    redacted = redact_secret(message, secrets=["secret-token"])

    assert "secret-token" not in redacted
    assert "abc123" not in redacted
    assert "refresh123" not in redacted


def test_api_client_get_builds_url_headers_and_parses_json():
    transport = FakeTransport(TransportResponse(status_code=200, text='{"result":"success","data":{"id":123}}'))
    client = InformaniakAPIClient(token="secret-token", base_url="https://api.example.test", transport=transport)

    payload = client.get("/2/profile", params={"include": "emails"})

    assert payload == {"result": "success", "data": {"id": 123}}
    assert transport.requests == [
        {
            "method": "GET",
            "url": "https://api.example.test/2/profile",
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer secret-token",
            },
            "params": {"include": "emails"},
            "json": None,
        }
    ]


def test_api_client_get_raw_allows_non_enveloped_json():
    response = TransportResponse(status_code=200, text='[{"id":"team-1","display_name":"Cylro"}]')
    client = InformaniakAPIClient(token="secret-token", base_url="https://api.example.test", transport=FakeTransport(response))

    payload = client.get_raw("https://chat.example.test/api/v4/users/me/teams")

    assert payload == [{"id": "team-1", "display_name": "Cylro"}]


def test_api_client_post_sends_json_content_type():
    transport = FakeTransport(TransportResponse(status_code=201, text='{"result":"success","data":{"ok":true}}'))
    client = InformaniakAPIClient(token="secret-token", base_url="https://api.example.test/", transport=transport)

    payload = client.post("1/accounts/42/tags", json={"name": "Cylro"})

    assert payload["data"]["ok"] is True
    assert transport.requests[0]["method"] == "POST"
    assert transport.requests[0]["url"] == "https://api.example.test/1/accounts/42/tags"
    assert transport.requests[0]["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer secret-token",
        "Content-Type": "application/json",
    }
    assert transport.requests[0]["json"] == {"name": "Cylro"}


def test_api_client_error_exposes_status_and_redacts_token():
    token = "very-secret-token"
    response = TransportResponse(
        status_code=403,
        text='{"result":"error","error":{"message":"Authorization: Bearer very-secret-token lacks scope"}}',
    )
    client = InformaniakAPIClient(token=token, base_url="https://api.example.test", transport=FakeTransport(response))

    with pytest.raises(InformaniakAPIError) as exc_info:
        client.get("/1/accounts")

    assert exc_info.value.status_code == 403
    assert "Bearer ***" in str(exc_info.value)
    assert token not in str(exc_info.value)


def test_api_client_401_has_auth_scope_message_and_redacts_known_token():
    token = "very-secret-token"
    response = TransportResponse(
        status_code=401,
        text='{"result":"error","error":{"message":"token very-secret-token expired"}}',
    )
    client = InformaniakAPIClient(token=token, base_url="https://api.example.test", transport=FakeTransport(response))

    with pytest.raises(InformaniakAPIError) as exc_info:
        client.get("/2/profile")

    assert exc_info.value.status_code == 401
    assert "authentication failed or insufficient scope" in str(exc_info.value)
    assert token not in str(exc_info.value)


def test_api_client_rejects_missing_response_envelope_with_readable_error():
    token = "very-secret-token"
    response = TransportResponse(status_code=200, text='{"id":123,"token":"very-secret-token"}')
    client = InformaniakAPIClient(token=token, base_url="https://api.example.test", transport=FakeTransport(response))

    with pytest.raises(InformaniakAPIError) as exc_info:
        client.get("/2/profile")

    message = str(exc_info.value)
    assert exc_info.value.status_code == 200
    assert "Unexpected API response envelope" in message
    assert "missing result" in message
    assert token not in message


def test_api_client_rejects_unexpected_response_envelope_result():
    response = TransportResponse(status_code=200, text='{"result":"maybe","data":{"id":123}}')
    client = InformaniakAPIClient(token="secret-token", base_url="https://api.example.test", transport=FakeTransport(response))

    with pytest.raises(InformaniakAPIError) as exc_info:
        client.get("/2/profile")

    assert exc_info.value.status_code == 200
    assert "expected result=success" in str(exc_info.value)


def test_api_client_rejects_invalid_json_response():
    response = TransportResponse(status_code=200, text="<html>not json</html>")
    client = InformaniakAPIClient(token="secret-token", base_url="https://api.example.test", transport=FakeTransport(response))

    with pytest.raises(InformaniakAPIError) as exc_info:
        client.get("/2/profile")

    assert exc_info.value.status_code == 200
    assert "Invalid JSON response" in str(exc_info.value)
