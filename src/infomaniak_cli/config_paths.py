from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "infomaniak-cli"


def get_config_dir() -> Path:
    """Return the directory used for infomaniak-cli configuration.

    `IK_CONFIG_DIR` is intentionally supported so tests, Hermes, and future
    automation can run against isolated configuration stores.
    """
    override = os.environ.get("IK_CONFIG_DIR")
    if override:
        return Path(override).expanduser()

    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / APP_NAME

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / APP_NAME

    return Path.home() / ".config" / APP_NAME


def get_profiles_dir(config_dir: Path | None = None) -> Path:
    return (config_dir or get_config_dir()) / "profiles"


def get_tokens_dir(config_dir: Path | None = None) -> Path:
    return (config_dir or get_config_dir()) / "tokens"
