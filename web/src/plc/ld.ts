// Ladder diagram: series/parallel tree editing + layout (compute positions and power flow for each element and wire segment).
// Tree: rung elements = series list; element {id, t, var…}; parallel {par: [branch list, …]}.
import { $t } from '../i18n';
import { FB_TYPES } from './plcApi';

export const CONTACTS = ['NO', 'NC', 'P', 'N'];
export const COILS = ['COIL', 'NCOIL', 'SET', 'RESET'];
export const BOXES = ['FB', 'CMP', 'MATH', 'MOVE'];
export const T_CN: Record<string, string> = { NO: $t('ladderEditor.noContact'), NC: $t('ladderEditor.ncContact'), P: $t('ladderEditor.risingEdgeContact'), N: $t('ladderEditor.fallingEdgeContact'), COIL: $t('ladderEditor.coil'), NCOIL: $t('ladderEditor.negatedCoil'), SET: $t('common.setCoil'),
  RESET: $t('common.resetCoil'), FB: $t('ld.functionBlock'), CMP: $t('ladderEditor.compare'), MATH: $t('ladderEditor.arithmetic'), MOVE: $t('ladderEditor.move') };
export const CMP_OPS = ['>', '>=', '=', '<>', '<', '<='];
export const MATH_OPS: Record<string, string> = { ADD: '+', SUB: '-', MUL: '×', DIV: '÷', MOD: 'MOD' };

let seq = 0;
export const newId = () => 'e' + Date.now().toString(36) + (seq++).toString(36);
const clone = (x: any) => JSON.parse(JSON.stringify(x));

export function isEl(x: any) { return x && !Array.isArray(x) && !x.par && !x.ser && x.t; }
export function isCoilLike(x: any) { return isEl(x) && COILS.includes(x.t); }

/** Reassign all IDs (for pasting). */
export function reId(x: any): any {
  if (Array.isArray(x)) return x.map(reId);
  if (x?.par) return { par: x.par.map(reId) };
  if (x?.ser) return { ser: reId(x.ser) };
  return { ...clone(x), id: newId() };
}

/** Find an element: return its list, index, rung number, and enclosing parallel node (if in a branch). */
export function locate(rungs: any[], id: string) {
  let hit: any = null;
  const walk = (list: any[], ri: number, parNode: any, branch: number) => {
    list.forEach((x, i) => {
      if (hit) return;
      if (Array.isArray(x)) walk(x, ri, parNode, branch);
      else if (x.par) x.par.forEach((b: any[], bi: number) => walk(b, ri, { node: x, list, index: i }, bi));
      else if (x.ser) walk(x.ser, ri, parNode, branch);
      else if (x.id === id) hit = { list, index: i, rung: ri, el: x, parent: parNode, branch };
    });
  };
  rungs.forEach((r, ri) => walk(r.elements, ri, null, 0));
  return hit as null | { list: any[]; index: number; rung: number; el: any; parent: any; branch: number };
}

/** Elements in a rung in display order (left→right, top→bottom). */
export function flatten(list: any[]): any[] {
  const out: any[] = [];
  for (const x of list) {
    if (Array.isArray(x)) out.push(...flatten(x));
    else if (x.par) x.par.forEach((b: any[]) => out.push(...flatten(b)));
    else if (x.ser) out.push(...flatten(x.ser));
    else out.push(x);
  }
  return out;
}

/** Clean up after deletion: remove empty branches and unwrap parallel nodes with only one branch. */
export function tidy(list: any[]) {
  for (let i = 0; i < list.length; i++) {
    const x = list[i];
    if (x?.par) {
      x.par.forEach((b: any[]) => tidy(b));
      x.par = x.par.filter((b: any[]) => b.length);
      if (!x.par.length) { list.splice(i, 1); i--; }
      else if (x.par.length === 1) { list.splice(i, 1, ...x.par[0]); i--; }
    } else if (x?.ser) { list.splice(i, 1, ...x.ser); i--; }
  }
}

export function removeIds(rungs: any[], ids: string[]) {
  for (const id of ids) {
    const h = locate(rungs, id);
    if (h) h.list.splice(h.index, 1);
  }
  rungs.forEach((r) => tidy(r.elements));
}

/** Default content for a new element. */
export function makeEl(t: string, extra: any = {}) {
  const e: any = { id: newId(), t };
  if (CONTACTS.includes(t) || COILS.includes(t)) e.var = '';
  if (t === 'FB') Object.assign(e, { fb: 'TON', inst: '', in: {}, out: {} });
  if (t === 'CMP') Object.assign(e, { op: '>=', a: '', b: '' });
  if (t === 'MATH') Object.assign(e, { op: 'ADD', a: '', b: '', out: '' });
  if (t === 'MOVE') Object.assign(e, { in: '', out: '' });
  return Object.assign(e, extra);
}

/** Trailing coil group (right-aligned): return the boundary index. */
export function tailStart(list: any[]) {
  let i = list.length;
  while (i > 0) {
    const x = list[i - 1];
    const coilBranch = x?.par && x.par.every((b: any[]) => b.length && b.every((y: any) => isCoilLike(y)));
    if (isCoilLike(x) || coilBranch) i--;
    else break;
  }
  return i;
}

/** Insert an element: after = selected element ID (insert after it); if none is selected, use a suitable position in the rung. */
export function insert(rungs: any[], ri: number, el: any, afterId?: string) {
  const isCoil = COILS.includes(el.t);
  if (afterId) {
    const h = locate(rungs, afterId);
    if (h) {
      if (isCoil && isCoilLike(h.el) && h.index === h.list.length - 1 && !h.parent) {
        // Adding a coil after a coil → parallel outputs
        h.list.splice(h.index, 1, { par: [[h.el], [el]] });
        return;
      }
      if (isCoil && h.parent && h.list.every(isCoilLike)) {
        h.parent.node.par.splice(h.branch + 1, 0, [el]);
        return;
      }
      h.list.splice(h.index + 1, 0, el);
      return;
    }
  }
  const r = rungs[Math.max(0, Math.min(ri, rungs.length - 1))];
  const list = r.elements;
  const ts = tailStart(list);
  if (isCoil) {
    if (ts < list.length) {
      const last = list[list.length - 1];
      if (last.par) last.par.push([el]);
      else list.splice(list.length - 1, 1, { par: [[last], [el]] });
    } else list.push(el);
  } else list.splice(ts, 0, el);
}

/** Add a parallel branch to the selection (consecutive elements in one series list): put el (or an empty wire segment) in the new branch. */
export function addParallel(rungs: any[], ids: string[], el: any | null) {
  const hs = ids.map((id) => locate(rungs, id)).filter(Boolean) as any[];
  if (!hs.length) return false;
  const list = hs[0].list;
  if (hs.some((h) => h.list !== list)) return false;
  const idx = hs.map((h) => h.index).sort((a, b) => a - b);
  const a = idx[0], b = idx[idx.length - 1];
  const seg = list.slice(a, b + 1);
  list.splice(a, b - a + 1, { par: [seg, el ? [el] : []] });
  return true;
}

// ---------------------------------------------------------------- Layout
export const G = { contactW: 92, coilW: 92, row: 76, wy: 40, wire: 30, busPad: 12, boxPinH: 22, boxHead: 24, boxW: 132, boxSide: 64, minEnd: 40 };

export type Prim =
  | { k: 'wire'; x1: number; y1: number; x2: number; y2: number; p: boolean | null }
  | { k: 'el'; el: any; x: number; y: number; w: number; h: number; wy: number; pin: boolean | null; pout: boolean | null; c: boolean | null }
  | { k: 'drop'; list: any[]; index: number; x: number; y: number; w: number; h: number }
  | { k: 'dropPar'; id: string; x: number; y: number; w: number; h: number };

type L = { w: number; h: number; wy: number; draw: (x: number, y: number, pin: boolean | null, out: Prim[]) => boolean | null };

export function boxPins(el: any): { ins: string[]; outs: string[] } {
  if (el.t === 'FB') { const d = FB_TYPES[el.fb] || FB_TYPES.TON; return { ins: d.in, outs: d.out }; }
  if (el.t === 'CMP') return { ins: ['EN', 'IN1', 'IN2'], outs: ['OUT'] };
  if (el.t === 'MATH') return { ins: ['EN', 'IN1', 'IN2'], outs: ['ENO', 'OUT'] };
  return { ins: ['EN', 'IN'], outs: ['ENO', 'OUT'] };
}

function elLayout(el: any, flags: Record<string, boolean[]> | null): L {
  const f = flags ? flags[el.id] : null;
  if (BOXES.includes(el.t)) {
    const { ins, outs } = boxPins(el);
    const rows = Math.max(ins.length, outs.length);
    const bh = G.boxHead + rows * G.boxPinH + 6;
    const w = G.boxW + 2 * G.boxSide;
    const top = 22;                                     // Show the instance name above the box
    const wy = top + G.boxHead + G.boxPinH / 2;         // First pin row = power flow line
    return {
      w, h: top + bh + 12, wy,
      draw(x, y, pin, out) {
        const pout = f ? f[1] : null;
        out.push({ k: 'el', el, x, y, w, h: top + bh + 12, wy, pin: f ? f[0] : pin, pout, c: f ? f[2] : null });
        return f ? pout : pin;
      },
    };
  }
  const w = COILS.includes(el.t) ? G.coilW : G.contactW;
  return {
    w, h: G.row, wy: G.wy,
    draw(x, y, pin, out) {
      out.push({ k: 'el', el, x, y, w, h: G.row, wy: G.wy, pin: f ? f[0] : pin, pout: f ? f[1] : null, c: f ? f[2] : null });
      return f ? f[1] : null;
    },
  };
}

function serLayout(list: any[], flags: any, minW = 0): L {
  const items = list.map((x) => nodeLayout(x, flags));
  const empty = !items.length;
  const wy = empty ? G.wy : Math.max(...items.map((i) => i.wy));
  const h = empty ? G.row : Math.max(...items.map((i) => i.h - i.wy)) + wy;
  const natural = items.reduce((a, i) => a + i.w, 0) || G.wire * 2;
  const w = Math.max(natural, minW);
  return {
    w, h, wy,
    draw(x, y, pin, out) {
      let cx = x;
      let p = pin;
      items.forEach((it) => {
        p = it.draw(cx, y + wy - it.wy, p, out);
        cx += it.w;
      });
      if (cx < x + w) out.push({ k: 'wire', x1: cx, y1: y + wy, x2: x + w, y2: y + wy, p });
      return p;
    },
  };
}

function parLayout(node: any, flags: any): L {
  const bs = node.par.map((b: any[]) => serLayout(b, flags));
  const inner = Math.max(...bs.map((b: L) => b.w));
  const w = inner + 2 * G.busPad;
  const wy = bs[0].wy;
  const h = bs.reduce((a: number, b: L) => a + b.h, 0);
  return {
    w, h, wy,
    draw(x, y, pin, out) {
      let cy = y;
      const outs: (boolean | null)[] = [];
      const ys: number[] = [];
      bs.forEach((b: L, i: number) => {
        const by = cy + b.wy;
        ys.push(by);
        out.push({ k: 'wire', x1: x, y1: by, x2: x + G.busPad, y2: by, p: pin });
        const po = b.draw(x + G.busPad, cy, pin, out);
        const bEnd = x + G.busPad + b.w;
        if (bEnd < x + w) out.push({ k: 'wire', x1: bEnd, y1: by, x2: x + w, y2: by, p: po });
        outs.push(po);
        cy += b.h;
      });
      // The right rail is a single conductor: any energized branch energizes the entire rail
      const any = outs.some((o) => o === true) ? true : outs.every((o) => o === null) ? null : false;
      out.push({ k: 'wire', x1: x, y1: ys[0], x2: x, y2: ys[ys.length - 1], p: pin });
      out.push({ k: 'wire', x1: x + w, y1: ys[0], x2: x + w, y2: ys[ys.length - 1], p: any });
      return any;
    },
  };
}

function nodeLayout(x: any, flags: any): L {
  if (Array.isArray(x)) return serLayout(x, flags);
  if (x.par) return parLayout(x, flags);
  if (x.ser) return serLayout(x.ser, flags);
  return elLayout(x, flags);
}

/** Lay out a rung: left rail at x=0, right rail at width; trailing coils right-aligned. */
export function layoutRung(rung: any, flags: Record<string, boolean[]> | null, railOn: boolean | null, minWidth: number, drops = true) {
  const list = rung.elements;
  const ts = tailStart(list);
  const left = list.slice(0, ts), tail = list.slice(ts);
  const L1 = serLayout(left, flags);
  const L2 = tail.length ? serLayout(tail, flags) : null;
  const wy = Math.max(L1.wy, L2?.wy || 0);
  const h = Math.max(L1.h - L1.wy, (L2 ? L2.h - L2.wy : 0)) + wy;
  const natural = 18 + L1.w + (L2 ? L2.w : 0) + G.minEnd;
  const width = Math.max(minWidth, natural);
  const prims: Prim[] = [];
  const x0 = 18;
  let p = L1.draw(x0, wy - L1.wy, railOn, prims);
  if (!left.length) p = railOn;
  const x2 = L2 ? width - 18 - L2.w : width - 18;
  prims.push({ k: 'wire', x1: 0, y1: wy, x2: x0, y2: wy, p: railOn });
  const leftEnd = x0 + L1.w;
  // Fill the gap with wire
  prims.push({ k: 'wire', x1: leftEnd, y1: wy, x2: x2, y2: wy, p });
  let pout = p;
  if (L2) pout = L2.draw(x2, wy - L2.wy, p, prims);
  prims.push({ k: 'wire', x1: width - 18, y1: wy, x2: width, y2: wy, p: pout });
  if (drops) addDrops(rung.elements, prims);
  return { width, height: h + 8, wy, prims };
}

/** Drop targets: one per series gap (including inside branches), and one below each element (to add a parallel branch). Compute positions with a layout-only pass. */
function addDrops(list: any[], prims: Prim[]) {
  const els = prims.filter((p) => p.k === 'el') as any[];
  const byId = new Map(els.map((e) => [e.el.id, e]));
  const visit = (lst: any[]) => {
    const flat = lst;
    for (let i = 0; i <= flat.length; i++) {
      const prev = flat[i - 1], next = flat[i];
      const pb = prev ? bounds(prev, byId) : null, nb = next ? bounds(next, byId) : null;
      let x: number, y: number;
      if (pb && nb) { x = (pb.x2 + nb.x1) / 2; y = pb.wy; }
      else if (pb) { x = pb.x2 + 10; y = pb.wy; }
      else if (nb) { x = nb.x1 - 10; y = nb.wy; }
      else continue;
      prims.push({ k: 'drop', list: lst, index: i, x: x - 9, y: y - 15, w: 18, h: 30 });
    }
    for (const x of lst) {
      if (Array.isArray(x)) visit(x);
      else if (x.par) x.par.forEach((b: any[]) => { if (b.length) visit(b); });
      else if (x.ser) visit(x.ser);
    }
  };
  visit(list);
  for (const e of els) prims.push({ k: 'dropPar', id: e.el.id, x: e.x + 8, y: e.y + e.h - 14, w: e.w - 16, h: 14 });
  if (!list.length) prims.push({ k: 'drop', list, index: 0, x: 20, y: G.wy - 15, w: 120, h: 30 });
}

function bounds(x: any, byId: Map<string, any>): { x1: number; x2: number; wy: number } | null {
  const els = flatten([x]).map((e) => byId.get(e.id)).filter(Boolean);
  if (!els.length) return null;
  const first = byId.get(flatten([x])[0]?.id);
  return { x1: Math.min(...els.map((e: any) => e.x)), x2: Math.max(...els.map((e: any) => e.x + e.w)), wy: (first?.y ?? 0) + (first?.wy ?? G.wy) };
}
