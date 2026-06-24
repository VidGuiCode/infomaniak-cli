from infomaniak_cli.profiles import ProfileManager
import pytest


def test_setup_profile_creates_profile_and_current_default(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)

    profile = manager.create_or_update("work", make_default=True)

    assert profile.name == "work"
    assert manager.get_current_name() == "work"
    assert manager.get("work").name == "work"
    assert manager.list_names() == ["work"]


def test_profile_metadata_can_store_discovered_defaults(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)

    manager.create_or_update(
        "work",
        account_name="Example Co",
        default_mailbox="contact@example.com",
        default_drive_name="Example Documents",
        make_default=True,
    )
    profile = manager.get_current()

    assert profile.account_name == "Example Co"
    assert profile.default_mailbox == "contact@example.com"
    assert profile.default_drive_name == "Example Documents"


def test_profile_metadata_can_store_kchat_browser_url_details(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)

    manager.create_or_update(
        "work",
        kchat_url="https://cylro.kchat.infomaniak.com",
        kchat_ksuite_url="https://ksuite.infomaniak.com/1988835/kchat/cylro/channels/town-square",
        kchat_ksuite_account_id="1988835",
        kchat_workspace_slug="cylro",
        kchat_default_channel_slug="town-square",
        make_default=True,
    )
    profile = manager.get_current()

    assert profile.kchat_url == "https://cylro.kchat.infomaniak.com"
    assert profile.kchat_ksuite_url == "https://ksuite.infomaniak.com/1988835/kchat/cylro/channels/town-square"
    assert profile.kchat_ksuite_account_id == "1988835"
    assert profile.kchat_workspace_slug == "cylro"
    assert profile.kchat_default_channel_slug == "town-square"


def test_profile_metadata_can_replace_discovered_defaults_with_none(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update(
        "work",
        account_name="Example Co",
        default_drive_id="40",
        default_drive_name="drive",
        kchat_team_id="54",
        make_default=True,
    )

    profile = manager.replace_metadata(
        "work",
        account_name="Example Co",
        default_drive_id=None,
        default_drive_name=None,
        kchat_team_id=None,
    )

    assert profile.account_name == "Example Co"
    assert profile.default_drive_id is None
    assert profile.default_drive_name is None
    assert profile.kchat_team_id is None


def test_profile_rename_moves_metadata_and_updates_current(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("work", account_name="Example Co", make_default=True)

    renamed = manager.rename("work", "office")

    assert renamed.name == "office"
    assert renamed.account_name == "Example Co"
    assert not manager.exists("work")
    assert manager.exists("office")
    assert manager.get_current_name() == "office"


def test_profile_rename_fails_if_target_exists(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("work", make_default=True)
    manager.create_or_update("office")

    with pytest.raises(ValueError, match="already exists"):
        manager.rename("work", "office")

    assert manager.exists("work")
    assert manager.exists("office")


def test_profile_delete_removes_selected_profile_and_clears_current(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("work", make_default=True)

    deleted = manager.delete("work")

    assert deleted.name == "work"
    assert not manager.exists("work")
    assert manager.get_current_name() is None


def test_profile_delete_current_switches_to_remaining_profile(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update("work", make_default=True)
    manager.create_or_update("personal")

    manager.delete("work")

    assert manager.get_current_name() == "personal"
