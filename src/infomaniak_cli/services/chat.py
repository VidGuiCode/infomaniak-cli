from __future__ import annotations

import json
import re
from dataclasses import dataclass
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable, Mapping

from ..api import redact_secret


class ChatError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class KSuiteKChatUrl:
    original_url: str
    account_id: str
    workspace_slug: str
    channel_slug: str | None = None


class ChatClient:
    """Small read-only Mattermost-compatible client for kChat discovery."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        opener: Callable[..., Any] | None = None,
        auth_source: str = "explicit_chat_token",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.auth_source = auth_source
        self._opener = opener or urllib.request.urlopen

    def list_teams(self) -> list[Mapping[str, Any]]:
        payload = self._get("/api/v4/users/me/teams")
        return _items(payload, "teams")

    def list_channels(self, team_id: str, *, limit: int | None = None) -> list[Mapping[str, Any]]:
        channels = _items(self._get(f"/api/v4/teams/{urllib.parse.quote(str(team_id), safe='')}/channels"), "channels")
        if limit is not None:
            return channels[:limit]
        return channels

    def list_users(self, team_id: str, *, limit: int | None = None) -> list[Mapping[str, Any]]:
        users = _items(self._get("/api/v4/users", params={"in_team": team_id}), "users")
        if limit is not None:
            return users[:limit]
        return users

    def _get(self, path: str, *, params: Mapping[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
            method="GET",
        )
        try:
            with self._opener(request, timeout=30) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code in (401, 403):
                if self.auth_source == "main_token_fallback":
                    raise ChatError(
                        "kChat rejected the main Informaniak API token. "
                        "Run ik auth chat --url <url> --stdin to save a dedicated kChat token."
                    ) from exc
                raise ChatError(
                    f"kChat request failed: authentication failed or insufficient scope (HTTP {exc.code})"
                ) from exc
            raise ChatError(f"kChat request failed: HTTP {exc.code}: {redact_secret(body, secrets=[self.token])}") from exc
        except urllib.error.URLError as exc:
            raise ChatError(
                f"kChat request failed: {redact_secret(str(exc.reason), secrets=[self.token])}"
            ) from exc
        except OSError as exc:
            raise ChatError(f"kChat request failed: {redact_secret(str(exc), secrets=[self.token])}") from exc

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ChatError("Unexpected kChat response: invalid JSON") from exc


def is_trusted_infomaniak_kchat_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url.strip())
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and host.endswith(".kchat.infomaniak.com") and host != "kchat.infomaniak.com"


def parse_ksuite_kchat_url(url: str) -> KSuiteKChatUrl | None:
    clean_url = url.strip()
    parsed = urllib.parse.urlparse(clean_url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or host != "ksuite.infomaniak.com":
        return None

    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 3 or parts[1] != "kchat":
        return None

    account_id = parts[0]
    workspace_slug = parts[2]
    if not account_id.isdigit() or not _is_safe_kchat_slug(workspace_slug):
        return None

    channel_slug = None
    if len(parts) >= 5 and parts[3] == "channels" and _is_safe_kchat_slug(parts[4]):
        channel_slug = parts[4]

    return KSuiteKChatUrl(
        original_url=clean_url,
        account_id=account_id,
        workspace_slug=workspace_slug,
        channel_slug=channel_slug,
    )


def derive_kchat_api_base_candidates(url: str) -> list[str]:
    clean_url = url.strip()
    if is_trusted_infomaniak_kchat_url(clean_url):
        parsed = urllib.parse.urlparse(clean_url)
        host = (parsed.hostname or "").lower().rstrip(".")
        return [f"https://{host}"]

    parsed_ksuite_url = parse_ksuite_kchat_url(clean_url)
    if parsed_ksuite_url:
        return [f"https://{parsed_ksuite_url.workspace_slug}.kchat.infomaniak.com"]

    return []


def slim_team(team: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string_or_none(team.get("id")),
        "name": _string_or_none(team.get("name")),
        "display_name": _string_or_none(team.get("display_name")),
        "description": _string_or_none(team.get("description")),
    }


def slim_teams(teams: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_team(team) for team in teams]


def slim_channel(channel: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string_or_none(channel.get("id")),
        "team_id": _string_or_none(channel.get("team_id")),
        "name": _string_or_none(channel.get("name")),
        "display_name": _string_or_none(channel.get("display_name")),
        "type": _string_or_none(channel.get("type")),
        "purpose": _string_or_none(channel.get("purpose")),
        "header": _string_or_none(channel.get("header")),
    }


def slim_channels(channels: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_channel(channel) for channel in channels]


def slim_user(user: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _string_or_none(user.get("id")),
        "username": _string_or_none(user.get("username")),
        "nickname": _string_or_none(user.get("nickname")),
        "first_name": _string_or_none(user.get("first_name")),
        "last_name": _string_or_none(user.get("last_name")),
        "email": _string_or_none(user.get("email")),
    }


def slim_users(users: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_user(user) for user in users]


def _items(payload: Any, label: str) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    raise ChatError(f"Unexpected kChat {label} response: expected JSON list")


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _is_safe_kchat_slug(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", value))
