from __future__ import annotations

import json as json_module
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_BEARER_RE = re.compile(r"Bearer\s+[^\s\"',;}]+", re.IGNORECASE)
_SECRET_FIELD_RE = re.compile(
    r"\b(access[_-]?token|refresh[_-]?token|token|api[_-]?key|password|cookie)"
    r"(\s*[:=]\s*[\"']?)([^\"'\s,;}]+)",
    re.IGNORECASE,
)
DEFAULT_BASE_URL = "https://api.infomaniak.com"


def redact_secret(message: str, *, secrets: Iterable[str] = ()) -> str:
    """Redact credential-like strings from an error/log message."""
    redacted = _BEARER_RE.sub("Bearer ***", str(message))
    redacted = _SECRET_FIELD_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", redacted)
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "***")
    return redacted


class InformaniakAPIError(RuntimeError):
    def __init__(self, status_code: int, message: str, *, secrets: Iterable[str] = ()) -> None:
        self.status_code = status_code
        super().__init__(redact_secret(message, secrets=secrets))


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

    def get_raw(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params, validate_envelope=False)

    def probe_get(self, path: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }
        try:
            response = self.transport.request("GET", self._url(path), headers=headers, params=params, json=None)
        except InformaniakAPIError as exc:
            return {"status_code": exc.status_code, "json": None, "error": str(exc)}

        try:
            payload = json_module.loads(response.text)
        except json_module.JSONDecodeError:
            return {"status_code": response.status_code, "json": None, "error": "non-json response"}
        return {"status_code": response.status_code, "json": payload}

    def post(self, path: str, json: Any | None = None) -> Any:
        return self.request("POST", path, json=json)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any | None = None,
        validate_envelope: bool = True,
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
        try:
            payload = self._parse_json(method, path, response)
        except InformaniakAPIError as exc:
            if response.status_code in (401, 403):
                raise InformaniakAPIError(
                    response.status_code,
                    f"{method} {path} failed: authentication failed or insufficient scope ({exc})",
                    secrets=[self.token],
                ) from exc
            raise

        if response.status_code >= 400:
            message = self._error_message(payload) if isinstance(payload, dict) else str(payload)
            if response.status_code in (401, 403):
                message = f"authentication failed or insufficient scope ({message})"
            raise InformaniakAPIError(
                response.status_code,
                f"{method} {path} failed: {message}",
                secrets=[self.token],
            )

        if isinstance(payload, dict) and payload.get("result") == "error":
            raise InformaniakAPIError(
                response.status_code,
                f"{method} {path} failed: {self._error_message(payload)}",
                secrets=[self.token],
            )

        if validate_envelope:
            self._validate_success_envelope(method, path, response.status_code, payload)

        return payload

    def _url(self, path: str) -> str:
        clean_path = path.strip()
        if clean_path.startswith("http://") or clean_path.startswith("https://"):
            return clean_path
        return f"{self.base_url}/{clean_path.lstrip('/')}"

    def _parse_json(self, method: str, path: str, response: TransportResponse) -> Any:
        try:
            return json_module.loads(response.text)
        except json_module.JSONDecodeError as exc:
            raise InformaniakAPIError(
                response.status_code,
                f"Invalid JSON response from {method} {path}: {response.text[:200]}",
                secrets=[self.token],
            ) from exc

    def _validate_success_envelope(self, method: str, path: str, status_code: int, payload: Any) -> None:
        if not isinstance(payload, Mapping):
            raise InformaniakAPIError(
                status_code,
                f"Unexpected API response envelope from {method} {path}: expected JSON object with result=success",
                secrets=[self.token],
            )

        result = payload.get("result")
        if result == "success":
            if "data" not in payload:
                raise InformaniakAPIError(
                    status_code,
                    f"Unexpected API response envelope from {method} {path}: missing data field",
                    secrets=[self.token],
                )
            return

        preview = self._payload_preview(payload)
        if "result" not in payload:
            raise InformaniakAPIError(
                status_code,
                f"Unexpected API response envelope from {method} {path}: missing result field: {preview}",
                secrets=[self.token],
            )

        raise InformaniakAPIError(
            status_code,
            f"Unexpected API response envelope from {method} {path}: expected result=success, got {result!r}: {preview}",
            secrets=[self.token],
        )

    @staticmethod
    def _payload_preview(payload: Mapping[str, Any]) -> str:
        try:
            return json_module.dumps(dict(payload), sort_keys=True)[:200]
        except TypeError:
            return str(payload)[:200]

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
