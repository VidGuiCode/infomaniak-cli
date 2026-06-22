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
    _body_preview,
    _decode_header_value,
    _extract_text_body,
    _html_to_text,
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
        return ("OK", [b"10"])

    def examine(self, mailbox: str) -> tuple[str, list]:
        self.calls.append(("examine", (mailbox,)))
        self._selected = True
        return ("OK", [b"10"])

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
) -> bytes:
    msg = email.message.EmailMessage(policy=email.policy.default)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Date"] = "Mon, 01 Jan 2024 12:00:00 +0000"
    msg["Message-ID"] = "<test-msg-123@example.com>"
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


def _header_fetch_key(msg_id: str) -> str:
    return (
        f"fetch {msg_id} "
        f"(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])"
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

    def test_list_messages_honors_limit(self):
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
        items = client.list_messages(limit=1)
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
                _header_fetch_key("1"): (
                    "OK",
                    [(b"1 (UID 101 FLAGS (\\Recent))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_unread(limit=1)
        assert len(items) == 1
        assert items[0]["uid"] == "101"

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
                _header_fetch_key("1"): (
                    "OK",
                    [(b"1 (UID 301 FLAGS (\\Recent))", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.search("query", limit=1)
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


class TestIMAPClientFetchMessage:
    def test_fetch_message_returns_headers_and_body_preview(self):
        raw_msg = _build_raw_message(subject="Full message", body="This is the full body text.")
        fake = FakeIMAP(
            responses={
                "uid FETCH 555 (RFC822)": (
                    "OK",
                    [(b"555 (RFC822 {180}", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        msg = client.fetch_message("555")
        assert msg["uid"] == "555"
        assert msg["subject"] == "Full message"
        assert msg["body_preview"] == "This is the full body text."

    def test_fetch_message_not_found_raises(self):
        fake = FakeIMAP(responses={"uid FETCH 999 (RFC822)": ("OK", [])})
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
