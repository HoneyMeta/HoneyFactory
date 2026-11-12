// Command registry for the command palette (Ctrl+K). Any module can add commands:
//   import { registerCommand } from '@/commands/registry'
//   registerCommand({ id: 'plc.compile', title: 'Compile PLC Program', keywords: 'build compile', group: 'PLC', shortcut: 'Ctrl+B', when: () => …, run: () => … })
// Also supports providers (dynamic results for the query, e.g. factories, equipment, lessons): registerProvider('plants', (q) => [...]).
// Rank results by fuzzy match score, prioritizing recently used commands (stored locally in vf_cmd_recent).
import { $t } from '../i18n';
import { reactive } from 'vue';

export type Command = {
  id: string;
  title: string;
  run: () => any;
  keywords?: string | string[];
  when?: () => boolean;
  shortcut?: string;
  group?: string;
  icon?: string;
  hint?: string;
};
type Provider = (q: string) => Command[];

const cmds = new Map<string, Command>();
const providers = new Map<string, Provider>();
export const palette = reactive({ open: false, q: '', tick: 0 });

export function registerCommand(c: Command) { cmds.set(c.id, c); palette.tick++; return () => { if (cmds.get(c.id) === c) cmds.delete(c.id); palette.tick++; }; }
export function registerCommands(list: Command[]) { const offs = list.map(registerCommand); return () => offs.forEach((f) => f()); }
export function registerProvider(id: string, fn: Provider) { providers.set(id, fn); palette.tick++; return () => { providers.delete(id); palette.tick++; }; }
export const commandById = (id: string) => cmds.get(id);
export function openCommandPalette(q = '') { palette.q = q; palette.open = true; }
export function closeCommandPalette() { palette.open = false; }

// ---------- Recently used ----------
const RKEY = 'vf_cmd_recent';
function readRecent(): string[] { try { const v = JSON.parse(localStorage.getItem(RKEY) || '[]'); return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []; } catch { return []; } }
export const recent = reactive<{ ids: string[] }>({ ids: readRecent() });
function remember(id: string) {
  recent.ids = [id, ...recent.ids.filter((x) => x !== id)].slice(0, 30);
  try { localStorage.setItem(RKEY, JSON.stringify(recent.ids)); } catch { /* */ }
}

// ---------- Fuzzy matching ----------
const norm = (s: string) => s.toLowerCase().replace(/\s+/g, ' ').trim();
/** Score a word against text: contiguous match > prefix match > ordered scattered match (subsequence); return -1 for no match. */
function termScore(term: string, text: string, fuzzy = true): number {
  const i = text.indexOf(term);
  if (i >= 0) return 60 + (i === 0 ? 30 : /[\s\u00b7\uff1a:\uff08(/]/.test(text[i - 1] || '') ? 15 : 0) + Math.min(term.length * 4, 30) - Math.min(i, 20) * 0.5;
  if (!fuzzy) return -1;
  // Subsequence: characters appear in order; smaller gaps score higher
  let pos = -1, gaps = 0;
  for (const ch of term) { if (ch === ' ') continue; const j = text.indexOf(ch, pos + 1); if (j < 0) return -1; if (pos >= 0) gaps += j - pos - 1; pos = j; }
  return Math.max(1, 35 - gaps * 2);
}
export function scoreCommand(c: Command, q: string): number {
  const title = norm(c.title), kw = norm(Array.isArray(c.keywords) ? c.keywords.join(' ') : c.keywords || '');
  const qq = norm(q);
  if (!qq) return 0;
  if (title === qq) return 1000;
  // First look for the full phrase in the title ("switch to floor" → "switch to floor plan")
  const whole = termScore(qq, title);
  let s = whole >= 60 ? whole + 80 : 0;
  if (!s) {
    // Then split into words: each must appear in the title or keywords
    for (const t of qq.split(' ')) {
      const a = termScore(t, title), b = termScore(t, kw, false), c2 = termScore(t, norm(c.group || ''), false);
      const best = Math.max(a, b * 0.8, c2 * 0.5);
      if (best < 0) return -1;
      s += best;
    }
  }
  return s - title.length * 0.15;
}

export type Hit = Command & { score: number; recentRank: number };
/** Available commands (when is true), ranked by query score; without a query, show recent commands first, then group the rest. */
export function search(q: string, limit = 60): Hit[] {
  void palette.tick;
  const live: Command[] = [...cmds.values()];
  for (const p of providers.values()) { try { live.push(...p(q)); } catch (e) { console.warn($t('registry.commandProviderError'), e); } }
  const out: Hit[] = [];
  const seen = new Set<string>();
  for (const c of live) {
    if (seen.has(c.id)) continue;
    let ok = true;
    try { ok = !c.when || !!c.when(); } catch { ok = false; }
    if (!ok) continue;
    const r = recent.ids.indexOf(c.id);
    const s = q.trim() ? scoreCommand(c, q) : 0;
    if (s < 0) continue;
    seen.add(c.id);
    out.push({ ...c, score: s + (r >= 0 ? 40 - r : 0), recentRank: r });
  }
  if (!q.trim()) {
    out.sort((a, b) => (a.recentRank < 0 ? 999 : a.recentRank) - (b.recentRank < 0 ? 999 : b.recentRank));
    return out.slice(0, limit);
  }
  return out.sort((a, b) => b.score - a.score).slice(0, limit);
}
export async function runCommand(c: Command) {
  remember(c.id);
  palette.open = false;
  try { await c.run(); } catch (e: any) { if (e && e !== 'cancel' && e !== 'close') console.warn($t('registry.commandFailed'), c.id, e); }
}
