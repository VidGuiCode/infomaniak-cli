from infomaniak_cli.auth import ContactsPasswordStore, TokenStore



def test_token_store_redacts_and_detects_token(tmp_path):
    store = TokenStore(config_dir=tmp_path)
    store.save_token("work", "secret-token-value")

    assert store.has_token("work") is True
    assert store.load_token("work") == "secret-token-value"
    assert store.redacted_token("work") == "secr…alue"


def test_contacts_password_store_redacts_and_detects_password(tmp_path):
    store = ContactsPasswordStore(config_dir=tmp_path)
    store.save_password("work", "secret-contacts-password")

    assert store.has_password("work") is True
    assert store.load_password("work") == "secret-contacts-password"
    assert store.redacted_password("work") == "secr…word"
