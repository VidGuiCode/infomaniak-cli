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
ik bootstrap --dry-run --json          # show the defaults that would be saved
ik bootstrap --drive-id <id> --mailbox <address> --non-interactive
ik update
ik completion bash
```

Expected behavior:

- `setup`: create/update a profile, authenticate, discover services, choose defaults, run doctor.
- `whoami`: show active profile/account/user/default services and readiness.
- `doctor`: verify auth and configured service setup state.
- `bootstrap`: rerun autodiscovery, safely update defaults, and show missing setup actions.

`ik bootstrap` never silently resolves an ambiguous choice. When discovery returns several accounts,
drives or mailboxes and none is explicitly selected, it fails under `--non-interactive` naming the
flag that resolves it (`--account-id`, `--drive-id`, `--mailbox`) and listing every candidate id and
name; interactively it offers a numbered prompt. A single candidate is auto-selected as before, and
mailboxes keep their preference chain — your own address, then the already-configured one — because
those are justified matches rather than guesses.

This matters because the chosen defaults are what every later service command targets: a silently
wrong drive would redirect both reads and protected writes.

`ik bootstrap --dry-run` resolves everything and reports the account, drive and mailbox that would
become the profile defaults, plus how many candidates were seen, without touching the profile.
Bootstrap only ever changes **local profile configuration** — it performs no service write.
- `update`: check GitHub releases and update supported installs.
- `completion`: generate static shell completion scripts for bash, zsh, fish, and powershell.

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
ik auth contacts --username <sync-username> --stdin
ik auth calendar --username <sync-username> --stdin
ik auth chat --url <kchat-base-url> --token <kchat-token> --team-id <team_id>
```

`auth token` stores the selected profile's main Informaniak API token. `auth check` verifies that token with a read-only authenticated API request.

`auth logout` removes the selected profile's main Informaniak API token by default. Add `--all` to also remove local mail, contacts, calendar, and chat secrets for that profile. It never contacts or changes remote services.

`auth contacts` stores CardDAV contacts credentials. From the default DAV base `https://sync.infomaniak.com/`, it auto-discovers the address-book collection via standard CardDAV principal/home-set discovery and saves it; with multiple address books it picks a sensible default and prints the rest. Pass `--url <collection-url>` to set a collection explicitly, or `--no-discover` to save the URL verbatim. Use the Infomaniak sync username.

`auth calendar` stores CalDAV calendar credentials. From the default DAV base `https://sync.infomaniak.com/`, it auto-discovers the calendar collection and saves it; with multiple calendars it picks a default and lists the rest. Pass `--url <collection-url>` to set a collection explicitly, or `--no-discover` to save the URL verbatim. Use the Infomaniak sync username.

`auth chat` stores kChat/Mattermost-compatible connection settings. It accepts either the kSuite browser URL or a direct trusted API base. For kSuite URLs like `https://ksuite.infomaniak.com/<account_id>/kchat/<workspace>/channels/<channel>`, the CLI parses the account ID, workspace slug, and optional channel slug, derives `https://<workspace>.kchat.infomaniak.com`, and confirms it with read-only `GET /api/v4/users/me/teams` when a main Informaniak API token exists. The main token is never sent to arbitrary user-provided hosts.

## Account / environment discovery

These commands describe what the authenticated user/profile can access. An employee could run these if their Informaniak rights allow it.

```bash
ik account list
ik account services
ik account services --account-id <id>
ik account services --json --raw
ik account products --json --raw
ik account products --account-id <id> --json --raw
```

These commands stay read-only and intentionally cover user-accessible discovery, not company/account administration.

`ik account services` is the primary workflow discovery command. Default JSON/compact output is
normalized to stable fields: `id`, `name`, optional `count`, `actionable`, and—when the service has
a supported daily workflow—`area` plus `command`. Current hints include `ik drive list`,
`ik mail mailboxes`, `ik chat channels`, `ik calendar upcoming`, and `ik contacts list`.
Use `--table` for a compact inventory or `--json --raw` to inspect the full upstream response.

`ik account products` is lower-level catalog data. It remains available, especially with
`--json --raw`, for bootstrap debugging, support, and understanding product/service relationships;
normal drive/mail/calendar/contacts/chat workflows should not depend on it.

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
ik mail attachments <uid> --json
ik mail attachment-save <uid> 0 --output ./downloads/
ik mail drafts list --json
```

`ik mail mailboxes` lists configured/discovered mailbox addresses. Without an API token it can still show the profile's configured default mailbox. With a main Informaniak API token and a discovered mail hosting ID, it uses the confirmed read-only `GET /1/mail_hostings/{mail_hosting_id}/mailboxes` endpoint. `ik mail accounts` is an alias.

`ik mail hostings` lists mail hosting resources from the selected account's confirmed products/services discovery endpoints. `ik mail aliases` is deferred until a safe alias endpoint is confirmed.

Mailbox discovery is separate from IMAP content access: `ik mail list`, `ik mail unread`, `ik mail read`, `ik mail search`, and `ik mail threads` still require `ik auth mail` with the mailbox device password from the mail setup flow.

`ik mail list` defaults to the `INBOX` folder and shows both read and unread messages. Limited mail results are newest-first by default; add `--oldest-first` to show the oldest matching messages first. Each message in JSON output includes a `seen` boolean. `--days N` is a convenience shortcut for `--since` set to `today - N days`.

`ik mail unread` accepts the same folder, limit, ordering, and date filters as `ik mail list`. `ik mail read` also accepts `--folder` so you can read messages from any folder by UID. Human output prints the full readable body text, and slim JSON includes full `body_text` without requiring `--raw`; `--raw` keeps fuller parsed message metadata such as `body_preview`. `ik mail threads` groups messages into conversation threads using `In-Reply-To` and `References` headers.

Protected plain-text writes:

```bash
ik mail draft --to recipient@example.com --subject "Review" --body "Draft body" --dry-run --profile work
ik mail draft --to recipient@example.com --subject "Review" --body "Draft body" --profile work
ik mail send --to recipient@example.com --subject "Hello" --body "Message body" --dry-run --profile work
ik mail send --to recipient@example.com --subject "Hello" --body "Message body" --profile work
ik mail send --to recipient@example.com --subject "Report" --body "See attached." \
    --attach ./report.pdf --dry-run --profile work
ik mail reply <uid> --body "Acknowledged." --dry-run --profile work
ik mail reply <uid> --body "Acknowledged." --all --profile work
ik mail forward <uid> --to third@example.com --body "FYI" --with-attachments --dry-run
ik mail mark-read <uid> --dry-run --profile work
ik mail flag <uid> --profile work
ik mail move <uid> Archive --dry-run --profile work
ik mail drafts delete <uid> --dry-run --profile work
```

Both commands preview profile, mailbox/from, recipients, subject, and body; confirm by default;
support `--json`/`--compact`; and permit `--yes` only with explicit `--profile` or `IK_PROFILE`.
`--to`, `--cc`, and `--bcc` are repeatable. Drafts use IMAP APPEND with `\Draft`; sends use
authenticated SMTP SSL on port 465.

### Attachments

`ik mail attachments <uid>` lists a message's attachment parts with a stable `index`, `filename`,
`content_type` and `size`. `ik mail attachment-save <uid> <index|filename>` writes one attachment
to `--output` (a file or directory, defaulting to the attachment's own name). A filename matching
several parts is refused rather than guessed — use the index instead. An existing local file is
never overwritten without `--force`. Both commands use the non-mutating `BODY.PEEK` fetch, so
listing or saving never marks a message read. Because the filename comes from the sender, it is
reduced to a safe basename before writing, so a crafted name cannot escape your output directory.

`ik mail send` and `ik mail draft` accept repeatable `--attach <path>`. Content types are guessed
from the file name, the combined size is capped at 25 MB locally so an oversized message fails with
a clear error instead of part-way through SMTP, and the preview lists every attachment with its
name and size plus a total before you confirm.

### Reply, forward, and message lifecycle

`ik mail reply <uid>` and `ik mail forward <uid> --to ...` build from one exactly-resolved message.
`In-Reply-To` is set to the original `Message-ID` and `References` is **appended** to the original
chain, so threading survives in every client. `Re:`/`Fwd:` prefixes are never stacked, and folded
subject headers are collapsed to a single line. `--all` replies to the original recipients while
excluding your own address; forward always requires an explicit `--to` and can carry the original
attachments with `--with-attachments`.

`mail mark-read`, `mail mark-unread`, `mail flag`, `mail unflag`, and `mail move <uid> <folder>`
each act on exactly one resolved UID. They preview folder, UID, subject, action and current flags,
confirm by default, support `--dry-run`, gate `--yes` on an explicit profile, and read the flags
back afterwards. `move` verifies the destination folder exists first (run `ik mail folders` for the
exact names) and prefers IMAP `MOVE`, falling back to `COPY`. If a server lacks `UID EXPUNGE`, the
move reports an error rather than performing a mailbox-wide `EXPUNGE` that would affect messages
you never named.

`ik mail drafts list` is read-only; `ik mail drafts delete <uid>` is irreversible and protected.

Not implemented: scheduled send (no reliable native contract exists over IMAP/SMTP), HTML
composition, bulk delete, purge, spam reporting, and any multi-message or recursive mutation.

## kDrive

Read-only commands:

```bash
ik drive list
ik drive list --parent <folder_id> --limit 20 --json
ik drive folders
ik drive folders --parent <folder_id> --limit 20 --json
ik drive tree
ik drive tree --depth 2 --limit 20 --json
ik drive recent --limit 10 --json
ik drive recent --limit 10 --table
ik drive shared --json
ik drive search "RCS"
ik drive info <file_id>
```

Server-read-only write helper (downloads bytes; makes no server-side change):

```bash
ik drive download <file_id>
ik drive download <file_id> --output ./downloads/
ik drive download <file_id> --output ./logo.png --force
ik drive download <file_id> --json
```

Protected soft-delete (one resolved target, trash only):

```bash
ik --profile work drive rm <file_id> --dry-run
ik --profile work drive rm <file_id>
ik --profile work drive rm <file_id> --yes --json
```

Reversible single-item workflows:

```bash
ik --profile work drive upload ./report.pdf --parent <folder_id> --dry-run
ik --profile work drive upload /c/Users/user/report.pdf --parent <folder_id> --yes --json
ik --profile work drive move <file_id> <destination_folder_id> --dry-run
ik --profile work drive rename <file_id> "New name.pdf" --dry-run
ik drive trash list --limit 10 --json
ik drive trash show <file_id> --json
ik --profile work drive trash restore <file_id> --destination <folder_id> --dry-run
ik drive share-state <file_id> --json
```

`ik drive list` uses the selected profile's default kDrive ID and calls `GET /2/drive/{drive_id}/files`. Use `--drive-id <id>` to override the profile default. `--parent <folder_id>` is passed to the same endpoint as `parent_id`.

`ik drive folders` uses the same files endpoint and filters the returned items to folders/directories only. It supports `--drive-id`, `--parent`, `--limit`, `--json`, and `--raw`.

`ik drive tree` builds a shallow read-only folder tree from repeated files endpoint calls with `parent_id` filtering. It defaults to `--depth 2`; use lower depth for cheaper checks. `--limit` applies per folder request.

`ik drive recent` uses the same files endpoint and sorts client-side by the best available timestamp, newest first. It prefers `last_modified_at` and falls back to `created_at`. It supports `--drive-id`, `--parent`, `--limit`, `--json`, `--compact`, `--table`, and `--raw`.

`ik drive shared` uses the same files endpoint and filters client-side only when file payloads expose explicit shared/public/link-visible fields. It supports `--drive-id`, `--limit`, `--json`, `--compact`, `--table`, and `--raw`. It never creates, edits, or removes shares.

`ik drive search <query>` is currently implemented by listing files and filtering by file/folder name client-side because no separate search endpoint has been confirmed. `ik drive info <file_id>` is currently implemented by finding the item in the list endpoint response.

`ik drive download <file_id>` fetches a file's raw bytes via `GET /2/drive/{drive_id}/files/{file_id}/download` (confirmed live) and writes them locally. It first reads the file's metadata via `GET /2/drive/{drive_id}/files/{file_id}` to resolve the name and reject folders. The server side is read-only — no server change is made. `--output <path>` sets the destination (a directory keeps the remote name; otherwise the exact path is used); with no `--output` it writes the remote name into the current directory. It never overwrites an existing local file unless `--force` is given. Supports `--drive-id`, `--json`, and `--compact`.

On Windows, MSYS paths such as `/c/Users/user/Downloads/report.pdf` are translated to native `C:\\Users\\user\\Downloads\\report.pdf` paths by the same central normalizer used for download and upload. Ordinary native Windows and Unix paths are left intact. A download destination parent must already exist; the error names the missing directory and tells you to create it or select an existing path.

`ik drive rm <file_id>` resolves one target via `GET /2/drive/{drive_id}/files/{file_id}`, previews its name/type/id, then moves it to trash via `DELETE /2/drive/{drive_id}/files/{file_id}`. This is an undoable soft-delete; JSON includes returned undo metadata such as `cancel_id`. Confirmation is required unless `--yes` is used with an explicit profile. `--dry-run` resolves and previews without deleting. The drive root is refused; permanent, recursive, and bulk deletion are not available.

`ik drive upload <path>` uploads one local file through `POST /3/drive/{drive_id}/upload` with an octet-stream body, exact `total_size`, destination folder, and `conflict=error`. Remote overwrite/version creation is never selected. Files above 1 GB are refused because chunked upload is not implemented. The destination is resolved first, and the returned file id is read back after upload.

`ik drive move` and `ik drive rename` operate on one resolved id, show before/after state, refuse the drive root, use collision-safe server modes, and read back the result. `drive trash list/show` use the confirmed v3 trash reads; `drive trash restore` restores one exact trashed item through the v2 endpoint, optionally into one resolved destination folder. All four mutations confirm by default, support `--dry-run`, and allow `--yes` only with an explicit profile.

`ik drive share-state <file_id>` is read-only. It reads both the public-link and multi-access endpoints; an absent link is reported as `link: null`. Share creation/revocation remains disabled because recipient, public-link, and permission effects have not been proven safely.

Not implemented: remote overwrite/version upload, permanent delete, empty-trash, recursive/bulk operations, share creation/revocation, chunked upload, or sync.

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
ik chat search "invoice" --json
ik chat search "invoice" --channel <channel_slug> --limit 20 --json
ik chat thread <post_id> --json
```

Protected write (posts a message — off by default, confirmation required):

```bash
ik chat post "Deploy finished" --channel <channel_slug> --dry-run
ik chat post "Deploy finished" --channel <channel_slug>              # prompts to confirm
ik --profile work chat post "Deploy finished" --channel <channel_slug> --yes
ik chat post "Report attached" --channel <channel_slug> --attach ./report.pdf --dry-run
ik chat reply <post_id> --message "Acknowledged." --dry-run
ik --profile work chat reply <post_id> --message "Acknowledged." --yes
ik chat react <post_id> thumbsup --dry-run
ik chat unreact <post_id> :thumbsup: --dry-run
ik chat edit <post_id> --message "Corrected text" --dry-run     # your own posts only
ik chat delete <post_id> --dry-run                              # your own posts only, irreversible
```

`ik chat teams` uses the configured kChat API base URL and calls the Mattermost-compatible `GET /api/v4/users/me/teams` endpoint. Authentication order is explicit saved kChat token first, then the saved main Informaniak API token only for trusted `*.kchat.infomaniak.com` hosts.

`ik chat channels` lists channels for a team using `GET /api/v4/teams/{team_id}/channels`. If no team is saved and the profile has access to exactly one team, that team is used. Otherwise pass `--team-id <id>` or save one with `ik auth chat --team-id <id>`.

`ik chat users` lists users for a team using `GET /api/v4/users?in_team={team_id}`.

`ik chat search "<query>"` searches posts read-only via `POST /api/v4/teams/{team_id}/posts/search`. Use `--or` to match any term instead of all terms, `--limit` to cap results, and `--channel <slug>` to resolve a channel name read-only (`GET /api/v4/teams/{team_id}/channels/name/{name}`) and filter results to that channel.

`ik chat thread <post_id>` reads a thread read-only via `GET /api/v4/posts/{post_id}/thread`, preserving the server's post order.

`ik chat post "<message>" --channel <slug|id>` posts a message via `POST /api/v4/posts` (confirmed live for channel resolution). It is the first kChat write and follows the protected-write contract: it resolves the channel, prints a profile/team/channel/message preview, and requires confirmation before posting. `--dry-run` resolves the target and shows the plan without posting. `--yes` skips the prompt but only when the profile is explicit (`--profile <name>` or `IK_PROFILE`), so automation cannot post to the wrong account. Empty messages are refused.

`ik chat reply <post_id> --message "..."` replies in a thread. The channel is derived from the
resolved post rather than restated by the caller, so it cannot mismatch, and replying to a reply
threads to the existing root instead of nesting deeper.

`ik chat react <post_id> <emoji>` and `ik chat unreact <post_id> <emoji>` add and remove your own
reaction. Shortnames are accepted with or without surrounding colons (`thumbsup` or `:thumbsup:`)
and are validated locally, because the name becomes a URL path segment.

`ik chat edit <post_id> --message "..."` and `ik chat delete <post_id>` act **only on your own
posts**. Both resolve the post and compare its author to the authenticated user before issuing any
write, so another user's message is refused outright rather than relying on the server to reject
it. Edit previews before/after text and reads the post back; delete shows the author, channel, full
message text and thread size, states plainly that it is irreversible, and reports whether the
removal was confirmed rather than assuming it.

`--attach <path>` is repeatable on `chat post` and `chat reply`. Files upload via
`POST /api/v4/files` with a standard-library multipart body and are capped at 50 MB each. Uploads
happen only **after** confirmation, never during `--dry-run`. If an upload fails partway through a
multi-file post, the CLI reports how many files were already uploaded and left unreferenced.

Still excluded: channel creation, membership changes, moderation, and webhooks — these need
workspace-admin rights and are reserved for the `0.3.x` admin line.

If the trusted-host fallback is rejected, save a dedicated token with `ik auth chat --url <url> --stdin`.

Note: `search`, `thread`, and the `--channel` resolver target the documented standard Mattermost v4 endpoints; live confirmation against Infomaniak kChat is pending.

Not implemented: channel creation, membership changes, moderation, and webhooks.

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
ik auth contacts --username <sync-username> --stdin

ik contacts list
ik contacts list --limit 50 --json
ik contacts search "accountant"
ik contacts search "example.com" --json
ik contacts show <contact_id> --json
ik contacts show <contact_id> --json --raw
ik contacts export --output backup.vcf
ik contacts export --format json --json
ik contacts duplicates --json
```

`ik contacts list`, `ik contacts search`, and `ik contacts show` use the configured CardDAV collection URL. `ik auth contacts` auto-discovers that collection from the default DAV base `https://sync.infomaniak.com/`; pass `--url` to override or `--no-discover` to save a URL verbatim. JSON output defaults to a stable slim contact schema. Add `--raw` with `--json` to include the full parsed contact payload, including the raw vCard text when available.

Search is client-side and matches available name, email, phone, and organization fields case-insensitively.

`ik contacts export` is read-only. It writes the address book as `--format vcf` (default) or
`json`, to `--output <path>` or stdout, and refuses to overwrite an existing file without
`--force`. vCard output copies each contact's original card **verbatim**, so photos, custom `X-`
properties and anything else this CLI does not model survive a backup round trip; contacts without
a parseable vCard are reported in `skipped` rather than silently dropped. With `--json`/`--compact`
and no `--output`, the export travels inside the structured envelope as `body`.

Parsed contacts now also carry `addresses` (all seven `ADR` components), `groups` (`CATEGORIES`),
and `typed_emails`/`typed_phones` that preserve `TYPE=` parameters. The flat `emails` and `phones`
lists are unchanged, so existing consumers keep working.

`ik contacts duplicates` is read-only. It groups candidates by shared email address first, then by
display name, and reports which key matched so you can judge a name-only match yourself.

`ik contacts merge <primary_id> <secondary_id>` unions the secondary's fields onto the primary.
Conflicting scalar fields keep the **primary's** value and are listed as conflicts rather than
resolved silently. **The secondary contact is never deleted** — remove it explicitly with
`ik contacts delete` if you want to. The write touches the primary only, conditionally.

`ik contacts import <file.vcf>` accepts a document containing one or more vCards. Collisions are
detected by UID first, then by email, and a colliding contact is **skipped by default**; pass
`--update-existing` to update it instead, and even then the write is conditional on the current
ETag. `--dry-run` reports how many would be created and how many collide, on which key, without
writing anything. If a failure occurs partway through, the CLI reports how many contacts were
already written.

`ik contacts delete <contact_id>` resolves exactly one contact and deletes it with
`If-Match: <etag>`, so a contact changed remotely since it was resolved is never removed. The
preview shows the display name, emails, phones and organization, states plainly that the deletion
is irreversible, and the result reports whether removal was confirmed.

Still excluded: silent merge, bulk delete, and destructive address-book sync.

Protected writes:

```bash
ik --profile work contacts create --name "Example Person" --email person@example.com --dry-run
ik --profile work contacts create --name "Example Person" --email person@example.com
ik --profile work contacts update <contact_id> --organization "Example Co" --dry-run
ik --profile work contacts update <contact_id> --phone "+352 123" --yes --json
ik contacts merge <primary_id> <secondary_id> --dry-run --json
ik contacts import ./contacts.vcf --dry-run --json
ik --profile work contacts import ./contacts.vcf --update-existing --yes
ik contacts delete <contact_id> --dry-run --json
```

Create writes one vCard with `If-None-Match: *`, so it never overwrites an existing resource. Update first resolves exactly one contact, previews before/after fields, preserves unmodeled raw vCard properties, and writes with the resolved ETag in `If-Match` to prevent lost updates. Both require confirmation by default, support `--dry-run` and structured output, and allow `--yes` only with an explicit profile.

Not implemented: contact delete, import, bulk export, sync writes, or groups. `contacts groups` is deferred until address-book/group discovery is confirmed cleanly.

## Calendar

Read-only commands:

```bash
ik auth calendar --username <sync-username> --stdin

ik calendar list
ik calendar list --json
ik calendar today
ik calendar today --calendar <calendar_id_or_url> --json
ik calendar upcoming --days 14
ik calendar upcoming --days 30 --limit 20 --json
ik calendar search "invoice" --days 30 --json
ik calendar search "invoice" --from 2026-01-01 --to 2026-02-01 --json
ik calendar search --status CONFIRMED --json                          # filters, no query needed
ik calendar search --attendee user@example.com --timed --json
ik calendar search --uid <event_uid> --json                           # exact UID match
ik calendar show <event_id> --json
ik calendar show <event_id> --json --raw
ik calendar export --days 90 --format ics --output backup.ics
ik calendar export --from 2026-01-01 --to 2026-12-31 --format json --json
```

Protected writes (off by default, confirmation required):

```bash
ik calendar create --summary "Deploy review" --start 2026-08-01T15:00 --end 2026-08-01T16:00 --dry-run
ik calendar create --summary "Deploy review" --start 2026-08-01T15:00                       # prompts to confirm
ik calendar create --summary "Vacation" --start 2026-08-10 --end 2026-08-15 --all-day
ik --profile work calendar create --summary "Standup" --start 2026-08-01T09:00 --yes
ik calendar create --summary "Team sync" --start 2026-08-01T09:00 \
    --reminder-minutes 1440 --reminder-minutes 30 --dry-run          # repeatable reminders
ik --profile work calendar create --summary "Quarterly review" --start 2026-09-01T09:00 \
    --uid quarterly-review-2026q3 --if-missing --yes                 # safe to re-run
ik calendar create --summary "Quarterly deadline" --start 2026-03-31T09:00 \
    --rrule "FREQ=MONTHLY;INTERVAL=3;COUNT=4" --dry-run          # recurring, no attendees
ik --profile work calendar create-series --summary "Quarterly deadline" \
    --date 2026-03-31T09:00 --date 2026-06-30T09:00 \
    --date 2026-09-30T09:00 --date 2026-12-31T09:00 \
    --uid-prefix quarterly-2026 --if-missing --yes               # safe to re-run
ik calendar repair --dry-run --json                                  # local config only
ik --profile work calendar repair --url <collection_url> --yes
ik calendar update <event_id> --summary "New title" --reminder-minutes 30 --dry-run --json
ik --profile work calendar update <event_id> --start 2026-08-01T10:00 --yes
ik calendar cancel <event_id> --dry-run --json                       # soft cancellation
ik calendar delete <event_id> --hard --dry-run --json               # hard resource deletion
```

`ik calendar list`, `ik calendar upcoming`, `ik calendar today`, `ik calendar search`, and `ik calendar show` use the configured CalDAV collection URL. `ik auth calendar` auto-discovers that collection from the default DAV base `https://sync.infomaniak.com/`; pass `--url` to override or `--no-discover` to save a URL verbatim. JSON output defaults to stable slim calendar/event schemas. Add `--raw` with `--json` to include full parsed calendar/event payloads, including raw ICS text for events when available.

Search is client-side and matches available summary, description, location, organizer, and attendee fields case-insensitively.

`ik calendar search` also accepts `--attendee`, `--uid`, `--status`, `--description`, and a mutually exclusive `--all-day` / `--timed`. Every supplied criterion must match (AND), and the positional query becomes optional once at least one filter is given. `--uid` and `--status` match exactly (`--status` case-insensitively), while `--attendee` and `--description` are case-insensitive substrings. An event with no `STATUS` property does not match an explicit `--status` filter.

`ik calendar export` is read-only. It resolves a date range exactly like `search` (`--days`, `--from`/`--to`, `--calendar`, `--limit`) and writes `--format ics` (default) or `--format json` to `--output <path>`, or to stdout when `--output` is omitted. ICS output copies each event's original `VEVENT` verbatim inside one `VCALENDAR` envelope, so unmodeled properties survive a backup round trip; any event without a parseable `VEVENT` is reported in `skipped` rather than silently dropped. An existing `--output` file is never overwritten without `--force`. With `--json`/`--compact` and no `--output`, the export travels inside the structured envelope as `body`.

`--rrule` adds a single recurrence rule to a created event, e.g. `FREQ=MONTHLY;INTERVAL=3;COUNT=4`. The rule is validated and normalized locally — only `KEY=VALUE` parts, only known RFC 5545 part names, a known `FREQ`, no repeated parts, and no embedded line breaks — so a malformed rule is refused before any request rather than failing the whole `PUT`, and a rule can never inject an extra iCalendar property. Recurrence adds no attendees and notifies nobody.

`ik calendar create-series` creates one event per explicit `--date`, for the administrative case of a fixed list of deadlines. Each event's UID is `<--uid-prefix>-<date>`, so the whole series is deterministic and re-running with `--if-missing` is a no-op instead of a second set of events. Duplicate `--date` values and colliding derived UIDs are refused before any request; `--duration-minutes` cannot be combined with `--all-day`. The preview lists every event with its resolved start, end and UID, and one confirmation covers the batch. Because a series is a batch of independent writes, a failure partway through prints the failing UID and the UIDs already created, and points at `--if-missing` to finish the remainder without duplicating them.

Attendees, invitations, RSVP, and `calendar import` are **not implemented**. Infomaniak's CalDAV server advertises a scheduling outbox, so an attendee write would likely email real people; that surface stays disabled until the notification behavior is verified live. Events with attendees are still refused by `calendar update`, `cancel`, and `delete`.

`ik calendar repair` resolves and saves the profile's real CalDAV collection URL. It changes local profile config only and never touches calendar data, but still previews before/after, confirms by default, supports `--dry-run`, and gates `--yes` on an explicit profile. When discovery finds several collections it refuses to guess and lists them so `--url` can select one. Calendar reads also self-heal for the current run when the saved URL is still the service root, printing a note that suggests `calendar repair`.

`ik calendar search` accepts `--from` and `--to` together for explicit historical or future ranges. Bounds accept ISO dates or datetimes; a missing offset is interpreted as UTC. `--days` defaults to 30 only when no explicit range is supplied and cannot be combined with `--from`/`--to`.

`ik calendar create` creates an event by PUTting a minimal iCalendar VEVENT to the collection (`PUT {collection}/{uid}.ics` with `If-None-Match: *`, so it never overwrites an existing uid). It follows the protected-write contract: prints a profile/calendar/summary/start/end preview and requires confirmation. `--dry-run` shows the event and the full iCalendar body without writing. `--start`/`--end` take ISO 8601 datetimes (naive = floating local, offset/`Z` = normalized to UTC); with `--all-day` they take `YYYY-MM-DD` dates. `--end` defaults to +1h (timed) or +1 day (all-day). `--yes` skips the prompt only with an explicit profile (`--profile`/`IK_PROFILE`). `--location`/`--description` are optional. No attendees are invited.

`--reminder-minutes N` is repeatable and writes one display `VALARM` per value at create time, so a reminder no longer requires create-then-update. Negative and duplicate values are refused. `--uid` supplies a deterministic UID instead of a random one, which is what makes a re-run safe; combined with `--if-missing`, an event that already exists is reported as `created: false, existed: true` and exits 0 instead of erroring. `--if-missing` requires `--uid`, because a random UID can never match an existing event. Without `--if-missing`, an existing UID stays an error.

`ik calendar update` resolves the exact resource URL and ETag, preserves all unmodeled ICS content,
and uses `If-Match` to prevent lost updates. It supports summary, start/end, location, description,
and `--reminder-minutes`; reminder edits require exactly one existing simple alarm so complex alarm
sets are never flattened. `calendar cancel` is a soft cancellation (`STATUS:CANCELLED`), while
`calendar delete --hard` removes the CalDAV resource and is clearly irreversible through `ik`.
All three preview before/after or deletion implications, confirm by default, support structured
dry-runs, gate `--yes` on an explicit profile, and perform readback after a write. Events with
attendees are refused because RSVP/invite notification effects have not been verified. RSVP,
attendee/invite changes, multi-component recurring-resource edits, bulk changes, and calendar sync
remain excluded.

## Write safety contract

Every command that can change a service follows the same contract, and the test suite enforces it
rather than relying on convention:

- the exact resolved target and action appear in the preview and in `--dry-run`;
- confirmation is required by default;
- `--yes` skips confirmation **only** with an explicit `--profile` (or `IK_PROFILE`), so automation
  can never write to whichever profile happens to be current;
- structured `--json`/`--compact` output is always available;
- errors are redacted, and successful writes read the result back where the service supports it.

`tests/test_write_contract.py` introspects the parser and fails if a new mutating command misses any
of these. The few commands that take `--yes` without the full contract — `profile delete`,
`auth logout`, `doctor --fix-path`, `update` — are local-only and are listed there with a reason.

Write results include a **`notified`** field stating the real external effect: `true` for
`mail send`, `mail reply`, `mail forward`, `chat post` and `chat reply`, which genuinely reach other
people, and `false` for local or single-user writes such as `mail draft`, `calendar create` and
`drive mkdir`. A `--dry-run` always reports `notified: false`.

Where a command reports before/after state it also reports **`changed`**, listing only the fields
that actually differ, so you do not have to diff two full objects by eye.

`ik doctor --json` includes a **`capabilities`** section reporting whether `mail.send`,
`mail.attachments`, `drive.write`, `calendar.write`, `contacts.write` and `chat.post` are possible
for the selected profile, and naming the exact command that fixes anything missing. It inspects
local configuration only and never performs a network call or a write.

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

Compact single-line slim JSON is supported on all discovery and read-only commands:

```bash
ik doctor --compact
ik account list --compact
ik drive tree --compact
ik mail folders --compact
ik calendar list --compact
ik contacts list --compact
```

Dense human table mode:

```bash
ik drive list --table
ik drive recent --table
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
