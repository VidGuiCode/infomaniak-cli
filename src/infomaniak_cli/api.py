from __future__ import annotations

import json as json_module
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_BEARER_RE = re.compile(r"Bearer\s+[^\s]+", re.IGNORECASE)
DEFAULT_BASE_URL = "https://api.infomaniak.com"


def redact_secret(message: str) -> str:
    """Redact credential-like strings from an error/log message."""
    return _BEARER_RE.sub("Bearer ***", message)


class InformaniakAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str) -> None:
        self.status_code = status_code
        super().__init__(redact_secret(message))


@dataclass(slots=True)
class TransportResponse:
    status_code: int
    text: str
    headers: Mapping[str, str] | None = None


class Transport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> TransportResponse:
        ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> TransportResponse:
        if params:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}{urlencode(params, doseq=True)}"

        body = None
        if json is not None:
            body = json_module.dumps(json).encode("utf-8")

        request = Request(url=url, data=body, headers=dict(headers), method=method)
        try:
            with urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8")
                return TransportResponse(
                    status_code=response.status,
                    text=text,
                    headers=dict(response.headers.items()),
                )
        except HTTPError as exc:
            text = exc.read().decode("utf-8", errors="replace")
            return TransportResponse(
                status_code=exc.code,
                text=text,
                headers=dict(exc.headers.items()),
            )
        except URLError as exc:
            raise InformaniakAPIError(0, f"Network error while calling {url}: {exc}") from exc


class InformaniakAPIClient:
    def __init__(
        self,
        token: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: Transport | None = None,
    ) -> None:
        if not token or not token.strip():
            raise ValueError("API token is required")
        self.token = token.strip()
        self.base_url = base_url.rstrip("/")
        self.transport = transport or UrllibTransport()

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Any | None = None) -> Any:
        return self.request("POST", path, json=json)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        method = method.upper()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        if json is not None:
            headers["Content-Type"] = "application/json"

        url = self._url(path)
        response = self.transport.request(method, url, headers=headers, params=params, json=json)
        payload = self._parse_json(method, path, response)

        if response.status_code >= 400:
            message = self._error_message(payload) if isinstance(payload, dict) else str(payload)
            raise InformaniakAPIError(response.status_code, f"{method} {path} failed: {message}")

        if isinstance(payload, dict) and payload.get("result") == "error":
            raise InformaniakAPIError(response.status_code, f"{method} {path} failed: {self._error_message(payload)}")

        return payload

    def _url(self, path: str) -> str:
        clean_path = path.strip()
        if clean_path.startswith("http://") or clean_path.startswith("https://"):
            return clean_path
        return f"{self.base_url}/{clean_path.lstrip('/')}"

    @staticmethod
    def _parse_json(method: str, path: str, response: TransportResponse) -> Any:
        try:
            return json_module.loads(response.text)
        except json_module.JSONDecodeError as exc:
            raise InformaniakAPIError(
                response.status_code,
                f"Invalid JSON response from {method} {path}: {response.text[:200]}",
            ) from exc

    @staticmethod
    def _error_message(payload: Mapping[str, Any]) -> str:
        error = payload.get("error")
        if isinstance(error, Mapping):
            for key in ("message", "description", "code"):
                value = error.get(key)
                if value:
                    return str(value)
            return json_module.dumps(dict(error), sort_keys=True)
        if error:
            return str(error)
        if payload.get("message"):
            return str(payload["message"])
        return json_module.dumps(dict(payload), sort_keys=True)
