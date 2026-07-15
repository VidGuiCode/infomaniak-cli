from __future__ import annotations

import base64
import datetime
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import PurePosixPath
from typing import Any, Callable, Mapping

from ..api import redact_secret
from .dav_discovery import DavDiscoveryError, probe_collection


class CalendarError(ValueError):
    pass


class _MethodRequest(urllib.request.Request):
    def __init__(self, *args: Any, method: str = "GET", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._method = method

    def get_method(self) -> str:
        return self._method


class CalendarClient:
    """Small read-only CalDAV client for a configured calendar collection URL."""

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

    def list_calendars(self) -> list[dict[str, Any]]:
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<D:propfind xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav" '
            'xmlns:CS="http://calendarserver.org/ns/">'
            "<D:prop><D:displayname/><C:calendar-description/><CS:calendar-color/></D:prop>"
            "</D:propfind>"
        ).encode("utf-8")
        payload = self._request(self.url, method="PROPFIND", body=body, depth="0")
        return _parse_calendar_multistatus(payload, default_url=self.url)

    def list_events(
        self,
        *,
        calendar: str | None = None,
        start: datetime.datetime | None = None,
        end: datetime.datetime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        calendar_url = self._calendar_url(calendar)
        time_range = ""
        if start is not None and end is not None:
            time_range = f'<C:time-range start="{_caldav_time(start)}" end="{_caldav_time(end)}"/>'
        body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
            "<D:prop><D:getetag/><C:calendar-data/></D:prop>"
            "<C:filter><C:comp-filter name=\"VCALENDAR\"><C:comp-filter name=\"VEVENT\">"
            f"{time_range}"
            "</C:comp-filter></C:comp-filter></C:filter>"
            "</C:calendar-query>"
        ).encode("utf-8")
        payload = self._request(calendar_url, method="REPORT", body=body, depth="1")
        events = _parse_event_multistatus(
            payload,
            calendar_id=_calendar_id(calendar_url),
            default_url=calendar_url,
        )
        if not events:
            self._verify_collection_when_empty(calendar_url)
        if limit is not None:
            return events[:limit]
        return events

    def _verify_collection_when_empty(self, calendar_url: str) -> None:
        """Distinguish an empty calendar from a URL that is not one.

        A CalDAV REPORT against a non-calendar URL (e.g. the bare sync base
        saved when discovery found nothing) returns an empty multistatus
        instead of an error, which silently looks like "0 events"
        (confirmed live against sync.infomaniak.com, see
        context/LIVE_API_FINDINGS.md). An empty time window on a real
        calendar collection stays a normal empty result.
        """
        try:
            probe = probe_collection(calendar_url, self.username, self.password, opener=self._opener)
        except DavDiscoveryError as exc:
            raise CalendarError(
                f"Calendar collection check failed for {calendar_url}: {exc}. "
                "Run `ik auth calendar` to re-run auto-discovery, or pass --url <collection-url>."
            ) from exc
        if not probe["is_calendar"]:
            raise CalendarError(
                f"The configured calendar URL is not a CalDAV calendar: {calendar_url}. "
                "Run `ik auth calendar` to re-run auto-discovery, or pass --url <collection-url>. "
                "If discovery finds no calendar, the Infomaniak Calendar service may not be "
                "activated for this user yet - open the Calendar web app once, then retry."
            )

    def create_event(self, ics: str, uid: str, *, calendar: str | None = None) -> dict[str, Any]:
        """Create a calendar event by PUTting an iCalendar resource (CalDAV).

        Writes to ``{collection}/{uid}.ics`` with ``If-None-Match: *`` so an
        existing event with the same uid is never overwritten. The server side
        is a create-only write; callers handle preview/confirmation first.
        """
        collection = self._calendar_url(calendar).rstrip("/")
        event_url = f"{collection}/{urllib.parse.quote(uid, safe='')}.ics"
        request = _MethodRequest(
            event_url,
            data=ics.encode("utf-8"),
            method="PUT",
            headers={
                "Authorization": _basic_auth(self.username, self.password),
                "Content-Type": "text/calendar; charset=utf-8",
                "If-None-Match": "*",
            },
        )
        try:
            with self._opener(request) as response:
                status = getattr(response, "status", None) or getattr(response, "code", 201)
        except urllib.error.HTTPError as exc:
            if exc.code == 412:
                raise CalendarError(
                    f"An event with uid {uid} already exists at {event_url} (not overwritten)."
                ) from exc
            raise CalendarError(f"Calendar event creation failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise CalendarError(
                f"Calendar event creation failed: {redact_secret(str(exc.reason))}"
            ) from exc
        except OSError as exc:
            raise CalendarError(f"Calendar event creation failed: {redact_secret(str(exc))}") from exc
        return {"uid": uid, "url": event_url, "status": status}

    def update_event(self, event_url: str, ics: str, etag: str) -> dict[str, Any]:
        """Replace one exact CalDAV resource only if its ETag still matches."""
        if not event_url or not etag:
            raise CalendarError("Calendar update requires an exact event URL and ETag.")
        request = _MethodRequest(
            event_url,
            data=ics.encode("utf-8"),
            method="PUT",
            headers={
                "Authorization": _basic_auth(self.username, self.password),
                "Content-Type": "text/calendar; charset=utf-8",
                "If-Match": etag,
            },
        )
        return self._event_write(request, action="update")

    def delete_event(self, event_url: str, etag: str) -> dict[str, Any]:
        """Hard-delete one exact CalDAV resource only if its ETag still matches."""
        if not event_url or not etag:
            raise CalendarError("Calendar delete requires an exact event URL and ETag.")
        request = _MethodRequest(
            event_url,
            method="DELETE",
            headers={
                "Authorization": _basic_auth(self.username, self.password),
                "If-Match": etag,
            },
        )
        return self._event_write(request, action="delete")

    def _event_write(self, request: urllib.request.Request, *, action: str) -> dict[str, Any]:
        try:
            with self._opener(request) as response:
                status = getattr(response, "status", None) or getattr(response, "code", 204)
                headers = getattr(response, "headers", None)
                etag = headers.get("ETag") if headers is not None else None
        except urllib.error.HTTPError as exc:
            if exc.code == 412:
                raise CalendarError(
                    f"Calendar event changed since it was resolved; {action} was not applied (ETag mismatch)."
                ) from exc
            raise CalendarError(f"Calendar event {action} failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise CalendarError(
                f"Calendar event {action} failed: {redact_secret(str(exc.reason))}"
            ) from exc
        except OSError as exc:
            raise CalendarError(
                f"Calendar event {action} failed: {redact_secret(str(exc))}"
            ) from exc
        return {"url": request.full_url, "etag": etag, "status": status}

    def _calendar_url(self, calendar: str | None) -> str:
        if not calendar:
            return self.url
        if calendar.startswith(("http://", "https://")):
            return calendar
        for item in self.list_calendars():
            if calendar in {str(item.get("id")), str(item.get("name")), str(item.get("url"))}:
                return str(item["url"])
        return calendar

    def _request(self, url: str, *, method: str, body: bytes, depth: str) -> bytes:
        request = _MethodRequest(
            url,
            data=body,
            method=method,
            headers={
                "Authorization": _basic_auth(self.username, self.password),
                "Content-Type": "application/xml; charset=utf-8",
                "Depth": depth,
            },
        )
        try:
            with self._opener(request) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise CalendarError(f"Calendar CalDAV request failed: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise CalendarError(f"Calendar CalDAV request failed: {redact_secret(str(exc.reason))}") from exc
        except OSError as exc:
            raise CalendarError(f"Calendar CalDAV request failed: {redact_secret(str(exc))}") from exc


def slim_calendar(calendar: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string_or_none(calendar.get("id")),
        "name": _string_or_none(calendar.get("name")),
        "url": _string_or_none(calendar.get("url")),
        "color": _string_or_none(calendar.get("color")),
        "description": _string_or_none(calendar.get("description")),
    }


def slim_calendars(calendars: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_calendar(calendar) for calendar in calendars]


def slim_event(event: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string_or_none(event.get("id")),
        "uid": _string_or_none(event.get("uid")),
        "calendar_id": _string_or_none(event.get("calendar_id")),
        "summary": _string_or_none(event.get("summary")),
        "description": _string_or_none(event.get("description")),
        "location": _string_or_none(event.get("location")),
        "starts_at": _string_or_none(event.get("starts_at")),
        "ends_at": _string_or_none(event.get("ends_at")),
        "all_day": bool(event.get("all_day")),
        "status": _string_or_none(event.get("status")),
        "organizer": _string_or_none(event.get("organizer")),
        "attendees": _string_list(event.get("attendees")),
    }


def slim_events(events: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_event(event) for event in events]


def search_events(
    events: list[Mapping[str, Any]],
    query: str,
    *,
    limit: int | None = None,
) -> list[Mapping[str, Any]]:
    query_lower = query.casefold()
    matches = [event for event in events if query_lower in _event_search_text(event)]
    if limit is not None:
        return matches[:limit]
    return matches


def find_event(events: list[Mapping[str, Any]], event_id: str) -> Mapping[str, Any] | None:
    for event in events:
        if str(event.get("id")) == str(event_id) or str(event.get("uid")) == str(event_id):
            return event
    return None


def parse_event_input(value: str, *, all_day: bool) -> datetime.date:
    """Parse a user-supplied event date/time.

    ``all_day`` expects an ISO date (``YYYY-MM-DD``); otherwise an ISO 8601
    datetime (``YYYY-MM-DDTHH:MM`` optionally with seconds and a ``Z``/offset).
    A naive datetime is treated as floating local time; an aware one is
    normalized to UTC when formatted.
    """
    text = value.strip()
    try:
        if all_day:
            return datetime.date.fromisoformat(text[:10])
        return datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        kind = "date (YYYY-MM-DD)" if all_day else "datetime (e.g. 2026-07-20T14:00)"
        raise CalendarError(f"Invalid {kind}: {value!r}") from exc


def format_ics_datetime(value: datetime.date, *, all_day: bool) -> str:
    if all_day:
        day = value.date() if isinstance(value, datetime.datetime) else value
        return day.strftime("%Y%m%d")
    if not isinstance(value, datetime.datetime):
        raise CalendarError("A timed event requires a datetime value.")
    if value.tzinfo is None:
        return value.strftime("%Y%m%dT%H%M%S")
    return value.astimezone(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def build_event_ics(
    *,
    uid: str,
    dtstamp: datetime.datetime,
    summary: str,
    start: datetime.date,
    end: datetime.date,
    all_day: bool = False,
    description: str | None = None,
    location: str | None = None,
) -> str:
    """Build a minimal RFC 5545 VEVENT calendar object (no attendees/invites)."""
    value_date = ";VALUE=DATE" if all_day else ""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//infomaniak-cli//EN",
        "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{format_ics_datetime(dtstamp, all_day=False)}",
        f"DTSTART{value_date}:{format_ics_datetime(start, all_day=all_day)}",
        f"DTEND{value_date}:{format_ics_datetime(end, all_day=all_day)}",
        f"SUMMARY:{_escape_ics_text(summary)}",
    ]
    if location:
        lines.append(f"LOCATION:{_escape_ics_text(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape_ics_text(description)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def patch_event_ics(
    ics: str,
    *,
    summary: str | None = None,
    start: datetime.date | None = None,
    end: datetime.date | None = None,
    all_day: bool = False,
    location: str | None = None,
    description: str | None = None,
    clear_location: bool = False,
    clear_description: bool = False,
    status: str | None = None,
    reminder_minutes: int | None = None,
    dtstamp: datetime.datetime | None = None,
) -> str:
    """Patch modeled VEVENT properties while preserving every unmodeled line.

    Nested components such as VALARM are retained byte-for-byte except for the
    narrowly supported reminder edit: exactly one existing alarm with exactly
    one relative TRIGGER. Multiple/complex alarms are rejected rather than
    flattened or lost.
    """
    lines = _unfold_ics_lines(ics)
    event_count = sum(line.upper() == "BEGIN:VEVENT" for line in lines)
    if event_count == 0:
        raise CalendarError("Calendar event is missing a VEVENT body.")
    if event_count != 1:
        raise CalendarError(
            "Refusing to change a calendar resource with multiple VEVENT components; "
            "recurrence-instance targeting is not implemented safely yet."
        )

    replacements: dict[str, str | None] = {}
    if summary is not None:
        replacements["SUMMARY"] = f"SUMMARY:{_escape_ics_text(summary)}"
    if start is not None:
        suffix = ";VALUE=DATE" if all_day else ""
        replacements["DTSTART"] = f"DTSTART{suffix}:{format_ics_datetime(start, all_day=all_day)}"
    if end is not None:
        suffix = ";VALUE=DATE" if all_day else ""
        replacements["DTEND"] = f"DTEND{suffix}:{format_ics_datetime(end, all_day=all_day)}"
    if location is not None or clear_location:
        replacements["LOCATION"] = None if clear_location else f"LOCATION:{_escape_ics_text(location or '')}"
    if description is not None or clear_description:
        replacements["DESCRIPTION"] = None if clear_description else f"DESCRIPTION:{_escape_ics_text(description or '')}"
    if status is not None:
        replacements["STATUS"] = f"STATUS:{status.upper()}"
    if dtstamp is not None:
        replacements["DTSTAMP"] = f"DTSTAMP:{format_ics_datetime(dtstamp, all_day=False)}"

    output: list[str] = []
    seen: set[str] = set()
    in_event = False
    nested_depth = 0
    trigger_indexes: list[int] = []
    alarm_count = 0
    for line in lines:
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            in_event = True
            output.append(line)
            continue
        if in_event and upper.startswith("BEGIN:"):
            nested_depth += 1
            if upper == "BEGIN:VALARM":
                alarm_count += 1
            output.append(line)
            continue
        if in_event and upper.startswith("END:") and upper != "END:VEVENT":
            output.append(line)
            nested_depth = max(0, nested_depth - 1)
            continue
        if in_event and upper == "END:VEVENT":
            for name, replacement in replacements.items():
                if name not in seen and replacement is not None:
                    output.append(replacement)
            output.append(line)
            in_event = False
            continue

        name = line.split(":", 1)[0].split(";", 1)[0].upper() if ":" in line else ""
        if in_event and nested_depth == 0 and name in replacements:
            if name not in seen and replacements[name] is not None:
                output.append(replacements[name] or "")
            seen.add(name)
            continue
        if in_event and nested_depth > 0 and name == "TRIGGER":
            trigger_indexes.append(len(output))
        output.append(line)

    if reminder_minutes is not None:
        if reminder_minutes < 0:
            raise CalendarError("--reminder-minutes must be zero or greater.")
        if alarm_count != 1 or len(trigger_indexes) != 1:
            raise CalendarError(
                "Reminder changes require exactly one existing simple alarm so other alarms are preserved safely."
            )
        output[trigger_indexes[0]] = f"TRIGGER:-PT{reminder_minutes}M"

    return "\r\n".join(output) + "\r\n"


def _escape_ics_text(value: str) -> str:
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def parse_ics_events(ics: str, *, calendar_id: str | None = None, fallback_id: str | None = None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current: list[str] | None = None
    for line in _unfold_ics_lines(ics):
        if line.upper() == "BEGIN:VEVENT":
            current = [line]
            continue
        if current is not None:
            current.append(line)
            if line.upper() == "END:VEVENT":
                events.append(_parse_vevent(current, calendar_id=calendar_id, fallback_id=fallback_id))
                current = None
    return events


def _parse_calendar_multistatus(payload: bytes, *, default_url: str) -> list[dict[str, Any]]:
    root = _xml_root(payload)
    calendars: list[dict[str, Any]] = []
    for response in root.findall(".//{DAV:}response"):
        href = response.findtext("{DAV:}href")
        url = _absolute_or_default(href, default_url)
        name = response.findtext(".//{DAV:}displayname")
        description = response.findtext(".//{urn:ietf:params:xml:ns:caldav}calendar-description")
        color = (
            response.findtext(".//{http://calendarserver.org/ns/}calendar-color")
            or response.findtext(".//{http://apple.com/ns/ical/}calendar-color")
        )
        calendars.append(
            {
                "id": _calendar_id(url),
                "name": name or _calendar_id(url),
                "url": url,
                "color": color,
                "description": description,
            }
        )
    if not calendars:
        calendars.append({"id": _calendar_id(default_url), "name": _calendar_id(default_url), "url": default_url, "color": None, "description": None})
    return calendars


def _parse_event_multistatus(
    payload: bytes,
    *,
    calendar_id: str | None,
    default_url: str,
) -> list[dict[str, Any]]:
    root = _xml_root(payload)
    events: list[dict[str, Any]] = []
    for response in root.findall(".//{DAV:}response"):
        href = response.findtext("{DAV:}href")
        etag = response.findtext(".//{DAV:}getetag")
        calendar_data = response.findtext(".//{urn:ietf:params:xml:ns:caldav}calendar-data")
        if not calendar_data:
            continue
        parsed = parse_ics_events(calendar_data, calendar_id=calendar_id, fallback_id=_id_from_href(href))
        for event in parsed:
            event["url"] = urllib.parse.urljoin(default_url, href or "")
            event["etag"] = etag
            event["raw_ics"] = calendar_data
        events.extend(parsed)
    return events


def _parse_vevent(lines: list[str], *, calendar_id: str | None, fallback_id: str | None) -> dict[str, Any]:
    event: dict[str, Any] = {
        "id": fallback_id,
        "uid": None,
        "calendar_id": calendar_id,
        "summary": None,
        "description": None,
        "location": None,
        "starts_at": None,
        "ends_at": None,
        "all_day": False,
        "status": None,
        "organizer": None,
        "attendees": [],
        "raw_ics": "\n".join(lines),
    }
    for line in lines:
        if line.upper() in {"BEGIN:VEVENT", "END:VEVENT"} or ":" not in line:
            continue
        left, value = line.split(":", 1)
        name = left.split(";", 1)[0].upper()
        params = left[len(name):]
        value = _unescape_ics_value(value)
        if name == "UID":
            event["uid"] = value
            event["id"] = value
        elif name == "SUMMARY":
            event["summary"] = value
        elif name == "DESCRIPTION":
            event["description"] = value
        elif name == "LOCATION":
            event["location"] = value
        elif name == "DTSTART":
            event["starts_at"] = _parse_ics_datetime(value, params=params)
            event["all_day"] = "VALUE=DATE" in params.upper() or _is_date_value(value)
        elif name == "DTEND":
            event["ends_at"] = _parse_ics_datetime(value, params=params)
        elif name == "STATUS":
            event["status"] = value
        elif name == "ORGANIZER":
            event["organizer"] = _clean_mailto(value)
        elif name == "ATTENDEE":
            event["attendees"].append(_clean_mailto(value))
    if not event["id"]:
        event["id"] = event["uid"] or event["summary"]
    return event


def _xml_root(payload: bytes) -> ET.Element:
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise CalendarError("Unexpected Calendar CalDAV response: invalid XML") from exc


def _basic_auth(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _caldav_time(value: datetime.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.UTC)
    return value.astimezone(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")


def _parse_ics_datetime(value: str, *, params: str) -> str | None:
    if not value:
        return None
    if "VALUE=DATE" in params.upper() or _is_date_value(value):
        return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
    if value.endswith("Z"):
        parsed = datetime.datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.UTC)
        return parsed.isoformat().replace("+00:00", "Z")
    parsed = datetime.datetime.strptime(value, "%Y%m%dT%H%M%S")
    return parsed.isoformat()


def _is_date_value(value: str) -> bool:
    return len(value) == 8 and value.isdigit()


def _calendar_id(url: str | None) -> str | None:
    if not url:
        return None
    stripped = url.rstrip("/")
    name = PurePosixPath(stripped).name
    return name or stripped


def _id_from_href(href: str | None) -> str | None:
    if not href:
        return None
    name = PurePosixPath(href).name
    if name.endswith(".ics"):
        return name[:-4]
    return name or None


def _absolute_or_default(href: str | None, default_url: str) -> str:
    if not href:
        return default_url
    if href.startswith(("http://", "https://")):
        return href
    if default_url.endswith(href):
        return default_url
    return default_url


def _unfold_ics_lines(ics: str) -> list[str]:
    lines: list[str] = []
    for raw_line in ics.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not raw_line:
            continue
        if raw_line.startswith((" ", "\t")) and lines:
            lines[-1] += raw_line[1:]
        else:
            lines.append(raw_line)
    return lines


def _unescape_ics_value(value: str) -> str:
    return (
        value.replace(r"\n", "\n")
        .replace(r"\N", "\n")
        .replace(r"\;", ";")
        .replace(r"\,", ",")
        .replace(r"\\", "\\")
    )


def _clean_mailto(value: str) -> str:
    if value.casefold().startswith("mailto:"):
        return value[7:]
    return value


def _event_search_text(event: Mapping[str, Any]) -> str:
    values = [
        event.get("summary"),
        event.get("description"),
        event.get("location"),
        event.get("organizer"),
        *_string_list(event.get("attendees")),
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
