from infomaniak_cli.auth import CalendarPasswordStore, ChatTokenStore, ContactsPasswordStore, MailPasswordStore, TokenStore


def test_token_stores_can_rename_profile_secret_files(tmp_path):
    TokenStore(config_dir=tmp_path).save_token("work", "main-token")
    MailPasswordStore(config_dir=tmp_path).save_password("work", "mail-password")
    ContactsPasswordStore(config_dir=tmp_path).save_password("work", "contacts-password")
    CalendarPasswordStore(config_dir=tmp_path).save_password("work", "calendar-password")
    ChatTokenStore(config_dir=tmp_path).save_token("work", "chat-token")

    for store in (
        TokenStore(config_dir=tmp_path),
        MailPasswordStore(config_dir=tmp_path),
        ContactsPasswordStore(config_dir=tmp_path),
        CalendarPasswordStore(config_dir=tmp_path),
        ChatTokenStore(config_dir=tmp_path),
    ):
        store.rename_profile("work", "office")

    assert not TokenStore(config_dir=tmp_path).has_token("work")
    assert TokenStore(config_dir=tmp_path).load_token("office") == "main-token"
    assert MailPasswordStore(config_dir=tmp_path).load_password("office") == "mail-password"
    assert ContactsPasswordStore(config_dir=tmp_path).load_password("office") == "contacts-password"
    assert CalendarPasswordStore(config_dir=tmp_path).load_password("office") == "calendar-password"
    assert ChatTokenStore(config_dir=tmp_path).load_token("office") == "chat-token"


def test_token_stores_delete_profile_secret_files(tmp_path):
    TokenStore(config_dir=tmp_path).save_token("work", "main-token")
    MailPasswordStore(config_dir=tmp_path).save_password("work", "mail-password")
    ContactsPasswordStore(config_dir=tmp_path).save_password("work", "contacts-password")
    CalendarPasswordStore(config_dir=tmp_path).save_password("work", "calendar-password")
    ChatTokenStore(config_dir=tmp_path).save_token("work", "chat-token")

    for store in (
        TokenStore(config_dir=tmp_path),
        MailPasswordStore(config_dir=tmp_path),
        ContactsPasswordStore(config_dir=tmp_path),
        CalendarPasswordStore(config_dir=tmp_path),
        ChatTokenStore(config_dir=tmp_path),
    ):
        store.delete_profile("work")

    assert not TokenStore(config_dir=tmp_path).has_token("work")
    assert not MailPasswordStore(config_dir=tmp_path).has_password("work")
    assert not ContactsPasswordStore(config_dir=tmp_path).has_password("work")
    assert not CalendarPasswordStore(config_dir=tmp_path).has_password("work")
    assert not ChatTokenStore(config_dir=tmp_path).has_token("work")



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


def test_calendar_password_store_redacts_and_detects_password(tmp_path):
    store = CalendarPasswordStore(config_dir=tmp_path)
    store.save_password("work", "secret-calendar-password")

    assert store.has_password("work") is True
    assert store.load_password("work") == "secret-calendar-password"
    assert store.redacted_password("work") == "secr…word"


def test_chat_token_store_redacts_and_detects_token(tmp_path):
    store = ChatTokenStore(config_dir=tmp_path)
    store.save_token("work", "secret-chat-token")

    assert store.has_token("work") is True
    assert store.load_token("work") == "secret-chat-token"
    assert store.redacted_token("work") == "secr…oken"
