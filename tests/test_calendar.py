import datetime
import json

import pytest

from infomaniak_cli import cli
from infomaniak_cli.auth import CalendarPasswordStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.dav_discovery import DavDiscoveryError
from infomaniak_cli.services.calendar import (
    CalendarClient,
    CalendarConflictError,
    CalendarError,
    build_calendar_export_ics,
    build_event_ics,
    find_event,
    format_ics_datetime,
    patch_event_ics,
    parse_event_input,
    parse_ics_events,
    search_events,
    slim_calendar,
    slim_event,
)


CALENDARS = [
    {
        "id": "work",
        "name": "Work",
        "url": "https://sync.example.test/calendars/user/work/",
        "color": "#0088cc",
        "description": "Work calendar",
        "raw": {"extra": True},
    }
]

EVENTS = [
    {
        "id": "event-1",
        "uid": "uid-1",
        "calendar_id": "work",
        "summary": "Team Sync",
        "description": "Discuss roadmap",
        "location": "Office",
        "starts_at": "2026-06-24T09:00:00Z",
        "ends_at": "2026-06-24T10:00:00Z",
        "all_day": False,
        "status": "CONFIRMED",
        "organizer": "boss@example.com",
        "attendees": ["alice@example.com"],
        "url": "https://sync.example.test/calendars/user/work/uid-1.ics",
        "etag": '"etag-1"',
        "raw_ics": "\r\n".join([
            "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:uid-1",
            "DTSTART:20260624T090000Z", "DTEND:20260624T100000Z", "SUMMARY:Team Sync",
            "ATTENDEE:mailto:alice@example.com", "END:VEVENT", "END:VCALENDAR", "",
        ]),
    },
    {
        "id": "event-2",
        "uid": "uid-2",
        "calendar_id": "work",
        "summary": "Invoice review",
        "description": "Review supplier invoice",
        "location": "Home",
        "starts_at": "2026-06-23",
        "ends_at": "2026-06-24",
        "all_day": True,
        "status": "CONFIRMED",
        "organizer": None,
        "attendees": [],
        "url": "https://sync.example.test/calendars/user/work/uid-2.ics",
        "etag": '"etag-2"',
        "raw_ics": "\r\n".join([
            "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:uid-2",
            "DTSTART;VALUE=DATE:20260623", "DTEND;VALUE=DATE:20260624",
            "SUMMARY:Invoice review", "DESCRIPTION:Review supplier invoice", "LOCATION:Home",
            "STATUS:CONFIRMED", "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15M",
            "DESCRIPTION:Reminder", "END:VALARM", "END:VEVENT", "END:VCALENDAR", "",
        ]),
    },
]


class FakeCalendarClient:
    def __init__(self, url, username, password):
        self.url = url
        self.username = username
        self.password = password
        self.calls = []
        self.updated = {}
        self.deleted_urls = set()

    def list_calendars(self):
        self.calls.append(("list_calendars",))
        return CALENDARS

    def list_events(self, *, calendar=None, start=None, end=None, limit=None):
        self.calls.append(("list_events", calendar, start, end, limit))
        events = []
        for event in EVENTS:
            if event.get("url") in self.deleted_urls:
                continue
            events.append(self.updated.get(event.get("uid"), event))
        if limit is not None:
            return events[:limit]
        return events

    def create_event(self, ics, uid, *, calendar=None):
        self.calls.append(("create_event", ics, uid, calendar))
        return {"uid": uid, "url": f"{self.url}{uid}.ics", "status": 201}

    def update_event(self, event_url, ics, etag):
        self.calls.append(("update_event", event_url, ics, etag))
        event = parse_ics_events(ics, calendar_id="work")[0]
        event.update({"url": event_url, "etag": '"new-etag"'})
        self.updated[event["uid"]] = event
        return {"url": event_url, "etag": '"new-etag"', "status": 204}

    def delete_event(self, event_url, etag):
        self.calls.append(("delete_event", event_url, etag))
        self.deleted_urls.add(event_url)
        return {"url": event_url, "status": 204}


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def _configured_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        calendar_url="https://sync.example.test/calendars/user/work/",
        calendar_username="user@example.com",
        make_default=True,
    )
    CalendarPasswordStore().save_password("work", "secret-calendar-password")


def _freeze_now(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_now_utc",
        lambda: datetime.datetime(2026, 6, 23, 10, 0, tzinfo=datetime.UTC),
        raising=False,
    )
    monkeypatch.setattr(cli, "_today", lambda: datetime.date(2026, 6, 23))


def test_slim_calendar_projects_stable_fields():
    assert slim_calendar(CALENDARS[0]) == {
        "id": "work",
        "name": "Work",
        "url": "https://sync.example.test/calendars/user/work/",
        "color": "#0088cc",
        "description": "Work calendar",
    }


def test_slim_event_projects_stable_fields():
    assert slim_event(EVENTS[0]) == {
        "id": "event-1",
        "uid": "uid-1",
        "calendar_id": "work",
        "summary": "Team Sync",
        "description": "Discuss roadmap",
        "location": "Office",
        "starts_at": "2026-06-24T09:00:00Z",
        "ends_at": "2026-06-24T10:00:00Z",
        "all_day": False,
        "status": "CONFIRMED",
        "organizer": "boss@example.com",
        "attendees": ["alice@example.com"],
    }


def test_parse_ics_simple_vevent():
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
UID:uid-1
SUMMARY:Team Sync
DESCRIPTION:Discuss roadmap
LOCATION:Office
DTSTART:20260624T090000Z
DTEND:20260624T100000Z
STATUS:CONFIRMED
ORGANIZER;CN=Boss:mailto:boss@example.com
ATTENDEE;CN=Alice:mailto:alice@example.com
END:VEVENT
END:VCALENDAR
"""

    events = parse_ics_events(ics, calendar_id="work", fallback_id="event-1")

    assert events == [
        {
            "id": "uid-1",
            "uid": "uid-1",
            "calendar_id": "work",
            "summary": "Team Sync",
            "description": "Discuss roadmap",
            "location": "Office",
            "starts_at": "2026-06-24T09:00:00Z",
            "ends_at": "2026-06-24T10:00:00Z",
            "all_day": False,
            "status": "CONFIRMED",
            "organizer": "boss@example.com",
            "attendees": ["alice@example.com"],
            "raw_ics": "BEGIN:VEVENT\nUID:uid-1\nSUMMARY:Team Sync\nDESCRIPTION:Discuss roadmap\nLOCATION:Office\nDTSTART:20260624T090000Z\nDTEND:20260624T100000Z\nSTATUS:CONFIRMED\nORGANIZER;CN=Boss:mailto:boss@example.com\nATTENDEE;CN=Alice:mailto:alice@example.com\nEND:VEVENT",
        }
    ]


def test_caldav_client_constructs_calendar_and_event_requests():
    seen_requests = []
    calendar_payload = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav" xmlns:CS="http://calendarserver.org/ns/">
  <D:response>
    <D:href>/calendars/user/work/</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>Work</D:displayname>
        <CS:getctag>abc</CS:getctag>
        <C:calendar-description>Work calendar</C:calendar-description>
        <CS:calendar-color>#0088cc</CS:calendar-color>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>"""
    events_payload = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response>
    <D:href>/calendars/user/work/uid-1.ics</D:href>
    <D:propstat>
      <D:prop>
        <C:calendar-data>BEGIN:VCALENDAR
BEGIN:VEVENT
UID:uid-1
SUMMARY:Team Sync
DTSTART:20260624T090000Z
DTEND:20260624T100000Z
END:VEVENT
END:VCALENDAR</C:calendar-data>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>"""

    def opener(request):
        seen_requests.append(request)
        if request.get_method() == "PROPFIND":
            return FakeResponse(calendar_payload)
        return FakeResponse(events_payload)

    client = CalendarClient("https://sync.example.test/calendars/user/work/", "user@example.com", "pw", opener=opener)

    calendars = client.list_calendars()
    events = client.list_events(start=datetime.datetime(2026, 6, 23, tzinfo=datetime.UTC), end=datetime.datetime(2026, 6, 30, tzinfo=datetime.UTC))

    assert calendars[0]["id"] == "work"
    assert calendars[0]["name"] == "Work"
    assert events[0]["uid"] == "uid-1"
    assert seen_requests[0].get_method() == "PROPFIND"
    assert seen_requests[0].headers["Depth"] == "0"
    assert seen_requests[1].get_method() == "REPORT"
    assert seen_requests[1].headers["Depth"] == "1"


EMPTY_MULTISTATUS = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:"/>"""

CALENDAR_RESOURCETYPE = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response>
    <D:href>/calendars/user/work/</D:href>
    <D:propstat><D:prop>
      <D:resourcetype><D:collection/><C:calendar/></D:resourcetype>
    </D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
  </D:response>
</D:multistatus>"""

PLAIN_COLLECTION_RESOURCETYPE = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/</D:href>
    <D:propstat><D:prop>
      <D:resourcetype><D:collection/></D:resourcetype>
    </D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
  </D:response>
</D:multistatus>"""


def test_caldav_client_empty_real_calendar_returns_no_events():
    seen = []

    def opener(request):
        seen.append(request)
        if request.get_method() == "REPORT":
            return FakeResponse(EMPTY_MULTISTATUS)
        return FakeResponse(CALENDAR_RESOURCETYPE)

    client = CalendarClient("https://sync.example.test/calendars/user/work/", "user@example.com", "pw", opener=opener)

    assert client.list_events() == []
    assert [request.get_method() for request in seen] == ["REPORT", "PROPFIND"]


def test_caldav_client_zero_events_on_non_calendar_url_is_actionable():
    # Live sync.infomaniak.com finding: a REPORT against the bare sync base
    # returns an empty multistatus, which used to look like "0 events".
    import pytest

    from infomaniak_cli.services.calendar import CalendarError

    def opener(request):
        if request.get_method() == "REPORT":
            return FakeResponse(EMPTY_MULTISTATUS)
        return FakeResponse(PLAIN_COLLECTION_RESOURCETYPE)

    client = CalendarClient("https://sync.example.test/", "user@example.com", "pw", opener=opener)

    with pytest.raises(CalendarError) as excinfo:
        client.list_events()

    message = str(excinfo.value)
    assert "not a CalDAV calendar" in message
    assert "https://sync.example.test/" in message
    assert "ik auth calendar" in message


def test_caldav_client_zero_events_with_failing_probe_reports_status():
    import urllib.error

    import pytest

    from infomaniak_cli.services.calendar import CalendarError

    def opener(request):
        if request.get_method() == "REPORT":
            return FakeResponse(EMPTY_MULTISTATUS)
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    client = CalendarClient("https://sync.example.test/", "user@example.com", "pw", opener=opener)

    with pytest.raises(CalendarError) as excinfo:
        client.list_events()

    message = str(excinfo.value)
    assert "HTTP 404" in message
    assert "ik auth calendar" in message


def test_search_events_matches_fields_case_insensitively():
    assert [event["id"] for event in search_events(EVENTS, "team sync")] == ["event-1"]
    assert [event["id"] for event in search_events(EVENTS, "SUPPLIER")] == ["event-2"]
    assert [event["id"] for event in search_events(EVENTS, "office")] == ["event-1"]
    assert [event["id"] for event in search_events(EVENTS, "alice@example.com")] == ["event-1"]


def test_find_event_returns_existing_event_by_id_or_uid():
    assert find_event(EVENTS, "event-1")["summary"] == "Team Sync"
    assert find_event(EVENTS, "uid-2")["summary"] == "Invoice review"


def test_cli_calendar_list_slim_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created_clients = []

    def make_client(url, username, password):
        client = FakeCalendarClient(url, username, password)
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "CalendarClient", make_client)

    assert cli.main(["calendar", "list", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "profile": "work",
        "count": 1,
        "calendars": [
            {
                "id": "work",
                "name": "Work",
                "url": "https://sync.example.test/calendars/user/work/",
                "color": "#0088cc",
                "description": "Work calendar",
            }
        ],
    }
    assert created_clients[0].url == "https://sync.example.test/calendars/user/work/"
    assert created_clients[0].username == "user@example.com"
    assert created_clients[0].password == "secret-calendar-password"


def test_cli_calendar_list_raw_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "list", "--json", "--raw"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["calendars"][0]["raw"] == {"extra": True}


def test_cli_calendar_upcoming_days_limit_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _freeze_now(monkeypatch)
    created_clients = []

    def make_client(url, username, password):
        client = FakeCalendarClient(url, username, password)
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "CalendarClient", make_client)

    assert cli.main(["calendar", "upcoming", "--days", "7", "--limit", "1", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["days"] == 7
    assert output["count"] == 1
    assert output["events"][0]["id"] == "event-1"
    call = created_clients[0].calls[0]
    assert call[0] == "list_events"
    assert call[1] is None
    assert call[4] == 1


def test_cli_calendar_today_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _freeze_now(monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "today", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["count"] == 2
    assert "date" in output


def test_cli_calendar_search_filters_client_side(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _freeze_now(monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "search", "invoice", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["query"] == "invoice"
    assert output["count"] == 1
    assert output["events"][0]["id"] == "event-2"


def test_cli_calendar_search_explicit_range_reaches_caldav_client(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created_clients = []

    def make_client(url, username, password):
        client = FakeCalendarClient(url, username, password)
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "CalendarClient", make_client)

    assert cli.main([
        "calendar", "search", "invoice",
        "--from", "2026-01-01",
        "--to", "2026-02-01T12:30:00+01:00",
        "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["from"] == "2026-01-01T00:00:00Z"
    assert output["to"] == "2026-02-01T11:30:00Z"
    assert output["days"] is None
    call = created_clients[0].calls[0]
    assert call[2] == datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)
    assert call[3] == datetime.datetime(2026, 2, 1, 11, 30, tzinfo=datetime.UTC)


def test_cli_calendar_search_range_requires_both_bounds(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "search", "invoice", "--from", "2026-01-01"]) == 1

    assert "--from and --to must be used together" in capsys.readouterr().err


def test_cli_calendar_search_rejects_days_with_explicit_range(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main([
        "calendar", "search", "invoice", "--days", "7",
        "--from", "2026-01-01", "--to", "2026-02-01",
    ]) == 1

    assert "--days cannot be combined with --from/--to" in capsys.readouterr().err


def test_cli_calendar_search_rejects_reversed_range(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main([
        "calendar", "search", "invoice",
        "--from", "2026-02-01", "--to", "2026-01-01",
    ]) == 1

    assert "--to must be after --from" in capsys.readouterr().err


def test_cli_calendar_create_accepts_global_profile_after_subcommand(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created_clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create",
        "--summary", "Placement check",
        "--start", "2026-07-20T14:00",
        "--yes", "--json", "--profile", "work",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["created"] is True
    assert created_clients[0].calls[-1][0] == "create_event"


# --- v0.2.13 calendar discovery repair -------------------------------------


COLLECTION_URL = "https://sync.example.test/calendars/user/work/"


def _root_url_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        calendar_url="https://sync.infomaniak.com/",
        calendar_username="VG00000",
        make_default=True,
    )
    CalendarPasswordStore().save_password("work", "secret-calendar-password")


def test_calendar_read_auto_discovers_when_the_saved_url_is_only_the_service_root(
    tmp_path, monkeypatch, capsys
):
    _root_url_profile(tmp_path, monkeypatch)
    seen = []

    def fake_discover(url, username, password):
        seen.append(url)
        return [{"url": COLLECTION_URL, "name": "work"}]

    monkeypatch.setattr(cli, "discover_calendars", fake_discover)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "list", "--json"]) == 0

    assert seen == ["https://sync.infomaniak.com/"]
    assert "auto-discovered calendar collection" in capsys.readouterr().err


def test_calendar_read_does_not_discover_when_the_saved_url_is_already_a_collection(
    tmp_path, monkeypatch
):
    _configured_profile(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(cli, "discover_calendars", lambda *a, **k: calls.append(a) or [])
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "list", "--json"]) == 0
    assert calls == []


def test_calendar_read_repair_failure_keeps_the_saved_url_and_does_not_raise(
    tmp_path, monkeypatch, capsys
):
    _root_url_profile(tmp_path, monkeypatch)

    def failing_discover(url, username, password):
        raise DavDiscoveryError("principal not provisioned for secret-calendar-password")

    monkeypatch.setattr(cli, "discover_calendars", failing_discover)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "list", "--json"]) == 0

    err = capsys.readouterr().err
    assert "auto-discovery failed" in err
    assert "secret-calendar-password" not in err


def test_cli_calendar_repair_persists_the_discovered_collection(tmp_path, monkeypatch, capsys):
    _root_url_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli, "discover_calendars", lambda *a, **k: [{"url": COLLECTION_URL, "name": "work"}]
    )

    assert cli.main(["--profile", "work", "calendar", "repair", "--yes", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["saved"] is True
    assert payload["changed"] is True
    assert payload["after"] == COLLECTION_URL
    assert ProfileManager().get("work").calendar_url == COLLECTION_URL


def test_cli_calendar_repair_dry_run_changes_nothing(tmp_path, monkeypatch, capsys):
    _root_url_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli, "discover_calendars", lambda *a, **k: [{"url": COLLECTION_URL, "name": "work"}]
    )

    assert cli.main(["calendar", "repair", "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["saved"] is False
    assert payload["dry_run"] is True
    assert ProfileManager().get("work").calendar_url == "https://sync.infomaniak.com/"


def test_cli_calendar_repair_requires_an_explicit_profile_for_yes(tmp_path, monkeypatch, capsys):
    _root_url_profile(tmp_path, monkeypatch)
    monkeypatch.delenv("IK_PROFILE", raising=False)
    monkeypatch.setattr(
        cli, "discover_calendars", lambda *a, **k: [{"url": COLLECTION_URL, "name": "work"}]
    )

    assert cli.main(["calendar", "repair", "--yes"]) == 1

    assert "profile is explicit" in capsys.readouterr().err
    assert ProfileManager().get("work").calendar_url == "https://sync.infomaniak.com/"


def test_cli_calendar_repair_refuses_to_guess_between_several_collections(
    tmp_path, monkeypatch, capsys
):
    _root_url_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(
        cli,
        "discover_calendars",
        lambda *a, **k: [
            {"url": COLLECTION_URL, "name": "work"},
            {"url": "https://sync.example.test/calendars/user/personal/", "name": "personal"},
        ],
    )

    assert cli.main(["--profile", "work", "calendar", "repair", "--yes"]) == 1

    err = capsys.readouterr().err
    assert "refusing to guess" in err
    assert "--url" in err
    # nothing was persisted
    assert ProfileManager().get("work").calendar_url == "https://sync.infomaniak.com/"


def test_cli_calendar_repair_accepts_an_explicit_url_without_discovery(tmp_path, monkeypatch, capsys):
    _root_url_profile(tmp_path, monkeypatch)
    called = []
    monkeypatch.setattr(cli, "discover_calendars", lambda *a, **k: called.append(a) or [])

    assert cli.main([
        "--profile", "work", "calendar", "repair", "--url", COLLECTION_URL, "--yes", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["after"] == COLLECTION_URL
    assert called == []
    assert ProfileManager().get("work").calendar_url == COLLECTION_URL


def test_cli_calendar_repair_reports_a_discovery_failure_with_redaction(
    tmp_path, monkeypatch, capsys
):
    _root_url_profile(tmp_path, monkeypatch)

    def failing_discover(url, username, password):
        raise DavDiscoveryError("no principal for secret-calendar-password")

    monkeypatch.setattr(cli, "discover_calendars", failing_discover)

    assert cli.main(["--profile", "work", "calendar", "repair", "--yes"]) == 1

    err = capsys.readouterr().err
    assert "Calendar discovery failed" in err
    assert "secret-calendar-password" not in err


# --- v0.2.13 read-only export ----------------------------------------------


def test_build_calendar_export_ics_preserves_event_bodies_verbatim():
    ics, skipped = build_calendar_export_ics(EVENTS)

    assert skipped == []
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.endswith("END:VCALENDAR\r\n")
    assert ics.count("BEGIN:VEVENT") == 2
    # the second event's unmodeled VALARM survives the round trip
    assert "BEGIN:VALARM" in ics
    assert "TRIGGER:-PT15M" in ics
    assert "ATTENDEE:mailto:alice@example.com" in ics


def test_build_calendar_export_ics_reports_events_without_a_vevent():
    ics, skipped = build_calendar_export_ics([{"uid": "uid-broken", "raw_ics": "not-ics"}])

    assert skipped == ["uid-broken"]
    assert "BEGIN:VEVENT" not in ics


def test_cli_calendar_export_writes_an_ics_file(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)
    target = tmp_path / "backup" / "events.ics"

    assert cli.main([
        "calendar", "export", "--output", str(target), "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["format"] == "ics"
    assert payload["count"] == 2
    assert payload["skipped"] == []
    written = target.read_text(encoding="utf-8")
    assert written.count("BEGIN:VEVENT") == 2


def test_cli_calendar_export_refuses_to_overwrite_without_force(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)
    target = tmp_path / "events.ics"
    target.write_text("original", encoding="utf-8")

    assert cli.main(["calendar", "export", "--output", str(target)]) == 1
    assert "Refusing to overwrite" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "original"

    assert cli.main(["calendar", "export", "--output", str(target), "--force"]) == 0
    assert "BEGIN:VCALENDAR" in target.read_text(encoding="utf-8")


def test_cli_calendar_export_json_format_to_stdout(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "export", "--format", "json"]) == 0

    events = json.loads(capsys.readouterr().out)
    assert [event["uid"] for event in events] == ["uid-1", "uid-2"]


def test_cli_calendar_export_without_output_keeps_json_envelope_structured(
    tmp_path, monkeypatch, capsys
):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "export", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["output"] is None
    assert payload["format"] == "ics"
    assert payload["count"] == 2
    assert payload["body"].startswith("BEGIN:VCALENDAR")


def test_cli_calendar_export_is_read_only_and_never_writes_to_the_service(
    tmp_path, monkeypatch, capsys
):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main(["calendar", "export", "--format", "json"]) == 0

    calls = [call[0] for client in clients for call in client.calls]
    assert calls == ["list_events"]


# --- v0.2.13 richer search filters -----------------------------------------


def test_search_events_filters_are_anded_with_the_free_text_query():
    assert [e["uid"] for e in search_events(EVENTS, "review")] == ["uid-2"]
    # the query alone matches uid-2, but the attendee filter excludes it
    assert search_events(EVENTS, "review", attendee="alice@example.com") == []


def test_search_events_attendee_filter_is_a_case_insensitive_substring():
    assert [e["uid"] for e in search_events(EVENTS, attendee="ALICE")] == ["uid-1"]
    assert search_events(EVENTS, attendee="nobody@example.com") == []


def test_search_events_uid_filter_is_exact_not_substring():
    assert [e["uid"] for e in search_events(EVENTS, uid="uid-1")] == ["uid-1"]
    assert search_events(EVENTS, uid="uid") == []


def test_search_events_status_filter_is_case_insensitive_exact():
    assert len(search_events(EVENTS, status="confirmed")) == 2
    assert search_events(EVENTS, status="CANCELLED") == []


def test_search_events_description_filter_matches_a_substring():
    assert [e["uid"] for e in search_events(EVENTS, description="supplier")] == ["uid-2"]


def test_search_events_all_day_filter_separates_timed_from_all_day():
    assert [e["uid"] for e in search_events(EVENTS, all_day=True)] == ["uid-2"]
    assert [e["uid"] for e in search_events(EVENTS, all_day=False)] == ["uid-1"]


def test_cli_calendar_search_supports_filters_without_a_query(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "search", "--all-day", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["events"][0]["uid"] == "uid-2"
    assert payload["filters"] == {"all_day": True}


def test_cli_calendar_search_requires_a_query_or_a_filter(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "search", "--json"]) == 1

    assert "needs a query or at least one filter" in capsys.readouterr().err


def test_cli_calendar_search_rejects_all_day_together_with_timed(tmp_path, monkeypatch):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    with pytest.raises(SystemExit):
        cli.main(["calendar", "search", "--all-day", "--timed"])


# --- v0.2.13 create-time reminders and duplicate-safe creation -------------


def test_cli_calendar_create_writes_repeatable_create_time_reminders(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create",
        "--summary", "Quarterly review",
        "--start", "2026-07-20T14:00",
        "--reminder-minutes", "1440",
        "--reminder-minutes", "30",
        "--yes", "--json", "--profile", "work",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is True
    assert payload["reminders"] == [1440, 30]
    ics = clients[0].calls[-1][1]
    assert ics.count("BEGIN:VALARM") == 2
    triggers = [line for line in ics.split("\r\n") if line.startswith("TRIGGER:")]
    assert triggers == ["TRIGGER:-PT1440M", "TRIGGER:-PT30M"]


def test_cli_calendar_create_without_reminders_writes_no_alarm(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create", "--summary", "Team sync", "--start", "2026-07-20T14:00",
        "--yes", "--json", "--profile", "work",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["reminders"] == []
    assert "VALARM" not in clients[0].calls[-1][1]


def test_cli_calendar_create_writes_a_recurrence_rule_without_attendees(
    tmp_path, monkeypatch, capsys
):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create", "--summary", "Quarterly deadline", "--start", "2026-07-20T09:00",
        "--rrule", "FREQ=MONTHLY;INTERVAL=3;COUNT=4",
        "--yes", "--json", "--profile", "work",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is True
    assert payload["rrule"] == "FREQ=MONTHLY;INTERVAL=3;COUNT=4"
    ics = clients[0].calls[-1][1]
    assert "RRULE:FREQ=MONTHLY;INTERVAL=3;COUNT=4" in ics
    # recurrence must never smuggle in a third-party notification
    assert "ATTENDEE" not in ics
    assert "ORGANIZER" not in ics


def test_cli_calendar_create_rejects_a_malformed_rrule_before_writing(
    tmp_path, monkeypatch, capsys
):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create", "--summary", "Team sync", "--start", "2026-07-20T09:00",
        "--rrule", "INTERVAL=3", "--yes", "--profile", "work",
    ]) == 1

    assert "--rrule must include FREQ" in capsys.readouterr().err
    assert not any(call[0] == "create_event" for c in clients for call in c.calls)


def test_cli_calendar_create_series_creates_one_event_per_date_with_derived_uids(
    tmp_path, monkeypatch, capsys
):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create-series", "--summary", "Quarterly deadline",
        "--date", "2026-03-31T09:00", "--date", "2026-06-30T09:00",
        "--uid-prefix", "quarterly-2026", "--yes", "--json", "--profile", "work",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 2
    assert payload["created"] == 2
    assert [item["uid"] for item in payload["results"]] == [
        "quarterly-2026-20260331T0900", "quarterly-2026-20260630T0900"
    ]
    creates = [c for client in clients for c in client.calls if c[0] == "create_event"]
    assert len(creates) == 2
    assert all("ATTENDEE" not in call[1] for call in creates)


def test_cli_calendar_create_series_dry_run_creates_nothing(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create-series", "--summary", "Quarterly deadline",
        "--date", "2026-03-31T09:00", "--uid-prefix", "quarterly-2026",
        "--dry-run", "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["created"] == 0
    assert not any(call[0] == "create_event" for c in clients for call in c.calls)


def test_cli_calendar_create_series_is_idempotent_with_if_missing(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)

    class ConflictingClient(FakeCalendarClient):
        def create_event(self, ics, uid, *, calendar=None):
            self.calls.append(("create_event", ics, uid, calendar))
            raise CalendarConflictError(f"An event with uid {uid} already exists.")

    monkeypatch.setattr(cli, "CalendarClient", ConflictingClient)

    assert cli.main([
        "calendar", "create-series", "--summary", "Quarterly deadline",
        "--date", "2026-03-31T09:00", "--date", "2026-06-30T09:00",
        "--uid-prefix", "quarterly-2026", "--if-missing",
        "--yes", "--json", "--profile", "work",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] == 0
    assert payload["existed"] == 2


def test_cli_calendar_create_series_rejects_duplicate_dates(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create-series", "--summary", "Quarterly deadline",
        "--date", "2026-03-31T09:00", "--date", "2026-03-31T09:00",
        "--uid-prefix", "quarterly-2026", "--yes", "--profile", "work",
    ]) == 1

    assert "must be unique" in capsys.readouterr().err
    assert not any(call[0] == "create_event" for c in clients for call in c.calls)


def test_cli_calendar_create_series_requires_explicit_profile_for_yes(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.delenv("IK_PROFILE", raising=False)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create-series", "--summary", "Quarterly deadline",
        "--date", "2026-03-31T09:00", "--uid-prefix", "quarterly-2026", "--yes",
    ]) == 1

    assert "profile is explicit" in capsys.readouterr().err
    assert not any(call[0] == "create_event" for c in clients for call in c.calls)


def test_cli_calendar_create_uses_a_caller_supplied_uid_verbatim(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create", "--summary", "Team sync", "--start", "2026-07-20T14:00",
        "--uid", "quarterly-compliance-2026q3",
        "--yes", "--json", "--profile", "work",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["uid"] == "quarterly-compliance-2026q3"
    assert payload["uid_explicit"] is True
    assert clients[0].calls[-1][2] == "quarterly-compliance-2026q3"


@pytest.mark.parametrize("bad_uid", ["", "   ", "a/b", "a\\b", "a\nb", "x" * 256])
def test_cli_calendar_create_rejects_an_unsafe_uid_before_writing(
    tmp_path, monkeypatch, capsys, bad_uid
):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create", "--summary", "Team sync", "--start", "2026-07-20T14:00",
        "--uid", bad_uid, "--yes", "--profile", "work",
    ]) == 1

    assert "--uid must" in capsys.readouterr().err
    assert not any(call[0] == "create_event" for c in clients for call in c.calls)


def test_cli_calendar_create_if_missing_requires_a_deterministic_uid(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _make_recording_client(monkeypatch)

    assert cli.main([
        "calendar", "create", "--summary", "Team sync", "--start", "2026-07-20T14:00",
        "--if-missing", "--yes", "--profile", "work",
    ]) == 1

    assert "--if-missing needs a deterministic --uid" in capsys.readouterr().err
    assert not any(call[0] == "create_event" for c in clients for call in c.calls)


def test_cli_calendar_create_if_missing_treats_an_existing_event_as_a_no_op(
    tmp_path, monkeypatch, capsys
):
    _configured_profile(tmp_path, monkeypatch)

    class ConflictingClient(FakeCalendarClient):
        def create_event(self, ics, uid, *, calendar=None):
            self.calls.append(("create_event", ics, uid, calendar))
            raise CalendarConflictError(f"An event with uid {uid} already exists (not overwritten).")

    monkeypatch.setattr(cli, "CalendarClient", ConflictingClient)

    assert cli.main([
        "calendar", "create", "--summary", "Team sync", "--start", "2026-07-20T14:00",
        "--uid", "stable-uid", "--if-missing", "--yes", "--json", "--profile", "work",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] is False
    assert payload["existed"] is True


def test_cli_calendar_create_conflict_without_if_missing_is_still_an_error(
    tmp_path, monkeypatch, capsys
):
    _configured_profile(tmp_path, monkeypatch)

    class ConflictingClient(FakeCalendarClient):
        def create_event(self, ics, uid, *, calendar=None):
            raise CalendarConflictError(f"An event with uid {uid} already exists (not overwritten).")

    monkeypatch.setattr(cli, "CalendarClient", ConflictingClient)

    assert cli.main([
        "calendar", "create", "--summary", "Team sync", "--start", "2026-07-20T14:00",
        "--uid", "stable-uid", "--yes", "--profile", "work",
    ]) == 1

    assert "already exists" in capsys.readouterr().err


def test_cli_calendar_show_existing_event(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "show", "uid-1", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["event_id"] == "uid-1"
    assert output["event"]["summary"] == "Team Sync"


def test_cli_calendar_show_missing_event_is_helpful(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "CalendarClient", FakeCalendarClient)

    assert cli.main(["calendar", "show", "missing", "--json"]) == 1

    captured = capsys.readouterr()
    assert "Calendar event not found: missing" in captured.err


def test_cli_calendar_requires_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["calendar", "list"]) == 1

    captured = capsys.readouterr()
    assert "No calendar configured for profile: work" in captured.err
    assert "auth calendar" in captured.err


def test_calendar_parser_exposes_lifecycle_writes_but_not_rsvp_or_invites():
    parser = cli.build_parser()
    calendar_parser = parser._subparsers._group_actions[0].choices["calendar"]
    choices = calendar_parser._subparsers._group_actions[0].choices

    assert set(choices) == {
        "list", "upcoming", "today", "search", "show", "export",
        "create", "create-series", "update", "cancel", "delete", "repair",
    }
    # 0.2.14 boundary: collaboration and bulk surfaces must not appear yet.
    assert not {"rsvp", "invite", "sync", "import"} & set(choices)


# --- event ICS building / parsing -----------------------------------------


def test_parse_event_input_timed_and_all_day():
    assert parse_event_input("2026-07-20T14:30", all_day=False) == datetime.datetime(2026, 7, 20, 14, 30)
    assert parse_event_input("2026-07-20", all_day=True) == datetime.date(2026, 7, 20)


def test_parse_event_input_rejects_bad_value():
    import pytest

    with pytest.raises(CalendarError):
        parse_event_input("not-a-date", all_day=False)


def test_format_ics_datetime_naive_floating_and_aware_utc():
    naive = datetime.datetime(2026, 7, 20, 14, 30, 0)
    assert format_ics_datetime(naive, all_day=False) == "20260720T143000"
    aware = datetime.datetime(2026, 7, 20, 12, 30, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
    assert format_ics_datetime(aware, all_day=False) == "20260720T103000Z"
    assert format_ics_datetime(datetime.date(2026, 7, 20), all_day=True) == "20260720"


def test_build_event_ics_timed_and_escaping():
    ics = build_event_ics(
        uid="uid-x",
        dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
        summary="Lunch; with, team\nback-to-back",
        start=datetime.datetime(2026, 7, 20, 14, 0),
        end=datetime.datetime(2026, 7, 20, 15, 0),
        location="Café, HQ",
    )
    assert "BEGIN:VEVENT" in ics
    assert "UID:uid-x" in ics
    assert "DTSTAMP:20260701T080000Z" in ics
    assert "DTSTART:20260720T140000" in ics
    assert "DTEND:20260720T150000" in ics
    # text values are RFC 5545 escaped
    assert "SUMMARY:Lunch\\; with\\, team\\nback-to-back" in ics
    assert "LOCATION:Café\\, HQ" in ics
    assert ics.endswith("END:VCALENDAR\r\n")


def test_build_event_ics_emits_no_alarm_without_reminders():
    ics = build_event_ics(
        uid="uid-n",
        dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
        summary="Team sync",
        start=datetime.datetime(2026, 7, 20, 14, 0),
        end=datetime.datetime(2026, 7, 20, 15, 0),
    )
    assert "VALARM" not in ics


def test_build_event_ics_emits_one_valarm_per_reminder_in_order():
    ics = build_event_ics(
        uid="uid-r",
        dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
        summary="Quarterly review",
        start=datetime.datetime(2026, 7, 20, 14, 0),
        end=datetime.datetime(2026, 7, 20, 15, 0),
        reminders=[1440, 30, 0],
    )
    assert ics.count("BEGIN:VALARM") == 3
    assert ics.count("END:VALARM") == 3
    triggers = [line for line in ics.split("\r\n") if line.startswith("TRIGGER:")]
    assert triggers == ["TRIGGER:-PT1440M", "TRIGGER:-PT30M", "TRIGGER:-PT0M"]
    # alarms are nested inside the VEVENT, never after it
    assert ics.index("BEGIN:VALARM") > ics.index("BEGIN:VEVENT")
    assert ics.index("END:VALARM") < ics.index("END:VEVENT")
    assert "ACTION:DISPLAY" in ics
    assert "DESCRIPTION:Quarterly review" in ics


def test_build_event_ics_rejects_negative_and_duplicate_reminders():
    common = dict(
        uid="uid-b",
        dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
        summary="Team sync",
        start=datetime.datetime(2026, 7, 20, 14, 0),
        end=datetime.datetime(2026, 7, 20, 15, 0),
    )
    with pytest.raises(CalendarError, match="zero or greater"):
        build_event_ics(**common, reminders=[-5])
    with pytest.raises(CalendarError, match="duplicate"):
        build_event_ics(**common, reminders=[30, 30])


def test_build_event_ics_escapes_the_alarm_description():
    ics = build_event_ics(
        uid="uid-e",
        dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
        summary="Review; notes, here",
        start=datetime.datetime(2026, 7, 20, 14, 0),
        end=datetime.datetime(2026, 7, 20, 15, 0),
        reminders=[10],
    )
    assert "DESCRIPTION:Review\\; notes\\, here" in ics


def test_build_event_ics_emits_no_rrule_by_default():
    ics = build_event_ics(
        uid="uid-nr",
        dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
        summary="Team sync",
        start=datetime.datetime(2026, 7, 20, 14, 0),
        end=datetime.datetime(2026, 7, 20, 15, 0),
    )
    assert "RRULE" not in ics


def test_build_event_ics_emits_a_normalized_rrule_inside_the_vevent():
    ics = build_event_ics(
        uid="uid-rr",
        dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
        summary="Quarterly deadline",
        start=datetime.datetime(2026, 7, 20, 14, 0),
        end=datetime.datetime(2026, 7, 20, 15, 0),
        rrule="freq=monthly;interval=3;count=4",
    )
    assert "RRULE:FREQ=MONTHLY;INTERVAL=3;COUNT=4" in ics
    assert ics.index("RRULE:") > ics.index("BEGIN:VEVENT")
    assert ics.index("RRULE:") < ics.index("END:VEVENT")


def test_build_event_ics_rrule_is_emitted_before_any_alarm():
    ics = build_event_ics(
        uid="uid-ra",
        dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
        summary="Quarterly deadline",
        start=datetime.datetime(2026, 7, 20, 14, 0),
        end=datetime.datetime(2026, 7, 20, 15, 0),
        rrule="FREQ=WEEKLY",
        reminders=[30],
    )
    assert ics.index("RRULE:") < ics.index("BEGIN:VALARM")


@pytest.mark.parametrize(
    "bad_rule",
    ["", "   ", "INTERVAL=3", "FREQ=MONTHLY\r\nSUMMARY:injected", "FREQ=MONTHLY;BOGUS", "FREQ=NEVER"],
)
def test_build_event_ics_rejects_a_malformed_rrule(bad_rule):
    with pytest.raises(CalendarError):
        build_event_ics(
            uid="uid-bad",
            dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
            summary="Team sync",
            start=datetime.datetime(2026, 7, 20, 14, 0),
            end=datetime.datetime(2026, 7, 20, 15, 0),
            rrule=bad_rule,
        )


def test_build_event_ics_all_day_uses_value_date():
    ics = build_event_ics(
        uid="uid-y",
        dtstamp=datetime.datetime(2026, 7, 1, 8, 0, tzinfo=datetime.UTC),
        summary="Vacation",
        start=datetime.date(2026, 8, 10),
        end=datetime.date(2026, 8, 15),
        all_day=True,
    )
    assert "DTSTART;VALUE=DATE:20260810" in ics
    assert "DTEND;VALUE=DATE:20260815" in ics


def test_create_event_puts_ics_with_if_none_match():
    seen = []

    def opener(request):
        seen.append(request)
        return FakeResponse(b"")

    client = CalendarClient("https://sync.example.test/calendars/user/work/", "user@example.com", "pw", opener=opener)
    result = client.create_event("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", "uid-z")

    assert result["uid"] == "uid-z"
    assert result["url"].endswith("/uid-z.ics")
    request = seen[0]
    assert request.get_method() == "PUT"
    assert request.headers["If-none-match"] == "*"
    assert request.headers["Content-type"].startswith("text/calendar")
    assert request.data == b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"


def test_create_event_conflict_raises():
    import pytest
    import urllib.error

    def opener(request):
        raise urllib.error.HTTPError(request.full_url, 412, "Precondition Failed", {}, None)

    client = CalendarClient("https://sync.example.test/calendars/user/work/", "user@example.com", "pw", opener=opener)
    with pytest.raises(CalendarError) as excinfo:
        client.create_event("ics", "uid-dup")
    assert "already exists" in str(excinfo.value)


EVENTS_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:response><D:href>/calendars/user/work/uid-1.ics</D:href><D:propstat><D:prop>
    <D:getetag>"abc123"</D:getetag>
    <C:calendar-data>BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:uid-1
SUMMARY:Team Sync
DTSTART:20260624T090000Z
DTEND:20260624T100000Z
END:VEVENT
END:VCALENDAR</C:calendar-data>
  </D:prop></D:propstat></D:response>
</D:multistatus>"""


def test_event_report_keeps_resource_url_etag_and_full_ics():
    client = CalendarClient(
        "https://sync.example.test/calendars/user/work/",
        "user@example.com",
        "pw",
        opener=lambda request: FakeResponse(EVENTS_XML),
    )

    event = client.list_events()[0]

    assert event["url"] == "https://sync.example.test/calendars/user/work/uid-1.ics"
    assert event["etag"] == '"abc123"'
    assert event["raw_ics"].startswith("BEGIN:VCALENDAR")


def test_update_and_delete_use_if_match_on_exact_resource():
    seen = []

    def opener(request):
        seen.append(request)
        return FakeResponse(b"")

    client = CalendarClient("https://sync.example.test/calendars/user/work/", "user@example.com", "pw", opener=opener)
    updated = client.update_event(
        "https://sync.example.test/calendars/user/work/uid-1.ics",
        "BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n",
        '"abc123"',
    )
    deleted = client.delete_event(
        "https://sync.example.test/calendars/user/work/uid-1.ics",
        '"new-etag"',
    )

    assert updated["status"] == 204
    assert deleted["status"] == 204
    assert seen[0].get_method() == "PUT"
    assert seen[0].headers["If-match"] == '"abc123"'
    assert seen[1].get_method() == "DELETE"
    assert seen[1].headers["If-match"] == '"new-etag"'


def test_update_event_etag_conflict_is_actionable():
    import pytest
    import urllib.error

    def opener(request):
        raise urllib.error.HTTPError(request.full_url, 412, "Precondition Failed", {}, None)

    client = CalendarClient("https://sync.example.test/calendars/user/work/", "user@example.com", "pw", opener=opener)
    with pytest.raises(CalendarError) as excinfo:
        client.update_event("https://sync.example.test/calendars/user/work/uid-1.ics", "ics", '"old"')
    assert "changed since it was resolved" in str(excinfo.value)


def test_patch_event_ics_preserves_attendees_and_alarm_while_updating_fields():
    original = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:uid-1",
        "DTSTART:20260624T090000Z", "DTEND:20260624T100000Z", "SUMMARY:Old",
        "ATTENDEE;CN=Alice:mailto:alice@example.com", "X-CUSTOM:keep-me",
        "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15M", "DESCRIPTION:Reminder", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", "",
    ])

    changed = patch_event_ics(original, summary="New", location="Office")

    assert "SUMMARY:New" in changed
    assert "LOCATION:Office" in changed
    assert "ATTENDEE;CN=Alice:mailto:alice@example.com" in changed
    assert "X-CUSTOM:keep-me" in changed
    assert "TRIGGER:-PT15M" in changed


def test_patch_event_ics_changes_one_simple_reminder_without_dropping_alarm():
    original = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT", "UID:uid-1",
        "DTSTART:20260624T090000Z", "DTEND:20260624T100000Z", "SUMMARY:Old",
        "BEGIN:VALARM", "ACTION:DISPLAY", "TRIGGER:-PT15M", "DESCRIPTION:Reminder", "END:VALARM",
        "END:VEVENT", "END:VCALENDAR", "",
    ])

    changed = patch_event_ics(original, reminder_minutes=30)

    assert "TRIGGER:-PT30M" in changed
    assert "ACTION:DISPLAY" in changed
    assert "DESCRIPTION:Reminder" in changed


def test_patch_event_ics_refuses_multi_component_recurring_resource():
    import pytest

    original = "\r\n".join([
        "BEGIN:VCALENDAR", "VERSION:2.0",
        "BEGIN:VEVENT", "UID:series-1", "RECURRENCE-ID:20260720T090000Z", "SUMMARY:One", "END:VEVENT",
        "BEGIN:VEVENT", "UID:series-1", "RECURRENCE-ID:20260727T090000Z", "SUMMARY:Two", "END:VEVENT",
        "END:VCALENDAR", "",
    ])

    with pytest.raises(CalendarError) as excinfo:
        patch_event_ics(original, summary="Unsafe broad change")

    assert "multiple VEVENT" in str(excinfo.value)


# --- calendar create CLI (protected write) --------------------------------


def _make_recording_client(monkeypatch):
    created = []

    def make_client(url, username, password):
        client = FakeCalendarClient(url, username, password)
        created.append(client)
        return client

    monkeypatch.setattr(cli, "CalendarClient", make_client)
    return created


def test_cli_calendar_create_dry_run_does_not_create(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)

    rc = cli.main([
        "calendar", "create", "--summary", "Sync", "--start", "2026-08-01T15:00",
        "--dry-run", "--json",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["dry_run"] is True
    assert out["created"] is False
    assert "BEGIN:VCALENDAR" in out["ics"]
    # end defaulted to +1h
    assert out["end"] == "2026-08-01T16:00:00"
    assert not any(c.calls for c in created)


def test_cli_calendar_create_yes_requires_explicit_profile(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    rc = cli.main(["calendar", "create", "--summary", "x", "--start", "2026-08-01T15:00", "--yes"])
    assert rc == 1
    assert "explicit" in capsys.readouterr().err.lower()
    assert not any(call[0] == "create_event" for c in created for call in c.calls)


def test_cli_calendar_create_yes_with_explicit_profile_creates(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)

    rc = cli.main([
        "--profile", "work", "calendar", "create",
        "--summary", "Ship review", "--start", "2026-08-01T15:00", "--end", "2026-08-01T16:30",
        "--yes", "--json",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["created"] is True
    assert out["event"]["status"] == 201
    calls = [call for c in created for call in c.calls if call[0] == "create_event"]
    assert len(calls) == 1
    assert "SUMMARY:Ship review" in calls[0][1]


def test_cli_calendar_create_without_yes_non_interactive_errors(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)

    rc = cli.main(["--profile", "work", "calendar", "create", "--summary", "x", "--start", "2026-08-01T15:00"])
    assert rc == 1
    assert "requires --yes" in capsys.readouterr().err
    assert not any(call[0] == "create_event" for c in created for call in c.calls)


def test_cli_calendar_create_rejects_end_before_start(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _make_recording_client(monkeypatch)

    rc = cli.main([
        "--profile", "work", "calendar", "create", "--summary", "x",
        "--start", "2026-08-01T15:00", "--end", "2026-08-01T14:00", "--yes",
    ])
    assert rc == 1
    assert "must be after" in capsys.readouterr().err


def test_cli_calendar_create_empty_summary_refused(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _make_recording_client(monkeypatch)

    rc = cli.main(["--profile", "work", "calendar", "create", "--summary", "   ", "--start", "2026-08-01T15:00", "--yes"])
    assert rc == 1
    assert "empty --summary" in capsys.readouterr().err


def test_cli_calendar_create_interactive_confirm_creates(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)
    monkeypatch.setattr(cli, "_is_non_interactive", lambda args: False)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    rc = cli.main(["--profile", "work", "calendar", "create", "--summary", "Standup", "--start", "2026-08-01T09:00"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Created event 'Standup'" in out
    assert any(call[0] == "create_event" for c in created for call in c.calls)


def test_cli_calendar_create_interactive_decline_does_not_create(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)
    monkeypatch.setattr(cli, "_is_non_interactive", lambda args: False)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    rc = cli.main(["--profile", "work", "calendar", "create", "--summary", "Standup", "--start", "2026-08-01T09:00"])
    assert rc == 2
    assert "cancelled" in capsys.readouterr().out.lower()
    assert not any(call[0] == "create_event" for c in created for call in c.calls)


# --- calendar lifecycle CLI (protected writes) ----------------------------


def test_cli_calendar_update_dry_run_shows_before_after_and_preserves_alarm(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)

    rc = cli.main([
        "calendar", "update", "uid-2", "--summary", "Invoice approved",
        "--reminder-minutes", "30", "--dry-run", "--json",
    ])

    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "calendar.update"
    assert out["dry_run"] is True
    assert out["updated"] is False
    assert out["before"]["summary"] == "Invoice review"
    assert out["after"]["summary"] == "Invoice approved"
    assert "TRIGGER:-PT30M" in out["ics"]
    assert not any(call[0] == "update_event" for call in created[0].calls)


def test_cli_calendar_update_refuses_attendee_notification_risk(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)

    rc = cli.main([
        "--profile", "work", "calendar", "update", "uid-1", "--summary", "Changed", "--yes"
    ])

    assert rc == 1
    assert "attendee" in capsys.readouterr().err.lower()
    assert not any(call[0] == "update_event" for call in created[0].calls)


def test_cli_calendar_cancel_dry_run_is_soft_and_notification_safe(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _make_recording_client(monkeypatch)

    assert cli.main(["calendar", "cancel", "uid-2", "--dry-run", "--json"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "calendar.cancel"
    assert out["mode"] == "soft-cancel"
    assert out["after"]["status"] == "CANCELLED"
    assert out["cancelled"] is False


def test_cli_calendar_delete_requires_hard_acknowledgement(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _make_recording_client(monkeypatch)

    assert cli.main(["calendar", "delete", "uid-2", "--dry-run", "--json"]) == 1
    assert "--hard" in capsys.readouterr().err


def test_cli_calendar_delete_dry_run_is_explicit_hard_delete(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)

    assert cli.main(["calendar", "delete", "uid-2", "--hard", "--dry-run", "--json"]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["action"] == "calendar.delete"
    assert out["mode"] == "hard-delete"
    assert out["deleted"] is False
    assert out["before"]["uid"] == "uid-2"
    assert not any(call[0] == "delete_event" for call in created[0].calls)


def test_cli_calendar_update_yes_requires_explicit_profile(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    assert cli.main(["calendar", "update", "uid-2", "--summary", "Changed", "--yes"]) == 1

    assert "explicit" in capsys.readouterr().err.lower()
    assert not any(call[0] == "update_event" for call in created[0].calls)


def test_cli_calendar_update_yes_writes_and_reads_back(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created = _make_recording_client(monkeypatch)

    assert cli.main([
        "--profile", "work", "calendar", "update", "uid-2", "--summary", "Changed", "--yes", "--json"
    ]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["updated"] is True
    assert out["readback"]["summary"] == "Changed"
    call = next(call for call in created[0].calls if call[0] == "update_event")
    assert call[1].endswith("/uid-2.ics")
    assert call[3] == '"etag-2"'


def test_cli_calendar_cancel_yes_writes_status_and_reads_back(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _make_recording_client(monkeypatch)

    assert cli.main([
        "--profile", "work", "calendar", "cancel", "uid-2", "--yes", "--json"
    ]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["cancelled"] is True
    assert out["readback"]["status"] == "CANCELLED"


def test_cli_calendar_hard_delete_yes_writes_and_confirms_absence(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _make_recording_client(monkeypatch)

    assert cli.main([
        "--profile", "work", "calendar", "delete", "uid-2", "--hard", "--yes", "--json"
    ]) == 0

    out = json.loads(capsys.readouterr().out)
    assert out["deleted"] is True
    assert out["readback_deleted"] is True
