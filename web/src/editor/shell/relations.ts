// Object relations (4.3): upstream/downstream material flow, controlling PLC and each signal, network path (→ switch → gateway → MES).
// Shared by the Objects panel's "Relations" card, hover highlighting, floor plan/architecture views, and navigation history (back/forward).
import { computed } from 'vue';
import { blocksById, ed, focusOn, select } from '../store';

export type SignalRef = { link: string; point: string; ch: string; dir: 'in' | 'out'; device: string; plc: string };
export type Relations = {
  upstream: string[]; downstream: string[];          // Material
  plcs: string[]; devices: string[];                  // Equipment → controlling PLC; PLC → controlled equipment
  signals: SignalRef[];                               // Every signal involving this object
  network: string[];                                  // Objects directly connected by network
  path: string[];                                     // Network path: a shortest path along network cables to an information system (MES/SCADA)
  links: string[];                                    // IDs of all related connections (for highlighting)
};

const layerOf = (id: string) => (ed.cat?.types?.[blocksById.value[id]?.type]?.layer) || 'process';
export const linkKind = (l: any) => l?.kind || 'material';

/** All relations for an object. */
export function relationsOf(id: string): Relations {
  const links = ed.model?.links || [];
  const r: Relations = { upstream: [], downstream: [], plcs: [], devices: [], signals: [], network: [], path: [], links: [] };
  const add = (arr: string[], x: string) => { if (x && x !== id && !arr.includes(x)) arr.push(x); };
  for (const l of links) {
    const k = linkKind(l);
    if (l.from !== id && l.to !== id && l.via !== id) continue;
    r.links.push(l.id);
    if (k === 'material') { if (l.to === id) add(r.upstream, l.from); if (l.from === id) add(r.downstream, l.to); }
    else if (k === 'signal') {
      const plc = layerOf(l.to) === 'control' ? l.to : l.from, dev = plc === l.to ? l.from : l.to;
      if (id === dev) add(r.plcs, plc); else add(r.devices, dev);
      for (const s of l.signals || []) r.signals.push({ link: l.id, point: s.point, ch: s.ch, dir: s.dir, device: dev, plc });
    } else if (k === 'network') add(r.network, l.from === id ? l.to : l.from);
  }
  r.path = networkPath(id);
  return r;
}

/** Find the shortest network path from an object to an information system (MES/SCADA); equipment goes through its controlling PLC first. */
function networkPath(id: string): string[] {
  const links = (ed.model?.links || []).filter((l: any) => linkKind(l) === 'network');
  const nb = (x: string) => links.filter((l: any) => l.from === x || l.to === x).map((l: any) => (l.from === x ? l.to : l.from));
  let starts = [id];
  if (layerOf(id) === 'process') starts = (ed.model?.links || []).filter((l: any) => linkKind(l) === 'signal' && (l.from === id || l.to === id)).map((l: any) => (l.from === id ? l.to : l.from));
  for (const s of starts) {
    const prev: Record<string, string> = { [s]: '' }, q = [s];
    while (q.length) {
      const x = q.shift()!;
      if (layerOf(x) === 'it' && x !== id) { const p: string[] = []; for (let c = x; c; c = prev[c]) p.unshift(c); return id === s ? p.slice(1) : p; }
      for (const y of nb(x)) if (!(y in prev)) { prev[y] = x; q.push(y); }
    }
  }
  return [];
}

/** Objects and connections to highlight on hover. */
export function relatedSet(id: string) {
  const r = relationsOf(id);
  return { ids: new Set([id, ...r.upstream, ...r.downstream, ...r.plcs, ...r.devices, ...r.network, ...r.path]), links: new Set(r.links) };
}

// ---------- Navigation (click a relation to jump; IDE-style back/forward) ----------
const hist = { back: [] as string[], fwd: [] as string[] };
export const canBack = computed(() => (ed.navTick, hist.back.length > 0));
export const canFwd = computed(() => (ed.navTick, hist.fwd.length > 0));
export function goTo(id: string) {
  if (!blocksById.value[id]) return;
  const cur = ed.sel[0];
  if (cur && cur !== id) { hist.back.push(cur); if (hist.back.length > 50) hist.back.shift(); hist.fwd = []; }
  select([id]); focusOn(id); ed.navTick = (ed.navTick || 0) + 1;
}
export function goBack() {
  const id = hist.back.pop(); if (!id) return;
  if (ed.sel[0]) hist.fwd.push(ed.sel[0]);
  select([id]); focusOn(id); ed.navTick = (ed.navTick || 0) + 1;
}
export function goFwd() {
  const id = hist.fwd.pop(); if (!id) return;
  if (ed.sel[0]) hist.back.push(ed.sel[0]);
  select([id]); focusOn(id); ed.navTick = (ed.navTick || 0) + 1;
}

// ---------- Layer filters (shared across views; persisted) ----------
const FKEY = 'vf_filter';
export function defaultFilter() {
  return { layers: { process: true, control: true, network: true, it: true }, links: { material: true, signal: true, network: true } };
}
export function loadFilter() { try { ed.filter = { ...defaultFilter(), ...JSON.parse(localStorage.getItem(FKEY) || '{}') }; } catch { ed.filter = defaultFilter(); } }
export function saveFilter() { try { localStorage.setItem(FKEY, JSON.stringify(ed.filter)); } catch { /* */ } }
export const layerVisible = (id: string) => ed.filter?.layers?.[layerOf(id)] !== false;
export const linkVisible = (l: any) => ed.filter?.links?.[linkKind(l)] !== false && layerVisible(l.from) && layerVisible(l.to);
export { layerOf };
