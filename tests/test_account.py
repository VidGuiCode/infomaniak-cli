import json
import os
import subprocess
import sys

from infomaniak_cli import cli
from infomaniak_cli.api import DEFAULT_BASE_URL
from infomaniak_cli.auth import TokenStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.account import list_accounts, list_products, list_services


class FakeAPI:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        return self.responses[path]


def run_ik(tmp_path, *args):
    env = os.environ.copy()
    env["IK_CONFIG_DIR"] = str(tmp_path / "config")
    env["PYTHONPATH"] = "src"
    return subprocess.run(
        [sys.executable, "-m", "infomaniak_cli.cli", *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_account_service_lists_accounts_products_and_services():
    api = FakeAPI(
        {
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {"result": "success", "data": [{"id": "mail-1", "name": "Mail"}]},
            "/1/accounts/42/services": {"result": "success", "data": [{"id": "drive-1", "name": "Drive"}]},
        }
    )

    assert list_accounts(api) == [{"id": 42, "name": "Cylro SARL-S"}]
    assert list_products(api, "42") == [{"id": "mail-1", "name": "Mail"}]
    assert list_services(api, "42") == [{"id": "drive-1", "name": "Drive"}]
    assert api.calls == [
        ("/1/accounts", None),
        ("/1/accounts/42/products", None),
        ("/1/accounts/42/services", None),
    ]


def test_cli_account_list_json_uses_profile_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", make_default=True)
    TokenStore().save_token("cylro", "secret-token")
    fake_api = FakeAPI({"/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]}})
    seen_clients = []
    monkeypatch.setattr(
        cli,
        "InformaniakAPIClient",
        lambda token, *, base_url: (seen_clients.append((token, base_url)) or fake_api),
    )

    assert cli.main(["account", "list", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"profile": "cylro", "accounts": [{"id": 42, "name": "Cylro SARL-S"}]}
    assert seen_clients == [("secret-token", DEFAULT_BASE_URL)]
    assert fake_api.calls == [("/1/accounts", None)]


def test_cli_account_products_json_prefers_profile_account_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", account_id="42", make_default=True)
    TokenStore().save_token("cylro", "secret-token")
    fake_api = FakeAPI({"/1/accounts/42/products": {"result": "success", "data": [{"id": "mail-1"}]}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["account", "products", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"profile": "cylro", "account_id": "42", "products": [{"id": "mail-1"}]}
    assert fake_api.calls == [("/1/accounts/42/products", None)]


def test_cli_account_services_json_allows_explicit_account_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", account_id="42", make_default=True)
    TokenStore().save_token("cylro", "secret-token")
    fake_api = FakeAPI({"/1/accounts/99/services": {"result": "success", "data": [{"id": "drive-1"}]}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["account", "services", "--account-id", "99", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"profile": "cylro", "account_id": "99", "services": [{"id": "drive-1"}]}
    assert fake_api.calls == [("/1/accounts/99/services", None)]


def test_cli_account_products_requires_account_id_when_profile_has_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", make_default=True)
    TokenStore().save_token("cylro", "secret-token")

    assert cli.main(["account", "products"]) == 1

    captured = capsys.readouterr()
    assert "No account selected" in captured.err
    assert "rerun with --account-id" in captured.err


def test_cli_account_list_requires_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", make_default=True)

    assert cli.main(["account", "list"]) == 1

    captured = capsys.readouterr()
    assert "No token configured for profile: cylro" in captured.err


def test_cli_admin_accounts_is_not_a_discovery_alias(tmp_path):
    result = run_ik(tmp_path, "admin", "accounts")

    assert result.returncode != 0
    assert "invalid choice" in result.stderr
