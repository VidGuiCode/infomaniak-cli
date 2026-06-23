import datetime
import json

from infomaniak_cli import cli
from infomaniak_cli.auth import CalendarPasswordStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.calendar import (
    CalendarClient,
    find_event,
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


def test_calendar_parser_exposes_no_write_commands():
    parser = cli.build_parser()
    calendar_parser = parser._subparsers._group_actions[0].choices["calendar"]
    choices = calendar_parser._subparsers._group_actions[0].choices

    assert set(choices) == {"list", "upcoming", "today", "search", "show"}
    assert not {"create", "update", "delete", "rsvp", "invite", "sync"} & set(choices)
