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
    const settings = { skipDangerousModePermissionPrompt: true };
    const proxy = proxyEnv(homeDir, env);
    if (Object.keys(proxy).length) settings.env = proxy;
    write('settings.json', `${JSON.stringify(settings, null, 2)}\n`);
  }
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

module.exports = { HOME_VARS, agentHomeDir, ensureAgentHomes, proxyEnv, seedAgentHome };
