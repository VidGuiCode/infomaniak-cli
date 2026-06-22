# Changelog

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
