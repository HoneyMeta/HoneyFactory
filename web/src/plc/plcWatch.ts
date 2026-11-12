// Plant-wide PLC monitoring: poll /api/p/<pid>/plc/status every second; emit window events on breakpoint/step halts for the shell and notification bar.
//
//   window events:
//     vf:plc-halt  detail = { pid, bid, name, line?, rung?, reason: 'breakpoint'|'step'|'scan_end', label, devices }   A PLC just paused
//     vf:plc-run   detail = { pid, bid, name, state, devices }                                                         A paused PLC resumed (or stopped/failed)
//   bid is the PLC block ID (4.3); devices contains IDs of equipment it controls via signal wires.
//   usePlcWatch(pid) → { status }   status.plcs[i] (= status.cells[i]) = { bid, name, state, label, halt, lang, bps: [{line|rung, label}], error, devices }
//   Add/remove breakpoints, resume, and step via POST /api/p/<pid>/cells/<bid>/plc {action: breakpoint|run|step, …}
import { onBeforeUnmount, reactive } from 'vue';
import { get, P, post } from '../api';

type W = { status: any; users: number; timer: any; halted: Record<string, string> };
const watchers: Record<string, W> = {};

async function tick(pid: string) {
  const w = watchers[pid];
  if (!w) return;
  try {
    if (!document.hidden) {
      const r = await get(`${P(pid)}/plc/status`, true);
      w.status.cells = r.plcs || r.cells || [];
      w.status.plcs = w.status.cells;
      w.status.halted = r.halted || [];
      w.status.at = Date.now();
      const now: Record<string, string> = {};
      for (const c of w.status.cells) {
        if (c.state === 'HALT') {
          const key = JSON.stringify(c.halt || {});
          now[c.bid] = key;
          if (w.halted[c.bid] !== key) {
            window.dispatchEvent(new CustomEvent('vf:plc-halt', { detail: { pid, bid: c.bid, name: c.name, label: c.label, devices: c.devices || [], ...(c.halt || {}) } }));
          }
        } else if (w.halted[c.bid]) {
          window.dispatchEvent(new CustomEvent('vf:plc-run', { detail: { pid, bid: c.bid, name: c.name, state: c.state, devices: c.devices || [] } }));
        }
      }
      w.halted = now;
    }
  } catch { /* Factory unavailable or not logged in */ }
  if (watchers[pid]) w.timer = setTimeout(() => tick(pid), 1000);
}

/** Call in a component to monitor this factory's PLCs while mounted. */
export function usePlcWatch(pid: string) {
  let w = watchers[pid];
  if (!w) {
    w = watchers[pid] = { status: reactive({ cells: [] as any[], plcs: [] as any[], halted: [] as any[], at: 0 }), users: 0, timer: null, halted: {} };
    w.timer = setTimeout(() => tick(pid), 50);
  }
  w.users++;
  onBeforeUnmount(() => {
    w.users--;
    if (w.users <= 0) { clearTimeout(w.timer); delete watchers[pid]; }
  });
  return { status: w.status, refresh: () => tick(pid) };
}

export async function plcAct(pid: string, bid: string, body: any) {
  const r = await post(`${P(pid)}/cells/${encodeURIComponent(bid)}/plc`, body);
  const w = watchers[pid];
  if (w) { clearTimeout(w.timer); tick(pid); }
  return r;
}
