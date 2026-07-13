from __future__ import annotations

import logging
from pathlib import Path

import keyring
from keyring.errors import KeyringError

from .config_paths import get_config_dir, get_tokens_dir
from .secure_store import secure_dir, secure_write

logger = logging.getLogger(__name__)

SERVICE_NAME = "infomaniak-cli"


def _redact(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


class BaseStore:
    def __init__(self, service_suffix: str, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or get_config_dir()
        self.tokens_dir = get_tokens_dir(self.config_dir)
        self.service_suffix = service_suffix

    def _key(self, profile: str) -> str:
        safe_profile = profile.strip()
        if not safe_profile or any(part in safe_profile for part in ("/", "\\", "..")):
            raise ValueError(f"Invalid profile name: {profile!r}")
        return f"{safe_profile}.{self.service_suffix}"

    def _path(self, profile: str) -> Path:
        return self.tokens_dir / self._key(profile)

    def save(self, profile: str, secret: str) -> None:
        clean = secret.strip()
        if not clean:
            raise ValueError("Secret is required")
        key = self._key(profile)
        
        # Try OS keyring first
        try:
            keyring.set_password(SERVICE_NAME, key, clean)
            # Cleanup legacy plain-text file if keyring succeeded
            self._path(profile).unlink(missing_ok=True)
            return
        except KeyringError as exc:
            logger.debug("Keyring failed during save, falling back to file: %s", exc)
            
        # Fallback to restricted plain-text file
        secure_dir(self.tokens_dir)
        secure_write(self._path(profile), clean)

    def load(self, profile: str) -> str:
        key = self._key(profile)
        
        # Try OS keyring first
        try:
            val = keyring.get_password(SERVICE_NAME, key)
            if val is not None:
                return val
        except KeyringError as exc:
            logger.debug("Keyring failed during load, falling back to file: %s", exc)
            
        # Fallback to file
        path = self._path(profile)
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
        return ""

    def has(self, profile: str) -> bool:
        return bool(self.load(profile))

    def redacted(self, profile: str) -> str | None:
        val = self.load(profile)
        if not val:
            return None
        return _redact(val)

    def delete(self, profile: str) -> None:
        key = self._key(profile)
        try:
            if keyring.get_password(SERVICE_NAME, key) is not None:
                keyring.delete_password(SERVICE_NAME, key)
        except KeyringError as exc:
            logger.debug("Keyring failed during delete: %s", exc)
            
        self._path(profile).unlink(missing_ok=True)

    def rename_profile(self, old: str, new: str) -> None:
        # Check if old exists at all
        old_val = self.load(old)
        if not old_val:
            return
            
        # Check if new already exists
        if self.has(new):
            raise ValueError(f"Secret already exists for profile: {new}")
            
        # Perform rename (save to new, delete old)
        self.save(new, old_val)
        self.delete(old)

    def delete_profile(self, profile: str) -> None:
        self.delete(profile)


class TokenStore(BaseStore):
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__("token", config_dir)

    def save_token(self, profile: str, token: str) -> None:
        self.save(profile, token)

    def load_token(self, profile: str) -> str:
        return self.load(profile)

    def has_token(self, profile: str) -> bool:
        return self.has(profile)

    def redacted_token(self, profile: str) -> str | None:
        return self.redacted(profile)

    def delete_token(self, profile: str) -> None:
        self.delete(profile)


class MailPasswordStore(BaseStore):
    """Stores mailbox app-specific passwords separately from REST API tokens."""
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__("mail", config_dir)

    def save_password(self, profile: str, password: str) -> None:
        self.save(profile, password)

    def load_password(self, profile: str) -> str:
        return self.load(profile)

    def has_password(self, profile: str) -> bool:
        return self.has(profile)

    def redacted_password(self, profile: str) -> str | None:
        return self.redacted(profile)

    def delete_password(self, profile: str) -> None:
        self.delete(profile)


class ContactsPasswordStore(BaseStore):
    """Stores CardDAV contacts passwords separately from REST API and mail credentials."""
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__("contacts", config_dir)

    def save_password(self, profile: str, password: str) -> None:
        self.save(profile, password)

    def load_password(self, profile: str) -> str:
        return self.load(profile)

    def has_password(self, profile: str) -> bool:
        return self.has(profile)

    def redacted_password(self, profile: str) -> str | None:
        return self.redacted(profile)

    def delete_password(self, profile: str) -> None:
        self.delete(profile)


class CalendarPasswordStore(BaseStore):
    """Stores CalDAV calendar passwords separately from other profile credentials."""
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__("calendar", config_dir)

    def save_password(self, profile: str, password: str) -> None:
        self.save(profile, password)

    def load_password(self, profile: str) -> str:
        return self.load(profile)

    def has_password(self, profile: str) -> bool:
        return self.has(profile)

    def redacted_password(self, profile: str) -> str | None:
        return self.redacted(profile)

    def delete_password(self, profile: str) -> None:
        self.delete(profile)


class ChatTokenStore(BaseStore):
    """Stores kChat/Mattermost tokens separately from other profile credentials."""
    def __init__(self, config_dir: Path | None = None) -> None:
        super().__init__("chat", config_dir)

    def save_token(self, profile: str, token: str) -> None:
        self.save(profile, token)

    def load_token(self, profile: str) -> str:
        return self.load(profile)

    def has_token(self, profile: str) -> bool:
        return self.has(profile)

    def redacted_token(self, profile: str) -> str | None:
        return self.redacted(profile)

    def delete_token(self, profile: str) -> None:
        self.delete(profile)
