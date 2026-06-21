# infomaniak-cli Vision

## Goal

Create a unified Informaniak/kSuite CLI called `ik` that lets Gui and Hermes work with company and personal Informaniak accounts safely.

The CLI should reduce friction around:

- finding account IDs and product IDs;
- discovering mail hostings, mailboxes, kDrives, kChat teams, and kSuite products;
- separating personal vs company accounts;
- reading company/admin emails;
- locating kDrive documents;
- posting kChat updates;
- later exposing the same integration through one MCP server.

## Core design principle

Do **not** create one MCP per service.

Instead:

```text
One shared connector layer
One CLI command: ik
One optional MCP server later
Multiple service modules inside the same project
```

## Target architecture

```text
infomaniak-cli/
  src/infomaniak_cli/
    cli.py              # Typer/Click command entrypoint
    config.py           # profile + config loading
    auth.py             # OAuth/token/app-password handling
    bootstrap.py        # autodiscovery of accounts/products/services
    api.py              # REST API client
    profiles.py         # profile management
    services/
      account.py        # user-accessible accounts, products, services
      admin.py          # true Manager admin later: users, permissions, aliases, domains
      mail.py           # IMAP/SMTP and/or mail API helpers
      drive.py          # kDrive files/search/download/upload
      chat.py           # kChat channels/messages/files
      meet.py           # kMeet rooms/settings
      calendar.py       # CalDAV later
      contacts.py       # CardDAV later
    mcp_server.py       # optional later wrapper
  docs/
```

## Service mapping

| Service | First connector | Why |
|---|---|---|
| Account/profile/product discovery | Informaniak REST API | User-accessible environment discovery for bootstrap and profile setup |
| True Manager/admin management | Informaniak REST API | Only for profiles with admin rights: users, mail hostings, aliases, permissions, domains |
| Actual email content | IMAP/SMTP | More reliable for reading/sending real mailbox messages |
| kDrive | Informaniak REST API | APIs exist for drives, files, download, upload, search, access, trash, activities |
| kChat | kChat API | API exists for users, teams, channels, posts, files, webhooks, etc. |
| kMeet | Informaniak REST API | Useful but limited; room creation/settings appear to be available |
| Calendar | CalDAV | Likely better than forcing REST |
| Contacts | CardDAV | Likely better than forcing REST |
| SwissTransfer | Later/optional | Lower priority unless an API or concrete workflow is needed |

## MVP philosophy

Start read-only and discovery-focused.

The first version should help answer:

- Who am I logged in as?
- Which Informaniak account/profile is active?
- What products/services are available?
- Which mailboxes and aliases exist?
- What unread company emails need attention?
- Where is a document in kDrive?
- Can we post a controlled message to kChat?

Do not start with destructive automation.

## Hermes integration

Hermes can use the CLI immediately through terminal commands:

```bash
ik --profile cylro mail unread
ik --profile cylro drive search "RCS"
ik --profile cylro account services
```

Later, the project can expose one MCP server that wraps the same modules:

```yaml
mcp_servers:
  informaniak:
    command: "python"
    args: ["-m", "infomaniak_cli.mcp_server"]
```

Potential MCP tool names:

- `informaniak_whoami`
- `informaniak_mail_search`
- `informaniak_mail_read`
- `informaniak_drive_search`
- `informaniak_drive_download`
- `informaniak_chat_post`
- `informaniak_account_services`
- `informaniak_admin_mailboxes` later for true Manager/admin use


## Discovery vs admin boundary

The CLI has two different layers that must stay separate:

```text
account/bootstrap discovery = what the logged-in user can access
admin/manager = real company-account administration requiring admin rights
```

So account/product/service discovery should live under `ik account ...`, while `ik admin ...` is reserved for true Informaniak Manager actions such as users, permissions, aliases, domains, and all-company mailbox administration.
