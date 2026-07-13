import pytest

import keyring
from keyring.errors import KeyringError
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


@pytest.fixture(autouse=True)
def _mock_keyring(monkeypatch):
    """Keep the test suite from writing to the developer's real OS keyring.
    
    This provides an in-memory mock of the keyring API so tests run fully
    offline and side-effect free.
    """
    _store = {}

    def mock_set_password(service, username, password):
        _store[(service, username)] = password

    def mock_get_password(service, username):
        return _store.get((service, username))

    def mock_delete_password(service, username):
        if (service, username) in _store:
            del _store[(service, username)]
        else:
            raise KeyringError("Password not found")

    monkeypatch.setattr(keyring, "set_password", mock_set_password)
    monkeypatch.setattr(keyring, "get_password", mock_get_password)
    monkeypatch.setattr(keyring, "delete_password", mock_delete_password)

