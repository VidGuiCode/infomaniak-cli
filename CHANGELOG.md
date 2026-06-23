# Changelog

## Unreleased

- Improved kChat auth UX: `ik auth chat --url <url>` can save URL-only config for trusted `*.kchat.infomaniak.com` hosts when a main Informaniak API token exists.
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
