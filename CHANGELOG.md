# Changelog

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
