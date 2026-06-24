# Changelog

## v0.1.18 - Install, update, and PATH polish

- Added read-only install/PATH diagnostics (`pathcheck.py`): resolves the `ik` entry point, the install scripts dir, and whether it is on PATH (case-insensitive, path-normalized).
- `ik doctor` now reports the detected install method and a PATH line — a ✓ when `ik` is on PATH, or a ⚠ plus a copy-pasteable per-user fix command when it is installed but not on PATH. `--json`/`--compact` carry new `install_method` and `path` sections (existing `checks` keys unchanged).
- Added `ik doctor --fix-path`: previews the per-user PATH fix (no system/admin changes) and prints the exact manual command; it is idempotent (says "already on PATH" when fine). Automatic apply is deferred — see below.
- Broadened `ik update` failure hints with specific recovery guidance for uv tool and pip locked-executable/permission failures, and labeled the "unknown install method" fallback command as best-effort.
- Added `scripts/smoke_install.sh`: builds the wheel and verifies it in a throwaway venv (never global, never pipx/uv tool, isolated config). Not part of the default offline unit suite.
- Kept everything read-only except local config; the only PATH-affecting action is the opt-in `--fix-path` preview. Deferred: the environment-mutating `--fix-path` apply (the diagnostic + manual command ship now).
- Fixed a `UnicodeEncodeError` crash in `ik doctor` (and any command printing ✓/⚠) on a default non-UTF-8 Windows console (cp1252) when `PYTHONIOENCODING` was unset; `main()` now reconfigures stdout/stderr to UTF-8 with `errors="replace"` at startup, guarded for streams that do not support it, with offline regression tests.
- Documented that the CLI installs from GitHub (not PyPI): `pipx`/`uv tool`/`pip` install from `git+https://…` or a release wheel.

## v0.1.17 - Contacts/Calendar setup discovery polish

- Added read-only CardDAV/CalDAV collection discovery (`services/dav_discovery.py`) using standard DAV principal -> home-set -> Depth:1 enumeration (RFC 5397/6352/4791).
- `ik auth contacts` now auto-discovers the address-book collection from the default sync base and saves it; with multiple address books it picks a sensible default and lists the rest.
- `ik auth calendar` auto-discovers the calendar collection the same way.
- Added `--no-discover` to save a `--url` verbatim; `--url` remains an explicit override, and discovery never loses the saved password/username.
- Improved "no contacts/calendar configured" errors to mention auto-discovery and the explicit `--url` fallback.
- Kept everything read-only (PROPFIND only); no contact/calendar create/update/delete, RSVP/invite, or bulk import/export. Basic-auth credentials are redacted on every error path.
- Note: DAV discovery targets the standard RFC shapes; live confirmation against `sync.infomaniak.com` is pending.

## v0.1.16 - kChat read polish

- Added `ik chat search "<query>"` to search kChat posts read-only via the Mattermost-compatible post-search endpoint, with `--or`, `--limit`, and `--raw`.
- Added `--channel <slug>` to `ik chat search` to resolve a channel name read-only and filter results to that channel.
- Added `ik chat thread <post_id>` to read a thread read-only, preserving the server's post order.
- Added a stable slim post schema (`id`, `channel_id`, `user_id`, `message`, `type`, `create_at`, ISO-8601 `created_at`).
- Kept all kChat operations read-only; no posting, reactions, edits, deletes, channel creation, membership changes, or webhooks.
- Note: search/thread/channel-by-name target standard Mattermost v4 endpoints; live confirmation against Infomaniak kChat is pending.

## v0.1.15 - kDrive read polish

- Added `ik drive recent` to list files/folders newest-first from the existing read-only files endpoint.
- Added `ik drive shared` with conservative client-side filtering for explicit shared/public/link-visible payload fields.
- Improved slim kDrive file output with safe optional size, MIME type, extension, path hint, and owner display fields when present.
- Improved kDrive human/table rows with size and modified time.
- Kept kDrive operations read-only; no upload, move, delete, share edits, trash, or sync behavior.

## v0.1.14 - Bootstrap service defaults and setup guidance

- Improved `ik bootstrap` with a service readiness summary across auth, account, mail, kDrive, contacts, calendar, and kChat.
- Added `ik bootstrap --compact` for single-line machine-readable readiness JSON.
- Added actionable missing setup commands for optional service credentials without guessing secrets.
- Made bootstrap preserve existing service config/defaults when optional discovery cannot refresh them.
- Simplified Calendar and Contacts auth setup by defaulting to `https://sync.infomaniak.com/` and accepting the Infomaniak sync username directly.
- Expanded `whoami` and `doctor` readiness output while keeping secrets out of all output.
- Kept all Informaniak/kSuite service operations read-only.

## v0.1.13 - Help, command parity, and smoke coverage

- Added help smoke coverage for every implemented top-level command group and important subcommand.
- Made running `ik` without arguments print friendly help and common next steps.
- Cleaned public docs so they do not advertise unimplemented auth, admin, or mail write commands.
- Bumped release metadata to 0.1.13.
- Kept all Informaniak/kSuite service operations read-only.

## v0.1.12 - Output and error contract

- Added central output helpers for pretty JSON, compact JSON, structured error JSON, and simple human tables.
- Added `--compact` single-line slim JSON mode to selected high-value read commands.
- Added `--table` dense human output to selected list/discovery commands.
- Added structured JSON error envelopes for common command errors when machine-readable output is active.
- Documented current exit-code behavior and intended direction.
- Kept all Informaniak/kSuite service operations read-only.

## v0.1.11 - Profile/auth lifecycle polish

- Added `auth logout` with conservative default removal of only the selected profile's main API token.
- Added `auth logout --all` to also remove local mail, contacts, calendar, and chat secrets for the selected profile.
- Added `profile rename` and `profile delete` with local metadata/secret-file handling and current-profile updates.
- Added `IK_PROFILE` support with precedence after explicit `--profile` and before the saved current profile.
- Kept all Informaniak/kSuite service operations read-only; lifecycle commands only mutate local config/secrets.

## v0.1.10 - Mail read full-body UX fix

- `mail read` human output now prints the full readable body text instead of a truncated preview.
- `mail read --json` slim output now includes full `body_text` without requiring `--raw`.
- `body_preview` remains available in raw parsed message payloads and preview-oriented flows.
- HTML-only messages still render as readable text without tags.
- Kept mail read-only with `BODY.PEEK[]`; no SMTP/send, mark-as-read, delete, move, or archive behavior.

## v0.1.9 - Mailbox/account discovery polish

- Added read-only mailbox discovery commands: `mail mailboxes` and alias `mail accounts`.
- Added `mail hostings` using confirmed account product/service discovery data.
- Improved bootstrap default mailbox selection to prefer the authenticated user's mailbox when discovered.
- Improved `whoami` and `doctor` mail state output for IMAP readiness and REST discovery readiness.
- Deferred `mail aliases` until a safe alias endpoint is confirmed.
- Kept mail content commands read-only; no SMTP/send, mark-as-read, delete, move, or archive behavior.

## v0.1.8 - kChat setup discovery

- Improved kChat auth UX: `ik auth chat --url <url>` can save URL-only config for trusted `*.kchat.infomaniak.com` hosts when a main Informaniak API token exists.
- `ik auth chat --url <url>` now accepts kSuite browser kChat URLs, derives the trusted kChat API base, and confirms it with read-only team discovery when possible.
- kChat commands now try an explicit saved chat token first, then the main Informaniak API token only for trusted Infomaniak kChat hosts.
- Added clearer kChat auth state in `ik whoami` and clearer fallback rejection guidance without leaking tokens.

## v0.1.7 - Read-only kChat discovery

- Added explicit kChat/Mattermost-compatible setup with `ik auth chat`.
- Added read-only kChat commands: `chat teams`, `chat channels`, and `chat users`.
- Added stable slim JSON output with `--raw` for full team/channel/user payloads.
- Kept kChat operations read-only; no posting, reactions, edits, deletes, channel creation, membership changes, or webhooks.
- Changed `mail list`, `mail unread`, and `mail search` limits to default to newest matching messages first.
- Added `--oldest-first` for mail listing/search commands when oldest matching messages are desired.

## v0.1.6 - Read-only Calendar

- Added explicit CalDAV calendar setup with `ik auth calendar`.
- Added read-only calendar commands: `calendar list`, `calendar upcoming`, `calendar today`, `calendar search`, and `calendar show`.
- Added conservative stdlib CalDAV/ICS parsing for common calendar and VEVENT fields.
- Added stable slim JSON output with `--raw` for full parsed calendar/event payloads.
- Kept Calendar operations read-only; no create, update, delete, RSVP, invite, reminder write, or sync write behavior.

## v0.1.5 - Read-only Contacts

- Added explicit CardDAV contacts setup with `ik auth contacts`.
- Added read-only contacts commands: `contacts list`, `contacts search`, and `contacts show`.
- Added stable slim JSON output with `--raw` for full parsed contact payloads.
- Kept Contacts operations read-only; no create, update, delete, import, bulk export, or sync write behavior.
- Deferred contact groups until address-book/group discovery is confirmed cleanly.

## v0.1.4 - Read-only kDrive browsing

- Added `ik drive folders` to list folders from the confirmed kDrive files endpoint.
- Added `ik drive tree` for shallow, bounded folder-tree browsing.
- Added folder-only filtering, parent selection, depth, limit, slim JSON, and raw JSON support.
- Kept kDrive operations read-only; no download, upload, move, delete, share edits, trash, or sync behavior.

## v0.1.3 - Self-update command

- Added `ik update` to check the latest GitHub release and update supported installs.
- Added `--check`, `--yes`, `--json`, and `--dry-run` update modes.
- Detects pipx, uv tool, pip, source checkout, and unknown install methods conservatively.
- Keeps source checkout updates manual and avoids profile/token/config mutation.

## v0.1.2 - Read-only kDrive

- Added read-only kDrive commands: `drive list`, `drive search`, and `drive info`.
- Added stable slim JSON output with `--raw` for full API item payloads.
- Added default kDrive selection from profiles with `--drive-id` overrides.
- Kept kDrive operations read-only; no download, upload, move, delete, share edits, or sync behavior.

## v0.1.1 - Read-only mail

- Added IMAP mailbox setup with `ik auth mail`.
- Added read-only mail commands: `mail folders`, `mail labels`, `mail list`, `mail unread`, `mail search`, `mail read`, and `mail threads`.
- Added folder, date, unread, JSON, and raw-output support across mail reads.
- Added `mail read --folder` and `mail threads` conversation grouping via message headers.
- Improved IMAP error formatting for missing folders.
- Documented the Infomaniak mailbox device-password setup flow.

## v0.1.0 - CLI foundation

- Added the initial `ik` CLI package.
- Added profile setup, token auth, diagnostics, account discovery, bootstrap, and read-only kDrive listing foundation.
