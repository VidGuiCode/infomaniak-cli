from pathlib import Path

from infomaniak_cli.config_paths import get_config_dir, get_profiles_dir, get_tokens_dir


def test_config_dir_respects_override(tmp_path, monkeypatch):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "ik-config"))

    assert get_config_dir() == tmp_path / "ik-config"
    assert get_profiles_dir() == tmp_path / "ik-config" / "profiles"
    assert get_tokens_dir() == tmp_path / "ik-config" / "tokens"
