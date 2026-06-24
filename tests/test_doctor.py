import json
import os

from infomaniak_cli import cli
from infomaniak_cli.doctor import run_doctor
from infomaniak_cli.profiles import ProfileManager


POSIX_SCRIPTS = "/home/you/.local/bin"


def _path(*dirs):
    # Join with the host PATH separator so membership checks are OS-robust.
    return os.pathsep.join(dirs)


def test_run_doctor_reports_install_method_and_off_path_fix_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    data = run_doctor(
        "work",
        which=lambda name: None,  # ik not found on PATH
        path_env=_path("/usr/bin", "/bin"),
        os_name="posix",
        scripts_dir=POSIX_SCRIPTS,
        install_method="pip",
    )

    assert data["install_method"] == "pip"
    path = data["path"]
    assert path["scripts_dir"] == POSIX_SCRIPTS
    assert path["ik_path"] is None
    assert path["on_path"] is False
    assert path["fix_hint"] == f'echo \'export PATH="{POSIX_SCRIPTS}:$PATH"\' >> ~/.bashrc'
    # Existing checks remain intact (additive only).
    assert "config_dir" in data["checks"]
    assert data["checks"]["profile_configured"] is True


def test_run_doctor_on_path_has_no_fix_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))

    data = run_doctor(
        None,
        which=lambda name: f"{POSIX_SCRIPTS}/ik",
        path_env=_path("/usr/bin", POSIX_SCRIPTS),
        os_name="posix",
        scripts_dir=POSIX_SCRIPTS,
        install_method="uv_tool",
    )

    assert data["path"]["on_path"] is True
    assert data["path"]["fix_hint"] is None
    assert data["install_method"] == "uv_tool"


def _doctor_data(*, on_path, fix_hint=None):
    return {
        "profile": "work",
        "profiles": ["work"],
        "checks": {"config_dir": "/cfg", "profiles_found": 1, "token_configured": False},
        "install_method": "pip",
        "path": {
            "scripts_dir": POSIX_SCRIPTS,
            "ik_path": f"{POSIX_SCRIPTS}/ik" if on_path else None,
            "ik_dir": POSIX_SCRIPTS if on_path else None,
            "on_path": on_path,
            "dir_on_path": on_path,
            "fix_hint": fix_hint,
        },
        "profile_data": None,
        "readiness": None,
        "missing_setup_actions": [],
    }


def test_cmd_doctor_human_prints_warning_and_fix_when_not_on_path(monkeypatch, capsys):
    hint = f'echo \'export PATH="{POSIX_SCRIPTS}:$PATH"\' >> ~/.bashrc'
    monkeypatch.setattr(cli, "run_doctor", lambda *a, **k: _doctor_data(on_path=False, fix_hint=hint))

    assert cli.main(["doctor"]) == 0

    out = capsys.readouterr().out
    assert "Install method: pip" in out
    assert "⚠ ik is installed but not on PATH" in out
    assert hint in out


def test_cmd_doctor_human_prints_check_when_on_path(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_doctor", lambda *a, **k: _doctor_data(on_path=True))

    assert cli.main(["doctor"]) == 0

    out = capsys.readouterr().out
    assert "✓ ik on PATH:" in out
    assert "not on PATH" not in out


def test_cmd_doctor_json_includes_install_method_and_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["doctor", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert "install_method" in output
    assert "path" in output
    assert {"scripts_dir", "ik_path", "on_path", "fix_hint"}.issubset(output["path"].keys())
    # Existing checks contract preserved.
    assert "profile_configured" in output["checks"]


def test_cmd_doctor_fix_path_preview_when_not_on_path(monkeypatch, capsys):
    # OS-agnostic: do not patch os.name (pathlib derives PosixPath/WindowsPath from it).
    monkeypatch.setattr(cli, "run_doctor", lambda *a, **k: _doctor_data(on_path=False))
    monkeypatch.setenv("PATH", _path("/usr/bin", "/bin"))

    assert cli.main(["doctor", "--fix-path"]) == 0

    out = capsys.readouterr().out
    assert "Preview:" in out
    assert POSIX_SCRIPTS in out
    assert "Run:" in out
    assert "apply is deferred" in out


def test_cmd_doctor_fix_path_noop_when_already_on_path(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_doctor", lambda *a, **k: _doctor_data(on_path=True))
    monkeypatch.setenv("PATH", _path("/usr/bin", POSIX_SCRIPTS))

    assert cli.main(["doctor", "--fix-path"]) == 0

    out = capsys.readouterr().out
    assert "already on PATH" in out
    assert "Preview:" not in out
