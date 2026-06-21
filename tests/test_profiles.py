from infomaniak_cli.profiles import ProfileManager


def test_setup_profile_creates_profile_and_current_default(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)

    profile = manager.create_or_update("cylro", make_default=True)

    assert profile.name == "cylro"
    assert manager.get_current_name() == "cylro"
    assert manager.get("cylro").name == "cylro"
    assert manager.list_names() == ["cylro"]


def test_profile_metadata_can_store_discovered_defaults(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)

    manager.create_or_update(
        "cylro",
        account_name="Cylro SARL-S",
        default_mailbox="contact@cylro.com",
        default_drive_name="Cylro Documents",
        make_default=True,
    )
    profile = manager.get_current()

    assert profile.account_name == "Cylro SARL-S"
    assert profile.default_mailbox == "contact@cylro.com"
    assert profile.default_drive_name == "Cylro Documents"


def test_profile_metadata_can_replace_discovered_defaults_with_none(tmp_path):
    manager = ProfileManager(config_dir=tmp_path)
    manager.create_or_update(
        "cylro",
        account_name="Cylro SARL-S",
        default_drive_id="40",
        default_drive_name="drive",
        kchat_team_id="54",
        make_default=True,
    )

    profile = manager.replace_metadata(
        "cylro",
        account_name="Cylro SARL-S",
        default_drive_id=None,
        default_drive_name=None,
        kchat_team_id=None,
    )

    assert profile.account_name == "Cylro SARL-S"
    assert profile.default_drive_id is None
    assert profile.default_drive_name is None
    assert profile.kchat_team_id is None
