from infomaniak_cli.auth import TokenStore


def test_token_store_redacts_and_detects_token(tmp_path):
    store = TokenStore(config_dir=tmp_path)
    store.save_token("work", "secret-token-value")

    assert store.has_token("work") is True
    assert store.load_token("work") == "secret-token-value"
    assert store.redacted_token("work") == "secr…alue"
