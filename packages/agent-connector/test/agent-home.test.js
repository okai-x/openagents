'use strict';

const { describe, it, beforeEach, afterEach } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const os = require('os');
const { Config } = require('../src/config');
const { ensureAgentHomes, proxyEnv } = require('../src/agent-home');

let home;
let config;

beforeEach(() => {
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'ac-home-'));
  config = new Config(path.join(home, '.openagents'));
});

afterEach(() => {
  fs.rmSync(home, { recursive: true, force: true });
});

describe('ensureAgentHomes', () => {
  it('gives Codex and Claude agents a seeded home of their own, recorded in daemon.yaml', () => {
    config.addAgent({ name: 'sre', type: 'codex', path: '/work/sre' });
    config.addAgent({ name: 'architect', type: 'claude', env: { LLM_MODEL: 'opus' } });
    config.addAgent({ name: 'bot', type: 'openclaw' });

    const changed = ensureAgentHomes(config, home, { HTTPS_PROXY: 'http://127.0.0.1:7897' });

    assert.deepEqual(changed, ['sre', 'architect']);
    const codexHome = path.join(home, '.openagents', 'homes', 'sre', 'codex');
    const claudeHome = path.join(home, '.openagents', 'homes', 'architect', 'claude');
    assert.equal(config.getAgent('sre').env.CODEX_HOME, codexHome);
    assert.deepEqual(config.getAgent('architect').env, { LLM_MODEL: 'opus', CLAUDE_CONFIG_DIR: claudeHome });
    assert.equal(config.getAgent('bot').env, undefined);
    assert.ok(fs.existsSync(path.join(codexHome, 'config.toml')));
    const settings = JSON.parse(fs.readFileSync(path.join(claudeHome, 'settings.json'), 'utf-8'));
    assert.deepEqual(settings.env, { HTTPS_PROXY: 'http://127.0.0.1:7897' });
    assert.equal(fs.statSync(claudeHome).mode & 0o777, 0o700);
  });

  it('keeps an explicit home, which is how an agent opts out', () => {
    config.addAgent({ name: 'mine', type: 'codex', env: { CODEX_HOME: '/Users/me/.codex' } });
    assert.deepEqual(ensureAgentHomes(config, home, {}), []);
    assert.equal(config.getAgent('mine').env.CODEX_HOME, '/Users/me/.codex');
  });

  it('never overwrites a config already in the home', () => {
    config.addAgent({ name: 'sre', type: 'codex' });
    const dir = path.join(home, '.openagents', 'homes', 'sre', 'codex');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'config.toml'), 'model = "custom"\n');
    ensureAgentHomes(config, home, {});
    assert.equal(fs.readFileSync(path.join(dir, 'config.toml'), 'utf-8'), 'model = "custom"\n');
  });
});

describe('proxyEnv', () => {
  it("takes only the proxy from the person's Claude settings when the env has none", () => {
    fs.mkdirSync(path.join(home, '.claude'));
    fs.writeFileSync(path.join(home, '.claude', 'settings.json'), JSON.stringify({
      env: { HTTPS_PROXY: 'http://proxy:1', NO_PROXY: 'localhost', ANTHROPIC_API_KEY: 'secret' },
      hooks: { Stop: [] },
    }));
    assert.deepEqual(proxyEnv(home, {}), { HTTPS_PROXY: 'http://proxy:1', NO_PROXY: 'localhost' });
  });
});
