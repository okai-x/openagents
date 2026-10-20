# -*- coding: utf-8 -*-
"""The launcher's per-agent inventory report (what an agent can actually use)."""

from sqlalchemy import select


def _join_agent(client, workspace, name, agent_type="codex"):
    resp = client.post("/v1/join", json={
        "agent_name": name, "token": workspace["token"], "network": workspace["id"], "agent_type": agent_type,
    })
    assert resp.status_code == 200, resp.text


def _member_skills(db, workspace, agent_name):
    from app.models import WorkspaceMember
    db.expire_all()
    member = db.execute(select(WorkspaceMember).where(
        WorkspaceMember.workspace_id == workspace["id"], WorkspaceMember.agent_name == agent_name,
    )).scalar_one()
    return dict(member.enabled_skills or {})


def _report(client, workspace, agent, body, token=None):
    return client.post(
        f"/v1/workspaces/{workspace['id']}/members/{agent}/inventory",
        json=body, headers={"X-Workspace-Token": token or workspace["token"]},
    )


def test_inventory_is_stored_trimmed_and_without_unknown_fields(client, workspace, db):
    _join_agent(client, workspace, "sre")
    resp = _report(client, workspace, "sre", {
        "runtime": "codex",
        "modules": [{"name": "browser", "state": "off"}],
        "skills": [
            {"name": "runbook", "description": "x" * 500, "source": "hub", "state": "on", "env": {"TOKEN": "secret"}},
            {"name": "", "source": "home"},
        ],
        "mcp": [{"name": "cloudflare", "source": "home", "transport": "http", "state": "on", "headers": "secret"}],
        "flags": {"claudeaiConnectors": False},
    })
    assert resp.status_code == 200, resp.text

    inventory = _member_skills(db, workspace, "sre")["inventory"]
    assert inventory["runtime"] == "codex"
    assert inventory["modules"] == [{"name": "browser", "state": "off"}]
    assert [s["name"] for s in inventory["skills"]] == ["runbook"]
    assert len(inventory["skills"][0]["description"]) == 300
    assert inventory["mcp"] == [{"name": "cloudflare", "source": "home", "state": "on", "transport": "http"}]
    assert inventory["flags"] == {"claudeaiConnectors": False}
    assert inventory["reported_at"]
    assert "secret" not in str(inventory)


def test_inventory_needs_the_workspace_and_an_existing_member(client, workspace):
    _join_agent(client, workspace, "sre")
    assert _report(client, workspace, "sre", {}, token="wrong").json()["code"] == 401
    assert _report(client, workspace, "nobody", {}).json()["code"] == 404


def test_changing_tool_toggles_keeps_install_state_and_inventory(client, workspace, db):
    _join_agent(client, workspace, "sre")
    _report(client, workspace, "sre", {"runtime": "codex", "skills": [{"name": "runbook"}]})
    client.post(
        f"/v1/workspaces/{workspace['id']}/members/sre/skills/status",
        json={"skill_id": "claude-api", "state": "installed"},
        headers={"X-Workspace-Token": workspace["token"]},
    )

    resp = client.patch(
        f"/v1/workspaces/{workspace['id']}/members/sre",
        json={"enabled_skills": {"browser": False}},
        headers={"X-Workspace-Token": workspace["token"]},
    )
    assert resp.status_code == 200, resp.text

    skills = _member_skills(db, workspace, "sre")
    assert skills["browser"] is False
    assert skills["inventory"]["skills"] == [{"name": "runbook"}]
    assert skills["skill_status"]["claude-api"]["state"] == "installed"
    assert "claude-api" in skills["installed"]
