# Proposed CLI Commands

The installed command should be `ik`.

## Command taxonomy

Use these command layers consistently:

- `setup` / `bootstrap` / `whoami` / `doctor`: configure and diagnose the local profile.
- `account`: discover the logged-in user's accessible Informaniak environment.
- `mail`, `drive`, `chat`, `meet`, `calendar`, `contacts`: use a service as the selected profile.
- `admin`: true Informaniak Manager / company-admin operations only, and only when the profile has those rights.

Important naming rule:

```text
Discovery of what the current user can access is not admin.
Admin means real company/account administration.
```

## Setup and diagnostics

```bash
ik setup
ik setup --profile work
ik whoami
ik doctor
ik bootstrap
```

Expected behavior:

- `setup`: create/update a profile, authenticate, discover services, choose defaults, run doctor.
- `whoami`: show active profile/account/user/default services.
- `doctor`: verify auth and configured services.
- `bootstrap`: rerun autodiscovery and update saved IDs/defaults.

## Profiles

```bash
ik profile list
ik profile show
ik profile use work
ik profile rename old new
ik profile delete old
```

Every command should support:

```bash
ik --profile work <command>
```

## Auth

```bash
ik auth login
ik auth login --new-profile personal
ik auth status
ik auth logout
ik auth refresh
```

`auth login` should route to setup if needed.

## Account / environment discovery

These commands describe what the authenticated user/profile can access. An employee could run these if their Informaniak rights allow it.

```bash
ik account list
ik account products
ik account products --account-id <id>
ik account services
ik account services --account-id <id>
```

Read-only at first. These replace the earlier misleading `ik admin accounts/products/services` names.

## Admin / Informaniak Manager

Reserve `admin` for true company/account administration — the things normally done by an Informaniak Manager admin, not normal employee service usage.

Future read-only/admin commands may include:

```bash
ik admin users
ik admin permissions
ik admin mail-hostings
ik admin mailboxes
ik admin aliases
ik admin domains
```

Rules:

- start read-only;
- require actual account/admin rights;
- clearly show active profile and selected account;
- protect all writes with confirmation;
- do not use `admin` for generic bootstrap/discovery commands.

## Mail

Initial read-only commands:

```bash
ik mail unread
ik mail search "invoice"
ik mail read <message_id>
ik mail threads --since 7d
```

Later write commands:

```bash
ik mail draft --to accountant@example.com --subject "VAT question" --body-file reply.md
ik mail send --draft <draft_id>
ik mail send --to accountant@example.com --subject "VAT question" --body "..."
```

Sending should confirm profile/from/to unless `--yes` is provided.

## kDrive

```bash
ik drive list
ik drive search "RCS"
ik drive info <file_id>
ik drive download <file_id>
ik drive upload ./file.pdf /Admin/
ik drive share-info <file_id>
```

Uploads/moves/deletes should require confirmation in early versions.

## kChat

```bash
ik chat teams
ik chat channels
ik chat post --channel admin "Message"
ik chat search "Dolibarr"
ik chat thread <post_id>
```

Posting should show active profile/team/channel before sending.

## kMeet

```bash
ik meet rooms
ik meet create-room --name "Example Admin"
ik meet settings <room_id>
```

Lower priority.

## Calendar / Contacts

Later via CalDAV/CardDAV:

```bash
ik calendar today
ik calendar upcoming --days 14
ik contacts search "accountant"
ik contacts show <contact_id>
```

## Output modes

Human-readable by default:

```bash
ik mail unread
```

Machine-readable for Hermes/scripts:

```bash
ik mail unread --json
ik drive search "invoice" --json
```

Compact mode:

```bash
ik doctor --compact
```

## Safety flags

```bash
--profile <name>   # force profile
--json             # JSON output
--compact          # shorter output
--yes              # skip confirmation for safe scripted writes only
--dry-run          # show what would happen
```

Destructive commands should require explicit flags and confirmations.
