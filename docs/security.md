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
profiles/cylro.yaml
profiles/personal.yaml
tokens/cylro.token.json
tokens/personal.token.json
```

Commands should always show profile context for sensitive operations:

```text
Profile: cylro
Account: Cylro SARL-S
Sending from: contact@cylro.com
To: accountant@example.com
Continue? [y/N]
```

For Hermes/cron, use explicit profile always:

```bash
ik --profile cylro mail unread
```

Do not rely on the last selected default profile in scheduled jobs.

## Default permissions model

Initial MVP should be read-first:

Allowed early:

- whoami
- doctor
- account/product/service discovery
- mailbox list
- alias list
- unread/search/read email
- kDrive list/search/download
- kChat channel list

Protected by confirmation:

- send email
- post to kChat
- upload to kDrive
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
Profile: cylro
Action: kChat post
Team: Cylro
Channel: admin
Message: Reminder: VAT task due
Continue? [y/N]
```

`--yes` should be allowed only for specific scripted workflows and should still require explicit `--profile`.
