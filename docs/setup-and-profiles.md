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
> work

Open Informaniak login? [Y/n]

Authenticated as: user@example.com

Found accounts:
1. Personal account
2. Example Co

Use which account for profile "work"?
> 2

Found mailboxes:
1. contact@example.com
2. admin@example.com
3. user@example.com

Default mailbox?
> 1

Found kDrives:
1. Example Documents
2. Shared Admin

Default kDrive?
> 1

Make "work" the default profile? [Y/n]
```

Final output:

```text
✓ Profile created: work
✓ Authenticated as: user@example.com
✓ Account selected: Example Co
✓ Default mailbox: contact@example.com
✓ Default kDrive: Example Documents
✓ kChat workspace: Example Co
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
ik profile use work
ik whoami

ik --profile personal mail unread
ik --profile work drive search "invoice"
```

For Hermes and cron jobs, always prefer explicit profile:

```bash
ik --profile work mail unread
```

This avoids accidental personal/company mixups.

## Profile commands

Management commands should exist, but normal users should not need them before setup.

```bash
ik setup
ik setup --profile work

ik profile list
ik profile use work
ik profile show
ik profile rename old new
ik profile delete old --yes

ik auth login
ik auth logout
ik auth logout --all --yes
ik auth status
ik bootstrap
ik doctor
ik whoami
```

Profile selection precedence is:

1. explicit `--profile`
2. `IK_PROFILE`
3. saved current profile

Use `IK_PROFILE` when you want one terminal session to stay on a profile without changing the saved default:

```bash
IK_PROFILE=work ik whoami
IK_PROFILE=work ik mail unread --json
```

If `IK_PROFILE` names a profile that does not exist, commands fail clearly instead of falling back to the saved current profile.

`ik profile rename old new` renames local profile metadata and related local secret files. `ik profile delete old --yes` deletes only that local profile and its related local secrets. `ik auth logout` removes only the selected profile's main API token by default; `ik auth logout --all --yes` also removes local service-specific secrets for mail, contacts, calendar, and chat. None of these commands change remote Informaniak/kSuite services.

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
name: work
informaniak_user: user@example.com
account_id: "123456"
account_name: "Example Co"
ksuite_id: "98765"
mail_hosting_id: "55555"
default_mailbox: "contact@example.com"
default_drive_id: "77777"
default_drive_name: "Example Documents"
kchat_team_id: "abc123"
created_at: "2026-06-21T00:00:00Z"
updated_at: "2026-06-21T00:00:00Z"
```

## Storage paths

Prefer a normal user config location. On Windows:

```text
C:/Users/<user>/AppData/Roaming/infomaniak-cli/
  config.yaml
  profiles/
    work.yaml
    personal.yaml
  tokens/
    work.token.json
    personal.token.json
    work.mail
    personal.mail
```

Cross-platform fallback:

```text
~/.config/infomaniak-cli/
```

Secrets should not be committed to git.
