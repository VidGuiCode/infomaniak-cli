# Changelog

## [0.2.6] - 2026-07-14
### Added
- **kDrive:** `ik drive rm <file_id>` moves exactly one resolved file or folder to kDrive trash via
  `DELETE /2/drive/{drive_id}/files/{file_id}`.
  - Resolves metadata first and previews profile, drive, name, type, and id before acting.
  - Protected-write contract: confirmation by default, `--dry-run`, and `--yes` only with an
    explicit profile (`--profile` or `IK_PROFILE`).
  - `--json`/`--compact` return the resolved target, `trashed` state, and undo metadata such as the
    API `cancel_id`; errors continue through the shared secret-redacting API path.
  - Refuses the kDrive root. Permanent, recursive, and bulk deletion are not implemented.

## [0.2.5] - 2026-07-13
### Added
- **Calendar:** `ik calendar create --summary <s> --start <when>` — create an event on your own
  calendar (CalDAV).
  - Writes a minimal iCalendar VEVENT via `PUT {collection}/{uid}.ics` with `If-None-Match: *`
    (never overwrites an existing uid).
  - Protected-write contract: prints a profile/calendar/summary/start/end preview and **requires
    confirmation**; `--dry-run` shows the event + full iCalendar body without writing.
  - `--start`/`--end` take ISO 8601 datetimes (naive = floating local, offset/`Z` = UTC); `--all-day`
    switches to `YYYY-MM-DD` dates. `--end` defaults to +1h (timed) or +1 day (all-day).
  - `--yes` skips the prompt only with an explicit profile (`--profile`/`IK_PROFILE`).
    `--location`/`--description` optional; **no attendees are invited**.
  - `--json`/`--compact` emit the plan plus `{created, event}`.
  - Still excluded: update, delete, RSVP, invites, reminder writes, sync.
- **API/service:** binary-safe iCalendar builder (`build_event_ics`), input parser
  (`parse_event_input`), and `CalendarClient.create_event` (CalDAV PUT).

## [0.2.4] - 2026-07-13
### Added
- **kChat:** `ik chat post "<message>" --channel <slug|id>` — the first kChat write.
  - Posts via Mattermost `POST /api/v4/posts` (channel resolution confirmed live).
  - Follows the protected-write contract: resolves the channel, prints a
    profile/team/channel/message preview, and **requires confirmation** before posting.
  - `--dry-run` resolves the target and shows the plan without posting.
  - `--yes` skips the prompt **only** when the profile is explicit (`--profile` or `IK_PROFILE`),
    so automation cannot post to the wrong account. Empty messages are refused.
  - `--json`/`--compact` emit `{profile, team_id, channel_*, message, posted, post}`.
  - Still excluded: reactions, edits, deletes, channel creation, membership changes, webhooks.

## [0.2.3] - 2026-07-13
### Changed
- **`ik update` is quieter, faster, and self-verifying.**
  - Uses `pip install --upgrade` instead of `--force-reinstall`, so unchanged dependencies
    (keyring and its transitive deps) are no longer torn out and reinstalled on every update.
    This removes most of the installer output and the extra network round-trips.
  - On success, prints a one-line summary (`✓ Updated infomaniak-cli X → Y`) and shows the full
    installer log only on failure or with `--verbose`.
  - Verifies the installed version in a fresh interpreter after installing and reports it.
  - Best-effort removes broken `~*` leftover directories from the venv's site-packages, silencing
    the recurring pip "Ignoring invalid distribution" warning.
### Added
- **`ik update --force`** — opt back into a full `--force-reinstall` (reinstalls dependencies too)
  for recovery. **`ik update --verbose`** — show the full installer log even on success.

## [0.2.2] - 2026-07-13
### Added
- **kDrive:** `ik drive download <file_id>` — download a file's bytes to a local path.
  - Server side is **read-only** (`GET /2/drive/{id}/files/{id}/download`, confirmed live); no
    server-side change is made.
  - Resolves the filename from metadata and **rejects folders** before downloading.
  - `--output <path>` (a directory keeps the remote name; otherwise exact path); defaults to the
    remote name in the current directory.
  - **Never overwrites** an existing local file unless `--force` is given.
  - `--json` / `--compact` machine output with `{name, destination, bytes}`.
- **API:** binary-safe download path (`InformaniakAPIClient.download` + `Transport.download`) that
  returns raw bytes and never UTF-8-decodes the body, so downloaded files are byte-exact.

## [0.2.1] - 2026-07-13
### Fixed
- **kDrive:** `ik drive mkdir` now actually works. The 0.2.0 implementation posted to a
  non-existent endpoint (`POST /2/drive/{id}/files` with `{"type":"dir"}`) and failed with
  `404 method_not_found`.
  - Corrected to the real kDrive endpoint: `POST /2/drive/{id}/files/{parent_id}/directory`
    with body `{"name": ...}`.
  - Creating a folder at the top level now targets the drive root directory (id `1`,
    `visibility: is_root`) instead of relying on fragile child-inspection. `--parent <id>`
    nests under a specific directory.
  - Verified live (create at root + under a parent, listed, then deleted).

## [0.2.0] - 2026-07-13
### Added
- **kDrive:** Introduced `ik drive mkdir <name>`, the first low-risk write command for the 0.2.x line.
  - Safely creates a folder in kDrive without destructive potential.
  - Includes `--parent` flag for nesting.
  - Protected by interactive confirmation prompt.
  - Supports `--yes` flag to bypass prompts for scripting and agent use.

## v0.1.28 - Chat Search Debug (2026-07-13)

- **kChat**: Reverted the `in:` filter injection for channel searches as it causes 0 results on Infomaniak's API for certain channels. Added diagnostic warnings to the local filter to help identify mismatching channel IDs.

## v0.1.27 - Chat Search Polish (2026-07-13)

- **kChat**: `ik chat search ""` now implicitly uses a `*` wildcard instead of failing with HTTP 422.
- **kChat**: `ik chat search --channel <slug>` now correctly passes the `in:<channel>` filter to the Mattermost API, resolving an issue where the API would truncate results before the local filter could apply.
- **Doctor**: Suppressed the `⚠` warning for `chat_explicit_token_configured` if the main token fallback is successfully handling the connection.

## v0.1.26 - DAV Live Validation (2026-07-13)

- **DAV Polish**: Confirmed `0.1.17`'s DAV auto-discovery code against live Infomaniak environments. Discovery and payloads parse perfectly without modification!
- **Docs**: Updated documentation to explicitly point users to `config.infomaniak.com` to generate the correct DAV application passwords, as account-level passwords are rejected.

## v0.1.25 - CLI polish: fix-path and keyring

- **OS Keyring Integration**: Securely store API tokens and app passwords in the native OS credential manager (Windows Credential Locker, macOS Keychain, Linux Secret Service) via the `keyring` library, replacing plaintext token files.
- **Automated PATH Fix**: `ik doctor --fix-path` now permanently applies the required PATH changes to your shell/profile, instead of just printing the preview command.

## v0.1.24 - CLI UX polish and completions

- `ik completion` command added to generate static shell completions for bash, zsh, fish, and powershell.
- `--compact` flag added to all remaining read-only/discovery commands for single-line JSON parity across the suite. Error output is properly formatted as JSON when this flag is provided.

## v0.1.23 - Live-API confirmation (kChat + DAV)

Confirms and fixes the two live-token-gated findings from the `0.1.21` agent test, verified against the real Infomaniak APIs. Read-only; no new runtime dependency; the unit suite stays fully offline (the live shapes are captured as mocked regression tests).

- `ik chat search` no longer fails with "missing order/posts" on a zero-result query. Confirmed live: Infomaniak kChat serializes an empty post map as a JSON **list** (`{"order": [], "posts": []}`) instead of Mattermost's documented object shape. `_ordered_posts` now accepts the list shape (empty or populated) while keeping the documented dict shape working; an empty search exits 0 with `count: 0`.
- `ik contacts list` / `ik calendar today|upcoming` no longer report a silent `0` when the configured DAV URL is not a real collection. Confirmed live: a CardDAV/CalDAV REPORT against the bare `https://sync.infomaniak.com/` base returns an empty multistatus (HTTP 207) with no error. When a read parses zero items, the clients now probe the URL's `resourcetype` (read-only PROPFIND Depth:0, new `dav_discovery.probe_collection`); if the URL is not an addressbook/calendar collection the command fails with an actionable error naming the URL, the `ik auth contacts|calendar` re-discovery path, and the likely cause (the Infomaniak Contacts/Calendar service not yet activated for the user). A real-but-empty collection still returns an empty result.
- `ik auth contacts` / `ik auth calendar` now warn explicitly when auto-discovery finds no collection: reads will fail until a real collection exists.
- Live findings recorded (redacted) in the private live-API notes: kChat empty-list serialization; DAV auth enforced but no principal provisioned for the tested user (`/principals/<user>/` 404s despite being advertised by the server).

## v0.1.22 - Release, CI, and docs hygiene

Bundles the long-deferred release/CI/docs hygiene work with the offline bug fixes surfaced by a hands-on agent test of `0.1.21`, so the fixes land CI-protected.

Bug fixes (from the agent test):

- `ik drive tree` no longer lists folders as their own children/siblings. The kDrive files endpoint can ignore the `parent_id` query param and return the whole drive; `build_folder_tree` now filters children client-side by each item's own `parent_id`.
- `ik mail search` gained structured `--from`/`--to`/`--subject` filters (IMAP FROM/TO/SUBJECT). The positional query is now optional and documented as a plain substring, not a Gmail-style operator.
- `ik chat search --channel` accepts a channel **id or name** (tries name, falls back to id) via a new `ChatClient.resolve_channel`/`get_channel`, with a clearer not-found error pointing at `ik chat channels`.
- `ik mail read --html` prints the raw `text/html` body (plain text stays the default); `fetch_message`/`slim_message` expose `body_html` when present.

CI, packaging, and docs:

- Added `.github/workflows/ci.yml`: the offline pytest suite runs on push and pull request across Linux (Python 3.11–3.13) and one Windows job, plus a package job that builds the wheel/sdist, verifies their contents, and runs the install smoke test.
- Added `scripts/check_package_contents.py`: asserts the built wheel/sdist ship only `infomaniak_cli/**` and never leak `context/`, caches, or credential files.
- Added `CONTRIBUTING.md`, `docs/architecture.md`, and a public `docs/roadmap.md`; fixed the stale wheel version in `docs/release.md`; documented the new mail flags in the README and agent workflow.
- Cleared the `uv build` warnings (dropped the deprecated PEP 639 license classifier; widened the `uv_build` pin to `<0.12.0`).

Read-only; no new runtime dependency. Suite: 469 → 480 passed (3 POSIX-only skipped on Windows).

## v0.1.21 - Agent-readiness pass

- `ik` no longer blocks on a hidden prompt under automation. A run is treated as non-interactive when stdin is not a TTY, when `IK_NO_INTERACTIVE` is set (`1`/`true`/`yes`/`on`), or when a command's `--non-interactive` flag is passed. Centralized this in shared `_is_non_interactive`/`_prompt`/`_confirm` helpers.
- Secret-input commands (`auth token`, `auth mail`, `auth contacts`, `auth calendar`) and `setup` now fail fast with an actionable error naming `--stdin`/`--token`/`--password`/`--profile` instead of hanging on `input()` when non-interactive. The `--stdin` and explicit-value paths are unchanged.
- Confirmation commands (`auth logout`, `profile delete`, `update`) require `--yes` in non-interactive or machine-output (`--json`/`--compact`) mode instead of prompting; a real interactive terminal still prompts as before.
- Documented the stable agent workflow in `docs/agent-workflow.md` (profile precedence, `--json`/`--compact`/`--raw`/`--table`, exit codes, the structured JSON error envelope, non-interactive credential setup, and the recommended command sequence) and linked it from the README.
- Confirmed the `--compact` agent-read contract is consistent across `whoami`, `doctor`, `account services`, `drive list/recent/shared/search/info`, `mail list/unread/search/read/mailboxes/hostings`, `calendar upcoming/today`, `contacts search/show`, and `chat teams/channels/users/search/thread`, and that missing-config errors name the exact `ik … auth …` setup command.
- Read-only only; all changes are local CLI/runtime behavior. New offline tests cover non-interactive detection, fail-fast prompts, `--yes` confirmation gating, the compact-JSON contract, and missing-config error guidance.

## v0.1.20 - Credential-at-rest hardening

- Credential files written by `ik` (the REST API token plus mail/contacts/calendar/kChat app passwords under `tokens/`) are now restricted to the current user at rest: `chmod 0o600` for files and `0o700` for the `tokens/` directory on POSIX, and a best-effort `icacls /inheritance:r /grant:r <user>:F` on Windows.
- Centralized the write path in a new `secure_store.py` (`secure_dir` + `secure_write`) and routed all five secret stores through it, de-duplicating the previous per-store `mkdir`/`write_text`. The Windows `icacls` argv is built by a pure, unit-tested `harden_windows_command()`.
- Hardening is best-effort and never blocks saving: an unsupported filesystem, missing `icacls`, or non-zero `icacls` return degrades to a one-line non-fatal warning while the secret is still written. Permissions are only ever narrowed, and are re-applied on each save so older loose files get tightened on the next write.
- This is defense-in-depth, **not encryption**. An OS keyring backend remains deliberately deferred (it would be the project's first runtime dependency); this patch adds no new dependency and shells out only to the Windows built-in `icacls`.
- Tests stay fully offline: the Windows command builder and its failure paths are asserted with an injected runner, and an autouse fixture swaps the default runner for a no-op so the suite never spawns real `icacls`. Documented the at-rest model in `docs/security.md` and the README Configuration note.

## v0.1.19 - Feedback bug fixes

Fixes for three issues surfaced by a hands-on usage review (`context/feeback/report1.txt`) that exercised every command group:

- Fixed `render_table` crashing on any empty `--table` result. The column width calc collapsed to `max(<int>)` (`TypeError: 'int' object is not iterable`) when there were zero rows; it now wraps the widths in a list so every `--table` command (mailboxes, hostings, services, contacts, calendars, channels, users) renders just the header + separator on an empty result. Added an empty-rows regression test plus a CLI-level empty-table test.
- Updated `docs/release.md` to install from GitHub instead of the broken PyPI commands (`pipx install infomaniak-cli`, `uv tool install infomaniak-cli`, `pip install infomaniak-cli`), matching the README Install section: `git+https://…` installs and a `<tag>`/`<version>` release-wheel option.
- Fixed `ik account products` listing every product as `unnamed`. The products endpoint keys items by `service_name`; `_display_item` now falls back to `service_name`/`customer_name`, and a new `slim_products` projection maps a stable `{id, name, type}`. `ik account products --json` now emits the slim shape by default with `--raw` for the full payload, matching the `account list` pattern.

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
