import json

from infomaniak_cli import cli
from infomaniak_cli.auth import ContactsPasswordStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.contacts import (
    ContactsClient,
    build_vcard,
    find_contact,
    merge_vcard,
    search_contacts,
    slim_contact,
)


CONTACTS = [
    {
        "id": "contact-1",
        "display_name": "Example Person",
        "given_name": "Example",
        "family_name": "Person",
        "emails": ["person@example.com"],
        "phones": ["+352 111"],
        "organization": "Example Co",
        "raw_vcard": "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-1\r\nFN:Example Person\r\nN:Person;Example;;;\r\nEMAIL:person@example.com\r\nTEL:+352 111\r\nORG:Example Co\r\nNOTE:Preserve me\r\nEND:VCARD\r\n",
        "resource_url": "https://sync.example.test/addressbooks/user/default/contact-1.vcf",
        "etag": '"etag-1"',
    },
    {
        "id": "contact-2",
        "display_name": "Alice Admin",
        "given_name": "Alice",
        "family_name": "Admin",
        "emails": ["alice@example.net"],
        "phones": ["+352 222"],
        "organization": "Ops Team",
        "resource_url": "https://sync.example.test/addressbooks/user/default/contact-2.vcf",
        "etag": '"etag-2"',
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

    def create_contact(self, vcard, uid):
        self.calls.append(("create_contact", vcard, uid))
        return {"uid": uid, "url": f"{self.url}{uid}.vcf", "status": 201}

    def update_contact(self, vcard, contact):
        self.calls.append(("update_contact", vcard, contact))
        return {
            "uid": contact["id"],
            "url": contact["resource_url"],
            "status": 204,
        }


class FakeResponse:
    def __init__(self, payload, *, status=200, headers=None):
        self.payload = payload
        self.status = status
        self.headers = headers or {}

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
    assert contacts[0]["resource_url"] == "https://sync.example.test/addressbooks/user/default/contact-1.vcf"
    assert seen_requests[0].get_method() == "REPORT"
    assert seen_requests[0].headers["Depth"] == "1"


EMPTY_MULTISTATUS = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:"/>"""

ADDRESSBOOK_RESOURCETYPE = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:carddav">
  <D:response>
    <D:href>/addressbooks/user/default/</D:href>
    <D:propstat><D:prop>
      <D:resourcetype><D:collection/><C:addressbook/></D:resourcetype>
    </D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
  </D:response>
</D:multistatus>"""

PLAIN_COLLECTION_RESOURCETYPE = b"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
  <D:response>
    <D:href>/</D:href>
    <D:propstat><D:prop>
      <D:resourcetype><D:collection/></D:resourcetype>
    </D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>
  </D:response>
</D:multistatus>"""


def _method_routing_opener(routes, seen):
    def opener(request):
        seen.append(request)
        return FakeResponse(routes[request.get_method()])

    return opener


def test_carddav_client_empty_real_addressbook_returns_no_contacts():
    seen = []
    opener = _method_routing_opener(
        {"REPORT": EMPTY_MULTISTATUS, "PROPFIND": ADDRESSBOOK_RESOURCETYPE}, seen
    )
    client = ContactsClient(
        "https://sync.example.test/addressbooks/user/default/", "user@example.com", "pw", opener=opener
    )

    assert client.list_contacts() == []
    assert [request.get_method() for request in seen] == ["REPORT", "PROPFIND"]


def test_carddav_client_zero_contacts_on_non_addressbook_url_is_actionable():
    # Live sync.infomaniak.com finding: a REPORT against the bare sync base
    # returns an empty multistatus, which used to look like "0 contacts".
    import pytest

    from infomaniak_cli.services.contacts import ContactError

    opener = _method_routing_opener(
        {"REPORT": EMPTY_MULTISTATUS, "PROPFIND": PLAIN_COLLECTION_RESOURCETYPE}, []
    )
    client = ContactsClient("https://sync.example.test/", "user@example.com", "pw", opener=opener)

    with pytest.raises(ContactError) as excinfo:
        client.list_contacts()

    message = str(excinfo.value)
    assert "not a CardDAV address book" in message
    assert "https://sync.example.test/" in message
    assert "ik auth contacts" in message


def test_carddav_client_zero_contacts_with_failing_probe_reports_status():
    import urllib.error

    import pytest

    from infomaniak_cli.services.contacts import ContactError

    def opener(request):
        if request.get_method() == "REPORT":
            return FakeResponse(EMPTY_MULTISTATUS)
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    client = ContactsClient("https://sync.example.test/", "user@example.com", "pw", opener=opener)

    with pytest.raises(ContactError) as excinfo:
        client.list_contacts()

    message = str(excinfo.value)
    assert "HTTP 404" in message
    assert "ik auth contacts" in message


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
    assert output["contacts"][0]["raw_vcard"].startswith("BEGIN:VCARD")


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


def test_build_vcard_emits_escaped_vcard_3_fields():
    vcard = build_vcard(
        uid="uid-1",
        display_name="Example, Person",
        given_name="Example",
        family_name="Person",
        emails=["person@example.com"],
        phones=["+352 111"],
        organization="Example; Co",
    )

    assert vcard.startswith("BEGIN:VCARD\r\nVERSION:3.0\r\nUID:uid-1\r\n")
    assert "FN:Example\\, Person\r\n" in vcard
    assert "N:Person;Example;;;\r\n" in vcard
    assert "EMAIL:person@example.com\r\n" in vcard
    assert "TEL:+352 111\r\n" in vcard
    assert "ORG:Example\\; Co\r\n" in vcard
    assert vcard.endswith("END:VCARD\r\n")


def test_carddav_create_uses_put_if_none_match():
    seen = []

    def opener(request):
        seen.append(request)
        return FakeResponse(b"", status=201, headers={"ETag": '"new"'})

    client = ContactsClient(
        "https://sync.example.test/addressbooks/user/default/",
        "user@example.com", "pw", opener=opener,
    )
    result = client.create_contact("BEGIN:VCARD\r\nEND:VCARD\r\n", "uid-new")

    assert result["status"] == 201
    assert result["url"].endswith("/uid-new.vcf")
    assert seen[0].get_method() == "PUT"
    assert seen[0].headers["If-none-match"] == "*"


def test_carddav_update_uses_resolved_url_and_if_match():
    seen = []

    def opener(request):
        seen.append(request)
        return FakeResponse(b"", status=204)

    client = ContactsClient(
        "https://sync.example.test/addressbooks/user/default/",
        "user@example.com", "pw", opener=opener,
    )
    contact = {
        "id": "contact-1",
        "resource_url": "https://sync.example.test/addressbooks/user/default/contact-1.vcf",
        "etag": '"etag-1"',
    }
    result = client.update_contact("BEGIN:VCARD\r\nEND:VCARD\r\n", contact)

    assert result["status"] == 204
    assert seen[0].full_url == contact["resource_url"]
    assert seen[0].headers["If-match"] == '"etag-1"'


def test_merge_vcard_preserves_unmodeled_properties():
    merged = merge_vcard(
        CONTACTS[0]["raw_vcard"],
        uid="contact-1",
        display_name="Example Person",
        given_name="Example",
        family_name="Person",
        emails=["new@example.test"],
        phones=["+352 999"],
        organization="Updated Org",
    )

    assert "NOTE:Preserve me\r\n" in merged
    assert "EMAIL:new@example.test\r\n" in merged
    assert "EMAIL:person@example.com" not in merged
    assert "ORG:Updated Org\r\n" in merged


def test_carddav_update_refuses_missing_etag():
    import pytest
    from infomaniak_cli.services.contacts import ContactError

    client = ContactsClient(
        "https://sync.example.test/addressbooks/user/default/",
        "user@example.com", "pw", opener=lambda request: None,
    )
    with pytest.raises(ContactError, match="no ETag"):
        client.update_contact("vcard", {"id": "contact-1", "resource_url": "https://example.test/1.vcf"})


def test_carddav_write_error_redacts_password():
    import urllib.error
    import pytest
    from infomaniak_cli.services.contacts import ContactError

    password = "super-secret-contact-password"

    def opener(request):
        raise urllib.error.URLError(f"connection failed near {password}")

    client = ContactsClient(
        "https://sync.example.test/addressbooks/user/default/",
        "user@example.com", password, opener=opener,
    )
    with pytest.raises(ContactError) as excinfo:
        client.create_contact("vcard", "uid-new")

    assert password not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def _recording_contacts_client(monkeypatch):
    clients = []

    def make_client(url, username, password):
        client = FakeContactsClient(url, username, password)
        clients.append(client)
        return client

    monkeypatch.setattr(cli, "ContactsClient", make_client)
    return clients


def test_cli_contacts_create_dry_run_does_not_write(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _recording_contacts_client(monkeypatch)

    assert cli.main([
        "contacts", "create", "--name", "Disposable Contact",
        "--email", "disposable@example.test", "--dry-run", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["created"] is False
    assert output["contact"]["display_name"] == "Disposable Contact"
    assert "BEGIN:VCARD" in output["vcard"]
    assert clients == []


def test_cli_contacts_create_dry_run_needs_no_password_or_client(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        contacts_url="https://sync.example.test/addressbooks/user/default/",
        contacts_username="user@example.com",
        make_default=True,
    )

    assert cli.main([
        "contacts", "create", "--name", "Offline Preview",
        "--email", "preview@example.test", "--dry-run", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["created"] is False
    assert output["contact"]["display_name"] == "Offline Preview"
    assert "BEGIN:VCARD" in output["vcard"]


def test_cli_contacts_create_yes_requires_explicit_profile(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _recording_contacts_client(monkeypatch)

    assert cli.main([
        "contacts", "create", "--name", "Disposable Contact", "--yes",
    ]) == 1

    assert "unless the profile is explicit" in capsys.readouterr().err
    assert not any(call[0] == "create_contact" for call in clients[0].calls)


def test_cli_contacts_create_explicit_yes_writes_once(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _recording_contacts_client(monkeypatch)

    assert cli.main([
        "contacts", "create", "--name", "Disposable Contact",
        "--email", "disposable@example.test", "--yes", "--json", "--profile", "work",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["created"] is True
    assert output["result"]["status"] == 201
    assert len([call for call in clients[0].calls if call[0] == "create_contact"]) == 1


def test_cli_contacts_update_dry_run_resolves_and_merges_target(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _recording_contacts_client(monkeypatch)

    assert cli.main([
        "contacts", "update", "contact-1", "--organization", "Updated Org",
        "--dry-run", "--json",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["dry_run"] is True
    assert output["updated"] is False
    assert output["before"]["organization"] == "Example Co"
    assert output["after"]["organization"] == "Updated Org"
    assert output["after"]["emails"] == ["person@example.com"]
    assert "NOTE:Preserve me" in output["vcard"]
    assert not any(call[0] == "update_contact" for call in clients[0].calls)


def test_cli_contacts_update_explicit_yes_uses_resolved_target(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _recording_contacts_client(monkeypatch)

    assert cli.main([
        "contacts", "update", "contact-1", "--phone", "+352 999",
        "--yes", "--json", "--profile", "work",
    ]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["updated"] is True
    call = [call for call in clients[0].calls if call[0] == "update_contact"][0]
    assert call[2]["resource_url"].endswith("contact-1.vcf")


def test_cli_contacts_update_yes_requires_explicit_profile(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    clients = _recording_contacts_client(monkeypatch)

    assert cli.main([
        "contacts", "update", "contact-1", "--organization", "Updated Org", "--yes",
    ]) == 1

    assert "unless the profile is explicit" in capsys.readouterr().err
    assert not any(call[0] == "update_contact" for call in clients[0].calls)


def test_cli_contacts_update_requires_changed_field(tmp_path, monkeypatch, capsys):
    _configured_profile(tmp_path, monkeypatch)
    _recording_contacts_client(monkeypatch)

    assert cli.main(["contacts", "update", "contact-1", "--dry-run"]) == 1

    assert "requires at least one field" in capsys.readouterr().err


def test_contacts_parser_exposes_only_protected_write_commands():
    parser = cli.build_parser()
    contacts_parser = parser._subparsers._group_actions[0].choices["contacts"]
    choices = contacts_parser._subparsers._group_actions[0].choices

    assert set(choices) == {"list", "search", "show", "create", "update"}
    assert not {"delete", "import", "export", "sync"} & set(choices)
