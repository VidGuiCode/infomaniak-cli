from __future__ import annotations

from pathlib import Path

from .config_paths import get_config_dir, get_tokens_dir


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


class TokenStore:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or get_config_dir()
        self.tokens_dir = get_tokens_dir(self.config_dir)

    def save_token(self, profile: str, token: str) -> None:
        if not token:
            raise ValueError("Token is required")
        self.tokens_dir.mkdir(parents=True, exist_ok=True)
        self._token_path(profile).write_text(token, encoding="utf-8")

    def load_token(self, profile: str) -> str:
        return self._token_path(profile).read_text(encoding="utf-8").strip()

    def has_token(self, profile: str) -> bool:
        path = self._token_path(profile)
        return path.exists() and bool(path.read_text(encoding="utf-8").strip())

    def redacted_token(self, profile: str) -> str | None:
        if not self.has_token(profile):
            return None
        return _redact(self.load_token(profile))

    def delete_token(self, profile: str) -> None:
        self._token_path(profile).unlink(missing_ok=True)

    def _token_path(self, profile: str) -> Path:
        safe_profile = profile.strip()
        if not safe_profile or any(part in safe_profile for part in ("/", "\\", "..")):
            raise ValueError(f"Invalid profile name: {profile!r}")
        return self.tokens_dir / f"{safe_profile}.token"
