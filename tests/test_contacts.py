import json
import urllib.error

import pytest

from infomaniak_cli import cli
from infomaniak_cli.auth import ContactsPasswordStore
from infomaniak_cli.profiles import ProfileManager
from infomaniak_cli.services.contacts import (
    ContactError,
    ContactsClient,
    build_contacts_export,
    build_vcard,
    find_contact,
    find_duplicate_groups,
    merge_contact_fields,
    merge_vcard,
    parse_vcard,
    search_contacts,
    slim_contact,
    split_vcards,
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
        "typed_emails": [],
        "typed_phones": [],
        "addresses": [],
        "groups": [],
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
                "typed_emails": [],
                "typed_phones": [],
                "addresses": [],
                "groups": [],
            },
            {
                "id": "contact-2",
                "display_name": "Alice Admin",
                "given_name": "Alice",
                "family_name": "Admin",
                "emails": ["alice@example.net"],
                "phones": ["+352 222"],
                "organization": "Ops Team",
                "typed_emails": [],
                "typed_phones": [],
                "addresses": [],
                "groups": [],
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
            "typed_emails": [],
            "typed_phones": [],
            "addresses": [],
            "groups": [],
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

    # 0.2.8 added create/update; 0.2.17 added transfer and lifecycle. Every
    # write acts on exactly one resolved contact, and merge never deletes the
    # secondary.
    assert set(choices) == {
        "list", "search", "show", "create", "update",
        "export", "duplicates", "merge", "import", "delete",
    }
    # destructive whole-collection operations stay out
    assert not {"sync", "purge", "delete-all", "empty"} & set(choices)


# --- v0.2.17 transfer and lifecycle ---------------------------------------


RICH_VCARD = (
    "BEGIN:VCARD\r\n"
    "VERSION:3.0\r\n"
    "UID:contact-rich\r\n"
    "FN:Example Person\r\n"
    "N:Person;Example;;;\r\n"
    "EMAIL;TYPE=work:person@example.com\r\n"
    "EMAIL;TYPE=home:personal@example.com\r\n"
    "TEL;TYPE=cell:+3300000000\r\n"
    "ADR;TYPE=work:;;1 Example Street;Example City;Example Region;1000;Example Country\r\n"
    "CATEGORIES:Suppliers,Finance\r\n"
    "ORG:Example Co\r\n"
    "PHOTO;ENCODING=b;TYPE=JPEG:Zm9vYmFy\r\n"
    "X-CUSTOM-FIELD:keep me\r\n"
    "END:VCARD\r\n"
)


def test_parse_vcard_models_addresses_groups_and_types():
    parsed = parse_vcard(RICH_VCARD)

    assert parsed["emails"] == ["person@example.com", "personal@example.com"]
    assert parsed["typed_emails"][0] == {"value": "person@example.com", "type": "work"}
    assert parsed["typed_phones"][0]["type"] == "cell"
    assert parsed["groups"] == ["Suppliers", "Finance"]
    address = parsed["addresses"][0]
    assert address["type"] == "work"
    assert address["street"] == "1 Example Street"
    assert address["locality"] == "Example City"
    assert address["postal_code"] == "1000"
    assert address["country"] == "Example Country"


def test_merge_vcard_still_preserves_unmodeled_properties():
    """Regression: richer parsing must not start dropping what it cannot model."""
    merged = merge_vcard(RICH_VCARD, uid="contact-rich", display_name="Renamed Person")

    assert "X-CUSTOM-FIELD:keep me" in merged
    assert "PHOTO;ENCODING=b;TYPE=JPEG:Zm9vYmFy" in merged
    assert "CATEGORIES:Suppliers,Finance" in merged
    assert "FN:Renamed Person" in merged
    assert merged.count("FN:") == 1


def test_build_contacts_export_copies_raw_vcards_verbatim():
    contacts = [
        {"id": "contact-rich", "raw_vcard": RICH_VCARD},
        {"id": "contact-2", "raw_vcard": "BEGIN:VCARD\r\nUID:contact-2\r\nFN:Second\r\nEND:VCARD\r\n"},
    ]

    vcf, skipped = build_contacts_export(contacts)

    assert skipped == []
    assert vcf.count("BEGIN:VCARD") == 2
    assert "X-CUSTOM-FIELD:keep me" in vcf
    assert "PHOTO;ENCODING=b;TYPE=JPEG:Zm9vYmFy" in vcf


def test_build_contacts_export_reports_contacts_without_a_vcard():
    vcf, skipped = build_contacts_export([{"id": "broken", "raw_vcard": "not a vcard"}])

    assert skipped == ["broken"]
    assert "BEGIN:VCARD" not in vcf


def test_split_vcards_separates_a_multi_card_document():
    document = RICH_VCARD + "BEGIN:VCARD\r\nUID:second\r\nFN:Second\r\nEND:VCARD\r\n"

    cards = split_vcards(document)

    assert len(cards) == 2
    assert "UID:contact-rich" in cards[0]
    assert "UID:second" in cards[1]


def test_find_duplicate_groups_matches_on_email_then_name():
    contacts = [
        {"id": "a", "display_name": "Example Person", "emails": ["person@example.com"]},
        {"id": "b", "display_name": "Different Name", "emails": ["PERSON@example.com"]},
        {"id": "c", "display_name": "Other Person", "emails": []},
        {"id": "d", "display_name": "other person", "emails": []},
        {"id": "e", "display_name": "Unique", "emails": ["unique@example.com"]},
    ]

    groups = find_duplicate_groups(contacts)
    by_reason = {g["reason"]: g for g in groups}

    assert [c["id"] for c in by_reason["email"]["contacts"]] == ["a", "b"]
    assert [c["id"] for c in by_reason["display_name"]["contacts"]] == ["c", "d"]
    # a contact with no twin is never reported
    assert all("e" not in [c["id"] for c in g["contacts"]] for g in groups)


def test_merge_contact_fields_unions_values_and_reports_conflicts():
    primary = {
        "display_name": "Example Person", "organization": "Example Co",
        "emails": ["person@example.com"], "phones": [],
    }
    secondary = {
        "display_name": "Example Person", "organization": "Other Co",
        "emails": ["personal@example.com"], "phones": ["+3300000000"],
    }

    merged, conflicts = merge_contact_fields(primary, secondary)

    assert merged["emails"] == ["person@example.com", "personal@example.com"]
    assert merged["phones"] == ["+3300000000"]
    # the primary wins a scalar conflict, and the conflict is reported not hidden
    assert merged["organization"] == "Example Co"
    assert conflicts == [
        {"field": "organization", "primary": "Example Co", "secondary": "Other Co"}
    ]


def test_merge_contact_fields_deduplicates_case_insensitively():
    merged, _ = merge_contact_fields(
        {"emails": ["Person@Example.com"]}, {"emails": ["person@example.com"]}
    )

    assert merged["emails"] == ["Person@Example.com"]


def test_delete_contact_sends_if_match_and_reports_success():
    seen = []

    def opener(request):
        seen.append(request)
        return FakeResponse(b"", status=204)

    client = ContactsClient(
        "https://dav.example.test/addressbooks/user/default/",
        "user@example.com",
        "secret-contacts-password",
        opener=opener,
    )

    result = client.delete_contact(
        {"url": "https://dav.example.test/addressbooks/user/default/c1.vcf", "etag": '"etag-1"'}
    )

    assert result["deleted"] is True
    assert seen[0].get_method() == "DELETE"
    assert seen[0].headers["If-match"] == '"etag-1"'


def test_delete_contact_refuses_without_an_etag_or_url():
    client = ContactsClient(
        "https://dav.example.test/addressbooks/user/default/",
        "user@example.com",
        "secret-contacts-password",
        opener=lambda request: None,
    )

    with pytest.raises(ContactError, match="resource URL"):
        client.delete_contact({"etag": '"e"'})
    with pytest.raises(ContactError, match="ETag"):
        client.delete_contact({"url": "https://dav.example.test/c1.vcf"})


def test_delete_contact_maps_412_to_nothing_was_deleted():
    def opener(request):
        raise urllib.error.HTTPError(request.full_url, 412, "Precondition Failed", {}, None)

    client = ContactsClient(
        "https://dav.example.test/addressbooks/user/default/",
        "user@example.com",
        "secret-contacts-password",
        opener=opener,
    )

    with pytest.raises(ContactError, match="nothing was deleted"):
        client.delete_contact(
            {"url": "https://dav.example.test/c1.vcf", "etag": '"stale"'}
        )


def test_delete_contact_errors_redact_the_password():
    def opener(request):
        raise urllib.error.URLError("failed for secret-contacts-password")

    client = ContactsClient(
        "https://dav.example.test/addressbooks/user/default/",
        "user@example.com",
        "secret-contacts-password",
        opener=opener,
    )

    with pytest.raises(ContactError) as excinfo:
        client.delete_contact({"url": "https://dav.example.test/c1.vcf", "etag": '"e"'})
    assert "secret-contacts-password" not in str(excinfo.value)


# --- v0.2.17 CLI transfer and lifecycle -----------------------------------


LIFECYCLE_CONTACTS = [
    {
        "id": "contact-a",
        "display_name": "Example Person",
        "given_name": "Example",
        "family_name": "Person",
        "emails": ["person@example.com"],
        "phones": [],
        "organization": "Example Co",
        "url": "https://dav.example.test/ab/contact-a.vcf",
        "etag": '"etag-a"',
        "raw_vcard": (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-a\r\nFN:Example Person\r\n"
            "N:Person;Example;;;\r\nEMAIL:person@example.com\r\nORG:Example Co\r\n"
            "X-KEEP:me\r\nEND:VCARD\r\n"
        ),
    },
    {
        "id": "contact-b",
        "display_name": "Example Person",
        "given_name": "Example",
        "family_name": "Person",
        "emails": ["other@example.com"],
        "phones": ["+3300000000"],
        "organization": "Other Co",
        "url": "https://dav.example.test/ab/contact-b.vcf",
        "etag": '"etag-b"',
        "raw_vcard": (
            "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-b\r\nFN:Example Person\r\n"
            "EMAIL:other@example.com\r\nTEL:+3300000000\r\nORG:Other Co\r\nEND:VCARD\r\n"
        ),
    },
]


class _LifecycleContactsClient:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.contacts = [dict(c) for c in LIFECYCLE_CONTACTS]

    def list_contacts(self, limit=None):
        self.calls.append(("list_contacts", limit))
        return self.contacts[:limit] if limit is not None else list(self.contacts)

    def create_contact(self, vcard, uid):
        self.calls.append(("create_contact", uid))
        return {"uid": uid, "status": 201}

    def update_contact(self, vcard, contact):
        self.calls.append(("update_contact", contact.get("id"), vcard))
        return {"uid": contact.get("id"), "status": 204}

    def delete_contact(self, contact):
        self.calls.append(("delete_contact", contact.get("id"), contact.get("etag")))
        self.contacts = [c for c in self.contacts if c.get("id") != contact.get("id")]
        return {"url": contact.get("url"), "status": 204, "deleted": True}


def _lifecycle_contacts(tmp_path, monkeypatch):
    monkeypatch.setenv("IK_CONFIG_DIR", str(tmp_path / "config"))
    ProfileManager().create_or_update(
        "work",
        contacts_url="https://dav.example.test/ab/",
        contacts_username="user@example.com",
        make_default=True,
    )
    ContactsPasswordStore().save_password("work", "secret-contacts-password")
    created = []

    def factory(*args, **kwargs):
        client = _LifecycleContactsClient()
        created.append(client)
        return client

    monkeypatch.setattr(cli, "ContactsClient", factory)
    return created


def test_cli_contacts_export_writes_vcf_preserving_raw_cards(tmp_path, monkeypatch, capsys):
    _lifecycle_contacts(tmp_path, monkeypatch)
    target = tmp_path / "backup" / "contacts.vcf"

    assert cli.main(["contacts", "export", "--output", str(target), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 2
    assert payload["skipped"] == []
    written = target.read_text(encoding="utf-8")
    assert written.count("BEGIN:VCARD") == 2
    # an unmodeled property survives the export
    assert "X-KEEP:me" in written


def test_cli_contacts_export_refuses_overwrite_without_force(tmp_path, monkeypatch, capsys):
    _lifecycle_contacts(tmp_path, monkeypatch)
    target = tmp_path / "contacts.vcf"
    target.write_text("original", encoding="utf-8")

    assert cli.main(["contacts", "export", "--output", str(target)]) == 1
    assert "Refusing to overwrite" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "original"

    assert cli.main(["contacts", "export", "--output", str(target), "--force"]) == 0


def test_cli_contacts_export_is_read_only(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)

    assert cli.main(["contacts", "export", "--format", "json", "--json"]) == 0

    assert [c[0] for c in clients[0].calls] == ["list_contacts"]


def test_cli_contacts_duplicates_is_read_only_and_groups_by_name(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)

    assert cli.main(["contacts", "duplicates", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 1
    assert payload["groups"][0]["reason"] == "display_name"
    assert {c["id"] for c in payload["groups"][0]["contacts"]} == {"contact-a", "contact-b"}
    assert [c[0] for c in clients[0].calls] == ["list_contacts"]


def test_cli_contacts_merge_unions_fields_and_never_deletes_the_secondary(
    tmp_path, monkeypatch, capsys
):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)

    assert cli.main([
        "--profile", "work", "contacts", "merge", "contact-a", "contact-b", "--yes", "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["merged"] is True
    assert payload["secondary_deleted"] is False
    assert payload["after"]["emails"] == ["person@example.com", "other@example.com"]
    assert payload["after"]["phones"] == ["+3300000000"]
    # the primary wins the organization conflict, and it is reported
    assert payload["after"]["organization"] == "Example Co"
    assert payload["conflicts"][0]["field"] == "organization"
    kinds = [c[0] for c in clients[0].calls]
    assert "delete_contact" not in kinds
    updates = [c for c in clients[0].calls if c[0] == "update_contact"]
    assert updates[0][1] == "contact-a"
    # the unmodeled property must survive the merge write
    assert "X-KEEP:me" in updates[0][2]


def test_cli_contacts_merge_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)

    assert cli.main(["contacts", "merge", "contact-a", "contact-b", "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["merged"] is False
    assert not any(c[0] == "update_contact" for c in clients[0].calls)


def test_cli_contacts_merge_refuses_merging_a_contact_into_itself(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)

    assert cli.main(["contacts", "merge", "contact-a", "contact-a", "--dry-run"]) == 1

    assert "into itself" in capsys.readouterr().err
    assert not any(c[0] == "update_contact" for c in clients[0].calls)


def test_cli_contacts_import_dry_run_reports_collisions_and_writes_nothing(
    tmp_path, monkeypatch, capsys
):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)
    source = tmp_path / "import.vcf"
    source.write_text(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-a\r\nFN:Example Person\r\nEND:VCARD\r\n"
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-new\r\nFN:Brand New\r\nEND:VCARD\r\n",
        encoding="utf-8",
    )

    assert cli.main(["contacts", "import", str(source), "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["total"] == 2
    assert payload["to_create"] == 1
    assert payload["collisions"] == 1
    assert payload["created"] == 0
    kinds = {c[0] for c in clients[0].calls}
    assert "create_contact" not in kinds
    assert "update_contact" not in kinds


def test_cli_contacts_import_skips_collisions_by_default(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)
    source = tmp_path / "import.vcf"
    source.write_text(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-a\r\nFN:Example Person\r\nEND:VCARD\r\n"
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-new\r\nFN:Brand New\r\nEND:VCARD\r\n",
        encoding="utf-8",
    )

    assert cli.main(["--profile", "work", "contacts", "import", str(source), "--yes", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["created"] == 1
    assert payload["updated"] == 0
    assert not any(c[0] == "update_contact" for c in clients[0].calls)


def test_cli_contacts_import_updates_existing_only_when_asked(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)
    source = tmp_path / "import.vcf"
    source.write_text(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:contact-a\r\nFN:Renamed\r\nEND:VCARD\r\n",
        encoding="utf-8",
    )

    assert cli.main([
        "--profile", "work", "contacts", "import", str(source),
        "--update-existing", "--yes", "--json",
    ]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["updated"] == 1
    assert any(c[0] == "update_contact" for c in clients[0].calls)


def test_cli_contacts_import_detects_an_email_collision_without_a_uid_match(
    tmp_path, monkeypatch, capsys
):
    _lifecycle_contacts(tmp_path, monkeypatch)
    source = tmp_path / "import.vcf"
    source.write_text(
        "BEGIN:VCARD\r\nVERSION:3.0\r\nUID:totally-different\r\nFN:Someone\r\n"
        "EMAIL:PERSON@example.com\r\nEND:VCARD\r\n",
        encoding="utf-8",
    )

    assert cli.main(["contacts", "import", str(source), "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["collisions"] == 1
    assert payload["entries"][0]["collision_reason"] == "email"


def test_cli_contacts_delete_dry_run_deletes_nothing(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)

    assert cli.main(["contacts", "delete", "contact-a", "--dry-run", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["deleted"] is False
    assert payload["contact"]["display_name"] == "Example Person"
    assert not any(c[0] == "delete_contact" for c in clients[0].calls)


def test_cli_contacts_delete_uses_the_etag_and_confirms_removal(tmp_path, monkeypatch, capsys):
    clients = _lifecycle_contacts(tmp_path, monkeypatch)

    assert cli.main(["--profile", "work", "contacts", "delete", "contact-a", "--yes", "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["deleted"] is True
    assert payload["confirmed_gone"] is True
    deletes = [c for c in clients[0].calls if c[0] == "delete_contact"]
    assert deletes[0][2] == '"etag-a"'


def test_cli_contacts_lifecycle_writes_require_an_explicit_profile_for_yes(
    tmp_path, monkeypatch, capsys
):
    _lifecycle_contacts(tmp_path, monkeypatch)
    monkeypatch.delenv("IK_PROFILE", raising=False)

    for argv in (
        ["contacts", "delete", "contact-a", "--yes"],
        ["contacts", "merge", "contact-a", "contact-b", "--yes"],
    ):
        assert cli.main(argv) == 1
        assert "profile is explicit" in capsys.readouterr().err


def test_contacts_parser_exposes_lifecycle_but_no_bulk_destruction():
    parser = cli.build_parser()
    contacts_parser = parser._subparsers._group_actions[0].choices["contacts"]
    choices = set(contacts_parser._subparsers._group_actions[0].choices)

    assert {"export", "duplicates", "merge", "import", "delete"} <= choices
    assert not {"sync", "purge", "delete-all", "empty"} & choices
