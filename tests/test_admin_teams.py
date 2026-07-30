"""Offline tests for `ik admin teams` and honest paginated counts (0.3.3)."""

import json

from infomaniak_cli import cli
from infomaniak_cli.services.admin import page_info, slim_admin_team

from test_admin import FakeAPI, _install, _setup_profile

RAW_TEAM = {
    "id": 5,
    "name": "Example Team",
    "description": "Example description",
    "parent_id": None,
    "children": [{"id": 6}, {"id": 7}],
    "owned_by_id": 42,
    "position": 1,
    "color_id": 3,
    "is_sso": False,
    "created_at": 1750000000,
    "updated_at": 1750000001,
}


def _teams_payload(items, **envelope):
    return {"result": "success", "data": items, **envelope}


def test_slim_admin_team_counts_children():
    assert slim_admin_team(RAW_TEAM) == {
        "id": 5,
        "name": "Example Team",
        "description": "Example description",
        "parent_id": None,
        "children": 2,
        "owned_by_id": 42,
        "position": 1,
    }
    assert slim_admin_team({"id": 1})["children"] == 0


def test_page_info_extracts_or_nulls():
    assert page_info({"total": 6, "page": 1, "pages": 1, "items_per_page": 25}) == {
        "total": 6,
        "page": 1,
        "pages": 1,
        "items_per_page": 25,
    }
    assert page_info({"result": "success", "data": []}) == {
        "total": None,
        "page": None,
        "pages": None,
        "items_per_page": None,
    }
    assert page_info("not a mapping")["total"] is None


def test_cli_admin_teams_json_slims_and_reports_counts(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(
        monkeypatch,
        FakeAPI({"/1/accounts/42/teams": _teams_payload([RAW_TEAM], total=1, page=1, pages=1, items_per_page=25)}),
    )

    assert cli.main(["admin", "teams", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["teams"] == [slim_admin_team(RAW_TEAM)]
    assert output["count"] == 1
    assert output["total"] == 1
    assert output["complete"] is True


def test_cli_admin_teams_raw_and_table(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(monkeypatch, FakeAPI({"/1/accounts/42/teams": _teams_payload([RAW_TEAM], total=1)}))
    assert cli.main(["admin", "teams", "--json", "--raw"]) == 0
    assert json.loads(capsys.readouterr().out)["teams"] == [RAW_TEAM]

    _install(monkeypatch, FakeAPI({"/1/accounts/42/teams": _teams_payload([], total=0)}))
    assert cli.main(["admin", "teams", "--table"]) == 0
    assert "Team" in capsys.readouterr().out  # header renders when empty


def test_cli_admin_teams_reports_a_partial_page_honestly(tmp_path, monkeypatch, capsys):
    """A first-page count presented as the whole inventory would be a lie."""
    _setup_profile(tmp_path, monkeypatch)
    _install(
        monkeypatch,
        FakeAPI({"/1/accounts/42/teams": _teams_payload([RAW_TEAM], total=40, page=1, pages=2, items_per_page=25)}),
    )

    assert cli.main(["admin", "teams", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 1
    assert output["total"] == 40
    assert output["complete"] is False


def test_cli_admin_teams_human_output_says_it_is_showing_one_page(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(
        monkeypatch,
        FakeAPI({"/1/accounts/42/teams": _teams_payload([RAW_TEAM], total=40, page=1, pages=2, items_per_page=25)}),
    )

    assert cli.main(["admin", "teams"]) == 0

    out = capsys.readouterr().out
    assert "Showing 1 of 40 teams" in out
    assert "paginates" in out


def test_cli_admin_mailbox_list_reports_pagination_totals(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    mailbox = {"mailbox": "user@example.com", "mailbox_name": "user", "type": "mailbox"}
    _install(
        monkeypatch,
        FakeAPI({
            "/1/mail_hostings/111/mailboxes": _teams_payload([mailbox], total=9, page=1, pages=2, items_per_page=1),
        }),
    )

    assert cli.main(["admin", "mailbox", "list", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 1
    assert output["total"] == 9
    assert output["complete"] is False


def test_non_paginated_endpoints_report_complete_with_null_total(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    user = {"user_id": 7, "email": "user@example.com"}
    _install(monkeypatch, FakeAPI({"/2/accounts/42/users": {"result": "success", "data": [user]}}))

    assert cli.main(["admin", "users", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 1
    assert output["total"] is None
    assert output["complete"] is True


def test_cli_admin_teams_table_also_says_it_is_showing_one_page(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(
        monkeypatch,
        FakeAPI({"/1/accounts/42/teams": _teams_payload([RAW_TEAM], total=40, page=1, pages=2, items_per_page=25)}),
    )

    assert cli.main(["admin", "teams", "--table"]) == 0

    assert "Showing 1 of 40 teams" in capsys.readouterr().out


def test_cli_admin_mailbox_list_human_output_says_it_is_showing_one_page(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch, mail_hosting_id="111")
    mailbox = {"mailbox": "user@example.com", "mailbox_name": "user", "type": "mailbox"}
    _install(
        monkeypatch,
        FakeAPI({
            "/1/mail_hostings/111/mailboxes": _teams_payload([mailbox], total=9, page=1, pages=2, items_per_page=1),
        }),
    )

    assert cli.main(["admin", "mailbox", "list"]) == 0

    assert "Showing 1 of 9 mailboxes" in capsys.readouterr().out


def test_machine_output_never_contains_the_human_note(tmp_path, monkeypatch, capsys):
    """The note on stdout would break every consumer's json.loads."""
    _setup_profile(tmp_path, monkeypatch)
    _install(
        monkeypatch,
        FakeAPI({"/1/accounts/42/teams": _teams_payload([RAW_TEAM], total=40, page=1, pages=2, items_per_page=25)}),
    )

    assert cli.main(["admin", "teams", "--compact"]) == 0

    out = capsys.readouterr().out
    assert "Showing" not in out
    assert json.loads(out)["complete"] is False


def test_counts_survive_a_malformed_total(tmp_path, monkeypatch, capsys):
    """A list command must never traceback on a field it merely reports."""
    _setup_profile(tmp_path, monkeypatch)
    for bad_total in ("x", {}, [], None):
        _install(
            monkeypatch,
            FakeAPI({"/1/accounts/42/teams": _teams_payload([RAW_TEAM], total=bad_total)}),
        )
        assert cli.main(["admin", "teams", "--json"]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["total"] is None
        assert output["complete"] is True


def test_pages_greater_than_one_marks_incomplete_even_without_total(tmp_path, monkeypatch, capsys):
    _setup_profile(tmp_path, monkeypatch)
    _install(monkeypatch, FakeAPI({"/1/accounts/42/teams": _teams_payload([RAW_TEAM], pages=3)}))

    assert cli.main(["admin", "teams", "--json"]) == 0

    assert json.loads(capsys.readouterr().out)["complete"] is False
