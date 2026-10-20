// @vitest-environment jsdom
import React, { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

vi.mock('@/lib/i18n', () => ({
  useT: () => (key: string, params?: Record<string, unknown>) => (params ? `${key} ${Object.values(params).join(' ')}` : key),
  useFormatters: () => ({ timeAgo: () => '5m' }),
}));
import { AgentSkills } from './agent-skills';

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

const render = (props: Parameters<typeof AgentSkills>[0]) => act(async () => root.render(React.createElement(AgentSkills, props)));

it('shows a Codex agent by layer, keeping blocked personal skills folded away', async () => {
  await render({
    enabledSkills: {
      browser: false,
      skill_status: { runbook: { state: 'installed' }, 'claude-api': { state: 'installed' }, gone: { state: 'uninstalled' } },
      inventory: {
        runtime: 'codex',
        modules: [{ name: 'files', state: 'on' }, { name: 'browser', state: 'off' }],
        skills: [
          { name: 'runbook', source: 'hub', state: 'on', location: '~/team/sre/.codex/skills/runbook' },
          { name: 'skill-creator', source: 'builtin', state: 'on', description: 'Create skills' },
          { name: 'cloudflare', source: 'personal', state: 'off', location: '~/.agents/skills/cloudflare' },
        ],
        mcp: [{ name: 'cloudflare', source: 'home', state: 'on' }],
        reported_at: '2026-10-20T08:00:00Z',
      },
    },
  });

  const text = host.textContent || '';
  expect(text).toContain('agents.skillsReportedAt 5m');
  expect(host.querySelector('.line-through')?.textContent).toBe('agents.skillsModule.browser');
  // Installed in the hub but not found on the device; removed skills are not listed.
  expect(text).toContain('claude-apiagents.skillsMissing');
  expect(text).toContain('runbookagents.skillsHubState.installed');
  expect(text).not.toContain('gone');
  expect(text).toContain('agents.skillsAvailable 1');
  expect(host.querySelector('details summary')?.textContent).toBe('agents.skillsBlocked 1');
  expect(host.querySelector('details li')?.textContent).toBe('cloudflare · agents.skillsSource.personal');
  expect(text).not.toContain('agents.skillsAccount');
});

it("shows a Claude agent's account switches and the built-in note", async () => {
  await render({
    enabledSkills: {
      inventory: {
        runtime: 'claude',
        modules: [],
        skills: [{ name: 'openagents-workspace-architect', source: 'workspace', state: 'on' }],
        mcp: [
          { name: 'openagents-workspace', source: 'workspace', state: 'on' },
          { name: 'google-workspace', source: 'parent', state: 'off' },
          { name: 'other', source: 'parent', state: 'pending' },
        ],
        flags: { claudeaiConnectors: false, syncedSkills: false, syncedPlugins: true },
      },
    },
  });

  const text = host.textContent || '';
  expect(text).toContain('agents.skillsClaudeBuiltin');
  expect(text).toContain('google-workspaceagents.skillsSource.parentagents.skillsState.off');
  expect(text).toContain('otheragents.skillsSource.parentagents.skillsState.pending');
  expect(text).toContain('agents.skillsFlag.syncedPluginsagents.skillsState.on');
  expect(text).toContain('agents.skillsFlag.claudeaiConnectorsagents.skillsState.off');
});

it('says when a local agent has not reported, and stays hidden for a cloud agent with nothing to show', async () => {
  await render({ enabledSkills: null });
  expect(host.textContent).toContain('agents.skillsNotReported');

  await render({ enabledSkills: null, reportsInventory: false });
  expect(host.textContent).toBe('');
});
