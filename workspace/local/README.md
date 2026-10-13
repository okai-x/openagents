# Native macOS self-hosted workspace

This deployment keeps the workspace API, PostgreSQL database, file blobs, and asset history on this Mac. Codex CLI uses the existing ChatGPT login; task context may be sent to OpenAI. The application listens on loopback only.

## Installed layout

| Component | Location |
| --- | --- |
| Desktop app | `~/Applications/OpenAgents.app` |
| API and web bundle | `http://127.0.0.1:18765` |
| PostgreSQL 16 | `127.0.0.1:55432`, database `openagents_local` |
| Runtime and database | `~/OpenAgentsData/runtime`, `~/OpenAgentsData/postgres` |
| File and knowledge bodies | `~/OpenAgentsData/files` |
| Private credentials and sync state | `~/OpenAgentsData/private` |
| Backups and logs | `~/OpenAgentsData/backups`, `~/OpenAgentsData/logs` |
| Git assets and Codex working directory | `~/Workspace/01_Projects/openagents-assets` |
| Agent connection and session records | `~/.openagents` |
| Desktop preferences | `~/Library/Application Support/OpenAgents/settings.json` |

Open the desktop app to enter **My Workspace · 本地**. Its local entry uses a workspace token and does not forward the hosted account session to the local API. Keep credential-bearing settings private. The current web bundle also exists at `/ui/`; use the native app for the configured, authenticated entry.

## Daily use

From the asset directory:

```sh
./workspace.sh export         # server knowledge/workflows → Markdown/JSON + Git
./workspace.sh publish        # local edits → workspace API; checks revisions
./workspace.sh backup         # database + blobs + configs + Git + working tree
./workspace.sh verify_backup  # restore latest backup to a temporary database
```

The asset repo contains `AGENTS.md`, a usage guide, workspace and agent metadata, and a manually triggered asset-refinement workflow. No remote Git repository is configured.

Exports run every 6 hours. Backups run every 24 hours. Each scheduled job also runs once when its LaunchAgent loads, including login or an explicit reload. LaunchAgents operate after macOS login; jobs do not execute while the Mac sleeps. Backups currently have no automatic deletion policy. They are private archives on the same disk, not offsite disaster recovery.

## Synchronization behavior

Knowledge is Markdown with title/description stored in `knowledge/index.json`; workflows are normalized JSON. Only synchronized paths are automatically committed. Other authored files should be reviewed and committed normally. Deletions are deliberately not propagated.

The synchronizer compares both sides to a private baseline and stops on divergent changes. Publishing also sends a conditional revision; a server edit arriving during publication returns HTTP 412. A publication spanning multiple assets is not a single transaction: rerun and reconcile after any partial failure. To resolve a conflict, preserve the local version, return it to the last synchronized content, export the server version, then merge the preserved changes and publish. Do not discard either side blindly. There is no graphical merge tool in this integration.

## Operations

Run from the source checkout with `~/OpenAgentsData/runtime/venv/bin/python workspace/local/manage.py COMMAND`:

- `backend_service`: reload the local API LaunchAgent.
- `postgres_service`: reload the PostgreSQL LaunchAgent.
- `automation`: install/reload export and backup schedules.
- `backup`, `verify_backup`: create and verify recoverable data.

Health: `curl -fsS http://127.0.0.1:18765/ready`.
Service labels: `org.openagents.local.postgres`, `.backend`, `.assets`, `.backup` in `~/Library/LaunchAgents`.

The backup gate drains mutating API requests before capturing the database and blob files; reads continue. Writes wait briefly during capture. Do not directly modify database/blob files during backups. The Git bundle preserves commits, while `assets-working-tree.tar.gz` also captures uncommitted asset files. Agent session/config archives are sampled separately from the database; model-provider login state is not a portable account backup.

`verify_backup` checks archive SHA-256 hashes, restores PostgreSQL into a uniquely named disposable database, validates migrated event contents and referenced blob sizes, verifies the Git bundle, then removes only that temporary database. The result is stored privately in `backup-verification.json`.

## Restore and rollback

Before restoring, quit the desktop app and stop the backend plus scheduled export/backup LaunchAgents. Preserve current data as an additional backup. Verify the chosen manifest, restore `database.dump` into a **new** database using PostgreSQL 16 `pg_restore`, restore the matching `files.tar.gz`, and point the private deployment configuration to those restored paths/database. A normal disaster restore needs the matching configuration and credentials as well. The backup also contains `source-changes.patch` and `source.json`: clone the upstream repository at the recorded base commit, apply the patch with `git apply`, install `requirements-macos.lock` into a Python 3.12 environment, and rebuild the desktop app. Only committed source changes are captured. PostgreSQL and Node runtimes must be reinstalled from their official sources. The management script currently uses a fixed database name; change that setting explicitly if restoring into a different database. `verify_backup` is a safe restore drill, not an in-place rollback command.

To return to the pre-migration cloud configuration, preserve any new local data first. Quit the app and stop the agent daemon. Original `settings.json`, `account.json`, `daemon.yaml`, and `node.json` are in `~/OpenAgentsData/private/pre-local`; the original app is `~/OpenAgentsData/runtime/OpenAgents-before-local.app`. Restore those matching files together. The hosted workspace itself was not deleted or overwritten. The first cloud snapshot and final catch-up snapshot remain in `backups/cloud-*`.

## Deliberate limits

- Normal Codex conversations use subscription authentication. No OpenAI API key was created.
- Backend LLM routing, model-based workflow gates, Yumi, and BrowserFabric cloud browsing are not configured. Use explicit agent mentions/master-agent routing and workflows without model-based gates.
- Cloud account services, credits, and workspace sharing are not part of this local deployment. Do not publish local access tokens or expose these ports to the network.
- Automatic desktop downloads are disabled so an upstream release cannot overwrite the local entry changes. Update deliberately from this source branch and rebuild.
- This is a local adaptation of upstream commit `0a0ab10ba`, branch `codex/local-self-hosting`. Keep this checkout and runtime available; LaunchAgents reference them.

The one-time migration commands are intentionally conservative: a changed source schema or nonempty unsupported asset class stops import instead of silently omitting data. They are not a general cloud synchronization service.
