from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config_paths import get_config_dir, get_profiles_dir


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class Profile:
    name: str
    informaniak_user: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    ksuite_id: str | None = None
    mail_hosting_id: str | None = None
    default_mailbox: str | None = None
    imap_host: str | None = None
    imap_port: int | None = None
    default_drive_id: str | None = None
    default_drive_name: str | None = None
    contacts_url: str | None = None
    contacts_username: str | None = None
    calendar_url: str | None = None
    calendar_username: str | None = None
    kchat_url: str | None = None
    kchat_ksuite_url: str | None = None
    kchat_ksuite_account_id: str | None = None
    kchat_workspace_slug: str | None = None
    kchat_default_channel_slug: str | None = None
    kchat_team_id: str | None = None
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        allowed = {field.name for field in fields(cls)}
        filtered = {key: value for key, value in data.items() if key in allowed}
        return cls(**filtered)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProfileManager:
    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or get_config_dir()
        self.profiles_dir = get_profiles_dir(self.config_dir)
        self.config_file = self.config_dir / "config.json"

    def create_or_update(self, name: str, make_default: bool = False, **metadata: Any) -> Profile:
        if not name or not name.strip():
            raise ValueError("Profile name is required")

        existing = self.get(name) if self.exists(name) else None
        now = utc_now_iso()
        data = existing.to_dict() if existing else {"name": name, "created_at": now}
        data.update({key: value for key, value in metadata.items() if value is not None})
        data["updated_at"] = now
        profile = Profile.from_dict(data)
        self.save(profile)

        if make_default or not self.get_current_name():
            self.set_current(name)

        return profile

    def replace_metadata(self, name: str, make_default: bool = False, **metadata: Any) -> Profile:
        if not name or not name.strip():
            raise ValueError("Profile name is required")

        existing = self.get(name) if self.exists(name) else None
        now = utc_now_iso()
        data = existing.to_dict() if existing else {"name": name, "created_at": now}
        data.update(metadata)
        data["updated_at"] = now
        profile = Profile.from_dict(data)
        self.save(profile)

        if make_default or not self.get_current_name():
            self.set_current(name)

        return profile

    def exists(self, name: str) -> bool:
        return self._profile_path(name).exists()

    def save(self, profile: Profile) -> None:
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        self._profile_path(profile.name).write_text(
            json.dumps(profile.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get(self, name: str) -> Profile:
        path = self._profile_path(name)
        if not path.exists():
            raise KeyError(f"Profile not found: {name}")
        return Profile.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def get_current(self) -> Profile:
        current = self.get_current_name()
        if not current:
            raise KeyError("No current profile configured")
        return self.get(current)

    def get_current_name(self) -> str | None:
        if not self.config_file.exists():
            return None
        data = json.loads(self.config_file.read_text(encoding="utf-8"))
        return data.get("current_profile")

    def set_current(self, name: str) -> None:
        if not self.exists(name):
            raise KeyError(f"Profile not found: {name}")
        self._write_current(name)

    def clear_current(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            json.dumps({}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def rename(self, old: str, new: str) -> Profile:
        old_path = self._profile_path(old)
        new_path = self._profile_path(new)
        if not old_path.exists():
            raise KeyError(f"Profile not found: {old}")
        if new_path.exists():
            raise ValueError(f"Profile already exists: {new}")

        profile = self.get(old)
        data = profile.to_dict()
        data["name"] = new.strip()
        data["updated_at"] = utc_now_iso()
        renamed = Profile.from_dict(data)
        self.save(renamed)
        old_path.unlink()

        if self.get_current_name() == old.strip():
            self._write_current(renamed.name)

        return renamed

    def delete(self, name: str) -> Profile:
        path = self._profile_path(name)
        if not path.exists():
            raise KeyError(f"Profile not found: {name}")
        profile = self.get(name)
        path.unlink()

        if self.get_current_name() == name.strip():
            remaining = self.list_names()
            if remaining:
                self._write_current(remaining[0])
            else:
                self.clear_current()

        return profile

    def _write_current(self, name: str) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            json.dumps({"current_profile": name}, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def list_names(self) -> list[str]:
        if not self.profiles_dir.exists():
            return []
        return sorted(path.stem for path in self.profiles_dir.glob("*.json"))

    def _profile_path(self, name: str) -> Path:
        safe_name = name.strip()
        if not safe_name or any(part in safe_name for part in ("/", "\\", "..")):
            raise ValueError(f"Invalid profile name: {name!r}")
        return self.profiles_dir / f"{safe_name}.json"
