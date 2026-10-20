'use client';

import type { ReactNode } from 'react';
import { Sparkles } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useFormatters, useT, type MessageKey } from '@/lib/i18n';
import type { SkillStatusEntry } from '@/lib/types';

interface InventoryItem {
  name: string;
  description?: string;
  source?: string;
  state?: string;
  location?: string;
}

/** What an agent's connector last reported it can use (agent-connector/src/inventory.js). */
export interface AgentInventory {
  runtime?: string | null;
  modules?: InventoryItem[];
  skills?: InventoryItem[];
  mcp?: InventoryItem[];
  flags?: Record<string, boolean>;
  reported_at?: string;
}

const SOURCES = ['builtin', 'home', 'project', 'workspace', 'admin', 'synced', 'personal', 'hub', 'parent'];
const MODULES = ['workspace-core', 'files', 'browser', 'tunnel', 'todos', 'timers', 'routines', 'knowledge'];
const FLAGS = ['claudeaiConnectors', 'syncedSkills', 'syncedPlugins'] as const;

function Badge({ tone, children }: { tone: 'on' | 'off' | 'warn'; children: ReactNode }) {
  return (
    <span className={cn('shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium',
      tone === 'on' && 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
      tone === 'off' && 'bg-muted text-muted-foreground',
      tone === 'warn' && 'bg-amber-500/10 text-amber-700 dark:text-amber-300')}>
      {children}
    </span>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-1.5 px-3.5 py-2.5">
      <div className="text-[11px] font-medium text-muted-foreground">{title}</div>
      {children}
    </div>
  );
}

function Row({ name, hint, children }: { name: string; hint?: string; children?: ReactNode }) {
  return (
    <div className="flex items-center gap-2">
      <span className="min-w-0 flex-1 truncate" title={hint || name}>{name}</span>
      {children}
    </div>
  );
}

/**
 * The agent's skills panel: workspace tools, Skill Hub installs, the skills
 * and MCP servers it can actually use, and what is blocked, as last reported.
 */
export function AgentSkills({ enabledSkills, reportsInventory = true }: {
  enabledSkills: Record<string, unknown> | null;
  /** False for agents without a local connector (cloud agents). */
  reportsInventory?: boolean;
}) {
  const t = useT();
  const { timeAgo } = useFormatters();
  const inventory = (enabledSkills?.inventory ?? null) as AgentInventory | null;
  const hub = Object.entries((enabledSkills?.skill_status ?? {}) as Record<string, SkillStatusEntry>)
    .filter(([, s]) => s && s.state !== 'uninstalled');
  const skills = inventory?.skills ?? [];
  const available = skills.filter((s) => s.state !== 'off' && s.source !== 'hub');
  const blocked = skills.filter((s) => s.state === 'off');
  const source = (s?: string) => (s && SOURCES.includes(s) ? t(`agents.skillsSource.${s}` as MessageKey) : s || '');
  const onDisk = (id: string) => skills.some((s) => s.name === id || s.location?.endsWith(`/${id}`));
  if (!inventory && hub.length === 0 && !reportsInventory) return null;

  return (
    <div className="rounded-lg border overflow-hidden">
      <div className="px-3.5 py-2.5 border-b flex items-center gap-1.5">
        <Sparkles className="size-3 text-amber-500" />
        <span className="text-xs font-medium">{t('agents.skillsTitle')}</span>
        {inventory?.reported_at && (
          <span className="ml-auto text-[10px] text-muted-foreground">{t('agents.skillsReportedAt', { time: timeAgo(inventory.reported_at) })}</span>
        )}
      </div>
      <div className="divide-y text-[13px]">
        {inventory && (
          <Section title={t('agents.skillsModules')}>
            <div className="flex flex-wrap gap-1.5">
              {(inventory.modules ?? []).map((m) => (
                <span key={m.name} className={cn('rounded-md border px-2 py-0.5 text-xs', m.state === 'off' && 'text-muted-foreground line-through')}>
                  {MODULES.includes(m.name) ? t(`agents.skillsModule.${m.name}` as MessageKey) : m.name}
                </span>
              ))}
            </div>
          </Section>
        )}
        {hub.length > 0 && (
          <Section title={t('agents.skillsHub')}>
            {hub.map(([id, s]) => (
              <Row key={id} name={id}>
                {inventory && s.state === 'installed' && !onDisk(id)
                  ? <Badge tone="warn">{t('agents.skillsMissing')}</Badge>
                  : <Badge tone={s.state === 'failed' ? 'warn' : 'on'}>{t(`agents.skillsHubState.${s.state}` as MessageKey)}</Badge>}
              </Row>
            ))}
          </Section>
        )}
        {!inventory && reportsInventory && (
          <p className="px-3.5 py-3 text-xs text-muted-foreground">{t('agents.skillsNotReported')}</p>
        )}
        {inventory && (
          <Section title={t('agents.skillsAvailable', { count: available.length })}>
            {available.map((s) => (
              <Row key={`${s.source}:${s.location}:${s.name}`} name={s.name} hint={s.description}>
                <Badge tone="off">{source(s.source)}</Badge>
              </Row>
            ))}
            {inventory.runtime === 'claude' && <p className="text-[11px] text-muted-foreground">{t('agents.skillsClaudeBuiltin')}</p>}
          </Section>
        )}
        {blocked.length > 0 && (
          <details className="px-3.5 py-2.5">
            <summary className="cursor-pointer text-[11px] font-medium text-muted-foreground">{t('agents.skillsBlocked', { count: blocked.length })}</summary>
            <ul className="mt-1.5 space-y-0.5 text-xs text-muted-foreground">
              {blocked.map((s) => <li key={`${s.location}:${s.name}`} className="truncate" title={s.location}>{s.name} · {source(s.source)}</li>)}
            </ul>
          </details>
        )}
        {inventory && (
          <Section title={t('agents.skillsMcp')}>
            {(inventory.mcp ?? []).map((m) => {
              const state = m.state === 'on' || m.state === 'pending' ? m.state : 'off';
              return (
                <Row key={`${m.source}:${m.name}`} name={m.name} hint={m.location}>
                  <span className="text-[10px] text-muted-foreground">{source(m.source)}</span>
                  <Badge tone={state === 'on' ? 'on' : state === 'pending' ? 'warn' : 'off'}>{t(`agents.skillsState.${state}`)}</Badge>
                </Row>
              );
            })}
          </Section>
        )}
        {inventory?.runtime === 'claude' && inventory.flags && (
          <Section title={t('agents.skillsAccount')}>
            {FLAGS.map((k) => (
              <Row key={k} name={t(`agents.skillsFlag.${k}`)}>
                <Badge tone={inventory.flags?.[k] ? 'warn' : 'off'}>{t(`agents.skillsState.${inventory.flags?.[k] ? 'on' : 'off'}`)}</Badge>
              </Row>
            ))}
          </Section>
        )}
      </div>
    </div>
  );
}
