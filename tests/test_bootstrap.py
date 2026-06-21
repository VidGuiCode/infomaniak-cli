import pytest

from infomaniak_cli.bootstrap import BootstrapError, bootstrap_profile
from infomaniak_cli.profiles import ProfileManager


class FakeAPI:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        return self.responses[path]


def test_bootstrap_auto_selects_single_account_and_saves_discovered_account_defaults(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("cylro", make_default=True)
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {
                "result": "success",
                "data": [{"id": "mail-1", "name": "Cylro Mail", "type": "mail_hosting"}],
            },
            "/1/accounts/42/services": {
                "result": "success",
                "data": [
                    {"id": "drive-1", "name": "Cylro Documents", "service_type": "kdrive"},
                    {"id": "chat-1", "name": "Cylro Chat", "service_type": "kchat"},
                ],
            },
            "/2/drive": {"result": "success", "data": []},
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["profile"] == "cylro"
    assert result["account"]["id"] == "42"
    assert result["informaniak_user"] == "gui@example.com"
    assert api.calls == [
        ("/2/profile", None),
        ("/1/accounts", None),
        ("/1/accounts/42/products", None),
        ("/1/accounts/42/services", None),
        ("/1/mail_hostings/mail-1/mailboxes", None),
        ("/2/drive", {"account_id": "42"}),
    ]
    profile = manager.get("cylro")
    assert profile.informaniak_user == "gui@example.com"
    assert profile.account_id == "42"
    assert profile.account_name == "Cylro SARL-S"
    assert profile.mail_hosting_id == "mail-1"
    assert profile.default_drive_id is None
    assert profile.default_drive_name is None
    assert profile.kchat_team_id is None
    assert profile.ksuite_id is None


def test_bootstrap_enriches_mailbox_and_drive_defaults_from_optional_endpoints(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("cylro", make_default=True)
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {
                "result": "success",
                "data": [{"id": "mail-hosting-1", "name": "Cylro Mail", "type": "mail_hosting"}],
            },
            "/1/accounts/42/services": {
                "result": "success",
                "data": [{"id": "kchat-service-1", "name": "Cylro Chat", "service_type": "kchat"}],
            },
            "/1/mail_hostings/mail-hosting-1/mailboxes": {
                "result": "success",
                "data": [
                    {"id": "mbox-1", "email": "contact@cylro.com"},
                    {"id": "mbox-2", "email": "admin@cylro.com"},
                ],
            },
            "/2/drive": {
                "result": "success",
                "data": [
                    {
                        "id": 777,
                        "name": "Cylro Documents",
                        "account_id": 42,
                        "product_id": 3000001,
                        "role": "admin",
                        "size": 1000,
                        "used_size": 10,
                        "status": "active",
                    },
                    {
                        "id": 778,
                        "name": "Shared Admin",
                        "account_id": 42,
                        "product_id": 3000002,
                    },
                ],
            },
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["default_mailbox"] == "contact@cylro.com"
    assert result["default_drive"] == {"id": "777", "name": "Cylro Documents"}
    assert result["kchat_team_id"] is None
    assert api.calls == [
        ("/2/profile", None),
        ("/1/accounts", None),
        ("/1/accounts/42/products", None),
        ("/1/accounts/42/services", None),
        ("/1/mail_hostings/mail-hosting-1/mailboxes", None),
        ("/2/drive", {"account_id": "42"}),
    ]
    profile = manager.get("cylro")
    assert profile.mail_hosting_id == "mail-hosting-1"
    assert profile.default_mailbox == "contact@cylro.com"
    assert profile.default_drive_id == "777"
    assert profile.default_drive_name == "Cylro Documents"
    assert profile.kchat_team_id is None


def test_bootstrap_finds_drive_with_account_filtered_drive_endpoint(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("cylro", make_default=True)
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {"result": "success", "data": []},
            "/1/accounts/42/services": {"result": "success", "data": []},
            "/2/drive": {
                "result": "success",
                "data": [{"id": 777, "name": "Cylro Drive", "account_id": 42, "product_id": 3000001}],
            },
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["default_drive"] == {"id": "777", "name": "Cylro Drive"}
    assert api.calls == [
        ("/2/profile", None),
        ("/1/accounts", None),
        ("/1/accounts/42/products", None),
        ("/1/accounts/42/services", None),
        ("/2/drive", {"account_id": "42"}),
    ]
    profile = manager.get("cylro")
    assert profile.default_drive_id == "777"
    assert profile.default_drive_name == "Cylro Drive"


def test_bootstrap_keeps_drive_null_when_drive_endpoint_is_empty(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update(
        "cylro",
        default_drive_id="40",
        default_drive_name="drive",
        make_default=True,
    )
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {
                "result": "success",
                "data": [{"id": 3000001, "service_id": 40, "service_name": "drive"}],
            },
            "/1/accounts/42/services": {
                "result": "success",
                "data": [{"id": 40, "name": "drive", "count": 1}],
            },
            "/2/drive": {"result": "success", "data": []},
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["default_drive"] == {"id": None, "name": None}
    profile = manager.get("cylro")
    assert profile.default_drive_id is None
    assert profile.default_drive_name is None


def test_bootstrap_rejects_product_shaped_drive_endpoint_response(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update(
        "cylro",
        default_drive_id="3000001",
        default_drive_name="example.com",
        make_default=True,
    )
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {
                "result": "success",
                "data": [{"id": 3000001, "service_id": 40, "service_name": "drive", "customer_name": "example.com"}],
            },
            "/1/accounts/42/services": {
                "result": "success",
                "data": [{"id": 40, "name": "drive", "count": 1}],
            },
            "/2/drive": {
                "result": "success",
                "data": [{"id": 3000001, "service_id": 40, "service_name": "drive", "customer_name": "example.com"}],
            },
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["default_drive"] == {"id": None, "name": None}
    profile = manager.get("cylro")
    assert profile.default_drive_id is None
    assert profile.default_drive_name is None


def test_bootstrap_rejects_drive_response_without_real_drive_id(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("cylro", default_drive_id="3000001", make_default=True)
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {"result": "success", "data": []},
            "/1/accounts/42/services": {"result": "success", "data": []},
            "/2/drive": {
                "result": "success",
                "data": [{"product_id": 3000001, "name": "Cylro Drive", "account_id": 42}],
            },
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["default_drive"] == {"id": None, "name": None}
    assert manager.get("cylro").default_drive_id is None


def test_bootstrap_leaves_kchat_team_null_without_probing_main_api(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("cylro", kchat_team_id="54", make_default=True)
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {
                "result": "success",
                "data": [{"id": 3000002, "service_id": 54, "service_name": "kchat"}],
            },
            "/1/accounts/42/services": {
                "result": "success",
                "data": [{"id": 54, "name": "kchat", "count": 1}],
            },
            "/2/drive": {"result": "success", "data": []},
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["kchat_team_id"] is None
    assert result["counts"]["kchat_teams"] == 0
    assert all("kchat" not in path.lower() and "api/v4" not in path.lower() for path, _ in api.calls)
    assert manager.get("cylro").kchat_team_id is None


def test_bootstrap_continues_when_optional_service_endpoints_are_missing(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("cylro", make_default=True)
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {
                "result": "success",
                "data": [{"id": "mail-hosting-1", "name": "Cylro Mail", "type": "mail_hosting"}],
            },
            "/1/accounts/42/services": {"result": "success", "data": []},
            "/2/drive": {"result": "success", "data": []},
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["mail_hosting_id"] == "mail-hosting-1"
    assert result["default_mailbox"] is None
    assert result["default_drive"] == {"id": None, "name": None}
    assert result["kchat_team_id"] is None
    profile = manager.get("cylro")
    assert profile.mail_hosting_id == "mail-hosting-1"
    assert profile.default_mailbox is None
    assert profile.default_drive_id is None
    assert profile.default_drive_name is None
    assert profile.kchat_team_id is None


def test_bootstrap_does_not_save_service_catalog_ids_as_resource_defaults(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update(
        "cylro",
        default_drive_id="40",
        default_drive_name="drive",
        kchat_team_id="54",
        make_default=True,
    )
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Cylro SARL-S"}]},
            "/1/accounts/42/products": {
                "result": "success",
                "data": [
                    {"id": 3000001, "service_id": 40, "service_name": "drive", "customer_name": "example.com"},
                    {"id": 3000002, "service_id": 54, "service_name": "kchat", "customer_name": "example.com"},
                    {"id": 3000003, "service_id": 23, "service_name": "email_hosting", "customer_name": "example.com"},
                ],
            },
            "/1/accounts/42/services": {
                "result": "success",
                "data": [
                    {"id": 23, "name": "email_hosting", "count": 1},
                    {"id": 40, "name": "drive", "count": 1},
                    {"id": 54, "name": "kchat", "count": 1},
                ],
            },
            "/1/mail_hostings/3000003/mailboxes": {
                "result": "success",
                "data": [{"id": "mbox-1", "email": "gui@example.com"}],
            },
            "/2/drive": {"result": "success", "data": []},
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["mail_hosting_id"] == "3000003"
    assert result["default_mailbox"] == "gui@example.com"
    assert result["default_drive"] == {"id": None, "name": None}
    assert result["kchat_team_id"] is None
    profile = manager.get("cylro")
    assert profile.default_drive_id is None
    assert profile.default_drive_name is None
    assert profile.kchat_team_id is None
    assert all("my_ksuite" not in path for path, _ in api.calls)
    assert all("kchat" not in path.lower() and "api/v4" not in path.lower() for path, _ in api.calls)


def test_bootstrap_non_interactive_requires_account_id_when_multiple_accounts(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("cylro", make_default=True)
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {
                "result": "success",
                "data": [
                    {"id": 1, "name": "Personal"},
                    {"id": 42, "name": "Cylro SARL-S"},
                ],
            },
        }
    )

    with pytest.raises(BootstrapError) as exc_info:
        bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    message = str(exc_info.value)
    assert "Multiple accounts found" in message
    assert "1: Personal" in message
    assert "42: Cylro SARL-S" in message


def test_bootstrap_uses_explicit_account_id_when_multiple_accounts(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("cylro", make_default=True)
    api = FakeAPI(
        {
            "/2/profile": {"result": "success", "data": {"email": "gui@example.com"}},
            "/1/accounts": {
                "result": "success",
                "data": [
                    {"id": 1, "name": "Personal"},
                    {"id": 42, "name": "Cylro SARL-S"},
                ],
            },
            "/1/accounts/42/products": {"result": "success", "data": []},
            "/1/accounts/42/services": {"result": "success", "data": []},
            "/2/drive": {"result": "success", "data": []},
        }
    )

    bootstrap_profile("cylro", api, manager=manager, account_id="42", non_interactive=True)

    assert manager.get("cylro").account_name == "Cylro SARL-S"
