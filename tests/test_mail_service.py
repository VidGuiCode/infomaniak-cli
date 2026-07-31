"""Tests for the IMAP mail service — fully offline, no real network calls."""

from __future__ import annotations

import email.message
import email.policy
import imaplib
from typing import Any

import pytest

from infomaniak_cli.services.mail import (
    IMAPClient,
    MailError,
    SMTPClient,
    _body_preview,
    _body_text,
    _decode_header_value,
    _extract_text_body,
    _html_to_text,
    build_forward,
    build_mail_message,
    build_reply,
    extract_attachment,
    list_attachments,
    slim_message,
)


class FakeIMAP:
    """Test double that mimics the subset of imaplib.IMAP4_SSL used by IMAPClient."""

    def __init__(self, responses: dict[str, Any] | None = None, fail_login: bool = False):
        self.responses = responses or {}
        self.fail_login = fail_login
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._logged_in = False
        self._selected = False

    def login(self, username: str, password: str) -> None:
        self.calls.append(("login", (username, password)))
        if self.fail_login:
            raise imaplib.IMAP4.error("authentication failed")
        self._logged_in = True

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list]:
        self.calls.append(("select", (mailbox, readonly)))
        self._selected = True
        return self.responses.get("select", ("OK", [b"10"]))

    def examine(self, mailbox: str) -> tuple[str, list]:
        self.calls.append(("examine", (mailbox,)))
        self._selected = True
        return self.responses.get("examine", ("OK", [b"10"]))

    def list(self) -> tuple[str, list]:
        self.calls.append(("list", ()))
        return self.responses.get("list", ("OK", []))

    def search(self, charset: str | None, *criteria: str) -> tuple[str, list]:
        self.calls.append(("search", (charset,) + criteria))
        key = " ".join(criteria)
        return self.responses.get(key, ("OK", [b""]))

    def fetch(self, msg_set: str, msg_parts: str) -> tuple[str, list]:
        self.calls.append(("fetch", (msg_set, msg_parts)))
        key = f"fetch {msg_set} {msg_parts}"
        return self.responses.get(key, ("OK", []))

    def uid(self, command: str, *args: Any) -> tuple[str, list]:
        self.calls.append(("uid", (command,) + args))
        key = f"uid {command} {' '.join(str(a) for a in args)}"
        return self.responses.get(key, ("OK", []))

    def append(self, mailbox: str, flags: str, date_time: Any, message: bytes) -> tuple[str, list]:
        self.calls.append(("append", (mailbox, flags, date_time, message)))
        return self.responses.get("append", ("OK", [b"APPEND completed"]))

    def close(self) -> None:
        self.calls.append(("close", ()))

    def logout(self) -> None:
        self.calls.append(("logout", ()))


def _build_raw_message(
    subject: str = "Test subject",
    from_addr: str = "sender@example.com",
    to_addr: str = "recipient@example.com",
    body: str = "Hello world",
    content_type: str = "text/plain",
    message_id: str = "<test-msg-123@example.com>",
    in_reply_to: str | None = None,
    references: list[str] | None = None,
) -> bytes:
    msg = email.message.EmailMessage(policy=email.policy.default)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
    msg["Message-ID"] = message_id
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = " ".join(references)
    msg.set_content(body, subtype=content_type.split("/")[1])
    return msg.as_bytes()


class TestIMAPClientConnect:
    def test_connect_and_login_succeed(self):
        fake = FakeIMAP()
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "app-password", imap_factory=lambda h, p: fake
        )
        client._connect()
        assert fake._logged_in is True
        assert ("login", ("user@example.com", "app-password")) in fake.calls

    def test_auth_failure_raises_clear_error(self):
        fake = FakeIMAP(fail_login=True)
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "app-password", imap_factory=lambda h, p: fake
        )
        with pytest.raises(MailError) as exc_info:
            client._connect()
        assert "mail authentication failed" in str(exc_info.value)
        assert "check app password" in str(exc_info.value)
        # Never leak the password in the error
        assert "app-password" not in str(exc_info.value)


def test_build_mail_message_creates_plain_text_message_with_all_recipient_headers():
    message = build_mail_message(
        sender="sender@example.com",
        to=["one@example.com", "two@example.com"],
        cc=["copy@example.com"],
        bcc=["blind@example.com"],
        subject="A protected test",
        body="Hello from the CLI.\n",
    )

    assert message["From"] == "sender@example.com"
    assert message["To"] == "one@example.com, two@example.com"
    assert message["Cc"] == "copy@example.com"
    assert message["Bcc"] == "blind@example.com"
    assert message["Subject"] == "A protected test"
    assert message.get_content_type() == "text/plain"
    assert message.get_content() == "Hello from the CLI.\n"


@pytest.mark.parametrize("field,value", [
    ("sender", "sender@example.com\r\nBcc: victim@example.com"),
    ("to", "recipient@example.com\nCc: victim@example.com"),
    ("subject", "hello\r\nBcc: victim@example.com"),
])
def test_build_mail_message_rejects_header_injection(field, value):
    kwargs = {
        "sender": "sender@example.com",
        "to": ["recipient@example.com"],
        "subject": "hello",
        "body": "body",
    }
    kwargs[field] = [value] if field == "to" else value

    with pytest.raises(MailError, match="newline"):
        build_mail_message(**kwargs)


def test_imap_append_draft_uses_discovered_drafts_folder_and_draft_flag():
    fake = FakeIMAP({
        "list": ("OK", [b'(\\Drafts) "/" "Drafts.localized"']),
    })
    client = IMAPClient(
        "mail.infomaniak.com", 993, "sender@example.com", "app-password",
        imap_factory=lambda host, port: fake,
    )
    message = build_mail_message(
        sender="sender@example.com", to=["recipient@example.com"], subject="Draft", body="Body",
    )

    result = client.append_draft(message)

    append_call = next(call for call in fake.calls if call[0] == "append")
    assert append_call[1][0] == "Drafts.localized"
    assert append_call[1][1] == r"\Draft"
    assert b"Subject: Draft" in append_call[1][3]
    assert result == {"folder": "Drafts.localized", "status": "saved"}


class FakeSMTP:
    def __init__(self, *, fail_login=False, fail_send=False):
        self.fail_login = fail_login
        self.fail_send = fail_send
        self.calls = []

    def login(self, username, password):
        self.calls.append(("login", username, password))
        if self.fail_login:
            raise RuntimeError(f"bad password {password}")

    def send_message(self, message):
        self.calls.append(("send_message", message))
        if self.fail_send:
            raise RuntimeError("send failed")

    def quit(self):
        self.calls.append(("quit",))


def test_smtp_client_logs_in_and_sends_one_message():
    fake = FakeSMTP()
    client = SMTPClient(
        "mail.infomaniak.com", 465, "sender@example.com", "app-password",
        security="ssl",
        smtp_ssl_factory=lambda host, port, timeout=None: fake,
    )
    message = build_mail_message(
        sender="sender@example.com", to=["recipient@example.com"], subject="Send", body="Body",
    )

    result = client.send_message(message)

    assert fake.calls[0] == ("login", "sender@example.com", "app-password")
    assert len([call for call in fake.calls if call[0] == "send_message"]) == 1
    assert fake.calls[-1] == ("quit",)
    assert result == {"status": "sent"}


def test_smtp_client_redacts_password_from_transport_errors():
    password = "top-secret-mail-password"
    client = SMTPClient(
        "mail.infomaniak.com", 465, "sender@example.com", password,
        security="ssl",
        smtp_ssl_factory=lambda host, port, timeout=None: FakeSMTP(fail_login=True),
    )
    message = build_mail_message(
        sender="sender@example.com", to=["recipient@example.com"], subject="Send", body="Body",
    )

    with pytest.raises(MailError) as excinfo:
        client.send_message(message)

    assert password not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def _header_fetch_key(msg_id: str) -> str:
    return (
        f"fetch {msg_id} "
        f"(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES)])"
    )


class TestIMAPClientListFolders:
    def test_list_folders_parses_flags_and_roles(self):
        lines = [
            b'(\\HasNoChildren \\Inbox) "/" "INBOX"',
            b'(\\HasNoChildren \\Sent) "/" "Sent"',
            b'(\\HasChildren) "/" "Projects/Client A"',
            b'(\\Junk) "/" "Junk Mail"',
        ]
        fake = FakeIMAP(responses={"list": ("OK", lines)})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        folders = client.list_folders()
        assert len(folders) == 4
        assert folders[0] == {
            "name": "INBOX",
            "separator": "/",
            "flags": [r"\HasNoChildren", r"\Inbox"],
            "role": "inbox",
        }
        assert folders[1]["role"] == "sent"
        assert folders[2]["name"] == "Projects/Client A"
        assert folders[3]["role"] == "junk"
        assert ("list", ()) in fake.calls

    def test_list_folders_decodes_modified_utf7(self):
        # Re&-ceipts is the literal ampersand escape
        # &AOk- = é, &APw- = ü in modified UTF-7
        lines = [
            b'(\\HasNoChildren) "/" "Re&-ceipts"',
            b'(\\HasNoChildren) "/" "&AOk-rabische b&APw-cke"',
        ]
        fake = FakeIMAP(responses={"list": ("OK", lines)})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        folders = client.list_folders()
        assert folders[0]["name"] == "Re&ceipts"
        assert folders[1]["name"] == "érabische bücke"

    def test_list_folders_skips_unparseable_lines(self):
        fake = FakeIMAP(responses={"list": ("OK", [b"not-a-list-line"])})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        folders = client.list_folders()
        assert folders == []


class TestIMAPClientListMessages:
    def test_list_messages_returns_headers_with_seen_flag(self):
        raw_msg = _build_raw_message(subject="Invoice #42", body="Please pay")
        fake = FakeIMAP(
            responses={
                "ALL": ("OK", [b"1 2"]),
                _header_fetch_key("1"): (
                    "OK",
                    [(b"1 (UID 101 FLAGS (\\Seen))", raw_msg)],
                ),
                _header_fetch_key("2"): (
                    "OK",
                    [(b"2 (UID 102 FLAGS (\\Recent))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_messages(folder="INBOX")
        assert len(items) == 2
        assert items[0]["uid"] == "102"
        assert items[0]["seen"] is False
        assert items[1]["uid"] == "101"
        assert items[1]["seen"] is True
        assert ("examine", ("INBOX",)) in fake.calls

    def test_list_messages_builds_date_criteria(self):
        fake = FakeIMAP(responses={"SINCE 07-Jun-2026 BEFORE 15-Jun-2026": ("OK", [b""])})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_messages(since="2026-06-07", before="2026-06-15")
        assert items == []
        assert ("search", (None, "SINCE", "07-Jun-2026", "BEFORE", "15-Jun-2026")) in fake.calls

    def test_list_messages_builds_on_criteria(self):
        fake = FakeIMAP(responses={"ON 01-Jan-2024": ("OK", [b""])})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_messages(on="2024-01-01")
        assert items == []
        assert ("search", (None, "ON", "01-Jan-2024")) in fake.calls

    def test_list_messages_invalid_date_raises(self):
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: FakeIMAP()
        )
        with pytest.raises(MailError) as exc_info:
            client.list_messages(since="not-a-date")
        assert "invalid date" in str(exc_info.value)

    def test_list_messages_formats_examine_failure_cleanly(self):
        fake = FakeIMAP(
            responses={
                "examine": ("NO", [b"Mailbox doesn't exist: __codex_no_such_folder__"]),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )

        with pytest.raises(MailError) as exc_info:
            client.list_messages(folder="__codex_no_such_folder__")

        assert str(exc_info.value) == (
            "IMAP examine failed for __codex_no_such_folder__: "
            "Mailbox doesn't exist: __codex_no_such_folder__"
        )

    def test_list_messages_honors_limit(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "ALL": ("OK", [b"1 2 3"]),
                _header_fetch_key("3"): (
                    "OK",
                    [(b"3 (UID 103 FLAGS (\\Seen))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_messages(limit=1)
        assert len(items) == 1
        assert items[0]["uid"] == "103"

    def test_list_messages_oldest_first_preserves_ascending_limit(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "ALL": ("OK", [b"1 2 3"]),
                _header_fetch_key("1"): (
                    "OK",
                    [(b"1 (UID 101 FLAGS (\\Seen))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_messages(limit=1, order="oldest")
        assert len(items) == 1
        assert items[0]["uid"] == "101"

    def test_list_messages_empty_folder(self):
        fake = FakeIMAP(responses={"ALL": ("OK", [b""])})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_messages(folder="Archive")
        assert items == []


class TestIMAPClientListUnread:
    def test_list_unread_returns_slim_headers_with_uids(self):
        raw_msg = _build_raw_message(subject="Invoice #42", body="Please pay")
        fake = FakeIMAP(
            responses={
                "UNSEEN": ("OK", [b"1 2"]),
                _header_fetch_key("1"): (
                    "OK",
                    [(b"1 (UID 101 FLAGS (\\Seen))", raw_msg)],
                ),
                _header_fetch_key("2"): (
                    "OK",
                    [(b"2 (UID 102 FLAGS (\\Recent))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_unread()
        assert len(items) == 2
        assert items[0]["uid"] == "102"
        assert items[0]["seen"] is False
        assert items[0]["subject"] == "Invoice #42"
        assert items[0]["from"] == "sender@example.com"
        assert items[1]["uid"] == "101"
        assert ("search", (None, "UNSEEN")) in fake.calls

    def test_list_unread_honors_limit(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "UNSEEN": ("OK", [b"1 2 3"]),
                _header_fetch_key("3"): (
                    "OK",
                    [(b"3 (UID 103 FLAGS (\\Recent))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_unread(limit=1)
        assert len(items) == 1
        assert items[0]["uid"] == "103"

    def test_list_unread_empty_inbox(self):
        fake = FakeIMAP(responses={"UNSEEN": ("OK", [b""])})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_unread()
        assert items == []


class TestIMAPClientSearch:
    def test_search_returns_matching_messages(self):
        raw_msg = _build_raw_message(subject="Invoice due", body="Payment needed")
        fake = FakeIMAP(
            responses={
                "OR SUBJECT invoice FROM invoice": ("OK", [b"5"]),
                _header_fetch_key("5"): (
                    "OK",
                    [(b"5 (UID 2001 FLAGS (\\Seen))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.search("invoice")
        assert len(items) == 1
        assert items[0]["uid"] == "2001"
        assert items[0]["subject"] == "Invoice due"
        assert items[0]["seen"] is True

    def test_search_honors_limit(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "OR SUBJECT query FROM query": ("OK", [b"1 2 3"]),
                _header_fetch_key("3"): (
                    "OK",
                    [(b"3 (UID 303 FLAGS (\\Recent))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.search("query", limit=1)
        assert len(items) == 1
        assert items[0]["uid"] == "303"

    def test_search_oldest_first_preserves_ascending_limit(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "OR SUBJECT query FROM query": ("OK", [b"1 2 3"]),
                _header_fetch_key("1"): (
                    "OK",
                    [(b"1 (UID 301 FLAGS (\\Recent))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.search("query", limit=1, order="oldest")
        assert len(items) == 1
        assert items[0]["uid"] == "301"

    def test_search_with_date_and_unread_filters(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "OR SUBJECT invoice FROM invoice UNSEEN SINCE 01-Jun-2026 BEFORE 15-Jun-2026": (
                    "OK",
                    [b"7"],
                ),
                _header_fetch_key("7"): (
                    "OK",
                    [(b"7 (UID 4001 FLAGS (\\Recent))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.search(
            "invoice", folder="INBOX", unread_only=True, since="2026-06-01", before="2026-06-15"
        )
        assert len(items) == 1
        assert items[0]["uid"] == "4001"
        assert items[0]["seen"] is False
        assert ("examine", ("INBOX",)) in fake.calls

    def test_search_structured_flags_build_from_to_subject_criteria(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "FROM boss@example.com TO me@example.com SUBJECT Invoice": ("OK", [b"9"]),
                _header_fetch_key("9"): (
                    "OK",
                    [(b"9 (UID 5001 FLAGS (\\Recent))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.search(from_addr="boss@example.com", to_addr="me@example.com", subject="Invoice")
        assert len(items) == 1
        assert items[0]["uid"] == "5001"

    def test_search_query_and_from_are_anded(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "OR SUBJECT report FROM report FROM boss@example.com": ("OK", [b"3"]),
                _header_fetch_key("3"): ("OK", [(b"3 (UID 6001 FLAGS (\\Recent))", raw_msg)]),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.search("report", from_addr="boss@example.com")
        assert items[0]["uid"] == "6001"

    def test_search_requires_query_or_flag(self):
        fake = FakeIMAP(responses={})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        with pytest.raises(ValueError, match="--from/--to/--subject"):
            client.search()


class TestIMAPClientFetchMessage:
    def test_fetch_message_returns_headers_full_body_and_preview(self):
        raw_msg = _build_raw_message(subject="Full message", body="This is the full body text.")
        fake = FakeIMAP(
            responses={
                "uid FETCH 555 (BODY.PEEK[])": (
                    "OK",
                    [(b"555 (BODY[] {180}", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        msg = client.fetch_message("555")
        assert msg["uid"] == "555"
        assert msg["subject"] == "Full message"
        assert msg["body_text"] == "This is the full body text."
        assert msg["body_preview"] == "This is the full body text."
        assert ("uid", ("FETCH", "555", "(BODY.PEEK[])")) in fake.calls

    def test_fetch_message_body_text_is_not_truncated(self):
        full_body = "x" * 700
        raw_msg = _build_raw_message(subject="Long message", body=full_body)
        fake = FakeIMAP(
            responses={
                "uid FETCH 555 (BODY.PEEK[])": (
                    "OK",
                    [(b"555 (BODY[] {900}", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        msg = client.fetch_message("555")
        assert msg["body_text"] == full_body
        assert len(msg["body_preview"]) <= 501
        assert msg["body_preview"] != msg["body_text"]

    def test_fetch_message_exposes_raw_html_body(self):
        raw_msg = _build_raw_message(
            subject="HTML message",
            body="<p>Hello <b>world</b></p>",
            content_type="text/html",
        )
        fake = FakeIMAP(
            responses={
                "uid FETCH 555 (BODY.PEEK[])": ("OK", [(b"555 (BODY[] {200}", raw_msg)]),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        msg = client.fetch_message("555")
        assert "<b>world</b>" in msg["body_html"]
        # text body is the tag-stripped readable form
        assert "world" in msg["body_text"]
        assert "<b>" not in msg["body_text"]
        # slim view surfaces body_html when present
        assert "<b>world</b>" in slim_message(msg)["body_html"]

    def test_fetch_message_html_only_body_text_is_readable(self):
        raw_msg = _build_raw_message(
            subject="HTML message",
            body="<html><body><h1>Hello</h1><p>World</p></body></html>",
            content_type="text/html",
        )
        fake = FakeIMAP(
            responses={
                "uid FETCH 555 (BODY.PEEK[])": (
                    "OK",
                    [(b"555 (BODY[] {220}", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        msg = client.fetch_message("555")
        assert "Hello" in msg["body_text"]
        assert "World" in msg["body_text"]
        assert "<html>" not in msg["body_text"]

    def test_fetch_message_not_found_raises(self):
        fake = FakeIMAP(responses={"uid FETCH 999 (BODY.PEEK[])": ("OK", [])})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        with pytest.raises(MailError) as exc_info:
            client.fetch_message("999")
        assert "not found" in str(exc_info.value)


class TestIMAPClientContextManager:
    def test_context_manager_closes_connection(self):
        fake = FakeIMAP()
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        with client as c:
            c._connect()
        assert ("close", ()) in fake.calls
        assert ("logout", ()) in fake.calls


class TestHeaderDecoding:
    def test_decode_plain_header(self):
        assert _decode_header_value("Hello") == "Hello"

    def test_decode_mime_encoded_header(self):
        encoded = "=?utf-8?Q?=C3=A9mulsion?="
        assert _decode_header_value(encoded) == "émulsion"

    def test_decode_none_returns_none(self):
        assert _decode_header_value(None) is None


class TestBodyPreview:
    def test_body_text_returns_full_plain_text(self):
        msg = email.message.EmailMessage(policy=email.policy.default)
        msg.set_content("x" * 700)
        assert _body_text(msg) == "x" * 700

    def test_preview_from_plain_text(self):
        msg = email.message.EmailMessage(policy=email.policy.default)
        msg.set_content("Short message body")
        assert _body_preview(msg) == "Short message body"

    def test_preview_truncates_long_body(self):
        msg = email.message.EmailMessage(policy=email.policy.default)
        msg.set_content("x" * 600)
        preview = _body_preview(msg)
        assert preview.endswith("…")
        assert len(preview) <= 501

    def test_preview_from_multipart_prefers_plain(self):
        msg = email.message.EmailMessage(policy=email.policy.default)
        msg.make_mixed()
        plain = email.message.EmailMessage(policy=email.policy.default)
        plain.set_content("Plain text part")
        html = email.message.EmailMessage(policy=email.policy.default)
        html.set_content("<html><body>HTML part</body></html>", subtype="html")
        msg.attach(plain)
        msg.attach(html)
        assert _body_preview(msg) == "Plain text part"

    def test_preview_from_html_only_strips_tags(self):
        msg = email.message.EmailMessage(policy=email.policy.default)
        msg.set_content("<html><body><p>Hello</p><br><p>World</p></body></html>", subtype="html")
        preview = _body_preview(msg)
        assert "<html>" not in preview
        assert "Hello" in preview
        assert "World" in preview

    def test_preview_from_multipart_html_fallback(self):
        msg = email.message.EmailMessage(policy=email.policy.default)
        msg.make_mixed()
        html = email.message.EmailMessage(policy=email.policy.default)
        html.set_content("<p>Only HTML</p>", subtype="html")
        msg.attach(html)
        preview = _body_preview(msg)
        assert "Only HTML" in preview
        assert "<p>" not in preview


class TestHTMLToText:
    def test_strips_tags_and_preserves_structure(self):
        html = "<html><body><p>Hello</p><br><div>World</div></body></html>"
        text = _html_to_text(html)
        assert "Hello" in text
        assert "World" in text
        assert "<html>" not in text

    def test_removes_scripts_and_styles(self):
        html = "<html><script>alert('x')</script><style>.x{}</style><body>Content</body></html>"
        text = _html_to_text(html)
        assert "alert" not in text
        assert "Content" in text


class TestSlimMessage:
    def test_slim_message_keeps_only_useful_fields(self):
        raw = {
            "uid": "42",
            "from": "a@example.com",
            "to": "b@example.com",
            "subject": "Hello",
            "date": "Mon, 01 Jan 2024 12:00:00 +0000",
            "message_id": "<msg-42@example.com>",
            "body_preview": "Body text here",
        }
        slim = slim_message(raw)
        assert slim == {
            "uid": "42",
            "from": "a@example.com",
            "subject": "Hello",
            "date": "Mon, 01 Jan 2024 12:00:00 +0000",
            "seen": False,
        }


class TestIMAPClientListThreads:
    def test_list_threads_groups_by_in_reply_to(self):
        root = _build_raw_message(
            subject="Project kickoff",
            message_id="<root-1@example.com>",
            body="First message",
        )
        reply1 = _build_raw_message(
            subject="Re: Project kickoff",
            message_id="<reply-1@example.com>",
            in_reply_to="<root-1@example.com>",
            body="Reply one",
        )
        reply2 = _build_raw_message(
            subject="Re: Project kickoff",
            message_id="<reply-2@example.com>",
            in_reply_to="<reply-1@example.com>",
            body="Reply two",
        )
        other = _build_raw_message(
            subject="Invoice",
            message_id="<other-1@example.com>",
            body="Other thread",
        )
        fake = FakeIMAP(
            responses={
                "ALL": ("OK", [b"1 2 3 4"]),
                _header_fetch_key("1"): (
                    "OK",
                    [(b"1 (UID 101 FLAGS (\\Seen))", root)],
                ),
                _header_fetch_key("2"): (
                    "OK",
                    [(b"2 (UID 102 FLAGS (\\Seen))", reply1)],
                ),
                _header_fetch_key("3"): (
                    "OK",
                    [(b"3 (UID 103 FLAGS (\\Seen))", reply2)],
                ),
                _header_fetch_key("4"): (
                    "OK",
                    [(b"4 (UID 104 FLAGS (\\Seen))", other)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        threads = client.list_threads(folder="INBOX")
        assert len(threads) == 2
        by_subject = {t["subject"]: t for t in threads}
        # Project thread
        project = by_subject["Project kickoff"]
        assert project["message_count"] == 3
        assert project["newest_uid"] == "103"
        assert [m["uid"] for m in project["messages"]] == ["101", "102", "103"]
        # Invoice thread
        invoice = by_subject["Invoice"]
        assert invoice["message_count"] == 1
        assert invoice["messages"][0]["uid"] == "104"
        # Newest thread first
        assert threads[0]["newest_uid"] == "104"

    def test_list_threads_groups_by_references(self):
        root = _build_raw_message(
            subject="Meeting",
            message_id="<meet-root@example.com>",
            body="Meeting invite",
        )
        reply = _build_raw_message(
            subject="Re: Meeting",
            message_id="<meet-reply@example.com>",
            references=["<meet-root@example.com>"],
            body="I'll join",
        )
        fake = FakeIMAP(
            responses={
                "ALL": ("OK", [b"1 2"]),
                _header_fetch_key("1"): ("OK", [(b"1 (UID 201 FLAGS (\\Seen))", root)]),
                _header_fetch_key("2"): ("OK", [(b"2 (UID 202 FLAGS (\\Seen))", reply)]),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        threads = client.list_threads(folder="INBOX")
        assert len(threads) == 1
        assert threads[0]["message_count"] == 2
        assert [m["uid"] for m in threads[0]["messages"]] == ["201", "202"]

    def test_list_threads_honors_limit(self):
        msg1 = _build_raw_message(subject="A", message_id="<a@example.com>")
        msg2 = _build_raw_message(subject="B", message_id="<b@example.com>")
        fake = FakeIMAP(
            responses={
                "ALL": ("OK", [b"1 2"]),
                _header_fetch_key("1"): ("OK", [(b"1 (UID 301 FLAGS (\\Seen))", msg1)]),
                _header_fetch_key("2"): ("OK", [(b"2 (UID 302 FLAGS (\\Seen))", msg2)]),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        threads = client.list_threads(folder="INBOX", limit=1)
        assert len(threads) == 1
        assert threads[0]["newest_uid"] == "302"

    def test_list_threads_empty_folder(self):
        fake = FakeIMAP(responses={"ALL": ("OK", [b""])})
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        threads = client.list_threads(folder="Archive")
        assert threads == []



# --- v0.2.15 attachments ---------------------------------------------------


def _message_with_attachments() -> email.message.EmailMessage:
    msg = email.message.EmailMessage(policy=email.policy.SMTP)
    msg["From"] = "sender@example.com"
    msg["To"] = "user@example.com"
    msg["Subject"] = "Report"
    msg["Message-ID"] = "<orig-1@example.com>"
    msg.set_content("Body text")
    msg.add_attachment(b"PDFDATA", maintype="application", subtype="pdf", filename="report.pdf")
    msg.add_attachment(b"a,b\n1,2", maintype="text", subtype="csv", filename="data.csv")
    return msg


def test_list_attachments_returns_named_parts_only():
    parts = list_attachments(_message_with_attachments())

    assert [p["filename"] for p in parts] == ["report.pdf", "data.csv"]
    assert [p["index"] for p in parts] == [0, 1]
    assert parts[0]["content_type"] == "application/pdf"
    assert parts[0]["size"] == len(b"PDFDATA")


def test_list_attachments_is_empty_for_a_plain_message():
    msg = email.message.EmailMessage(policy=email.policy.SMTP)
    msg.set_content("just text")

    assert list_attachments(msg) == []


def test_extract_attachment_by_index_returns_bytes_verbatim():
    name, payload = extract_attachment(_message_with_attachments(), 0)

    assert name == "report.pdf"
    assert payload == b"PDFDATA"


def test_extract_attachment_by_unambiguous_filename():
    name, payload = extract_attachment(_message_with_attachments(), "data.csv")

    assert name == "data.csv"
    assert payload == b"a,b\n1,2"


def test_extract_attachment_refuses_an_out_of_range_index():
    with pytest.raises(MailError, match="out of range"):
        extract_attachment(_message_with_attachments(), 5)


def test_extract_attachment_refuses_an_ambiguous_filename():
    msg = email.message.EmailMessage(policy=email.policy.SMTP)
    msg.set_content("body")
    msg.add_attachment(b"one", maintype="application", subtype="pdf", filename="same.pdf")
    msg.add_attachment(b"two", maintype="application", subtype="pdf", filename="same.pdf")

    with pytest.raises(MailError, match="ambiguous"):
        extract_attachment(msg, "same.pdf")


def test_extract_attachment_refuses_an_unknown_filename():
    with pytest.raises(MailError, match="no attachment"):
        extract_attachment(_message_with_attachments(), "missing.txt")


# --- v0.2.15 attachment sending -------------------------------------------


def test_build_mail_message_attaches_files_with_guessed_types(tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"PDFDATA")
    # An extension with no registered type must fall back, not raise. Avoid
    # asserting types that vary by platform registry (e.g. .csv on Windows).
    blob = tmp_path / "data.unknownext"
    blob.write_bytes(b"RAWBYTES")

    msg = build_mail_message(
        sender="user@example.com", to=["recipient@example.com"],
        subject="Report", body="See attached.", attachments=[pdf, blob],
    )

    parts = list_attachments(msg)
    assert [p["filename"] for p in parts] == ["report.pdf", "data.unknownext"]
    assert parts[0]["content_type"] == "application/pdf"
    assert parts[1]["content_type"] == "application/octet-stream"
    assert extract_attachment(msg, 0)[1] == b"PDFDATA"
    assert extract_attachment(msg, 1)[1] == b"RAWBYTES"


def test_build_mail_message_without_attachments_stays_plain_text():
    msg = build_mail_message(
        sender="user@example.com", to=["recipient@example.com"],
        subject="Hello", body="Body",
    )

    assert list_attachments(msg) == []
    assert msg.get_content_type() == "text/plain"


def test_build_mail_message_refuses_a_missing_or_directory_attachment(tmp_path):
    with pytest.raises(MailError, match="does not exist"):
        build_mail_message(
            sender="user@example.com", to=["recipient@example.com"],
            subject="s", body="b", attachments=[tmp_path / "absent.pdf"],
        )
    folder = tmp_path / "folder"
    folder.mkdir()
    with pytest.raises(MailError, match="not a single file"):
        build_mail_message(
            sender="user@example.com", to=["recipient@example.com"],
            subject="s", body="b", attachments=[folder],
        )


def test_build_mail_message_enforces_a_total_attachment_size_cap(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 2048)

    with pytest.raises(MailError, match="total attachment size"):
        build_mail_message(
            sender="user@example.com", to=["recipient@example.com"],
            subject="s", body="b", attachments=[big], max_total_bytes=1024,
        )


# --- v0.2.15 reply and forward --------------------------------------------


def _original() -> email.message.EmailMessage:
    msg = email.message.EmailMessage(policy=email.policy.SMTP)
    msg["From"] = "sender@example.com"
    msg["To"] = "user@example.com, other@example.com"
    msg["Cc"] = "cc@example.com"
    msg["Subject"] = "Quarterly report"
    msg["Message-ID"] = "<orig-1@example.com>"
    msg["References"] = "<root-0@example.com>"
    msg.set_content("Original body")
    return msg


def test_build_reply_preserves_threading_headers():
    reply = build_reply(_original(), sender="user@example.com", body="Thanks.")

    assert reply["In-Reply-To"] == "<orig-1@example.com>"
    # References must append, never replace
    assert "<root-0@example.com>" in reply["References"]
    assert "<orig-1@example.com>" in reply["References"]
    assert reply["To"] == "sender@example.com"
    assert reply["Subject"] == "Re: Quarterly report"


def test_build_reply_does_not_stack_the_re_prefix():
    original = _original()
    del original["Subject"]
    original["Subject"] = "Re: Quarterly report"

    reply = build_reply(original, sender="user@example.com", body="Thanks.")

    assert reply["Subject"] == "Re: Quarterly report"


def test_build_reply_all_includes_others_but_never_our_own_address():
    reply = build_reply(_original(), sender="user@example.com", body="Thanks.", reply_all=True)

    recipients = f"{reply['To']} {reply.get('Cc') or ''}"
    assert "sender@example.com" in recipients
    assert "other@example.com" in recipients
    assert "cc@example.com" in recipients
    assert "user@example.com" not in recipients


def test_build_forward_preserves_references_and_requires_recipients():
    fwd = build_forward(_original(), sender="user@example.com", to=["third@example.com"], body="FYI")

    assert fwd["To"] == "third@example.com"
    assert fwd["Subject"] == "Fwd: Quarterly report"
    assert "<orig-1@example.com>" in fwd["References"]

    with pytest.raises(MailError, match="at least one"):
        build_forward(_original(), sender="user@example.com", to=[], body="FYI")


def test_build_forward_does_not_stack_the_fwd_prefix():
    original = _original()
    del original["Subject"]
    original["Subject"] = "Fwd: Quarterly report"

    fwd = build_forward(original, sender="user@example.com", to=["third@example.com"], body="FYI")

    assert fwd["Subject"] == "Fwd: Quarterly report"


# --- v0.2.15 message lifecycle (flags, move, draft delete) -----------------


def _lifecycle_client(responses=None):
    fake = FakeIMAP(responses or {})
    client = IMAPClient(
        "mail.example.test", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
    )
    return fake, client


def test_mark_read_uses_a_read_write_select_and_adds_the_seen_flag():
    fake, client = _lifecycle_client()

    result = client.mark_read("42", folder="INBOX")

    assert result == {"uid": "42", "folder": "INBOX", "flag": r"\Seen", "added": True}
    selects = [c for c in fake.calls if c[0] == "select"]
    assert selects and selects[-1][1] == ("INBOX", False)  # readonly=False
    stores = [c for c in fake.calls if c[0] == "uid" and c[1][0] == "STORE"]
    assert stores[-1][1] == ("STORE", "42", "+FLAGS", r"(\Seen)")


def test_mark_unread_removes_the_seen_flag():
    fake, client = _lifecycle_client()

    client.mark_unread("42")

    stores = [c for c in fake.calls if c[0] == "uid" and c[1][0] == "STORE"]
    assert stores[-1][1] == ("STORE", "42", "-FLAGS", r"(\Seen)")


def test_flag_and_unflag_toggle_the_flagged_flag():
    fake, client = _lifecycle_client()

    client.flag_message("7")
    client.unflag_message("7")

    stores = [c[1] for c in fake.calls if c[0] == "uid" and c[1][0] == "STORE"]
    assert stores[0] == ("STORE", "7", "+FLAGS", r"(\Flagged)")
    assert stores[1] == ("STORE", "7", "-FLAGS", r"(\Flagged)")


def test_reading_paths_never_take_the_read_write_select():
    """Regression: introducing mutations must not make reads mutate state."""
    fake, client = _lifecycle_client({"search": ("OK", [b""])})

    client.list_messages(folder="INBOX")

    assert not [c for c in fake.calls if c[0] == "select" and c[1][1] is False]
    assert [c for c in fake.calls if c[0] == "examine"]


def test_move_message_prefers_uid_move():
    fake, client = _lifecycle_client()

    result = client.move_message("42", "Archive", folder="INBOX")

    assert result["method"] == "MOVE"
    assert result["to"] == "Archive"
    moves = [c for c in fake.calls if c[0] == "uid" and c[1][0] == "MOVE"]
    assert moves and moves[-1][1] == ("MOVE", "42", "Archive")


def test_move_message_refuses_a_mailbox_wide_expunge_when_uid_expunge_is_unavailable():
    class NoMoveNoUidExpunge(FakeIMAP):
        def uid(self, command, *args):
            self.calls.append(("uid", (command, *args)))
            if command in {"MOVE", "EXPUNGE"}:
                raise imaplib.IMAP4.error(f"{command} not supported")
            return ("OK", [b""])

    fake = NoMoveNoUidExpunge({})
    client = IMAPClient(
        "mail.example.test", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
    )

    with pytest.raises(MailError, match="Refusing a mailbox-wide EXPUNGE"):
        client.move_message("42", "Archive")


def test_message_flags_reads_without_mutating():
    fake, client = _lifecycle_client(
        {"uid FETCH 42 (FLAGS)": ("OK", [rb"1 (UID 42 FLAGS (\Seen \Flagged))"])}
    )

    flags = client.message_flags("42")

    assert flags == [r"\Seen", r"\Flagged"]
    assert not [c for c in fake.calls if c[0] == "select" and c[1][1] is False]


def _parsed_with_folded_subject() -> email.message.Message:
    """A message as it actually arrives from the wire, with a folded subject.

    Folding is how long subjects are transmitted (RFC 5322 section 2.2.3), so
    the decoded value legitimately contains CR/LF plus continuation whitespace.
    """
    raw = (
        b"From: sender@example.com\r\n"
        b"To: user@example.com\r\n"
        b"Subject: Quarterly report\r\n and supporting figures\r\n"
        b"Message-ID: <orig-1@example.com>\r\n"
        b"References: <root-0@example.com>\r\n"
        b"\r\n"
        b"Original body\r\n"
    )
    return email.message_from_bytes(raw)


def test_build_reply_collapses_a_folded_subject_header():
    """Regression: a folded real-world subject must not produce a newline.

    Leaving the fold in makes the header-injection guard reject the reply, which
    broke replying to any message with a long subject.
    """
    reply = build_reply(
        _parsed_with_folded_subject(), sender="user@example.com", body="Thanks."
    )

    assert "\n" not in reply["Subject"]
    assert "\r" not in reply["Subject"]
    assert reply["Subject"] == "Re: Quarterly report and supporting figures"


def test_build_forward_collapses_a_folded_subject_header():
    fwd = build_forward(
        _parsed_with_folded_subject(),
        sender="user@example.com",
        to=["third@example.com"],
        body="FYI",
    )

    assert "\n" not in fwd["Subject"]
    assert fwd["Subject"] == "Fwd: Quarterly report and supporting figures"
