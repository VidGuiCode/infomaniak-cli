"""Read-only CardDAV/CalDAV collection discovery (RFC 5397/6352/4791).

Discovery walks the standard DAV chain: current-user-principal -> home-set ->
Depth:1 collection enumeration, keeping only resources whose <resourcetype>
advertises an addressbook (CardDAV) or calendar (CalDAV). Everything here uses
read-only PROPFIND. Credentials travel as HTTP Basic auth and are never logged.
"""

from __future__ import annotations

import base64
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable

from ..api import redact_secret


DAV_NS = "DAV:"
CARDDAV_NS = "urn:ietf:params:xml:ns:carddav"
CALDAV_NS = "urn:ietf:params:xml:ns:caldav"


class DavDiscoveryError(ValueError):
    pass


class _MethodRequest(urllib.request.Request):
    def __init__(self, *args: Any, method: str = "GET", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._method = method

    def get_method(self) -> str:
        return self._method


def discover_current_user_principal(
    base_url: str,
    username: str,
    password: str,
    *,
    opener: Callable[[urllib.request.Request], Any] | None = None,
) -> str | None:
    """Return the current-user-principal URL for the credentials, or None."""
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:propfind xmlns:D="DAV:"><D:prop><D:current-user-principal/></D:prop></D:propfind>'
    )
    root = _xml_root(_propfind(base_url, username, password, body, depth="0", opener=opener))
    for response in root.findall(".//{DAV:}response"):
        href = response.find(".//{DAV:}current-user-principal/{DAV:}href")
        if href is not None and href.text:
            return _resolve_href(href.text, base_url)
    return None


def discover_addressbooks(
    base_url: str,
    username: str,
    password: str,
    *,
    opener: Callable[[urllib.request.Request], Any] | None = None,
) -> list[dict[str, Any]]:
    """Discover CardDAV address-book collections from a DAV base URL."""
    return _discover_collections(
        base_url,
        username,
        password,
        home_ns=CARDDAV_NS,
        home_prop="addressbook-home-set",
        collection_tag="addressbook",
        opener=opener,
    )


def discover_calendars(
    base_url: str,
    username: str,
    password: str,
    *,
    opener: Callable[[urllib.request.Request], Any] | None = None,
) -> list[dict[str, Any]]:
    """Discover CalDAV calendar collections from a DAV base URL."""
    return _discover_collections(
        base_url,
        username,
        password,
        home_ns=CALDAV_NS,
        home_prop="calendar-home-set",
        collection_tag="calendar",
        opener=opener,
    )


def _discover_collections(
    base_url: str,
    username: str,
    password: str,
    *,
    home_ns: str,
    home_prop: str,
    collection_tag: str,
    opener: Callable[[urllib.request.Request], Any] | None,
) -> list[dict[str, Any]]:
    principal_url = discover_current_user_principal(base_url, username, password, opener=opener)
    if not principal_url:
        return []
    home_url = _discover_home_set(
        principal_url, username, password, home_ns=home_ns, home_prop=home_prop, opener=opener
    )
    if not home_url:
        return []
    return _enumerate_collections(
        home_url, username, password, collection_ns=home_ns, collection_tag=collection_tag, opener=opener
    )


def _discover_home_set(
    principal_url: str,
    username: str,
    password: str,
    *,
    home_ns: str,
    home_prop: str,
    opener: Callable[[urllib.request.Request], Any] | None,
) -> str | None:
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<D:propfind xmlns:D="DAV:" xmlns:C="{home_ns}">'
        f"<D:prop><C:{home_prop}/></D:prop></D:propfind>"
    )
    root = _xml_root(_propfind(principal_url, username, password, body, depth="0", opener=opener))
    for response in root.findall(".//{DAV:}response"):
        href = response.find(f".//{{{home_ns}}}{home_prop}/{{DAV:}}href")
        if href is not None and href.text:
            return _resolve_href(href.text, principal_url)
    return None


def _enumerate_collections(
    home_url: str,
    username: str,
    password: str,
    *,
    collection_ns: str,
    collection_tag: str,
    opener: Callable[[urllib.request.Request], Any] | None,
) -> list[dict[str, Any]]:
    body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:propfind xmlns:D="DAV:"><D:prop><D:resourcetype/><D:displayname/></D:prop></D:propfind>'
    )
    root = _xml_root(_propfind(home_url, username, password, body, depth="1", opener=opener))
    collections: list[dict[str, Any]] = []
    for response in root.findall(".//{DAV:}response"):
        if not _resourcetype_contains(response, collection_ns, collection_tag):
            continue
        url = _resolve_href(response.findtext("{DAV:}href"), home_url)
        if not url:
            continue
        name = response.findtext(".//{DAV:}displayname") or _name_from_url(url)
        collections.append({"url": url, "name": name})
    return collections


def _resourcetype_contains(response: ET.Element, ns: str, tag: str) -> bool:
    target = f"{{{ns}}}{tag}"
    for resourcetype in response.iter("{DAV:}resourcetype"):
        for child in resourcetype:
            if child.tag == target:
                return True
    return False


def _propfind(
    url: str,
    username: str,
    password: str,
    body: str,
    *,
    depth: str,
    opener: Callable[[urllib.request.Request], Any] | None,
) -> bytes:
    request = _MethodRequest(
        url,
        data=body.encode("utf-8"),
        method="PROPFIND",
        headers={
            "Authorization": _basic_auth(username, password),
            "Content-Type": "application/xml; charset=utf-8",
            "Depth": depth,
        },
    )
    send = opener or urllib.request.urlopen
    try:
        with send(request) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise DavDiscoveryError(f"DAV discovery request failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise DavDiscoveryError(
            f"DAV discovery request failed: {redact_secret(str(exc.reason), secrets=[password])}"
        ) from exc
    except OSError as exc:
        raise DavDiscoveryError(
            f"DAV discovery request failed: {redact_secret(str(exc), secrets=[password])}"
        ) from exc


def _xml_root(payload: bytes) -> ET.Element:
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise DavDiscoveryError("Unexpected DAV discovery response: invalid XML") from exc


def _basic_auth(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _resolve_href(href: str | None, request_url: str) -> str | None:
    if not href:
        return None
    href = href.strip()
    if not href:
        return None
    if href.startswith(("http://", "https://")):
        return href
    return urllib.parse.urljoin(request_url, href)


def _name_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path.rstrip("/")
    name = path.rsplit("/", 1)[-1]
    return name or url
