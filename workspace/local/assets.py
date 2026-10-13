"""Git-friendly knowledge/workflow snapshots with conflict-checked publishing.

Local files are never overwritten when they differ from the last synchronized
version. Deletions are not propagated automatically in either direction.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import fcntl
import httpx

import manage


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def reconcile(base, local, remote):
    """Choose an action without ever silently discarding divergent changes."""
    if local == remote:
        return "same"
    if base is None:
        if local is None:
            return "pull"
        if remote is None:
            return "push"
        return "conflict"
    if local != base and remote != base:
        return "conflict"
    return "push" if local != base else "pull"


def git(*args):
    return subprocess.run(["git", "-C", str(manage.ASSETS), *args], check=True, capture_output=True, text=True)


def initialize():
    root = manage.ASSETS
    root.mkdir(parents=True, exist_ok=True)
    for folder in ("knowledge", "decisions", "agents", "skills", "workflows", "artifacts", "evals"):
        (root / folder).mkdir(exist_ok=True)
        (root / folder / ".gitkeep").touch(exist_ok=True)
    if not (root / ".git").exists():
        git("init", "-b", "main")
        git("config", "user.name", "OpenAgents Local")
        git("config", "user.email", "openagents@localhost")
    texts = {
        ".gitignore": ".DS_Store\n.env\n.env.*\n!.env.example\n*.log\nnode_modules/\n.venv/\n.codex/\n.claude/\n.openagents/\ncredentials*\nauth.json\n",
        "README.md": "# 本地工作区资产\n\n工作区的数据服务运行在 http://127.0.0.1:18765。\n\n"
        "- knowledge/: 与工作区知识库同步的 Markdown。\n- workflows/: 可发布到工作区的流程定义。\n"
        "- decisions/: 经确认的决策及理由。\n- agents/、skills/: 可复用角色与技能。\n"
        "- artifacts/: 交付物。\n- evals/: 检验改进效果的案例。\n\n"
        "在本目录运行 `./workspace.sh export` 拉取知识/流程；运行 `./workspace.sh publish` 发布本地修改。"
        "双方同时改动会报告冲突，不自动覆盖。删除暂不双向传播。\n"
        "运行 `./workspace.sh backup` 创建数据库、文件和配置备份。\n\n"
        "后台每 6 小时导出服务端的知识和流程变化并提交 Git；每 24 小时创建完整备份。"
        "导出是周期快照，期间的每次编辑不会分别形成提交。\n"
        "手工修改、技能和交付物请在验证后自行提交 Git。此仓库尚未配置远程。\n",
        "AGENTS.md": "# 工作区资产维护\n\n"
        "本目录是长期资产仓库。开始任务先读 README.md、相关 knowledge/ 和 decisions/。\n"
        "把可复用经验整理成知识，把用户确认的选择及理由写入 decisions/；修改已有内容时消除过时结论。\n"
        "完成任务后验证结果并提交相关文件到 Git，提交说明写清目的和变化。\n"
        "需要在工作区界面共享知识时，运行 ./workspace.sh publish。遇到同步冲突先读取两边内容进行合并。\n"
        "凭证、运行时会话、环境变量文件不进入 Git；不要提交整个 .codex 或 .openagents 目录。\n",
        "decisions/0001-local-workspace.md": "# 工作区自托管\n\n"
        "- 工作区数据库、知识正文、文件与备份由本机保存。\n"
        "- 允许任务所需内容发送给 OpenAI；Codex 通过 ChatGPT 官方订阅登录。\n"
        "- 资产使用 Git 持续整理和验证；完整运行状态另做数据库与文件备份。\n",
    }
    for name, content in texts.items():
        path = root / name
        if not path.exists():
            path.write_text(content)
    wrapper = root / "workspace.sh"
    if not wrapper.exists():
        import shlex
        wrapper.write_text("#!/bin/sh\nset -eu\nexec " + shlex.quote(str(manage.PYTHON)) + " " +
                           shlex.quote(str(Path(manage.__file__).resolve())) + ' "${1:-export}"\n')
        wrapper.chmod(0o755)
    git("add", "README.md", "AGENTS.md", ".gitignore", "workspace.sh", "decisions", "knowledge/.gitkeep",
        "agents/.gitkeep", "skills/.gitkeep", "workflows/.gitkeep", "artifacts/.gitkeep", "evals/.gitkeep")
    if git("diff", "--cached", "--name-only").stdout:
        git("commit", "-m", "Initialize persistent local workspace assets")


def sync(mode="export"):
    root = manage.ASSETS
    root.mkdir(parents=True, exist_ok=True)
    lock = open(manage.PRIVATE / "assets.lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX)
    state_file = manage.PRIVATE / "assets-state.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    cfg = manage.settings()
    token, wid = cfg["workspace_token"], cfg["workspace_id"]
    written = []
    index_file = root / "knowledge/index.json"
    index = json.loads(index_file.read_text()) if index_file.exists() else {}
    with httpx.Client(base_url=manage.ENDPOINT, headers={"X-Workspace-Token": token}, timeout=30, trust_env=False) as client:
        entries = []
        offset = 0
        while True:
            page = manage.request(client, "/v1/knowledge", network=wid, limit=500, offset=offset)
            entries.extend(page["entries"])
            offset += len(page["entries"])
            if offset >= page["total"] or not page["entries"]:
                break
        remote = {}
        for entry in entries:
            content = manage.request(client, f"/v1/knowledge/{entry['id']}", network=wid)["content"]
            path = next((p for p, s in state.items() if s.get("id") == entry["id"] and p.startswith("knowledge/")), f"knowledge/{entry['id']}.md")
            remote[path] = {"id": entry["id"], "kind": "knowledge", "value": {
                "title": entry["title"], "description": entry.get("description") or "", "content": content}}
        workflows = manage.request(client, "/v1/workflows", network=wid)["workflows"]
        for workflow in workflows:
            path = next((p for p, s in state.items() if s.get("id") == workflow["id"] and p.startswith("workflows/")), f"workflows/{workflow['id']}.json")
            remote[path] = {"id": workflow["id"], "kind": "workflows", "value": {
                k: workflow.get(k) for k in ("name", "description", "steps", "max_iterations")}}
        paths = set(remote)
        if mode == "publish":
            paths.update(str(p.relative_to(root)) for p in (root / "knowledge").glob("*.md"))
            paths.update(str(p.relative_to(root)) for p in (root / "workflows").glob("*.json"))
        actions = []
        for name in sorted(paths):
            path = root / name
            # Paths from state are never allowed to escape the asset directory.
            if not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError("Invalid asset path")
            kind = "knowledge" if name.startswith("knowledge/") else "workflows"
            value = None
            if path.exists():
                if kind == "knowledge":
                    content = path.read_text()
                    meta = index.get(name, {})
                    first = content.splitlines()[0] if content.splitlines() else path.stem
                    value = {"title": meta.get("title") or first.lstrip("# "),
                             "description": meta.get("description") or "", "content": content}
                else:
                    value = json.loads(path.read_text())
            current = remote.get(name)
            old = state.get(name, {}).get("hash")
            choice = reconcile(old, digest(value) if value is not None else None,
                               digest(current["value"]) if current else None)
            if choice == "conflict":
                raise RuntimeError(f"Asset conflict: {name}. Neither side was overwritten; merge before publishing.")
            if old and (current is None or value is None):
                # No deletion propagation, and no accidental recreation of deleted remote entries.
                continue
            actions.append((name, kind, value, current, choice))
        for name, kind, value, current, choice in actions:
            path = root / name
            if mode == "publish" and choice == "push":
                payload = {**value, "network": wid}
                if kind == "knowledge":
                    payload["source"] = "human:local-assets"
                if current:
                    method = "PUT" if kind == "knowledge" else "PATCH"
                    response = client.request(method, f"/v1/{kind}/{current['id']}", json=payload,
                                              headers={"If-Match": digest(current["value"])})
                else:
                    response = client.post(f"/v1/{kind}", json=payload)
                response.raise_for_status()
                result = response.json()
                if result.get("code", 0) not in (0, 200):
                    raise RuntimeError(f"Publish failed for {name}: {result.get('message')}")
                # Read back the canonical representation after server normalization.
                item = manage.request(client, f"/v1/{kind}/{result['data']['id']}", network=wid)
                if kind == "knowledge":
                    canonical = {"title": item["title"], "description": item.get("description") or "", "content": item["content"]}
                else:
                    canonical = {k: item.get(k) for k in ("name", "description", "steps", "max_iterations")}
                current = {"id": item["id"], "value": canonical}
                if canonical != value:
                    if kind == "knowledge":
                        path.write_text(canonical["content"])
                    else:
                        manage.write_json(path, canonical)
                written.append(name)
                choice = "same"
            if choice == "pull":
                value = current["value"]
                path.parent.mkdir(exist_ok=True)
                if kind == "knowledge":
                    path.write_text(value["content"])
                else:
                    manage.write_json(path, value)
                written.append(name)
                choice = "same"
            if choice == "same" and current:
                state[name] = {"id": current["id"], "hash": digest(current["value"])}
                if kind == "knowledge":
                    index[name] = {"id": current["id"], "title": current["value"]["title"],
                                   "description": current["value"]["description"]}
    if index_file.exists() or index:
        old_index = index_file.read_text() if index_file.exists() else None
        manage.write_json(index_file, index)
        if old_index != index_file.read_text():
            written.append("knowledge/index.json")
    manage.write_json(state_file, state)
    if written:
        # Never sweep up unrelated authored files or a pre-existing staging area.
        git("add", "--", *written)
        if git("diff", "--cached", "--name-only", "--", *written).stdout:
            git("commit", "-m", "Snapshot workspace knowledge and workflows", "--", *written)
    print(f"Assets {mode}: {len(actions)} entries checked, {len(written)} files updated.")
