# Proposed CLI Commands

The installed command should be `ik`.

## Setup and diagnostics

```bash
ik setup
ik setup --profile cylro
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
ik profile use cylro
ik profile rename old new
ik profile delete old
```

Every command should support:

```bash
ik --profile cylro <command>
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

## Admin / discovery

```bash
ik admin accounts
ik admin products
ik admin services
ik admin users
ik admin teams
ik admin mail-hostings
ik admin mailboxes
ik admin aliases
```

Read-only at first.

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
ik meet create-room --name "Cylro Admin"
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
