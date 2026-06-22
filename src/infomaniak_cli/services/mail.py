"""Read-only IMAP mail service for Infomaniak mailboxes.

Uses Python standard library imaplib + email.
No third-party dependencies.
"""

from __future__ import annotations

import email
import email.header
import email.message
import imaplib
import re
from typing import Any


class MailError(ValueError):
    pass


class IMAPClient:
    """Injectable IMAP client for read-only mailbox access.

    Parameters
    ----------
    host: str
        IMAP server hostname (e.g. mail.infomaniak.com).
    port: int
        IMAP server port (usually 993).
    username: str
        Full email address used for IMAP login.
    password: str
        App-specific password (never the login password or REST token).
    imap_factory:
        Callable returning an IMAP connection object. Defaults to
        ``imaplib.IMAP4_SSL`` so tests can inject a fake.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        imap_factory: Any = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._imap_factory = imap_factory or imaplib.IMAP4_SSL
        self._conn = None

    def _connect(self) -> None:
        if self._conn is not None:
            return
        try:
            self._conn = self._imap_factory(self.host, self.port)
            self._conn.login(self.username, self.password)
        except imaplib.IMAP4.error as exc:
            raise MailError("mail authentication failed (check app password)") from exc

    def _select(self, mailbox: str = "INBOX") -> None:
        self._connect()
        typ, data = self._conn.select(mailbox)
        if typ != "OK":
            raise MailError(f"IMAP select failed for {mailbox}: {data}")

    def _search(self, criteria: list[str]) -> list[str]:
        self._select("INBOX")
        typ, data = self._conn.search(None, *criteria)
        if typ != "OK" or data is None or not data[0]:
            return []
        return data[0].decode().split()

    def _fetch_uids(self, msg_ids: list[str]) -> list[str]:
        """Convert message sequence numbers to UIDs."""
        if not msg_ids:
            return []
        uids = []
        for msg_id in msg_ids:
            typ, data = self._conn.fetch(msg_id, "(UID)")
            if typ == "OK" and data and data[0]:
                # Parse response like: b'1 (UID 123)'
                match = re.search(rb"UID\s+(\d+)", data[0])
                if match:
                    uids.append(match.group(1).decode())
        return uids

    def _fetch_headers(self, msg_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch slim headers for a list of message sequence numbers."""
        if not msg_ids:
            return []
        items = []
        for msg_id in msg_ids:
            typ, data = self._conn.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID)])")
            if typ != "OK" or not data or not data[0]:
                continue
            raw_msg = data[0][1] if isinstance(data[0], tuple) else data[0]
            msg = email.message_from_bytes(raw_msg)
            items.append(_slim_headers(msg, uid=None))
        return items

    def list_unread(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return unread message summaries (slim headers)."""
        self._select("INBOX")
        msg_ids = self._search(["UNSEEN"])
        if limit is not None:
            msg_ids = msg_ids[:limit]
        uids = self._fetch_uids(msg_ids)
        items = self._fetch_headers(msg_ids)
        for item, uid in zip(items, uids):
            item["uid"] = uid
        return items

    def search(self, query: str, limit: int | None = None) -> list[dict[str, Any]]:
        """Search messages by a free-text query.

        Uses IMAP OR search on SUBJECT and FROM.
        """
        self._select("INBOX")
        # IMAP search with OR SUBJECT query FROM query
        criteria = ["OR", "SUBJECT", query, "FROM", query]
        msg_ids = self._search(criteria)
        if limit is not None:
            msg_ids = msg_ids[:limit]
        uids = self._fetch_uids(msg_ids)
        items = self._fetch_headers(msg_ids)
        for item, uid in zip(items, uids):
            item["uid"] = uid
        return items

    def fetch_message(self, uid: str) -> dict[str, Any]:
        """Fetch a full message by UID, returning parsed headers + body preview."""
        self._select("INBOX")
        typ, data = self._conn.uid("FETCH", uid, "(RFC822)")
        if typ != "OK" or not data or not data[0]:
            raise MailError(f"Message UID {uid} not found")
        raw_msg = data[0][1] if isinstance(data[0], tuple) else data[0]
        msg = email.message_from_bytes(raw_msg)
        result = _slim_headers(msg, uid=uid)
        result["body_preview"] = _body_preview(msg)
        return result

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    def __enter__(self) -> "IMAPClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


def _decode_header_value(value: str | None) -> str | None:
    if value is None:
        return None
    parts = email.header.decode_header(value)
    decoded_parts = []
    for part, charset in parts:
        if isinstance(part, bytes):
            try:
                decoded_parts.append(part.decode(charset or "utf-8", errors="replace"))
            except LookupError:
                decoded_parts.append(part.decode("utf-8", errors="replace"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts)


def _slim_headers(msg: email.message.Message, uid: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "from": _decode_header_value(msg.get("From")),
        "to": _decode_header_value(msg.get("To")),
        "subject": _decode_header_value(msg.get("Subject")),
        "date": msg.get("Date"),
        "message_id": msg.get("Message-ID"),
    }
    if uid is not None:
        result["uid"] = uid
    return result


def _body_preview(msg: email.message.Message, max_length: int = 500) -> str | None:
    """Extract a plain-text preview from a message, handling multipart."""
    body = _extract_text_body(msg)
    if body is None:
        return None
    body = body.strip()
    if len(body) > max_length:
        body = body[:max_length] + "…"
    return body


def _extract_text_body(msg: email.message.Message) -> str | None:
    """Walk the message parts and return the best plain-text representation."""
    if not msg.is_multipart():
        content_type = msg.get_content_type()
        payload = msg.get_payload(decode=True)
        if payload is None:
            return None
        text = _decode_payload(payload, msg.get_content_charset())
        if content_type == "text/plain":
            return text
        if content_type == "text/html":
            return _html_to_text(text)
        return text

    # Multipart: prefer text/plain, then text/html, then any text/*
    plain_part = None
    html_part = None
    text_part = None

    for part in msg.walk():
        if part.is_multipart():
            continue
        content_type = part.get_content_type()
        if content_type == "text/plain" and plain_part is None:
            plain_part = part
        elif content_type == "text/html" and html_part is None:
            html_part = part
        elif content_type.startswith("text/") and text_part is None:
            text_part = part

    chosen = plain_part or html_part or text_part
    if chosen is None:
        return None

    payload = chosen.get_payload(decode=True)
    if payload is None:
        return None
    text = _decode_payload(payload, chosen.get_content_charset())
    if chosen.get_content_type() == "text/html":
        return _html_to_text(text)
    return text


def _decode_payload(payload: bytes, charset: str | None) -> str:
    try:
        return payload.decode(charset or "utf-8", errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    """Very basic HTML tag stripping for preview purposes."""
    # Remove scripts and styles first
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Replace block tags with newlines
    html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"<p[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</p>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<div[^>]*>", "\n", html, flags=re.IGNORECASE)
    html = re.sub(r"</div>", "", html, flags=re.IGNORECASE)
    # Strip remaining tags
    html = re.sub(r"<[^>]+>", "", html)
    # Collapse whitespace
    html = re.sub(r"\n\s*\n", "\n", html)
    return html.strip()


def slim_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Return a slim view suitable for ``--json`` output."""
    return {
        "uid": msg.get("uid"),
        "from": msg.get("from"),
        "subject": msg.get("subject"),
        "date": msg.get("date"),
    }
