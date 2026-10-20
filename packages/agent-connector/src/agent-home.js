'use strict';

/**
 * Per-agent CLI config homes.
 *
 * Each Codex or Claude Code agent runs against its own config directory,
 * ~/.openagents/homes/<agent>/<type>, so nothing in the person's own ~/.codex
 * or ~/.claude (skills, plugins, MCP servers, hooks, global instructions,
 * approval rules, sessions) reaches a workspace role. The directory is
 * recorded in the agent's env in daemon.yaml, so the daemon, `agn probe` and
 * the launcher all see the same one. Pointing the variable back at ~/.codex or
 * ~/.claude opts an agent out.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const HOME_VARS = { codex: 'CODEX_HOME', claude: 'CLAUDE_CONFIG_DIR' };

// The one thing carried over from the person's own Claude config: how to reach
// the network. Node ignores the macOS system proxy, so without it a new Claude
// home cannot reach Anthropic from behind a proxy.
const PROXY_KEYS = ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
  'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy'];

function agentHomeDir(name, type, homeDir = os.homedir()) {
  const safe = (s) => String(s || '').replace(/[^A-Za-z0-9._-]/g, '_') || 'default';
  return path.join(homeDir, '.openagents', 'homes', safe(name), safe(type));
}

function proxyEnv(homeDir = os.homedir(), env = process.env) {
  const pick = (source) => Object.fromEntries(PROXY_KEYS
    .filter((k) => typeof source[k] === 'string' && source[k])
    .map((k) => [k, source[k]]));
  const fromEnv = pick(env);
  if (Object.keys(fromEnv).length) return fromEnv;
  try {
    const settings = JSON.parse(fs.readFileSync(path.join(homeDir, '.claude', 'settings.json'), 'utf-8'));
    return pick(settings.env || {});
  } catch {
    return {};
  }
}

/** Create the home with a minimal config. Existing files are never overwritten. */
function seedAgentHome(type, dir, homeDir = os.homedir(), env = process.env) {
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  const write = (file, text) => {
    const target = path.join(dir, file);
    if (!fs.existsSync(target)) fs.writeFileSync(target, text, { mode: 0o600 });
  };
  if (type === 'codex') {
    write('config.toml', "# This agent's own Codex config. ~/.codex is not read.\n");
  } else if (type === 'claude') {
    // A separate config dir still signs in to the person's claude.ai account,
    // which would hand the role their connectors and synced skills and plugins.
    const settings = {
      skipDangerousModePermissionPrompt: true,
      disableClaudeAiConnectors: true,
      syncClaudeAiSkills: false,
      syncClaudeAiPlugins: false,
    };
    const proxy = proxyEnv(homeDir, env);
    if (Object.keys(proxy).length) settings.env = proxy;
    write('settings.json', `${JSON.stringify(settings, null, 2)}\n`);
  }
}

/** A home this module manages, as opposed to one a person pointed an agent at. */
function isManagedHome(dir, homeDir = os.homedir()) {
  const root = path.join(homeDir, '.openagents', 'homes') + path.sep;
  return path.resolve(String(dir || '')).startsWith(root);
}

// Codex always scans ~/.agents/skills, whatever CODEX_HOME says, and offers no
// switch for the folder: each skill must be turned off by its SKILL.md path.
const SKILLS_BEGIN = '# >>> openagents: skills in ~/.agents/skills are off for this agent. Rewritten before every run; put your own settings above.';
const SKILLS_END = '# <<< openagents';

function personalSkillFiles(homeDir = os.homedir()) {
  const out = [];
  const walk = (dir, depth) => {
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.name === 'SKILL.md' && entry.isFile()) out.push(full);
      else if (depth < 5 && (entry.isDirectory() || entry.isSymbolicLink())) walk(full, depth + 1);
    }
  };
  walk(path.join(homeDir, '.agents', 'skills'), 0);
  return out.sort();
}

/** Keep the block that turns off the person's ~/.agents/skills current in a Codex home. */
function syncPersonalSkills(codexHome, homeDir = os.homedir()) {
  const file = path.join(codexHome, 'config.toml');
  let text = '';
  try { text = fs.readFileSync(file, 'utf-8'); } catch {}
  const start = text.indexOf(SKILLS_BEGIN);
  const end = start === -1 ? -1 : text.indexOf(SKILLS_END, start);
  const rest = start === -1 ? text
    : text.slice(0, start) + (end === -1 ? '' : text.slice(end + SKILLS_END.length));
  const skills = personalSkillFiles(homeDir);
  const block = skills.length
    ? [SKILLS_BEGIN, ...skills.map((p) => `[[skills.config]]\npath = ${JSON.stringify(p)}\nenabled = false`), SKILLS_END].join('\n')
    : '';
  const kept = rest.replace(/\s+$/, '');
  const next = (kept ? `${kept}\n` : '') + (block ? `${kept ? '\n' : ''}${block}\n` : '');
  if (next !== text) fs.writeFileSync(file, next, { mode: 0o600 });
  return skills.length;
}

/**
 * Give every Codex and Claude agent that lacks one its own config home and
 * record it in daemon.yaml. Returns the names of the agents that changed.
 */
function ensureAgentHomes(config, homeDir = os.homedir(), env = process.env) {
  const changed = [];
  for (const agent of config.getAgents()) {
    const type = String(agent.type || '').toLowerCase();
    const key = HOME_VARS[type];
    if (!key || (agent.env && agent.env[key])) continue;
    const dir = agentHomeDir(agent.name, type, homeDir);
    seedAgentHome(type, dir, homeDir, env);
    config.updateAgent(agent.name, { env: { ...(agent.env || {}), [key]: dir } });
    changed.push(agent.name);
  }
  return changed;
}

module.exports = {
  HOME_VARS, agentHomeDir, ensureAgentHomes, isManagedHome, personalSkillFiles,
  proxyEnv, seedAgentHome, syncPersonalSkills,
};
