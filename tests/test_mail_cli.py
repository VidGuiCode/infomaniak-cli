"""CLI tests for mail commands — fully offline, mocked IMAP."""

from __future__ import annotations

import datetime
import io
import json
import sys
from typing import Any

import pytest

from infomaniak_cli import cli
from infomaniak_cli.auth import MailPasswordStore, TokenStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.mail import MailError


def _validate_iso_date(value):
    if value is None:
        return
    try:
        datetime.datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"invalid date: {value}. Expected YYYY-MM-DD.") from exc


class FakeIMAP:
    """Test double for IMAPClient, injected via the cli module."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.calls = []
        self._opened = False

    def _connect(self):
        self._opened = True

    def _select(self, mailbox="INBOX"):
        self.calls.append(("select", mailbox))

    def list_folders(self):
        return self.responses.get("list_folders", [])

    def list_messages(
        self,
        folder="INBOX",
        limit=None,
        unread_only=False,
        since=None,
        before=None,
        on=None,
        order="newest",
    ):
        for value in (since, before, on):
            _validate_iso_date(value)
        self._select(folder)
        key = "list_messages"
        items = self.responses.get(key, [])
        if unread_only:
            key = "list_unread"
            items = self.responses.get(key, [])
        if limit is not None:
            items = items[:limit]
        # Record call args so tests can inspect criteria
        self.calls.append((
            "list_messages",
            folder,
            limit,
            unread_only,
            since,
            before,
            on,
            order,
        ))
        return items

    def list_unread(self, limit=None, order="newest"):
        return self.list_messages(folder="INBOX", limit=limit, unread_only=True, order=order)

    def search(self, query, folder="INBOX", limit=None, unread_only=False, since=None, before=None, on=None, order="newest"):
        for value in (since, before, on):
            _validate_iso_date(value)
        self._select(folder)
        items = self.responses.get("search", {}).get(query, [])
        if limit is not None:
            items = items[:limit]
        self.calls.append((
            "search",
            query,
            folder,
            limit,
            unread_only,
            since,
            before,
            on,
            order,
        ))
        return items

    def fetch_message(self, uid, folder="INBOX"):
        self._select(folder)
        msg = self.responses.get("fetch_message", {}).get(uid)
        if msg is None:
            raise MailError(f"Message UID {uid} not found")
        return msg

    def list_threads(self, folder="INBOX", limit=None, since=None, before=None, on=None, days=None):
        for value in (since, before, on):
            _validate_iso_date(value)
        self._select(folder)
        threads = self.responses.get("list_threads", [])
        if limit is not None:
            threads = threads[:limit]
        self.calls.append((
            "list_threads",
            folder,
            limit,
            since,
            before,
            on,
            days,
        ))
        return threads

    def close(self):
        self.calls.append("close")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _fake_imap_factory(responses):
    instances = []

    def make_client(host, port, username, password, *, imap_factory=None):
        fake = FakeIMAP(responses)
        fake.calls.append(("init", host, port, username, password))
        instances.append(fake)
        return fake

    make_client.instances = instances
    return make_client


class TestAuthMail:
    def test_auth_mail_stdin_saves_password_and_does_not_echo_it(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", make_default=True)
        password = "secret-mail-password"
        monkeypatch.setattr(sys, "stdin", io.StringIO(f"  {password}\n\n"))

        assert cli.main(["auth", "mail", "--stdin"]) == 0

        captured = capsys.readouterr()
        assert password not in captured.out
        assert password not in captured.err
        assert MailPasswordStore().load_password("work") == password

    def test_auth_mail_argument_saves_password(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", make_default=True)

        assert cli.main(["auth", "mail", "--password", "arg-password"]) == 0

        captured = capsys.readouterr()
        assert "arg-password" not in captured.out
        assert MailPasswordStore().load_password("work") == "arg-password"

    def test_auth_mail_updates_profile_mailbox_and_host(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", make_default=True)

        assert cli.main([
            "auth", "mail",
            "--password", "pw",
            "--mailbox", "user@example.com",
            "--imap-host", "imap.example.com",
            "--imap-port", "995",
        ]) == 0

        profile = ProfileManager().get("work")
        assert profile.default_mailbox == "user@example.com"
        assert profile.imap_host == "imap.example.com"
        assert profile.imap_port == 995


class TestMailUnread:
    def test_mail_unread_requires_mailbox(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        assert cli.main(["mail", "unread"]) == 1

        captured = capsys.readouterr()
        assert "No default mailbox configured" in captured.err
        assert "auth mail" in captured.err

    def test_mail_unread_requires_mail_password(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)

        assert cli.main(["mail", "unread"]) == 1

        captured = capsys.readouterr()
        assert "No mail password configured" in captured.err
        assert "auth mail" in captured.err

    def test_mail_unread_json_uses_mocked_imap(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_unread": [
                {"uid": "101", "from": "a@example.com", "subject": "Hello", "date": "Mon, 01 Jan 2024"},
                {"uid": "102", "from": "b@example.com", "subject": "World", "date": "Tue, 02 Jan 2024"},
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "unread", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"  # resolved current profile
        assert output["folder"] == "INBOX"
        assert output["count"] == 2
        assert len(output["messages"]) == 2
        assert output["messages"][0] == {
            "uid": "101", "from": "a@example.com", "subject": "Hello",
            "date": "Mon, 01 Jan 2024", "seen": False,
        }

    def test_mail_unread_json_raw_emits_full_payload(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_unread": [
                {"uid": "101", "from": "a@example.com", "subject": "Hello", "date": "Mon", "body_preview": "body"},
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "unread", "--json", "--raw"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"
        assert "body_preview" in output["messages"][0]

    def test_mail_unread_limit_honored(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_unread": [
                {"uid": "101", "from": "a@example.com", "subject": "1", "date": "Mon"},
                {"uid": "102", "from": "b@example.com", "subject": "2", "date": "Tue"},
                {"uid": "103", "from": "c@example.com", "subject": "3", "date": "Wed"},
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "unread", "--json", "--limit", "2"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"
        assert output["count"] == 2
        assert len(output["messages"]) == 2

    def test_mail_unread_accepts_folder_filter(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        created_clients = []

        def make_client(host, port, username, password, *, imap_factory=None):
            fake = FakeIMAP({"list_unread": []})
            created_clients.append(fake)
            return fake

        monkeypatch.setattr(cli, "IMAPClient", make_client)

        assert cli.main(["mail", "unread", "--folder", "Sent", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "Sent"
        assert ("list_messages", "Sent", 20, True, None, None, None, "newest") in created_clients[0].calls

    def test_mail_unread_accepts_folder_short_option(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        created_clients = []

        def make_client(host, port, username, password, *, imap_factory=None):
            fake = FakeIMAP({"list_unread": []})
            created_clients.append(fake)
            return fake

        monkeypatch.setattr(cli, "IMAPClient", make_client)

        assert cli.main(["mail", "unread", "-f", "Archive", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "Archive"
        assert ("list_messages", "Archive", 20, True, None, None, None, "newest") in created_clients[0].calls

    def test_mail_unread_accepts_days_filter(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")
        monkeypatch.setattr(cli, "_today", lambda: datetime.date(2026, 6, 22))
        created_clients = []

        def make_client(host, port, username, password, *, imap_factory=None):
            fake = FakeIMAP({"list_unread": []})
            created_clients.append(fake)
            return fake

        monkeypatch.setattr(cli, "IMAPClient", make_client)

        assert cli.main(["mail", "unread", "--days", "7", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "INBOX"
        assert ("list_messages", "INBOX", 20, True, "2026-06-15", None, None, "newest") in created_clients[0].calls

    def test_mail_unread_accepts_since_and_before_filters(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")
        created_clients = []

        def make_client(host, port, username, password, *, imap_factory=None):
            fake = FakeIMAP({"list_unread": []})
            created_clients.append(fake)
            return fake

        monkeypatch.setattr(cli, "IMAPClient", make_client)

        assert cli.main([
            "mail", "unread",
            "--since", "2026-06-01",
            "--before", "2026-06-15",
            "--json",
        ]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "INBOX"
        assert (
            "list_messages",
            "INBOX",
            20,
            True,
            "2026-06-01",
            "2026-06-15",
            None,
            "newest",
        ) in created_clients[0].calls

    def test_mail_unread_accepts_limit_short_option(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")
        created_clients = []

        def make_client(host, port, username, password, *, imap_factory=None):
            fake = FakeIMAP({"list_unread": []})
            created_clients.append(fake)
            return fake

        monkeypatch.setattr(cli, "IMAPClient", make_client)

        assert cli.main(["mail", "unread", "-n", "3", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 0
        assert ("list_messages", "INBOX", 3, True, None, None, None, "newest") in created_clients[0].calls

    def test_mail_unread_accepts_oldest_first_option(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")
        created_clients = []

        def make_client(host, port, username, password, *, imap_factory=None):
            fake = FakeIMAP({"list_unread": []})
            created_clients.append(fake)
            return fake

        monkeypatch.setattr(cli, "IMAPClient", make_client)

        assert cli.main(["mail", "unread", "--oldest-first", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 0
        assert ("list_messages", "INBOX", 20, True, None, None, None, "oldest") in created_clients[0].calls

    def test_mail_unread_human_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_unread": [
                {"uid": "101", "from": "sender@example.com", "subject": "Invoice", "date": "Mon"},
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "unread"]) == 0

        out = capsys.readouterr().out
        assert "Unread messages in INBOX: 1" in out
        assert "101" in out
        assert "Invoice" in out


class TestMailSearch:
    def test_mail_search_json(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "search": {
                "invoice": [
                    {"uid": "201", "from": "boss@example.com", "subject": "Invoice due", "date": "Mon"},
                ],
            },
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "search", "invoice", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"
        assert output["query"] == "invoice"
        assert output["folder"] == "INBOX"
        assert output["count"] == 1
        assert output["messages"][0]["uid"] == "201"

    def test_mail_search_limit(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "search": {
                "q": [
                    {"uid": "301", "from": "a", "subject": "1", "date": "Mon"},
                    {"uid": "302", "from": "b", "subject": "2", "date": "Tue"},
                ],
            },
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "search", "q", "--json", "--limit", "1"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"
        assert output["count"] == 1
        assert len(output["messages"]) == 1

    def test_mail_search_missing_config(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", make_default=True)

        assert cli.main(["mail", "search", "invoice"]) == 1

        captured = capsys.readouterr()
        assert "No default mailbox configured" in captured.err


class TestMailRead:
    def test_mail_read_json(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "fetch_message": {
                "555": {
                    "uid": "555",
                    "from": "sender@example.com",
                    "to": "user@example.com",
                    "subject": "Full message",
                    "date": "Mon",
                    "body_preview": "The full body.",
                },
            },
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "read", "555", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["uid"] == "555"
        assert output["message"]["uid"] == "555"
        assert output["message"]["from"] == "sender@example.com"
        assert "body_preview" not in output["message"]  # slim mode by default

    def test_mail_read_raw_json(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "fetch_message": {
                "555": {
                    "uid": "555",
                    "from": "sender@example.com",
                    "to": "user@example.com",
                    "subject": "Full",
                    "date": "Mon",
                    "body_preview": "The full body.",
                    "message_id": "<msg@example.com>",
                },
            },
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "read", "555", "--json", "--raw"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert "body_preview" in output["message"]

    def test_mail_read_human_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "fetch_message": {
                "555": {
                    "uid": "555",
                    "from": "sender@example.com",
                    "to": "user@example.com",
                    "subject": "Subject line",
                    "date": "Mon, 01 Jan 2024",
                    "body_preview": "Hello world",
                },
            },
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "read", "555"]) == 0

        out = capsys.readouterr().out
        assert "UID: 555" in out
        assert "From: sender@example.com" in out
        assert "Subject: Subject line" in out
        assert "Hello world" in out

    def test_mail_read_not_found(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"fetch_message": {}}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "read", "999", "--json"]) == 1

        captured = capsys.readouterr()
        assert "not found" in captured.err


class TestMailProfileOverride:
    def test_mail_unread_with_explicit_profile(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="work@example.com", make_default=True)
        ProfileManager().create_or_update("personal", default_mailbox="personal@example.com")
        MailPasswordStore().save_password("work", "work-pw")
        MailPasswordStore().save_password("personal", "personal-pw")

        fake_responses = {"list_unread": []}
        seen = []

        def make_client(host, port, username, password, *, imap_factory=None):
            seen.append((username, password))
            fake = FakeIMAP(fake_responses)
            return fake

        monkeypatch.setattr(cli, "IMAPClient", make_client)

        assert cli.main(["--profile", "personal", "mail", "unread", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "personal"
        assert seen == [("personal@example.com", "personal-pw")]


class TestMailFolders:
    def test_mail_folders_json_slim(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_folders": [
                {"name": "INBOX", "separator": "/", "flags": [r"\Inbox"], "role": "inbox"},
                {"name": "Sent", "separator": "/", "flags": [r"\Sent"], "role": "sent"},
                {"name": "Junk Mail", "separator": "/", "flags": [r"\Junk"], "role": "junk"},
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "folders", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"
        assert output["count"] == 3
        assert output["folders"] == [
            {"name": "INBOX", "role": "inbox"},
            {"name": "Sent", "role": "sent"},
            {"name": "Junk Mail", "role": "junk"},
        ]

    def test_mail_labels_alias(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_folders": [{"name": "INBOX", "role": "inbox"}]}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "labels", "--json"]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 1

    def test_mail_folders_raw_json(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        folder = {"name": "INBOX", "separator": "/", "flags": [r"\Inbox"], "role": "inbox"}
        fake_responses = {"list_folders": [folder]}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "folders", "--json", "--raw"]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["folders"][0] == folder

    def test_mail_folders_human_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_folders": [
                {"name": "INBOX", "separator": "/", "flags": [r"\Inbox"], "role": "inbox"},
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "folders"]) == 0
        out = capsys.readouterr().out
        assert "Profile: work" in out
        assert "Folders: 1" in out
        assert "INBOX (inbox)" in out


class TestMailList:
    def test_mail_list_defaults_to_inbox_and_limit(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_messages": [
                {"uid": "1", "from": "a@example.com", "subject": "s1", "date": "Mon", "seen": True},
                {"uid": "2", "from": "b@example.com", "subject": "s2", "date": "Tue", "seen": False},
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "list", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"
        assert output["folder"] == "INBOX"
        assert output["count"] == 2
        assert output["messages"][0]["seen"] is True

    def test_mail_list_defaults_to_newest_order(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_messages": []}
        factory = _fake_imap_factory(fake_responses)
        monkeypatch.setattr(cli, "IMAPClient", factory)

        assert cli.main(["mail", "list", "--limit", "10", "--json"]) == 0

        fake = factory.instances[0]
        assert fake.calls[-2] == ("list_messages", "INBOX", 10, False, None, None, None, "newest")

    def test_mail_list_oldest_first_option(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_messages": []}
        factory = _fake_imap_factory(fake_responses)
        monkeypatch.setattr(cli, "IMAPClient", factory)

        assert cli.main(["mail", "list", "--limit", "10", "--oldest-first", "--json"]) == 0

        fake = factory.instances[0]
        assert fake.calls[-2] == ("list_messages", "INBOX", 10, False, None, None, None, "oldest")

    def test_mail_list_folder_option(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_messages": []}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "list", "--folder", "Spam", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "Spam"

    def test_mail_list_unread_only(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_messages": []}
        factory = _fake_imap_factory(fake_responses)
        monkeypatch.setattr(cli, "IMAPClient", factory)

        assert cli.main(["mail", "list", "--unread", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "INBOX"

    def test_mail_list_days_computes_since(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_messages": []}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))
        # Freeze today to 2026-06-22; --days 5 => since 2026-06-17
        monkeypatch.setattr(cli, "_today", lambda: __import__("datetime").date(2026, 6, 22))

        assert cli.main(["mail", "list", "--days", "5", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "INBOX"
        assert output["count"] == 0

    def test_mail_list_since_before_validate_and_pass(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_messages": []}
        factory = _fake_imap_factory(fake_responses)
        monkeypatch.setattr(cli, "IMAPClient", factory)

        assert cli.main(["mail", "list", "--since", "2026-06-01", "--before", "2026-06-15", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "INBOX"

    def test_mail_list_days_and_since_errors(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_messages": []}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "list", "--days", "5", "--since", "2026-06-01", "--json"]) == 2

        captured = capsys.readouterr()
        assert "use either --days or --since" in captured.err

    def test_mail_list_invalid_date_errors(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_messages": []}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "list", "--since", "not-a-date", "--json"]) == 1

        captured = capsys.readouterr()
        assert "invalid date" in captured.err


class TestMailSearchExtended:
    def test_mail_search_with_folder_and_days(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "search": {
                "invoice": [
                    {"uid": "501", "from": "acct@example.com", "subject": "Invoice", "date": "Mon", "seen": False},
                ],
            },
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))
        monkeypatch.setattr(cli, "_today", lambda: __import__("datetime").date(2026, 6, 22))

        assert cli.main(["mail", "search", "invoice", "--folder", "Archive", "--days", "30", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"
        assert output["folder"] == "Archive"
        assert output["query"] == "invoice"
        assert output["count"] == 1
        assert output["messages"][0]["uid"] == "501"

    def test_mail_search_unread_and_dates(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"search": {"query": []}}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main([
            "mail", "search", "query", "--unread",
            "--since", "2026-06-01", "--before", "2026-06-15", "--json",
        ]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "INBOX"
        assert output["count"] == 0

    def test_mail_search_days_and_since_errors(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"search": {"invoice": []}}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "search", "invoice", "--days", "5", "--since", "2026-06-01", "--json"]) == 2

        captured = capsys.readouterr()
        assert "use either --days or --since" in captured.err




class TestMailReadFolder:
    def test_mail_read_default_folder_is_inbox(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "fetch_message": {
                "555": {
                    "uid": "555",
                    "from": "sender@example.com",
                    "to": "user@example.com",
                    "subject": "Subject line",
                    "date": "Mon, 01 Jan 2024",
                    "body_preview": "Hello world",
                },
            },
        }
        factory = _fake_imap_factory(fake_responses)
        seen = []

        def tracking_factory(host, port, username, password, *, imap_factory=None):
            fake = factory(host, port, username, password, imap_factory=imap_factory)
            original_fetch = fake.fetch_message

            def tracking_fetch(uid, folder="INBOX"):
                seen.append(folder)
                return original_fetch(uid, folder=folder)

            fake.fetch_message = tracking_fetch
            return fake

        monkeypatch.setattr(cli, "IMAPClient", tracking_factory)

        assert cli.main(["mail", "read", "555", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"
        assert output["uid"] == "555"
        assert output["folder"] == "INBOX"
        assert output["message"]["uid"] == "555"
        assert seen == ["INBOX"]

    def test_mail_read_folder_option_selects_folder(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "fetch_message": {
                "555": {
                    "uid": "555",
                    "from": "sender@example.com",
                    "to": "user@example.com",
                    "subject": "Spam item",
                    "date": "Mon, 01 Jan 2024",
                    "body_preview": "Spam body",
                },
            },
        }
        factory = _fake_imap_factory(fake_responses)
        seen = []

        def tracking_factory(host, port, username, password, *, imap_factory=None):
            fake = factory(host, port, username, password, imap_factory=imap_factory)
            original_fetch = fake.fetch_message

            def tracking_fetch(uid, folder="INBOX"):
                seen.append(folder)
                return original_fetch(uid, folder=folder)

            fake.fetch_message = tracking_fetch
            return fake

        monkeypatch.setattr(cli, "IMAPClient", tracking_factory)

        assert cli.main(["mail", "read", "555", "--folder", "Spam", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "Spam"
        assert output["message"]["subject"] == "Spam item"
        assert seen == ["Spam"]

    def test_mail_read_human_output_shows_folder(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "fetch_message": {
                "555": {
                    "uid": "555",
                    "from": "sender@example.com",
                    "to": "user@example.com",
                    "subject": "Subject line",
                    "date": "Mon, 01 Jan 2024",
                    "body_preview": "Hello world",
                },
            },
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "read", "555", "--folder", "Sent"]) == 0

        out = capsys.readouterr().out
        assert "Folder: Sent" in out
        assert "UID: 555" in out



class TestMailThreads:
    def test_mail_threads_json_groups_messages(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_threads": [
                {
                    "thread_id": "<root@example.com>",
                    "subject": "Project kickoff",
                    "message_count": 2,
                    "newest_date": "Tue, 02 Jan 2024",
                    "newest_uid": "102",
                    "messages": [
                        {"uid": "101", "from": "a@example.com", "subject": "Project kickoff", "date": "Mon, 01 Jan 2024", "seen": True},
                        {"uid": "102", "from": "b@example.com", "subject": "Re: Project kickoff", "date": "Tue, 02 Jan 2024", "seen": False},
                    ],
                },
                {
                    "thread_id": "<other@example.com>",
                    "subject": "Invoice",
                    "message_count": 1,
                    "newest_date": "Wed, 03 Jan 2024",
                    "newest_uid": "103",
                    "messages": [
                        {"uid": "103", "from": "c@example.com", "subject": "Invoice", "date": "Wed, 03 Jan 2024", "seen": True},
                    ],
                },
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "threads", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["profile"] == "work"
        assert output["folder"] == "INBOX"
        assert output["count"] == 2
        assert len(output["threads"]) == 2
        assert output["threads"][0]["thread_id"] == "<root@example.com>"
        assert output["threads"][0]["message_count"] == 2
        assert output["threads"][0]["messages"][0] == {
            "uid": "101", "from": "a@example.com", "subject": "Project kickoff",
            "date": "Mon, 01 Jan 2024", "seen": True,
        }

    def test_mail_threads_folder_and_days(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_threads": []}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))
        monkeypatch.setattr(cli, "_today", lambda: __import__("datetime").date(2026, 6, 22))

        assert cli.main(["mail", "threads", "--folder", "Sent", "--days", "7", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["folder"] == "Sent"
        assert output["count"] == 0

    def test_mail_threads_limit(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_threads": [
                {"thread_id": "t1", "subject": "A", "message_count": 1, "newest_date": "Mon", "newest_uid": "2", "messages": []},
                {"thread_id": "t2", "subject": "B", "message_count": 1, "newest_date": "Mon", "newest_uid": "1", "messages": []},
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "threads", "--limit", "1", "--json"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert output["count"] == 1

    def test_mail_threads_raw_includes_full_messages(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_threads": [
                {
                    "thread_id": "t1",
                    "subject": "A",
                    "message_count": 1,
                    "newest_date": "Mon",
                    "newest_uid": "1",
                    "messages": [
                        {"uid": "1", "from": "a@example.com", "subject": "A", "date": "Mon", "seen": True, "in_reply_to": "<x@example.com>"},
                    ],
                },
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "threads", "--json", "--raw"]) == 0

        output = json.loads(capsys.readouterr().out)
        assert "in_reply_to" in output["threads"][0]["messages"][0]

    def test_mail_threads_human_output(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {
            "list_threads": [
                {
                    "thread_id": "<root@example.com>",
                    "subject": "Project kickoff",
                    "message_count": 1,
                    "newest_date": "Mon, 01 Jan 2024",
                    "newest_uid": "101",
                    "messages": [
                        {"uid": "101", "from": "a@example.com", "subject": "Project kickoff", "date": "Mon, 01 Jan 2024", "seen": True},
                    ],
                },
            ],
        }
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "threads"]) == 0

        out = capsys.readouterr().out
        assert "Threads in INBOX: 1" in out
        assert "Project kickoff" in out
        assert "101" in out

    def test_mail_threads_days_and_since_errors(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
        ProfileManager().create_or_update("work", default_mailbox="user@example.com", make_default=True)
        MailPasswordStore().save_password("work", "pw")

        fake_responses = {"list_threads": []}
        monkeypatch.setattr(cli, "IMAPClient", _fake_imap_factory(fake_responses))

        assert cli.main(["mail", "threads", "--days", "5", "--since", "2026-06-01", "--json"]) == 2

        captured = capsys.readouterr()
        assert "use either --days or --since" in captured.err

