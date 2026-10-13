"""One-time recoverable switch from hosted workspace to local deployment."""
from pathlib import Path
import json
import socket
import time
import yaml
import httpx
import manage


def run():
    cfg = manage.settings()
    bundle = json.loads((Path(cfg['snapshot']) / 'snapshot.json').read_text())
    if bundle['knowledge'] or bundle['files'] or any(bundle[k].get(k) for k in ('tasks', 'workflows', 'routines')):
        raise RuntimeError('New source assets need migration before switching')
    session = manage.db()
    from app.models import EventRecord, Channel
    from sqlalchemy import select, DateTime
    existing = set(session.scalars(select(EventRecord.id).where(EventRecord.network_id == cfg['workspace_id'])))
    channels = set(session.scalars(select(Channel.id).where(Channel.workspace_id == cfg['workspace_id'])))
    if channels != {c['channelId'] for c in bundle['channels']}:
        raise RuntimeError('Source channels changed; reconcile before switching')
    added = 0
    for event in bundle['events']:
        if event['id'] in existing:
            continue
        values = {k: v for k, v in event.items() if k in EventRecord.__table__.columns and k != 'metadata'}
        for col in EventRecord.__table__.columns:
            if isinstance(col.type, DateTime) and isinstance(values.get(col.key), str):
                values[col.key] = manage.datetime.fromisoformat(values[col.key].replace('Z', '+00:00'))
        row = EventRecord(**{**values, 'network_id': cfg['workspace_id']})
        row.metadata_ = event.get('metadata', {})
        session.add(row)
        added += 1
    session.commit()
    session.close()
    node_file = Path.home() / '.openagents/node.json'
    node = json.loads(node_file.read_text())
    with httpx.Client(base_url=manage.ENDPOINT, headers={'X-Workspace-Token': cfg['workspace_token']}, trust_env=False) as client:
        response = client.post(f"/v1/workspaces/{cfg['workspace_id']}/pairing-codes")
        response.raise_for_status()
        code = response.json()['data']['code']
        response = client.post('/v1/nodes/redeem', json={'code': code, 'node_key': node['node_key'],
            'hostname': socket.gethostname(), 'device_type': 'laptop', 'os': 'darwin', 'launcher_version': '1.0.18'})
        response.raise_for_status()
        pair = response.json()['data']
    pairing = {'node_id': pair['nodeId'], 'workspace_id': pair['workspaceId'], 'workspace_slug': pair['workspaceSlug'],
        'workspace_name': pair['workspaceName'], 'endpoint': manage.ENDPOINT, 'token': pair['token'],
        'paired_at': manage.datetime.now(manage.timezone.utc).isoformat()}
    others = [p for p in node.get('pairings', []) if p.get('workspace_id') != cfg['workspace_id']]
    manage.write_json(node_file, {'node_key': node['node_key'], **pairing, 'pairings': [pairing, *others]})
    daemon_path = Path.home() / '.openagents/daemon.yaml'
    daemon = yaml.safe_load(daemon_path.read_text())
    for network in daemon['networks']:
        if network['id'] == cfg['workspace_id']:
            network.update(endpoint=manage.ENDPOINT, token=pair['token'], name=pair['workspaceName'])
    for agent in daemon['agents']:
        if agent['name'] == 'codex-kai':
            agent['path'] = str(manage.ASSETS)
            agent['network'] = cfg['slug']
            if bundle['events']:
                manage.write_json(Path.home()/'.openagents/cursors'/f"{cfg['workspace_id']}__{agent['name']}.json",
                    {'cursor': bundle['events'][-1]['id'], 'savedAt': int(time.time()*1000),
                     'workspaceId': cfg['workspace_id'], 'agentName': agent['name']})
    daemon_path.write_text(yaml.safe_dump(daemon, allow_unicode=True, sort_keys=False))
    daemon_path.chmod(0o600)
    path = Path.home() / 'Library/Application Support/OpenAgents/settings.json'
    app = json.loads(path.read_text()) if path.exists() else {}
    app.update(workspaceEndpoint=manage.ENDPOINT, localWorkspace={'endpoint': manage.ENDPOINT, 'slug': cfg['slug'],
        'token': cfg['workspace_token']}, analyticsEnabled=False, autoUpdate=False, agentAutoStart=True)
    manage.write_json(path, app)
    report = json.loads((manage.PRIVATE/'migration-report.json').read_text())
    report.update(final_source_snapshot=cfg['snapshot'], source_events=len(bundle['events']), catchup_events=added,
                  cutover_at=manage.datetime.now(manage.timezone.utc).isoformat())
    manage.write_json(manage.PRIVATE/'migration-report.json', report)
    print(json.dumps({'local_endpoint': manage.ENDPOINT, 'migrated_events': len(bundle['events']),
        'catchup_events': added, 'agent_path': str(manage.ASSETS)}, ensure_ascii=False))
