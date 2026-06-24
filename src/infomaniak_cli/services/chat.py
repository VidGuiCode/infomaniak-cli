from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
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

    def search_posts(
        self,
        team_id: str,
        terms: str,
        *,
        is_or_search: bool = False,
        limit: int | None = None,
    ) -> list[Mapping[str, Any]]:
        payload = self._post(
            f"/api/v4/teams/{urllib.parse.quote(str(team_id), safe='')}/posts/search",
            {"terms": terms, "is_or_search": bool(is_or_search)},
        )
        return _ordered_posts(payload, limit=limit)

    def get_thread(self, post_id: str) -> list[Mapping[str, Any]]:
        payload = self._get(f"/api/v4/posts/{urllib.parse.quote(str(post_id), safe='')}/thread")
        return _ordered_posts(payload)

    def get_channel_by_name(self, team_id: str, channel_name: str) -> Mapping[str, Any]:
        payload = self._get(
            f"/api/v4/teams/{urllib.parse.quote(str(team_id), safe='')}"
            f"/channels/name/{urllib.parse.quote(str(channel_name), safe='')}",
            not_found=f"kChat channel not found: {channel_name}",
        )
        if not isinstance(payload, Mapping):
            raise ChatError("Unexpected kChat channel response: expected a JSON object")
        return payload

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    def _get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        not_found: str | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        return self._send(request, not_found=not_found)

    def _post(self, path: str, body: Mapping[str, Any]) -> Any:
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        return self._send(request)

    def _send(self, request: urllib.request.Request, *, not_found: str | None = None) -> Any:
        try:
            with self._opener(request, timeout=30) as response:
                text = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            if exc.code == 404 and not_found is not None:
                raise ChatError(not_found) from exc
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


def slim_post(post: Mapping[str, Any]) -> dict[str, Any]:
    create_at = post.get("create_at")
    return {
        "id": _string_or_none(post.get("id")),
        "channel_id": _string_or_none(post.get("channel_id")),
        "user_id": _string_or_none(post.get("user_id")),
        "message": _string_or_none(post.get("message")),
        "type": _string_or_none(post.get("type")),
        "create_at": create_at if _is_real_number(create_at) else None,
        "created_at": _iso_from_millis(create_at),
    }


def slim_posts(posts: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [slim_post(post) for post in posts]


def _items(payload: Any, label: str) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]
    raise ChatError(f"Unexpected kChat {label} response: expected JSON list")


def _ordered_posts(payload: Any, *, limit: int | None = None) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        raise ChatError("Unexpected kChat posts response: expected a post list object")
    order = payload.get("order")
    posts = payload.get("posts")
    if not isinstance(order, list) or not isinstance(posts, Mapping):
        raise ChatError("Unexpected kChat posts response: missing order/posts")
    ordered: list[Mapping[str, Any]] = []
    for post_id in order:
        post = posts.get(post_id)
        if isinstance(post, Mapping):
            ordered.append(post)
    if limit is not None:
        return ordered[:limit]
    return ordered


def _is_real_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _iso_from_millis(value: Any) -> str | None:
    if not _is_real_number(value):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _is_safe_kchat_slug(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}", value))
