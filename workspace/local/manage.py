#!/usr/bin/env python3
"""Private, macOS-native OpenAgents deployment and data management.

Secrets and snapshots live outside this checkout. Never print credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import plistlib
import re
import time
from datetime import datetime, timezone

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "workspace/backend"
ROOT = Path(os.environ.get("OPENAGENTS_LOCAL_DATA", str(Path.home() / "OpenAgentsData")))
PRIVATE = ROOT / "private"
CONFIG = PRIVATE / "deployment.json"
PG = ROOT / "runtime/Postgres.app/Contents/Versions/16/bin"
PYTHON = ROOT / "runtime/venv/bin/python"
ENDPOINT = "http://127.0.0.1:18765"
ASSETS = Path.home() / "Workspace/01_Projects/openagents-assets"


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as stream:
        os.chmod(tmp, 0o600)
        json.dump(data, stream, ensure_ascii=False, indent=2, default=str)
        stream.write("\n")
    tmp.replace(path)


def settings():
    return json.loads(CONFIG.read_text())


def environment():
    cfg = settings()
    env = dict(os.environ)
    env.update({
        "DATABASE_URL": f"postgresql://openagents:{cfg['db_password']}@127.0.0.1:55432/openagents_local",
        "AUTH_MODE": "workspace_token", "IDENTITY_MODE": "standalone",
        "FILE_STORAGE_BACKEND": "local", "FILE_STORAGE_PATH": str(ROOT / "files"),
        "WORKSPACE_SESSION_SECRET": cfg["session_secret"],
        "CORS_ORIGINS": f"{ENDPOINT},openagents://workspace",
        "FRONTEND_BASE_URL": ENDPOINT, "WORKSPACE_ENDPOINT": ENDPOINT,
        "ANALYTICS_ENABLED": "0", "YUMI_ENABLED": "false",
        "ROUTER_LLM_ENABLED": "false", "FIREBASE_PROJECT_ID": "",
        "APPLE_CLIENT_IDS": "", "BROWSERFABRIC_API_KEY": "",
        "BROWSERFABRIC_PROVISION_SECRET": "", "REDIS_URL": "",
        "PYTHONPATH": str(BACKEND),
    })
    return env


def configure():
    PRIVATE.mkdir(parents=True, exist_ok=True)
    PRIVATE.chmod(0o700)
    if not CONFIG.exists():
        write_json(CONFIG, {"db_password": secrets.token_urlsafe(32),
                           "session_secret": secrets.token_urlsafe(48),
                           "workspace_token": secrets.token_urlsafe(32),
                           "endpoint": ENDPOINT, "assets": str(ASSETS)})
    password = PRIVATE / "postgres-password"
    password.write_text(settings()["db_password"] + "\n")
    password.chmod(0o600)
    print("Local configuration ready; credentials stored privately.")


def initdb():
    data = ROOT / "postgres"
    if not (data / "PG_VERSION").exists():
        subprocess.run([str(PG / "initdb"), "-D", str(data), "-U", "openagents",
                        "--encoding=UTF8", "--locale=C", "--auth=scram-sha-256",
                        f"--pwfile={PRIVATE / 'postgres-password'}"], check=True)
        with (data / "postgresql.conf").open("a") as stream:
            stream.write("\nlisten_addresses = '127.0.0.1'\nport = 55432\n")
            stream.write(f"unix_socket_directories = '{ROOT}'\nmax_connections = 120\n")
    print("PostgreSQL initialized.")


def install_service(name, arguments, interval=None):
    label = f"org.openagents.local.{name}"
    path = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    definition = {"Label": label, "ProgramArguments": arguments,
                  "WorkingDirectory": str(REPO),
                  "StandardOutPath": str(ROOT / "logs" / f"{name}.log"),
                  "StandardErrorPath": str(ROOT / "logs" / f"{name}.log"),
                  "RunAtLoad": True,
                  "EnvironmentVariables": {"PATH": f"{Path.home()}/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"}}
    if interval:
        definition["StartInterval"] = interval
    else:
        definition["KeepAlive"] = True
        definition["ThrottleInterval"] = 10
    with path.open("wb") as stream:
        plistlib.dump(definition, stream)
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{label}"], capture_output=True)
    # bootout can return while launchd is still removing the old registration.
    for attempt in range(10):
        result = subprocess.run(["launchctl", "bootstrap", domain, str(path)], capture_output=True, text=True)
        if result.returncode == 0:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError(f"launchd could not load {label}: {result.stderr.strip()}")
    print(f"Service installed: {label}")


def postgres_service():
    install_service("postgres", [str(PG / "postgres"), "-D", str(ROOT / "postgres")])


def migrate():
    import psycopg2
    from psycopg2 import sql
    connection = psycopg2.connect(host="127.0.0.1", port=55432, user="openagents",
                                  password=settings()["db_password"], dbname="postgres")
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", ("openagents_local",))
        if not cursor.fetchone():
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier("openagents_local")))
    connection.close()
    subprocess.run([str(PYTHON.parent / "alembic"), "upgrade", "head"], cwd=BACKEND, env=environment(), check=True)


def serve():
    os.environ.update(environment())
    sys.path.insert(0, str(BACKEND))
    import uvicorn
    from server import app
    uvicorn.run(app, host="127.0.0.1", port=18765, access_log=False)


def backend_service():
    install_service("backend", [str(PYTHON), str(Path(__file__).resolve()), "serve"])


def cutover():
    from cutover import run
    run()


def assets_init():
    from assets import initialize
    initialize()
    print(f"Git asset repository initialized: {ASSETS}")


def export():
    from assets import sync
    sync("export")


def publish():
    from assets import sync
    sync("publish")


def backup():
    import tarfile
    import fcntl
    lock = open(PRIVATE / "backup.lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX)
    target = ROOT / "backups" / ("local-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    target.mkdir(mode=0o700)
    env = {**os.environ, "PGPASSWORD": settings()["db_password"]}
    with (PRIVATE / 'storage.lock').open('a') as storage_lock:
        fcntl.flock(storage_lock, fcntl.LOCK_EX)
        subprocess.run([str(PG / "pg_dump"), "-h", "127.0.0.1", "-p", "55432", "-U", "openagents",
                        "-Fc", "-f", str(target / "database.dump"), "openagents_local"], env=env, check=True)
        with tarfile.open(target / "files.tar.gz", "w:gz") as archive:
            archive.add(ROOT / "files", arcname="files")
    with tarfile.open(target / "private-config.tar.gz", "w:gz") as archive:
        for path in PRIVATE.rglob('*'):
            if path.is_file() and path.suffix in ('.json', '.yaml'):
                archive.add(path, arcname='private/' + str(path.relative_to(PRIVATE)))
        for name in ('daemon.yaml', 'node.json', 'sessions', 'launcher-sessions', 'cursors'):
            path = Path.home()/'.openagents'/name
            if path.exists():
                archive.add(path, arcname='openagents/' + name)
        for name in ('settings.json', 'account.json'):
            path = Path.home()/'Library/Application Support/OpenAgents'/name
            if path.exists():
                archive.add(path, arcname='desktop/' + name)
    if (ASSETS / ".git").exists():
        subprocess.run(["git", "-C", str(ASSETS), "bundle", "create", str(target / "assets.bundle"), "--all"], check=True)
        with tarfile.open(target / 'assets-working-tree.tar.gz', 'w:gz') as archive:
            archive.add(ASSETS, arcname='assets', filter=lambda item: None if '/.git/' in item.name or item.name.endswith('/.git') else item)
    # Preserve the local adaptation without duplicating the large upstream history.
    base = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', '0a0ab10ba']).decode().strip()
    head = subprocess.check_output(['git', '-C', str(REPO), 'rev-parse', 'HEAD']).decode().strip()
    (target / 'source-changes.patch').write_bytes(subprocess.check_output(
        ['git', '-C', str(REPO), 'diff', '--binary', base, 'HEAD']))
    write_json(target / 'source.json', {'repository': 'https://github.com/openagents-org/openagents.git',
                                      'base_commit': base, 'head_commit': head})
    checksums = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in target.iterdir() if p.is_file()}
    write_json(target / "manifest.json", {"created_at": datetime.now(timezone.utc).isoformat(), "sha256": checksums})
    print(f"Backup created: {target}")


def verify_backup():
    from verify import run
    run()


def automation():
    command = [str(PYTHON), str(Path(__file__).resolve())]
    install_service("assets", command + ["export"], interval=300)
    install_service("backup", command + ["backup"], interval=21600)


def db():
    os.environ.update(environment())
    sys.path.insert(0, str(BACKEND))
    from app.database import SessionLocal
    return SessionLocal()


def request(client, route, **params):
    result = client.get(route, params=params)
    result.raise_for_status()
    payload = result.json()
    if payload.get("code", 0) not in (0, 200):
        raise RuntimeError(f"API rejected {route}: code={payload.get('code')}")
    return payload.get("data", payload)


def snapshot():
    """Read-only export of the currently paired hosted workspace."""
    import httpx
    node = json.loads((Path.home() / ".openagents/node.json").read_text())
    pairings = node.get("pairings") or [node]
    source = next(p for p in pairings if p.get("endpoint", "").rstrip("/") == "https://workspace-endpoint.openagents.org")
    wid = source["workspace_id"]
    folder = ROOT / "backups" / ("cloud-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    folder.mkdir(parents=True, mode=0o700)
    bundle = {"source": source["endpoint"], "exported_at": datetime.now(timezone.utc).isoformat(), "workspace_id": wid}
    with httpx.Client(base_url=source["endpoint"], headers={"X-Workspace-Token": source["token"]}, timeout=60, follow_redirects=False) as client:
        bundle["workspace"] = request(client, f"/v1/workspaces/{wid}")
        # Never archive a cloud access token returned by the workspace endpoint.
        bundle["workspace"].pop("token", None)
        bundle["discovery"] = request(client, "/v1/discover", network=wid)
        bundle["collaborators"] = request(client, f"/v1/workspaces/{wid}/collaborators")
        for name in ("tasks", "workflows", "routines"):
            bundle[name] = request(client, f"/v1/{name}", network=wid)
        events, cursor = [], None
        while True:
            params = {"network": wid, "limit": 500, "sort": "asc"}
            if cursor:
                params["after"] = cursor
            page = request(client, "/v1/events", **params)
            rows = page.get("events", [])
            if not rows:
                break
            if rows[-1]["id"] == cursor:
                raise RuntimeError("Event pagination did not advance")
            events.extend(rows)
            cursor = rows[-1]["id"]
            if not page.get("has_more"):
                break
        bundle["events"] = events
        channels = {c.get("name") or c.get("address", "").removeprefix("channel/") for c in bundle["discovery"].get("channels", [])}
        channels.discard("")
        channels.update(e["target"][8:] for e in events if e.get("target", "").startswith("channel/"))
        bundle["channels"] = []
        from urllib.parse import quote
        for name in sorted(channels):
            response = client.get(f"/v1/workspaces/{wid}/channels/{quote(name, safe='')}")
            if response.status_code == 404:
                continue
            response.raise_for_status()
            bundle["channels"].append(response.json()["data"])
        for kind, key in (("knowledge", "entries"), ("files", "files")):
            rows = []
            for status in ("active", "deleted"):
                offset = 0
                while True:
                    page = request(client, f"/v1/{kind}", network=wid, limit=200, offset=offset, status=status)
                    batch = page.get(key, [])
                    rows.extend(batch)
                    offset += len(batch)
                    if not batch or offset >= page.get("total", offset):
                        break
            for row in rows:
                if kind == "knowledge":
                    if row.get("status") == "deleted":
                        row["unavailable_content"] = True
                        continue
                    detail = request(client, f"/v1/knowledge/{row['id']}", network=wid)
                    row["content"] = detail.get("content", "")
                else:
                    response = client.get(f"/v1/files/{row['id']}", params={"network": wid})
                    if response.status_code == 404 and row.get("status") == "deleted":
                        row["unavailable_content"] = True
                        continue
                    response.raise_for_status()
                    blob = response.content
                    if len(blob) != row["size"]:
                        raise RuntimeError(f"File size mismatch for {row['id']}")
                    (folder / "blobs").mkdir(exist_ok=True)
                    (folder / "blobs" / row["id"]).write_bytes(blob)
                    row["sha256"] = hashlib.sha256(blob).hexdigest()
            bundle[kind] = rows
    write_json(folder / "snapshot.json", bundle)
    cfg = settings()
    cfg.update({"snapshot": str(folder), "workspace_id": wid, "slug": bundle["workspace"]["slug"]})
    write_json(CONFIG, cfg)
    print(json.dumps({"snapshot": str(folder), "workspace": bundle["workspace"]["name"],
                      **{k: len(bundle[k]) for k in ("events", "channels", "knowledge", "files")},
                      **{k: len(bundle[k].get(k, [])) for k in ("tasks", "workflows", "routines")}}, ensure_ascii=False))


def import_snapshot():
    cfg = settings()
    folder = Path(cfg["snapshot"])
    bundle = json.loads((folder / "snapshot.json").read_text())
    session = db()
    from app import models as m
    from app.storage import get_file_store
    from sqlalchemy import DateTime, select, func
    ws = bundle["workspace"]
    wid = ws["workspaceId"]
    if session.get(m.Workspace, wid):
        raise RuntimeError("Workspace already exists locally; import will not overwrite it")

    def add(model, values):
        values = {k: v for k, v in values.items() if k in model.__table__.columns and v is not None}
        for column in model.__table__.columns:
            if isinstance(column.type, DateTime) and isinstance(values.get(column.key), str):
                values[column.key] = datetime.fromisoformat(values[column.key].replace("Z", "+00:00"))
        row = model(**values)
        session.add(row)
        return row

    add(m.Workspace, {"id": wid, "slug": ws["slug"], "name": ws["name"] + " · 本地",
        "creator_email": ws.get("creatorEmail"), "password_hash": cfg["workspace_token"],
        "require_login": True, "settings": {k: v for k, v in ws.get("settings", {}).items()
            if not re.search(r"token|secret|password|api.?key", k, re.I)},
        "status": "active", "created_at": ws.get("createdAt"), "last_activity_at": ws.get("lastActivityAt")})
    session.flush()
    for agent in ws.get("agents", []):
        add(m.WorkspaceMember, {"workspace_id": wid, "agent_name": agent["agentName"],
            "display_name": agent.get("displayName"), "agent_type": agent.get("agentType"),
            "description": agent.get("description"), "model": agent.get("model"),
            "working_dir": str(ASSETS) if agent.get("agentType") == "codex" else agent.get("workingDir"),
            "role": agent.get("role", "member"), "status": "offline", "joined_at": agent.get("joinedAt")})
    discovered = {c["address"].removeprefix("channel/"): c for c in bundle["discovery"].get("channels", [])}
    for channel in bundle["channels"]:
        add(m.Channel, {"id": channel["channelId"], "workspace_id": wid, "name": channel["name"],
            "title": channel.get("title"), "title_manually_set": channel.get("titleManuallySet", False),
            "created_by": channel.get("createdBy"), "master_agent": channel.get("masterAgent"),
            "resume_from": channel.get("resumeFrom"), "orchestration_mode": channel.get("orchestrationMode", "dynamic"),
            "orchestration_instruction": channel.get("orchestrationInstruction"), "workflow_id": channel.get("workflowId"),
            "status": channel.get("status", "active"), "starred": channel.get("starred", False),
            "created_at": channel.get("createdAt"), "last_event_at": discovered.get(channel["name"], {}).get("last_event_at")})
    session.flush()
    for channel in bundle["channels"]:
        for name in channel.get("participants", []):
            add(m.ChannelMember, {"channel_id": channel["channelId"], "agent_name": name})
    for event in bundle["events"]:
        values = {k: v for k, v in event.items() if k != "metadata"}
        row = add(m.EventRecord, {**values, "network_id": wid})
        row.metadata_ = event.get("metadata", {})
    for collaborator in bundle["collaborators"].get("collaborators", []):
        add(m.WorkspaceCollaborator, {"workspace_id": wid, "email": collaborator["email"],
            "role": collaborator.get("role", "editor"), "added_by": collaborator.get("addedBy"),
            "added_at": collaborator.get("addedAt"), "display_name": collaborator.get("displayName")})
    store = get_file_store()
    for row in bundle["knowledge"]:
        if row.get("unavailable_content"):
            raise RuntimeError("A deleted knowledge entry could not be exported; restore it at source before migration")
        key = store.save(wid, row["id"], row["slug"] + ".md", row["content"].encode())
        add(m.KnowledgeEntry, {**row, "workspace_id": wid, "storage_key": key})
    for row in bundle["files"]:
        if row.get("unavailable_content"):
            raise RuntimeError("A trashed file is unavailable; restore it at source before migration")
        blob = (folder / "blobs" / row["id"]).read_bytes()
        if hashlib.sha256(blob).hexdigest() != row["sha256"]:
            raise RuntimeError("Snapshot file checksum mismatch")
        key = store.save(wid, row["id"], Path(row["filename"]).name, blob)
        add(m.FileRecord, {**row, "workspace_id": wid, "storage_key": key})
    # Keep the initial migration explicit: no silently dropped scheduler or workflow fields.
    if any(bundle[k].get(k) for k in ("tasks", "workflows", "routines")):
        raise RuntimeError("Nonempty tasks/workflows/routines need schema mapping before import")
    session.flush()
    counts = {"events": session.scalar(select(func.count()).select_from(m.EventRecord).where(m.EventRecord.network_id == wid)),
              "channels": session.scalar(select(func.count()).select_from(m.Channel).where(m.Channel.workspace_id == wid))}
    if counts != {"events": len(bundle["events"]), "channels": len(bundle["channels"])}:
        raise RuntimeError("Migration count mismatch")
    session.commit()
    session.close()
    write_json(PRIVATE / "migration-report.json", {"source_snapshot": str(folder), "verified_counts": counts,
        "files_sha256_verified": len(bundle["files"]), "imported_at": datetime.now(timezone.utc).isoformat()})
    print(json.dumps({"imported_and_verified": counts}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["configure", "initdb", "snapshot", "postgres_service", "migrate", "serve", "backend_service", "import_snapshot", "cutover", "assets_init", "export", "publish", "backup", "verify_backup", "automation"])
    args = parser.parse_args()
    globals()[args.command]()


if __name__ == "__main__":
    main()
