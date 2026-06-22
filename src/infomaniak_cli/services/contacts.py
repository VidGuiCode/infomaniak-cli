from __future__ import annotations

import base64
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from ..api import redact_secret


class ContactError(ValueError):
    pass


class _MethodRequest(urllib.request.Request):
    def __init__(self, *args: Any, method: str = "GET", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._method = method

    def get_method(self) -> str:
        return self._method


class ContactsClient:
    """Small read-only CardDAV client for a configured address-book collection URL."""

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

        contacts = _parse_carddav_multistatus(payload)
        if limit is not None:
            return contacts[:limit]
        return contacts


def slim_contact(contact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string_or_none(contact.get("id")),
        "display_name": _string_or_none(contact.get("display_name")),
        "given_name": _string_or_none(contact.get("given_name")),
        "family_name": _string_or_none(contact.get("family_name")),
        "emails": _string_list(contact.get("emails")),
        "phones": _string_list(contact.get("phones")),
        "organization": _string_or_none(contact.get("organization")),
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


def parse_vcard(vcard: str, *, fallback_id: str | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": fallback_id,
        "display_name": None,
        "given_name": None,
        "family_name": None,
        "emails": [],
        "phones": [],
        "organization": None,
        "raw_vcard": vcard,
    }
    for line in _unfold_vcard_lines(vcard):
        if ":" not in line:
            continue
        left, value = line.split(":", 1)
        name = left.split(";", 1)[0].upper()
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
        elif name == "TEL" and value:
            data["phones"].append(value)
        elif name == "ORG" and value:
            data["organization"] = value.split(";", 1)[0]

    if not data["display_name"]:
        data["display_name"] = _fallback_display_name(data)
    if not data["id"]:
        data["id"] = data["display_name"] or (data["emails"][0] if data["emails"] else None)
    return data


def _parse_carddav_multistatus(payload: bytes) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ContactError("Unexpected Contacts CardDAV response: invalid XML") from exc

    contacts: list[dict[str, Any]] = []
    for response in root.findall(".//{DAV:}response"):
        href = response.findtext("{DAV:}href")
        address_data = response.findtext(".//{urn:ietf:params:xml:ns:carddav}address-data")
        if not address_data:
            continue
        contacts.append(parse_vcard(address_data, fallback_id=_id_from_href(href)))
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
