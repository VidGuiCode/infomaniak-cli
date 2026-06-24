# Security and Safety Notes

## Main risks

The CLI will potentially access personal and company services. The design must prevent accidental cross-account actions.

Important risks:

- sending company mail from the personal account;
- sending personal mail from the company account;
- deleting/moving kDrive files accidentally;
- leaking tokens in logs or terminal output;
- giving Hermes too much write power too early;
- cron jobs using the wrong active/default profile.

## Profile separation

Every profile has separate credentials and defaults:

```text
profiles/work.yaml
profiles/personal.yaml
tokens/work.token.json
tokens/personal.token.json
```

Commands should always show profile context for sensitive operations:

```text
Profile: work
Account: Example Co
Sending from: contact@example.com
To: accountant@example.com
Continue? [y/N]
```

For Hermes/cron, use explicit profile always:

```bash
ik --profile work mail unread
```

Do not rely on the last selected default profile in scheduled jobs. Profile selection precedence is explicit `--profile`, then `IK_PROFILE`, then the saved current profile. A missing `IK_PROFILE` value fails clearly instead of silently falling back.

## Local auth lifecycle

Profile lifecycle commands only change local files:

- `ik auth logout` removes the selected profile's main API token.
- `ik auth logout --all --yes` also removes local mail, contacts, calendar, and chat secrets for that profile.
- `ik profile rename old new` renames local profile metadata and related local secret files.
- `ik profile delete name --yes` deletes only that local profile and its related local secrets.

These commands do not revoke remote tokens, change remote services, delete remote data, or touch unrelated profiles.

## Default permissions model

Initial MVP should be read-first:

Allowed early:

- whoami
- doctor
- account/product/service discovery through `ik account ...`
- profile/default-service discovery through `ik bootstrap`
- service-level mailbox list for the selected user/mailbox when available
- unread/search/read email
- kDrive list/folders/tree/search/info
- kChat channel list

Protected by confirmation:

- send email
- post to kChat
- upload to kDrive
- true company-admin inventory/actions unless explicitly read-only
- change mailbox settings

Avoid until later:

- delete email
- delete kDrive files
- change DNS/domain settings
- remove users/mailboxes
- broad bulk updates

## Token handling

Do not commit tokens or config secrets.

Recommended `.gitignore` entries:

```gitignore
.env
*.token.json
secrets.json
config.local.yaml
```

Prefer OS keyring later if practical. For MVP, local token files are acceptable if they are outside the repo and protected by normal user file permissions.

## Logging

Logs must redact:

- access tokens
- refresh tokens
- app passwords
- mailbox passwords
- Authorization headers
- cookies

Do not print raw API responses if they may contain secrets.

Structured JSON errors are also redacted. When `--json` or `--compact` is active, common command errors use an `error` envelope and should not include tokens, app passwords, cookies, or Authorization header values.

Bootstrap, whoami, and doctor readiness output reports only configured/ready booleans and setup commands. It must not print token values, app passwords, cookies, or Authorization headers.

## Rate limiting

Informaniak docs mention a general API rate limit of 60 requests/minute, with possible extra endpoint-specific limits.

The CLI should:

- avoid spammy polling;
- cache bootstrap discovery where possible;
- retry politely on rate-limit responses;
- provide clear errors.

## Write confirmations

For external side effects, show:

- active profile;
- account name;
- service;
- target;
- action.

Example:

```text
Profile: work
Action: kChat post
Team: Example Co
Channel: admin
Message: Reminder: VAT task due
Continue? [y/N]
```

`--yes` should be allowed only for specific scripted workflows and should still require explicit `--profile`.


## Discovery is not admin

`ik account ...` and `ik bootstrap` describe what the logged-in profile can access. These commands are suitable for normal user/environment discovery.

Manager/admin operations are deferred until a separate, explicit surface exists. Those commands should assume elevated responsibility, show active profile/account context, and avoid writes until explicit confirmation flows exist.
