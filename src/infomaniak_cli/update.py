from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


LATEST_RELEASE_URL = "https://api.github.com/repos/VidGuiCode/infomaniak-cli/releases/latest"


class UpdateCheckError(RuntimeError):
    pass


@dataclass(slots=True)
class ReleaseInfo:
    tag: str
    version: str
    release_url: str
    wheel_url: str | None


@dataclass(slots=True)
class UpdatePlan:
    current_version: str
    latest_version: str
    update_available: bool
    release_url: str
    wheel_url: str | None
    install_method: str
    can_auto_update: bool
    command: list[str] | None
    instructions: list[str] | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "release_url": self.release_url,
            "wheel_url": self.wheel_url,
            "install_method": self.install_method,
            "can_auto_update": self.can_auto_update,
            "command": self.command,
        }


def fetch_latest_release(fetch: Any = None) -> ReleaseInfo:
    fetch = fetch or urlopen
    try:
        with fetch(LATEST_RELEASE_URL, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise UpdateCheckError(f"GitHub latest release request failed: HTTP {exc.code}") from exc
    except URLError as exc:
        raise UpdateCheckError(f"GitHub latest release request failed: {exc.reason}") from exc
    except OSError as exc:
        raise UpdateCheckError(f"GitHub latest release request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise UpdateCheckError("GitHub latest release response was not valid JSON") from exc
    return parse_latest_release(payload)


def parse_latest_release(payload: Mapping[str, Any]) -> ReleaseInfo:
    tag = str(payload.get("tag_name") or payload.get("name") or "").strip()
    version = normalize_version(tag)
    if not version:
        raise UpdateCheckError("GitHub latest release response did not include a release tag")
    release_url = str(payload.get("html_url") or "").strip()
    if not release_url:
        release_url = f"https://github.com/VidGuiCode/infomaniak-cli/releases/tag/{tag}"
    return ReleaseInfo(
        tag=tag,
        version=version,
        release_url=release_url,
        wheel_url=_find_wheel_url(payload.get("assets"), version),
    )


def normalize_version(version: str) -> str:
    value = str(version).strip()
    if value.startswith(("v", "V")):
        value = value[1:]
    return value


def is_newer_version(current: str, latest: str) -> bool:
    return _version_tuple(latest) > _version_tuple(current)


def detect_install_method(
    *,
    executable: str | Path | None = None,
    prefix: str | Path | None = None,
    base_prefix: str | Path | None = None,
    module_file: str | Path | None = None,
) -> str:
    executable_path = Path(executable or sys.executable)
    prefix_path = Path(prefix or sys.prefix)
    base_prefix_path = Path(base_prefix or getattr(sys, "base_prefix", sys.prefix))
    module_path = Path(module_file or __file__).resolve()

    if _has_git_parent(module_path):
        return "source"

    haystack = " ".join(str(path).lower() for path in (executable_path, prefix_path, module_path))
    normalized = haystack.replace("\\", "/")
    if "pipx" in normalized and "/venvs/" in normalized:
        return "pipx"
    if "/uv/tools/" in normalized or "/uv\\tools/" in normalized:
        return "uv_tool"
    if prefix_path != base_prefix_path:
        return "pip"
    return "unknown"


def build_update_plan(current_version: str, release: ReleaseInfo, *, install_method: str | None = None) -> UpdatePlan:
    method = install_method or detect_install_method()
    update_available = is_newer_version(current_version, release.version)
    command: list[str] | None = None
    instructions: list[str] | None = None
    can_auto_update = False

    if update_available and release.wheel_url:
        if method == "pipx":
            command = ["pipx", "runpip", "infomaniak-cli", "install", "--force-reinstall", release.wheel_url]
            can_auto_update = True
        elif method == "uv_tool":
            command = ["uv", "tool", "install", "--force", release.wheel_url]
            can_auto_update = True
        elif method == "pip":
            command = [sys.executable, "-m", "pip", "install", "--force-reinstall", release.wheel_url]
            can_auto_update = True
        elif method == "unknown":
            command = ["pipx", "install", "--force", "--backend", "pip", release.wheel_url]
        elif method == "source":
            instructions = ["git pull", "uv sync"]
    elif update_available and method == "source":
        instructions = ["git pull", "uv sync"]

    return UpdatePlan(
        current_version=normalize_version(current_version),
        latest_version=release.version,
        update_available=update_available,
        release_url=release.release_url,
        wheel_url=release.wheel_url,
        install_method=method,
        can_auto_update=can_auto_update,
        command=command,
        instructions=instructions,
    )


def run_update_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def update_failure_hint(command: list[str], stderr: str) -> str | None:
    if not command:
        return None
    lowered = stderr.lower()
    head = command[0]

    if head == "pipx":
        if "virtual environment already exists" in lowered or "uv venv" in lowered:
            return (
                "pipx failed while trying to create an existing venv through its uv backend. "
                "Manual recovery: pipx runpip infomaniak-cli install --force-reinstall <wheel_url>"
            )
        return None

    if head == "uv":
        if any(token in lowered for token in ("permission denied", "in use", "being used", "os error 5", "access is denied")):
            return (
                "uv tool install could not replace the running executable, often because `ik` is still open. "
                "Close any running `ik` process and retry: uv tool install --force <wheel_url>"
            )
        return None

    # pip invoked as `<python> -m pip install ...`
    if "-m" in command and "pip" in command:
        if any(token in lowered for token in ("access is denied", "permission denied", "being used by another process", "winerror 5")):
            return (
                "pip could not overwrite the installed files, often because `ik` is running or the install needs user scope. "
                "Close any running `ik` and retry, or install for your user: "
                "python -m pip install --user --force-reinstall <wheel_url>"
            )
        return None

    return None


def _find_wheel_url(assets: Any, version: str) -> str | None:
    if not isinstance(assets, list):
        return None
    preferred_name = f"infomaniak_cli-{version}-py3-none-any.whl"
    wheel_assets = [asset for asset in assets if isinstance(asset, Mapping) and str(asset.get("name", "")).endswith(".whl")]
    for asset in wheel_assets:
        if asset.get("name") == preferred_name and asset.get("browser_download_url"):
            return str(asset["browser_download_url"])
    for asset in wheel_assets:
        name = str(asset.get("name", ""))
        if name.startswith("infomaniak_cli-") and name.endswith("-py3-none-any.whl") and asset.get("browser_download_url"):
            return str(asset["browser_download_url"])
    return None


def _version_tuple(version: str) -> tuple[int, ...]:
    normalized = normalize_version(version)
    parts = []
    for part in normalized.split("."):
        digits = ""
        for char in part:
            if not char.isdigit():
                break
            digits += char
        parts.append(int(digits or "0"))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _has_git_parent(path: Path) -> bool:
    for parent in (path, *path.parents):
        if (parent / ".git").exists():
            return True
    return False
