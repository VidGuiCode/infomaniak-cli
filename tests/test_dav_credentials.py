"""DAV credential reuse and address-book selection (v0.2.20).

Fully offline: discovery is stubbed and no DAV request is made.
"""

from __future__ import annotations

import json

from infomaniak_cli import cli
from infomaniak_cli.auth import CalendarPasswordStore, ContactsPasswordStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.dav_discovery import DavDiscoveryError



# --- v0.2.20 DAV credential reuse -----------------------------------------


CAL_PASSWORD = "secret-caldav-password"
CARD_PASSWORD = "secret-carddav-password"


def _dav_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        calendar_url="https://sync.example.test/calendars/user/work/",
        calendar_username="VG00000",
        contacts_url="https://sync.example.test/addressbooks/user/default/",
        contacts_username="VG00000",
        make_default=True,
    )


def test_auth_contacts_reuses_the_stored_calendar_password(tmp_path, monkeypatch, capsys):
    _dav_profile(tmp_path, monkeypatch)
    CalendarPasswordStore().save_password("work", CAL_PASSWORD)
    monkeypatch.setattr(cli, "discover_addressbooks", lambda *a, **k: [])

    assert cli.main(["--profile", "work", "auth", "contacts", "--reuse-from", "calendar"]) == 0

    assert ContactsPasswordStore().load_password("work") == CAL_PASSWORD
    captured = capsys.readouterr()
    # the secret must never be echoed
    assert CAL_PASSWORD not in captured.out
    assert CAL_PASSWORD not in captured.err
    assert "reused from calendar" in captured.out


def test_auth_calendar_reuses_the_stored_contacts_password(tmp_path, monkeypatch, capsys):
    _dav_profile(tmp_path, monkeypatch)
    ContactsPasswordStore().save_password("work", CARD_PASSWORD)
    monkeypatch.setattr(cli, "discover_calendars", lambda *a, **k: [])

    assert cli.main(["--profile", "work", "auth", "calendar", "--reuse-from", "contacts"]) == 0

    assert CalendarPasswordStore().load_password("work") == CARD_PASSWORD
    assert CARD_PASSWORD not in capsys.readouterr().out


def test_reuse_never_copies_the_url_or_username(tmp_path, monkeypatch):
    """Only the credential is shared; collections stay independent."""
    _dav_profile(tmp_path, monkeypatch)
    CalendarPasswordStore().save_password("work", CAL_PASSWORD)
    monkeypatch.setattr(cli, "discover_addressbooks", lambda *a, **k: [])

    before = ProfileManager().get("work")
    assert cli.main(["--profile", "work", "auth", "contacts", "--reuse-from", "calendar"]) == 0
    after = ProfileManager().get("work")

    assert after.contacts_url == before.contacts_url
    assert after.calendar_url == before.calendar_url
    assert after.contacts_url != after.calendar_url


def test_reuse_without_a_source_password_is_actionable(tmp_path, monkeypatch, capsys):
    _dav_profile(tmp_path, monkeypatch)

    assert cli.main(["--profile", "work", "auth", "contacts", "--reuse-from", "calendar"]) == 1

    err = capsys.readouterr().err
    assert "nothing to reuse" in err
    assert "auth calendar" in err


def test_reuse_offer_is_accepted_and_stores_the_other_service(tmp_path, monkeypatch, capsys):
    _dav_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "discover_calendars", lambda *a, **k: [])
    # the offer only happens on a real terminal, by design
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "y")

    assert cli.main([
        "--profile", "work", "auth", "calendar", "--password", CAL_PASSWORD,
    ]) == 0

    assert ContactsPasswordStore().load_password("work") == CAL_PASSWORD
    assert CAL_PASSWORD not in capsys.readouterr().out


def test_reuse_offer_declined_stores_nothing(tmp_path, monkeypatch, capsys):
    _dav_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "discover_calendars", lambda *a, **k: [])
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")

    assert cli.main([
        "--profile", "work", "auth", "calendar", "--password", CAL_PASSWORD,
    ]) == 0

    assert not ContactsPasswordStore().has_password("work")
    assert "Not reused" in capsys.readouterr().out


def test_reuse_offer_is_skipped_when_suppressed(tmp_path, monkeypatch):
    _dav_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "discover_calendars", lambda *a, **k: [])
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)

    def no_prompt(*args, **kwargs):
        raise AssertionError("--no-reuse-prompt must not prompt")

    monkeypatch.setattr("builtins.input", no_prompt)

    assert cli.main([
        "--profile", "work", "auth", "calendar",
        "--password", CAL_PASSWORD, "--no-reuse-prompt",
    ]) == 0

    assert not ContactsPasswordStore().has_password("work")


def test_reuse_offer_is_skipped_when_the_other_service_already_has_one(tmp_path, monkeypatch):
    _dav_profile(tmp_path, monkeypatch)
    ContactsPasswordStore().save_password("work", CARD_PASSWORD)
    monkeypatch.setattr(cli, "discover_calendars", lambda *a, **k: [])
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: True)

    def no_prompt(*args, **kwargs):
        raise AssertionError("must not offer when the target already has a password")

    monkeypatch.setattr("builtins.input", no_prompt)

    assert cli.main(["--profile", "work", "auth", "calendar", "--password", CAL_PASSWORD]) == 0

    # the existing contacts password is untouched
    assert ContactsPasswordStore().load_password("work") == CARD_PASSWORD


# --- v0.2.20 address-book selection ---------------------------------------


ADDRESSBOOKS = [
    {"name": "Default", "url": "https://sync.example.test/addressbooks/user/default/"},
    {"name": "Chamber", "url": "https://sync.example.test/addressbooks/user/chamber/"},
]


def _addressbook_profile(tmp_path, monkeypatch, *, url="https://sync.example.test/addressbooks/user/default/"):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work", contacts_url=url, contacts_username="VG00000", make_default=True
    )
    ContactsPasswordStore().save_password("work", CARD_PASSWORD)


def test_contacts_addressbook_list_is_read_only(tmp_path, monkeypatch, capsys):
    _addressbook_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "discover_addressbooks", lambda *a, **k: ADDRESSBOOKS)

    assert cli.main(["contacts", "addressbook", "list", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 2
    assert payload["current"].endswith("/default/")
    # nothing was persisted
    assert ProfileManager().get("work").contacts_url.endswith("/default/")


def test_contacts_addressbook_use_persists_the_named_collection(tmp_path, monkeypatch, capsys):
    _addressbook_profile(tmp_path, monkeypatch)
    target = ADDRESSBOOKS[1]["url"]

    assert cli.main([
        "--profile", "work", "contacts", "addressbook", "use", target, "--yes", "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["saved"] is True
    assert payload["after"] == target
    assert payload["writes"] == "local profile config only"
    assert ProfileManager().get("work").contacts_url == target


def test_contacts_addressbook_use_dry_run_persists_nothing(tmp_path, monkeypatch, capsys):
    _addressbook_profile(tmp_path, monkeypatch)
    before = ProfileManager().get("work").contacts_url

    assert cli.main([
        "contacts", "addressbook", "use", ADDRESSBOOKS[1]["url"], "--dry-run", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["saved"] is False
    assert ProfileManager().get("work").contacts_url == before


def test_contacts_addressbook_use_requires_an_explicit_profile_for_yes(tmp_path, monkeypatch, capsys):
    _addressbook_profile(tmp_path, monkeypatch)
    monkeypatch.delenv("IK_PROFILE", raising=False)
    before = ProfileManager().get("work").contacts_url

    assert cli.main(["contacts", "addressbook", "use", ADDRESSBOOKS[1]["url"], "--yes"]) == 1

    assert "profile is explicit" in capsys.readouterr().err
    assert ProfileManager().get("work").contacts_url == before


def test_contacts_addressbook_repair_refuses_to_guess_between_several(tmp_path, monkeypatch, capsys):
    _addressbook_profile(tmp_path, monkeypatch, url="https://sync.infomaniak.com/")
    monkeypatch.setattr(cli, "discover_addressbooks", lambda *a, **k: ADDRESSBOOKS)

    assert cli.main(["--profile", "work", "contacts", "addressbook", "repair", "--yes"]) == 1

    err = capsys.readouterr().err
    assert "refusing to guess" in err
    assert "addressbook use" in err
    assert ProfileManager().get("work").contacts_url == "https://sync.infomaniak.com/"


def test_contacts_addressbook_repair_saves_a_single_discovery(tmp_path, monkeypatch, capsys):
    _addressbook_profile(tmp_path, monkeypatch, url="https://sync.infomaniak.com/")
    monkeypatch.setattr(cli, "discover_addressbooks", lambda *a, **k: [ADDRESSBOOKS[0]])

    assert cli.main(["--profile", "work", "contacts", "addressbook", "repair", "--yes", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["saved"] is True
    assert payload["after"] == ADDRESSBOOKS[0]["url"]


def test_contacts_addressbook_errors_redact_the_password(tmp_path, monkeypatch, capsys):
    _addressbook_profile(tmp_path, monkeypatch)

    def failing(*args, **kwargs):
        raise DavDiscoveryError(f"no principal for {CARD_PASSWORD}")

    monkeypatch.setattr(cli, "discover_addressbooks", failing)

    assert cli.main(["contacts", "addressbook", "list"]) == 1

    err = capsys.readouterr().err
    assert CARD_PASSWORD not in err
    assert "discovery failed" in err


def test_calendar_repair_list_is_read_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        calendar_url="https://sync.example.test/calendars/user/work/",
        calendar_username="VG00000",
        make_default=True,
    )
    CalendarPasswordStore().save_password("work", CAL_PASSWORD)
    monkeypatch.setattr(
        cli, "discover_calendars",
        lambda *a, **k: [{"name": "Work", "url": "https://sync.example.test/calendars/user/work/"}],
    )
    before = ProfileManager().get("work").calendar_url

    assert cli.main(["calendar", "repair", "--list", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert ProfileManager().get("work").calendar_url == before


def test_reuse_offer_is_never_made_when_stdin_is_not_a_terminal(tmp_path, monkeypatch):
    """Piped/scripted runs must never block on the reuse question."""
    _dav_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "discover_calendars", lambda *a, **k: [])
    monkeypatch.setattr(cli, "_stdin_is_tty", lambda: False)

    def no_prompt(*args, **kwargs):
        raise AssertionError("must not prompt without a terminal")

    monkeypatch.setattr("builtins.input", no_prompt)

    assert cli.main(["--profile", "work", "auth", "calendar", "--password", CAL_PASSWORD]) == 0
    assert not ContactsPasswordStore().has_password("work")


def test_reuse_from_cannot_be_combined_with_an_explicit_password(tmp_path, monkeypatch, capsys):
    """Two sources for one secret is ambiguous, so it is refused rather than ranked."""
    _dav_profile(tmp_path, monkeypatch)
    CalendarPasswordStore().save_password("work", CAL_PASSWORD)

    for extra in (["--password", "other"], ["--stdin"]):
        assert cli.main([
            "--profile", "work", "auth", "contacts", "--reuse-from", "calendar", *extra,
        ]) == 2
        assert "cannot be combined" in capsys.readouterr().err

    # nothing was stored by the refused invocations
    assert not ContactsPasswordStore().has_password("work")
