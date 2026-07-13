import datetime
import json

from infomaniak_cli import cli
from infomaniak_cli.auth import CalendarPasswordStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.calendar import (
    CalendarClient,
    CalendarError,
    build_event_ics,
    find_event,
    format_ics_datetime,
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
        "raw_ics": "BEGIN:VEVENT",
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
    },
]


class FakeCalendarClient:
    def __init__(self, url, username, password):
        self.url = url
        self.username = username
        self.password = password
        self.calls = []

    def list_calendars(self):
        self.calls.append(("list_calendars",))
        return CALENDARS

    def list_events(self, *, calendar=None, start=None, end=None, limit=None):
        self.calls.append(("list_events", calendar, start, end, limit))
        events = EVENTS
        if limit is not None:
            return events[:limit]
        return events

    def create_event(self, ics, uid, *, calendar=None):
        self.calls.append(("create_event", ics, uid, calendar))
        return {"uid": uid, "url": f"{self.url}{uid}.ics", "status": 201}


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


def test_calendar_parser_exposes_only_create_as_write_command():
    parser = cli.build_parser()
    calendar_parser = parser._subparsers._group_actions[0].choices["calendar"]
    choices = calendar_parser._subparsers._group_actions[0].choices

    # `create` is the single protected write added in 0.2.5; nothing destructive.
    assert set(choices) == {"list", "upcoming", "today", "search", "show", "create"}
    assert not {"update", "delete", "rsvp", "invite", "sync"} & set(choices)


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
