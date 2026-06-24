import json

from infomaniak_cli import cli
from infomaniak_cli.auth import CalendarPasswordStore, ContactsPasswordStore, MailPasswordStore, TokenStore
from infomaniak_cli.profiles import ProfileManager


class FakeBootstrapAPI:
    def __init__(self):
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        responses = {
            "/2/profile": {"result": "success", "data": {"email": "user@example.com"}},
            "/1/accounts": {"result": "success", "data": [{"id": 42, "name": "Example Co"}]},
            "/1/accounts/42/products": {
                "result": "success",
                "data": [{"id": "mail-1", "name": "Example Mail", "type": "mail_hosting"}],
            },
            "/1/accounts/42/services": {
                "result": "success",
                "data": [{"id": "drive-service", "name": "kDrive", "service_type": "kdrive"}],
            },
            "/1/mail_hostings/mail-1/mailboxes": {
                "result": "success",
                "data": [{"id": "mbox-1", "email": "user@example.com"}],
            },
            "/2/drive": {
                "result": "success",
                "data": [{"id": "drive-1", "name": "Work Drive", "account_id": 42, "product_id": 3000001}],
            },
        }
        return responses[path]


def test_bootstrap_json_outputs_readiness_summary_and_setup_actions(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    TokenStore().save_token("work", "secret-main-token")
    MailPasswordStore().save_password("work", "secret-mail-password")
    fake_api = FakeBootstrapAPI()
    monkeypatch.setattr(cli, "_make_api_client", lambda token, base_url: fake_api)

    assert cli.main(["bootstrap", "--json", "--non-interactive"]) == 0

    captured = capsys.readouterr()
    assert "secret-main-token" not in captured.out
    assert "secret-mail-password" not in captured.out
    output = json.loads(captured.out)
    assert output["profile"] == "work"
    assert output["auth"]["main_api_token_configured"] is True
    assert output["account"] == {"id": "42", "name": "Example Co", "selected": True}
    assert output["mail"]["default_mailbox"] == "user@example.com"
    assert output["mail"]["mail_password_configured"] is True
    assert output["mail"]["imap_ready"] is True
    assert output["drive"]["default_drive"] == {"id": "drive-1", "name": "Work Drive"}
    assert output["contacts"]["configured"] is False
    assert output["calendar"]["configured"] is False
    assert output["chat"]["configured"] is False
    assert output["missing_setup_actions"] == [
        "ik auth contacts --username user@example.com --stdin",
        "ik auth calendar --username user@example.com --stdin",
        "ik auth chat --url <ksuite-kchat-url>",
    ]


def test_bootstrap_compact_outputs_single_line_readiness_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)
    TokenStore().save_token("work", "secret-main-token")
    monkeypatch.setattr(cli, "_make_api_client", lambda token, base_url: FakeBootstrapAPI())

    assert cli.main(["bootstrap", "--compact", "--non-interactive"]) == 0

    captured = capsys.readouterr()
    assert "\n" not in captured.out.rstrip("\n")
    output = json.loads(captured.out)
    assert output["profile"] == "work"
    assert output["mail"]["setup_action"] == (
        "ik auth mail --mailbox user@example.com --password <device-password>"
    )


def test_whoami_json_readiness_fields_do_not_leak_secrets(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        account_id="42",
        account_name="Example Co",
        default_mailbox="user@example.com",
        default_drive_id="drive-1",
        default_drive_name="Work Drive",
        contacts_url="https://sync.example.test/addressbooks/user/default/",
        contacts_username="user@example.com",
        calendar_url="https://sync.example.test/calendars/user/work/",
        calendar_username="user@example.com",
        kchat_url="https://cylro.kchat.infomaniak.com",
        make_default=True,
    )
    TokenStore().save_token("work", "secret-main-token")
    ContactsPasswordStore().save_password("work", "secret-contacts-password")
    CalendarPasswordStore().save_password("work", "secret-calendar-password")

    assert cli.main(["whoami", "--json"]) == 0

    captured = capsys.readouterr()
    assert "secret-main-token" not in captured.out
    assert "secret-contacts-password" not in captured.out
    assert "secret-calendar-password" not in captured.out
    output = json.loads(captured.out)
    assert output["readiness"]["auth"]["main_api_token_configured"] is True
    assert output["readiness"]["mail"]["imap_ready"] is False
    assert output["readiness"]["contacts"]["ready"] is True
    assert output["readiness"]["calendar"]["ready"] is True
    assert output["readiness"]["chat"]["main_token_fallback_possible"] is True


def test_doctor_compact_reports_missing_setup_actions(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        account_id="42",
        account_name="Example Co",
        default_mailbox="user@example.com",
        make_default=True,
    )
    TokenStore().save_token("work", "secret-main-token")

    assert cli.main(["doctor", "--compact"]) == 0

    captured = capsys.readouterr()
    assert "secret-main-token" not in captured.out
    assert "\n" not in captured.out.rstrip("\n")
    output = json.loads(captured.out)
    checks = output["checks"]
    assert checks["token_configured"] is True
    assert checks["mail_password_configured"] is False
    assert checks["contacts_configured"] is False
    assert checks["calendar_configured"] is False
    assert checks["chat_configured"] is False
    assert "ik auth mail --mailbox user@example.com --password <device-password>" in output["missing_setup_actions"]
    assert "ik auth contacts --username user@example.com --stdin" in output["missing_setup_actions"]
    assert "ik auth calendar --username user@example.com --stdin" in output["missing_setup_actions"]
