# Using `ik` from an agent

This is the stable contract for driving `infomaniak-cli` from an AI agent
(Claude Code, Hermes, Codex) or any non-interactive script. The goal is boring,
predictable automation: machine-readable output, no hidden prompts, and clear
errors that say exactly which setup command to run next.

Most commands here are read-only. Implemented service writes are explicitly protected with a
context preview, confirmation by default, `--dry-run`, and explicit-profile-gated `--yes`.

## Golden rules

1. **Always pass an explicit `--profile`.** Automation must not depend on the
   saved "current" profile, which a human could change. Use `ik --profile work …`.
2. **Always pass `--json` (or `--compact`)** on read commands so you parse
   structured output, never scraped human text.
3. **Never rely on an interactive prompt.** Provide secrets via `--stdin` and
   confirmations via `--yes` only after validating a `--dry-run`. See [Non-interactive mode](#non-interactive-mode).

Protected mail examples:

```bash
ik mail draft --to recipient@example.com --subject "Review" --body "Draft body" --dry-run --json --profile work
ik mail send --to recipient@example.com --subject "Hello" --body "Message body" --dry-run --json --profile work
```

An agent must not remove `--dry-run` or add `--yes` until the user has authorized the exact
profile, sender, recipients, subject, and body. Actual mail writes require a current-session target.

## Profile selection precedence

1. `--profile <name>` flag (highest — always use this in automation).
2. `IK_PROFILE` env var (per-terminal session).
3. The saved current/default profile (lowest — fine for humans, not automation).

Global `--profile` and `--base-url` options may be placed before or after commands/subcommands;
automation should still pass `--profile` explicitly.

## Output modes

| Flag | Use |
| --- | --- |
| `--json` | Pretty, multi-line structured JSON. Default machine format. |
| `--compact` | Single-line slim JSON. Best for token-efficient agent reads. |
| `--raw` | With `--json`, the full upstream payload instead of the slim schema. |
| `--table` | Dense human table. **Not** a machine contract — never parse it. |

`--table` cannot be combined with `--json`/`--compact`.

`--compact` is available on all discovery and read-only commands:

- `whoami`, `doctor`, `bootstrap`
- `account list`, `account products`, `account services`
- `drive list`, `drive folders`, `drive tree`, `drive recent`, `drive shared`, `drive search`, `drive info`
- `mail list`, `mail unread`, `mail search`, `mail read`, `mail mailboxes`, `mail hostings`, `mail folders`, `mail threads`
- `calendar list`, `calendar upcoming`, `calendar today`, `calendar search`, `calendar show`
- `contacts list`, `contacts search`, `contacts show`
- `chat teams`, `chat channels`, `chat users`, `chat search`, `chat thread`

`ik mail read --json` includes the full readable `body_text` without needing
`--raw`; the human output prints text by default, and `--html` prints the raw
HTML body instead. `ik mail search` accepts a plain-substring positional query
and/or structured `--from`/`--to`/`--subject` filters (these are IMAP header
matches, not Gmail-style operators). `ik chat search --channel` accepts a channel
slug or id.

## Non-interactive mode

`ik` treats a run as non-interactive when **any** of these is true:

- the stdin is not a TTY (piped, redirected, or run by an agent), or
- the `IK_NO_INTERACTIVE` env var is set to `1`/`true`/`yes`/`on`, or
- the command supports `--non-interactive` and it was passed (`setup`, `bootstrap`).

In non-interactive mode, a command that would otherwise prompt **fails fast with
an actionable error instead of hanging**:

- Secret input → provide it with `--stdin` (preferred) or `--token`/`--password`.
- Confirmations (`auth logout`, `profile delete`, `update`) → pass `--yes`.

Save credentials without a prompt by piping them on stdin:

```bash
printf '%s' "$IK_TOKEN" | ik --profile work auth token --stdin
printf '%s' "$IK_MAIL_APP_PASSWORD" | ik --profile work auth mail --mailbox user@example.com --stdin
```

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | General runtime error (API error, auth failure, validation, missing config). |
| `2` | CLI usage error (bad/missing arguments, mutually exclusive flags). |

When `--json` or `--compact` is active, errors are emitted as a structured JSON
envelope on **stderr**:

```json
{"error":{"type":"auth_failure","message":"…","exit_code":1}}
```

`type` is one of `missing_profile`, `auth_failure`, `api_error`,
`validation_error`, or `runtime_error`. Tokens, passwords, cookies, and
`Authorization` headers are redacted from every error path.

## Recommended workflow

```bash
# 0. One-time, non-interactive credential setup
printf '%s' "$IK_TOKEN" | ik --profile work auth token --stdin
ik --profile work bootstrap --json --non-interactive

# 1. Orient
ik --profile work whoami --compact
ik --profile work doctor --compact

# 2. Discover
ik --profile work account services --compact

# 3. Read services
ik --profile work drive search "invoice" --compact
ik --profile work mail unread --days 7 --compact
ik --profile work calendar upcoming --days 14 --compact
ik --profile work contacts search "accountant" --compact
ik --profile work chat channels --compact
```

`ik account services` is the primary workflow discovery command: its slim records state whether a
service is actionable and provide the next CLI command. `ik account products` is lower-level
catalog data; agents should request `ik account products --json --raw` only for diagnostics.

## Environment variables

| Var | Effect |
| --- | --- |
| `IK_PROFILE` | Default profile when `--profile` is omitted. |
| `IK_CONFIG_DIR` | Override the config/secrets directory (useful for CI/sandboxes). |
| `IK_NO_INTERACTIVE` | Force non-interactive mode regardless of TTY. |

## Handling "not configured" errors

Missing-config errors name the exact command to fix them, e.g.:

```
No default mailbox configured for profile: work.
Run `ik --profile work auth mail` to set the mailbox email and app password.
```

Parse the suggested `ik … auth …` command (or surface it to the user) rather than
guessing credentials.
