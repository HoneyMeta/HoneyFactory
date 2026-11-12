// Live control/communication layer status shared by Floor Plan and Architecture: PLC status (/plc/status) and architecture data (/architecture, provided by assistant P).
// Poll only while views are using this (reference counted); silently ignore missing endpoints or errors.
import { $t } from '../../i18n';
import { reactive } from 'vue';
import { get, P } from '../../api';
import { ed } from '../store';

export const live = reactive<{ plc: Record<string, any>; nodes: Record<string, any>; links: Record<string, any>; at: number }>({ plc: {}, nodes: {}, links: {}, at: 0 });
let users = 0, timer: any = null;

/** Normalize PLC status: run = running / halt = paused at breakpoint / stop = stopped / fault = faulted / '' = unknown. */
export function plcState(id: string) {
  const s = String(live.plc[id]?.state || live.nodes[id]?.plc || '').toUpperCase();
  if (!s) return '';
  if (s.includes('HALT') || s.includes('BREAK')) return 'halt';
  if (s.includes('RUN')) return 'run';
  if (s.includes('FAULT') || s.includes('ERR')) return 'fault';
  return 'stop';
}
export const PLC_CN: Record<string, string> = { run: $t('common.running'), halt: $t('live.pausedAtBreakpoint'), stop: $t('common.stop'), fault: $t('common.fault') };

/** Architecture node status: accept several formats ({nodes:[{id,…}]} / {nodes:{id:{…}}} / {blocks:[…]}). */
function byId(x: any): Record<string, any> {
  if (!x) return {};
  if (Array.isArray(x)) return Object.fromEntries(x.filter((n: any) => n && (n.id || n.bid)).map((n: any) => [n.id || n.bid, n]));
  if (typeof x === 'object') return x;
  return {};
}
async function poll() {
  if (!ed.pid || ed.replay) return;
  const pid = ed.pid;
  const hasPlc = (ed.model?.blocks || []).some((b: any) => b.type === 'plc' || b.type === 'cell');
  if (hasPlc) {
    const r = await get(P(pid) + '/plc/status', true).catch(() => null);
    if (r && pid === ed.pid) live.plc = byId(r.cells || r.plcs || r);
  }
  const a = await get(P(pid) + '/architecture', true).catch(() => null);
  if (a && pid === ed.pid) { live.nodes = byId(a.nodes || a.blocks); live.links = byId(a.links || a.edges); }
  live.at = Date.now();
}
export function useLive() {
  users++;
  if (!timer) { poll(); timer = setInterval(poll, 2500); }
  return () => { users--; if (users <= 0) { users = 0; clearInterval(timer); timer = null; } };
}
/** One-line node/link online status summary (shown if provided by the architecture API). */
export function nodeStatus(id: string): { text: string; cls: string } | null {
  const n = live.nodes[id]; if (!n) return null;
  const st = String(n.status ?? n.state ?? (n.online === false ? 'offline' : n.online ? 'online' : '')).toLowerCase();
  const clients = n.clients ?? n.sessions ?? n.mes?.clients;
  const map: Record<string, [string, string]> = { online: [$t('common.online'), 'ok'], ok: [$t('common.normal'), 'ok'], connected: [$t('common.connected'), 'ok'], running: [$t('common.running'), 'ok'], offline: [$t('common.offline'), 'bad'],
    disconnected: [$t('common.disconnected'), 'bad'], fault: [$t('common.fault'), 'bad'], error: [$t('common.error'), 'bad'], idle: [$t('common.idle2'), 'mu'], degraded: [$t('common.abnormal'), 'warn'], waiting: [$t('common.waiting'), 'warn'], down: [$t('common.offline'), 'bad'] };
  const m = map[st];
  const text = [m ? m[0] : st || '', clients !== undefined ? $t('live.clients0', [clients]) : '', n.label || n.msg || ''].filter(Boolean).join(' · ');
  return text ? { text, cls: m ? m[1] : 'mu' } : null;
}
export function linkFault(l: any): string {
  const f = live.links[l.id]?.fault || l.fault;
  if (!f) return '';
  const mode = typeof f === 'string' ? f : f.mode;
  return ({ disconnect: $t('common.disconnected'), delay: $t('live.latency'), latency: $t('live.latency'), jitter: $t('live.jitter'), loss: $t('live.packetLoss'), drop: $t('live.packetLoss'), bad: $t('live.badQuality'), bad_quality: $t('live.badQuality'), freeze: $t('common.held') } as any)[mode] || mode || $t('common.fault');
}
