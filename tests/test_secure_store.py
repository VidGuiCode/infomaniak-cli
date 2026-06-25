import getpass
import os
import stat
import sys

import pytest

from infomaniak_cli import secure_store
from infomaniak_cli.auth import TokenStore
from infomaniak_cli.secure_store import (
    DIR_MODE,
    FILE_MODE,
    harden_windows_command,
    secure_dir,
    secure_write,
)

posix_only = pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="POSIX file modes do not map onto Windows ACLs",
)


@posix_only
def test_secure_write_sets_owner_only_file_mode(tmp_path):
    target = tmp_path / "tokens" / "work.token"
    secure_dir(target.parent)
    secure_write(target, "secret-token-value")

    assert target.read_text(encoding="utf-8") == "secret-token-value"
    assert stat.S_IMODE(os.stat(target).st_mode) == FILE_MODE


@posix_only
def test_secure_dir_sets_owner_only_dir_mode(tmp_path):
    target = tmp_path / "tokens"
    secure_dir(target)

    assert stat.S_IMODE(os.stat(target).st_mode) == DIR_MODE


@posix_only
def test_token_store_save_hardens_file_and_dir(tmp_path):
    TokenStore(config_dir=tmp_path).save_token("work", "secret-token-value")

    token_path = tmp_path / "tokens" / "work.token"
    assert stat.S_IMODE(os.stat(token_path).st_mode) == FILE_MODE
    assert stat.S_IMODE(os.stat(token_path.parent).st_mode) == DIR_MODE


def test_harden_windows_command_builds_owner_only_icacls_argv(tmp_path):
    target = tmp_path / "tokens" / "work.token"

    assert harden_windows_command(target) == [
        "icacls",
        str(target),
        "/inheritance:r",
        "/grant:r",
        f"{getpass.getuser()}:F",
    ]


def test_windows_hardening_failure_is_non_fatal_and_keeps_secret(tmp_path, monkeypatch):
    # Force the Windows branch on any platform and simulate icacls being absent.
    monkeypatch.setattr(secure_store, "_is_windows", lambda: True)
    target = tmp_path / "tokens" / "work.token"
    target.parent.mkdir(parents=True, exist_ok=True)
    warnings = []

    def boom(command):
        raise FileNotFoundError("icacls not found")

    secure_write(target, "secret-token-value", runner=boom, warn=warnings.append)

    assert target.read_text(encoding="utf-8") == "secret-token-value"
    assert warnings and "icacls" in warnings[0]


def test_windows_hardening_nonzero_return_is_non_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(secure_store, "_is_windows", lambda: True)
    target = tmp_path / "tokens" / "work.token"
    target.parent.mkdir(parents=True, exist_ok=True)
    warnings = []
    seen = []

    class Result:
        returncode = 1

    def runner(command):
        seen.append(command)
        return Result()

    secure_write(target, "secret-token-value", runner=runner, warn=warnings.append)

    assert seen == [harden_windows_command(target)]
    assert target.read_text(encoding="utf-8") == "secret-token-value"
    assert warnings and "icacls exited with 1" in warnings[0]


def test_posix_chmod_failure_is_non_fatal_and_keeps_secret(tmp_path, monkeypatch):
    # A hardening failure must never lose the secret, on any platform.
    monkeypatch.setattr(secure_store, "_is_windows", lambda: False)
    monkeypatch.setattr(
        secure_store.os,
        "chmod",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("read-only fs")),
    )
    target = tmp_path / "tokens" / "work.token"
    target.parent.mkdir(parents=True, exist_ok=True)
    warnings = []

    secure_write(target, "secret-token-value", warn=warnings.append)

    assert target.read_text(encoding="utf-8") == "secret-token-value"
    assert warnings and "could not restrict permissions" in warnings[0]


def test_token_store_round_trips_after_hardening_failure(tmp_path, monkeypatch):
    # Even when hardening fails, the store's save -> load must still work.
    monkeypatch.setattr(secure_store, "_is_windows", lambda: True)
    monkeypatch.setattr(
        secure_store,
        "_default_runner",
        lambda command: (_ for _ in ()).throw(FileNotFoundError("icacls not found")),
    )
    monkeypatch.setattr(secure_store, "_default_warn", lambda message: None)
    store = TokenStore(config_dir=tmp_path)

    store.save_token("work", "secret-token-value")

    assert store.load_token("work") == "secret-token-value"
