// 4.5 Coach data (backend vfactory/teach/coach.py): run logs, live checklist, diagnostics, automated test prechecks.
// Share one polling loop per factory across the console, task panel, PLC editor, and guided tutorials (cached by pid, polled only while in use, with incremental log fetching).
//   const c = useCoach(pid)       In components: poll while mounted; c.s.entries / c.s.checklist / c.s.state / c.s.diag / c.s.auto
//   coachOf(pid)                  Read current data without mounting (for the tutorial engine)
import { $t } from '../../i18n';
import { onBeforeUnmount, reactive } from 'vue';
import { get, P, post } from '../../api';

export type Entry = { seq: number; t: number | null; wall: number; k: string; msg: string; [k: string]: any };
const MAX = 800;
type C = ReturnType<typeof make>;
const cache = new Map<string, C>();

function make(pid: string) {
  const s = reactive({
    pid, seq: 0, entries: [] as Entry[], checklist: null as any, state: null as any, diag: null as any, auto: null as any, autoBusy: false,
    scene: null as string | null, err: '', at: 0, users: 0, cleared: 0,
  });
  let timer: any = null;
  let busy = false;
  const api = {
    s,
    async poll() {
      if (busy) return;
      busy = true;
      try {
        const r = await get(`${P(pid)}/coach?since=${s.seq}`, true);
        if (r.gap || (r.seq < s.seq)) s.entries = [];
        if (r.entries?.length) {
          s.entries.push(...r.entries);
          if (s.entries.length > MAX) s.entries.splice(0, s.entries.length - MAX);
        }
        s.seq = r.seq; s.checklist = r.checklist || null; s.state = r.state || null; s.diag = r.diag || null; s.auto = r.auto || null;
        s.autoBusy = !!r.auto_busy; s.scene = r.scene || null; s.err = ''; s.at = Date.now();
      } catch (e: any) { s.err = e?.message || $t('coach.failedToReadTheRun'); } finally { busy = false; }
    },
    use() {
      s.users++;
      if (!timer) {
        const tick = async () => {
          if (!document.hidden) await api.poll();
          timer = setTimeout(tick, s.checklist?.trial ? 400 : 700);
        };
        timer = setTimeout(tick, 30);
      }
      return () => { s.users--; if (s.users <= 0 && timer) { clearTimeout(timer); timer = null; } };
    },
    async trial(key?: string) { const r = await post(`${P(pid)}/coach/trial`, { key: key || null }); api.poll(); return r; },
    async stopTrial() { await post(`${P(pid)}/coach/stop_trial`, {}); api.poll(); },
    async autotest() { s.autoBusy = true; try { const r = await post(`${P(pid)}/coach/autotest`, {}); await api.poll(); return r; } finally { s.autoBusy = false; } },
    async clear() { await post(`${P(pid)}/coach/clear`, {}); s.entries = []; s.cleared = Date.now(); await api.poll(); },
    /** Check for a matching log entry after seq (exclusive). */
    since(seq: number, f: (e: Entry) => boolean) { return s.entries.some((e) => e.seq > seq && f(e)); },
  };
  return api;
}

export function coachOf(pid: string): C {
  let c = cache.get(pid);
  if (!c) { c = make(pid); cache.set(pid, c); }
  return c;
}

/** Call in a component to poll this factory's coach data while mounted. */
export function useCoach(pid: string): C {
  const c = coachOf(pid);
  const rel = c.use();
  onBeforeUnmount(rel);
  return c;
}

export const KIND_CN: Record<string, string> = { act: $t('common.actions'), in: $t('common.input'), out: $t('common.output'), dev: $t('common.equipment'), alarm: $t('common.alarm'), plc: 'PLC', check: $t('common.check'), diag: $t('coach.diagnostics'), info: $t('common.hint'), trial: $t('checklist.demo') };
export const FILTERS = [
  { k: 'all', label: $t('common.all'), kinds: [] as string[] },
  { k: 'act', label: $t('common.actions'), kinds: ['act', 'trial'] },
  { k: 'io', label: $t('coach.inputsOutputs'), kinds: ['in', 'out'] },
  { k: 'plc', label: 'PLC', kinds: ['plc'] },
  { k: 'check', label: $t('coach.checksDiagnostics'), kinds: ['check', 'diag'] },
  { k: 'alarm', label: $t('coach.equipmentAlarms'), kinds: ['dev', 'alarm'] },
];
export function fmtSimT(t: any) {
  if (typeof t !== 'number') return '';
  const m = Math.floor(t / 60), sec = t - m * 60;
  return `${m}:${sec.toFixed(1).padStart(4, '0')}`;
}
export function fmtWall(ms: number) {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
}
