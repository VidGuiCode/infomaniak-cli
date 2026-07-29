from __future__ import annotations

import base64
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from ..api import redact_secret
from .dav_discovery import DavDiscoveryError, probe_collection


class ContactError(ValueError):
    pass


class _MethodRequest(urllib.request.Request):
    def __init__(self, *args: Any, method: str = "GET", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._method = method

    def get_method(self) -> str:
        return self._method


class ContactsClient:
    """Small CardDAV client for a configured address-book collection URL."""

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        *,
        opener: Callable[[urllib.request.Request], Any] | None = None,
    ) -> None:
        self.url = url
        self.username = username
        self.password = password
        self._opener = opener or urllib.request.urlopen

    def list_contacts(self, limit: int | None = None) -> list[dict[str, Any]]:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<C:addressbook-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:carddav">'
            "<D:prop><D:getetag/><C:address-data/></D:prop>"
            "</C:addressbook-query>"
        ).encode("utf-8")
        request = _MethodRequest(
            self.url,
            data=body,
            method="REPORT",
            headers={
                "Authorization": _basic_auth(self.username, self.password),
                "Content-Type": "application/xml; charset=utf-8",
                "Depth": "1",
            },
        )

        try:
            with self._opener(request) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            raise ContactError(f"Contacts CardDAV request failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ContactError(f"Contacts CardDAV request failed: {redact_secret(str(exc.reason))}") from exc
        except OSError as exc:
            raise ContactError(f"Contacts CardDAV request failed: {redact_secret(str(exc))}") from exc

        contacts = _parse_carddav_multistatus(payload, default_url=self.url)
        if not contacts:
            self._verify_collection_when_empty()
        if limit is not None:
            return contacts[:limit]
        return contacts

    def create_contact(self, vcard: str, uid: str) -> dict[str, Any]:
        collection = self.url.rstrip("/")
        resource_url = f"{collection}/{urllib.parse.quote(uid, safe='')}.vcf"
        return self._put_vcard(resource_url, vcard, uid=uid, if_none_match=True)

    def update_contact(self, vcard: str, contact: Mapping[str, Any]) -> dict[str, Any]:
        resource_url = contact.get("resource_url")
        etag = contact.get("etag")
        if not resource_url:
            raise ContactError("Resolved contact has no CardDAV resource URL; refusing update.")
        if not etag:
            raise ContactError("Resolved contact has no ETag; refusing an unsafe update.")
        uid = str(contact.get("id") or "")
        return self._put_vcard(str(resource_url), vcard, uid=uid, etag=str(etag))

    def delete_contact(self, contact: Mapping[str, Any]) -> dict[str, Any]:
        """Delete one exactly-resolved contact, conditional on its ETag.

        ``If-Match`` means a contact changed remotely since it was resolved is
        never removed on stale information.
        """
        resource_url = contact.get("url")
        if not resource_url:
            raise ContactError(
                "Resolved contact has no CardDAV resource URL; refusing an unsafe delete."
            )
        etag = contact.get("etag")
        if not etag:
            raise ContactError(
                "Resolved contact has no ETag; refusing an unconditional delete."
            )
        headers = {
            "Authorization": _basic_auth(self.username, self.password),
            "If-Match": str(etag),
        }
        request = _MethodRequest(str(resource_url), method="DELETE", headers=headers)
        try:
            with self._opener(request) as response:
                status = getattr(response, "status", None) or getattr(response, "code", 204)
        except urllib.error.HTTPError as exc:
            if exc.code == 412:
                raise ContactError(
                    "Contact changed remotely since it was resolved; nothing was deleted."
                ) from exc
            raise ContactError(f"Contacts CardDAV delete failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ContactError(
                f"Contacts CardDAV delete failed: "
                f"{redact_secret(str(exc.reason), secrets=[self.password])}"
            ) from exc
        except OSError as exc:
            raise ContactError(
                f"Contacts CardDAV delete failed: {redact_secret(str(exc), secrets=[self.password])}"
            ) from exc
        return {"url": str(resource_url), "status": status, "deleted": True}

    def _put_vcard(
        self,
        resource_url: str,
        vcard: str,
        *,
        uid: str,
        etag: str | None = None,
        if_none_match: bool = False,
    ) -> dict[str, Any]:
        headers = {
            "Authorization": _basic_auth(self.username, self.password),
            "Content-Type": "text/vcard; charset=utf-8",
        }
        if if_none_match:
            headers["If-None-Match"] = "*"
        if etag:
            headers["If-Match"] = etag
        request = _MethodRequest(
            resource_url,
            data=vcard.encode("utf-8"),
            method="PUT",
            headers=headers,
        )
        try:
            with self._opener(request) as response:
                status = getattr(response, "status", None) or getattr(response, "code", 200)
                response_headers = getattr(response, "headers", {}) or {}
                response_etag = response_headers.get("ETag") if hasattr(response_headers, "get") else None
        except urllib.error.HTTPError as exc:
            if exc.code == 412:
                action = "creation conflict" if if_none_match else "update conflict (contact changed remotely)"
                raise ContactError(f"Contacts {action}; nothing was overwritten.") from exc
            raise ContactError(f"Contacts CardDAV write failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ContactError(
                f"Contacts CardDAV write failed: "
                f"{redact_secret(str(exc.reason), secrets=[self.password])}"
            ) from exc
        except OSError as exc:
            raise ContactError(
                f"Contacts CardDAV write failed: {redact_secret(str(exc), secrets=[self.password])}"
            ) from exc
        return {"uid": uid, "url": resource_url, "status": status, "etag": response_etag}

    def _verify_collection_when_empty(self) -> None:
        """Distinguish an empty address book from a URL that is not one.

        A CardDAV REPORT against a non-addressbook URL (e.g. the bare sync
        base saved when discovery found nothing) returns an empty multistatus
        instead of an error, which silently looks like "0 contacts"
        (confirmed live against sync.infomaniak.com, see
        context/LIVE_API_FINDINGS.md).
        """
        try:
            probe = probe_collection(self.url, self.username, self.password, opener=self._opener)
        except DavDiscoveryError as exc:
            raise ContactError(
                f"Contacts collection check failed for {self.url}: {exc}. "
                "Run `ik auth contacts` to re-run auto-discovery, or pass --url <collection-url>."
            ) from exc
        if not probe["is_addressbook"]:
            raise ContactError(
                f"The configured contacts URL is not a CardDAV address book: {self.url}. "
                "Run `ik auth contacts` to re-run auto-discovery, or pass --url <collection-url>. "
                "If discovery finds no address book, the Infomaniak Contacts service may not be "
                "activated for this user yet - open the Contacts web app once, then retry."
            )


def slim_contact(contact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string_or_none(contact.get("id")),
        "display_name": _string_or_none(contact.get("display_name")),
        "given_name": _string_or_none(contact.get("given_name")),
        "family_name": _string_or_none(contact.get("family_name")),
        "emails": _string_list(contact.get("emails")),
        "phones": _string_list(contact.get("phones")),
        "organization": _string_or_none(contact.get("organization")),
        # 0.2.17: richer multi-value fields. `emails`/`phones` stay flat lists so
        # existing consumers keep working; the typed variants carry TYPE=.
        "typed_emails": list(contact.get("typed_emails") or []),
        "typed_phones": list(contact.get("typed_phones") or []),
        "addresses": list(contact.get("addresses") or []),
        "groups": _string_list(contact.get("groups")),
    }


def slim_contacts(contacts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_contact(contact) for contact in contacts]


def search_contacts(
    contacts: list[Mapping[str, Any]],
    query: str,
    *,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    query_lower = query.casefold()
    matches = [contact for contact in contacts if query_lower in _contact_search_text(contact)]
    if limit is not None:
        return matches[:limit]
    return matches


def find_contact(contacts: list[Mapping[str, Any]], contact_id: str) -> Mapping[str, Any] | None:
    for contact in contacts:
        if str(contact.get("id")) == str(contact_id):
            return contact
    return None


def build_vcard(
    *,
    uid: str,
    display_name: str,
    given_name: str | None = None,
    family_name: str | None = None,
    emails: list[str] | None = None,
    phones: list[str] | None = None,
    organization: str | None = None,
) -> str:
    if not uid.strip():
        raise ContactError("Contact UID is required.")
    if not display_name.strip():
        raise ContactError("Contact display name is required.")
    lines = [
        "BEGIN:VCARD",
        "VERSION:3.0",
        f"UID:{_escape_vcard_value(uid)}",
        f"FN:{_escape_vcard_value(display_name)}",
        "N:"
        + ";".join(
            [
                _escape_vcard_value(family_name or ""),
                _escape_vcard_value(given_name or ""),
                "",
                "",
                "",
            ]
        ),
    ]
    lines.extend(f"EMAIL:{_escape_vcard_value(value)}" for value in (emails or []) if value)
    lines.extend(f"TEL:{_escape_vcard_value(value)}" for value in (phones or []) if value)
    if organization:
        lines.append(f"ORG:{_escape_vcard_value(organization)}")
    lines.append("END:VCARD")
    return "\r\n".join(lines) + "\r\n"


def merge_vcard(
    raw_vcard: str,
    *,
    uid: str,
    display_name: str | None = None,
    given_name: str | None = None,
    family_name: str | None = None,
    emails: list[str] | None = None,
    phones: list[str] | None = None,
    organization: str | None = None,
) -> str:
    """Replace selected supported fields while preserving all other properties."""
    lines = _unfold_vcard_lines(raw_vcard)
    if not lines or lines[0].upper() != "BEGIN:VCARD" or lines[-1].upper() != "END:VCARD":
        raise ContactError("Resolved contact has no complete raw vCard; refusing an unsafe update.")

    replaced = {"UID"}
    replacement_lines = [f"UID:{_escape_vcard_value(uid)}"]
    if display_name is not None:
        replaced.add("FN")
        replacement_lines.append(f"FN:{_escape_vcard_value(display_name)}")
    if given_name is not None or family_name is not None:
        replaced.add("N")
        replacement_lines.append(
            "N:"
            + ";".join(
                [
                    _escape_vcard_value(family_name or ""),
                    _escape_vcard_value(given_name or ""),
                    "",
                    "",
                    "",
                ]
            )
        )
    if emails is not None:
        replaced.add("EMAIL")
        replacement_lines.extend(f"EMAIL:{_escape_vcard_value(value)}" for value in emails if value)
    if phones is not None:
        replaced.add("TEL")
        replacement_lines.extend(f"TEL:{_escape_vcard_value(value)}" for value in phones if value)
    if organization is not None:
        replaced.add("ORG")
        replacement_lines.append(f"ORG:{_escape_vcard_value(organization)}")

    preserved: list[str] = []
    for line in lines[:-1]:
        name = line.split(":", 1)[0].split(";", 1)[0].upper()
        if name not in replaced:
            preserved.append(line)
    return "\r\n".join([*preserved, *replacement_lines, "END:VCARD"]) + "\r\n"


def build_contacts_export(contacts: list[Mapping[str, Any]]) -> tuple[str, list[str]]:
    """Concatenate each contact's original vCard verbatim.

    Returns ``(vcf, skipped_ids)``. Copying ``raw_vcard`` untouched is what makes
    an export a faithful backup: photos, custom ``X-`` properties and anything
    else this CLI does not model survive a round trip.
    """
    blocks: list[str] = []
    skipped: list[str] = []
    for contact in contacts:
        raw = contact.get("raw_vcard")
        if not raw or not isinstance(raw, str) or "BEGIN:VCARD" not in raw.upper():
            skipped.append(str(contact.get("id") or contact.get("uid") or "<unknown>"))
            continue
        blocks.append(raw.strip("\r\n"))
    return "\r\n".join(blocks) + ("\r\n" if blocks else ""), skipped


def split_vcards(text: str) -> list[str]:
    """Split a multi-vCard document into individual vCard strings."""
    cards: list[str] = []
    current: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        upper = line.strip().upper()
        if upper == "BEGIN:VCARD":
            current = [line]
        elif upper == "END:VCARD":
            if current:
                current.append(line)
                cards.append("\r\n".join(current) + "\r\n")
                current = []
        elif current:
            current.append(line)
    return cards


def _normalized_key(value: Any) -> str:
    return " ".join(str(value or "").split()).casefold()


def find_duplicate_groups(contacts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Group contacts that share an email address, or failing that a display name.

    Detection only — nothing here merges or deletes. Email is checked first
    because it is the stronger signal; a name-only match is reported separately
    so the caller can judge it.
    """
    groups: list[dict[str, Any]] = []
    claimed: set[int] = set()

    by_email: dict[str, list[int]] = {}
    for index, contact in enumerate(contacts):
        for email in _string_list(contact.get("emails")):
            key = _normalized_key(email)
            if key:
                by_email.setdefault(key, []).append(index)
    for key, indexes in by_email.items():
        unique = sorted(set(indexes))
        if len(unique) > 1:
            groups.append({"reason": "email", "key": key, "contacts": [contacts[i] for i in unique]})
            claimed.update(unique)

    by_name: dict[str, list[int]] = {}
    for index, contact in enumerate(contacts):
        if index in claimed:
            continue
        key = _normalized_key(contact.get("display_name"))
        if key:
            by_name.setdefault(key, []).append(index)
    for key, indexes in by_name.items():
        unique = sorted(set(indexes))
        if len(unique) > 1:
            groups.append({"reason": "display_name", "key": key, "contacts": [contacts[i] for i in unique]})

    return groups


def merge_contact_fields(
    primary: Mapping[str, Any], secondary: Mapping[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Compute a union of two contacts, favouring the primary on conflicts.

    Returns ``(merged_fields, conflicts)``. The secondary is never modified or
    deleted here — merging is additive on the primary only, so nothing is lost
    silently.
    """
    merged: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []

    for field in ("display_name", "given_name", "family_name", "organization"):
        p_value = primary.get(field)
        s_value = secondary.get(field)
        if p_value and s_value and _normalized_key(p_value) != _normalized_key(s_value):
            conflicts.append({"field": field, "primary": p_value, "secondary": s_value})
        merged[field] = p_value or s_value or None

    for field in ("emails", "phones"):
        combined: list[str] = []
        seen: set[str] = set()
        for value in _string_list(primary.get(field)) + _string_list(secondary.get(field)):
            key = _normalized_key(value)
            if key and key not in seen:
                seen.add(key)
                combined.append(value)
        merged[field] = combined

    return merged, conflicts


def parse_vcard(vcard: str, *, fallback_id: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": fallback_id,
        "display_name": None,
        "given_name": None,
        "family_name": None,
        "emails": [],
        "phones": [],
        "organization": None,
        "addresses": [],
        "groups": [],
        "typed_emails": [],
        "typed_phones": [],
        "raw_vcard": vcard,
    }
    for line in _unfold_vcard_lines(vcard):
        if ":" not in line:
            continue
        left, value = line.split(":", 1)
        name = left.split(";", 1)[0].upper()
        params = left.split(";")[1:]
        value_type = _type_parameter(params)
        value = _unescape_vcard_value(value)
        if name == "UID" and value:
            data["id"] = value
        elif name == "FN":
            data["display_name"] = value
        elif name == "N":
            parts = value.split(";")
            data["family_name"] = parts[0] or None
            data["given_name"] = parts[1] if len(parts) > 1 and parts[1] else None
        elif name == "EMAIL" and value:
            data["emails"].append(value)
            data["typed_emails"].append({"value": value, "type": value_type})
        elif name == "TEL" and value:
            data["phones"].append(value)
            data["typed_phones"].append({"value": value, "type": value_type})
        elif name == "ORG" and value:
            data["organization"] = value.split(";", 1)[0]
        elif name == "ADR" and value:
            parts = (value.split(";") + [""] * 7)[:7]
            data["addresses"].append(
                {
                    "type": value_type,
                    "post_office_box": parts[0] or None,
                    "extended": parts[1] or None,
                    "street": parts[2] or None,
                    "locality": parts[3] or None,
                    "region": parts[4] or None,
                    "postal_code": parts[5] or None,
                    "country": parts[6] or None,
                }
            )
        elif name == "CATEGORIES" and value:
            data["groups"].extend(item.strip() for item in value.split(",") if item.strip())

    if not data["display_name"]:
        data["display_name"] = _fallback_display_name(data)
    if not data["id"]:
        data["id"] = data["display_name"] or (data["emails"][0] if data["emails"] else None)
    return data


def _parse_carddav_multistatus(payload: bytes, *, default_url: str) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ContactError("Unexpected Contacts CardDAV response: invalid XML") from exc

    contacts: list[dict[str, Any]] = []
    for response in root.findall(".//{DAV:}response"):
        href = response.findtext("{DAV:}href")
        etag = response.findtext(".//{DAV:}getetag")
        address_data = response.findtext(".//{urn:ietf:params:xml:ns:carddav}address-data")
        if not address_data:
            continue
        contact = parse_vcard(address_data, fallback_id=_id_from_href(href))
        contact["resource_url"] = urllib.parse.urljoin(default_url, href or "")
        contact["etag"] = etag
        contacts.append(contact)
    return contacts


def _basic_auth(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    name = PurePosixPath(href).name
    if name.endswith(".vcf"):
        return name[:-4]
    return name or None


def _unfold_vcard_lines(vcard: str) -> list[str]:
    lines: list[str] = []
    for raw_line in vcard.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw_line:
            continue
        if raw_line.startswith((" ", "\t")) and lines:
            lines[-1] += raw_line[1:]
        else:
            lines.append(raw_line)
    return lines


def _unescape_vcard_value(value: str) -> str:
    return (
        value.replace(r"\n", "\n")
        .replace(r"\N", "\n")
        .replace(r"\;", ";")
        .replace(r"\,", ",")
        .replace(r"\\", "\\")
    )


def _escape_vcard_value(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


def _type_parameter(params: list[str]) -> str | None:
    """Extract a vCard TYPE= parameter value, e.g. EMAIL;TYPE=work."""
    for param in params:
        key, _, value = param.partition("=")
        if key.strip().upper() == "TYPE" and value.strip():
            return value.strip().strip('"').casefold()
    return None


def _fallback_display_name(data: Mapping[str, Any]) -> str | None:
    name_parts = [part for part in (data.get("given_name"), data.get("family_name")) if part]
    if name_parts:
        return " ".join(str(part) for part in name_parts)
    if data.get("organization"):
        return str(data["organization"])
    emails = data.get("emails")
    if isinstance(emails, list) and emails:
        return str(emails[0])
    return None


def _contact_search_text(contact: Mapping[str, Any]) -> str:
    values = [
        contact.get("display_name"),
        contact.get("given_name"),
        contact.get("family_name"),
        contact.get("organization"),
        *_string_list(contact.get("emails")),
        *_string_list(contact.get("phones")),
    ]
    return " ".join(str(value) for value in values if value).casefold()


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]
