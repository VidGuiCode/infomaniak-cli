from infomaniak_cli.services.mail_discovery import (
    list_mail_hostings,
    list_mailboxes,
    select_default_mailbox,
    slim_mail_hosting,
    slim_mailbox,
)


class FakeAPI:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def get(self, path, params=None):
        self.calls.append((path, params))
        return self.responses[path]


def test_list_mail_hostings_filters_account_catalog_items():
    api = FakeAPI(
        {
            "/1/accounts/42/products": {
                "result": "success",
                "data": [
                    {"id": "mail-1", "name": "Example Mail", "type": "mail_hosting"},
                    {"id": "drive-1", "name": "Drive", "type": "drive"},
                ],
            },
            "/1/accounts/42/services": {
                "result": "success",
                "data": [
                    {"id": "mail-2", "name": "example.com", "service_name": "email_hosting"},
                    {"id": "chat-1", "name": "kChat", "service_name": "kchat"},
                ],
            },
        }
    )

    hostings = list_mail_hostings(api, "42")

    assert [item["id"] for item in hostings] == ["mail-1", "mail-2"]
    assert api.calls == [
        ("/1/accounts/42/products", None),
        ("/1/accounts/42/services", None),
    ]


def test_list_mailboxes_uses_confirmed_mail_hosting_endpoint():
    api = FakeAPI(
        {
            "/1/mail_hostings/mail-1/mailboxes": {
                "result": "success",
                "data": [{"id": "box-1", "email": "user@example.com"}],
            }
        }
    )

    assert list_mailboxes(api, "mail-1") == [{"id": "box-1", "email": "user@example.com"}]
    assert api.calls == [("/1/mail_hostings/mail-1/mailboxes", None)]


def test_select_default_mailbox_prefers_profile_user_email():
    mailboxes = [
        {"id": "box-1", "email": "admin@example.com"},
        {"id": "box-2", "email": "user@example.com"},
    ]

    assert select_default_mailbox(mailboxes, "user@example.com") == "user@example.com"


def test_select_default_mailbox_falls_back_to_first_available():
    assert select_default_mailbox([{"id": "box-1", "email": "admin@example.com"}], "user@example.com") == (
        "admin@example.com"
    )


def test_slim_mail_discovery_shapes_are_stable():
    assert slim_mail_hosting({"id": "mail-1", "name": "Example Mail", "type": "mail_hosting"}) == {
        "id": "mail-1",
        "name": "Example Mail",
        "type": "mail_hosting",
        "customer_name": None,
    }
    assert slim_mailbox({"id": "box-1", "email": "user@example.com"}, mail_hosting_id="mail-1", source="api") == {
        "id": "box-1",
        "email": "user@example.com",
        "name": "user@example.com",
        "login": None,
        "mail_hosting_id": "mail-1",
        "source": "api",
    }
