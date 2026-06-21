from infomaniak_cli.auth import TokenStore


def test_token_store_redacts_and_detects_token(tmp_path):
    store = TokenStore(config_dir=tmp_path)
    store.save_token("cylro", "secret-token-value")

    assert store.has_token("cylro") is True
    assert store.load_token("cylro") == "secret-token-value"
    assert store.redacted_token("cylro") == "secr…alue"
