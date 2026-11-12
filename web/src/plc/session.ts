// PLC programming session for one control unit: project program, compilation results, online values, undo/redo.
// Shared across panels for the same unit (programming popup, sidebar, HMI), cached by pid/bid.
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { reactive } from 'vue';
import { plcApi } from './plcApi';

export type Sess = ReturnType<typeof makeSess>;
const cache = new Map<string, Sess>();
const clone = (x: any) => JSON.parse(JSON.stringify(x));

function makeSess(pid: string, bid: string) {
  const s = reactive({
    pid, bid, loaded: false, loading: false, program: null as any, io: [] as any[], cell: null as any, mode: 'internal',
    projectHash: '', onlineHash: '' as string | null, savedProgram: '', compile: null as any, errors: [] as any[], warnings: [] as any[],
    online: null as any, monitor: true, busy: '', undo: [] as string[], redo: [] as string[], users: 0, lastPoll: 0, pollErr: '',
    sel: [] as string[], selRung: -1, clip: null as any, rev: 0,
  });
  let timer: any = null;

  const api = {
    s,
    get dirty() { return !!s.program && JSON.stringify(s.program) !== s.savedProgram; },
    get lang() { return s.program?.lang || 'LD'; },
    async load(force = false) {
      if (s.loaded && !force) return;
      s.loading = true;
      try {
        const r = await plcApi.program(pid, bid);
        s.program = normalize(r.program);
        s.savedProgram = JSON.stringify(s.program);
        s.io = r.io || []; s.cell = r.cell; s.mode = r.mode;
        s.projectHash = r.project_hash; s.onlineHash = r.online_hash;
        s.undo = []; s.redo = []; s.loaded = true; s.rev++;
      } finally { s.loading = false; }
    },
    /** Call before editing the program to record an undo step. */
    snap() {
      s.undo.push(JSON.stringify(s.program));
      if (s.undo.length > 200) s.undo.shift();
      s.redo = [];
    },
    change(fn: (p: any) => void) {
      api.snap();
      fn(s.program);
      s.rev++;
    },
    undoOne() {
      const x = s.undo.pop(); if (!x) return;
      s.redo.push(JSON.stringify(s.program)); s.program = JSON.parse(x); s.rev++;
    },
    redoOne() {
      const x = s.redo.pop(); if (!x) return;
      s.undo.push(JSON.stringify(s.program)); s.program = JSON.parse(x); s.rev++;
    },
    async save(quiet = false) {
      s.busy = 'save';
      try {
        const r = await plcApi.save(pid, bid, s.program);
        s.savedProgram = JSON.stringify(s.program); s.projectHash = r.project_hash;
        if (!quiet) ElMessage.success($t('common.saved'));
      } finally { s.busy = ''; }
    },
    async compile() {
      s.busy = 'compile';
      try {
        const r = await plcApi.compile(pid, bid, s.program);
        api.applyCompile(r);
        if (r.ok) ElMessage.success(r.warnings?.length ? $t('plcSession.compilationSucceededWith0Warnings', [r.warnings.length]) : $t('plcSession.compilationSucceeded'));
        else ElMessage.error($t('plcSession.compilationFailed0Errors', [r.errors.length]));
        return r;
      } finally { s.busy = ''; }
    },
    /** Compile without notifications (for cross references and timing charts). */
    async compileQuiet() {
      try { const r = await plcApi.compile(pid, bid, s.program); api.applyCompile(r); return r; } catch { return null; }
    },
    /** Program replaced (new/import/restore): invalidate previous compilation results. */
    clearCompile() { s.compile = null; s.errors = []; s.warnings = []; },
    applyCompile(r: any) {
      s.compile = r; s.errors = r.errors || []; s.warnings = r.warnings || [];
      if (r.source && s.program?.lang === 'LD') {
        // Write back element IDs filled in by the backend (not counted as an edit)
        const dirty = api.dirty;
        s.program.source = r.source;
        if (!dirty) s.savedProgram = JSON.stringify(s.program);
      }
    },
    async download(cold = false) {
      s.busy = 'download';
      try {
        const r = await plcApi.download(pid, bid, s.program, { cold });
        api.applyCompile(r);
        if (!r.ok) { ElMessage.error($t('plcSession.compilationFailedNotDownloaded0', [r.errors.length])); return r; }
        s.savedProgram = JSON.stringify(s.program); s.onlineHash = r.hash; s.projectHash = r.hash;
        const tail = r.state === 'STOP' ? $t('plcSession.plcIsStoppedClickRun') : '';
        ElMessage.success((cold ? $t('plcSession.downloadedColdStart') : r.kept?.length ? $t('plcSession.downloadedPreservingValuesFor0', [r.kept.length]) : $t('deliveryExport.downloaded')) + tail);
        await api.poll();
        return r;
      } finally { s.busy = ''; }
    },
    async act(body: any, quiet = false) {
      try {
        const r = await plcApi.action(pid, bid, body);
        if (s.online) Object.assign(s.online, { state: r.state, state_cn: r.state_cn, halt: r.halt, bps: r.bps, error: r.error, forced: r.forced });
        api.poll();
        return r;
      } catch (e: any) { if (!quiet) throw e; }
    },
    async poll() {
      try {
        const r = await plcApi.online(pid, bid, s.program?.lang !== 'ST');
        s.online = r; s.lastPoll = Date.now(); s.pollErr = '';
        if (r.hash !== undefined) s.onlineHash = r.hash;
      } catch (e: any) { s.pollErr = e?.message || $t('plcSession.failedToReadOnlineValues'); }
    },
    /** Increment on panel mount, decrement on unmount; poll online values while in use. */
    use() {
      s.users++;
      if (!timer) {
        const tick = async () => {
          if (s.monitor && !document.hidden) await api.poll();
          timer = setTimeout(tick, s.online?.state === 'RUN' ? 250 : 600);
        };
        timer = setTimeout(tick, 50);
      }
      return () => {
        s.users--;
        if (s.users <= 0 && timer) { clearTimeout(timer); timer = null; }
      };
    },
    /** All available symbols (variable table + I/O + auto-declarations + function block members) for autocomplete. */
    symbols() {
      const out: { name: string; type: string; info: string }[] = [];
      const seen = new Set<string>();
      const add = (name: string, type: string, info: string) => { const k = name.toUpperCase(); if (!seen.has(k)) { seen.add(k); out.push({ name, type, info }); } };
      for (const e of s.io) add(e.name, e.type || 'BOOL', `${e.dir === 'in' ? $t('common.input') : $t('common.output')} ${e.addr || ''} ${e.comment || ''}`.trim());
      for (const v of s.program?.vars || []) if (v.name) add(v.name, v.type, `${v.addr || ''} ${v.comment || ''}`.trim());
      for (const v of s.compile?.symbols || []) add(v.name, v.type, v.comment || '');
      for (const v of [...out]) {
        const fb = FB_MEMBERS[v.type];
        if (fb) for (const m of fb) add(`${v.name}.${m}`, MEMBER_T[m] || 'BOOL', $t('plcSession.n1Of0', [v.type, m]));
      }
      return out;
    },
    typeOf(name: string) {
      const up = String(name || '').toUpperCase();
      return api.symbols().find((x) => x.name.toUpperCase() === up)?.type;
    },
  };
  return api;
}

const FB_MEMBERS: Record<string, string[]> = { TON: ['Q', 'ET', 'IN', 'PT'], TOF: ['Q', 'ET', 'IN', 'PT'], TP: ['Q', 'ET', 'IN', 'PT'], CTU: ['Q', 'CV', 'PV'],
  CTD: ['Q', 'CV', 'PV'], CTUD: ['QU', 'QD', 'CV', 'PV'], R_TRIG: ['Q'], F_TRIG: ['Q'], SR: ['Q1'], RS: ['Q1'] };
const MEMBER_T: Record<string, string> = { Q: 'BOOL', ET: 'TIME', PT: 'TIME', IN: 'BOOL', CV: 'INT', PV: 'INT', QU: 'BOOL', QD: 'BOOL', Q1: 'BOOL' };

export function normalize(p: any) {
  p = clone(p || {});
  p.lang = (p.lang || 'LD').toUpperCase();
  p.vars ||= [];
  if (p.lang === 'LD') {
    if (typeof p.source === 'string') { try { p.source = JSON.parse(p.source); } catch { p.source = { rungs: [] }; } }
    p.source ||= { rungs: [] };
    p.source.rungs ||= [];
    if (!p.source.rungs.length) p.source.rungs.push({ comment: '', elements: [] });
    let n = 0;
    const fix = (x: any) => {
      if (Array.isArray(x)) x.forEach(fix);
      else if (x && x.par) x.par.forEach(fix);
      else if (x && x.ser) fix(x.ser);
      else if (x) {
        if (!x.id) x.id = 'e' + Date.now().toString(36) + (n++);
        if (x.t === false) x.t = 'NO';             // Unquoted NO in handwritten YAML becomes false
        else if (typeof x.t === 'string') x.t = ({ CONTACT: 'NO', RISING: 'P', FALLING: 'N' } as any)[x.t.toUpperCase()] || x.t.toUpperCase();
      }
    };
    p.source.rungs.forEach((r: any) => fix(r.elements));
  } else if (typeof p.source !== 'string') p.source = '';
  return p;
}

export function useSession(pid: string, bid: string): Sess {
  const k = pid + '/' + bid;
  let s = cache.get(k);
  if (!s) { s = makeSess(pid, bid); cache.set(k, s); }
  return s;
}
