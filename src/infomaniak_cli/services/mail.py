"""IMAP and protected SMTP mail helpers for Infomaniak mailboxes.

Uses Python standard library imaplib + smtplib + email.
No third-party dependencies.
"""

from __future__ import annotations

import base64
import datetime
import email
import email.header
import email.message
import email.policy
import email.utils
import imaplib
import mimetypes
import re
import smtplib
from pathlib import Path
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


def _reject_header_newlines(value: str, field: str) -> str:
    text = str(value).strip()
    if "\r" in text or "\n" in text:
        raise MailError(f"{field} must not contain a newline")
    return text


def _mail_address(value: str, field: str) -> str:
    text = _reject_header_newlines(value, field)
    _, address = email.utils.parseaddr(text)
    if not address or "@" not in address:
        raise MailError(f"invalid {field} email address: {text!r}")
    return text


def build_mail_message(
    *,
    sender: str,
    to: list[str],
    subject: str,
    body: str,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments: list[Any] | None = None,
    max_total_bytes: int = 25 * 1024 * 1024,
) -> email.message.EmailMessage:
    """Build one plain-text RFC message after rejecting header injection.

    ``attachments`` are local file paths. Each is read, typed with
    ``mimetypes.guess_type`` and added as a real attachment part; the combined
    size is capped locally so an oversized message fails here with a clear error
    instead of being rejected mid-SMTP.
    """
    recipients = list(to or [])
    copies = list(cc or [])
    blind_copies = list(bcc or [])
    if not recipients:
        raise MailError("at least one --to recipient is required")

    message = email.message.EmailMessage(policy=email.policy.SMTP)
    message["From"] = _mail_address(sender, "sender")
    message["To"] = ", ".join(_mail_address(value, "recipient") for value in recipients)
    if copies:
        message["Cc"] = ", ".join(_mail_address(value, "cc") for value in copies)
    if blind_copies:
        message["Bcc"] = ", ".join(_mail_address(value, "bcc") for value in blind_copies)
    message["Subject"] = _reject_header_newlines(subject, "subject")
    message["Date"] = email.utils.formatdate(localtime=True)
    message["Message-ID"] = email.utils.make_msgid()
    message.set_content(str(body))
    _attach_files(message, attachments, max_total_bytes=max_total_bytes)
    return message


def _attach_files(
    message: email.message.EmailMessage,
    attachments: list[Any] | None,
    *,
    max_total_bytes: int,
) -> None:
    """Attach local files to a message, refusing bad paths and oversized totals."""
    if not attachments:
        return
    total = 0
    for raw in attachments:
        path = Path(raw)
        if not path.exists():
            raise MailError(f"Attachment does not exist: {path}")
        if not path.is_file():
            raise MailError(f"Attachment is not a single file: {path}")
        payload = path.read_bytes()
        total += len(payload)
        if total > max_total_bytes:
            raise MailError(
                f"Refusing to send: total attachment size {total} bytes exceeds the "
                f"{max_total_bytes} byte limit."
            )
        guessed, _ = mimetypes.guess_type(path.name)
        maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
        message.add_attachment(
            payload, maintype=maintype, subtype=subtype or "octet-stream", filename=path.name
        )


def _prefixed_subject(original: str | None, prefix: str) -> str:
    """Add a Re:/Fwd: prefix without stacking one that is already present.

    Real subjects arrive folded across lines (RFC 5322 header folding), so the
    decoded value can contain CR/LF and continuation whitespace. Those are
    collapsed to single spaces here: leaving them in produces a subject that the
    header-injection guard rightly rejects, which would make replying to any
    long-subject message fail.
    """
    decoded = _decode_header_value(original) or ""
    subject = " ".join(decoded.split())
    if subject.casefold().startswith(f"{prefix.casefold()}:"):
        return subject
    return f"{prefix}: {subject}".strip()


def _address_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [addr for _, addr in email.utils.getaddresses([value]) if addr]


def build_reply(
    original: email.message.Message,
    *,
    sender: str,
    body: str,
    reply_all: bool = False,
    attachments: list[Any] | None = None,
) -> email.message.EmailMessage:
    """Build a reply to one resolved message, preserving threading headers.

    ``In-Reply-To`` is the original ``Message-ID`` and ``References`` appends to
    the original chain rather than replacing it, so clients keep the thread.
    """
    original_id = (original.get("Message-ID") or "").strip()
    to = _address_list(original.get("Reply-To")) or _address_list(original.get("From"))
    cc: list[str] = []
    if reply_all:
        own = sender.casefold()
        extra = _address_list(original.get("To")) + _address_list(original.get("Cc"))
        seen = {addr.casefold() for addr in to}
        for addr in extra:
            key = addr.casefold()
            if key == own or key in seen:
                continue
            seen.add(key)
            cc.append(addr)

    quoted = "\n".join(f"> {line}" for line in (_body_text(original) or "").splitlines())
    message = build_mail_message(
        sender=sender,
        to=to,
        subject=_prefixed_subject(original.get("Subject"), "Re"),
        body=f"{body}\n\n{quoted}".rstrip() + "\n",
        cc=cc or None,
        attachments=attachments,
    )
    _apply_threading(message, original, original_id)
    return message


def build_forward(
    original: email.message.Message,
    *,
    sender: str,
    to: list[str],
    body: str,
    with_attachments: bool = False,
) -> email.message.EmailMessage:
    """Build a forward of one resolved message to explicit recipients."""
    if not to:
        raise MailError("forward requires at least one --to recipient")
    original_id = (original.get("Message-ID") or "").strip()
    quoted = "\n".join(f"> {line}" for line in (_body_text(original) or "").splitlines())
    header = (
        f"---------- Forwarded message ----------\n"
        f"From: {_decode_header_value(original.get('From')) or ''}\n"
        f"Subject: {_decode_header_value(original.get('Subject')) or ''}\n"
    )
    message = build_mail_message(
        sender=sender,
        to=to,
        subject=_prefixed_subject(original.get("Subject"), "Fwd"),
        body=f"{body}\n\n{header}\n{quoted}".rstrip() + "\n",
    )
    if with_attachments:
        for name, payload in (
            (item["filename"], extract_attachment(original, item["index"])[1])
            for item in list_attachments(original)
        ):
            guessed, _ = mimetypes.guess_type(name)
            maintype, _, subtype = (guessed or "application/octet-stream").partition("/")
            message.add_attachment(
                payload, maintype=maintype, subtype=subtype or "octet-stream", filename=name
            )
    _apply_threading(message, original, original_id)
    return message


def _apply_threading(
    message: email.message.EmailMessage,
    original: email.message.Message,
    original_id: str,
) -> None:
    """Set In-Reply-To and append to References so threading survives."""
    if not original_id:
        return
    message["In-Reply-To"] = original_id
    prior = (original.get("References") or "").split()
    chain = [ref for ref in prior if ref] + [original_id]
    message["References"] = " ".join(dict.fromkeys(chain))


def list_attachments(msg: email.message.Message) -> list[dict[str, Any]]:
    """List the named attachment parts of a message, in document order.

    Only parts that are real attachments are returned: a part is included when it
    carries a filename, or when its Content-Disposition is ``attachment``. Inline
    body parts and multipart containers are skipped, so the returned index is a
    stable handle for :func:`extract_attachment`.
    """
    parts: list[dict[str, Any]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        disposition = (part.get_content_disposition() or "").casefold()
        if not filename and disposition != "attachment":
            continue
        payload = part.get_payload(decode=True) or b""
        parts.append(
            {
                "index": len(parts),
                "filename": _decode_header_value(filename) or f"part-{len(parts)}",
                "content_type": part.get_content_type(),
                "size": len(payload),
            }
        )
    return parts


def extract_attachment(
    msg: email.message.Message, target: int | str
) -> tuple[str, bytes]:
    """Return ``(filename, bytes)`` for one exactly-resolved attachment.

    ``target`` is either the index from :func:`list_attachments` or a filename.
    A filename that matches several parts is refused rather than guessed, so a
    save never silently writes the wrong attachment.
    """
    payloads: list[tuple[str, bytes]] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        filename = part.get_filename()
        disposition = (part.get_content_disposition() or "").casefold()
        if not filename and disposition != "attachment":
            continue
        name = _decode_header_value(filename) or f"part-{len(payloads)}"
        payloads.append((name, part.get_payload(decode=True) or b""))

    if isinstance(target, int):
        if target < 0 or target >= len(payloads):
            raise MailError(
                f"Attachment index {target} is out of range; the message has {len(payloads)}."
            )
        return payloads[target]

    matches = [item for item in payloads if item[0] == target]
    if not matches:
        raise MailError(f"There is no attachment named {target!r} on this message.")
    if len(matches) > 1:
        raise MailError(
            f"Attachment name {target!r} is ambiguous ({len(matches)} parts share it); "
            "use the index from `ik mail attachments` instead."
        )
    return matches[0]


class IMAPClient:
    """Injectable IMAP client for mailbox access.

    Read commands use EXAMINE/BODY.PEEK and never change server-side state.
    Mutations are confined to the small set of methods that call
    :meth:`_select_writable` — flag changes, move, and draft delete — plus the
    protected-draft APPEND. Adding a new read path must use :meth:`_examine`.

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
        query: str | None = None,
        folder: str = "INBOX",
        limit: int | None = None,
        unread_only: bool = False,
        since: str | None = None,
        before: str | None = None,
        on: str | None = None,
        order: str = "newest",
        from_addr: str | None = None,
        to_addr: str | None = None,
        subject: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search messages in a folder.

        The positional ``query`` is a plain substring matched against SUBJECT or
        FROM (IMAP ``OR``); it is not a Gmail-style operator. ``from_addr``,
        ``to_addr``, and ``subject`` add structured IMAP criteria (ANDed). At
        least one of query/from_addr/to_addr/subject is required.
        """
        if order not in {"newest", "oldest"}:
            raise ValueError("order must be 'newest' or 'oldest'")
        if not any(value for value in (query, from_addr, to_addr, subject)):
            raise ValueError("provide a search query or at least one of --from/--to/--subject")
        self._examine(folder)
        criteria: list[str] = []
        if query:
            criteria.extend(["OR", "SUBJECT", query, "FROM", query])
        if from_addr:
            criteria.extend(["FROM", from_addr])
        if to_addr:
            criteria.extend(["TO", to_addr])
        if subject:
            criteria.extend(["SUBJECT", subject])
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
        """Fetch a full message by UID, returning parsed headers and readable body text."""
        self._examine(folder)
        typ, data = self._conn.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or not data[0]:
            raise MailError(f"Message UID {uid} not found")
        raw_msg = data[0][1] if isinstance(data[0], tuple) else data[0]
        msg = email.message_from_bytes(raw_msg)
        result = _slim_headers(msg, uid=uid)
        result["body_text"] = _body_text(msg)
        result["body_preview"] = _body_preview(msg)
        result["body_html"] = _body_html(msg)
        return result

    def fetch_raw(self, uid: str, folder: str = "INBOX") -> bytes:
        """Fetch one message's raw bytes using BODY.PEEK so \\Seen is not set."""
        self._examine(folder)
        typ, data = self._conn.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or not data[0]:
            raise MailError(f"Message UID {uid} not found in {folder}")
        raw = data[0][1] if isinstance(data[0], tuple) else data[0]
        if not isinstance(raw, (bytes, bytearray)):
            raise MailError(f"Unexpected IMAP payload for UID {uid}")
        return bytes(raw)

    def _select_writable(self, mailbox: str) -> None:
        """Read-write SELECT, used ONLY by mutating operations.

        Read paths keep using :meth:`_examine`, so listing, searching and reading
        can never change server-side state such as ``\\Seen``.
        """
        self._connect()
        typ, data = self._conn.select(mailbox, readonly=False)
        if typ != "OK":
            raise MailError(f"IMAP select failed for {mailbox}: {_format_imap_response(data)}")

    def _store_flag(self, uid: str, flag: str, *, add: bool, folder: str) -> dict[str, Any]:
        self._select_writable(folder)
        command = "+FLAGS" if add else "-FLAGS"
        typ, data = self._conn.uid("STORE", uid, command, f"({flag})")
        if typ != "OK":
            raise MailError(
                f"IMAP flag update failed for UID {uid} in {folder}: {_format_imap_response(data)}"
            )
        return {"uid": uid, "folder": folder, "flag": flag, "added": add}

    def mark_read(self, uid: str, folder: str = "INBOX") -> dict[str, Any]:
        return self._store_flag(uid, r"\Seen", add=True, folder=folder)

    def mark_unread(self, uid: str, folder: str = "INBOX") -> dict[str, Any]:
        return self._store_flag(uid, r"\Seen", add=False, folder=folder)

    def flag_message(self, uid: str, folder: str = "INBOX") -> dict[str, Any]:
        return self._store_flag(uid, r"\Flagged", add=True, folder=folder)

    def unflag_message(self, uid: str, folder: str = "INBOX") -> dict[str, Any]:
        return self._store_flag(uid, r"\Flagged", add=False, folder=folder)

    def message_flags(self, uid: str, folder: str = "INBOX") -> list[str]:
        """Read the flags of one message without changing them."""
        self._examine(folder)
        typ, data = self._conn.uid("FETCH", uid, "(FLAGS)")
        if typ != "OK" or not data or not data[0]:
            raise MailError(f"Message UID {uid} not found in {folder}")
        raw = data[0] if isinstance(data[0], bytes) else data[0][0]
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        match = re.search(r"FLAGS \(([^)]*)\)", text)
        return match.group(1).split() if match else []

    def move_message(self, uid: str, destination: str, folder: str = "INBOX") -> dict[str, Any]:
        """Move one message, preferring UID MOVE and falling back to COPY+EXPUNGE."""
        self._select_writable(folder)
        try:
            typ, data = self._conn.uid("MOVE", uid, destination)
            if typ == "OK":
                return {"uid": uid, "from": folder, "to": destination, "method": "MOVE"}
        except Exception:
            # Server does not implement RFC 6851 MOVE; fall through to COPY.
            pass

        typ, data = self._conn.uid("COPY", uid, destination)
        if typ != "OK":
            raise MailError(
                f"IMAP move failed for UID {uid} to {destination}: {_format_imap_response(data)}"
            )
        typ, data = self._conn.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
        if typ != "OK":
            raise MailError(
                f"IMAP move copied UID {uid} but could not mark the original deleted: "
                f"{_format_imap_response(data)}"
            )
        self._expunge_uid(uid)
        return {"uid": uid, "from": folder, "to": destination, "method": "COPY+EXPUNGE"}

    def _expunge_uid(self, uid: str) -> None:
        """Expunge exactly one UID, never the whole mailbox, when possible."""
        try:
            typ, data = self._conn.uid("EXPUNGE", uid)
            if typ == "OK":
                return
        except Exception:
            pass
        # UIDPLUS unavailable: the \Deleted flag is left set and the message is
        # hidden from listings, but we refuse a mailbox-wide EXPUNGE because it
        # would remove other messages the caller never named.
        raise MailError(
            f"UID {uid} was copied and marked deleted, but this server does not support "
            "UID EXPUNGE. Refusing a mailbox-wide EXPUNGE, which would affect other messages. "
            "Remove the original from your mail client."
        )

    def delete_draft(self, uid: str, folder: str | None = None) -> dict[str, Any]:
        """Delete exactly one draft by UID from the Drafts folder."""
        target = folder or self.drafts_folder()
        self._select_writable(target)
        typ, data = self._conn.uid("STORE", uid, "+FLAGS", r"(\Deleted)")
        if typ != "OK":
            raise MailError(
                f"IMAP draft delete failed for UID {uid}: {_format_imap_response(data)}"
            )
        self._expunge_uid(uid)
        return {"uid": uid, "folder": target, "status": "deleted"}

    def drafts_folder(self) -> str:
        drafts = next((item for item in self.list_folders() if item.get("role") == "drafts"), None)
        return str(drafts.get("name")) if drafts else "Drafts"

    def append_draft(
        self,
        message: email.message.EmailMessage,
        folder: str | None = None,
    ) -> dict[str, str]:
        """Append exactly one message with the IMAP ``\\Draft`` flag."""
        self._connect()
        target = folder
        if not target:
            drafts = next((item for item in self.list_folders() if item.get("role") == "drafts"), None)
            target = str(drafts.get("name")) if drafts else "Drafts"
        try:
            typ, data = self._conn.append(
                target,
                r"\Draft",
                None,
                message.as_bytes(policy=email.policy.SMTP),
            )
        except Exception as exc:
            detail = str(exc).replace(self.password, "***")
            raise MailError(f"IMAP draft save failed: {detail}") from exc
        if typ != "OK":
            raise MailError(f"IMAP draft save failed for {target}: {_format_imap_response(data)}")
        return {"folder": target, "status": "saved"}

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


class SMTPClient:
    """Injectable authenticated SMTP-over-SSL client for one-message sends."""

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        *,
        smtp_factory: Any = None,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self._smtp_factory = smtp_factory or smtplib.SMTP_SSL

    def send_message(self, message: email.message.EmailMessage) -> dict[str, str]:
        connection = None
        try:
            connection = self._smtp_factory(self.host, self.port)
            connection.login(self.username, self.password)
            refused = connection.send_message(message)
            if refused:
                raise MailError(f"SMTP refused {len(refused)} recipient(s)")
        except Exception as exc:
            if isinstance(exc, MailError):
                raise
            detail = str(exc).replace(self.password, "***")
            raise MailError(f"SMTP send failed: {detail}") from exc
        finally:
            if connection is not None:
                try:
                    connection.quit()
                except Exception:
                    pass
        return {"status": "sent"}


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
    body = _body_text(msg)
    if body is None:
        return None
    if len(body) > max_length:
        body = body[:max_length] + "…"
    return body


def _body_text(msg: email.message.Message) -> str | None:
    """Extract the full readable text body from a message without truncating it."""
    body = _extract_text_body(msg)
    if body is None:
        return None
    return body.strip()


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


def _body_html(msg: email.message.Message) -> str | None:
    """Return the raw HTML body (text/html part), unconverted, if present."""
    if not msg.is_multipart():
        if msg.get_content_type() != "text/html":
            return None
        payload = msg.get_payload(decode=True)
        if payload is None:
            return None
        return _decode_payload(payload, msg.get_content_charset())

    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            return _decode_payload(payload, part.get_content_charset())
    return None


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
    result = {
        "uid": msg.get("uid"),
        "from": msg.get("from"),
        "subject": msg.get("subject"),
        "date": msg.get("date"),
        "seen": msg.get("seen", False),
    }
    if "body_text" in msg:
        result["body_text"] = msg.get("body_text")
    if msg.get("body_html"):
        result["body_html"] = msg.get("body_html")
    return result


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
