import json
import os
import subprocess
import sys

from infomaniak_cli import cli
from infomaniak_cli.api import DEFAULT_BASE_URL
from infomaniak_cli.auth import TokenStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.account import (
    list_accounts,
    list_products,
    list_services,
    slim_account,
    slim_product,
    slim_products,
)


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
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Example Co"}]},
            "/1/accounts/42/products": {"result": "success", "data": [{"id": "mail-1", "name": "Mail"}]},
            "/1/accounts/42/services": {"result": "success", "data": [{"id": "drive-1", "name": "Drive"}]},
        }
    )

    assert list_accounts(api) == [{"id": 42, "name": "Example Co"}]
    assert list_products(api, "42") == [{"id": "mail-1", "name": "Mail"}]
    assert list_services(api, "42") == [{"id": "drive-1", "name": "Drive"}]
    assert api.calls == [
        ("/1/accounts", None),
        ("/1/accounts/42/products", None),
        ("/1/accounts/42/services", None),
    ]


def test_slim_account_projects_useful_fields_only():
    raw = {
        "id": 42,
        "name": "Example Co",
        "type": "owner",
        "legal_entity_type": "company",
        "phone": "+0000000000",
        "website": "https://example.com/",
        "billing": True,
    }

    assert slim_account(raw) == {
        "id": 42,
        "name": "Example Co",
        "type": "owner",
        "legal_entity_type": "company",
    }


def test_slim_product_resolves_name_and_type_from_service_name():
    raw = {"service_name": "drive", "service_id": 40, "id": 123, "customer_name": "Example Co"}

    assert slim_product(raw) == {"id": 123, "name": "drive", "type": "drive"}


def test_slim_product_falls_back_to_customer_name_and_drops_missing_fields():
    assert slim_product({"id": "mail-1"}) == {"id": "mail-1"}
    assert slim_product({"customer_name": "Example Co", "product_id": 9}) == {
        "id": 9,
        "name": "Example Co",
    }


def test_slim_products_projects_each_item():
    raw = [
        {"service_name": "drive", "service_id": 40, "id": 123},
        {"service_name": "kchat", "service_id": 54, "id": 456},
    ]

    assert slim_products(raw) == [
        {"id": 123, "name": "drive", "type": "drive"},
        {"id": 456, "name": "kchat", "type": "kchat"},
    ]


def test_display_item_resolves_product_name_from_service_name():
    rendered = cli._display_item({"service_name": "drive", "service_id": 40, "id": 123})

    assert rendered == "123\tdrive"


def test_cli_account_list_json_uses_profile_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    TokenStore().save_token("work", "secret-token")
    fake_api = FakeAPI(
        {
            "/1/accounts": {
                "result": "success",
                "data": [
                    {
                        "id": 42,
                        "name": "Example Co",
                        "type": "owner",
                        "legal_entity_type": "company",
                        "phone": "+0000000000",
                    }
                ],
            }
        }
    )
    seen_clients = []
    monkeypatch.setattr(
        cli,
        "InformaniakAPIClient",
        lambda token, *, base_url: (seen_clients.append((token, base_url)) or fake_api),
    )

    assert cli.main(["account", "list", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "profile": "work",
        "accounts": [{"id": 42, "name": "Example Co", "type": "owner", "legal_entity_type": "company"}],
    }
    assert "phone" not in output["accounts"][0]
    assert seen_clients == [("secret-token", DEFAULT_BASE_URL)]
    assert fake_api.calls == [("/1/accounts", None)]


def test_cli_account_list_json_raw_emits_full_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    TokenStore().save_token("work", "secret-token")
    raw_account = {
        "id": 42,
        "name": "Example Co",
        "type": "owner",
        "phone": "+0000000000",
        "website": "https://example.com/",
    }
    fake_api = FakeAPI({"/1/accounts": {"result": "success", "data": [raw_account]}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["account", "list", "--json", "--raw"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"profile": "work", "accounts": [raw_account]}


def test_cli_account_products_json_prefers_profile_account_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", account_id="42", make_default=True)
    TokenStore().save_token("work", "secret-token")
    fake_api = FakeAPI({"/1/accounts/42/products": {"result": "success", "data": [{"id": "mail-1"}]}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["account", "products", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"profile": "work", "account_id": "42", "products": [{"id": "mail-1"}]}
    assert fake_api.calls == [("/1/accounts/42/products", None)]


def test_cli_account_products_json_slims_service_name(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", account_id="42", make_default=True)
    TokenStore().save_token("work", "secret-token")
    fake_api = FakeAPI(
        {
            "/1/accounts/42/products": {
                "result": "success",
                "data": [{"service_name": "drive", "service_id": 40, "id": 123, "customer_name": "Example Co"}],
            }
        }
    )
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["account", "products", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "profile": "work",
        "account_id": "42",
        "products": [{"id": 123, "name": "drive", "type": "drive"}],
    }


def test_cli_account_products_json_raw_emits_full_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", account_id="42", make_default=True)
    TokenStore().save_token("work", "secret-token")
    raw_product = {"service_name": "drive", "service_id": 40, "id": 123, "customer_name": "Example Co"}
    fake_api = FakeAPI({"/1/accounts/42/products": {"result": "success", "data": [raw_product]}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["account", "products", "--json", "--raw"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"profile": "work", "account_id": "42", "products": [raw_product]}


def test_cli_account_services_json_allows_explicit_account_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", account_id="42", make_default=True)
    TokenStore().save_token("work", "secret-token")
    fake_api = FakeAPI({"/1/accounts/99/services": {"result": "success", "data": [{"id": "drive-1"}]}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["account", "services", "--account-id", "99", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"profile": "work", "account_id": "99", "services": [{"id": "drive-1"}]}
    assert fake_api.calls == [("/1/accounts/99/services", None)]


def test_cli_account_services_compact_is_single_line_slim_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", account_id="42", make_default=True)
    TokenStore().save_token("work", "secret-token")
    fake_api = FakeAPI({"/1/accounts/42/services": {"result": "success", "data": [{"id": "drive-1"}]}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["account", "services", "--compact"]) == 0

    captured = capsys.readouterr()
    assert "\n" not in captured.out.rstrip("\n")
    assert json.loads(captured.out) == {"profile": "work", "account_id": "42", "services": [{"id": "drive-1"}]}


def test_cli_account_services_table_handles_empty_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", account_id="42", make_default=True)
    TokenStore().save_token("work", "secret-token")
    fake_api = FakeAPI({"/1/accounts/42/services": {"result": "success", "data": []}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    # An empty result with --table must render the header and not crash (regression).
    assert cli.main(["account", "services", "--table"]) == 0

    captured = capsys.readouterr()
    assert captured.out.splitlines()[0].startswith("ID")


def test_cli_account_products_requires_account_id_when_profile_has_none(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    TokenStore().save_token("work", "secret-token")

    assert cli.main(["account", "products"]) == 1

    captured = capsys.readouterr()
    assert "No account selected" in captured.err
    assert "rerun with --account-id" in captured.err


def test_cli_account_list_requires_token(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["account", "list"]) == 1

    captured = capsys.readouterr()
    assert "No token configured for profile: work" in captured.err


def test_cli_admin_accounts_is_not_a_discovery_alias(tmp_path):
    result = run_ik(tmp_path, "admin", "accounts")

    assert result.returncode != 0
    assert "invalid choice" in result.stderr
