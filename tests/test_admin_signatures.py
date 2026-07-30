"""Offline tests for `ik admin mailbox signature` (0.3.4).

PATCH is a genuine partial update here (unlike the forwarding PUT), so these
tests pin that only the given fields are sent, plus the guards around deleting
a signature that is currently a default.
"""

import json

import pytest

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIError
from infomaniak_cli.services.admin import signature_items, slim_signature

from test_admin import RAW_HOSTING, FakeAPI, _install, _setup_profile

SIG_A = {"id": 11, "name": "Work", "content": "Best regards\nExample Person", "position": "bottom"}
SIG_B = {"id": 22, "name": "Short", "content": "Thanks", "position": "top"}


class SignatureAPI(FakeAPI):
    """Stateful fake for the signature endpoints."""

    def __init__(self, signatures=(SIG_A, SIG_B), *, default_id=11, reply_id=None, is_forced=False):
        super().__init__({})
        self.signatures = [dict(s) for s in signatures]
        self.default_id = default_id
        self.reply_id = reply_id
        self.is_forced = is_forced
        self.posts = []
        self.patches = []
        self.deletes = []
        self._next_id = 90

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path.endswith("/signatures"):
            return {
                "result": "success",
                "data": {
                    "signatures": [dict(s) for s in self.signatures],
                    "default_signature_id": self.default_id,
                    "default_reply_signature_id": self.reply_id,
                    "is_forced": self.is_forced,
                },
            }
        if path == "/1/mail_hostings/111":
            return {"result": "success", "data": RAW_HOSTING}
        raise InformaniakAPIError(404, f"GET {path} failed: not found")

    def post(self, path, json=None):
        self.posts.append((path, json))
        if path.endswith("/set_defaults"):
            if "default_signature_id" in json:
                self.default_id = json["default_signature_id"]
            if "default_reply_signature_id" in json:
                self.reply_id = json["default_reply_signature_id"]
            return {"result": "success", "data": True}
        self._next_id += 1
        self.signatures.append({"id": self._next_id, **json})
        return {"result": "success", "data": {"id": self._next_id}}

    def request(self, method, path, *, params=None, json=None, **kwargs):
        assert method == "PATCH"
        self.patches.append((path, json))
        target = path.rsplit("/", 1)[-1]
        for signature in self.signatures:
            if str(signature["id"]) == target:
                signature.update(json)
        return {"result": "success", "data": True}

    def delete(self, path, params=None):
        self.deletes.append(path)
        target = path.rsplit("/", 1)[-1]
        self.signatures = [s for s in self.signatures if str(s["id"]) != target]
        return {"result": "success", "data": True}


def test_slim_signature_reports_length_not_body():
    slim = slim_signature(SIG_A, default_signature_id=11, default_reply_signature_id=22)

    assert slim["content_length"] == len(SIG_A["content"])
    assert "content" not in slim
    assert slim["is_default_send"] is True
    assert slim["is_default_reply"] is False


def test_signature_items_tolerates_a_missing_or_odd_payload():
    assert signature_items({"signatures": [SIG_A]}) == [SIG_A]
    assert signature_items({}) == []
    assert signature_items({"signatures": "nope"}) == []


def test_cli_signature_list_omits_bodies_but_raw_keeps_them(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, SignatureAPI())

    assert cli.main(["admin", "mailbox", "signature", "list", "user", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 2
    assert output["default_signature_id"] == 11
    assert all("content" not in item for item in output["signatures"])
    assert output["signatures"][0]["content_length"] == len(SIG_A["content"])

    _install(monkeypatch, SignatureAPI())
    assert cli.main(["admin", "mailbox", "signature", "list", "user", "--json", "--raw"]) == 0
    assert json.loads(capsys.readouterr().out)["signatures"][0]["content"] == SIG_A["content"]


def test_cli_signature_show_includes_the_content(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, SignatureAPI())

    assert cli.main(["admin", "mailbox", "signature", "show", "user", "11", "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["signature"]["content"] == SIG_A["content"]


def test_cli_signature_show_unknown_id_names_the_list_command(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, SignatureAPI())

    assert cli.main(["admin", "mailbox", "signature", "show", "user", "999", "--json"]) == 1

    assert "signature list" in capsys.readouterr().err


def test_cli_signature_create_sends_only_given_fields(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "create", "user", "--name", "New",
        "--content", "Body", "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["created"] is True
    assert output["confirmed"] is True
    assert output["notified"] is False
    path, body = api.posts[0]
    assert path == "/1/mail_hostings/111/mailboxes/user/signatures"
    assert body == {"name": "New", "content": "Body"}


def test_cli_signature_create_reads_a_content_file(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)
    body_file = tmp_path / "sig.html"
    body_file.write_text("<p>Example</p>", encoding="utf-8")

    assert cli.main([
        "admin", "mailbox", "signature", "create", "user", "--name", "Filed",
        "--content-file", str(body_file), "--yes", "--profile", "work", "--json",
    ]) == 0

    assert api.posts[0][1]["content"] == "<p>Example</p>"


def test_cli_signature_create_missing_content_file_is_actionable(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "create", "user", "--name", "X",
        "--content-file", str(tmp_path / "missing.html"), "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "not found" in capsys.readouterr().err
    assert api.posts == []


def test_cli_signature_update_patches_only_what_changed(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "update", "user", "11", "--name", "Renamed",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["updated"] is True
    assert output["confirmed"] is True
    assert output["fields_sent"] == ["name"]
    path, body = api.patches[0]
    assert path == "/1/mail_hostings/111/mailboxes/user/signatures/11"
    assert body == {"name": "Renamed"}  # content/position untouched


def test_cli_signature_update_refuses_when_nothing_was_passed(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "update", "user", "11",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "Nothing to update" in capsys.readouterr().err
    assert api.patches == []


def test_cli_signature_update_footer_flags_are_mutually_exclusive(tmp_path, monkeypatch):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, SignatureAPI())

    with pytest.raises(SystemExit) as excinfo:
        cli.main([
            "admin", "mailbox", "signature", "update", "user", "11",
            "--footer", "--no-footer", "--profile", "work",
        ])

    assert excinfo.value.code == 2


def test_cli_signature_delete_refuses_a_current_default(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI(default_id=11)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "delete", "user", "11",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    err = capsys.readouterr().err
    assert "currently a default" in err
    assert api.deletes == []


def test_cli_signature_delete_of_a_default_needs_force(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI(default_id=11)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "delete", "user", "11", "--force-default",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["deleted"] is True
    assert output["was_default"] is True
    assert output["confirmed_gone"] is True
    assert api.deletes == ["/1/mail_hostings/111/mailboxes/user/signatures/11"]


def test_cli_signature_delete_non_default_needs_no_force(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI(default_id=11)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "delete", "user", "22",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["confirmed_gone"] is True


def test_cli_signature_set_default_requires_a_target(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "set-default", "user",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "--send" in capsys.readouterr().err
    assert api.posts == []


def test_cli_signature_set_default_posts_and_reads_back(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI(default_id=11)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "set-default", "user", "--send", "22", "--reply", "11",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["confirmed"] is True
    assert output["after"] == {"default_signature_id": 22, "default_reply_signature_id": 11}
    assert api.posts[0][1] == {"default_signature_id": 22, "default_reply_signature_id": 11}


def test_cli_signature_set_default_rejects_an_unknown_id(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "set-default", "user", "--send", "999",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "No signature with id 999" in capsys.readouterr().err
    assert api.posts == []


@pytest.mark.parametrize(
    "argv",
    [
        ["admin", "mailbox", "signature", "create", "user", "--name", "X"],
        ["admin", "mailbox", "signature", "update", "user", "11", "--name", "X"],
        ["admin", "mailbox", "signature", "delete", "user", "22"],
        ["admin", "mailbox", "signature", "set-default", "user", "--send", "22"],
    ],
)
def test_cli_signature_writes_dry_run_never_writes(argv, tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)

    assert cli.main([*argv, "--dry-run", "--profile", "work", "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["dry_run"] is True
    assert api.posts == [] and api.patches == [] and api.deletes == []


@pytest.mark.parametrize(
    "argv",
    [
        ["admin", "mailbox", "signature", "create", "user", "--name", "X"],
        ["admin", "mailbox", "signature", "update", "user", "11", "--name", "X"],
        ["admin", "mailbox", "signature", "delete", "user", "22"],
        ["admin", "mailbox", "signature", "set-default", "user", "--send", "22"],
    ],
)
def test_cli_signature_writes_require_an_explicit_profile_for_yes(argv, tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    assert cli.main([*argv, "--yes", "--json"]) == 1

    assert "explicit" in capsys.readouterr().err
    assert api.posts == [] and api.patches == [] and api.deletes == []


def test_cli_signature_list_warns_when_a_forced_policy_applies(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, SignatureAPI(is_forced=True))

    assert cli.main(["admin", "mailbox", "signature", "list", "user"]) == 0

    assert "forced signature policy" in capsys.readouterr().out


# --- P3 review regressions: server-side normalization must not turn a good
# write into a reported failure, and undocumented API behaviour must be detected.


class NormalizingAPI(SignatureAPI):
    """Server that trims names, wraps bodies, and echoes booleans as strings."""

    def post(self, path, json=None):
        if not path.endswith("/set_defaults") and "name" in (json or {}):
            json = {**json, "name": json["name"].strip()}
        return super().post(path, json)

    def request(self, method, path, *, params=None, json=None, **kwargs):
        if json and "content" in json:
            json = {**json, "content": json["content"] + "\n<!-- wrapped -->"}
        if json and "has_infomaniak_footer" in json:
            json = {**json, "has_infomaniak_footer": "1" if json["has_infomaniak_footer"] else "0"}
        return super().request(method, path, params=params, json=json, **kwargs)


def test_create_identifies_the_new_signature_by_id_not_name(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = NormalizingAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "create", "user", "--name", "Trailing ",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["confirmed"] is True
    assert output["signature_id"] is not None


def test_update_confirms_despite_a_wrapped_body(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = NormalizingAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "update", "user", "11", "--content", "New body",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["confirmed"] is True


def test_update_confirms_despite_a_string_boolean(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = NormalizingAPI()
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "update", "user", "11", "--no-footer",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert json.loads(capsys.readouterr().out)["confirmed"] is True


def test_update_reports_defaults_accurately_in_before_and_after(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, SignatureAPI(default_id=11))

    assert cli.main([
        "admin", "mailbox", "signature", "update", "user", "11", "--name", "Renamed",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["before"]["is_default_send"] is True
    assert output["after"]["is_default_send"] is True


def test_set_default_detects_an_omitted_pointer_being_cleared(tmp_path, monkeypatch, capsys):
    """The API's behaviour for an omitted pointer is undocumented; detect it."""
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")

    class ClearingAPI(SignatureAPI):
        def post(self, path, json=None):
            result = super().post(path, json)
            if path.endswith("/set_defaults") and "default_reply_signature_id" not in json:
                self.reply_id = None  # server clears what was not sent
            return result

    api = ClearingAPI(default_id=11, reply_id=22)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "set-default", "user", "--send", "22",
        "--yes", "--profile", "work", "--json",
    ]) == 1

    captured = capsys.readouterr()
    assert "clear omitted" in captured.err
    assert json.loads(captured.out)["untouched_defaults_kept"] is False


def test_set_default_tolerates_a_non_numeric_signature_id(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI([{"id": "sig-abc", "name": "Odd", "content": "x"}], default_id=None)
    _install(monkeypatch, api)

    assert cli.main([
        "admin", "mailbox", "signature", "set-default", "user", "--send", "sig-abc",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    assert api.posts[0][1]["default_signature_id"] == "sig-abc"


def test_create_warns_when_set_default_did_not_take_effect(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")

    class IgnoresDefaultAPI(SignatureAPI):
        def post(self, path, json=None):
            payload = super().post(path, json)
            self.default_id = 11  # server ignored is_default on create
            return payload

    _install(monkeypatch, IgnoresDefaultAPI(default_id=11))

    assert cli.main([
        "admin", "mailbox", "signature", "create", "user", "--name", "New", "--set-default",
        "--yes", "--profile", "work", "--json",
    ]) == 0

    captured = capsys.readouterr()
    assert "did not become the default" in captured.err
    assert json.loads(captured.out)["default_confirmed"] is False


def test_unreadable_content_file_is_actionable(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = SignatureAPI()
    _install(monkeypatch, api)
    binary = tmp_path / "sig.bin"
    binary.write_bytes(b"\xff\xfe\x00invalid utf8")

    assert cli.main([
        "admin", "mailbox", "signature", "create", "user", "--name", "X",
        "--content-file", str(binary), "--yes", "--profile", "work", "--json",
    ]) == 1

    assert "Could not read signature content file" in capsys.readouterr().err
    assert api.posts == []
