import json
import os
import subprocess
import sys


def run_ik(tmp_path, *args):
    env = os.environ.copy()
    env["IK_CONFIG_DIR"] = str(tmp_path / "config")
    env["PYTHONPATH"] = "src"
    return subprocess.run(
        [sys.executable, "-m", "infomaniak_cli.cli", *args],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_cli_setup_whoami_and_doctor_json(tmp_path):
    setup = run_ik(tmp_path, "setup", "--profile", "cylro", "--non-interactive")
    assert setup.returncode == 0, setup.stderr
    assert "Profile ready: cylro" in setup.stdout

    whoami = run_ik(tmp_path, "whoami", "--json")
    assert whoami.returncode == 0, whoami.stderr
    data = json.loads(whoami.stdout)
    assert data["profile"] == "cylro"

    doctor = run_ik(tmp_path, "doctor", "--json")
    assert doctor.returncode == 0, doctor.stderr
    checks = json.loads(doctor.stdout)["checks"]
    assert checks["profile_configured"] is True
    assert checks["token_configured"] is False


def test_cli_bootstrap_requires_token(tmp_path):
    setup = run_ik(tmp_path, "setup", "--profile", "cylro", "--non-interactive")
    assert setup.returncode == 0, setup.stderr

    bootstrap = run_ik(tmp_path, "bootstrap", "--non-interactive")

    assert bootstrap.returncode == 1
    assert "No token configured for profile: cylro" in bootstrap.stderr
