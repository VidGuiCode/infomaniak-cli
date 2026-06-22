import io
import json
import subprocess
import sys
from pathlib import Path

from infomaniak_cli import cli
from infomaniak_cli.update import (
    UpdateCheckError,
    build_update_plan,
    detect_install_method,
    is_newer_version,
    parse_latest_release,
)


def _release_payload(version="0.1.3", *, assets=None):
    tag = f"v{version}"
    if assets is None:
        assets = [
            {
                "name": f"infomaniak_cli-{version}-py3-none-any.whl",
                "browser_download_url": (
                    f"https://github.com/VidGuiCode/infomaniak-cli/releases/download/{tag}/"
                    f"infomaniak_cli-{version}-py3-none-any.whl"
                ),
            },
            {"name": f"infomaniak-cli-{version}.tar.gz", "browser_download_url": "https://example.test/sdist"},
        ]
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/VidGuiCode/infomaniak-cli/releases/tag/{tag}",
        "assets": assets,
    }


def test_latest_release_parsing_finds_wheel_url():
    release = parse_latest_release(_release_payload("0.1.3"))

    assert release.version == "0.1.3"
    assert release.tag == "v0.1.3"
    assert release.release_url.endswith("/v0.1.3")
    assert release.wheel_url.endswith("infomaniak_cli-0.1.3-py3-none-any.whl")


def test_version_comparison_same_version_has_no_update():
    assert is_newer_version("0.1.2", "0.1.2") is False
    assert is_newer_version("0.1.2", "v0.1.2") is False


def test_version_comparison_newer_patch_has_update():
    assert is_newer_version("0.1.2", "0.1.3") is True


def test_version_comparison_newer_minor_has_update():
    assert is_newer_version("0.1.9", "0.2.0") is True


def test_version_comparison_normalizes_v_prefix():
    assert is_newer_version("v0.1.2", "0.1.3") is True
    assert is_newer_version("0.1.2", "v0.1.3") is True


def test_pipx_detection():
    method = detect_install_method(
        executable=Path(r"C:\Users\gui\.local\pipx\venvs\infomaniak-cli\Scripts\python.exe"),
        prefix=Path(r"C:\Users\gui\.local\pipx\venvs\infomaniak-cli"),
        base_prefix=Path(r"C:\Python311"),
        module_file=Path(r"C:\Users\gui\.local\pipx\venvs\infomaniak-cli\Lib\site-packages\infomaniak_cli\update.py"),
    )

    assert method == "pipx"


def test_uv_tool_detection():
    method = detect_install_method(
        executable=Path(r"C:\Users\gui\AppData\Roaming\uv\tools\infomaniak-cli\Scripts\python.exe"),
        prefix=Path(r"C:\Users\gui\AppData\Roaming\uv\tools\infomaniak-cli"),
        base_prefix=Path(r"C:\Python311"),
        module_file=Path(r"C:\Users\gui\AppData\Roaming\uv\tools\infomaniak-cli\Lib\site-packages\infomaniak_cli\update.py"),
    )

    assert method == "uv_tool"


def test_pip_detection():
    method = detect_install_method(
        executable=Path(r"C:\project\.venv\Scripts\python.exe"),
        prefix=Path(r"C:\project\.venv"),
        base_prefix=Path(r"C:\Python311"),
        module_file=Path(r"C:\project\.venv\Lib\site-packages\infomaniak_cli\update.py"),
    )

    assert method == "pip"


def test_source_checkout_detection(tmp_path):
    repo = tmp_path / "infomaniak-cli"
    module_file = repo / "src" / "infomaniak_cli" / "update.py"
    (repo / ".git").mkdir(parents=True)
    module_file.parent.mkdir(parents=True)
    module_file.write_text("", encoding="utf-8")

    method = detect_install_method(
        executable=Path(sys.executable),
        prefix=Path(sys.prefix),
        base_prefix=Path(sys.base_prefix),
        module_file=module_file,
    )

    assert method == "source"


def test_build_update_plan_for_unknown_prints_safe_fallback_command():
    release = parse_latest_release(_release_payload("0.1.3"))

    plan = build_update_plan("0.1.2", release, install_method="unknown")

    assert plan.update_available is True
    assert plan.install_method == "unknown"
    assert plan.can_auto_update is False
    assert plan.command == ["pipx", "install", "--force", release.wheel_url]


def test_build_update_plan_for_source_does_not_auto_update():
    release = parse_latest_release(_release_payload("0.1.3"))

    plan = build_update_plan("0.1.2", release, install_method="source")

    assert plan.can_auto_update is False
    assert plan.command is None
    assert plan.instructions == ["git pull", "uv sync"]


def test_missing_wheel_asset_has_clean_plan():
    release = parse_latest_release(_release_payload("0.1.3", assets=[]))

    plan = build_update_plan("0.1.2", release, install_method="pipx")

    assert plan.wheel_url is None
    assert plan.can_auto_update is False
    assert plan.command is None


def test_cli_update_check_never_runs_subprocess(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: parse_latest_release(_release_payload("0.1.3")))
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "pipx")

    def fail_run(command):
        raise AssertionError(f"unexpected subprocess: {command}")

    monkeypatch.setattr(cli.update_module, "run_update_command", fail_run)

    assert cli.main(["update", "--check"]) == 0

    out = capsys.readouterr().out
    assert "Current version: 0.1.2" in out
    assert "Latest version: 0.1.3" in out
    assert "Update now?" not in out


def test_cli_update_dry_run_shows_command_but_does_not_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: parse_latest_release(_release_payload("0.1.3")))
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "pipx")
    monkeypatch.setattr(cli.update_module, "run_update_command", lambda command: (_ for _ in ()).throw(AssertionError()))

    assert cli.main(["update", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert "Would run: pipx install --force" in out
    assert "Update now?" not in out


def test_cli_update_json_returns_shape_and_does_not_prompt(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: parse_latest_release(_release_payload("0.1.3")))
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "pipx")
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))
    monkeypatch.setattr(cli.update_module, "run_update_command", lambda command: (_ for _ in ()).throw(AssertionError()))

    assert cli.main(["update", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["current_version"] == "0.1.2"
    assert output["latest_version"] == "0.1.3"
    assert output["update_available"] is True
    assert output["install_method"] == "pipx"
    assert output["can_auto_update"] is True
    assert output["command"][0:3] == ["pipx", "install", "--force"]


def test_cli_update_json_yes_runs_supported_updater_and_stays_json(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: parse_latest_release(_release_payload("0.1.3")))
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "pipx")

    def fake_run(command):
        return subprocess.CompletedProcess(command, 0, stdout="updated", stderr="")

    monkeypatch.setattr(cli.update_module, "run_update_command", fake_run)

    assert cli.main(["update", "--json", "--yes"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["updater"] == {"ran": True, "returncode": 0, "stdout": "updated", "stderr": ""}


def test_cli_update_json_check_yes_never_runs_subprocess(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: parse_latest_release(_release_payload("0.1.3")))
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "pipx")
    monkeypatch.setattr(cli.update_module, "run_update_command", lambda command: (_ for _ in ()).throw(AssertionError()))

    assert cli.main(["update", "--json", "--check", "--yes"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert "updater" not in output
    assert output["update_available"] is True


def test_cli_update_yes_runs_supported_updater(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: parse_latest_release(_release_payload("0.1.3")))
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "pipx")
    calls = []

    def fake_run(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

    monkeypatch.setattr(cli.update_module, "run_update_command", fake_run)

    assert cli.main(["update", "--yes"]) == 0

    assert calls
    assert calls[0][0:3] == ["pipx", "install", "--force"]
    assert "Running: pipx install --force" in capsys.readouterr().out


def test_cli_update_source_checkout_does_not_auto_run(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: parse_latest_release(_release_payload("0.1.3")))
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "source")
    monkeypatch.setattr(cli.update_module, "run_update_command", lambda command: (_ for _ in ()).throw(AssertionError()))

    assert cli.main(["update", "--yes"]) == 0

    out = capsys.readouterr().out
    assert "Source checkout detected" in out
    assert "git pull" in out
    assert "uv sync" in out


def test_cli_update_unknown_install_method_prints_fallback(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: parse_latest_release(_release_payload("0.1.3")))
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "unknown")

    assert cli.main(["update", "--yes"]) == 0

    out = capsys.readouterr().out
    assert "Install method could not be detected" in out
    assert "pipx install --force" in out


def test_cli_update_missing_wheel_asset_prints_clean_message(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(
        cli.update_module,
        "fetch_latest_release",
        lambda: parse_latest_release(_release_payload("0.1.3", assets=[])),
    )
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "pipx")

    assert cli.main(["update", "--yes"]) == 0

    out = capsys.readouterr().out
    assert "No installable wheel asset was found" in out
    assert "Release URL:" in out


def test_cli_update_network_failure_is_clean(monkeypatch, capsys):
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: (_ for _ in ()).throw(UpdateCheckError("GitHub failed")))

    assert cli.main(["update", "--check"]) == 1

    assert "error: GitHub failed" in capsys.readouterr().err


def test_cli_update_current_version_message(monkeypatch, capsys):
    monkeypatch.setattr(cli, "__version__", "0.1.2")
    monkeypatch.setattr(cli.update_module, "fetch_latest_release", lambda: parse_latest_release(_release_payload("0.1.2")))
    monkeypatch.setattr(cli.update_module, "detect_install_method", lambda: "pipx")

    assert cli.main(["update"]) == 0

    assert "infomaniak-cli 0.1.2 is up to date." in capsys.readouterr().out
