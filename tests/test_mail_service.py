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

    def select(self, mailbox: str) -> tuple[str, list]:
        self.calls.append(("select", (mailbox,)))
        self._selected = True
        return ("OK", [b"10"])

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


class TestIMAPClientListUnread:
    def test_list_unread_returns_slim_headers_with_uids(self):
        raw_msg = _build_raw_message(subject="Invoice #42", body="Please pay")
        fake = FakeIMAP(
            responses={
                "UNSEEN": ("OK", [b"1 2"]),
                "fetch 1 (UID)": ("OK", [b"1 (UID 101)"]),
                "fetch 2 (UID)": ("OK", [b"2 (UID 102)"]),
                "fetch 1 (BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])": (
                    "OK",
                    [(b"1", raw_msg)],
                ),
                "fetch 2 (BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])": (
                    "OK",
                    [(b"2", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.list_unread()
        assert len(items) == 2
        assert items[0]["uid"] == "101"
        assert items[0]["subject"] == "Invoice #42"
        assert items[0]["from"] == "sender@example.com"
        assert items[1]["uid"] == "102"
        assert ("search", (None, "UNSEEN")) in fake.calls

    def test_list_unread_honors_limit(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "UNSEEN": ("OK", [b"1 2 3"]),
                "fetch 1 (UID)": ("OK", [b"1 (UID 101)"]),
                "fetch 1 (BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])": (
                    "OK",
                    [(b"1", raw_msg)],
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
                "fetch 5 (UID)": ("OK", [b"5 (UID 2001)"]),
                "fetch 5 (BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])": (
                    "OK",
                    [(b"5", raw_msg)],
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

    def test_search_honors_limit(self):
        raw_msg = _build_raw_message()
        fake = FakeIMAP(
            responses={
                "OR SUBJECT query FROM query": ("OK", [b"1 2 3"]),
                "fetch 1 (UID)": ("OK", [b"1 (UID 301)"]),
                "fetch 1 (BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])": (
                    "OK",
                    [(b"1", raw_msg)],
                ),
            }
        )
        client = IMAPClient(
            "mail.infomaniak.com", 993, "user@example.com", "pw", imap_factory=lambda h, p: fake
        )
        items = client.search("query", limit=1)
        assert len(items) == 1
        assert items[0]["uid"] == "301"


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
        }
