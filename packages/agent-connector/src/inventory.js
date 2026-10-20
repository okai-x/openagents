'use strict';

/**
 * What an agent can actually use, for the workspace's per-agent skills panel:
 * workspace tool modules, skills by where they come from, and MCP servers.
 *
 * Only names, short descriptions and locations are reported. Never file
 * contents, env values, args or headers: MCP configs often carry tokens.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const { isManagedHome } = require('./agent-home');
const { parseSkillFrontmatter } = require('./skill-installer');
const { SKILL_CATALOG } = require('./skill-catalog');

const MAX_ITEMS = 200;
const MAX_DESC = 160;

const where = (p, homeDir) => (p.startsWith(homeDir + path.sep) ? `~${p.slice(homeDir.length)}` : p);

/** SKILL.md files under `root`, nested folders included. */
function skillFiles(root, { skip = [] } = {}) {
  const out = [];
  const walk = (dir, depth) => {
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.name === 'SKILL.md' && entry.isFile()) out.push(full);
      else if (depth < 5 && !skip.includes(entry.name) && (entry.isDirectory() || entry.isSymbolicLink())) walk(full, depth + 1);
    }
  };
  walk(root, 0);
  return out.sort();
}

function skillEntry(file, source, state, homeDir) {
  const meta = parseSkillFrontmatter(file);
  const name = meta.name || path.basename(path.dirname(file));
  // A skill that is off only needs naming; this travels with every agent list.
  const description = state === 'off' ? '' : String(meta.description || '').slice(0, MAX_DESC);
  return { name, description, source, state, location: where(path.dirname(file), homeDir) };
}

/** `.agents/skills` folders Codex scans, from the working dir up to the repo root. */
function repoSkillRoots(workingDir) {
  const roots = [];
  let dir = path.resolve(workingDir);
  for (;;) {
    roots.push(path.join(dir, '.agents', 'skills'));
    if (fs.existsSync(path.join(dir, '.git'))) return roots;
    const parent = path.dirname(dir);
    if (parent === dir) return roots.slice(0, 1);
    dir = parent;
  }
}

function codexMcp(codexHome) {
  let text = '';
  try { text = fs.readFileSync(path.join(codexHome, 'config.toml'), 'utf-8'); } catch { return []; }
  const out = [];
  for (const section of text.split(/^(?=\[)/m)) {
    const m = /^\[mcp_servers\.("?)([^\]"]+)\1\]/.exec(section);
    if (!m) continue;
    out.push({
      name: m[2],
      source: 'home',
      transport: /^\s*url\s*=/m.test(section) ? 'http' : 'stdio',
      state: /^\s*enabled\s*=\s*false/m.test(section) ? 'off' : 'on',
    });
  }
  return out;
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf-8')); } catch { return null; }
}

function claudeMcp(configDir, workingDir, homeDir) {
  const settings = readJson(path.join(configDir, 'settings.json')) || {};
  const state = readJson(path.join(configDir, '.claude.json')) || {};
  const project = (state.projects || {})[path.resolve(workingDir)] || {};
  const out = [{ name: 'openagents-workspace', source: 'workspace', transport: 'stdio', state: 'on' }];
  const add = (servers, source) => {
    for (const [name, cfg] of Object.entries(servers || {})) {
      out.push({ name, source, transport: cfg && (cfg.url || cfg.type === 'http' || cfg.type === 'sse') ? 'http' : 'stdio', state: 'on' });
    }
  };
  add(state.mcpServers, 'home');
  add(project.mcpServers, 'home');
  // Project .mcp.json files apply from the working dir up to the home dir and
  // need approval before they load.
  const disabled = new Set(settings.disabledMcpjsonServers || []);
  const approved = new Set([...(settings.enabledMcpjsonServers || []), ...(project.enabledMcpjsonServers || [])]);
  for (let dir = path.resolve(workingDir); ; dir = path.dirname(dir)) {
    const file = readJson(path.join(dir, '.mcp.json'));
    for (const name of Object.keys((file && file.mcpServers) || {})) {
      const on = !disabled.has(name) && (settings.enableAllProjectMcpServers === true || approved.has(name));
      out.push({ name, source: dir === path.resolve(workingDir) ? 'project' : 'parent', transport: 'stdio',
        state: disabled.has(name) ? 'off' : (on ? 'on' : 'pending'), location: where(path.join(dir, '.mcp.json'), homeDir) });
    }
    if (dir === homeDir || dir === path.dirname(dir)) break;
  }
  return { mcp: out, settings };
}

/**
 * Collect one agent's inventory. `disabledModules` is the set the adapter
 * synced from the workspace; `env` carries the agent's CODEX_HOME or
 * CLAUDE_CONFIG_DIR.
 */
function collectInventory({ agentType, workingDir, env = {}, disabledModules = new Set(), homeDir = os.homedir() }) {
  const type = String(agentType || '').toLowerCase();
  const modules = SKILL_CATALOG.map((m) => ({
    name: m.id,
    state: m.moduleKey && disabledModules.has(m.moduleKey) ? 'off' : 'on',
  }));
  const skills = [];
  let mcp = [];
  const flags = {};
  const wd = workingDir || '';

  if (type === 'codex') {
    const codexHome = env.CODEX_HOME || path.join(homeDir, '.codex');
    for (const f of skillFiles(path.join(wd, '.codex', 'skills'))) skills.push(skillEntry(f, 'hub', 'on', homeDir));
    for (const f of skillFiles(path.join(codexHome, 'skills', '.system'))) skills.push(skillEntry(f, 'builtin', 'on', homeDir));
    for (const f of skillFiles(path.join(codexHome, 'skills'), { skip: ['.system'] })) skills.push(skillEntry(f, 'home', 'on', homeDir));
    if (wd) for (const root of repoSkillRoots(wd)) for (const f of skillFiles(root)) skills.push(skillEntry(f, 'project', 'on', homeDir));
    // Turned off by agent-home.js in a managed home.
    const personal = isManagedHome(codexHome, homeDir) ? 'off' : 'on';
    for (const f of skillFiles(path.join(homeDir, '.agents', 'skills'))) skills.push(skillEntry(f, 'personal', personal, homeDir));
    for (const f of skillFiles('/etc/codex/skills')) skills.push(skillEntry(f, 'admin', 'on', homeDir));
    mcp = codexMcp(codexHome);
  } else if (type === 'claude') {
    const configDir = env.CLAUDE_CONFIG_DIR || path.join(homeDir, '.claude');
    const projectSkills = path.join(wd, '.claude', 'skills');
    for (const f of skillFiles(projectSkills)) skills.push(skillEntry(f, 'project', 'on', homeDir));
    // The connector's own workspace skill is a loose .md file.
    try {
      for (const name of fs.readdirSync(projectSkills)) {
        if (name.endsWith('.md')) skills.push({ name: name.replace(/\.md$/, ''), description: '', source: 'workspace', state: 'on', location: where(projectSkills, homeDir) });
      }
    } catch {}
    const result = claudeMcp(configDir, wd || homeDir, homeDir);
    mcp = result.mcp;
    const synced = result.settings.syncClaudeAiSkills === false ? 'off' : 'on';
    for (const f of skillFiles(path.join(configDir, 'skills'), { skip: ['synced'] })) skills.push(skillEntry(f, 'home', 'on', homeDir));
    for (const f of skillFiles(path.join(configDir, 'skills', 'synced'))) skills.push(skillEntry(f, 'synced', synced, homeDir));
    flags.claudeaiConnectors = result.settings.disableClaudeAiConnectors !== true;
    flags.syncedSkills = result.settings.syncClaudeAiSkills !== false;
    flags.syncedPlugins = result.settings.syncClaudeAiPlugins !== false;
  }

  return { runtime: type || null, modules, skills: skills.slice(0, MAX_ITEMS), mcp: mcp.slice(0, MAX_ITEMS), flags };
}

module.exports = { collectInventory };
