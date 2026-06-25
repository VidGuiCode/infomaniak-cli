import pytest

from infomaniak_cli import secure_store


class _NoopRunResult:
    returncode = 0


@pytest.fixture(autouse=True)
def _no_real_icacls(monkeypatch):
    """Keep the offline unit suite from spawning real ``icacls`` on Windows.

    Production code still shells out to ``icacls`` to harden credential files; in
    the test suite we swap the *default* runner for a no-op so that saving a
    secret never spawns a subprocess (fast + fully offline) and never rewrites
    temp-dir ACLs (real ``/inheritance:r`` on tmp dirs broke pytest cleanup).

    POSIX ``os.chmod`` is deliberately left real, so the owner-only file/dir mode
    assertions in ``test_secure_store.py`` stay meaningful. Tests that exercise
    the Windows failure classification pass their own ``runner`` explicitly and
    are unaffected by this default-runner swap.
    """

    monkeypatch.setattr(secure_store, "_default_runner", lambda command: _NoopRunResult())
