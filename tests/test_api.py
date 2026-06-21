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


def test_api_client_rejects_invalid_json_response():
    response = TransportResponse(status_code=200, text="<html>not json</html>")
    client = InformaniakAPIClient(token="secret-token", base_url="https://api.example.test", transport=FakeTransport(response))

    with pytest.raises(InformaniakAPIError) as exc_info:
        client.get("/2/profile")

    assert exc_info.value.status_code == 200
    assert "Invalid JSON response" in str(exc_info.value)
