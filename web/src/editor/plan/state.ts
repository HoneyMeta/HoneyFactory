// Floor plan editing state and layout operations (walls, zones, aisles, road networks, and annotations live in plant.layout; changes use the command bus and support undo).
// Shared by PlanView (canvas interaction), LayoutProps (layout properties in the right panel), and ArrayDialog (array duplication).
import { $t } from '../../i18n';
import { computed, reactive } from 'vue';
import { blocksById, cloneOps, ed, exec, flash, selBlocks, type Op } from '../store';
import { bbox, isClosed, remapDoors, r2, type Pt } from './geom';

export type LSel = { kind: string; id: string };
export const LK_CN: Record<string, string> = { walls: $t('planView.wall'), zones: $t('common.area'), aisles: $t('common.channel'), nodes: $t('planState.roadNetworkNode'), edges: $t('planState.roadNetworkLink'), dims: $t('planView.dimensions') };
export const NODE_CN: Record<string, string> = { node: $t('planState.intersection'), station: $t('planState.stop'), charger: $t('planState.chargingPoint') };

export const pv = reactive<any>({
  lsel: [] as LSel[],          // Selected layout elements
  preview: null as any,        // Layout being dragged (committed on release)
  clipKind: '' as '' | 'layout' | 'blocks',   // Most recently copied content type (determines what Ctrl+V pastes)
  arrayOpen: false,
  focusName: 0,                // Increment to focus the name field in the properties card.
});

export const clone = (x: any) => JSON.parse(JSON.stringify(x));
export const L = computed<any>(() => ed.model?.plant?.layout || {});
/** Layout for the canvas: use the preview while dragging. */
export const LL = computed<any>(() => pv.preview || L.value);

export const listOf = (l: any, kind: string): any[] => (kind === 'nodes' || kind === 'edges' ? ((l.paths ||= { nodes: [], edges: [] })[kind] ||= []) : (l[kind] ||= []));
export const itemOf = (l: any, s: LSel | null | undefined) => (s ? (kind2list(l, s.kind) || []).find((x: any) => x.id === s.id) : null);
const kind2list = (l: any, kind: string) => (kind === 'nodes' || kind === 'edges' ? l.paths?.[kind] : l[kind]);
export const isLay = (kind: string, id: string) => pv.lsel.some((s: LSel) => s.kind === kind && s.id === id);
export const sel1 = computed<LSel | null>(() => (pv.lsel.length === 1 ? pv.lsel[0] : null));
export const selItem = computed<any>(() => itemOf(L.value, sel1.value));

export function usedIds(l: any) {
  return new Set([...(l.walls || []), ...(l.zones || []), ...(l.aisles || []), ...(l.dims || []), ...(l.paths?.nodes || []), ...(l.paths?.edges || [])].map((x: any) => x.id));
}
export function lid(l: any, prefix: string) {
  const used = usedIds(l);
  let n = 1; while (used.has(prefix + n)) n++; return prefix + n;
}
export const PREFIX: Record<string, string> = { walls: 'W', zones: 'Z', aisles: 'A', dims: 'D', nodes: 'N', edges: 'E' };

/** Update layout: fn modifies a copy, producing one undoable command; extra contains other commands to execute in the same step (e.g., equipment). */
export function setLayout(fn: (l: any) => void, label: string, extra: Op[] = [], plantSet: Record<string, any> = {}) {
  const l = clone(L.value); fn(l);
  exec([...extra, { op: 'update_plant', set: { 'plant.layout': l, ...plantSet } }], label);
}
export function setItem(set: any, s: LSel | null = sel1.value) {
  if (!s) return;
  setLayout((l) => { const it = itemOf(l, s); if (it) for (const [k, v] of Object.entries(set)) { if (v === null || v === undefined || v === '') delete it[k]; else it[k] = v; } }, $t('common.edit2') + LK_CN[s.kind]);
}
export function removeLays(sels: LSel[] = pv.lsel) {
  if (!sels.length) return;
  setLayout((l) => {
    for (const s of sels) {
      const arr = listOf(l, s.kind); const i = arr.findIndex((x: any) => x.id === s.id); if (i >= 0) arr.splice(i, 1);
      if (s.kind === 'nodes' && l.paths) l.paths.edges = (l.paths.edges || []).filter((e: any) => e.a !== s.id && e.b !== s.id);
    }
  }, sels.length > 1 ? $t('planState.delete0LayoutElements', [sels.length]) : $t('common.delete') + LK_CN[sels[0].kind]);
  pv.lsel = [];
}

/** All points on an element (for box selection and bounding boxes). */
export function pointsOf(l: any, s: LSel): Pt[] {
  const it = itemOf(l, s); if (!it) return [];
  if (s.kind === 'nodes') return [[it.x, it.y]];
  if (s.kind === 'edges') { const ns = l.paths?.nodes || []; return [it.a, it.b].map((id: string) => ns.find((n: any) => n.id === id)).filter(Boolean).map((n: any) => [n.x, n.y]); }
  if (s.kind === 'dims') return [it.a, it.b];
  return it.pts || [];
}
export function allSels(l: any): LSel[] {
  const out: LSel[] = [];
  for (const k of ['walls', 'zones', 'aisles', 'dims']) for (const it of l[k] || []) out.push({ kind: k, id: it.id });
  for (const k of ['nodes', 'edges']) for (const it of l.paths?.[k] || []) out.push({ kind: k, id: it.id });
  return out;
}

/** Translate selected layout elements (road network edges move both endpoint nodes; move each node only once). */
export function translate(l: any, sels: LSel[], dx: number, dy: number) {
  const nodes = new Set<string>();
  for (const s of sels) {
    const it = itemOf(l, s); if (!it) continue;
    if (s.kind === 'nodes') nodes.add(it.id);
    else if (s.kind === 'edges') { nodes.add(it.a); nodes.add(it.b); }
    else if (s.kind === 'dims') { it.a = [r2(it.a[0] + dx), r2(it.a[1] + dy)]; it.b = [r2(it.b[0] + dx), r2(it.b[1] + dy)]; }
    else it.pts = it.pts.map((q: Pt) => [r2(q[0] + dx), r2(q[1] + dy)]);
  }
  for (const n of l.paths?.nodes || []) if (nodes.has(n.id)) { n.x = r2(n.x + dx); n.y = r2(n.y + dy); }
}

// ---------- Copy / Paste / Array ----------
let clip: any = null;
const CLIP_KEY = 'vf_plan_clip';
/** Package selected layout elements and equipment (include road network edge endpoints and edges between selected nodes). */
function buildClip() {
  const l = L.value;
  const c: any = { walls: [], zones: [], aisles: [], dims: [], nodes: [], edges: [], blocks: [], links: [] };
  const nodeIds = new Set<string>(), selNodes = new Set<string>();
  for (const s of pv.lsel) {
    const it = itemOf(l, s); if (!it) continue;
    if (s.kind === 'edges') { c.edges.push(clone(it)); nodeIds.add(it.a); nodeIds.add(it.b); }
    else if (s.kind === 'nodes') { nodeIds.add(it.id); selNodes.add(it.id); }
    else c[s.kind].push(clone(it));
  }
  c.nodes = (l.paths?.nodes || []).filter((n: any) => nodeIds.has(n.id)).map(clone);
  for (const e of l.paths?.edges || []) if (selNodes.has(e.a) && selNodes.has(e.b) && !c.edges.some((x: any) => x.id === e.id)) c.edges.push(clone(e));
  const bs = selBlocks.value; const ids = new Set(bs.map((b: any) => b.id));
  c.blocks = clone(bs); c.links = clone((ed.model.links || []).filter((x: any) => ids.has(x.from) && ids.has(x.to)));
  return clipCount(c) ? c : null;
}
/** Copy selected layout elements and equipment to the clipboard. */
export function copyLay() {
  if (!pv.lsel.length) return false;
  const c = buildClip(); if (!c) return false;
  clip = c; pv.clipKind = 'layout';
  try { localStorage.setItem(CLIP_KEY, JSON.stringify(c)); } catch { /* */ }
  return true;
}
export function getClip() {
  if (clip) return clip;
  try { clip = JSON.parse(localStorage.getItem(CLIP_KEY) || 'null'); } catch { /* */ }
  return clip;
}
export const clipCount = (c: any) => (c ? ['walls', 'zones', 'aisles', 'dims', 'nodes', 'edges', 'blocks'].reduce((t, k) => t + (c[k]?.length || 0), 0) : 0);
export function clipBox(c: any) {
  const pts: Pt[] = [];
  for (const k of ['walls', 'zones', 'aisles']) for (const it of c[k] || []) pts.push(...it.pts);
  for (const d of c.dims || []) pts.push(d.a, d.b);
  for (const n of c.nodes || []) pts.push([n.x, n.y]);
  for (const b of c.blocks || []) pts.push([b.pos[0] - b.size[0] / 2, b.pos[1] - b.size[1] / 2], [b.pos[0] + b.size[0] / 2, b.pos[1] + b.size[1] / 2]);
  return bbox(pts);
}
/** Insert a clipboard copy into l at each offset in offsets; return the new element selection and equipment commands. */
function placeCopies(l: any, c: any, offsets: number[][]) {
  const sels: LSel[] = [];
  for (const [dx, dy] of offsets) {
    for (const k of ['walls', 'zones', 'aisles', 'dims']) for (const it of c[k] || []) {
      const n = clone(it); n.id = lid(l, PREFIX[k]);
      if (k === 'zones' && /^(\u533a\u57df|Zone|Area) \d+$/.test(it.name || '')) n.name = $t('planView.area') + n.id.slice(1);
      if (k === 'dims') { n.a = [r2(it.a[0] + dx), r2(it.a[1] + dy)]; n.b = [r2(it.b[0] + dx), r2(it.b[1] + dy)]; }
      else n.pts = it.pts.map((q: Pt) => [r2(q[0] + dx), r2(q[1] + dy)]);
      if (n.outer) delete n.outer;
      listOf(l, k).push(n); sels.push({ kind: k, id: n.id });
    }
    const map: Record<string, string> = {};
    for (const it of c.nodes || []) { const n = clone(it); n.id = lid(l, 'N'); map[it.id] = n.id; n.x = r2(it.x + dx); n.y = r2(it.y + dy); delete n.block; listOf(l, 'nodes').push(n); sels.push({ kind: 'nodes', id: n.id }); }
    for (const it of c.edges || []) {
      if (!map[it.a] || !map[it.b]) continue;
      const n = clone(it); n.id = lid(l, 'E'); n.a = map[it.a]; n.b = map[it.b]; listOf(l, 'edges').push(n); sels.push({ kind: 'edges', id: n.id });
    }
  }
  // Equipment: assign temporary IDs to each copy, then let cloneOps reassign all IDs (single undo step).
  let ops: Op[] = [], ids: string[] = [];
  if (c.blocks?.length) {
    const fb: any[] = [], fl: any[] = [];
    offsets.forEach(([dx, dy], i) => {
      const m: Record<string, string> = {};
      for (const b of c.blocks) {
        const f = `${b.id}z${i}`; m[b.id] = f;
        fb.push({ ...clone(b), id: f, name: (b.name || '').replace(b.id, f), pos: [r2(b.pos[0] + dx), r2(b.pos[1] + dy)], node: [(b.node?.[0] || 0) + dx * 12 + 40, (b.node?.[1] || 0) + dy * 12 + 40] });
      }
      for (const x of c.links || []) if (m[x.from] && m[x.to]) fl.push({ ...clone(x), from: m[x.from], to: m[x.to] });
    });
    ({ ops, ids } = cloneOps(fb, fl, [0, 0], [0, 0]));
  }
  return { sels, ops, ids };
}
/** Paste: center the clipboard bounding box at at if provided; otherwise offset by 2 m. */
export function pasteLay(at?: Pt | null, snap = (x: number) => x) {
  const c = getClip(); if (!clipCount(c)) return;
  const bb = clipBox(c)!;
  const d = at ? [snap(at[0] - (bb.x0 + bb.x1) / 2), snap(at[1] - (bb.y0 + bb.y1) / 2)] : [2, 2];
  commitCopies(c, [d], $t('planState.paste0Items', [clipCount(c)]));
}
function commitCopies(c: any, offs: number[][], label: string, keep = false) {
  const prevLsel = keep ? [...pv.lsel] : [], prevSel = keep ? [...ed.sel] : [];
  const l = clone(L.value);
  const res = placeCopies(l, c, offs);
  const changed = res.sels.length > 0;
  exec([...res.ops, ...(changed ? [{ op: 'update_plant', set: { 'plant.layout': l } }] : [])], label);
  pv.lsel = [...prevLsel, ...res.sels];
  ed.sel = [...prevSel, ...res.ids]; if (res.ids.length) flash(res.ids);
}
/** Duplicate once (Ctrl+D). */
export function duplicateLay() { if (copyLay()) pasteLay(null); }
/** Bounding box of the selection (layout elements + equipment). */
export function selBox() {
  const l = L.value, pts: Pt[] = [];
  for (const s of pv.lsel) pts.push(...pointsOf(l, s));
  for (const b of selBlocks.value) pts.push([b.pos[0] - b.size[0] / 2, b.pos[1] - b.size[1] / 2], [b.pos[0] + b.size[0] / 2, b.pos[1] + b.size[1] / 2]);
  return bbox(pts);
}
/** Array: rows × cols with column spacing dx and row spacing dy (meters); the original counts as the first copy. Equipment and layout elements share one undo step. */
export function arraySel(rows: number, cols: number, dx: number, dy: number) {
  const c = buildClip(); if (!c) return;
  const offs: number[][] = [];
  for (let r = 0; r < rows; r++) for (let k = 0; k < cols; k++) if (r || k) offs.push([r2(k * dx), r2(r * dy)]);
  if (offs.length) commitCopies(c, offs, $t('planState.array01', [rows, cols]), true);
}

// ---------- Building Exterior Walls ----------
export const outerOf = (l: any) => (l.walls || []).find((w: any) => w.outer);
export function rectPts(W: number, D: number): Pt[] { return [[0, 0], [W, 0], [W, D], [0, D], [0, 0]]; }
/** Whether the exterior wall is still the original rectangle generated from the building dimensions. */
export function outerMatches(w: any, floor: number[] | undefined) {
  if (!w || !floor || !isClosed(w.pts) || w.pts.length !== 5) return false;
  const bb = bbox(w.pts)!;
  return Math.abs(bb.x0) < 1e-6 && Math.abs(bb.y0) < 1e-6 && w.pts.every((q: Pt) => (q[0] === 0 || q[0] === bb.x1) && (q[1] === 0 || q[1] === bb.y1));
}
/** Generate an exterior wall: a standard closed wall, optionally with a gate centered on the front wall (maximum Y side). */
export function addOuterWall(W: number, D: number, t: number, doorW: number) {
  setLayout((l) => {
    const w: any = { id: lid(l, 'W'), pts: rectPts(W, D), t, outer: true, doors: [] };
    if (doorW > 0) w.doors.push({ s: r2(W + D + W / 2), w: doorW });
    listOf(l, 'walls').push(w);
    pv.lsel = [{ kind: 'walls', id: w.id }];
  }, $t('planState.generateBuildingExteriorWalls'));
}
/** Resize the building: update the exterior wall if it is still the original rectangle (scale door opening positions proportionally). Return whether the wall was updated. */
export function setHallSize(W: number, D: number) {
  const ow = outerOf(L.value), fl = ed.model?.plant?.floor;
  const follow = !!ow && outerMatches(ow, fl);
  setLayout((l) => {
    const w = outerOf(l);
    if (follow && w) { const np = rectPts(W, D); w.doors = remapDoors(w.pts, np, w.doors || []); w.pts = np; }
  }, $t('planState.resizeBuilding'), [], { 'plant.floor': [W, D] });
  return follow;
}
export function rebuildOuter() {
  const fl = ed.model?.plant?.floor; if (!fl) return;
  setLayout((l) => { const w = outerOf(l); if (!w) return; const np = rectPts(fl[0], fl[1]); w.doors = remapDoors(w.pts, np, w.doors || []); w.pts = np; }, $t('planView.rebuildExteriorWallsToBuilding'));
}

// ---------- Equipment ----------
export function rotateSel(deg: number) {
  exec(selBlocks.value.map((b: any) => ({ op: 'update_block', id: b.id, set: { rot: (((b.rot || 0) + deg) % 360 + 360) % 360 } })), $t('details.rotation'));
}
export const blockName = (id: string) => blocksById.value[id]?.name || id;
