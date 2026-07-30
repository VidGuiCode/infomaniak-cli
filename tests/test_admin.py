"""Offline tests for the read-only `ik admin` Manager inventory group (0.3.0)."""

import json

import pytest

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIError
from infomaniak_cli.auth import TokenStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.admin import (
    add_mailbox_alias,
    alias_local_part,
    delete_mailbox_alias,
    get_account_admin,
    get_mailbox_admin,
    list_account_users,
    list_mail_hostings_admin,
    mailbox_key,
    slim_account_overview,
    slim_admin_hosting,
    slim_admin_mailbox,
    slim_admin_user,
    slim_aliases,
    slim_forwarding,
    summarize_signatures,
)


class FakeAPI:
    """Path -> envelope map; a value that is an Exception is raised instead."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        try:
            response = self.responses[path]
        except KeyError:
            raise InformaniakAPIError(404, f"GET {path} failed: not found")
        if isinstance(response, Exception):
            raise response
        return response


RAW_USER = {
    "user_id": 7,
    "email": "user@example.com",
    "display_name": "Example User",
    "first_name": "Example",
    "last_name": "User",
    "role_type": "admin",
    "state_in_account": "active",
    "user_status": "active",
    "has_billing_access": True,
    "has_no_manager_access": False,
    "is_workspace_only": False,
    "invitation_id": None,
    "last_login_at": 1750000000,
}

RAW_HOSTING = {
    "id": 111,
    "account_id": 42,
    "customer_name": "example.com",
    "main_fqdn": "example.com",
    "service_name": "email_hosting",
    "service_id": 23,
    "is_locked": False,
    "dns_error": False,
    "rights": {"read": True},
}

RAW_MAILBOX = {
    "mailbox": "user@example.com",
    "mailbox_name": "user",
    "mailbox_idn": "user@example.com",
    "type": "mailbox",
    "is_limited": False,
    "is_free_mail": False,
    "is_used_for_account": True,
    "note": None,
}


def _setup_profile(tmp_path, monkeypatch, **metadata):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", account_id="42", make_default=True, **metadata)
    TokenStore().save_token("work", "secret-token")


def _install(monkeypatch, fake_api):
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)


# --- service layer ---


def test_service_functions_hit_the_confirmed_endpoints():
    api = FakeAPI(
        {
            "/1/accounts/42": {"result": "success", "data": {"id": 42, "name": "Example Co", "nb_users": 3}},
            "/2/accounts/42/users": {"result": "success", "data": [RAW_USER]},
            "/1/mail_hostings": {"result": "success", "data": [RAW_HOSTING]},
            "/1/mail_hostings/111/mailboxes/user": {"result": "success", "data": RAW_MAILBOX},
        }
    )

    assert get_account_admin(api, "42") == {"id": 42, "name": "Example Co", "nb_users": 3}
    assert list_account_users(api, "42") == [RAW_USER]
    assert list_mail_hostings_admin(api) == [RAW_HOSTING]
    assert get_mailbox_admin(api, "111", "user") == RAW_MAILBOX
    assert api.calls == [
        ("/1/accounts/42", None),
        ("/2/accounts/42/users", None),
        ("/1/mail_hostings", None),
        ("/1/mail_hostings/111/mailboxes/user", None),
    ]


def test_mailbox_key_accepts_local_part_or_full_address():
    assert mailbox_key("user") == "user"
    assert mailbox_key("user@example.com") == "user"


def test_mailbox_key_rejects_empty_names():
    import pytest

    with pytest.raises(ValueError):
        mailbox_key("")
    with pytest.raises(ValueError):
        mailbox_key("@example.com")


def test_mailbox_requests_percent_encode_hostile_path_segments():
    """A caller-supplied name must never extend or redirect the request path."""
    api = FakeAPI(
        {
            "/1/mail_hostings/111/mailboxes/..%2F..%2F..%2F2%2Fprofile": {
                "result": "success",
                "data": RAW_MAILBOX,
            }
        }
    )

    assert get_mailbox_admin(api, "111", "../../../2/profile") == RAW_MAILBOX
    assert api.calls == [("/1/mail_hostings/111/mailboxes/..%2F..%2F..%2F2%2Fprofile", None)]


def test_slim_account_overview_and_aliases_projections():
    assert slim_account_overview({"id": 42, "name": "Example Co", "nb_users": 3, "phone": "x"}) == {
        "id": 42,
        "name": "Example Co",
        "nb_users": 3,
    }
    assert slim_aliases({"aliases": ["a"], "enabled_alias": True}) == {"aliases": ["a"], "enabled_alias": True}
    assert slim_aliases({}) == {"aliases": [], "enabled_alias": None}


def test_slim_admin_user_projects_role_fields():
    assert slim_admin_user(RAW_USER) == {
        "user_id": 7,
        "email": "user@example.com",
        "display_name": "Example User",
        "role_type": "admin",
        "state_in_account": "active",
        "user_status": "active",
        "has_billing_access": True,
        "is_workspace_only": False,
        "last_login_at": 1750000000,
    }


def test_slim_admin_hosting_and_mailbox_projections():
    assert slim_admin_hosting(RAW_HOSTING) == {
        "id": 111,
        "customer_name": "example.com",
        "main_fqdn": "example.com",
        "service_name": "email_hosting",
        "is_locked": False,
        "dns_error": False,
    }
    assert slim_admin_mailbox(RAW_MAILBOX) == {
        "mailbox": "user@example.com",
        "mailbox_name": "user",
        "type": "mailbox",
        "is_limited": False,
        "is_free_mail": False,
        "is_used_for_account": True,
    }


def test_slim_forwarding_normalizes_the_api_spelling():
    raw = {
        "is_enabled": True,
        "redirect_adresses": ["other@example.com"],
        "has_dont_deliver": False,
        "has_forward_spam": False,
    }

    assert slim_forwarding(raw) == {
        "is_enabled": True,
        "redirect_addresses": ["other@example.com"],
        "has_dont_deliver": False,
        "has_forward_spam": False,
    }
    # already-correct spelling passes through
    assert slim_forwarding({"redirect_addresses": []})["redirect_addresses"] == []


def test_summarize_signatures_reports_counts_never_bodies():
    raw = {
        "signatures": [{"id": 1, "content": "<p>private</p>"}, {"id": 2, "content": "x"}],
        "default_signature_id": 1,
        "default_reply_signature_id": None,
        "is_forced": False,
    }

    summary = summarize_signatures(raw)

    assert summary == {
        "count": 2,
        "default_signature_id": 1,
        "default_reply_signature_id": None,
        "is_forced": False,
    }
    assert "private" not in json.dumps(summary)


# --- admin users ---


def test_cli_admin_users_json_slims(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(monkeypatch, FakeAPI({"/2/accounts/42/users": {"result": "success", "data": [RAW_USER]}}))

    assert cli.main(["admin", "users", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["account_id"] == "42"
    assert output["count"] == 1
    assert output["users"] == [slim_admin_user(RAW_USER)]


def test_cli_admin_users_raw_emits_full_payload(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(monkeypatch, FakeAPI({"/2/accounts/42/users": {"result": "success", "data": [RAW_USER]}}))

    assert cli.main(["admin", "users", "--json", "--raw"]) == 0

    assert json.loads(capsys.readouterr().out)["users"] == [RAW_USER]


def test_cli_admin_users_table_and_empty(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(monkeypatch, FakeAPI({"/2/accounts/42/users": {"result": "success", "data": []}}))

    assert cli.main(["admin", "users", "--table"]) == 0

    out = capsys.readouterr().out
    assert "Email" in out  # header renders even when empty


# --- admin status ---


def test_cli_admin_status_reports_readable_admin_surfaces(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(
        monkeypatch,
        FakeAPI(
            {
                "/1/accounts/42": {"result": "success", "data": {"id": 42, "name": "Example Co", "nb_users": 3}},
                "/2/accounts/42/users": {"result": "success", "data": [RAW_USER]},
                "/1/mail_hostings": {"result": "success", "data": [RAW_HOSTING]},
            }
        ),
    )

    assert cli.main(["admin", "status", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["admin_read_access"] is True
    assert output["users"] == {"readable": True, "count": 1}
    assert output["mail_hostings"] == {"readable": True, "count": 1}
    assert output["account"] == {"id": 42, "name": "Example Co", "nb_users": 3}
    assert output["writes"] == "none"


def test_cli_admin_status_degrades_on_forbidden_not_crashes(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(
        monkeypatch,
        FakeAPI(
            {
                "/1/accounts/42": {"result": "success", "data": {"id": 42, "name": "Example Co", "nb_users": 3}},
                "/2/accounts/42/users": InformaniakAPIError(403, "GET /2/accounts/42/users failed: forbidden"),
                "/1/mail_hostings": InformaniakAPIError(403, "GET /1/mail_hostings failed: forbidden"),
            }
        ),
    )

    assert cli.main(["admin", "status", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["admin_read_access"] is False
    assert output["users"] == {"readable": False, "error_status": 403}
    assert output["mail_hostings"] == {"readable": False, "error_status": 403}


def test_cli_admin_status_human_output_shows_counts_not_user_emails(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(
        monkeypatch,
        FakeAPI(
            {
                "/1/accounts/42": {"result": "success", "data": {"id": 42, "name": "Example Co", "nb_users": 3}},
                "/2/accounts/42/users": {"result": "success", "data": [RAW_USER]},
                "/1/mail_hostings": {"result": "success", "data": [RAW_HOSTING]},
            }
        ),
    )

    assert cli.main(["admin", "status"]) == 0

    out = capsys.readouterr().out
    assert "user@example.com" not in out
    assert "read-only" in out


# --- admin hostings ---


def test_cli_admin_hostings_json_slims(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(monkeypatch, FakeAPI({"/1/mail_hostings": {"result": "success", "data": [RAW_HOSTING]}}))

    assert cli.main(["admin", "hostings", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["hostings"] == [slim_admin_hosting(RAW_HOSTING)]
    assert output["count"] == 1


# --- admin mailbox list ---


def test_cli_admin_mailbox_list_uses_profile_hosting(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(
        monkeypatch,
        FakeAPI({"/1/mail_hostings/111/mailboxes": {"result": "success", "data": [RAW_MAILBOX]}}),
    )

    assert cli.main(["admin", "mailbox", "list", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mail_hosting_id"] == "111"
    assert output["mailboxes"] == [slim_admin_mailbox(RAW_MAILBOX)]


def test_cli_admin_mailbox_list_auto_selects_single_discovered_hosting(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)  # no mail_hosting_id saved
    _install(
        monkeypatch,
        FakeAPI(
            {
                "/1/mail_hostings": {"result": "success", "data": [RAW_HOSTING]},
                "/1/mail_hostings/111/mailboxes": {"result": "success", "data": [RAW_MAILBOX]},
            }
        ),
    )

    assert cli.main(["admin", "mailbox", "list", "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["mail_hosting_id"] == "111"


def test_cli_admin_mailbox_list_refuses_to_guess_between_hostings(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    second = dict(RAW_HOSTING, id=222, customer_name="example.org", main_fqdn="example.org")
    _install(
        monkeypatch,
        FakeAPI({"/1/mail_hostings": {"result": "success", "data": [RAW_HOSTING, second]}}),
    )

    assert cli.main(["admin", "mailbox", "list"]) == 1

    err = capsys.readouterr().err
    assert "--hosting-id" in err
    assert "111" in err and "222" in err


def test_cli_admin_mailbox_list_explicit_hosting_id_wins(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(
        monkeypatch,
        FakeAPI({"/1/mail_hostings/222/mailboxes": {"result": "success", "data": []}}),
    )

    assert cli.main(["admin", "mailbox", "list", "--hosting-id", "222", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mail_hosting_id"] == "222"
    assert output["mailboxes"] == []


# --- admin mailbox show ---


def _show_api():
    return FakeAPI(
        {
            "/1/mail_hostings/111/mailboxes/user": {"result": "success", "data": RAW_MAILBOX},
            "/1/mail_hostings/111/mailboxes/user/aliases": {
                "result": "success",
                "data": {"aliases": ["alias1"], "enabled_alias": True},
            },
            "/1/mail_hostings/111/mailboxes/user/forwarding_addresses": {
                "result": "success",
                "data": {
                    "is_enabled": False,
                    "redirect_adresses": [],
                    "has_dont_deliver": False,
                    "has_forward_spam": False,
                },
            },
            "/1/mail_hostings/111/mailboxes/user/signatures": {
                "result": "success",
                "data": {
                    "signatures": [{"id": 1, "content": "body"}],
                    "default_signature_id": 1,
                    "default_reply_signature_id": None,
                    "is_forced": False,
                },
            },
        }
    )


def test_cli_admin_mailbox_show_merges_all_admin_reads(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, _show_api())

    assert cli.main(["admin", "mailbox", "show", "user", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mailbox"] == slim_admin_mailbox(RAW_MAILBOX)
    assert output["aliases"] == {"aliases": ["alias1"], "enabled_alias": True}
    assert output["forwarding"]["redirect_addresses"] == []
    assert output["signatures"]["count"] == 1
    assert "content" not in json.dumps(output)


def test_cli_admin_mailbox_show_accepts_full_address(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, _show_api())

    assert cli.main(["admin", "mailbox", "show", "user@example.com", "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["mailbox_name"] == "user"


def test_cli_admin_mailbox_show_unknown_names_the_list_command(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, FakeAPI({}))

    assert cli.main(["admin", "mailbox", "show", "ghost"]) == 1

    err = capsys.readouterr().err
    assert "ghost" in err
    assert "admin mailbox list" in err


def test_cli_admin_mailbox_show_raw_keeps_upstream_payloads(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    _install(monkeypatch, _show_api())

    assert cli.main(["admin", "mailbox", "show", "user", "--json", "--raw"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["mailbox"] == RAW_MAILBOX
    assert output["forwarding"]["redirect_adresses"] == []
    assert output["signatures"]["signatures"][0]["content"] == "body"


# --- admin mailbox alias add/remove (0.3.1, first admin write) ---
# The generic protected-write contract for these lives in
# tests/test_write_contract.py; admin left READ_ONLY_GROUPS deliberately there.


class AliasWriteAPI(FakeAPI):
    """Stateful fake: GET reflects the alias list, POST/DELETE mutate it."""

    def __init__(self, aliases):
        super().__init__({})
        self.state = list(aliases)
        self.posts = []
        self.deletes = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        if path.endswith("/aliases"):
            return {"result": "success", "data": {"aliases": list(self.state), "enabled_alias": True}}
        if path == "/1/mail_hostings/111":
            return {"result": "success", "data": RAW_HOSTING}
        raise InformaniakAPIError(404, f"GET {path} failed: not found")

    def post(self, path, json=None):
        self.posts.append((path, json))
        self.state.append(json["alias"])
        return {"result": "success", "data": True}

    def delete(self, path, params=None):
        self.deletes.append(path)
        alias = path.rsplit("/", 1)[-1]
        if alias in self.state:
            self.state.remove(alias)
        return {"result": "success", "data": True}


def test_alias_service_functions_use_documented_paths_and_quote_segments():
    api = AliasWriteAPI([])

    add_mailbox_alias(api, "111", "user", "sales")
    delete_mailbox_alias(api, "111", "user", "sa les")

    assert api.posts == [("/1/mail_hostings/111/mailboxes/user/aliases", {"alias": "sales"})]
    assert api.deletes == ["/1/mail_hostings/111/mailboxes/user/aliases/sa%20les"]


def test_quote_refuses_dot_segments():
    from infomaniak_cli.services.admin import _quote

    for bad in ("", ".", ".."):
        with pytest.raises(ValueError):
            _quote(bad)


def test_alias_local_part_validation():
    assert alias_local_part(" sales ") == "sales"
    with pytest.raises(ValueError):
        alias_local_part("")
    with pytest.raises(ValueError):
        alias_local_part("sales@example.com")
    with pytest.raises(ValueError):
        alias_local_part("sa les")
    with pytest.raises(ValueError):
        alias_local_part("a/b")


def test_cli_alias_matching_is_case_insensitive_on_add(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = AliasWriteAPI(["Sales"])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "alias", "add", "user", "sales", "--yes", "--profile", "work", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["added"] is False
    assert output["existed"] is True
    assert output["server_spelling"] == "Sales"
    assert api.posts == []


def test_cli_alias_remove_targets_the_server_spelling(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = AliasWriteAPI(["Sales"])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "alias", "remove", "user", "sales", "--yes", "--profile", "work", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["removed"] is True
    assert output["confirmed_absent"] is True
    assert api.deletes == ["/1/mail_hostings/111/mailboxes/user/aliases/Sales"]


def test_cli_alias_add_writes_reads_back_and_diffs(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = AliasWriteAPI(["old"])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "alias", "add", "user", "sales", "--yes", "--profile", "work", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["added"] is True
    assert output["notified"] is False
    assert output["confirmed_present"] is True
    assert output["aliases_before"] == ["old"]
    assert sorted(output["aliases_after"]) == ["old", "sales"]
    assert "aliases" in output["changed"]
    assert len(api.posts) == 1


def test_cli_alias_remove_writes_and_confirms_absent(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = AliasWriteAPI(["old", "sales"])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "alias", "remove", "user", "sales", "--yes", "--profile", "work", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["removed"] is True
    assert output["confirmed_absent"] is True
    assert output["aliases_after"] == ["old"]
    assert api.deletes == ["/1/mail_hostings/111/mailboxes/user/aliases/sales"]


def test_cli_alias_add_existing_is_a_reported_noop(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = AliasWriteAPI(["sales"])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "alias", "add", "user", "sales", "--yes", "--profile", "work", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["added"] is False
    assert output["existed"] is True
    assert api.posts == []


def test_cli_alias_remove_absent_is_a_reported_noop(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = AliasWriteAPI(["old"])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "alias", "remove", "user", "ghost", "--yes", "--profile", "work", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["removed"] is False
    assert output["existed"] is False
    assert api.deletes == []


def test_cli_alias_add_dry_run_never_posts(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = AliasWriteAPI(["old"])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "alias", "add", "user", "sales", "--dry-run", "--profile", "work", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["added"] is False
    assert output["changed"]["aliases"]["after"] == ["old", "sales"]
    assert api.posts == []
    assert api.state == ["old"]


def test_cli_alias_yes_requires_explicit_profile(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = AliasWriteAPI([])
    _install(monkeypatch, api)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    assert cli.main(["admin", "mailbox", "alias", "add", "user", "sales", "--yes", "--json"]) == 1

    assert "explicit" in capsys.readouterr().err
    assert api.posts == []


def test_cli_alias_full_address_alias_is_refused(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    api = AliasWriteAPI([])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "alias", "add", "user", "sales@example.com", "--yes", "--profile", "work", "--json"]) == 1

    assert "local part" in capsys.readouterr().err
    assert api.posts == []


def test_cli_alias_without_yes_never_writes_under_automation(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    monkeypatch.setenv("IK_NO_INTERACTIVE", "1")
    api = AliasWriteAPI(["old"])
    _install(monkeypatch, api)

    assert cli.main(["admin", "mailbox", "alias", "add", "user", "sales", "--profile", "work"]) == 1

    assert api.posts == []
    assert api.state == ["old"]
