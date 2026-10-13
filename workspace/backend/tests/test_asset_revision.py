from app.asset_revision import asset_revision


def test_stale_knowledge_publish_does_not_overwrite_newer_content(client, workspace):
    headers = {"X-Workspace-Token": workspace["token"]}
    original = {"title": "Versioned", "description": "", "content": "initial"}
    response = client.post("/v1/knowledge", headers=headers, json={"network": workspace["id"], **original})
    entry_id = response.json()["data"]["id"]
    url = f"/v1/knowledge/{entry_id}"
    changed = client.put(url, headers={**headers, "If-Match": asset_revision(original)},
                         json={"network": workspace["id"], "content": "newer"})
    assert changed.status_code == 200
    stale = client.put(url, headers={**headers, "If-Match": asset_revision(original)},
                       json={"network": workspace["id"], "content": "stale edit"})
    assert stale.status_code == 412
    current = client.get(url, headers=headers, params={"network": workspace["id"]})
    assert current.json()["data"]["content"] == "newer"


def test_stale_workflow_publish_does_not_overwrite_newer_steps(client, workspace):
    headers = {"X-Workspace-Token": workspace["token"]}
    created = client.post('/v1/workflows', headers=headers, json={
        'network': workspace['id'], 'name': 'Versioned workflow',
        'steps': [{'instruction': 'Review', 'assignee': {'kind': 'human', 'human': 'alice'}}],
    }).json()['data']
    revision = asset_revision({k: created.get(k) for k in ('name','description','steps','max_iterations')})
    url = f"/v1/workflows/{created['id']}"
    updated = client.patch(url, headers={**headers, 'If-Match': revision},
                           json={'network': workspace['id'], 'name': 'New version'})
    assert updated.status_code == 200
    stale = client.patch(url, headers={**headers, 'If-Match': revision},
                         json={'network': workspace['id'], 'name': 'Stale version'})
    assert stale.status_code == 412
    assert client.get(url, headers=headers, params={'network':workspace['id']}).json()['data']['name'] == 'New version'
