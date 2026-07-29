# infomaniak-cli

![version](https://img.shields.io/badge/version-0.2.14-blue) ![license](https://img.shields.io/badge/license-MIT-green) ![python](https://img.shields.io/badge/python-%3E%3D3.11-blue) ![platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20mac-lightgrey)

**Unofficial CLI for [Informaniak](https://www.infomaniak.com) — manage your kSuite accounts, kDrive, mail, and services from any terminal or IDE.**

Built for personal and company Informaniak accounts. Token-based auth — no browser session required.

> ⚠️ **Unofficial project** — this is not an official Informaniak product. It is a community tool built independently.
>
> 🤖 **AI-assisted development** — this project was built with AI assistance (Claude, Codex, Hermes). Architecture, tooling decisions, and implementation were developed through human-AI collaboration. The code works and the design is intentional, but it was not written line by line without AI involvement. Contributions are welcome regardless of how they are written.

## Install

Requires Python 3.11+.

`infomaniak-cli` is distributed through GitHub — it is **not** published on PyPI, so install it from the repository or a release wheel, not from a bare `infomaniak-cli` package name.

Recommended global install with [pipx](https://pipx.pypa.io/), straight from GitHub:

```bash
pipx install git+https://github.com/VidGuiCode/infomaniak-cli.git --backend pip
ik version
```

Alternative install with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/VidGuiCode/infomaniak-cli.git
ik version
```

Plain `pip` also works (use a virtual environment so the CLI stays isolated from your system Python packages):

```bash
pip install git+https://github.com/VidGuiCode/infomaniak-cli.git
```

To pin a specific version, install its release wheel from the [Releases page](https://github.com/VidGuiCode/infomaniak-cli/releases):

```bash
pipx install https://github.com/VidGuiCode/infomaniak-cli/releases/download/<tag>/infomaniak_cli-<version>-py3-none-any.whl --backend pip
```

For development:

```bash
git clone https://github.com/VidGuiCode/infomaniak-cli.git
cd infomaniak-cli
uv sync
```

## Update

```bash
ik update
ik update --yes
```

`ik update` checks the latest GitHub release and can update pipx, uv tool, or pip installs when a release wheel is available. Source checkouts stay manual and print `git pull` / `uv sync` instructions.

For pipx installs, `ik update` upgrades the package inside the pipx environment using `pipx runpip`.
`pipx list` can therefore show stale package metadata; use `ik version` as the source of truth.

### Troubleshooting: `ik` not found / not on PATH

A `pip install --user` install can put `ik` in a per-user scripts directory that is not on your `PATH` (Windows: `%APPDATA%\Python\PythonXYZ\Scripts`; Linux/macOS: `~/.local/bin`), so the shell reports `ik: command not found`.

Run `ik doctor` to see your install method and a PATH check. When `ik` is installed but not on PATH, doctor prints the scripts directory. You can automatically fix this by running:

```bash
ik doctor --fix-path
```

Then open a new terminal so the change takes effect. (`pipx` and `uv tool` installs put `ik` on PATH automatically, which is why they are recommended above.)

## Quick start

```bash
ik setup --profile work
ik auth token
# paste your Informaniak Manager personal API token

ik bootstrap --json
ik whoami --json
ik doctor --json
ik completion bash > ~/.bash_completion.d/ik

ik auth mail --mailbox user@example.com --password <app-password>
ik auth contacts --username <sync-username> --stdin
ik auth calendar --username <sync-username> --stdin
ik auth chat --url <kchat-base-url> --token <kchat-token> --team-id <team_id>

ik account list
ik account services
ik account services --json --raw
ik account products --json --raw  # lower-level catalog diagnostics

ik drive list
ik drive list --json
ik drive list --json --raw
ik drive folders --json
ik drive tree --depth 2 --json
ik drive recent --limit 10 --json
ik drive shared --json
ik drive search "invoice" --json
ik drive info <file_id> --json
ik drive download <file_id> --output ./downloads/
ik --profile work drive rm <file_id> --dry-run
ik --profile work drive upload ./report.pdf --parent <folder_id> --dry-run
ik --profile work drive move <file_id> <destination_folder_id> --dry-run
ik --profile work drive rename <file_id> "New name.pdf" --dry-run
ik drive trash list --json
ik --profile work drive trash restore <file_id> --dry-run
ik drive share-state <file_id> --json

ik mail folders --json
ik mail mailboxes --json
ik mail hostings --json
ik mail list --days 7 --json
ik mail unread
ik mail search "invoice" --days 30 --json
ik mail search --from infomaniak --subject invoice --json
ik mail read <uid> --json
ik mail read <uid> --html
ik mail threads --folder Sent --days 7 --json

ik contacts list --json
ik contacts search "accountant" --json
ik contacts show <contact_id> --json
ik --profile work contacts create --name "Example Person" --email person@example.com --dry-run
ik --profile work contacts update <contact_id> --organization "Example Co" --dry-run

ik calendar list --json
ik calendar upcoming --days 14 --json
ik calendar today --json
ik calendar search "invoice" --from 2026-01-01 --to 2026-02-01 --json
ik calendar search --status CONFIRMED --timed --json
ik calendar show <event_id> --json
ik calendar export --days 90 --format ics --output backup.ics

ik chat teams --json
ik chat channels --json
ik chat users --json
```

Context (profile, account, drive) is sticky — set it once and every command uses it. Profile selection precedence is explicit `--profile`, then `IK_PROFILE`, then the saved current profile. Global `--profile` and `--base-url` flags work before or after subcommands.

`ik bootstrap` refreshes safe read-only defaults such as account, mail hosting, default mailbox, and default kDrive. It also prints readiness and missing setup actions for Mail, Contacts, Calendar, and kChat without guessing or storing credentials.

## Mail setup

Mail works over IMAP. Go to **https://config.infomaniak.com/**, use the **add a device** flow for your mailbox, and copy the generated credentials into the CLI.

Then:

```bash
ik auth mail --mailbox you@example.com --password "<config.infomaniak.com device password>"
ik mail mailboxes --json
ik mail unread --json
```

`ik mail mailboxes` discovers which mailbox addresses are visible from the profile/bootstrap/API context. Reading actual message content still uses IMAP, so `ik auth mail` is still required before `ik mail unread`, `ik mail list`, `ik mail read`, or `ik mail threads`.

Protected plain-text drafts and sends use the same mailbox device password. Preview first; an
actual write confirms interactively, while unattended `--yes` requires an explicit profile:

```bash
ik mail draft --to recipient@example.com --subject "Review" --body "Draft body" --dry-run --profile work
ik mail send --to recipient@example.com --subject "Hello" --body "Message body" --dry-run --profile work
```

Drafts are appended over IMAP with the `\Draft` flag. Sends use authenticated SMTP-over-SSL on
port 465. Attachments, HTML, bulk sends, delete, move, and mark-as-read remain excluded.

Use the full email address as the mailbox username.

Full walkthrough and troubleshooting: **[`docs/mail-setup.md`](docs/mail-setup.md)**.

## Contacts setup

Contacts use CardDAV through Infomaniak sync. You must generate an application password at **https://config.infomaniak.com/** (under *My Contacts & Calendars* -> *Windows* -> *CalDav Synchronizer*). Do not use an account-level password.

Use your sync username, then paste the application password into stdin:

```bash
ik --profile <profile> auth contacts --username <sync-username> --stdin
ik contacts list --json
```

From the default DAV base `https://sync.infomaniak.com/`, `ik auth contacts` auto-discovers your address-book collection (standard CardDAV principal/home-set discovery) and saves it. If several address books exist it picks a sensible default and prints the rest so you can re-run with `--url <collection-url>`. Pass `--url` to set a collection explicitly, or `--no-discover` to save the URL verbatim. The CLI does not reuse mail credentials automatically.

## Calendar setup

Calendar uses CalDAV through Infomaniak sync. You must generate an application password at **https://config.infomaniak.com/** (under *My Contacts & Calendars* -> *Windows* -> *CalDav Synchronizer*). Do not use an account-level password.

Use your sync username, then paste the application password into stdin:

```bash
ik --profile <profile> auth calendar --username <sync-username> --stdin
ik calendar upcoming --days 14 --json
```

From the default DAV base `https://sync.infomaniak.com/`, `ik auth calendar` auto-discovers your calendar collection and saves it; with multiple calendars it picks a default and lists the rest for re-running with `--url <collection-url>`. Pass `--url` to set a collection explicitly, or `--no-discover` to save the URL verbatim. The CLI does not reuse mail or contacts credentials automatically.

If a profile's calendar URL was left as the service root, calendar reads auto-discover a usable collection for that run and print a note. `ik calendar repair` resolves and saves the real collection permanently; it refuses to guess when several calendars are found, so pass `--url <collection-url>` to choose one. Repair changes local profile config only.

The four credentials a profile can hold — API token, mailbox password, Contacts/CardDAV password, Calendar/CalDAV password — are distinct and stored separately. See [docs/setup-and-profiles.md](docs/setup-and-profiles.md#the-four-credentials).

## kChat setup

kChat uses Mattermost-compatible connection settings:

```bash
ik auth chat --url "https://ksuite.infomaniak.com/<account_id>/kchat/<workspace>/channels/<channel>"
ik chat teams --json
```

The browser URL is parsed locally, then the CLI tries the trusted API base `https://<workspace>.kchat.infomaniak.com` with your main Informaniak API token. If that token is not accepted, save a dedicated kChat token:

```bash
ik auth chat --url "https://ksuite.infomaniak.com/<account_id>/kchat/<workspace>/channels/<channel>" --stdin
```

You can also configure the direct trusted API base:

```bash
ik auth chat --url "https://<workspace>.kchat.infomaniak.com"
ik chat teams --json
```

The CLI never sends the main API token to arbitrary kChat URLs. Use `--stdin` or `--token` for non-Infomaniak hosts.

## Commands

| Area | Commands |
|------|----------|
| Setup | `setup`, `whoami`, `doctor`, `completion` |
| Update | `update` |
| Auth | `auth token`, `auth check`, `auth status`, `auth logout`, `auth mail`, `auth contacts`, `auth calendar`, `auth chat` |
| Profile | `profile list`, `show`, `use`, `rename`, `delete` |
| Discovery | `account list`, `products`, `services` |
| kDrive | `drive list`, `drive folders`, `drive tree`, `drive recent`, `drive shared`, `drive search`, `drive info`, `drive mkdir`, `drive download`, `drive upload`, `drive move`, `drive rename`, `drive rm`, `drive trash list/show/restore`, `drive share-state` |
| Mail | `mail mailboxes/accounts`, `mail hostings`, `mail folders/labels`, `mail list`, `mail unread`, `mail search`, `mail read`, `mail threads`, `mail draft`, `mail send` |
| Contacts | `contacts list`, `contacts search`, `contacts show`, `contacts create`, `contacts update` |
| Calendar | `calendar list`, `calendar upcoming`, `calendar today`, `calendar search`, `calendar show`, `calendar export`, `calendar create`, `calendar create-series`, `calendar update`, `calendar cancel`, `calendar delete`, `calendar repair` |
| kChat | `chat teams`, `chat channels`, `chat users`, `chat search`, `chat thread`, `chat post` |

Run `ik <command> --help` for full options on any command.

## Using with AI agents

Any AI agent that can run shell commands (Claude Code, Cursor, Copilot, Hermes, CLI scripts) can use `infomaniak-cli` directly — no MCP server, no protocol, no setup.

### Recommended workflow

```bash
# 1. Orient
ik whoami --json
ik doctor --json

# 2. Discover
ik account list --json
ik account services --json
ik account products --json --raw  # only when debugging catalog/discovery mismatches

# 3. Use services
ik drive list --json
ik drive list --json --raw
ik drive folders --json
ik drive tree --depth 2 --json
ik drive recent --limit 10 --json
ik drive shared --json
ik drive search "invoice" --json
ik drive info <file_id> --json
ik drive download <file_id> --output ./downloads/
ik --profile work drive rm <file_id> --dry-run
ik --profile work drive upload ./report.pdf --parent <folder_id> --dry-run
ik --profile work drive move <file_id> <destination_folder_id> --dry-run
ik --profile work drive rename <file_id> "New name.pdf" --dry-run
ik drive trash list --json
ik --profile work drive trash restore <file_id> --dry-run
ik drive share-state <file_id> --json

ik mail folders --json
ik mail mailboxes --json
ik mail hostings --json
ik mail list --days 7 --json
ik mail unread --folder INBOX --days 7 --json
ik mail search "invoice" --days 30 --json
ik mail search --from infomaniak --subject invoice --json
ik mail read <uid> --json
ik mail read <uid> --html
ik mail threads --folder Sent --days 7 --json

ik contacts list --json
ik contacts search "accountant" --json
ik contacts show <contact_id> --json
ik --profile work contacts create --name "Example Person" --email person@example.com --dry-run
ik --profile work contacts update <contact_id> --organization "Example Co" --dry-run

ik calendar list --json
ik calendar upcoming --days 14 --json
ik calendar today --json
ik calendar search "invoice" --from 2026-01-01 --to 2026-02-01 --json
ik calendar search --status CONFIRMED --timed --json
ik calendar show <event_id> --json
ik calendar export --days 90 --format ics --output backup.ics

ik chat teams --json
ik chat channels --json
ik chat users --json
```

Use `--json` for pretty structured output, `--compact` for single-line slim JSON (available on all discovery and read-only commands), and `--table` for dense human tables on supported list commands. `ik mail read --json` includes full readable `body_text` without `--raw` (plain text is the default human output; pass `--html` for the raw HTML body); `--raw` keeps fuller parsed message metadata such as `body_preview`. `ik mail search` takes a plain-substring positional query and/or structured `--from`/`--to`/`--subject` filters (not Gmail-style operators). Use `--profile` to target a specific account, or set `IK_PROFILE` for one terminal session.

`ik account services` is the primary workflow discovery command. Its default JSON is a stable,
slim inventory with an `actionable` flag and next-command hints such as `ik drive list`,
`ik mail mailboxes`, and `ik chat channels`; use `--json --raw` for the full upstream payload.
`ik account products` is lower-level catalog data kept for bootstrap diagnostics and support, not
as a daily workflow surface.

When `--json` or `--compact` is active, common command errors use a structured JSON error envelope on stderr.

### Non-interactive / scripted use

`ik` never blocks on a hidden prompt under automation. When stdin is not a TTY, or `IK_NO_INTERACTIVE=1` is set, a command that would prompt instead fails fast with an actionable error: provide secrets with `--stdin` (e.g. `printf '%s' "$TOKEN" | ik --profile work auth token --stdin`) and confirm destructive local commands (`auth logout`, `profile delete`, `update`) with `--yes`.

See **[docs/agent-workflow.md](docs/agent-workflow.md)** for the full agent workflow contract: profile precedence, output modes, exit codes, the structured error envelope, and the recommended command sequence.

## Configuration

Login state is stored in your platform's app-data folder:

- **Windows:** `C:\Users\<user>\AppData\Roaming\infomaniak-cli\`
- **macOS:** `~/Library/Application Support/infomaniak-cli/`
- **Linux:** `~/.config/infomaniak-cli/`

This directory contains your profile config and local secrets. Treat it as a secret and do not share or commit it.

Credential files (your REST API token and any mail/contacts/calendar/kChat app passwords under `tokens/`) are written **owner-only** at rest on a best-effort basis — `chmod 0o600` on POSIX, or an `icacls` ACL restricted to the current user on Windows. This is defense-in-depth, **not encryption**: it limits who can read the files but does not encrypt them. If the permission step ever fails, the secret is still saved and a one-line warning is printed.

`ik auth logout` removes the selected profile's main API token. `ik auth logout --all` also removes local mail, contacts, calendar, and chat secrets for that profile. `ik profile delete <name> --yes` removes the local profile and its related local secrets. None of these commands touch remote services.

To remove the installed CLI itself:

```bash
pipx uninstall infomaniak-cli
```

If you installed with `uv tool`, run `uv tool uninstall infomaniak-cli`. If you installed with plain `pip`, run `pip uninstall infomaniak-cli`.

## How this differs from other tools

- **Official Informaniak Manager** is the web dashboard. `infomaniak-cli` talks to the API on behalf of a user — no web browser required.
- **One MCP per service** would mean separate integrations for Mail, kDrive, kChat, etc. `infomaniak-cli` is one unified CLI for all kSuite services, with an optional future MCP wrapper.

## Development

```bash
uv sync
uv run pytest -q
uv run ik --help
```

Tests use pytest. See `tests/` for coverage of the API client, config paths, profiles, auth, bootstrap, account discovery, and CLI smoke tests.

## Roadmap

See [`context/ROADMAP.md`](context/ROADMAP.md) (private working context) for planned features. Public docs:

- [`docs/vision.md`](docs/vision.md) — full product vision and service mapping
- [`docs/setup-and-profiles.md`](docs/setup-and-profiles.md) — setup/auth/profile flow
- [`docs/mail-setup.md`](docs/mail-setup.md) — IMAP mail setup with config.infomaniak.com device credentials
- [`docs/commands.md`](docs/commands.md) — CLI commands reference
- [`docs/security.md`](docs/security.md) — safety, secrets, profile separation
- [`docs/release.md`](docs/release.md) - install and release guidance

## License

[MIT](LICENSE)
