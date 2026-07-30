"""Offline tests for `ik admin mailbox settings` and `... sender` (0.3.5).

PATCH is partial per field, but the two sender arrays replace wholesale, so
these tests pin that add/remove always send the complete list — and that no
command can flip `has_responder`, which would auto-reply to third parties.
"""


import json

import pytest

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIError
from infomaniak_cli.services.admin import (
    mailbox_note,
    sender_list,
    slim_mailbox_settings,
    update_mailbox_settings,
)

from test_admin import RAW_HOSTING, FakeAPI, _install, _setup_profile


class SettingsAPI(FakeAPI):
    """Stateful fake for the mailbox settings PATCH."""

    def __init__(self, **overrides):
        super().__init__({})
        self.state = {
            "mailbox": "user@example.com",
            "mailbox_name": "user",
            "note": "",
            "has_move_spam": True,
            "has_mail_filtering": False,
            "mail_filtering_folder_commercials": None,
            "mail_filtering_folder_social_networks": None,
            "blocked_senders": [],
            "authorized_senders": [],
            # NOTE: overrides below are normalized to the live object shape in
            # __init__ so the fake never returns a shape the API would not.
            "has_responder": False,
            **overrides,
        }
        for key in ("blocked_senders", "authorized_senders"):
            self.state[key] = [
                entry if isinstance(entry, dict) else {"email": entry, "locked": ""}
                for entry in self.state.get(key) or []
            ]
        self.patches = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path == "/1/mail_hostings/111/mailboxes/user":
            data = dict(self.state)
            # The live API omits both arrays unless ?with= asks for them.
            if not (params or {}).get("with"):
                data.pop("blocked_senders", None)
                data.pop("authorized_senders", None)
            return {"result": "success", "data": data}
        if path == "/1/mail_hostings/111":
            return {"result": "success", "data": RAW_HOSTING}
        raise InformaniakAPIError(404, f"GET {path} failed: not found")

    def request(self, method, path, *, params=None, json=None, **kwargs):
        assert method == "PATCH"
        self.patches.append((path, json))
        stored = dict(json)
        # Live shape: the server echoes sender entries back as objects even
        # though it accepts plain strings on write.
        for key in ("blocked_senders", "authorized_senders"):
            if key in stored:
                stored[key] = [{"email": entry, "locked": ""} for entry in stored[key]]
        self.state.update(stored)
        return {"result": "success", "data": True}


def test_slim_mailbox_settings_projects_readable_fields():
    state = slim_mailbox_settings({
        "note": "hi",
        "blocked_senders": ["a@example.com"],
        "authorized_senders": None,
    })

    assert state == {"note": "hi", "blocked_senders": ["a@example.com"], "authorized_senders": []}


def test_sender_list_refuses_when_the_read_omitted_the_array():
    """Returning [] for an absent key would wipe the real list on write-back."""
    with pytest.raises(ValueError) as excinfo:
        sender_list({"note": "x"}, "blocked_senders")

    assert "did not include" in str(excinfo.value)


def test_update_mailbox_settings_refuses_unsupported_fields():
    with pytest.raises(ValueError) as excinfo:
        update_mailbox_settings(object(), "111", "user", {"has_responder": True})

    assert "does not support" in str(excinfo.value)


def test_mailbox_note_length_is_capped_locally():
    assert mailbox_note("short") == "short"
    with pytest.raises(ValueError):
        mailbox_note("x" * 81)


def test_cli_settings_show_reads_only(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI(note="Team mailbox", blocked_senders=["spam@example.com"])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "settings", "show", "user", "--json"]) == 0

    settings = json.loads(capsys.readouterr().out)["settings"]
    assert settings["note"] == "Team mailbox"
    assert settings["blocked_senders"] == ["spam@example.com"]
    assert api.patches == []


def test_cli_settings_set_sends_only_changed_fields(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI(has_move_spam=True)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "settings", "set", "user", "--note", "Shared",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["updated"] is True
    assert output["confirmed"] is True
    assert output["fields_sent"] == ["note"]
    assert api.patches[0][0] == "/1/mail_hostings/111/mailboxes/user"
    assert api.patches[0][1] == {"note": "Shared"}


def test_cli_settings_set_refuses_when_nothing_passed(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "settings", "set", "user", "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "Nothing to set" in capsys.readouterr().err
    assert api.patches == []
    assert api.calls == []  # a usage error must not cost a round-trip


def test_cli_settings_set_rejects_a_too_long_note(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "settings", "set", "user", "--note", "x" * 81,
        "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "at most 80" in capsys.readouterr().err
    assert api.patches == []



def test_cli_sender_block_sends_the_complete_list(tmp_path, monkeypatch, capsys):
    """The array replaces wholesale, so existing entries must be resent."""
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI(blocked_senders=["old@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "block", "user", "new@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["confirmed"] is True
    assert api.patches[0][1] == {"blocked_senders": ["old@example.com", "new@example.com"]}


def test_cli_sender_block_is_idempotent_and_case_insensitive(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI(blocked_senders=["Spam@Example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "block", "user", "spam@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["updated"] is False
    assert api.patches == []


def test_cli_sender_unblock_removes_case_variants(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI(blocked_senders=["Spam@Example.com", "keep@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "unblock", "user", "spam@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert api.patches[0][1] == {"blocked_senders": ["keep@example.com"]}


def test_cli_sender_unblock_absent_is_a_noop(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI(blocked_senders=["other@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "unblock", "user", "ghost@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["updated"] is False
    assert api.patches == []


def test_cli_sender_allow_uses_the_other_list(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "allow", "user", "friend@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert api.patches[0][1] == {"authorized_senders": ["friend@example.com"]}


def test_cli_sender_block_states_the_delivery_effect(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "block", "user", "spam@example.com",
        "--dry-run", "--profile", "work",
    ]) == 0

    assert "will stop arriving" in capsys.readouterr().out
    assert api.patches == []


def test_cli_sender_block_rejects_a_malformed_address(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "block", "user", "not-an-address",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "valid forwarding address" in capsys.readouterr().err
    assert api.patches == []


@pytest.mark.parametrize(
    "argv",
    [
        ["admin", "mailbox", "settings", "set", "user", "--note", "X"],
        ["admin", "mailbox", "sender", "block", "user", "a@example.com"],
        ["admin", "mailbox", "sender", "unblock", "user", "a@example.com"],
        ["admin", "mailbox", "sender", "allow", "user", "a@example.com"],
    ],
)
def test_settings_writes_dry_run_never_patches(argv, tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI(blocked_senders=["a@example.com"], authorized_senders=[])
    _install(monkeypatch, api)

    assert cli.main([*argv, "--dry-run", "--profile", "work", "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert api.patches == []


@pytest.mark.parametrize(
    "argv",
    [
        ["admin", "mailbox", "settings", "set", "user", "--note", "X"],
        ["admin", "mailbox", "sender", "block", "user", "a@example.com"],
    ],
)
def test_settings_writes_require_an_explicit_profile_for_yes(argv, tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI()
    _install(monkeypatch, api)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    assert cli.main([*argv, "--yes", "--json"]) == 1

    assert "explicit" in capsys.readouterr().err
    assert api.patches == []


def test_settings_readback_mismatch_warns_and_exits_nonzero(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")

    class LyingAPI(SettingsAPI):
        def request(self, method, path, *, params=None, json=None, **kwargs):
            self.patches.append((path, json))
            return {"result": "success", "data": True}  # accepts, changes nothing

    api = LyingAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "settings", "set", "user", "--note", "Changed",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    captured = capsys.readouterr()
    assert "readback does not reflect it" in captured.err
    assert json.loads(captured.out)["confirmed"] is False


def test_no_settings_command_can_write_an_unsupported_field(tmp_path, monkeypatch, capsys):
    """Behavioural, not a string grep: drive every write and inspect the PATCHes.

    Enabling `has_responder` would auto-reply to third parties, and the spam and
    filtering flags cannot be read back at all, so none of them may be written.
    """
    from infomaniak_cli.services.admin import WRITABLE_MAILBOX_FIELDS

    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    # Each invocation must actually change something, or it no-ops and the
    # assertion below would pass vacuously.
    invocations = [
        (["admin", "mailbox", "settings", "set", "user", "--note", "X"], {}),
        (["admin", "mailbox", "sender", "block", "user", "new@example.com"], {}),
        (["admin", "mailbox", "sender", "unblock", "user", "a@example.com"],
         {"blocked_senders": ["a@example.com"]}),
        (["admin", "mailbox", "sender", "allow", "user", "new@example.com"], {}),
        (["admin", "mailbox", "sender", "unallow", "user", "b@example.com"],
         {"authorized_senders": ["b@example.com"]}),
    ]
    sent: set[str] = set()
    for argv, state in invocations:
        api = SettingsAPI(**state)
        _install(monkeypatch, api)
        assert cli.main([*argv, "--yes", "--profile", "work", "--json"]) == 0
        capsys.readouterr()
        assert api.patches, f"expected a PATCH for {argv}"
        for _path, body in api.patches:
            sent.update(body)

    assert sent, "expected at least one PATCH across the write commands"
    assert sent <= set(WRITABLE_MAILBOX_FIELDS)
    assert "has_responder" not in sent
    assert "show_config_modal" not in sent


def test_sender_write_refuses_when_the_read_omits_the_array(tmp_path, monkeypatch, capsys):
    """Without ?with=, the API omits the arrays; writing then would wipe them."""
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")

    class NoWithAPI(SettingsAPI):
        def get(self, path, params=None):
            self.calls.append((path, params))
            if path == "/1/mail_hostings/111/mailboxes/user":
                data = {k: v for k, v in self.state.items()
                        if k not in ("blocked_senders", "authorized_senders")}
                return {"result": "success", "data": data}
            if path == "/1/mail_hostings/111":
                return {"result": "success", "data": RAW_HOSTING}
            raise InformaniakAPIError(404, f"GET {path} failed: not found")

    api = NoWithAPI(blocked_senders=["keep@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "block", "user", "new@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "did not include" in capsys.readouterr().err
    assert api.patches == []


def test_settings_read_requests_the_sender_arrays(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI()
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "settings", "show", "user", "--json"]) == 0

    mailbox_reads = [c for c in api.calls if c[0].endswith("/mailboxes/user")]
    assert mailbox_reads
    assert all((c[1] or {}).get("with") for c in mailbox_reads)


def test_clearing_the_note_is_confirmed_not_reported_as_a_failure(tmp_path, monkeypatch, capsys):
    """The server stores a cleared note as null; "" and None mean the same."""
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")

    class NullingAPI(SettingsAPI):
        def request(self, method, path, *, params=None, json=None, **kwargs):
            self.patches.append((path, json))
            self.state.update({k: (None if v == "" else v) for k, v in json.items()})
            return {"result": "success", "data": True}

    api = NullingAPI(note="Old note")
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "settings", "set", "user", "--note", "",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["confirmed"] is True


def test_sender_dry_run_reports_the_planned_diff(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI(blocked_senders=["old@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "block", "user", "new@example.com",
        "--dry-run", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["after"]["blocked_senders"] == ["old@example.com", "new@example.com"]
    assert "blocked_senders" in output["changed"]
    assert api.patches == []


def test_settings_cancelled_confirmation_exits_two(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI()
    _install(monkeypatch, api)
    monkeypatch.setattr(cli, "_confirm", lambda *a, **k: False)

    assert cli.main([
        "admin", "mailbox", "settings", "set", "user", "--note", "X", "--profile", "work",
    ]) == 2

    assert api.patches == []


def test_sender_list_maps_the_live_object_shape_to_addresses():
    """Confirmed live: reads return objects, writes take plain strings."""
    assert sender_list(
        {"blocked_senders": [{"email": "a@example.com", "locked": ""}]}, "blocked_senders"
    ) == ["a@example.com"]
    # plain strings (defensive) still work
    assert sender_list({"blocked_senders": ["b@example.com"]}, "blocked_senders") == ["b@example.com"]
    assert sender_list({"blocked_senders": []}, "blocked_senders") == []


def test_sender_write_never_sends_the_read_object_shape(tmp_path, monkeypatch, capsys):
    """Echoing the read shape back would store stringified dicts."""
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SettingsAPI(blocked_senders=["old@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "sender", "block", "user", "new@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    sent = api.patches[0][1]["blocked_senders"]
    assert sent == ["old@example.com", "new@example.com"]
    assert all(isinstance(entry, str) for entry in sent)
