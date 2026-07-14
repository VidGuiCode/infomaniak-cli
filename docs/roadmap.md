# Roadmap

`infomaniak-cli` is built in deliberate stages. The guiding rule: stay
**read-only** and become boringly reliable for everyday and agent use before any
write behavior is added.

## Versioning intent

- **`0.1.x`** — the foundation: read-only service coverage, setup/discovery,
  profile and runtime polish, stable output contracts, packaging/CI hygiene, and
  agent-safe UX.
- **`0.2.x`** — carefully protected, low-risk writes (with confirmation and
  `--dry-run`), only once the `0.1.x` basics are stable.
- **`0.3.x`** — a true admin/Manager layer, only for operations that genuinely
  require company-admin rights.
- **`0.4.x`** — an optional MCP wrapper around the stable CLI functions.
- **`1.0.0`** — stable MVP: safe daily use, documented and tested.

## Shipped (`0.1.x`)

- Foundation: `setup`, profiles, token auth, `doctor`, account discovery,
  `bootstrap`.
- Read-only **mail** over IMAP: folders/labels, list, unread, search, read,
  threads, mailboxes/hostings.
- Read-only **kDrive**: list, folders, tree, recent, shared, search, info.
- Read-only **Contacts** (CardDAV) and **Calendar** (CalDAV), with collection
  auto-discovery.
- Read-only **kChat** (Mattermost-compatible): teams, channels, users, search,
  thread.
- Output & error contract: `--json`, `--compact`, `--table`, `--raw`, structured
  JSON errors, documented exit codes.
- Profile/auth lifecycle, install/PATH diagnostics, self-update.
- Credential files written owner-only at rest (defense in depth, not encryption).
- Agent-readiness: no hidden prompts under automation, a documented agent
  workflow ([agent-workflow.md](agent-workflow.md)).

## Shipped recently

- **`0.2.7` — Calendar history and CLI ergonomics:** explicit `calendar search --from/--to`
  ranges, global `--profile`/`--base-url` placement at any command depth, Windows/MSYS kDrive
  download-path translation, and pipx stale-metadata guidance.

- **`0.2.6` — protected kDrive trash:** `ik drive rm <file_id>` resolves and previews one
  file/folder, confirms by default, supports `--dry-run`, and permits unattended `--yes` only
  with an explicit profile. It moves the item to undoable trash; permanent, recursive, and bulk
  deletion remain excluded.

- **`0.1.22` — Release, CI & docs hygiene** (plus offline bug fixes): a CI
  workflow running the offline suite on Linux + Windows, packaging verification,
  contributor/architecture docs, and fixes surfaced by hands-on testing
  (kDrive `tree` nesting, `mail search --from/--to/--subject`, `chat search
  --channel` by id or name, `mail read --html`).
- **`0.1.23` — Live-API confirmation**: the kChat search/thread response shape
  confirmed live and handled (empty results no longer error), and
  contacts/calendar reads now distinguish a real-but-empty collection from a
  misconfigured or unprovisioned CardDAV/CalDAV URL with an actionable error.

## In progress / next

- **`0.1.24` — CLI polish**: shell completion (`ik completion
  bash|zsh|fish|powershell`) and `--compact` output-mode parity across the
  remaining read commands.

## Later

- **`0.2.x`** introduces protected writes behind a confirmation + `--dry-run`
  contract: kDrive download, kChat posting, calendar/contact creation, and mail
  drafts/send — each showing profile/account/target/action before acting.
- A true admin/Manager layer and an optional MCP wrapper follow once the CLI is
  solid.

This roadmap describes direction, not commitments or dates.
