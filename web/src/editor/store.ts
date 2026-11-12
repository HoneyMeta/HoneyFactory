// Editor state and command bus: all changes (UI actions, AI changesets) use exec(ops) for unified undo/redo and draft autosave.
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, h, reactive } from 'vue';
import { canEdit, get, P, post, put } from '../api';

export type Op = { op: string; [k: string]: any };
const clone = (x: any) => JSON.parse(JSON.stringify(x));

function setPath(obj: any, path: string, value: any) {
  const ks = path.split('.');
  for (const k of ks.slice(0, -1)) obj = obj[k] ??= {};
  const last = ks[ks.length - 1];
  const old = obj[last];
  if (value === null || value === undefined) delete obj[last]; else obj[last] = clone(value);
  return old === undefined ? null : clone(old);
}

/** Matches apply_ops in backend flow/model.py; modifies model in place and returns inverse commands. */
export function applyOps(m: any, ops: Op[]): Op[] {
  const inv: Op[] = [];
  const find = (coll: string, id: string) => (m[coll] || []).find((x: any) => x.id === id);
  for (const o of ops) {
    if (o.op === 'add_block') { (m.blocks ||= []).push(clone(o.block)); inv.unshift({ op: 'remove_block', id: o.block.id }); }
    else if (o.op === 'remove_block') {
      const b = find('blocks', o.id); if (!b) continue;
      const gone = (m.links || []).filter((l: any) => [l.from, l.to, l.via].includes(o.id));
      m.links = (m.links || []).filter((l: any) => !gone.includes(l));
      m.blocks = m.blocks.filter((x: any) => x.id !== o.id);
      inv.unshift({ op: 'add_block', block: b }); gone.forEach((l: any) => inv.splice(1, 0, { op: 'add_link', link: l }));
    } else if (['update_block', 'update_link', 'update_group', 'update_note'].includes(o.op)) {
      const coll = { update_block: 'blocks', update_link: 'links', update_group: 'groups', update_note: 'notes' }[o.op]!;
      const x = find(coll, o.id); if (!x) continue;
      const old: any = {};
      for (const [p, v] of Object.entries(o.set)) old[p] = setPath(x, p, v);
      inv.unshift({ op: o.op, id: o.id, set: old });
    } else if (o.op === 'add_link') { (m.links ||= []).push(clone(o.link)); inv.unshift({ op: 'remove_link', id: o.link.id }); }
    else if (o.op === 'remove_link') { const l = find('links', o.id); if (l) { m.links = m.links.filter((x: any) => x.id !== o.id); inv.unshift({ op: 'add_link', link: l }); } }
    else if (o.op === 'add_group') { (m.groups ||= []).push(clone(o.group)); inv.unshift({ op: 'remove_group', id: o.group.id }); }
    else if (o.op === 'remove_group') { const g = find('groups', o.id); if (g) { m.groups = m.groups.filter((x: any) => x.id !== o.id); inv.unshift({ op: 'add_group', group: g }); } }
    else if (o.op === 'add_note') { (m.notes ||= []).push(clone(o.note)); inv.unshift({ op: 'remove_note', id: o.note.id }); }
    else if (o.op === 'remove_note') { const g = find('notes', o.id); if (g) { m.notes = m.notes.filter((x: any) => x.id !== o.id); inv.unshift({ op: 'add_note', note: g }); } }
    else if (o.op === 'update_plant') { const old: any = {}; for (const [p, v] of Object.entries(o.set)) old[p] = setPath(m, p, v); inv.unshift({ op: 'update_plant', set: old }); }
    else if (o.op === 'replace_model') { const prev = clone(m); for (const k of Object.keys(m)) delete m[k]; Object.assign(m, clone(o.model)); inv.unshift({ op: 'replace_model', model: prev }); }
  }
  return inv;
}

export function describeOp(o: Op, cat: any, m: any): string {
  const nm = (id: string) => (m.blocks || []).find((b: any) => b.id === id)?.name || id;
  if (o.op === 'add_block') return $t('store.add012', [cat?.types[o.block.type]?.label || o.block.type, o.block.name || o.block.id, o.block.id]);
  if (o.op === 'remove_block') return $t('store.delete0', [nm(o.id)]);
  if (o.op === 'update_block') return $t('store.edit0', [nm(o.id)]) + Object.entries(o.set).map(([k, v]) => `${k} = ${typeof v === 'object' ? JSON.stringify(v).slice(0, 60) : v}`).join($t('common.k344'));
  if (o.op === 'add_link') return $t('store.connect012', [nm(o.link.from), nm(o.link.to), o.link.via ? $t('store.transportedBy0', [nm(o.link.via)]) : '']);
  if (o.op === 'remove_link') return $t('store.deleteConnection0', [o.id]);
  if (o.op === 'update_link') return $t('store.editConnection0', [o.id]) + Object.entries(o.set).map(([k, v]) => `${k} = ${v}`).join($t('common.k344'));
  if (o.op === 'update_plant') return $t('store.editFactoryProperties') + Object.keys(o.set).join($t('common.k360'));
  return o.op;
}

export const ed = reactive<any>({
  pid: '', model: null as any, cat: null as any, sel: [] as string[], selLink: '' as string, undo: [] as any[], redo: [] as any[],
  validation: null as any, changes: [] as any[], saving: false, savedAt: '', runtime: null as any, view: '3d', highlight: [] as string[],
  clipboard: null as any, aiOpen: true, aiSeed: '', cursor: [0, 0] as number[],
  focusReq: null as any, overlay: true, chat: [] as any[], bottom: 'timeline', tryrun: null as any,
  live: [] as any[], structural: false, replay: null as any, split: false, rightTab: 'props', lastHit: 0,
  floats: [] as any[], workspace: localStorage.getItem('vf_ws') || 'all', leftPanel: '', leftOpen: true,
  // Graph-centric (4.1): placement mode, graph selection, breakpoints, watches
  placing: null as null | { type: string; label: string },
  pick: null as null | { prompt: string; kinds?: string[]; onPick: (id: string) => void },
  bps: [] as any[], watches: {} as Record<string, string[]>, watchVals: {} as Record<string, Record<string, any>>,
  // 4.3: layer filters (read/written by shell/relations.ts), navigation history counters, hovered object (relation highlighting), simple/expert modes
  filter: (() => { try { return JSON.parse(localStorage.getItem('vf_filter') || 'null'); } catch { return null; } })()
    || { layers: { process: true, control: true, network: true, it: true }, links: { material: true, signal: true, network: true } },
  navTick: 0, hoverId: '' as string, expert: (() => { try { return localStorage.getItem('vf_expert') === '1'; } catch { return false; } })(),
  // 4.7 small screens: collapsible right sidebar, hideable bottom timeline (persisted)
  rightOpen: (() => { try { return localStorage.getItem('vf_right_open') !== '0'; } catch { return true; } })(),
  tlOpen: (() => { try { return localStorage.getItem('vf_tl_open') !== '0'; } catch { return true; } })(),
});
/** 4.7: collapse/expand right sidebar, hide/show timeline (persist choices). */
export function setRightOpen(v: boolean) { ed.rightOpen = v; try { localStorage.setItem('vf_right_open', v ? '1' : '0'); } catch { /* */ } }
export function setTimelineOpen(v: boolean) { ed.tlOpen = v; try { localStorage.setItem('vf_tl_open', v ? '1' : '0'); } catch { /* */ } }
(window as any).__vfEd = ed;   // For UI tests (read/write editor state)
/** Run state: running / paused / edit (reset) / replay. */
export const mode = computed(() => (ed.replay ? 'replay' : ed.runtime?.ctl?.mode || 'running'));
/** View state overlay: snapshot during replay, live state otherwise. */
export const viewState = computed(() => ed.replay?.data || ed.runtime);
export const blocksById = computed(() => Object.fromEntries((ed.model?.blocks || []).map((b: any) => [b.id, b])));
export const selBlocks = computed(() => ed.sel.map((id: string) => blocksById.value[id]).filter(Boolean));

let timer: any = null;
export async function loadModel(pid: string) {
  ed.pid = pid; ed.undo = []; ed.redo = []; ed.sel = []; ed.selLink = '';
  ed.cat ||= await get('/api/catalog');
  const r = await get(P(pid) + '/model');
  ed.model = r.model; ed.validation = r.validation; setState(r); ed.savedAt = r.draft_saved || '';
}
function setState(r: any) { ed.changes = r.running_changes || []; ed.live = r.live_changes || []; ed.structural = !!r.structural; }
export function scheduleSave() {
  clearTimeout(timer);
  timer = setTimeout(saveDraft, 700);
}
export async function saveDraft() {
  if (!ed.model) return;
  ed.saving = true;
  try {
    const r = await put(P(ed.pid) + '/model', { model: ed.model });
    ed.validation = r.validation; setState(r); ed.savedAt = new Date().toTimeString().slice(0, 8);
    // Apply parameter/position changes to the running factory immediately (like editing properties while paused in UE); rebuild structural changes on "Run"
    if (!r.structural && r.validation.ok && canEdit()) setState(await post(P(ed.pid) + '/model/hot', { model: ed.model }));
  } finally { ed.saving = false; }
}
/** Auto-pause when editing starts (return to live mode first if replaying). */
export async function pauseForEdit() {
  if (ed.replay) ed.replay = null;
  if (mode.value === 'running' && canEdit()) {
    await post(P(ed.pid) + '/ctl', { action: 'pause' });
    if (ed.runtime?.ctl) ed.runtime.ctl.mode = 'paused';
    ElMessage.info($t('store.pausedForEditing'));
  }
}
export const ctl = (action: string, extra: any = {}) => post(P(ed.pid) + '/ctl', { action, ...extra });
export function exec(ops: Op[], label = '') {
  if (!ops.length) return;
  if (!canEdit()) { ElMessage.info($t('place.viewOnlyEditingIsDisabled')); return; }
  if (ed.modelLocked && ops.some((o: any) => o.op !== 'update_plant' || !Object.keys(o.set || {}).every((k) => k.startsWith('plant.cameras')))) { ElMessage.info($t('details.onlyThePlcProgramCan')); return; }
  pauseForEdit();
  const inv = applyOps(ed.model, ops);
  ed.undo.push({ ops, inv, label }); ed.redo = [];
  if (ed.undo.length > 300) ed.undo.shift();
  scheduleSave();
}
export function undo() {
  const h = ed.undo.pop(); if (!h) return;
  applyOps(ed.model, h.inv); ed.redo.push(h); scheduleSave(); ElMessage.info($t('store.undo') + (h.label || $t('common.edit2')));
}
export function redo() {
  const h = ed.redo.pop(); if (!h) return;
  h.inv = applyOps(ed.model, h.ops); ed.undo.push(h); scheduleSave();
}

export function newId(prefix: string, extra: string[] = []) {
  const used = new Set([...(ed.model.blocks || []).map((b: any) => b.id), ...(ed.model.links || []).map((l: any) => l.id),
    ...(ed.model.groups || []).map((g: any) => g.id), ...(ed.model.notes || []).map((g: any) => g.id), ...extra]);
  let n = 1; while (used.has(`${prefix}${n}`)) n++;
  return `${prefix}${n}`;
}

/** Find free space: move down to avoid overlapping graph cards or equipment footprints in the floor plan. */
export function freeNode(node: number[], skip = '') {
  const n = [...node];
  for (let i = 0; i < 40; i++) {
    if (!(ed.model.blocks || []).some((b: any) => b.id !== skip && Math.abs((b.node?.[0] || 0) - n[0]) < 200 && Math.abs((b.node?.[1] || 0) - n[1]) < 120)) break;
    n[1] += 150;
  }
  return n;
}
export function freePos(pos: number[], size: number[], skip = '') {
  const p = [...pos];
  for (let i = 0; i < 40; i++) {
    if (!(ed.model.blocks || []).some((b: any) => b.id !== skip && b.type !== 'transporter' && b.type !== 'operators'
      && Math.abs(b.pos[0] - p[0]) < (b.size[0] + size[0]) / 2 + 0.5 && Math.abs(b.pos[1] - p[1]) < (b.size[1] + size[1]) / 2 + 0.5)) break;
    p[1] += size[1] + 1.5;
  }
  return p;
}

export function makeBlock(type: string, pos: number[], node: number[]) {
  const t = ed.cat.types[type];
  node = freeNode(node);
  if (!['transporter', 'operators'].includes(type)) pos = freePos(pos, t.size);
  const id = newId(ed.cat.prefix[type] || 'X');
  const params: any = {};
  for (const [k, p] of Object.entries(t.params) as any) if (p.default !== undefined && p.default !== null && p.default !== '') params[k] = clone(p.default);
  if (params.modbus_unit) {
    const used = new Set((ed.model.blocks || []).map((b: any) => b.params?.modbus_unit).filter(Boolean));
    let u = 1; while (used.has(u) || u === 10) u++; params.modbus_unit = u;
  }
  return { id, type, name: `${t.label.replace(/\s*[\uff08(][^\uff09)]*[\uff09)]/, '')} ${id}`, pos: pos.map((v) => Math.round(v * 2) / 2), size: [...t.size], rot: 0, node: node.map(Math.round), params };
}

/** Copy selected blocks and their connections, reassign IDs, and return a new command (paste / duplicate / insert template). */
export function cloneOps(blocks: any[], links: any[], dpos = [3, 3], dnode = [40, 40]): { ops: Op[]; ids: string[] } {
  const map: Record<string, string> = {}, ops: Op[] = [], taken: string[] = [];
  for (const b of blocks) {
    const prefix = (b.id.match(/^[A-Za-z_]+/) || ['X'])[0];
    const nid = newId(prefix, taken); taken.push(nid); map[b.id] = nid;
    const nb = clone(b); nb.id = nid; nb.name = (b.name || '').replace(b.id, nid) || nid;
    nb.pos = [b.pos[0] + dpos[0], b.pos[1] + dpos[1]]; nb.node = [(b.node?.[0] || 0) + dnode[0], (b.node?.[1] || 0) + dnode[1]];
    ops.push({ op: 'add_block', block: nb });
  }
  for (const l of links) {
    if (!map[l.from] || !map[l.to]) continue;
    const id = newId('L', taken); taken.push(id);
    ops.push({ op: 'add_link', link: { ...clone(l), id, from: map[l.from], to: map[l.to] } });
  }
  return { ops, ids: Object.values(map) };
}
export function select(ids: string[], add = false) {
  ed.selLink = '';
  ed.sel = add ? [...new Set([...ed.sel, ...ids])] : ids;
}
export function areaOf(pos: number[]) { return (ed.model.areas || []).find((a: any) => a.x[0] <= pos[0] && pos[0] < a.x[1])?.name || ''; }

export const STATE_CN: Record<string, string> = { Executing: $t('common.running'), Idle: $t('common.idle'), Starved: $t('common.materialShortage'), Blocked: $t('common.blocked'), Setup: $t('common.changeover'), Stopped: $t('common.down'), Planned: $t('store.plannedStop'), Moving: $t('view3DHover.traveling'), WaitPLC: $t('store.waitingForPlc') };
/** Status colors: match HoneyMOM's five status colors (running / idle / stopped / changeover); use similar but distinct colors for starved, blocked, planned stops, and waiting for PLC. */
export const STATE_COLOR: Record<string, string> = { Executing: '#15a34a', Idle: '#d99a16', Starved: '#c7a12a', Blocked: '#8e5bd1', Setup: '#1463d6', Stopped: '#dc2b2b', Planned: '#7d7aa8', WaitPLC: '#d9822b' };
export const PORT_CN: Record<string, string> = { in: $t('common.in'), out: $t('common.out'), ng: 'NG', melt: $t('store.iron'), ladle: $t('common.ladle'), sand: $t('store.sand'), mold: $t('store.sandMold') };
export const rtById = computed<Record<string, any>>(() => Object.fromEntries((viewState.value?.stations || []).map((s: any) => [s.id, s])));
export const typeOf = (b: any) => ed.cat?.types[b?.type] || { label: b?.type, icon: 'Box', color: '#888', in: [], out: [], params: {}, size: [4, 4] };

/** Ask each view to center the specified object. */
export function focusOn(id: string, keepZoom = false) { ed.focusReq = { id, keepZoom, n: (ed.focusReq?.n || 0) + 1 }; }

/** For a block dropped in the graph, place its floor plan footprint beside the nearest block in the graph. */
export function planPosNear(node: number[]) {
  const bs = ed.model.blocks || [];
  if (!bs.length) return [10, 10];
  const near = bs.reduce((a: any, b: any) => (dist(b.node, node) < dist(a.node, node) ? b : a));
  const dx = (node[0] - (near.node?.[0] || 0)) / 50, dy = (node[1] - (near.node?.[1] || 0)) / 50;
  return [near.pos[0] + Math.max(-12, Math.min(12, dx)), near.pos[1] + Math.max(-12, Math.min(12, dy)) + (Math.abs(dx) < 3 && Math.abs(dy) < 3 ? near.size[1] + 2 : 0)];
}
/** For a block dropped in the floor plan, place its graph card below the nearest block's card. */
export function nodePosNear(pos: number[]) {
  const bs = ed.model.blocks || [];
  if (!bs.length) return [100, 100];
  const near = bs.reduce((a: any, b: any) => (dist(b.pos, pos) < dist(a.pos, pos) ? b : a));
  return [(near.node?.[0] || 0) + (pos[0] - near.pos[0]) * 12, (near.node?.[1] || 0) + 150];
}
const dist = (a: number[] = [0, 0], b: number[] = [0, 0]) => Math.hypot(a[0] - b[0], a[1] - b[1]);

/** Delete selected objects (blocks, connections, groups, annotations). */
export function removeSelected() {
  const ops: Op[] = [];
  if (ed.selLink) ops.push({ op: 'remove_link', id: ed.selLink });
  for (const id of ed.sel) {
    if (blocksById.value[id]) ops.push({ op: 'remove_block', id });
    else if ((ed.model.groups || []).some((g: any) => g.id === id)) {
      for (const b of ed.model.blocks.filter((x: any) => x.group === id)) ops.push({ op: 'update_block', id: b.id, set: { group: null } });
      ops.push({ op: 'remove_group', id });
    } else if ((ed.model.notes || []).some((g: any) => g.id === id)) ops.push({ op: 'remove_note', id });
  }
  if (ops.length) {
    const depth = ed.undo.length;
    exec(ops, $t('store.delete0Items', [ops.length])); ed.sel = []; ed.selLink = '';
    if (ed.undo.length > depth) {   // Notify only after actual deletion (exec rejects changes in read-only mode)
      const m = ElMessage({ type: 'info', duration: 5000, message: h('span', [$t('store.deleted') + ops.length + $t('store.items'), h('a', { style: 'cursor:pointer;color:var(--el-color-primary)', onClick: () => { undo(); m.close(); } }, $t('store.undoCtrlZ'))]) });
    }
  }
}
export function copySel() {
  const bs = selBlocks.value; if (!bs.length) return;
  const ids = new Set(bs.map((b: any) => b.id));
  ed.clipboard = { blocks: clone(bs), links: clone((ed.model.links || []).filter((l: any) => ids.has(l.from) && ids.has(l.to))) };
  try { localStorage.setItem('vf_ed_clip', JSON.stringify(ed.clipboard)); } catch { /* */ }
}
export function paste(at?: { node?: number[]; pos?: number[] }) {
  let clip = ed.clipboard;
  if (!clip) try { clip = JSON.parse(localStorage.getItem('vf_ed_clip') || 'null'); } catch { /* */ }
  if (!clip?.blocks?.length) return;
  const b0 = clip.blocks[0];
  const dnode = at?.node ? [at.node[0] - b0.node[0], at.node[1] - b0.node[1]] : [260, 0];   // No position specified: offset by one card to avoid overlapping the original
  const dpos = at?.pos ? [at.pos[0] - b0.pos[0], at.pos[1] - b0.pos[1]] : [b0.size[0] + 2, 0];
  const { ops, ids } = cloneOps(clip.blocks, clip.links, dpos, dnode);
  exec(ops, $t('store.paste0Blocks', [ids.length])); select(ids); flash(ids);
}
export function duplicateSel() { copySel(); paste(); }
export function groupSel() {
  const bs = selBlocks.value; if (bs.length < 1) return;
  const id = newId('G');
  exec([{ op: 'add_group', group: { id, name: $t('store.group0', [id.slice(1)]), color: '#3b82c4', collapsed: false } },
    ...bs.map((b: any) => ({ op: 'update_block', id: b.id, set: { group: id } }))], $t('store.createGroup'));
  ed.sel = [id];
}
export function flash(ids: string[], ms = 4000) { ed.highlight = ids; setTimeout(() => { if (ed.highlight === ids) ed.highlight = []; }, ms); }

/** Align / distribute: field='pos' for floor plan, 'node' for graph. */
export function arrange(kind: string, field: 'pos' | 'node') {
  const bs = selBlocks.value; if (bs.length < 2) return;
  const ax = ['left', 'right', 'hcenter', 'hdist'].includes(kind) ? 0 : 1;
  const half = (b: any) => (field === 'pos' ? b.size[ax] / 2 : 0);
  const v = bs.map((b: any) => b[field][ax]);
  const ops: Op[] = [];
  const setv = (b: any, x: number) => { const p = [...b[field]]; p[ax] = Math.round(x * 2) / 2; ops.push({ op: 'update_block', id: b.id, set: { [field]: p } }); };
  if (kind === 'left' || kind === 'top') { const m = Math.min(...bs.map((b: any) => b[field][ax] - half(b))); bs.forEach((b: any) => setv(b, m + half(b))); }
  else if (kind === 'right' || kind === 'bottom') { const m = Math.max(...bs.map((b: any) => b[field][ax] + half(b))); bs.forEach((b: any) => setv(b, m - half(b))); }
  else if (kind === 'hcenter' || kind === 'vcenter') { const m = v.reduce((a: number, b: number) => a + b, 0) / v.length; bs.forEach((b: any) => setv(b, m)); }
  else if (kind === 'hdist' || kind === 'vdist') {
    // Equal gaps between adjacent blocks (floor plan: footprint edges, at least 1.5 m; graph: at least one card width/height)
    if (bs.length < 2) return;
    const s = [...bs].sort((a: any, b: any) => a[field][ax] - b[field][ax]);
    const ext = (b: any) => (field === 'pos' ? b.size[ax] : ax === 0 ? 220 : 120);
    const lo = s[0][field][ax] - half(s[0]), hi = s[s.length - 1][field][ax] + half(s[s.length - 1]);
    const total = s.reduce((a: number, b: any) => a + ext(b), 0);
    const gap = Math.max(field === 'pos' ? 1.5 : 40, (hi - lo - total) / (s.length - 1));
    let x = lo;
    for (const b of s) { setv(b, x + half(b)); x += ext(b) + gap; }
  }
  exec(ops, $t('view3D.align'));
}
export async function reloadTemplates() { ed.templates = await get('/api/templates', true).catch(() => []); }

// ---------- Floating windows ----------
let floatSeq = 0;
/** Open a floating window (reuse and bring to front if the same panel and parameters are already open). */
export function openFloat(p: { id: string; title: string; icon?: string; component: any; size?: number[]; dock?: string }, props: any = {}, key = '') {
  const id = p.id + (key ? ':' + key : '');
  const z = Math.max(10, ...ed.floats.map((w: any) => w.z)) + 1;
  const old = ed.floats.find((w: any) => w.id === id);
  if (old) { old.z = z; return old; }
  let [w, h] = p.size || [520, 360];
  const n = ed.floats.length % 6;
  let x = Math.max(60, Math.min(innerWidth - w - 20, 280 + n * 28)), y = Math.max(90, Math.min(innerHeight - h - 20, 110 + n * 28));
  // dock: 'right' — occupy the right half (PLC programming: equipment motion remains visible in 3D on the left)
  if (p.dock === 'right') { w = Math.round(Math.min(w, innerWidth * 0.55)); h = innerHeight - 150; x = innerWidth - w - 12; y = 92; }
  const win = { id, title: p.title, icon: p.icon, component: p.component, props: { pid: ed.pid, ...props }, x, y, w, h, z, max: false, seq: ++floatSeq };
  ed.floats.push(win);
  return win;
}
/** 4.7 Floating window close guards (e.g., unapplied production plan changes): register floatGuards.set(windowId, callback) in the panel; returning false prevents closing. */
export const floatGuards = new Map<string, () => boolean | Promise<boolean>>();
/** Check which floating windows can close (unguarded windows always can); return their IDs. */
export async function guardFloats(ids: string[]) {
  const okIds: string[] = [];
  for (const id of ids) { const g = floatGuards.get(id); if (!g || (await g())) okIds.push(id); }
  return okIds;
}
export async function closeFloat(id: string) {
  if (!(await guardFloats([id])).length) return false;
  ed.floats = ed.floats.filter((w: any) => w.id !== id);
  return true;
}

/** Snap to adjacent equipment: edge-to-edge or center-to-center (tolerance tol meters); return the adjusted position. */
export function snapNeighbors(id: string, pos: number[], tol = 0.4) {
  const me = blocksById.value[id]; if (!me) return pos;
  const ext = (b: any) => (Math.round((b.rot || 0) / 90) % 2 ? [b.size[1], b.size[0]] : [b.size[0], b.size[1]]);
  const [w, h] = ext(me);
  let best = [tol + 1, tol + 1], shift = [0, 0];
  for (const b of ed.model.blocks || []) {
    if (b.id === id || (b.floor || 'F1') !== (me.floor || 'F1') || ['transporter', 'operators'].includes(b.type)) continue;
    const [bw, bh] = ext(b);
    for (const [ax, mine] of [[0, [pos[0] - w / 2, pos[0], pos[0] + w / 2]], [1, [pos[1] - h / 2, pos[1], pos[1] + h / 2]]] as [number, number[]][]) {
      const c = ax ? b.pos[1] : b.pos[0], half = (ax ? bh : bw) / 2;
      for (const m of mine) for (const t of [c - half, c, c + half]) {
        const d = t - m;
        if (Math.abs(d) < Math.abs(best[ax]) && Math.abs(d) <= tol) { best[ax] = d; shift[ax] = d; }
      }
    }
  }
  return [+(pos[0] + shift[0]).toFixed(2), +(pos[1] + shift[1]).toFixed(2)];
}
