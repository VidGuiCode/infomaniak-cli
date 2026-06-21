# Setup, Auth, Bootstrap, and Profiles

## Key decision

Profiles should be created during setup/auth login, not as a separate mandatory step.

The normal first command should be:

```bash
ik setup
```

This should leave the user with a ready-to-use profile.

## Ideal first-time flow

```bash
ik setup
```

Interactive flow:

```text
No profiles found.

What is this profile for?
> cylro

Open Informaniak login? [Y/n]

Authenticated as: gui@example.com

Found accounts:
1. Personal account
2. Cylro SARL-S

Use which account for profile "cylro"?
> 2

Found mailboxes:
1. contact@cylro.com
2. admin@cylro.com
3. gui@cylro.com

Default mailbox?
> 1

Found kDrives:
1. Cylro Documents
2. Shared Admin

Default kDrive?
> 1

Make "cylro" the default profile? [Y/n]
```

Final output:

```text
✓ Profile created: cylro
✓ Authenticated as: gui@example.com
✓ Account selected: Cylro SARL-S
✓ Default mailbox: contact@cylro.com
✓ Default kDrive: Cylro Documents
✓ kChat workspace: Cylro
✓ Profile is ready
```

## Adding another account/profile later

```bash
ik setup --profile personal
```

or:

```bash
ik auth login --new-profile personal
```

The setup flow should authenticate, discover accounts/products, and save defaults for that profile.

## Profiles are important

Gui has personal and company Informaniak usage. The CLI must keep them separated.

Expected usage:

```bash
ik profile use cylro
ik whoami

ik --profile personal mail unread
ik --profile cylro drive search "invoice"
```

For Hermes and cron jobs, always prefer explicit profile:

```bash
ik --profile cylro mail unread
```

This avoids accidental personal/company mixups.

## Profile commands

Management commands should exist, but normal users should not need them before setup.

```bash
ik setup
ik setup --profile cylro

ik profile list
ik profile use cylro
ik profile show
ik profile rename old new
ik profile delete old

ik auth login
ik auth logout
ik auth status
ik bootstrap
ik doctor
ik whoami
```

## Smart auth behavior

`ik auth login` should be smart:

- if no profile exists, redirect to `ik setup`;
- if a current profile exists, refresh/re-authenticate that profile;
- if `--new-profile NAME` is given, create/setup that profile.

## Bootstrap/autodiscovery

`ik bootstrap` should discover and save IDs automatically.

It should attempt to find:

- authenticated Informaniak user/profile;
- accessible accounts;
- current/default account;
- kSuite products;
- mail hostings;
- mailboxes;
- aliases;
- kDrive IDs/names;
- kChat teams/channels;
- kMeet rooms/settings if available;
- domains/DNS services if relevant later.

If multiple choices exist, ask the user to choose from a list rather than requiring manual ID hunting.

## Discovery vs admin naming

Bootstrap/discovery is about the logged-in user's accessible environment. It must not assume the profile has company-admin rights.

Use neutral account commands for user-accessible inventory:

```bash
ik account list
ik account products
ik account services
```

Reserve `ik admin ...` for true Informaniak Manager / company-admin operations only, such as users, permissions, aliases, domains, and all-company mailbox administration. A normal employee should be able to use `ik setup`, `ik bootstrap`, `ik account ...`, and service commands without touching `ik admin ...`.

## Stored profile example

```yaml
name: cylro
informaniak_user: gui@example.com
account_id: "123456"
account_name: "Cylro SARL-S"
ksuite_id: "98765"
mail_hosting_id: "55555"
default_mailbox: "contact@cylro.com"
default_drive_id: "77777"
default_drive_name: "Cylro Documents"
kchat_team_id: "abc123"
created_at: "2026-06-21T00:00:00Z"
updated_at: "2026-06-21T00:00:00Z"
```

## Storage paths

Prefer a normal user config location. On Windows:

```text
C:/Users/gui/AppData/Roaming/infomaniak-cli/
  config.yaml
  profiles/
    cylro.yaml
    personal.yaml
  tokens/
    cylro.token.json
    personal.token.json
```

Cross-platform fallback:

```text
~/.config/infomaniak-cli/
```

Secrets should not be committed to git.
