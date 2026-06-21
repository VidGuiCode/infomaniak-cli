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


def test_bootstrap_auto_selects_single_account_and_saves_discovered_defaults(tmp_path):
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
            "/1/my_ksuite/current": {"result": "success", "data": {"id": "ksuite-1"}},
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
        ("/1/my_ksuite/current", None),
        ("/1/mail_hostings/mail-1/mailboxes", None),
        ("/2/drive", None),
        ("/api/v4/teams", None),
    ]
    profile = manager.get("cylro")
    assert profile.informaniak_user == "gui@example.com"
    assert profile.account_id == "42"
    assert profile.account_name == "Cylro SARL-S"
    assert profile.mail_hosting_id == "mail-1"
    assert profile.default_drive_id == "drive-1"
    assert profile.default_drive_name == "Cylro Documents"
    assert profile.kchat_team_id == "chat-1"
    assert profile.ksuite_id == "ksuite-1"


def test_bootstrap_enriches_mailbox_drive_and_kchat_defaults_from_optional_endpoints(tmp_path):
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
            "/1/my_ksuite/current": {"result": "success", "data": {"id": "ksuite-1"}},
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
                    {"id": "drive-1", "name": "Cylro Documents"},
                    {"id": "drive-2", "name": "Shared Admin"},
                ],
            },
            "/api/v4/teams": {
                "result": "success",
                "data": [{"id": "team-1", "display_name": "Cylro"}],
            },
        }
    )

    result = bootstrap_profile("cylro", api, manager=manager, non_interactive=True)

    assert result["default_mailbox"] == "contact@cylro.com"
    assert result["default_drive"] == {"id": "drive-1", "name": "Cylro Documents"}
    assert result["kchat_team_id"] == "team-1"
    assert api.calls == [
        ("/2/profile", None),
        ("/1/accounts", None),
        ("/1/accounts/42/products", None),
        ("/1/accounts/42/services", None),
        ("/1/my_ksuite/current", None),
        ("/1/mail_hostings/mail-hosting-1/mailboxes", None),
        ("/2/drive", None),
        ("/api/v4/teams", None),
    ]
    profile = manager.get("cylro")
    assert profile.mail_hosting_id == "mail-hosting-1"
    assert profile.default_mailbox == "contact@cylro.com"
    assert profile.default_drive_id == "drive-1"
    assert profile.default_drive_name == "Cylro Documents"
    assert profile.kchat_team_id == "team-1"


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
            "/1/my_ksuite/current": {"result": "success", "data": {"id": "ksuite-1"}},
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
            "/1/my_ksuite/current": {"result": "success", "data": {}},
        }
    )

    bootstrap_profile("cylro", api, manager=manager, account_id="42", non_interactive=True)

    assert manager.get("cylro").account_name == "Cylro SARL-S"
