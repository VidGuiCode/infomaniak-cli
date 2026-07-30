# Changelog

## [0.3.3] - 2026-07-30
### Added
- **`ik admin teams`** — list account teams/workgroups (id, name, description, parent, child
  count, owner, position) with `--table`, `--raw`, `--json`/`--compact`. Read-only.

### Fixed
- **List counts no longer present one page as the whole inventory.** `admin mailbox list` (and the
  new `admin teams`) read a paginated endpoint but reported `count: <len(first page)>` with no
  indication more existed — the same class of quiet dishonesty as a silent first-match. Every admin
  list now reports `count` (items returned), `total` (the server's figure, `null` when the endpoint
  does not paginate) and `complete`; when `count < total` the human output prints
  "Showing N of TOTAL … this endpoint paginates and ik reads one page."

### Changed
- The JSON from `admin users`, `admin hostings` and `admin mailbox list` gains `total` and
  `complete` alongside the existing `count`. Existing keys are unchanged, so this is additive.

### Notes
- Multi-page fetching is deliberately **not** implemented: reporting the truth fixes the
  dishonesty, while auto-paging changes request volume against a rate-limited API. A `--all-pages`
  flag can follow if a real account needs it.
- Discovery closed an open question: there is **no per-user detail endpoint** — it 404s even with a
  valid user id — so `ik admin users` is the only source of user information. The docs now say so
  instead of leaving it open.

## [0.3.2] - 2026-07-30
### Added
- **`ik admin mailbox forwarding show|add|remove|set|disable`** — read and change where a mailbox
  forwards its mail. `show` is read-only; the four writes carry the protected-write contract
  (preview, confirmation, `--dry-run`, explicit-profile-gated `--yes`, `changed` diff,
  `notified: false`, post-write readback with a warning when the readback disagrees).
- Guardrails specific to this endpoint, which is unusually easy to misuse:
  - **The API is a full replace, not a patch.** `add`/`remove` are read-modify-write and always
    send the complete configuration, so no field is ever blanked by omission.
  - **Dropping every address is destructive and guarded by effect, not by command name.**
    Infomaniak drops every stored address when forwarding is turned off, and this CLI cannot
    restore them. Any change emptying a non-empty list — `disable`, or `set` with no `--address` —
    refuses unless `--i-understand-addresses-are-dropped` is passed. `--dry-run` always previews
    and lists what would be lost. `remove` is exempt: it names the one address it drops.
  - **Forwarding can never end in a mail black hole.** If a change leaves no addresses, keeping a
    local copy is forced back on — otherwise "no forwarding target and no local delivery" would
    silently discard incoming mail.
  - Removing the last address is called out, because forwarding then stops entirely.
  - A readback that disagrees with the requested state exits non-zero instead of reporting success.
  - `--keep-copy`/`--no-keep-copy` and `--forward-spam`/`--no-forward-spam` are mutually exclusive
    at parse time rather than resolving silently, and address lists are deduplicated
    case-insensitively and capped at the documented maximum.
  - Output states effects rather than flag names: `keeps_local_copy` instead of the API's inverted
    `has_dont_deliver`, plus `forwards_spam`.
  - The read returns `redirect_adresses` (single `d`) as objects while the write takes
    `redirect_addresses` as plain strings; the mapping is handled and pinned by tests.
- Full destination addresses are required (a typo silently misroutes mail); add/remove are
  idempotent and match case-insensitively.

### Notes
- **No forwarding write was exercised against a live mailbox for this release**, deliberately. The
  test mailbox was configured "forwarding enabled, no addresses, no local copy", so adding a probe
  address would have forwarded real incoming mail without keeping a copy for the duration of the
  test — and the new black-hole guard would then have prevented restoring that exact flag
  combination. Read and `--dry-run` paths were verified live (previews, warnings, gates and the
  no-conditional-write notice all behaved correctly against real state, which was byte-identical
  before and after). The write path is covered by 22 offline tests against a stateful fake that
  mirrors the endpoint's read/write field asymmetry.

## [0.3.1] - 2026-07-30
### Added
- **`ik admin mailbox alias add|remove <mailbox> <alias>` — the first admin write**, shipped with
  explicit maintainer sign-off because an alias changes which addresses deliver to a mailbox.
  Endpoints: `POST .../mailboxes/{name}/aliases` and `DELETE .../aliases/{alias}` (documented
  contract, live-verified with a single throwaway alias add+remove before release).
- Full protected-write contract: preview with the current alias list, confirmation by default,
  `--dry-run`, explicit-profile-gated `--yes`/`-y`, `--json`/`--compact`, a `changed` diff,
  `notified: false` (an alias change emails nobody), and post-write **readback** — the alias list
  is re-fetched and the result reports `confirmed_present`/`confirmed_absent`.
- Idempotent supervised re-runs: adding an existing alias or removing an absent one is a reported
  no-op (`added/removed: false`, `existed`) that sends no request and exits 0.
- Aliases are validated as local parts (values containing `@` are refused with guidance) and
  percent-encoded into the request path like every other caller-supplied segment.

### Changed
- The `admin` group is no longer described as read-only: its help now states reads and protected
  mailbox-alias writes, and `admin` left the `READ_ONLY_GROUPS` contract set deliberately — the
  generic protected-write contract tests cover the new commands instead.

### Notes
- Still not implemented: forwarding changes (next, `0.3.2`), signature writes, mailbox settings,
  user creation/deletion, invitations, DNS, filters, auto-reply, and all bulk admin operations.

## [0.3.0] - 2026-07-30
### Added
- **`ik admin` — the first Manager/admin surface, entirely read-only.** Every command is built on
  an endpoint that was live-verified read-only before implementation; no admin command in this
  release accepts `--yes` or `--dry-run` because none of them can change anything:
  - `ik admin status` — reports whether the stored token can read Manager surfaces (account users,
    mail hostings), with counts. A forbidden surface is reported as unreadable with its HTTP status
    instead of failing the whole command, and the result states `writes: "none"`.
  - `ik admin users` — account users with `role_type`, `state_in_account`, `user_status`, billing
    access and workspace-only flags (`--table`, `--raw` supported).
  - `ik admin hostings` — mail hostings with lock and DNS-error state.
  - `ik admin mailbox list` — mailboxes on a mail hosting (`--table`, `--raw` supported).
  - `ik admin mailbox show <name>` — one mailbox plus its aliases, forwarding state
    (normalized to `redirect_addresses`; `--raw` preserves the upstream spelling), and a signature
    **summary** (count/defaults/forced — bodies only with `--raw`).
- `admin mailbox list|show` resolve the mail hosting from `--hosting-id`, else the profile's
  configured mail hosting, else a single discovered hosting — with several candidates they refuse
  and list them rather than guessing (the `0.2.19` no-first-match rule).

### Notes
- The admin group requires a token with Manager-level access. `ik admin status` is the diagnostic
  for that; it degrades honestly instead of erroring when scope is missing.
- No admin **write** ships in `0.3.0`, by design. User creation/deletion, invitations, alias and
  forwarding changes, DNS, filters and auto-reply are not implemented; reversible single-resource
  admin writes are considered for later `0.3.x` releases only after their endpoints are verified
  and with explicit maintainer sign-off.

## [0.2.21] - 2026-07-30
### Fixed
- **Top-level `ik --help` described Calendar and kChat as "read-only"** even though both expose
  protected writes (`calendar create/update/cancel/delete/create-series/repair`, `chat
  post/reply/react/unreact/edit/delete`). Understating what a group can do is not cosmetic: someone
  deciding whether a command is safe to run unattended would be misled about the safety posture.
  The group descriptions now state both halves, matching the wording Mail already used:

  | Group | Before | After |
  | --- | --- | --- |
  | `calendar` | Read-only CalDAV calendar commands | CalDAV calendar reads and protected event writes |
  | `chat` | Read-only kChat discovery commands | kChat reads and protected post/reaction writes |
  | `contacts` | CardDAV contacts commands | CardDAV contacts reads and protected contact writes |
  | `drive` | Use kDrive as the selected profile | kDrive reads and protected file writes |

- A new contract test fails if any command group is described as "read-only" while exposing a
  subcommand that accepts `--yes`, so this cannot drift again. Per-subcommand "(read-only)" labels
  were already accurate and are unchanged.

## [0.2.20] - 2026-07-30
### Added
- **Opt-in DAV credential reuse.** `ik auth contacts --reuse-from calendar` and
  `ik auth calendar --reuse-from contacts` take the sync password already stored for the other
  service instead of asking for it again. Infomaniak generates both sync passwords in the same
  place and they are commonly identical, so retyping one was pure friction. The secret is copied
  store-to-store in memory — never printed, never passed on a command line, never written anywhere
  but the secure store. **Only the credential is reused:** URL, username and connectivity checks
  stay independent per service, so reuse never implies a shared collection.
- After configuring one DAV service interactively, `ik` offers to reuse the same password for the
  other **only** when the other has none stored. Declining stores nothing. The offer never appears
  under `--non-interactive`, `IK_NO_INTERACTIVE`, a non-TTY stdin, or `--no-reuse-prompt`, so
  automation can never block on it.
- `--reuse-from` is refused together with `--password` or `--stdin`, since two sources for one
  secret is ambiguous.
- **`ik contacts addressbook`** — switch address book without going back through authentication:
  `list` (read-only discovery, marking the current selection), `use <collection-url>` (persist an
  explicit collection), and `repair` (rediscover when the saved URL is only the service root,
  refusing to guess between several and listing them). This closes an asymmetry from `0.2.13`, which
  gave Calendar `repair --url` but left Contacts with no equivalent.
- `ik calendar repair --list` for the matching read-only enumeration, so both DAV services expose
  collections the same way.

### Notes
- The address-book commands change **local profile config only** and say so in their output. They
  keep the protected-write contract: preview, confirmation by default, `--dry-run`,
  explicit-profile-gated `--yes`, structured output.
- This release addresses findings 2 and 3 of the v0.2.19 usage report. Finding 1 (calendar attendees
  and invitations) remains gated on the live notification probe; finding 4 (`ik admin` for users,
  aliases, forwarding, filters and DNS) is the `0.3.x` line, which needs Manager rights.

## [0.2.19] - 2026-07-29
### Fixed
- **`ik bootstrap` silently picked the first drive** when discovery returned several, carrying a
  literal `TODO` since the command was written. Whichever drive the API happened to return first
  became the profile default, and every later `ik drive …` read *and protected write* then targeted
  it. Bootstrap now refuses to guess: with several drives and `--non-interactive` it fails naming
  `--drive-id` and listing every id and name, and otherwise offers a deterministic numbered prompt.
- The same rule now applies to mailboxes. The existing preference chain is unchanged and still wins
  first — the profile user's own address, then the already-configured mailbox — because those are
  justified matches rather than guesses. Only when neither matches **and** several mailboxes exist
  does the ambiguity rule apply, resolved with `--mailbox`.

### Added
- `ik bootstrap --drive-id <id>` and `ik bootstrap --mailbox <address>` for explicit,
  automation-friendly selection.
- `ik bootstrap --dry-run` resolves everything and reports the account, drive and mailbox that
  *would* become the profile defaults, along with how many candidates were seen, then exits without
  touching the profile. The JSON envelope reports `saved: false` and a `selection` block; the normal
  path reports the same block before saving, so the change is visible rather than inferred
  afterwards.
- Every bootstrap result states `writes: "local profile config only"`, and a test asserts bootstrap
  issues no service write — it changes local configuration and nothing else.

### Changed
- Account, drive and mailbox selection now share one implementation, so the rule cannot drift
  between them. Account behavior is unchanged and its existing tests pass untouched. A profile with
  exactly one drive, or whose mailbox preference matches, bootstraps exactly as before.

## [0.2.18] - 2026-07-29
### Fixed
- **`ik drive mkdir` did not follow the protected-write contract.** Shipped since `0.2.0`, it
  accepted `--yes` with **no `--dry-run` and no explicit-profile gate**, so unattended automation
  could create a folder in whichever profile happened to be current. It now previews the exact
  target, supports `--dry-run`, and gates `--yes` on an explicit profile like every other write.
  This was found by the new contract test, not by inspection.

### Added
- **Shared write-contract tests** (`tests/test_write_contract.py`) that introspect the real parser
  instead of a hand-maintained list. Every command accepting `--yes` must also offer `--dry-run`,
  `--json`/`--compact` and `-y`, and must reach the explicit-profile gate; every command offering
  `--dry-run` must be gated. Deliberate exceptions (`profile delete`, `auth logout`,
  `doctor --fix-path`, `update`) are listed with a written reason, so an exception is a decision
  rather than an oversight. A new mutating command that forgets a guarantee now fails the suite.
- **Redaction contract tests:** every credential-holding service module must wire a redactor into
  its error paths, and the shared output redactor is asserted against known secret shapes
  (`Bearer …`, `token=…`, `password=…`).
- **`ik doctor` write-capability readiness.** A new `capabilities` section reports whether
  `mail.send`, `mail.attachments`, `drive.write`, `calendar.write`, `contacts.write` and
  `chat.post` are actually possible for the selected profile, and names the exact command that
  fixes each missing prerequisite. Purely local inspection — no network call, no write.
- **`notified` on write results**, stating the real external effect rather than leaving the caller
  to infer it: `true` for `mail send`/`reply`/`forward` and `chat post`/`reply`, `false` for local
  or single-user writes such as `mail draft`, `calendar create` and `drive mkdir`. A dry run always
  reports `notified: false`. Tests assert the values are accurate, because a blanket `false` would
  be worse than no field at all.
- **`changed` diffs** via a shared `_diff_fields` helper, so a preview can report what actually
  differs instead of leaving the caller to compare two full states. `before`/`after` are unchanged.

### Changed
- The explicit-profile gate is now **one implementation**. It previously existed as five
  near-identical helpers plus ten inline copies, each an opportunity for the rule to drift; the
  per-service helpers are now thin delegates and every inline copy is gone. Behavior is unchanged —
  all pre-existing gate tests pass untouched.

## [0.2.17] - 2026-07-29
### Added
- **Read-only export first:** `ik contacts export` writes the address book as `vcf` (default) or
  `json`, to `--output <path>` or stdout. vCard output copies each contact's original card
  **verbatim**, so photos, custom `X-` properties and anything else the CLI does not model survive
  a backup round trip. Contacts without a parseable vCard are reported in `skipped`, never
  silently dropped. An existing output file needs `--force`.
- **Richer field modelling:** `ADR` addresses (all seven components), `CATEGORIES` groups, and
  `TYPE=` parameters on `EMAIL`/`TEL`. The flat `emails`/`phones` lists are unchanged for
  compatibility; `typed_emails`/`typed_phones`/`addresses`/`groups` are additive.
- **Duplicate detection:** `ik contacts duplicates` is read-only and groups candidates by shared
  email first, then by display name, reporting which key matched.
- **Merge with preview:** `ik contacts merge <primary_id> <secondary_id>` unions the two contacts
  onto the primary. Conflicting scalar fields keep the primary's value and are reported rather
  than hidden. **The secondary is never deleted** — removing it stays an explicit, separate step.
- **Import with a no-overwrite default:** `ik contacts import <file.vcf>` detects collisions by UID
  then by email, and **skips** colliding contacts unless `--update-existing` is passed; even then
  the write is conditional on the current ETag. A failure partway through reports how many
  contacts were already written.
- **Single-contact delete:** `ik contacts delete <contact_id>` resolves exactly one contact and
  deletes it with `If-Match: <etag>`, so a contact changed remotely since resolution is never
  removed. 412 maps to "changed remotely; nothing was deleted". The preview shows name, emails,
  phones and organization, states plainly that it is irreversible, and the result reports whether
  removal was confirmed.

### Notes
- Silent merge, bulk delete, and destructive address-book sync remain excluded.

## [0.2.16] - 2026-07-29
### Added
- **`ik chat reply <post_id>`:** replies in a thread. The channel is derived from the resolved
  post rather than restated by the caller, so it cannot mismatch, and replying to a reply threads
  to the existing root instead of nesting deeper.
- **Reactions:** `ik chat react <post_id> <emoji>` and `ik chat unreact <post_id> <emoji>`. Emoji
  shortnames are accepted with or without surrounding colons and validated locally, since the name
  becomes a URL path segment.
- **`ik chat edit <post_id> --message`:** edits **your own** post, previewing before/after text and
  reading the post back afterwards.
- **`ik chat delete <post_id>`:** deletes **your own** post. The preview shows the author, channel,
  full message text and thread size, states plainly that it is irreversible, and the result reports
  whether the removal was confirmed rather than assuming it.
- **Attachments:** repeatable `--attach <path>` on `ik chat post` and `ik chat reply`. Files upload
  through `POST /api/v4/files` with a standard-library multipart body, are capped at 50 MB each,
  and upload only **after** confirmation — never during `--dry-run`.

### Changed
- Ownership is enforced client-side: `edit` and `delete` resolve the post and compare its `user_id`
  to the authenticated user before any write request is issued. Another user's post is refused
  outright rather than relying on the server to reject it.
- The kChat client gained `PUT`, `DELETE` and multipart transports, all routed through the existing
  send path so token redaction and 401/403 classification are unchanged.

### Notes
- If an attachment upload fails partway through a multi-file post, the CLI reports how many files
  were already uploaded and left unreferenced, instead of failing silently.
- Channel creation, membership changes, moderation and webhooks remain out of the `0.2.x` line;
  they require workspace-admin rights and are reserved for `0.3.x`.

## [0.2.15] - 2026-07-29
### Added
- **Attachments, read side:** `ik mail attachments <uid>` lists a message's attachment parts with a
  stable index, filename, content type and size. `ik mail attachment-save <uid> <index|filename>`
  writes one attachment to disk. A filename that matches several parts is refused rather than
  guessed, and an existing local file is never overwritten without `--force`. Both use the
  non-mutating `BODY.PEEK` fetch, so listing or saving never marks a message read.
- **Attachments, send side:** `ik mail send` and `ik mail draft` accept repeatable `--attach <path>`.
  Types are guessed with the standard library, the combined size is capped locally (25 MB) so an
  oversized message fails with a clear error instead of mid-SMTP, and the preview lists every
  attachment with its name, size and a total before confirmation.
- **Reply and forward:** `ik mail reply <uid>` and `ik mail forward <uid> --to ...` build from one
  resolved message. `In-Reply-To` is set and `References` is **appended** to the original chain, so
  threading survives. `Re:`/`Fwd:` prefixes are not stacked. `--all` replies to the original
  recipients while excluding your own address; forward always requires explicit `--to` and can
  carry the original attachments with `--with-attachments`.
- **Message lifecycle:** `mail mark-read`, `mail mark-unread`, `mail flag`, `mail unflag`, and
  `mail move <uid> <folder>` act on exactly one resolved UID, preview folder/UID/subject/action and
  current flags, and read the flags back after the change. `move` verifies the destination folder
  exists first and prefers IMAP `MOVE`, falling back to `COPY`.
- **Draft lifecycle:** `ik mail drafts list` (read-only) and `ik mail drafts delete <uid>`
  (irreversible, protected) around the existing draft-creation path.

### Changed
- Reads and writes are now explicitly separated at the IMAP layer: every read path uses `EXAMINE`
  with `BODY.PEEK`, and only flag changes, move and draft delete take a read-write `SELECT`. A
  regression test asserts reads never take the read-write path.
- If a server lacks `UID EXPUNGE`, a move reports an error instead of falling back to a
  mailbox-wide `EXPUNGE`, which would remove messages the caller never named.

### Fixed
- Replying to or forwarding a message whose subject header is **folded** across lines (how long
  subjects are actually transmitted) produced a subject containing CR/LF, which the header
  injection guard then rejected. Derived subjects now collapse folding whitespace.
- Saving an attachment used the sender-supplied filename directly, so a crafted name such as
  `../../evil` could escape the chosen output directory. Filenames are now reduced to a safe
  basename before any write.

### Not included
- Scheduled send. IMAP and SMTP expose no reliable native scheduled-send contract, and simulating
  one client-side would require a background process this CLI does not have. Investigated and
  declined rather than silently dropped.
- Bulk delete, purge, spam reporting, and any multi-message or recursive mutation.

## [0.2.14] - 2026-07-29
### Added
- **Recurrence on create:** `ik calendar create --rrule "FREQ=MONTHLY;INTERVAL=3;COUNT=4"` adds a
  single recurrence rule. The rule is validated and normalized locally — `KEY=VALUE` parts only,
  known RFC 5545 part names, a known `FREQ`, no repeated parts, and no embedded line breaks — so a
  malformed rule is refused before any request instead of failing the whole `PUT`, and a rule can
  never inject an extra iCalendar property.
- **`ik calendar create-series`:** creates one event per explicit `--date`, for a fixed list of
  deadlines. Each UID is `<--uid-prefix>-<date>`, so the series is deterministic and re-running
  with `--if-missing` is a no-op rather than a second set of events. Duplicate `--date` values and
  colliding derived UIDs are refused before any request, and `--duration-minutes` cannot be
  combined with `--all-day`. The preview lists every event with its resolved start, end and UID,
  and one confirmation covers the batch.
- Because a series is a batch of independent writes, a failure partway through reports the failing
  UID and the UIDs already created, and points at `--if-missing` to finish the remainder without
  duplicating them.

### Notes
- **Attendees, invitations, RSVP, contact-name resolution and `calendar import` are deliberately
  not included in this release.** A read-only capability probe confirmed that Infomaniak's CalDAV
  server advertises `schedule-outbox-URL` and `schedule-inbox-URL`, so writing an `ATTENDEE` would
  very likely email a real person. Until that notification behavior is verified live, those
  surfaces stay disabled and attendee-bearing events remain refused by `calendar update`,
  `calendar cancel`, and `calendar delete`. The findings are recorded in the project's private
  live-API notes; the deferred work is tracked as its own future milestone.

## [0.2.13] - 2026-07-29
### Added
- **Create-time reminders:** `ik calendar create --reminder-minutes N` is repeatable and emits one
  display `VALARM` per value, so an administrative reminder no longer needs create-then-update.
  Negative and duplicate values are refused.
- **Duplicate-safe creation:** `--uid` supplies a deterministic event UID, and `--if-missing`
  turns the server's "already exists" response into a successful no-op (`created: false`,
  `existed: true`). `--if-missing` requires `--uid`, because a random UID can never match. Without
  `--if-missing`, an existing UID remains an error.
- **Calendar discovery repair:** a profile whose calendar URL is only the service root now
  auto-discovers a usable collection for the current read instead of failing, and
  `ik calendar repair` resolves and saves the real collection to the profile. Repair refuses to
  guess when several collections are discovered and lists them so `--url` can choose one. It
  changes local profile config only and never touches calendar data.
- **Richer search filters:** `ik calendar search` gains `--attendee`, `--uid`, `--status`,
  `--description`, and a mutually exclusive `--all-day` / `--timed`. Filters combine with the
  free-text query as AND, and the query is now optional when at least one filter is given.
  `--uid` and `--status` match exactly; the rest are case-insensitive substrings.
- **Read-only export:** `ik calendar export` writes a resolved date range as `ics` or `json`, to
  `--output <path>` or stdout. ICS output copies each event's original `VEVENT` verbatim, so
  unmodeled properties survive a backup round trip; events without a parseable `VEVENT` are
  reported as skipped rather than dropped. An existing `--output` file is never overwritten
  without `--force`.

### Changed
- `docs/setup-and-profiles.md` now documents the four distinct credentials (Informaniak API token,
  mailbox password, Contacts/CardDAV password, Calendar/CalDAV password), where the sync passwords
  are generated, and that Contacts and Calendar passwords are stored separately.

### Fixed
- The offline test suite no longer reaches the developer's real OS keyring. `conftest`'s mock is
  in-process only, so tests that shell out could pick up a machine credential for a profile named
  `work` and turn offline tests into live API calls. Subprocess helpers now pin a failing keyring
  backend and fall back to the isolated `IK_CONFIG_DIR`.

## [0.2.12] - 2026-07-29
### Added
- **Single-file kDrive upload:** `ik drive upload <path>` uses the official v3 octet-stream
  endpoint with `conflict=error`, so a same-name remote file is never overwritten. It accepts
  native Windows, MSYS `/c/...`, and Unix local paths through one shared normalizer.
- **Exact move and rename:** `ik drive move <file_id> <destination_folder_id>` and
  `ik drive rename <file_id> <name>` resolve one source and destination, refuse the drive root,
  preview before/after state, reject name conflicts, and read the item back after the write.
- **Reversible trash lifecycle:** `ik drive trash list`, `trash show`, and protected
  `trash restore` use the confirmed v3 read/v2 restore contract. Permanent trash deletion,
  empty-trash, recursive, and bulk operations remain unavailable.
- **Read-only share state:** `ik drive share-state <file_id>` reads public-link and multi-access
  state. The live API's normal 404 for “no public link” is represented as `link: null`.
  Share creation/revocation remains deferred until recipient/link permissions are safely proven.
- Every Drive mutation supports before/after preview, `--dry-run`, confirmation by default,
  structured `--json`/`--compact`, explicit-profile-gated `--yes`, redacted errors, and readback.

## [0.2.11.post1] - 2026-07-15
### Fixed
- Calendar update/cancel now refuse a CalDAV resource containing multiple VEVENT components.
  This prevents a single-instance request from rewriting every override in a recurring series;
  recurrence-instance targeting remains deferred until it can be resolved conditionally and exactly.

## [0.2.11] - 2026-07-15
### Added
- **Conditional Calendar update:** `ik calendar update <event_id>` resolves one exact CalDAV
  resource, previews before/after state, preserves unmodeled iCalendar properties, and writes with
  `If-Match: <etag>` so concurrent edits are never silently overwritten.
- **Soft cancellation:** `ik calendar cancel <event_id>` retains the resource and writes
  `STATUS:CANCELLED` conditionally. **Hard deletion:** `ik calendar delete <event_id> --hard`
  removes the exact resource conditionally and requires an additional explicit acknowledgement.
- Lifecycle writes follow the protected-write contract: confirmation by default, structured
  `--json`/`--compact`, `--dry-run`, explicit-profile-gated `--yes`, and safe readback.
- Update can change summary, start/end, location, description, and one existing simple reminder.
  Full ICS and VALARM content is preserved; complex/multiple alarms are refused rather than lost.
- Events with attendees are refused for update/cancel/delete because Infomaniak RSVP/invite
  notification effects are not yet verified. RSVP, attendee edits, and invite sending remain disabled.

## [0.2.10] - 2026-07-15
### Changed
- `ik account services` is now the primary workflow-facing inventory. Default JSON/compact output
  normalizes upstream catalog records to stable `id`, `name`, optional `count`, and `actionable`
  fields; supported service families also expose an `area` and a concrete next CLI `command`.
- Added `ik account services --json --raw` for full upstream diagnostics and a workflow-oriented
  table/human view. Known hints cover drive, mail, chat, calendar, and contacts.
- `ik account products` remains compatible but is explicitly labeled lower-level catalog data for
  bootstrap debugging, support, and product/service relationship inspection rather than daily use.

## [0.2.9] - 2026-07-14
### Added
- **Protected mail drafts:** `ik mail draft` builds one plain-text RFC message and appends it to
  the discovered/configured Drafts folder with the IMAP `\Draft` flag.
- **Protected mail send:** `ik mail send` sends one plain-text message from the profile's fixed
  default mailbox through authenticated SMTP-over-SSL on port 465.
- Both commands preview profile, mailbox/from, repeatable To/Cc/Bcc recipients, subject, and body;
  confirm by default; support credential-free/network-free `--dry-run`; and permit `--yes` only
  with an explicit profile. Header-newline injection is rejected and transport errors redact the
  stored mail password. Attachments, HTML, bulk sends, delete, move, and mark-read remain excluded.

## [0.2.8.post1] - 2026-07-14
### Fixed
- `ik contacts create --dry-run` is now a genuinely offline preview: it requires configured
  address-book metadata, but no stored Contacts password and no CardDAV client or network call.

## [0.2.8] - 2026-07-14
### Added
- **Contacts create:** `ik contacts create --name <name>` writes one vCard with confirmation,
  `--dry-run`, structured output, and explicit-profile-gated `--yes`. Creation uses CardDAV PUT
  with `If-None-Match: *`, so an existing resource is never overwritten.
- **Contacts update:** `ik contacts update <contact_id> <field options>` resolves the existing
  contact first and previews before/after values. It preserves unmodeled raw vCard properties and
  writes to the resolved resource URL with `If-Match: <etag>` to prevent lost updates.
- Supported fields are display/given/family name, repeatable email and phone, and organization.
  Delete, bulk import, export, and sync writes remain excluded.

## [0.2.7] - 2026-07-14
### Added
- **Calendar history:** `ik calendar search <query> --from <ISO> --to <ISO>` queries an explicit
  CalDAV time range, including past events. Date-only and offset-aware datetime bounds are
  accepted; `--days` remains the default convenience when no explicit range is supplied.
### Fixed
- Global `--profile` and `--base-url` options are accepted before or after commands/subcommands.
- On Windows, kDrive download destinations in MSYS form (`/c/Users/...`) are translated to native
  drive paths before validation; missing-parent errors now state how to resolve them.
### Documented
- `pipx list` may retain stale metadata after the quiet `pipx runpip` updater path; `ik version`
  is the authoritative installed version.

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
