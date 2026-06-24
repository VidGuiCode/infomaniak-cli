# Proposed CLI Commands

The installed command should be `ik`.

## Command taxonomy

Use these command layers consistently:

- `setup` / `bootstrap` / `whoami` / `doctor`: configure and diagnose the local profile.
- `account`: discover the logged-in user's accessible Informaniak environment.
- `mail`, `drive`, `chat`, `meet`, `calendar`, `contacts`: use a service as the selected profile.
- Manager/admin operations are deferred until a separate, explicit surface is designed and implemented.

Important naming rule:

```text
Discovery of what the current user can access belongs under `account`.
Company/account administration is not implemented in this CLI yet.
```

## Setup and diagnostics

```bash
ik setup
ik setup --profile work
ik whoami
ik doctor
ik bootstrap
ik bootstrap --compact
ik update
```

Expected behavior:

- `setup`: create/update a profile, authenticate, discover services, choose defaults, run doctor.
- `whoami`: show active profile/account/user/default services and readiness.
- `doctor`: verify auth and configured service setup state.
- `bootstrap`: rerun autodiscovery, safely update defaults, and show missing setup actions.
- `update`: check GitHub releases and update supported installs.

Update flags:

```bash
ik update --check    # check only; never install
ik update --yes      # update without prompting when auto-update is safe
ik update --json     # machine-readable status; no prompt/install unless combined with --yes
ik update --dry-run  # show the updater command without running it
```

## Profiles

```bash
ik profile list
ik profile show
ik profile use work
ik profile rename old new
ik profile delete old --yes
```

Every command should support:

```bash
ik --profile work <command>
IK_PROFILE=work ik <command>
```

Profile selection precedence is: explicit `--profile`, then `IK_PROFILE`, then the saved current profile. If `IK_PROFILE` names a missing profile, commands fail instead of falling back to the saved current profile.

`profile rename` renames local profile metadata and related local secret files. `profile delete --yes` removes only the named local profile and its related local secrets; it never touches remote services.

## Auth

```bash
ik auth token
ik auth token --stdin
ik auth check
ik auth status
ik auth logout
ik auth logout --all --yes
ik auth mail --mailbox user@example.com --password <mailbox-device-password>
ik auth contacts --url <carddav-address-book-url> --username user@example.com --password <carddav-password>
ik auth calendar --url <caldav-calendar-url> --username user@example.com --password <caldav-password>
ik auth chat --url <kchat-base-url> --token <kchat-token> --team-id <team_id>
```

`auth token` stores the selected profile's main Informaniak API token. `auth check` verifies that token with a read-only authenticated API request.

`auth logout` removes the selected profile's main Informaniak API token by default. Add `--all` to also remove local mail, contacts, calendar, and chat secrets for that profile. It never contacts or changes remote services.

`auth contacts` stores explicit CardDAV contacts credentials. It does not reuse mail credentials automatically.

`auth calendar` stores explicit CalDAV calendar credentials. It does not reuse mail or contacts credentials automatically.

`auth chat` stores kChat/Mattermost-compatible connection settings. It accepts either the kSuite browser URL or a direct trusted API base. For kSuite URLs like `https://ksuite.infomaniak.com/<account_id>/kchat/<workspace>/channels/<channel>`, the CLI parses the account ID, workspace slug, and optional channel slug, derives `https://<workspace>.kchat.infomaniak.com`, and confirms it with read-only `GET /api/v4/users/me/teams` when a main Informaniak API token exists. The main token is never sent to arbitrary user-provided hosts.

## Account / environment discovery

These commands describe what the authenticated user/profile can access. An employee could run these if their Informaniak rights allow it.

```bash
ik account list
ik account products
ik account products --account-id <id>
ik account services
ik account services --account-id <id>
```

These commands stay read-only and intentionally cover user-accessible discovery, not company/account administration.

## Admin / Informaniak Manager

Reserve `admin` for true company/account administration — the things normally done by an Informaniak Manager admin, not normal employee service usage.

Current state:

```text
No Manager/admin commands are implemented yet.
```

Rules:

- start read-only;
- require actual account/admin rights;
- clearly show active profile and selected account;
- protect all writes with confirmation;
- do not use `admin` for generic bootstrap/discovery commands.

## Mail

Read-only commands:

```bash
ik auth mail --mailbox user@example.com --password <app-password>

ik mail mailboxes           # or ik mail accounts
ik mail hostings --json
ik mail folders              # or ik mail labels
ik mail list                 # both read and unread; default folder INBOX
ik mail list --folder Spam --days 5 --json
ik mail list --limit 10      # newest 10 matching messages by default
ik mail list --limit 10 --oldest-first
ik mail list --since 2026-06-01 --before 2026-06-15 --json
ik mail unread               # shortcut for ik mail list --unread
ik mail unread --folder Sent --since 2026-06-01 --json
ik mail search "invoice" --days 30 --json
ik mail read <uid> --folder Spam --json
ik mail threads --folder Sent --days 7 --json
```

`ik mail mailboxes` lists configured/discovered mailbox addresses. Without an API token it can still show the profile's configured default mailbox. With a main Informaniak API token and a discovered mail hosting ID, it uses the confirmed read-only `GET /1/mail_hostings/{mail_hosting_id}/mailboxes` endpoint. `ik mail accounts` is an alias.

`ik mail hostings` lists mail hosting resources from the selected account's confirmed products/services discovery endpoints. `ik mail aliases` is deferred until a safe alias endpoint is confirmed.

Mailbox discovery is separate from IMAP content access: `ik mail list`, `ik mail unread`, `ik mail read`, `ik mail search`, and `ik mail threads` still require `ik auth mail` with the mailbox device password from the mail setup flow.

`ik mail list` defaults to the `INBOX` folder and shows both read and unread messages. Limited mail results are newest-first by default; add `--oldest-first` to show the oldest matching messages first. Each message in JSON output includes a `seen` boolean. `--days N` is a convenience shortcut for `--since` set to `today - N days`.

`ik mail unread` accepts the same folder, limit, ordering, and date filters as `ik mail list`. `ik mail read` also accepts `--folder` so you can read messages from any folder by UID. Human output prints the full readable body text, and slim JSON includes full `body_text` without requiring `--raw`; `--raw` keeps fuller parsed message metadata such as `body_preview`. `ik mail threads` groups messages into conversation threads using `In-Reply-To` and `References` headers.

Mail sending, drafts, mark-as-read, delete, move, and archive are not implemented.

## kDrive

Read-only commands:

```bash
ik drive list
ik drive list --parent <folder_id> --limit 20 --json
ik drive folders
ik drive folders --parent <folder_id> --limit 20 --json
ik drive tree
ik drive tree --depth 2 --limit 20 --json
ik drive search "RCS"
ik drive info <file_id>
```

`ik drive list` uses the selected profile's default kDrive ID and calls `GET /2/drive/{drive_id}/files`. Use `--drive-id <id>` to override the profile default. `--parent <folder_id>` is passed to the same endpoint as `parent_id`.

`ik drive folders` uses the same files endpoint and filters the returned items to folders/directories only. It supports `--drive-id`, `--parent`, `--limit`, `--json`, and `--raw`.

`ik drive tree` builds a shallow read-only folder tree from repeated files endpoint calls with `parent_id` filtering. It defaults to `--depth 2`; use lower depth for cheaper checks. `--limit` applies per folder request.

`ik drive search <query>` is currently implemented by listing files and filtering by file/folder name client-side because no separate search endpoint has been confirmed. `ik drive info <file_id>` is currently implemented by finding the item in the list endpoint response because no single-file metadata endpoint has been confirmed.

Not implemented in v0.1.7: download, upload, move, delete, share changes, trash, recursive sync, or any write behavior.

## kChat

Read-only commands:

```bash
ik auth chat --url https://ksuite.infomaniak.com/<account_id>/kchat/<workspace>/channels/<channel>
ik auth chat --url <kchat-base-url> --token <kchat-token> --team-id <team_id>
ik auth chat --url https://<workspace>.kchat.infomaniak.com

ik chat teams
ik chat teams --json
ik chat channels --team-id <team_id> --limit 50 --json
ik chat users --team-id <team_id> --limit 50 --json
```

`ik chat teams` uses the configured kChat API base URL and calls the Mattermost-compatible `GET /api/v4/users/me/teams` endpoint. Authentication order is explicit saved kChat token first, then the saved main Informaniak API token only for trusted `*.kchat.infomaniak.com` hosts.

`ik chat channels` lists channels for a team using `GET /api/v4/teams/{team_id}/channels`. If no team is saved and the profile has access to exactly one team, that team is used. Otherwise pass `--team-id <id>` or save one with `ik auth chat --team-id <id>`.

`ik chat users` lists users for a team using `GET /api/v4/users?in_team={team_id}`.

If the trusted-host fallback is rejected, save a dedicated token with `ik auth chat --url <url> --stdin`.

Not implemented in v0.1.7: posting, reactions, edits, deletes, channel creation, membership changes, webhooks, post search, or thread display.

## kMeet

```bash
ik meet rooms
ik meet create-room --name "Example Admin"
ik meet settings <room_id>
```

Lower priority.

## Contacts

Read-only commands:

```bash
ik auth contacts --url <carddav-address-book-url> --username user@example.com --password <carddav-password>

ik contacts list
ik contacts list --limit 50 --json
ik contacts search "accountant"
ik contacts search "example.com" --json
ik contacts show <contact_id> --json
ik contacts show <contact_id> --json --raw
```

`ik contacts list`, `ik contacts search`, and `ik contacts show` use a configured CardDAV address-book collection URL. JSON output defaults to a stable slim contact schema. Add `--raw` with `--json` to include the full parsed contact payload, including the raw vCard text when available.

Search is client-side and matches available name, email, phone, and organization fields case-insensitively.

Not implemented in v0.1.5: contact create, update, delete, import, bulk export, sync writes, or groups. `contacts groups` is deferred until address-book/group discovery is confirmed cleanly.

## Calendar

Read-only commands:

```bash
ik auth calendar --url <caldav-calendar-url> --username user@example.com --password <caldav-password>

ik calendar list
ik calendar list --json
ik calendar today
ik calendar today --calendar <calendar_id_or_url> --json
ik calendar upcoming --days 14
ik calendar upcoming --days 30 --limit 20 --json
ik calendar search "invoice" --days 30 --json
ik calendar show <event_id> --json
ik calendar show <event_id> --json --raw
```

`ik calendar list`, `ik calendar upcoming`, `ik calendar today`, `ik calendar search`, and `ik calendar show` use a configured CalDAV calendar collection URL. JSON output defaults to stable slim calendar/event schemas. Add `--raw` with `--json` to include full parsed calendar/event payloads, including raw ICS text for events when available.

Search is client-side and matches available summary, description, location, organizer, and attendee fields case-insensitively.

Not implemented in v0.1.6: event create, update, delete, RSVP, invites, reminder writes, or sync writes.

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

Compact single-line slim JSON:

```bash
ik doctor --compact
ik bootstrap --compact
ik drive search "invoice" --compact
ik mail read <uid> --compact
```

Dense human table mode:

```bash
ik drive list --table
ik account services --table
ik chat users --table
```

`--compact` implies machine-readable JSON and does not require `--json`. `--table` is human-facing and not a stable machine contract. `--table` cannot be combined with `--json` or `--compact`.

When `--json` or `--compact` is active, common command errors use this stderr shape:

```json
{"error":{"exit_code":1,"message":"No profile selected. Run `ik setup --profile <name>` first.","type":"missing_profile"}}
```

Current exit-code reality:

- `0`: success
- `1`: general runtime/config/auth/API error
- `2`: some validation/usage errors, especially parser errors and legacy mail date validation

Future versions may split missing config, auth failures, and network/API unavailable into more specific codes.

## Safety flags

```bash
--profile <name>   # force profile
--json             # JSON output
--compact          # single-line slim JSON
--table            # dense human-readable table where supported
--yes              # skip confirmation for safe scripted writes only
--dry-run          # show what would happen
```

Destructive commands should require explicit flags and confirmations.
