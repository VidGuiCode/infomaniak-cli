"""Read-only IMAP mail service for Infomaniak mailboxes.

Uses Python standard library imaplib + email.
No third-party dependencies.
"""

from __future__ import annotations

import base64
import datetime
import email
import email.header
import email.message
import imaplib
import re
from typing import Any


_SPECIAL_USE_ROLES: dict[str, str] = {
    r"\Inbox": "inbox",
    r"\Sent": "sent",
    r"\Junk": "junk",
    r"\Spam": "spam",
    r"\Trash": "trash",
    r"\Drafts": "drafts",
    r"\Archive": "archive",
    r"\Flagged": "flagged",
}


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

    def _examine(self, mailbox: str = "INBOX") -> None:
        self._connect()
        try:
            typ, data = self._conn.examine(mailbox)
        except Exception:
            # Fall back to read-only select if examine is not supported
            typ, data = self._conn.select(mailbox, readonly=True)
        if typ != "OK":
            raise MailError(f"IMAP examine failed for {mailbox}: {_format_imap_response(data)}")

    def _search(self, criteria: list[str]) -> list[str]:
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

    def _fetch_headers_and_flags(self, msg_ids: list[str]) -> list[dict[str, Any]]:
        """Fetch headers and flags for a list of message sequence numbers."""
        if not msg_ids:
            return []
        items = []
        for msg_id in msg_ids:
            typ, data = self._conn.fetch(
                msg_id,
                "(UID FLAGS BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID IN-REPLY-TO REFERENCES)])",
            )
            if typ != "OK" or not data or not data[0]:
                continue
            if isinstance(data[0], tuple):
                raw_meta, raw_header = data[0]
                meta = _parse_fetch_meta(raw_meta)
                msg = email.message_from_bytes(raw_header)
                item = _slim_headers(msg, uid=meta.get("uid"))
                item["seen"] = r"\Seen" in meta.get("flags", [])
                items.append(item)
        return items

    def list_threads(
        self,
        folder: str = "INBOX",
        limit: int | None = None,
        since: str | None = None,
        before: str | None = None,
        on: str | None = None,
        days: int | None = None,
    ) -> list[dict[str, Any]]:
        """Group messages in a folder into conversation threads.

        Threads are determined by following ``In-Reply-To`` and ``References``
        headers. Results are sorted by newest message first.
        """
        if days is not None and since is not None:
            raise MailError("use either --days or --since, not both")
        if days is not None:
            since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

        self._examine(folder)
        criteria: list[str] = []
        if since:
            criteria.extend(["SINCE", _imap_date(since)])
        if before:
            criteria.extend(["BEFORE", _imap_date(before)])
        if on:
            criteria.extend(["ON", _imap_date(on)])
        if not criteria:
            criteria = ["ALL"]

        msg_ids = self._search(criteria)
        items = self._fetch_headers_and_flags(msg_ids)
        threads = _build_threads(items)
        if limit is not None:
            threads = threads[:limit]
        return threads

    def list_folders(self) -> list[dict[str, Any]]:
        """Return IMAP folders with names, separators, flags, and roles."""
        self._connect()
        typ, data = self._conn.list()
        if typ != "OK" or not data:
            return []
        folders = []
        for line in data:
            if line is None:
                continue
            folder = _parse_folder_list(line)
            if folder:
                folders.append(folder)
        return folders

    def list_messages(
        self,
        folder: str = "INBOX",
        limit: int | None = None,
        unread_only: bool = False,
        since: str | None = None,
        before: str | None = None,
        on: str | None = None,
        order: str = "newest",
    ) -> list[dict[str, Any]]:
        """List messages in a folder, optionally filtered by date and read status.

        Uses EXAMINE for read-only access so messages are never marked as seen.
        Results are sorted by UID descending (newest first).
        """
        if order not in {"newest", "oldest"}:
            raise ValueError("order must be 'newest' or 'oldest'")
        self._examine(folder)
        criteria: list[str] = []
        if unread_only:
            criteria.append("UNSEEN")
        if since:
            criteria.extend(["SINCE", _imap_date(since)])
        if before:
            criteria.extend(["BEFORE", _imap_date(before)])
        if on:
            criteria.extend(["ON", _imap_date(on)])
        if not criteria:
            criteria = ["ALL"]

        msg_ids = self._search(criteria)
        msg_ids = _limit_msg_ids(msg_ids, limit=limit, order=order)

        items = self._fetch_headers_and_flags(msg_ids)
        items.sort(key=lambda x: int(x.get("uid", 0)), reverse=(order == "newest"))
        return items

    def list_unread(self, limit: int | None = None, order: str = "newest") -> list[dict[str, Any]]:
        """Return unread message summaries (slim headers)."""
        return self.list_messages(folder="INBOX", limit=limit, unread_only=True, order=order)

    def search(
        self,
        query: str,
        folder: str = "INBOX",
        limit: int | None = None,
        unread_only: bool = False,
        since: str | None = None,
        before: str | None = None,
        on: str | None = None,
        order: str = "newest",
    ) -> list[dict[str, Any]]:
        """Search messages by a free-text query in a folder.

        Uses IMAP OR search on SUBJECT and FROM, combined with optional filters.
        """
        if order not in {"newest", "oldest"}:
            raise ValueError("order must be 'newest' or 'oldest'")
        self._examine(folder)
        criteria = ["OR", "SUBJECT", query, "FROM", query]
        if unread_only:
            criteria.append("UNSEEN")
        if since:
            criteria.extend(["SINCE", _imap_date(since)])
        if before:
            criteria.extend(["BEFORE", _imap_date(before)])
        if on:
            criteria.extend(["ON", _imap_date(on)])

        msg_ids = self._search(criteria)
        msg_ids = _limit_msg_ids(msg_ids, limit=limit, order=order)

        items = self._fetch_headers_and_flags(msg_ids)
        items.sort(key=lambda x: int(x.get("uid", 0)), reverse=(order == "newest"))
        return items

    def fetch_message(self, uid: str, folder: str = "INBOX") -> dict[str, Any]:
        """Fetch a full message by UID, returning parsed headers + body preview."""
        self._examine(folder)
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
        "in_reply_to": msg.get("In-Reply-To"),
        "references": _parse_message_id_list(msg.get("References")),
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


def _format_imap_response(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, bytes):
        return data.decode(errors="replace")
    if isinstance(data, str):
        return data
    if isinstance(data, (list, tuple)):
        parts = [_format_imap_response(item) for item in data if item is not None]
        return "; ".join(part for part in parts if part)
    return str(data)


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
        "seen": msg.get("seen", False),
    }


def _imap_date(date_str: str) -> str:
    """Convert YYYY-MM-DD to IMAP date format (DD-Mon-YYYY)."""
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise MailError(f"invalid date: {date_str}. Expected YYYY-MM-DD.") from exc
    return dt.strftime("%d-%b-%Y")


def _limit_msg_ids(msg_ids: list[str], *, limit: int | None, order: str) -> list[str]:
    if limit is None:
        return msg_ids
    if limit <= 0:
        return []
    return msg_ids[-limit:] if order == "newest" else msg_ids[:limit]


def _parse_fetch_meta(raw_meta: bytes) -> dict[str, Any]:
    """Parse UID and FLAGS from an IMAP FETCH response envelope."""
    text = raw_meta.decode("ascii", errors="replace")
    meta: dict[str, Any] = {"uid": None, "flags": []}
    uid_match = re.search(r"UID\s+(\d+)", text)
    if uid_match:
        meta["uid"] = uid_match.group(1)
    flags_match = re.search(r"FLAGS\s+\(([^)]*)\)", text)
    if flags_match:
        meta["flags"] = flags_match.group(1).split()
    return meta


def _decode_modified_utf7(data: bytes) -> str:
    """Decode an IMAP modified UTF-7 mailbox name to a Unicode string."""
    result: list[str] = []
    i = 0
    while i < len(data):
        byte = data[i : i + 1]
        if byte == b"&":
            if i + 1 < len(data) and data[i + 1 : i + 2] == b"-":
                result.append("&")
                i += 2
                continue
            end = data.find(b"-", i)
            if end == -1:
                end = len(data)
            encoded = data[i + 1 : end]
            # Modified base64 uses ',' instead of '/'
            encoded = encoded.replace(b",", b"/")
            padding = (4 - len(encoded) % 4) % 4
            encoded += b"=" * padding
            try:
                utf16 = base64.b64decode(encoded)
                result.append(utf16.decode("utf-16be"))
            except Exception:
                # Fall back to preserving raw bytes if decoding fails
                result.append(data[i:end].decode("latin-1"))
            i = end + 1
        else:
            try:
                result.append(byte.decode("ascii"))
            except UnicodeDecodeError:
                result.append(byte.decode("latin-1"))
            i += 1
    return "".join(result)


def _parse_folder_list(line: bytes) -> dict[str, Any] | None:
    """Parse one IMAP LIST response line into folder metadata.

    Expected format::

        (\\Flag1 \\Flag2) "/" "Folder Name"
        (\\HasNoChildren \\Inbox) "." INBOX

    Returns None when the line cannot be parsed.
    """
    match = re.match(
        rb"^\s*\((?P<flags>.*?)\)\s+(?P<sep>\"[^\"]*\"|[^\s]+)\s+(?P<name>.*)$",
        line,
    )
    if not match:
        return None
    flags_text = match.group("flags").decode("ascii", errors="replace")
    flags = flags_text.split()
    separator = match.group("sep").decode("ascii", errors="replace").strip('"')
    name_raw = match.group("name").strip()
    if name_raw.startswith(b'"') and name_raw.endswith(b'"'):
        name_raw = name_raw[1:-1]
    name = _decode_modified_utf7(name_raw)
    role: str | None = None
    for flag in flags:
        role = _SPECIAL_USE_ROLES.get(flag)
        if role:
            break
    return {
        "name": name,
        "separator": separator or None,
        "flags": flags,
        "role": role,
    }


def _parse_message_id_list(value: str | None) -> list[str]:
    """Split a space-separated Message-ID list header into individual IDs."""
    if not value:
        return []
    return [part.strip() for part in value.split() if part.strip()]


class _UnionFind:
    """Simple union-find for grouping message IDs into threads."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def _ensure(self, x: str) -> None:
        if x not in self.parent:
            self.parent[x] = x

    def find(self, x: str) -> str:
        self._ensure(x)
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: str, y: str) -> None:
        self._ensure(x)
        self._ensure(y)
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[ry] = rx


def _build_threads(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group messages into conversation threads by In-Reply-To/References."""
    uf = _UnionFind()
    for item in items:
        mid = item.get("message_id") or f"uid-{item.get('uid')}"
        uf.find(mid)
        in_reply_to = item.get("in_reply_to")
        if in_reply_to:
            uf.union(mid, in_reply_to)
        for ref in item.get("references", []):
            if ref:
                uf.union(mid, ref)

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        mid = item.get("message_id") or f"uid-{item.get('uid')}"
        root = uf.find(mid)
        groups.setdefault(root, []).append(item)

    threads: list[dict[str, Any]] = []
    for root, messages in groups.items():
        messages.sort(key=lambda x: int(x.get("uid", 0)))
        newest = messages[-1]
        threads.append(
            {
                "thread_id": root,
                "subject": messages[0].get("subject") or "(no subject)",
                "message_count": len(messages),
                "newest_date": newest.get("date"),
                "newest_uid": newest.get("uid"),
                "messages": messages,
            }
        )

    threads.sort(key=lambda t: int(t.get("newest_uid", 0)), reverse=True)
    return threads
