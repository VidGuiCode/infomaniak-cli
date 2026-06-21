# infomaniak-cli

`infomaniak-cli` is planned as a unified command-line bridge for Informaniak and kSuite, with a short executable command named `ik`.

The goal is to give Gui and Hermes one clean interface for company and personal Informaniak accounts without building one separate MCP integration per service.

## Short vision

Build one CLI first:

```bash
ik setup
ik whoami
ik doctor
ik mail unread
ik drive search "invoice"
ik admin mailboxes
ik chat post --channel admin "Reminder: VAT task due"
```

Then, once the CLI is stable, optionally expose the same functionality through one MCP server:

```text
Informaniak APIs / IMAP / SMTP / CalDAV / CardDAV
              ↓
      infomaniak-cli Python library
              ↓
          CLI command: ik
              ↓
        optional MCP wrapper
```

## Why CLI-first, MCP-later

MCP is useful, but the hard part is authentication, account selection, service discovery, and safe actions. A CLI-first design is easier to debug, script, test, and use outside Hermes. The MCP server can later call the same internal code.

Benefits:

- one authentication/config system;
- works in Hermes through terminal commands immediately;
- works in cron jobs and scripts;
- easier debugging than MCP-only;
- one future MCP server instead of one MCP per kSuite service.

## Project naming

- Repository/folder name: `infomaniak-cli`
- Installed command name: `ik`

This keeps the repo descriptive while the command stays short.

## kSuite / Informaniak scope

Based on the current product/API review, kSuite includes or relates to:

- Mail
- kDrive
- kChat
- kMeet
- SwissTransfer
- online office/collaboration with Microsoft Office or OnlyOffice
- privacy/security features
- kSuite Pro AI features such as editorial assistant, scheduled send, event planning, smart reminders, OCR search, audio transcription, and automatic translation

Informaniak developer APIs cover useful areas including:

- Core resources / profile / accounts / products / kSuite
- Mail services and mailbox administration
- kDrive
- kChat
- kMeet
- domains/DNS

Some user-data services may need standard protocols instead of the REST API:

- actual email reading/sending: IMAP/SMTP
- calendar: CalDAV
- contacts: CardDAV

## Initial MVP

The first useful version should focus on read-first, safe company administration:

```bash
ik setup
ik whoami
ik doctor

ik admin accounts
ik admin products
ik admin mailboxes
ik admin aliases

ik mail unread
ik mail search "query"
ik mail read <message_id>

ik drive list
ik drive search "query"
ik drive download <file_id>

ik chat channels
ik chat post --channel <id> "message"
```

Writes/sends/deletes should be explicit and protected by confirmations.

## Current development baseline

A minimal Python/uv foundation is in place:

- console command: `ik`
- setup-created profiles: `ik setup --profile cylro --non-interactive`
- local diagnostics: `ik whoami`, `ik doctor`
- profile management: `ik profile list/show/use`
- token placeholder commands: `ik auth status/token`
- pytest coverage for config paths, profiles, auth token storage, redaction, and CLI smoke

Run tests on this Windows/Git-Bash environment with a repo-local temp folder:

```bash
mkdir -p .tmp
TMPDIR="$PWD/.tmp" TEMP="$PWD/.tmp" TMP="$PWD/.tmp" uv run pytest -q
```

Smoke test:

```bash
IK_CONFIG_DIR="$PWD/.tmp/manual-config" uv run ik setup --profile cylro --non-interactive
IK_CONFIG_DIR="$PWD/.tmp/manual-config" uv run ik whoami --json
IK_CONFIG_DIR="$PWD/.tmp/manual-config" uv run ik doctor --json
```

## Documentation

See:

- [`docs/vision.md`](docs/vision.md) — full product vision and service mapping
- [`docs/setup-and-profiles.md`](docs/setup-and-profiles.md) — setup/auth/profile flow
- [`docs/commands.md`](docs/commands.md) — proposed CLI commands
- [`docs/security.md`](docs/security.md) — safety, secrets, profile separation
