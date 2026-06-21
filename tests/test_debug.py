import json

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIClient, TransportResponse
from infomaniak_cli.auth import TokenStore
from infomaniak_cli.debug import build_probe_candidates, probe_endpoints
from infomaniak_cli.profiles import ProfileManager


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


class FakeProbeClient:
    def __init__(self, token):
        self.token = token
        self.calls = []

    def probe_get(self, path, params=None):
        self.calls.append((path, params))
        if path == "/2/drive":
            return {"status_code": 200, "json": {"result": "success", "data": [{"id": "drive-1", "name": self.token}]}}
        return {"status_code": 404, "json": {"result": "error", "error": {"message": self.token}}}


def test_build_probe_candidates_includes_drive_kchat_and_ksuite_paths():
    candidates = build_probe_candidates("42")

    assert [(candidate["group"], candidate["path"], candidate["params"]) for candidate in candidates] == [
        ("kdrive", "/2/drive", None),
        ("kdrive", "/2/drive", {"account_id": "42"}),
        ("kdrive", "/3/drive", None),
        ("kdrive", "/1/drive", None),
        ("kdrive", "/2/kdrive", None),
        ("kchat", "/1/kchat", None),
        ("kchat", "/2/kchat", None),
        ("kchat", "/1/accounts/42/kchat", None),
        ("ksuite", "/1/my_ksuite/current", None),
        ("ksuite", "/1/my_ksuite", None),
    ]


def test_probe_endpoints_reports_status_and_shape_without_values_or_token():
    token = "secret-token"
    transport = FakeTransport(
        TransportResponse(status_code=200, text='{"result":"success","data":[{"id":"drive-1","name":"Cylro"}]}'),
        TransportResponse(status_code=404, text='{"result":"error","error":{"message":"secret-token not allowed"}}'),
    )
    client = InformaniakAPIClient(token=token, base_url="https://api.example.test", transport=transport)
    candidates = [
        {"group": "kdrive", "path": "/2/drive", "params": None},
        {"group": "kchat", "path": "/1/kchat", "params": None},
    ]

    result = probe_endpoints(client, candidates)

    assert result["results"][0] == {
        "group": "kdrive",
        "path": "/2/drive",
        "params": None,
        "status_code": 200,
        "shape": {
            "type": "object",
            "keys": ["data", "result"],
            "data": {"type": "list", "count": 1, "first_item_keys": ["id", "name"]},
        },
    }
    assert result["results"][1]["status_code"] == 404
    rendered = json.dumps(result)
    assert token not in rendered
    assert "Cylro" not in rendered
    assert transport.requests[0]["headers"]["Authorization"] == f"Bearer {token}"


def test_cli_debug_probe_json_uses_profile_token_and_does_not_leak_values(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", account_id="42", make_default=True)
    token = "secret-token"
    TokenStore().save_token("cylro", token)
    fake_client = FakeProbeClient(token)
    monkeypatch.setattr(cli, "_make_api_client", lambda token, base_url: fake_client)

    assert cli.main(["debug", "probe", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "cylro"
    assert "kChat may require a different host or token" in output["notes"][0]
    assert fake_client.calls == [(candidate["path"], candidate["params"]) for candidate in build_probe_candidates("42")]
    rendered = json.dumps(output)
    assert token not in rendered
