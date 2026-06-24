import urllib.error

import pytest

from infomaniak_cli.services.dav_discovery import (
    DavDiscoveryError,
    discover_addressbooks,
    discover_calendars,
    discover_current_user_principal,
)


BASE_URL = "https://sync.example.test/"
PRINCIPAL_URL = "https://sync.example.test/dav/principals/users/user/"
ADDRESSBOOK_HOME = "https://sync.example.test/dav/addressbooks/user/"
CALENDAR_HOME = "https://sync.example.test/dav/calendars/user/"

PRINCIPAL_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/</D:href>
    <D:propstat>
      <D:prop>
        <D:current-user-principal>
          <D:href>/dav/principals/users/user/</D:href>
        </D:current-user-principal>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>
</D:multistatus>"""

ADDRESSBOOK_HOME_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:carddav">
  <D:response>
    <D:href>/dav/principals/users/user/</D:href>
    <D:propstat>
      <D:prop>
        <C:addressbook-home-set>
          <D:href>/dav/addressbooks/user/</D:href>
        </C:addressbook-home-set>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>"""

ADDRESSBOOKS_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:carddav">
  <D:response>
    <D:href>/dav/addressbooks/user/</D:href>
    <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/addressbooks/user/default/</D:href>
    <D:propstat><D:prop>
      <D:resourcetype><D:collection/><C:addressbook/></D:resourcetype>
      <D:displayname>Default</D:displayname>
    </D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/addressbooks/user/work/</D:href>
    <D:propstat><D:prop>
      <D:resourcetype><D:collection/><C:addressbook/></D:resourcetype>
      <D:displayname>Work</D:displayname>
    </D:prop></D:propstat>
  </D:response>
</D:multistatus>"""

CALENDAR_HOME_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response>
    <D:href>/dav/principals/users/user/</D:href>
    <D:propstat>
      <D:prop>
        <C:calendar-home-set>
          <D:href>/dav/calendars/user/</D:href>
        </C:calendar-home-set>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>"""

CALENDARS_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response>
    <D:href>/dav/calendars/user/</D:href>
    <D:propstat><D:prop><D:resourcetype><D:collection/></D:resourcetype></D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>/dav/calendars/user/personal/</D:href>
    <D:propstat><D:prop>
      <D:resourcetype><D:collection/><C:calendar/></D:resourcetype>
      <D:displayname>Personal</D:displayname>
    </D:prop></D:propstat>
  </D:response>
  <D:response>
    <D:href>https://other.example.test/dav/calendars/user/work/</D:href>
    <D:propstat><D:prop>
      <D:resourcetype><D:collection/><C:calendar/></D:resourcetype>
      <D:displayname>Work</D:displayname>
    </D:prop></D:propstat>
  </D:response>
</D:multistatus>"""


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def _routing_opener(routes, seen):
    def opener(request):
        seen.append(request)
        key = (request.full_url, request.headers.get("Depth"))
        if key not in routes:
            raise AssertionError(f"unexpected request: method={request.get_method()} key={key}")
        return FakeResponse(routes[key])

    return opener


def test_discover_current_user_principal_resolves_relative_href():
    seen = []
    opener = _routing_opener({(BASE_URL, "0"): PRINCIPAL_XML}, seen)

    principal = discover_current_user_principal(BASE_URL, "user", "pw", opener=opener)

    assert principal == PRINCIPAL_URL
    assert seen[0].get_method() == "PROPFIND"
    assert seen[0].headers["Depth"] == "0"
    body = seen[0].data.decode("utf-8")
    assert "current-user-principal" in body
    assert seen[0].headers["Authorization"].startswith("Basic ")


def test_discover_addressbooks_walks_principal_home_and_collections():
    seen = []
    opener = _routing_opener(
        {
            (BASE_URL, "0"): PRINCIPAL_XML,
            (PRINCIPAL_URL, "0"): ADDRESSBOOK_HOME_XML,
            (ADDRESSBOOK_HOME, "1"): ADDRESSBOOKS_XML,
        },
        seen,
    )

    addressbooks = discover_addressbooks(BASE_URL, "user", "pw", opener=opener)

    assert addressbooks == [
        {"url": "https://sync.example.test/dav/addressbooks/user/default/", "name": "Default"},
        {"url": "https://sync.example.test/dav/addressbooks/user/work/", "name": "Work"},
    ]
    # principal Depth 0, home-set Depth 0, enumerate Depth 1
    assert [req.headers["Depth"] for req in seen] == ["0", "0", "1"]
    assert "addressbook-home-set" in seen[1].data.decode("utf-8")
    enumerate_body = seen[2].data.decode("utf-8")
    assert "resourcetype" in enumerate_body
    assert "displayname" in enumerate_body


def test_discover_calendars_filters_by_resourcetype_and_keeps_absolute_href():
    seen = []
    opener = _routing_opener(
        {
            (BASE_URL, "0"): PRINCIPAL_XML,
            (PRINCIPAL_URL, "0"): CALENDAR_HOME_XML,
            (CALENDAR_HOME, "1"): CALENDARS_XML,
        },
        seen,
    )

    calendars = discover_calendars(BASE_URL, "user", "pw", opener=opener)

    assert calendars == [
        {"url": "https://sync.example.test/dav/calendars/user/personal/", "name": "Personal"},
        {"url": "https://other.example.test/dav/calendars/user/work/", "name": "Work"},
    ]
    assert "calendar-home-set" in seen[1].data.decode("utf-8")


def test_discover_returns_empty_when_no_principal():
    empty = b"""<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:"></D:multistatus>"""
    seen = []
    opener = _routing_opener({(BASE_URL, "0"): empty}, seen)

    assert discover_addressbooks(BASE_URL, "user", "pw", opener=opener) == []


def test_discover_error_redacts_password():
    password = "super-secret-pw"

    def opener(request):
        raise urllib.error.URLError(f"connect to user:{password}@host failed")

    with pytest.raises(DavDiscoveryError) as excinfo:
        discover_addressbooks(BASE_URL, "user", password, opener=opener)

    message = str(excinfo.value)
    assert password not in message
    assert "***" in message


def test_discover_error_on_http_status_is_clear():
    def opener(request):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    with pytest.raises(DavDiscoveryError) as excinfo:
        discover_current_user_principal(BASE_URL, "user", "pw", opener=opener)

    assert "HTTP 401" in str(excinfo.value)
