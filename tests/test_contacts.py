import json

from infomaniak_cli import cli
from infomaniak_cli.auth import ContactsPasswordStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.contacts import ContactsClient, find_contact, search_contacts, slim_contact


CONTACTS = [
    {
        "id": "contact-1",
        "display_name": "Example Person",
        "given_name": "Example",
        "family_name": "Person",
        "emails": ["person@example.com"],
        "phones": ["+352 111"],
        "organization": "Example Co",
        "raw_vcard": "BEGIN:VCARD",
    },
    {
        "id": "contact-2",
        "display_name": "Alice Admin",
        "given_name": "Alice",
        "family_name": "Admin",
        "emails": ["alice@example.net"],
        "phones": ["+352 222"],
        "organization": "Ops Team",
    },
]


class FakeContactsClient:
    def __init__(self, url, username, password, contacts=None):
        self.url = url
        self.username = username
        self.password = password
        self.contacts = contacts if contacts is not None else CONTACTS
        self.calls = []

    def list_contacts(self, limit=None):
        self.calls.append(("list_contacts", limit))
        if limit is not None:
            return self.contacts[:limit]
        return self.contacts


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


def _configured_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        contacts_url="https://sync.example.test/addressbooks/user/default/",
        contacts_username="user@example.com",
        make_default=True,
    )
    ContactsPasswordStore().save_password("work", "secret-contacts-password")


def test_slim_contact_projects_stable_fields():
    raw = {
        "id": "contact-1",
        "display_name": "Example Person",
        "given_name": "Example",
        "family_name": "Person",
        "emails": ["person@example.com"],
        "phones": ["+352 111"],
        "organization": "Example Co",
        "raw_vcard": "BEGIN:VCARD",
    }

    assert slim_contact(raw) == {
        "id": "contact-1",
        "display_name": "Example Person",
        "given_name": "Example",
        "family_name": "Person",
        "emails": ["person@example.com"],
        "phones": ["+352 111"],
        "organization": "Example Co",
    }


def test_search_contacts_matches_name_email_org_and_phone_case_insensitively():
    assert [c["id"] for c in search_contacts(CONTACTS, "example person")] == ["contact-1"]
    assert [c["id"] for c in search_contacts(CONTACTS, "ALICE@EXAMPLE.NET")] == ["contact-2"]
    assert [c["id"] for c in search_contacts(CONTACTS, "ops team")] == ["contact-2"]
    assert [c["id"] for c in search_contacts(CONTACTS, "352 111")] == ["contact-1"]


def test_find_contact_returns_existing_contact_by_id():
    assert find_contact(CONTACTS, "contact-2")["display_name"] == "Alice Admin"


def test_carddav_client_parses_multistatus_vcards():
    seen_requests = []
    payload = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:carddav">
  <D:response>
    <D:href>/addressbooks/user/default/contact-1.vcf</D:href>
    <D:propstat>
      <D:prop>
        <C:address-data>BEGIN:VCARD
VERSION:3.0
UID:uid-1
FN:Example Person
N:Person;Example;;;
EMAIL:person@example.com
TEL:+352 111
ORG:Example Co
END:VCARD</C:address-data>
      </D:prop>
    </D:propstat>
  </D:response>
</D:multistatus>"""

    def opener(request):
        seen_requests.append(request)
        return FakeResponse(payload)

    client = ContactsClient("https://sync.example.test/addressbooks/user/default/", "user@example.com", "pw", opener=opener)

    contacts = client.list_contacts()

    assert contacts[0]["id"] == "uid-1"
    assert contacts[0]["display_name"] == "Example Person"
    assert contacts[0]["given_name"] == "Example"
    assert contacts[0]["family_name"] == "Person"
    assert contacts[0]["emails"] == ["person@example.com"]
    assert contacts[0]["phones"] == ["+352 111"]
    assert contacts[0]["organization"] == "Example Co"
    assert seen_requests[0].get_method() == "REPORT"
    assert seen_requests[0].headers["Depth"] == "1"


def test_cli_contacts_list_slim_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created_clients = []

    def make_client(url, username, password):
        client = FakeContactsClient(url, username, password)
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ContactsClient", make_client)

    assert cli.main(["contacts", "list", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "profile": "work",
        "count": 2,
        "contacts": [
            {
                "id": "contact-1",
                "display_name": "Example Person",
                "given_name": "Example",
                "family_name": "Person",
                "emails": ["person@example.com"],
                "phones": ["+352 111"],
                "organization": "Example Co",
            },
            {
                "id": "contact-2",
                "display_name": "Alice Admin",
                "given_name": "Alice",
                "family_name": "Admin",
                "emails": ["alice@example.net"],
                "phones": ["+352 222"],
                "organization": "Ops Team",
            },
        ],
    }
    assert created_clients[0].url == "https://sync.example.test/addressbooks/user/default/"
    assert created_clients[0].username == "user@example.com"
    assert created_clients[0].password == "secret-contacts-password"
    assert created_clients[0].calls == [("list_contacts", None)]


def test_cli_contacts_list_raw_json(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "ContactsClient", FakeContactsClient)

    assert cli.main(["contacts", "list", "--json", "--raw"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["contacts"][0]["raw_vcard"] == "BEGIN:VCARD"


def test_cli_contacts_list_limit(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    created_clients = []

    def make_client(url, username, password):
        client = FakeContactsClient(url, username, password)
        created_clients.append(client)
        return client

    monkeypatch.setattr(cli, "ContactsClient", make_client)

    assert cli.main(["contacts", "list", "--limit", "1", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 1
    assert output["contacts"][0]["id"] == "contact-1"
    assert created_clients[0].calls == [("list_contacts", 1)]


def test_cli_contacts_search_filters_client_side(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "ContactsClient", FakeContactsClient)

    assert cli.main(["contacts", "search", "EXAMPLE", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["profile"] == "work"
    assert output["query"] == "EXAMPLE"
    assert output["count"] == 2
    assert [contact["id"] for contact in output["contacts"]] == ["contact-1", "contact-2"]


def test_cli_contacts_search_limit_applies_after_filtering(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "ContactsClient", FakeContactsClient)

    assert cli.main(["contacts", "search", "example", "--limit", "1", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["count"] == 1
    assert output["contacts"][0]["id"] == "contact-1"


def test_cli_contacts_show_existing_contact(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "ContactsClient", FakeContactsClient)

    assert cli.main(["contacts", "show", "contact-2", "--json"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "profile": "work",
        "contact_id": "contact-2",
        "contact": {
            "id": "contact-2",
            "display_name": "Alice Admin",
            "given_name": "Alice",
            "family_name": "Admin",
            "emails": ["alice@example.net"],
            "phones": ["+352 222"],
            "organization": "Ops Team",
        },
    }


def test_cli_contacts_show_missing_contact_is_helpful(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "ContactsClient", FakeContactsClient)

    assert cli.main(["contacts", "show", "missing", "--json"]) == 1

    captured = capsys.readouterr()
    assert "Contact not found: missing" in captured.err


def test_cli_contacts_requires_contacts_configuration(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update("work", make_default=True)

    assert cli.main(["contacts", "list"]) == 1

    captured = capsys.readouterr()
    assert "No contacts configured for profile: work" in captured.err
    assert "auth contacts" in captured.err


def test_contacts_parser_exposes_no_write_commands():
    parser = cli.build_parser()
    contacts_parser = parser._subparsers._group_actions[0].choices["contacts"]
    choices = contacts_parser._subparsers._group_actions[0].choices

    assert set(choices) == {"list", "search", "show"}
    assert not {"create", "update", "delete", "import", "export", "sync"} & set(choices)
