# Mail setup (IMAP) — read this first, it saves a lot of time

Setting up `ik mail` is the trickiest part of Infomaniak, because Infomaniak has **two different
kinds of "application password"** and only one of them works for mailbox IMAP. This guide gets it
right the first time.

## TL;DR

```bash
ik auth mail --mailbox you@example.com --password "<mailbox-device-password>"
ik mail unread --json
```

- The password must come from **https://config.infomaniak.com/** (the mail sync assistant,
  "add a device" flow) — **NOT** the account-level "Application passwords" page.
- The username must be the **full email address** (e.g. `you@example.com`, not `you`).

## Why mail is different from the rest of the CLI

Everything else in `ik` uses your **REST API token** (from the Manager developer area).

**Mail does not.** Infomaniak's REST API only exposes mailbox *administration*, not message
reading. To actually read mail you connect over **IMAP**, which needs a **separate mailbox
password** — not your REST token, and not your login password.

## The password trap (important)

Infomaniak shows TWO things that both look like "application passwords":

| Where you find it | Works for IMAP? |
|-------------------|-----------------|
| Manager → My Profile → Security → **Application passwords** | ❌ NO — rejected with `Invalid login or password` |
| **https://config.infomaniak.com/** → add a device / mail sync assistant | ✅ YES — this is the mailbox password IMAP needs |

If you use the account-level "Application passwords" one, login fails every time with
`Invalid login or password`, even though the password is technically valid — it just isn't a
**mailbox** password. This is the #1 reason mail setup fails.

### Extra note for 2FA accounts
If your account has two-factor auth enabled (recommended, and common for company accounts), your
normal login password can **never** be used for IMAP — there is no way to do the phone/app
confirmation over IMAP. The device password from config.infomaniak.com bypasses this correctly.

## Step by step

1. Go to **https://config.infomaniak.com/**
2. Choose to **add a new device** / configure a mail client for the mailbox you want
   (e.g. `you@example.com`).
3. The assistant generates a **device password** for that mailbox. It may be shown grouped with
   spaces (e.g. `abcd efgh ijkl mnop`) — spaces are ignored, you can keep or remove them.
4. Copy it. It is shown only once.
5. Store it in `ik`:
   ```bash
   ik auth mail --mailbox you@example.com --password "abcd efgh ijkl mnop"
   ```
   Or pipe it without it appearing in shell history:
   ```bash
   ik auth mail --mailbox you@example.com --stdin
   ```
6. Test:
   ```bash
   ik mail unread --json
   ```

## Confirmed working settings

```text
IMAP host : mail.infomaniak.com
IMAP port : 993 (SSL/TLS)
Username  : full email address (you@example.com)
Password  : device password from config.infomaniak.com
```

## Commands

```bash
ik mail folders [--json] [--raw]
ik mail labels   # alias for folders

ik mail list [--folder/-f <name>] [--limit/-n N] [--unread]
             [--since YYYY-MM-DD] [--before YYYY-MM-DD] [--days N]
             [--json] [--raw]

ik mail unread [--limit N] [--json] [--raw]   # shortcut for list --unread

ik mail search "query" [--folder/-f <name>] [--limit N] [--unread]
                       [--since YYYY-MM-DD] [--before YYYY-MM-DD] [--days N]
                       [--json] [--raw]

ik mail read <uid> [--folder/-f <name>] [--json] [--raw]
ik mail threads [--folder/-f <name>] [--days N] [--since YYYY-MM-DD] [--before YYYY-MM-DD] [--limit/-n N] [--json] [--raw]
```

- `--folder` selects any IMAP folder. Default is `INBOX`.
- `--days N` is a shortcut for `--since` set to `today - N days`.
- `--since`/`--before` accept dates as `YYYY-MM-DD`.
- `--unread` filters to unread messages only.
- `ik mail list` shows **both** read and unread messages by default; each message has a `seen` flag in JSON output.

`<uid>` is a number from the `unread`/`search` output. In PowerShell do NOT type the angle
brackets — `<` is a reserved operator. Use the bare number:

```powershell
ik --profile work mail read 70 --json
```

## Examples

```bash
ik mail folders --json
ik mail list --folder Sent --days 7 --json
ik mail list --folder Spam --days 5 --json
ik mail list --since 2026-06-01 --before 2026-06-15 --json
ik mail unread --json
ik mail search "invoice" --days 30 --json
ik mail read 123 --json
ik mail read 123 --folder Spam --json
ik mail threads --days 7 --json
ik mail threads --folder Sent --since 2026-06-01 --json
```

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Invalid login or password` | Used the account-level application password | Generate the mailbox password at https://config.infomaniak.com/ |
| `Invalid login or password` with correct-looking password | Username was the local part only | Use the FULL email address |
| Works in webmail but not IMAP, 2FA on | Login password can't pass 2FA over IMAP | Use the config.infomaniak.com device password |
| `The '<' operator is reserved` (PowerShell) | You typed literal `<uid>` | Use the real number, no angle brackets |
| `invalid date` | Date not in YYYY-MM-DD format | Use `--since 2026-06-01`, not `--since 01/06/2026` |

## Security

- The mailbox password is stored locally, separate from your REST token, and is redacted in output.
- It is never committed to git.
- `ik mail` is read-only. Sending (SMTP) is a future feature.
