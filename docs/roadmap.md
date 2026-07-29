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

Releases use normal semantic patch versions only. A follow-up fix takes the next
patch version, never a `.postN` release.

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

- **`0.2.12` — kDrive reversible workflows:** single-file upload refuses remote overwrite;
  exact move/rename and trash restore use before/after preview, confirmation, dry-run,
  explicit-profile-gated `--yes`, and readback. Trash list/show and exact share state are read-only.
  Share writes and permanent, recursive, bulk, empty-trash, chunked, or sync operations remain out.

- **`0.2.11` — Calendar lifecycle:** exact-target event update uses CalDAV ETags and preserves
  unmodeled ICS/alarm content; soft cancellation and explicitly acknowledged hard deletion share
  the protected-write/readback contract. Attendee-bearing events and RSVP/invite behavior remain
  disabled until notification effects are verified. Patch `0.2.11.post1` also refuses
  multi-VEVENT recurrence resources until one instance can be targeted safely.

- **`0.2.10` — products/services discovery cleanup:** `account services` is now the primary,
  normalized workflow inventory with actionability and next-command hints; `account products`
  remains available as lower-level catalog/debug data.

- **`0.2.9` — protected Mail draft/send:** plain-text IMAP drafts and SMTP-over-SSL sends use the
  fixed profile mailbox, preview all recipients and content, confirm by default, support offline
  `--dry-run`, and gate unattended `--yes` on an explicit profile.

- **`0.2.8` — protected Contacts writes:** create uses collision-safe CardDAV PUT; update resolves
  one contact, preserves unmodeled vCard properties, and uses ETag `If-Match` protection. Both
  require preview/confirmation and support `--dry-run` plus explicit-profile-gated `--yes`.

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

## Next (`0.2.x`)

- **`0.2.13` — Calendar administrative essentials:** create-time reminders, duplicate-safe
  (idempotent) event creation, automatic repair when the saved CalDAV URL is only the service root,
  richer `calendar search` filters, and read-only `ics`/`json` export for audit and backup. No
  third-party notification effect, so it ships on the existing protected-write contract.
- **`0.2.14` — Calendar collaboration:** attendees, invitations, recurrence (`--rrule` and explicit
  date series), contact-name resolution for attendees, and bulk event import. Attendee and invite
  writes stay disabled until Infomaniak's CalDAV notification behavior is verified live, because
  they email real people; recurrence edits need exact single-instance targeting first.
- **`0.2.15` — Mail attachments and lifecycle:** attachment save/send, UID-based reply/forward,
  mark/flag, move/archive, and draft management with normalized local paths.
- **`0.2.16` — kChat conversation lifecycle:** thread replies, reactions, own-post editing,
  attachments, and exact-target own-post deletion. Workspace administration stays out.
- **`0.2.17` — Contacts transfer/lifecycle:** full-fidelity export, richer fields, duplicate/merge
  previews, collision-safe import, and exact-target single-contact deletion.
- **`0.2.18` — Shared write safety/readiness:** stable JSON action/result schemas, result readback,
  before/after diffs, idempotency keys, explicit partial-failure and notification-sent reporting,
  common path normalization, and write-capability checks in doctor.
- **`0.2.19` — Bootstrap multi-service selection:** deterministic interactive and non-interactive
  selection when discovery finds multiple drives or other same-family services.

## Later

- **`0.3.x`** adds a true admin/Manager layer, read-only first, for operations that genuinely
  require company-admin rights.
- **`0.4.x`** may add an optional MCP wrapper around stable CLI functions.
- Irreversible, recursive, bulk, and admin-scoped operations remain excluded until individually
  designed and explicitly approved; planned single-resource cleanup commands retain full guardrails.

This roadmap describes direction, not commitments or dates.
