"""Offline tests for `ik admin mailbox forwarding` (0.3.2).

The endpoint is a full replace with no ETag, and `is_enabled: false` is
documented to DROP every stored address, so these tests pin the read->write
field mapping and the destructive-path guard rather than only happy paths.
"""

import json

import pytest

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIError
from infomaniak_cli.services.admin import forwarding_address, forwarding_addresses

from test_admin import RAW_HOSTING, FakeAPI, _install, _setup_profile


class ForwardingAPI(FakeAPI):
    """Stateful fake mirroring the real read/write asymmetry.

    The read returns `redirect_adresses` (single d) as objects; the write takes
    `redirect_addresses` (correct spelling) as plain strings.
    """

    def __init__(self, addresses=(), *, is_enabled=True, dont_deliver=False, forward_spam=False):
        super().__init__({})
        self.addresses = list(addresses)
        self.is_enabled = is_enabled
        self.dont_deliver = dont_deliver
        self.forward_spam = forward_spam
        self.puts = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path.endswith("/forwarding_addresses"):
            return {
                "result": "success",
                "data": {
                    "is_enabled": self.is_enabled,
                    "redirect_adresses": [{"email": a, "email_idn": a} for a in self.addresses],
                    "has_dont_deliver": self.dont_deliver,
                    "has_forward_spam": self.forward_spam,
                },
            }
        if path == "/1/mail_hostings/111":
            return {"result": "success", "data": RAW_HOSTING}
        raise InformaniakAPIError(404, f"GET {path} failed: not found")

    def request(self, method, path, *, params=None, json=None, **kwargs):
        assert method == "PUT"
        self.puts.append((path, json))
        self.addresses = list(json["redirect_addresses"])
        self.is_enabled = json["is_enabled"]
        self.dont_deliver = json["has_dont_deliver"]
        self.forward_spam = json["has_forward_spam"]
        return {"result": "success", "data": True}


def test_forwarding_addresses_maps_the_read_object_shape():
    assert forwarding_addresses(
        {"redirect_adresses": [{"email": "a@example.com", "email_idn": "a@example.com"}]}
    ) == ["a@example.com"]
    assert forwarding_addresses({"redirect_adresses": []}) == []
    assert forwarding_addresses({}) == []
    assert forwarding_addresses({"redirect_addresses": ["b@example.com"]}) == ["b@example.com"]


def test_forwarding_address_validation():
    assert forwarding_address(" a@example.com ") == "a@example.com"
    for bad in ("", "not-an-address", "a@localhost", "a b@example.com"):
        with pytest.raises(ValueError):
            forwarding_address(bad)


def test_cli_forwarding_show_reports_effects_not_flag_names(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, ForwardingAPI(["a@example.com"], dont_deliver=True))

    assert cli.main(["admin", "mailbox", "forwarding", "show", "user", "--json"]) == 0

    state = json.loads(capsys.readouterr().out)["forwarding"]
    assert state == {
        "enabled": True,
        "addresses": ["a@example.com"],
        "keeps_local_copy": False,  # has_dont_deliver: True, inverted for the reader
        "forwards_spam": False,
    }


def test_cli_forwarding_add_sends_the_complete_body(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["a@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "add", "user", "b@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["updated"] is True
    assert output["confirmed"] is True
    assert output["notified"] is False
    assert output["after"]["addresses"] == ["a@example.com", "b@example.com"]
    path, body = api.puts[0]
    assert path == "/1/mail_hostings/111/mailboxes/user/forwarding_addresses"
    # every documented field is always sent: a partial PUT would blank one
    assert set(body) == {"redirect_addresses", "is_enabled", "has_dont_deliver", "has_forward_spam"}
    assert body["redirect_addresses"] == ["a@example.com", "b@example.com"]


def test_cli_forwarding_add_enables_when_currently_off(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI([], is_enabled=False)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "add", "user", "b@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert api.puts[0][1]["is_enabled"] is True


def test_cli_forwarding_add_existing_is_a_noop(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["A@Example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "add", "user", "a@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["updated"] is False
    assert api.puts == []


def test_cli_forwarding_remove_last_address_warns_and_previews(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["a@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "remove", "user", "a@example.com",
        "--dry-run", "--profile", "work",
    ]) == 0

    assert "forwarding will stop entirely" in capsys.readouterr().out
    assert api.puts == []


def test_cli_forwarding_remove_absent_is_a_noop(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["a@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "remove", "user", "ghost@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["updated"] is False
    assert api.puts == []


def test_cli_forwarding_set_replaces_and_names_dropped_addresses(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["old@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "set", "user", "--address", "new@example.com",
        "--no-keep-copy", "--dry-run", "--profile", "work",
    ]) == 0

    out = capsys.readouterr().out
    assert "old@example.com" in out
    assert "no local copy" in out.lower()
    assert api.puts == []


def test_cli_forwarding_disable_refuses_without_acknowledgement(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["a@example.com", "b@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "disable", "user",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "drops every stored forwarding address" in capsys.readouterr().err
    assert api.puts == []


def test_cli_forwarding_set_with_no_addresses_cannot_bypass_the_acknowledgement(
    tmp_path, monkeypatch, capsys
):
    """`set` with no --address sends the same body as `disable`.

    Guarding only the command that names itself would leave the acknowledgement
    decorative, so the check keys on the effect.
    """
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["a@example.com", "b@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "set", "user", "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "drops every stored forwarding address" in capsys.readouterr().err
    assert api.puts == []


def test_cli_forwarding_disable_dry_run_previews_without_acknowledgement(tmp_path, monkeypatch, capsys):
    """The preview is exactly when a user needs to see what would be lost."""
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["a@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "disable", "user", "--dry-run", "--profile", "work",
    ]) == 0

    out = capsys.readouterr().out
    assert "a@example.com" in out
    assert "cannot be restored" in out
    assert api.puts == []


def test_cli_forwarding_emptying_addresses_always_restores_the_local_copy(tmp_path, monkeypatch, capsys):
    """No addresses plus no local copy would leave mail nowhere to go."""
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["a@example.com"], dont_deliver=True)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "remove", "user", "a@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["after"]["addresses"] == []
    assert output["after"]["keeps_local_copy"] is True
    assert api.puts[0][1]["has_dont_deliver"] is False


def test_cli_forwarding_remove_drops_case_variant_duplicates(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["A@example.com", "a@example.com", "keep@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "remove", "user", "a@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["after"]["addresses"] == ["keep@example.com"]


def test_cli_forwarding_set_dedupes_case_variants(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI([])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "set", "user",
        "--address", "a@example.com", "--address", "A@Example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert api.puts[0][1]["redirect_addresses"] == ["a@example.com"]


def test_cli_forwarding_set_refuses_contradictory_copy_flags(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, ForwardingAPI([]))

    with pytest.raises(SystemExit) as excinfo:
        cli.main([
            "admin", "mailbox", "forwarding", "set", "user", "--address", "a@example.com",
            "--keep-copy", "--no-keep-copy", "--profile", "work",
        ])

    assert excinfo.value.code == 2


def test_cli_forwarding_noop_result_still_carries_the_full_shape(tmp_path, monkeypatch, capsys):
    """A retry hits the no-op branch; scripts must not crash on missing keys."""
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, ForwardingAPI(["a@example.com"]))

    assert cli.main([
        "admin", "mailbox", "forwarding", "add", "user", "a@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["updated"] is False
    assert output["after"] == output["before"]
    assert output["changed"] == {}
    assert output["confirmed"] is None
    assert output["conditional_write"] is False


def test_cli_forwarding_disable_with_acknowledgement_clears_addresses(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI(["a@example.com"])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "disable", "user",
        "--i-understand-addresses-are-dropped", "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["updated"] is True
    assert output["after"] == {
        "enabled": False,
        "addresses": [],
        "keeps_local_copy": True,
        "forwards_spam": False,
    }
    assert api.puts[0][1]["is_enabled"] is False


def test_cli_forwarding_disable_when_already_off_is_a_noop(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI([], is_enabled=False)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "disable", "user",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["updated"] is False
    assert api.puts == []


def test_cli_forwarding_yes_requires_explicit_profile(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = ForwardingAPI([])
    _install(monkeypatch, api)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    assert cli.main([
        "admin", "mailbox", "forwarding", "add", "user", "b@example.com", "--yes", "--json",
    ]) == 1

    assert "explicit" in capsys.readouterr().err
    assert api.puts == []


def test_cli_forwarding_add_never_writes_without_yes_under_automation(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    api = ForwardingAPI([])
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "forwarding", "add", "user", "b@example.com", "--profile", "work",
    ]) == 1

    assert api.puts == []


def test_cli_forwarding_readback_mismatch_warns(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")

    class LyingAPI(ForwardingAPI):
        """Accepts the write but changes nothing — the readback must catch it."""

        def request(self, method, path, *, params=None, json=None, **kwargs):
            self.puts.append((path, json))
            return {"result": "success", "data": True}

    api = LyingAPI([])
    _install(monkeypatch, api)

    # Mail routing: an accepted-but-unconfirmed write must not read as success.
    assert cli.main([
        "admin", "mailbox", "forwarding", "add", "user", "b@example.com",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    captured = capsys.readouterr()
    assert "readback differs" in captured.err
    assert json.loads(captured.out)["confirmed"] is False
