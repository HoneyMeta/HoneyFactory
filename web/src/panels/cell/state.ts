// Shared control cell editor state: component catalog, current cell / component selection, and commits (undoable via the Workbench command bus).
import { $t } from '../../i18n';
import { computed, markRaw, reactive, watch } from 'vue';
import { canEdit, get, P, post, put, session } from '../../api';
import { blocksById, ed, exec, openFloat, rtById } from '../../editor/store';
import { setDraftLookup } from '../../scene_ext/cell';

// bid: current control cell; dev: regular equipment in the interior view (shows its control I/O panel when not a control cell)
export const cs = reactive<any>({ cat: null as any, bid: '', dev: '', comp: '', tool: '', io: null as any, issues: [] as any[], busy: false });

// Render 3D from the draft cell definition (including unapplied changes)
setDraftLookup((pid: string, bid: string) => (pid && pid === ed.pid ? blocksById.value[bid]?.params?.cell : null) || null);

export async function loadCat() {
  if (!cs.cat) cs.cat = await get('/api/cells/catalog', true).catch(() => null);
  return cs.cat;
}

export const cellBlocks = computed(() => (ed.model?.blocks || []).filter((b: any) => b.type === 'cell'));
export const curBlock = computed(() => (cs.bid ? blocksById.value[cs.bid] : null));
export const curCell = computed<any>(() => curBlock.value?.params?.cell || null);
export const curLive = computed<any>(() => (cs.bid ? rtById.value[cs.bid]?.cell : null) || null);
export const curComp = computed<any>(() => (curCell.value?.components || []).find((c: any) => c.id === cs.comp) || null);

/** Students: cell structure (components, I/O table, PLC mode) is read-only; hide fault injection. Panel buttons, force, and reset remain available. */
export const isStudent = () => session.user?.role === 'student';
export const canEditCell = () => canEdit() && !isStudent();
export const canFault = () => canEdit() && !isStudent();

export const clone = (x: any) => JSON.parse(JSON.stringify(x ?? null));
export const typeOf = (t: string) => cs.cat?.types?.[t] || { label: t, params: {}, size: [0.5, 0.5], cat: '' };
export const labelOf = (c: any) => c?.label || c?.params?.label || typeOf(c?.type).label;

/** Regular production equipment with a control interface (the interior view shows its control tags). */
const NO_CTL = new Set(['cell', 'operators', 'transporter', 'worker_crew', 'submodel', 'plc', 'hmi', 'gateway', 'switch', 'scada', 'mes']);
export const isPlainDevice = (id: string) => { const b = blocksById.value[id]; return !!b && !NO_CTL.has(b.type); };

/** Follow the selected Workbench block: control cell → cell editor; regular production equipment → its control tags (equipment interior). The Objects panel's "Equipment Interior" button sets ed.interior. */
export function followSelection() {
  const want = [ed.interior, ...(ed.sel || [])].filter(Boolean);
  const hit = want.find((id: string) => blocksById.value[id]?.type === 'cell');
  const dev = want.find((id: string) => isPlainDevice(id));
  if (ed.interior && blocksById.value[ed.interior]) {           // Opened from the Objects panel: use its selection
    if (blocksById.value[ed.interior].type === 'cell') { if (cs.bid !== ed.interior) { cs.bid = ed.interior; cs.comp = ''; } cs.dev = ''; }
    else if (isPlainDevice(ed.interior)) cs.dev = ed.interior;
    ed.interior = '';
  } else if (hit) { if (hit !== cs.bid) { cs.bid = hit; cs.comp = ''; } cs.dev = ''; }
  else if (dev) cs.dev = dev;
  if (cs.dev && !blocksById.value[cs.dev]) cs.dev = '';
  if (!cs.bid && cellBlocks.value.length) cs.bid = cellBlocks.value[0].id;
  if (cs.bid && !blocksById.value[cs.bid]) cs.bid = cellBlocks.value[0]?.id || '';
}

/** Commit the cell definition to the model (draft, undoable); update the I/O table when components change, preserving existing names and addresses. */
export async function commit(cell: any, label = $t('cellState.editControlCell'), regenIo = true) {
  if (!cs.bid || !canEditCell()) return;
  const c = clone(cell);
  if (regenIo) {
    try { c.io = (await post('/api/cells/auto_io', { cell: c, keep: true })).io; } catch { /* Keep the original table */ }
  }
  exec([{ op: 'update_block', id: cs.bid, set: { 'params.cell': c } }, ...signalSyncOps(cs.bid, curCell.value, c)], label);
  validate(c);
}

/** Signal wire channel format (omit %, remove X from bit addresses): %IX0.0 → I0.0, %QW64 → QW64. */
export function chOf(addr?: string) {
  const a = String(addr || '').trim().replace(/^%/, '').toUpperCase();
  const m = /^([IQM])X?(\d+\.\d+)$/.exec(a);
  return m ? m[1] + m[2] : a;
}

/** When the cell I/O table changes (components added, names or addresses changed), update connected signal wires: remove deleted tags;
 *  replace channels still using auto-filled old addresses with new addresses; add new tags to all-I/O wires (all_io, generated during migration/creation). */
export function signalSyncOps(bid: string, oldCell: any, cell: any) {
  const ops: any[] = [];
  const io: any[] = cell?.io || [];
  const byName = new Map(io.map((e: any) => [e.name, e]));
  const oldAddr = new Map((oldCell?.io || []).map((e: any) => [e.name, e.addr]));
  // Rename: the I/O name for the same component signal has changed
  const ren = new Map<string, string>();
  for (const o of oldCell?.io || []) {
    const n = io.find((e: any) => e.comp === o.comp && e.signal === o.signal);
    if (n && n.name !== o.name) ren.set(o.name, n.name);
  }
  for (const l of ed.model?.links || []) {
    if ((l.kind || 'material') !== 'signal' || (l.from !== bid && l.to !== bid)) continue;
    const sigs: any[] = [];
    for (const s0 of l.signals || []) {
      const s = { ...s0, point: ren.get(s0.point) || s0.point };
      const e = byName.get(s.point);
      if (!e) continue;
      if (!s.ch || s.ch === chOf(oldAddr.get(s0.point) as string)) s.ch = chOf(e.addr) || s.point;
      s.dir = e.dir || s.dir;
      sigs.push(s);
    }
    if (l.all_io) for (const e of io) if (e.name && !sigs.some((s) => s.point === e.name)) sigs.push({ point: e.name, ch: chOf(e.addr) || e.name, dir: e.dir || 'in' });
    if (JSON.stringify(sigs) !== JSON.stringify(l.signals || [])) ops.push({ op: 'update_link', id: l.id, set: { signals: sigs } });
  }
  return ops;
}

let vt: any = null;
export function validate(cell: any) {
  if (!canEditCell()) { cs.issues = []; return; }        // Skip inspection API calls for students (read-only display)
  clearTimeout(vt);
  vt = setTimeout(async () => { try { cs.issues = (await post('/api/cells/validate', { cell })).issues; } catch { /* */ } }, 300);
}

export function newCompId(cell: any, type: string) {
  const pre = cs.cat?.prefix?.[type] || 'X';
  const used = new Set((cell.components || []).map((c: any) => c.id));
  let n = 1; while (used.has(pre + n)) n++;
  return pre + n;
}

export function defaultComp(type: string, id: string, pos: number[]) {
  const t = typeOf(type);
  const z: Record<string, number> = { diffuse_sensor: 0.35, retro_sensor: 0.35, capacitive: 0.32, inductive: 0.32, vision_sensor: 0.9, height_sensor: 0.9,
    pusher: 0.35, pivot_arm: 0.33, emitter: 0.27, cell_entry: 0.27, button: 0.95, switch: 0.95, estop: 0.95, lamp: 0.95, display: 0.95, potentiometer: 0.95,
    encoder: 0.27, gripper: 0.35 };
  return { id, type, pos: [round(pos[0]), round(pos[1]), z[type] ?? 0], rot: 0, size: [...(t.size || [0.5, 0.5])], params: {} };
}
export const round = (v: number, s = 0.05) => +(Math.round(v / s) * s).toFixed(3);

/** Component signal → I/O row. */
export function ioOf(cell: any, compId: string) { return (cell?.io || []).filter((e: any) => e.comp === compId); }

// ---------------- Running cell (live API) ----------------
export async function applyLive(pid: string) {
  if (!cs.bid || !curCell.value) return;
  cs.busy = true;
  try { await put(P(pid) + `/cells/${cs.bid}`, { cell: clone(curCell.value) }); } finally { cs.busy = false; }
}
export const force = (pid: string, name: string, value: any) => post(P(pid) + `/cells/${cs.bid}/io/force`, { name, value });
export const press = (pid: string, comp: string, action = 'press', value: any = null) => post(P(pid) + `/cells/${cs.bid}/panel`, { comp, action, value, hold: 0.4 });
export async function pollIo(pid: string) {
  if (!cs.bid) return null;
  try { cs.io = await get(P(pid) + `/cells/${cs.bid}/io`, true); } catch { cs.io = null; }
  return cs.io;
}

// ---------------- Students entering a control cell sandbox: open the console at the canvas bottom right by default ----------------
const consoleShown = new Set<string>();
export function openConsole(force = false) {
  if (!ed.pid || !cellBlocks.value.length) return;
  if (!force && consoleShown.has(ed.pid)) return;
  consoleShown.add(ed.pid);
  import('./CellConsole.vue').then((m) => {
    const size = [600, 470];
    openFloat({ id: 'cell-console', title: $t('common.operatorPanel'), icon: 'Operation', component: markRaw(m.default), size });
    const w = (ed.floats || []).find((x: any) => x.id === 'cell-console');
    if (w) { w.x = Math.max(60, innerWidth - size[0] - 360); w.y = Math.max(90, innerHeight - size[1] - 150); }
  });
}
watch(() => [ed.pid, cellBlocks.value.length, session.user?.role], () => {
  if (session.user?.role === 'student' && String(ed.pid || '').startsWith('sb-') && cellBlocks.value.length) openConsole();
});
