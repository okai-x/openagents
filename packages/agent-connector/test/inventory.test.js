'use strict';

const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { collectInventory } = require('../src/inventory');

let home;
const write = (rel, text) => {
  const file = path.join(home, rel);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, text);
};
const skill = (rel, name, description = '') => write(`${rel}/SKILL.md`, `---\nname: ${name}\ndescription: ${description}\n---\nbody`);
const find = (list, name) => list.find((x) => x.name === name);

beforeEach(() => { home = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ac-inv-'))); });
afterEach(() => { fs.rmSync(home, { recursive: true, force: true }); });

describe('collectInventory', () => {
  it('lists a Codex agent by source, with personal skills off in a managed home', () => {
    const wd = path.join(home, 'team', 'sre');
    fs.mkdirSync(path.join(home, 'team', '.git'), { recursive: true });
    const codexHome = path.join(home, '.openagents', 'homes', 'sre', 'codex');
    skill('team/sre/.codex/skills/runbook', 'runbook', 'Hub skill');
    skill('.openagents/homes/sre/codex/skills/.system/skill-creator', 'skill-creator');
    skill('team/.agents/skills/team-style', 'team-style');
    skill('.agents/skills/cloudflare', 'cloudflare');
    write('.openagents/homes/sre/codex/config.toml',
      'model = "m"\n\n[mcp_servers.cloudflare]\nurl = "https://example.com/mcp"\n\n[mcp_servers.local]\ncommand = "x"\nenv = { TOKEN = "secret" }\nenabled = false\n');

    const inv = collectInventory({ agentType: 'codex', workingDir: wd, env: { CODEX_HOME: codexHome },
      disabledModules: new Set(['browser']), homeDir: home });

    assert.equal(inv.runtime, 'codex');
    assert.equal(find(inv.modules, 'browser').state, 'off');
    assert.equal(find(inv.modules, 'workspace-core').state, 'on');
    assert.deepEqual(find(inv.skills, 'runbook'), {
      name: 'runbook', description: 'Hub skill', source: 'hub', state: 'on', location: '~/team/sre/.codex/skills/runbook',
    });
    assert.equal(find(inv.skills, 'skill-creator').source, 'builtin');
    assert.equal(find(inv.skills, 'team-style').source, 'project');
    assert.deepEqual([find(inv.skills, 'cloudflare').source, find(inv.skills, 'cloudflare').state], ['personal', 'off']);
    assert.deepEqual(inv.mcp, [
      { name: 'cloudflare', source: 'home', transport: 'http', state: 'on' },
      { name: 'local', source: 'home', transport: 'stdio', state: 'off' },
    ]);
    assert.ok(!JSON.stringify(inv).includes('secret'));
  });

  it("lists a Claude agent's skills, MCP servers and claude.ai switches without their secrets", () => {
    const wd = path.join(home, 'team', 'architect');
    const configDir = path.join(home, '.openagents', 'homes', 'architect', 'claude');
    skill('team/architect/.claude/skills/adr', 'adr');
    write('team/architect/.claude/skills/openagents-workspace-architect.md', 'token inside');
    write('.openagents/homes/architect/claude/settings.json', JSON.stringify({
      disableClaudeAiConnectors: true, syncClaudeAiSkills: false, disabledMcpjsonServers: ['gw'],
    }));
    write('.openagents/homes/architect/claude/.claude.json', JSON.stringify({
      mcpServers: { mine: { command: 'x', env: { TOKEN: 'secret' } } },
    }));
    write('.mcp.json', JSON.stringify({ mcpServers: { gw: { command: 'uvx' }, other: { command: 'y' } } }));

    const inv = collectInventory({ agentType: 'claude', workingDir: wd, env: { CLAUDE_CONFIG_DIR: configDir }, homeDir: home });

    assert.equal(find(inv.skills, 'adr').source, 'project');
    assert.equal(find(inv.skills, 'openagents-workspace-architect').source, 'workspace');
    assert.deepEqual(inv.mcp.map((m) => [m.name, m.source, m.state]), [
      ['openagents-workspace', 'workspace', 'on'],
      ['mine', 'home', 'on'],
      ['gw', 'parent', 'off'],
      ['other', 'parent', 'pending'],
    ]);
    assert.deepEqual(inv.flags, { claudeaiConnectors: false, syncedSkills: false, syncedPlugins: true });
    assert.ok(!JSON.stringify(inv).includes('secret'));
    assert.ok(!JSON.stringify(inv).includes('token inside'));
  });
});
