# Architecture

`infomaniak-cli` is a small Python CLI (`ik`) for Infomaniak/kSuite. Reads are
broadly available; writes are added only as protected, exact-target workflows.
This document maps the modules and the patterns that keep it testable.

## Layout

```
src/infomaniak_cli/
  cli.py            # argparse parser + cmd_* handlers; output/runtime/prompt helpers
  api.py            # InformaniakAPIClient: REST transport (injectable), errors, redaction
  auth.py           # five per-profile secret stores (token, mail, contacts, calendar, chat)
  profiles.py       # ProfileManager + Profile: JSON-backed profile config
  config_paths.py   # config/tokens dir resolution (honors IK_CONFIG_DIR)
  secure_store.py   # secure_dir/secure_write: owner-only credential files at rest
  output.py         # pretty/compact JSON, structured error_json, redact(), render_table
  local_paths.py    # shared Windows/MSYS/Unix local path normalization
  readiness.py      # build_readiness(): per-service "is it set up?" summary
  doctor.py         # run_doctor(): local diagnostics
  pathcheck.py      # read-only install/PATH diagnostics
  bootstrap.py      # account/product/service discovery into a profile
  debug.py          # probe_profile(): endpoint probing for diagnostics
  update.py         # self-update (ik update) against GitHub releases
  services/
    account.py        # accounts/products/services + slim_* projections
    drive.py          # kDrive reads + protected upload/move/rename/trash/restore services
    mail.py           # IMAPClient (read-only BODY.PEEK) + slim_message
    mail_discovery.py # mailboxes / mail hostings
    contacts.py       # CardDAV ContactsClient
    calendar.py       # CalDAV CalendarClient
    chat.py           # Mattermost-compatible kChat ChatClient
    dav_discovery.py  # CardDAV/CalDAV collection discovery
```

## Layers

- **CLI (`cli.py`)** owns argument parsing and the `cmd_*` handlers. It resolves
  the active profile (precedence: `--profile` → `IK_PROFILE` → saved current),
  selects output mode, and never embeds business logic that belongs in a service
  module. Output gating goes through `_machine_output`/`print_machine`/`_raw_output`;
  prompts go through `_is_non_interactive`/`_prompt`/`_confirm` so nothing blocks
  under automation.
- **Services (`services/*`)** are pure-ish modules that talk to one backend each
  and return plain dict/list data plus stable `slim_*` projections for `--json`.
  The CLI formats; services fetch and shape.
- **Transport** is split per backend: `api.py` for the Infomaniak REST API, IMAP
  for mail, CardDAV/CalDAV for contacts/calendar, and a Mattermost-compatible
  HTTP client for kChat. kChat is **not** on `api.infomaniak.com`.

## Profile & credential storage

Profiles live as JSON under the config dir (`config_paths.get_config_dir()`,
overridable with `IK_CONFIG_DIR`). Secrets live under `tokens/` via the five
stores in `auth.py`. Every credential write goes through `secure_store.secure_write`
(POSIX `chmod 0o600`, the `tokens/` dir `0o700`; Windows best-effort `icacls`),
best-effort and non-fatal — defense in depth, not encryption.

## Output & error contract

`output.py` centralizes JSON (`pretty_json`/`compact_json`), the structured
`error_json` envelope emitted on stderr when `--json`/`--compact` is active, the
`redact()` helper, and `render_table` for `--table`. Default JSON is slim; `--raw`
exposes full upstream payloads. Exit codes: `0` success, `1` runtime error, `2`
CLI usage error. See [agent-workflow.md](agent-workflow.md) for the agent contract.

## Testing approach

The suite is fully offline. Every transport is **injectable** so tests never hit
the network:

- `InformaniakAPIClient` / `ChatClient` accept an injected `opener`.
- `IMAPClient` accepts an `imap_factory`; CLI tests swap `cli.IMAPClient`/`cli.ChatClient`
  for fakes.
- `secure_store`'s Windows runner is swapped for a no-op via an autouse fixture
  (`tests/conftest.py`); POSIX `chmod` stays real so mode assertions are meaningful.

Tests set `IK_CONFIG_DIR` to a tmp path so they never read or write real profiles
or secrets. Add tests for every behavior change (TDD).
