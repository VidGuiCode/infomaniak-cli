from infomaniak_cli.profiles import ProfileManager


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
