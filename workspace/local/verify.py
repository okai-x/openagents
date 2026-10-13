"""Restore a backup into a disposable database; verify content without printing it."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import uuid
import psycopg2
from psycopg2 import sql
import manage


def run():
    folder = max((manage.ROOT/'backups').glob('local-*'), key=lambda p: p.name)
    manifest = json.loads((folder/'manifest.json').read_text())
    for name, expected in manifest['sha256'].items():
        if Path(name).name != name or hashlib.sha256((folder/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Backup checksum verification failed')
    cfg = manage.settings()
    connection_args = dict(host='127.0.0.1', port=55432, user='openagents', password=cfg['db_password'])
    admin = psycopg2.connect(**connection_args, dbname='postgres')
    admin.autocommit = True
    target = 'oa_restore_check_' + uuid.uuid4().hex[:12]
    with admin.cursor() as cur:
        cur.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(target)))
    restored = None
    try:
        subprocess.run([str(manage.PG/'pg_restore'), '-h', '127.0.0.1', '-p', '55432', '-U', 'openagents',
                        '--exit-on-error', '--no-owner', '-d', target, str(folder/'database.dump')],
                       env={**os.environ, 'PGPASSWORD': cfg['db_password']}, check=True, capture_output=True)
        restored = psycopg2.connect(**connection_args, dbname=target)
        counts = {}
        with restored.cursor() as cur:
            for table in ('workspaces', 'channels', 'events', 'knowledge_entries', 'files', 'workflows'):
                cur.execute(sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table)))
                counts[table] = cur.fetchone()[0]
            with tarfile.open(folder/'files.tar.gz') as archive:
                cur.execute("SELECT storage_key, content_size FROM knowledge_entries WHERE storage_key IS NOT NULL AND status='active' UNION ALL SELECT storage_key, size FROM files WHERE status='active'")
                blobs = cur.fetchall()
                for key, size in blobs:
                    content = archive.extractfile('files/'+key).read()
                    if size is not None and len(content) != size:
                        raise RuntimeError('Restored blob size mismatch')
            source = json.loads((Path(cfg['snapshot'])/'snapshot.json').read_text())
            cur.execute('SELECT id,type,source,target,payload,metadata,timestamp FROM events WHERE network_id=%s', (cfg['workspace_id'],))
            rows = {r[0]: dict(zip(('id','type','source','target','payload','metadata','timestamp'),r)) for r in cur.fetchall()}
            for event in source['events']:
                row = rows.get(event['id'])
                if row is None or any(row[k] != event.get(k, {} if k == 'metadata' else None) for k in row):
                    raise RuntimeError('Source event content mismatch: ' + event['id'])
        subprocess.run(['git', '-C', str(manage.ASSETS), 'bundle', 'verify', str(folder/'assets.bundle')],
                       check=True, capture_output=True)
        report = {'backup': str(folder), 'restored_counts': counts, 'verified_blobs': len(blobs),
                  'verified_source_event_contents': len(source['events']), 'git_bundle_verified': True,
                  'verified_at': manage.datetime.now(manage.timezone.utc).isoformat()}
        manage.write_json(manage.PRIVATE/'backup-verification.json', report)
        print(json.dumps(report, ensure_ascii=False))
    finally:
        if restored:
            restored.close()
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(target)))
        admin.close()
