from infomaniak_cli.pathcheck import (
    fix_path_command,
    locate_entry_point,
    path_status,
    plan_path_fix,
)


WIN_SCRIPTS = r"C:\Users\you\AppData\Roaming\Python\Python311\Scripts"
WIN_IK = WIN_SCRIPTS + r"\ik.exe"
POSIX_SCRIPTS = "/home/you/.local/bin"
POSIX_IK = POSIX_SCRIPTS + "/ik"


def test_locate_entry_point_uses_injected_which():
    assert locate_entry_point(lambda name: f"/usr/bin/{name}") == "/usr/bin/ik"
    assert locate_entry_point(lambda name: None) is None


def test_path_status_on_path_when_ik_dir_is_listed():
    status = path_status(
        scripts_dir=POSIX_SCRIPTS,
        ik_path=POSIX_IK,
        path_env=f"/usr/bin:{POSIX_SCRIPTS}:/bin",
        sep=":",
    )

    assert status["on_path"] is True
    assert status["dir_on_path"] is True
    assert status["ik_dir"] == POSIX_SCRIPTS


def test_path_status_not_on_path_reports_dir_off_path():
    status = path_status(
        scripts_dir=POSIX_SCRIPTS,
        ik_path=POSIX_IK,
        path_env="/usr/bin:/bin",
        sep=":",
    )

    assert status["on_path"] is False
    assert status["dir_on_path"] is False


def test_path_status_windows_comparison_is_case_insensitive():
    status = path_status(
        scripts_dir=WIN_SCRIPTS,
        ik_path=WIN_IK,
        path_env=r"C:\Windows;c:\users\you\appdata\roaming\python\python311\scripts",
        sep=";",
    )

    assert status["on_path"] is True
    assert status["dir_on_path"] is True


def test_path_status_dir_on_path_but_exe_elsewhere():
    # scripts_dir is on PATH, but the resolved ik lives in a different (off-PATH) dir.
    status = path_status(
        scripts_dir=POSIX_SCRIPTS,
        ik_path="/opt/other/bin/ik",
        path_env=f"/usr/bin:{POSIX_SCRIPTS}",
        sep=":",
    )

    assert status["dir_on_path"] is True
    assert status["on_path"] is False
    assert status["ik_dir"] == "/opt/other/bin"


def test_path_status_ik_not_found():
    status = path_status(
        scripts_dir=POSIX_SCRIPTS,
        ik_path=None,
        path_env="/usr/bin:/bin",
        sep=":",
    )

    assert status["ik_path"] is None
    assert status["ik_dir"] is None
    assert status["on_path"] is False
    assert status["dir_on_path"] is False


def test_fix_path_command_windows_targets_user_scope_only():
    command = fix_path_command(scripts_dir=WIN_SCRIPTS, os_name="nt")

    assert "powershell" in command
    assert "'User'" in command
    assert WIN_SCRIPTS in command
    # Never machine/system scope, never setx (which can clobber a long PATH).
    assert "Machine" not in command
    assert "setx" not in command.lower()


def test_fix_path_command_posix_appends_export_to_rc():
    command = fix_path_command(scripts_dir=POSIX_SCRIPTS, os_name="posix")

    assert command == f'echo \'export PATH="{POSIX_SCRIPTS}:$PATH"\' >> ~/.bashrc'


def test_plan_path_fix_already_on_path_is_noop():
    plan = plan_path_fix(POSIX_SCRIPTS, f"/usr/bin:{POSIX_SCRIPTS}", os_name="posix", sep=":")

    assert plan["already_on_path"] is True
    assert plan["new_path"] is None
    assert plan["fix_command"] is None


def test_plan_path_fix_appends_and_returns_command():
    plan = plan_path_fix(POSIX_SCRIPTS, "/usr/bin:/bin", os_name="posix", sep=":")

    assert plan["already_on_path"] is False
    assert plan["new_path"] == f"/usr/bin:/bin:{POSIX_SCRIPTS}"
    assert plan["fix_command"] == f'echo \'export PATH="{POSIX_SCRIPTS}:$PATH"\' >> ~/.bashrc'
    assert POSIX_SCRIPTS in plan["change_description"]


def test_plan_path_fix_empty_path_uses_scripts_dir():
    plan = plan_path_fix(POSIX_SCRIPTS, "", os_name="posix", sep=":")

    assert plan["new_path"] == POSIX_SCRIPTS
