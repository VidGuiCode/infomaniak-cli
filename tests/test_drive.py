import json

import pytest

from infomaniak_cli import cli
from infomaniak_cli.api import InformaniakAPIError
from infomaniak_cli.auth import TokenStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.drive import DriveError, list_files, slim_file


class FakeAPI:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        response = self.responses[path]
        if isinstance(response, Exception):
            raise response
        return response


def test_drive_service_lists_files_from_standard_envelope():
    api = FakeAPI(
        {
            "/2/drive/drive-1/files": {
                "result": "success",
                "data": [
                    {"id": "folder-1", "name": "Admin", "type": "dir", "size": 0, "extra": "kept-in-raw"},
                    {"id": "file-1", "name": "Invoice.pdf", "type": "file", "size": 1234},
                ],
            }
        }
    )

    files = list_files(api, "drive-1")

    assert files == [
        {"id": "folder-1", "name": "Admin", "type": "dir", "size": 0, "extra": "kept-in-raw"},
        {"id": "file-1", "name": "Invoice.pdf", "type": "file", "size": 1234},
    ]
    assert api.calls == [("/2/drive/drive-1/files", None)]


def test_drive_service_passes_parent_and_limit_params():
    api = FakeAPI({"/2/drive/drive-1/files": {"result": "success", "data": []}})

    assert list_files(api, "drive-1", parent_id="folder-1", limit=25) == []

    assert api.calls == [("/2/drive/drive-1/files", {"parent_id": "folder-1", "limit": 25})]


def test_drive_service_error_envelope_is_readable_and_redacted():
    api = FakeAPI(
        {
            "/2/drive/drive-1/files": {
                "result": "error",
                "error": {"message": "token=secret-token lacks scope"},
            }
        }
    )

    with pytest.raises(DriveError) as exc_info:
        list_files(api, "drive-1")

    assert "kDrive files request failed" in str(exc_info.value)
    assert "secret-token" not in str(exc_info.value)
    assert "token=***" in str(exc_info.value)


def test_drive_service_missing_envelope_is_readable():
    api = FakeAPI({"/2/drive/drive-1/files": {"unexpected": "shape"}})

    with pytest.raises(DriveError) as exc_info:
        list_files(api, "drive-1")

    assert "Unexpected kDrive files response" in str(exc_info.value)


def test_slim_file_projects_useful_fields_only():
    raw = {
        "id": "file-1",
        "name": "Invoice.pdf",
        "type": "file",
        "size": 1234,
        "created_at": 1,
        "updated_at": 2,
        "permissions": {"share": True},
    }

    assert slim_file(raw) == {
        "id": "file-1",
        "name": "Invoice.pdf",
        "type": "file",
        "size": 1234,
        "created_at": 1,
        "updated_at": 2,
    }


def test_cli_drive_list_json_uses_profile_default_drive_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", default_drive_id="drive-1", make_default=True)
    TokenStore().save_token("cylro", "secret-token")
    fake_api = FakeAPI(
        {
            "/2/drive/drive-1/files": {
                "result": "success",
                "data": [
                    {
                        "id": "folder-1",
                        "name": "Admin",
                        "type": "dir",
                        "size": 0,
                        "created_at": 1,
                        "updated_at": 2,
                        "raw_only": True,
                    }
                ],
            }
        }
    )
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["drive", "list", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "profile": "cylro",
        "drive_id": "drive-1",
        "parent_id": None,
        "files": [
            {"id": "folder-1", "name": "Admin", "type": "dir", "size": 0, "created_at": 1, "updated_at": 2}
        ],
    }
    assert fake_api.calls == [("/2/drive/drive-1/files", None)]


def test_cli_drive_list_json_raw_emits_full_payload(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", default_drive_id="drive-1", make_default=True)
    TokenStore().save_token("cylro", "secret-token")
    raw_file = {"id": "folder-1", "name": "Admin", "type": "dir", "permissions": {"share": True}}
    fake_api = FakeAPI({"/2/drive/drive-1/files": {"result": "success", "data": [raw_file]}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["drive", "list", "--json", "--raw"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"profile": "cylro", "drive_id": "drive-1", "parent_id": None, "files": [raw_file]}


def test_cli_drive_list_honors_drive_id_override(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", default_drive_id="profile-drive", make_default=True)
    TokenStore().save_token("cylro", "secret-token")
    fake_api = FakeAPI({"/2/drive/override-drive/files": {"result": "success", "data": []}})
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["drive", "list", "--drive-id", "override-drive", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["drive_id"] == "override-drive"
    assert fake_api.calls == [("/2/drive/override-drive/files", None)]


def test_cli_drive_list_requires_drive_id(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", make_default=True)
    TokenStore().save_token("cylro", "secret-token")

    assert cli.main(["drive", "list"]) == 1

    captured = capsys.readouterr()
    assert "No default kDrive selected for profile: cylro" in captured.err
    assert "Run `ik --profile cylro bootstrap`" in captured.err
    assert "--drive-id" in captured.err


def test_cli_drive_list_redacts_api_errors(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", default_drive_id="drive-1", make_default=True)
    TokenStore().save_token("cylro", "secret-token")
    fake_api = FakeAPI(
        {
            "/2/drive/drive-1/files": InformaniakAPIError(
                500,
                "GET /2/drive/drive-1/files failed: token=secret-token backend error",
                secrets=["secret-token"],
            )
        }
    )
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["drive", "list", "--json"]) == 1

    captured = capsys.readouterr()
    assert "backend error" in captured.err
    assert "secret-token" not in captured.err
    assert "token=***" in captured.err


def test_cli_drive_list_404_reports_wrong_drive_id_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("cylro", default_drive_id="drive-1", make_default=True)
    TokenStore().save_token("cylro", "secret-token")
    fake_api = FakeAPI(
        {
            "/2/drive/drive-1/files": InformaniakAPIError(
                404,
                "GET /2/drive/drive-1/files failed: not found",
                secrets=["secret-token"],
            )
        }
    )
    monkeypatch.setattr(cli, "InformaniakAPIClient", lambda token, *, base_url: fake_api)

    assert cli.main(["drive", "list", "--json"]) == 1

    captured = capsys.readouterr()
    assert "/2/drive/drive-1/files" in captured.err
    assert "saved kDrive id may be wrong" in captured.err
