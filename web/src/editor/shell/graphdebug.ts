// Graph-centric debugging (inspired by UE Blueprints): set breakpoints, watches, and fault injection on equipment nodes, with results drawn on the graph.
// All three views (Graph / Floor Plan / 3D) and context menus share this data: ed.bps (breakpoints), ed.watches / ed.watchVals (watches), stationInfo (equipment tags and injectable faults).
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { reactive } from 'vue';
import { del, get, P, patch, post } from '../../api';
import { blocksById, ed, flash, focusOn, select } from '../store';

const pid = () => ed.pid;

// ---------- Breakpoints ----------
export async function loadBps() { ed.bps = await get(P(pid()) + '/breakpoints', true).catch(() => []); }
export const bpsOf = (id: string) => (ed.bps || []).filter((b: any) => b.cond?.id === id);
/** Graph marker: 'on' for enabled breakpoints, 'off' for disabled only, '' for none. */
export function bpMark(id: string) { const l = bpsOf(id); return !l.length ? '' : l.some((b: any) => b.enabled) ? 'on' : 'off'; }
export async function addBp(cond: any, name?: string) {
  await post(P(pid()) + '/breakpoints', { cond, name });
  changed();
}
export async function toggleBp(b: any) { await patch(`${P(pid())}/breakpoints/${b.id}`, { enabled: !b.enabled }); changed(); }
export async function removeBp(b: any) { await del(`${P(pid())}/breakpoints/${b.id}`); changed(); }
function changed() { window.dispatchEvent(new CustomEvent('vf:breakpoints-changed')); }
/** F9: add a default breakpoint to selected equipment (buffer: full; others: enters downtime), or remove all existing breakpoints. */
export async function toggleDefaultBp(ids: string[]) {
  for (const id of ids) {
    const l = bpsOf(id);
    if (l.length) { for (const b of l) await del(`${P(pid())}/breakpoints/${b.id}`); continue; }
    const b = blocksById.value[id];
    if (b?.type === 'buffer') await post(P(pid()) + '/breakpoints', { cond: { kind: 'buffer', id, op: '>=', value: b.params?.capacity || 10 } });
    else await post(P(pid()) + '/breakpoints', { cond: { kind: 'state', id, state: 'Stopped' } });
  }
  changed();
}
export async function promptBp(kind: string, id: string) {
  if (kind === 'state_for') {
    const r = await ElMessageBox.prompt($t('graphdebug.pauseAfterHowManyMinutes'), $t('graphdebug.setBreakpoint'), { inputValue: '10', inputPattern: /^\d+(\.\d+)?$/, inputErrorMessage: $t('graphdebug.enterANumber') }).catch(() => null);
    if (r) await addBp({ kind: 'state_for', id, state: 'Stopped', minutes: +r.value });
  } else if (kind === 'buffer') {
    const r = await ElMessageBox.prompt($t('graphdebug.pauseWhenThePartCount'), $t('graphdebug.setBreakpoint'), { inputValue: String(blocksById.value[id]?.params?.capacity || 10), inputPattern: /^\d+$/, inputErrorMessage: $t('graphdebug.enterAnInteger') }).catch(() => null);
    if (r) await addBp({ kind: 'buffer', id, op: '>=', value: +r.value });
  }
}
export async function tagBp(id: string, tag: string) {
  const cur = ed.watchVals[id]?.[tag] ?? stationInfo[id]?.tags?.[tag]?.v;
  const r = await ElMessageBox.prompt($t('graphdebug.pauseWhen0ExceedsWhat', [tag, fmt(cur)]), $t('graphdebug.tagBreakpoint'), { inputValue: typeof cur === 'number' ? String(+(cur * 1.1).toFixed(2)) : '', inputPattern: /^-?\d+(\.\d+)?$/, inputErrorMessage: $t('graphdebug.enterANumber') }).catch(() => null);
  if (r) await addBp({ kind: 'tag', id, tag, op: '>', value: +r.value });
}

// ---------- Equipment info (tags, injectable faults), fetched once when the context menu opens ----------
export const stationInfo = reactive<Record<string, any>>({});
export async function loadStation(id: string) {
  const d = await get(`${P(pid())}/station/${encodeURIComponent(id)}`, true).catch(() => null);
  if (d) stationInfo[id] = { tags: d.tags || {}, faults: d.faults || {}, at: Date.now() };
  return stationInfo[id];
}
export const numericTags = (id: string) => Object.entries(stationInfo[id]?.tags || {}).filter(([, t]: any) => typeof t.v === 'number').map(([k]) => k);

// ---------- Faults ----------
export async function injectFault(id: string, kind: string) {
  await post(`${P(pid())}/station/${encodeURIComponent(id)}/fault`, { kind });
  ElMessage.success(kind === 'clear' ? $t('graphdebug.faultCleared') : $t('graphdebug.faultInjected')); flash([id], 3000);
}

// ---------- Watches (UE Watch): show live values below nodes ----------
const wkey = () => 'vf_watch_' + pid();
export function loadWatches() { try { ed.watches = JSON.parse(localStorage.getItem(wkey()) || '{}'); } catch { ed.watches = {}; } ed.watchVals = {}; }
function saveWatches() { try { localStorage.setItem(wkey(), JSON.stringify(ed.watches)); } catch { /* */ } }
export const isWatched = (id: string, tag: string) => (ed.watches[id] || []).includes(tag);
export function toggleWatch(id: string, tag: string) {
  const l = ed.watches[id] || [];
  ed.watches = { ...ed.watches, [id]: l.includes(tag) ? l.filter((x) => x !== tag) : [...l, tag] };
  if (!ed.watches[id].length) { const w = { ...ed.watches }; delete w[id]; ed.watches = w; }
  saveWatches(); pollWatches();
}
export function clearWatches(id: string) { const w = { ...ed.watches }; delete w[id]; ed.watches = w; saveWatches(); }
export async function pollWatches() {
  const ids = Object.keys(ed.watches || {}).filter((id) => blocksById.value[id]);
  if (!ids.length || !pid()) return;
  const out: Record<string, Record<string, any>> = {};
  await Promise.all(ids.map(async (id) => {
    const d = await loadStation(id);
    out[id] = Object.fromEntries((ed.watches[id] || []).map((t) => [t, d?.tags?.[t]?.v]));
  }));
  ed.watchVals = out;
}
/** Watch rows shown on a node: [[tag, text]]. */
export function watchRows(id: string): [string, string][] {
  return (ed.watches?.[id] || []).map((t) => [t.split('/').pop() || t, fmt(ed.watchVals?.[id]?.[t])]);
}
export function fmt(v: any) {
  if (v === undefined || v === null) return '…';
  if (typeof v === 'number') return Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 1 ? v.toFixed(2) : v.toFixed(3);
  if (typeof v === 'boolean') return v ? '1' : '0';
  return String(v).slice(0, 16);
}

/** On breakpoint hit: select, locate, and flash (highlight in Graph / Floor Plan / 3D). */
export function showHit(id: string) { if (!blocksById.value[id]) return; select([id]); focusOn(id); flash([id], 6000); }

/** PLC block run state (Graph nodes and Architecture show RUN/STOP/breakpoint pause): ed.plcStatus[PLC ID] = {state, label, …}. */
export async function pollPlc() {
  if (!(ed.model?.blocks || []).some((b: any) => b.type === 'plc')) { ed.plcStatus = {}; return; }
  const r = await get(P(pid()) + '/plc/status', true).catch(() => null);
  const list = Array.isArray(r) ? r : r?.cells || r?.plcs || [];
  ed.plcStatus = Object.fromEntries(list.map((x: any) => [x.bid || x.id, x]));
}
let timer: any = null;
/** Called on Workbench mount: load breakpoints and watches, then start polling. */
export function startGraphDebug() {
  loadBps(); loadWatches(); pollWatches(); pollPlc();
  clearInterval(timer); timer = setInterval(() => { pollWatches(); pollPlc(); }, 2000);
  const onBp = () => loadBps();
  addEventListener('vf:breakpoints-changed', onBp);
  return () => { clearInterval(timer); removeEventListener('vf:breakpoints-changed', onBp); };
}
