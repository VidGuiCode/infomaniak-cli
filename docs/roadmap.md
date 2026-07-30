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

## Shipped (`0.2.13` – `0.2.21`)

The `0.2.x` line is complete in intent: all five services (drive, mail, calendar, contacts, chat)
have reads plus protected-write lifecycles.

- **`0.2.13`** — Calendar administrative essentials: create-time reminders, duplicate-safe create,
  discovery repair, richer search filters, read-only export.
- **`0.2.14`** — Calendar recurrence: `--rrule` on create and `create-series` with deterministic
  per-date UIDs. Attendees/invitations were split out and stay gated on a live notification probe.
- **`0.2.15`** — Mail attachments and message lifecycle (reply/forward, mark/flag, move, drafts).
- **`0.2.16`** — kChat conversation lifecycle (reply, reactions, edit, attachments, own-post delete).
- **`0.2.17`** — Contacts transfer and lifecycle (export, duplicates/merge, import, delete).
- **`0.2.18`** — Shared write-safety contract, machine-enforced by parser-introspecting tests.
- **`0.2.19`** — Bootstrap multi-service selection: no more silent first-match defaults.
- **`0.2.20`** — Opt-in DAV credential reuse and address-book selection.
- **`0.2.21`** — Help-text accuracy: no group may claim read-only while exposing writes.

## Current (`0.3.x`) — admin/Manager layer

- **`0.3.0` — Admin discovery, read-only (shipped):** the `ik admin` group — `status`, `users`,
  `hostings`, `mailbox list/show` (aliases, forwarding, signature summary). Built only on
  live-verified endpoints; shipped no admin write of any kind.
- **`0.3.1` — Mailbox alias add/remove (shipped):** the first admin write, reversible and
  single-resource, with maintainer sign-off, the full protected-write contract, idempotent
  re-runs, and post-write readback.
- **`0.3.2` — Mailbox forwarding (shipped):** read plus protected add/remove/set/disable. The
  endpoint is a full replace with no conditional write, and disabling forwarding drops every
  stored address, so the destructive path requires an explicit acknowledgement flag and the
  previews state the effect in plain language.
- **`0.3.3` — Read-only admin polish (shipped):** `ik admin teams`, and honest counts on
  paginated endpoints (`count`/`total`/`complete`) so a first page is never reported as the whole
  inventory.
- **`0.3.4` — Mailbox signatures (shipped):** read plus protected create/update/set-default/delete.
  The update is a genuine partial update; delete is irreversible and guarded when the signature is
  a current default; bodies stay out of list output because they carry personal data.
- **`0.3.5` — Mailbox settings (shipped):** the admin note and the blocked/allowed sender lists.
  Rescoped during review: spam and filtering settings are write-only in this API, so they could not
  be previewed or confirmed and are not exposed; auto-reply is excluded because enabling it would
  reply to third parties with content this API does not expose.

This completes the `0.3.x` admin line. Further admin surface (user lifecycle, invitations, DNS,
sieve filters, auto-reply) needs its own discovery and explicit approval before being planned.
- User creation/deletion, invitations, DNS, filters, auto-reply, and every bulk or recursive admin
  operation remain excluded until individually designed and explicitly approved.

## Later

- **`0.4.x`** may add an optional MCP wrapper around stable CLI functions.
- Irreversible, recursive, bulk, and admin-scoped operations remain excluded until individually
  designed and explicitly approved; planned single-resource cleanup commands retain full guardrails.

This roadmap describes direction, not commitments or dates.
