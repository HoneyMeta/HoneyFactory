// Orthogonal routing (4.4), shared by Floor Plan and Architecture. Endpoints attach to ports on object borders; horizontal/vertical segments avoid other objects, with rounded corners,
// and parallel lines in the same corridor are offset. Units follow the view (Floor Plan = meters, Architecture = pixels); callers supply all dimensions in those units.
//
// Approach:
//   1. assignPorts: choose a side facing the other endpoint at each end (keep signal/network lines off material-flow sides where possible); order ports by opposite endpoint position.
//   2. routeOne: run A* on a sparse grid formed by "expanded obstacle boundaries + this line's two port extension points" (cost = length + turn penalty; object crossings ×1000,
//      object clearance zones ×3), ensuring a route always exists and avoids other objects in normal layouts.
//   3. nudge: offset overlapping interior segments on the same line by gap, in order.
//   4. pathD: rounded polyline SVG path; labelAt: midpoint of the longest segment (for labels such as "6 channels" or the protocol).
// Recompute all routes only when model geometry changes; use elbow (simple right-angle routing) while dragging.
export type Pt = number[];
export type Rect = { x0: number; y0: number; x1: number; y1: number };
export type Conn = { key: string; a: string; b: string; kind: string };
export type End = { id: string; p: Pt; side: number };
export type Route = { key: string; kind: string; a: End; b: End; pts: Pt[] };
export type RouteOpts = { margin: number; bend?: number; gap?: number; close?: number };

// Sides: 0 right (+x), 1 bottom (+y), 2 left, 3 top
export const NX = [1, 0, -1, 0], NY = [0, 1, 0, -1];
const cx = (r: Rect) => (r.x0 + r.x1) / 2, cy = (r: Rect) => (r.y0 + r.y1) / 2;

/** Side facing the other endpoint: use left/right for a larger x offset, top/bottom for a larger y offset. */
function facing(A: Rect, B: Rect) {
  const dx = cx(B) - cx(A), dy = cy(B) - cy(A);
  const gx = Math.abs(dx) - ((A.x1 - A.x0) + (B.x1 - B.x0)) / 2, gy = Math.abs(dy) - ((A.y1 - A.y0) + (B.y1 - B.y0)) / 2;
  const hor = gx > gy || (gx === gy && Math.abs(dx) >= Math.abs(dy));
  const main = hor ? (dx >= 0 ? 0 : 2) : dy >= 0 ? 1 : 3;
  const alt = hor ? (dy >= 0 ? 1 : 3) : dx >= 0 ? 0 : 2;     // The other side facing the opposite endpoint
  const altOk = hor ? Math.abs(dy) > (A.y1 - A.y0) / 2 : Math.abs(dx) > (A.x1 - A.x0) / 2;
  return { main, alt, altOk };
}

/** Another object is immediately outside this side (within clearance m): extending from here would hit it. */
function stubBlocked(rects: Record<string, Rect>, me: string, ot: string, s: number, m: number) {
  const A = rects[me], e = 1e-6;
  const z = s === 0 ? { x0: A.x1, x1: A.x1 + m, y0: A.y0, y1: A.y1 } : s === 2 ? { x0: A.x0 - m, x1: A.x0, y0: A.y0, y1: A.y1 }
    : s === 1 ? { x0: A.x0, x1: A.x1, y0: A.y1, y1: A.y1 + m } : { x0: A.x0, x1: A.x1, y0: A.y0 - m, y1: A.y0 };
  for (const [id, R] of Object.entries(rects)) {
    if (id === me || id === ot) continue;
    if (R.x0 < z.x1 - e && R.x1 > z.x0 + e && R.y0 < z.y1 - e && R.y1 > z.y0 + e) return true;
  }
  return false;
}
/** Side scores (lower is better): facing the endpoint 0, alternate facing side 1, lateral side 3, rear side 4; adjacent object outside +10. */
function sideScores(rects: Record<string, Rect>, me: string, ot: string, m: number) {
  const f = facing(rects[me], rects[ot]), sc = [3, 3, 3, 3];
  sc[(f.main + 2) % 4] = 4; sc[f.alt] = f.altOk ? 1 : 2; sc[f.main] = 0;
  if (m > 0) for (let s = 0; s < 4; s++) if (stubBlocked(rects, me, ot, s, m)) sc[s] += 10;
  return sc;
}

/** Ports: choose a side at each end; order ports on each side by opposite endpoint position to avoid crossings. m: clearance used to avoid sides with adjacent objects outside. */
export function assignPorts(rects: Record<string, Rect>, conns: Conn[], m = 0): Record<string, { a: End; b: End }> {
  const slots: Record<string, { key: string; end: 'a' | 'b'; other: string; kind: string }[]> = {};
  const sideOf: Record<string, number> = {};
  const used = new Set<string>();                    // Sides occupied by material-flow lines (id:side)
  const ordered = [...conns].sort((p, q) => +(p.kind !== 'material') - +(q.kind !== 'material'));
  for (const c of ordered) {
    const A = rects[c.a], B = rects[c.b]; if (!A || !B) continue;
    for (const [end, me, ot] of [['a', c.a, c.b], ['b', c.b, c.a]] as ['a' | 'b', string, string][]) {
      const sc = sideScores(rects, me, ot, m);
      let s = sc.indexOf(Math.min(...sc));
      // Signal/network lines: if the chosen side has material flow, switch to a free side with a similar score (≤ +1) to keep signal and material flow separate.
      if (c.kind !== 'material' && used.has(me + ':' + s)) {
        const alt = [0, 1, 2, 3].filter((x) => x !== s && !used.has(me + ':' + x) && sc[x] <= sc[s] + 1).sort((p, q) => sc[p] - sc[q])[0];
        if (alt !== undefined) s = alt;
      }
      if (c.kind === 'material') used.add(me + ':' + s);
      sideOf[c.key + ':' + end] = s;
      (slots[me + ':' + s] ||= []).push({ key: c.key, end, other: ot, kind: c.kind });
    }
  }
  const out: Record<string, { a: End; b: End }> = {};
  for (const [k, arr] of Object.entries(slots)) {
    const i0 = k.lastIndexOf(':'), id = k.slice(0, i0), s = +k.slice(i0 + 1), R = rects[id];
    const along = s === 0 || s === 2 ? (r: Rect) => cy(r) : (r: Rect) => cx(r);
    arr.sort((p, q) => along(rects[p.other]) - along(rects[q.other]) || (p.kind < q.kind ? -1 : p.kind > q.kind ? 1 : 0) || (p.key < q.key ? -1 : 1));
    const n = arr.length;
    arr.forEach((x, i) => {
      const t = (i + 1) / (n + 1);
      const p = s === 0 ? [R.x1, R.y0 + (R.y1 - R.y0) * t] : s === 2 ? [R.x0, R.y0 + (R.y1 - R.y0) * t]
        : s === 1 ? [R.x0 + (R.x1 - R.x0) * t, R.y1] : [R.x0 + (R.x1 - R.x0) * t, R.y0];
      (out[x.key] ||= { a: null as any, b: null as any })[x.end] = { id, p, side: s };
    });
  }
  for (const k of Object.keys(out)) if (!out[k].a || !out[k].b) delete out[k];
  return out;
}

// ---------- A* ----------
function lowerBound(a: number[], x: number) { let lo = 0, hi = a.length; while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] < x) lo = m + 1; else hi = m; } return lo; }
function uniq(a: number[]) { a.sort((p, q) => p - q); const o: number[] = []; for (const x of a) if (!o.length || x - o[o.length - 1] > 1e-7) o.push(x); return o; }

class Heap {
  f: number[] = []; s: number[] = [];
  get size() { return this.f.length; }
  push(f: number, s: number) {
    const F = this.f, S = this.s; let i = F.length; F.push(f); S.push(s);
    while (i > 0) { const p = (i - 1) >> 1; if (F[p] <= f) break; F[i] = F[p]; S[i] = S[p]; i = p; }
    F[i] = f; S[i] = s;
  }
  pop() {
    const F = this.f, S = this.s, top = S[0], lf = F.pop()!, ls = S.pop()!, n = F.length;
    if (n) {
      let i = 0;
      for (;;) { let c = 2 * i + 1; if (c >= n) break; if (c + 1 < n && F[c + 1] < F[c]) c++; if (F[c] >= lf) break; F[i] = F[c]; S[i] = S[c]; i = c; }
      F[i] = lf; S[i] = ls;
    }
    return top;
  }
}

// Reusable buffers (grids may have tens of thousands of nodes; allocating per line would create heavy GC pressure)
const B = { n: 0, node: new Uint8Array(0), hE: new Uint8Array(0), vE: new Uint8Array(0), g: new Float64Array(0), prev: new Int32Array(0), seen: new Int32Array(0), cur: 0 };
function grow(N: number) {
  if (B.n >= N) return;
  const n = Math.max(N, B.n * 2, 4096);
  Object.assign(B, { n, node: new Uint8Array(n), hE: new Uint8Array(n), vE: new Uint8Array(n), g: new Float64Array(n * 4), prev: new Int32Array(n * 4), seen: new Int32Array(n * 4), cur: 0 });
}

/** A "world": obstacles (object rectangles) + clearance; routes can reuse its grid lines. */
export class Router {
  rects: Rect[]; m: number; bend: number;
  bx: number[]; by: number[]; frame: Rect;
  constructor(rects: Rect[], o: RouteOpts) {
    this.rects = rects; this.m = o.margin; this.bend = o.bend ?? o.margin * 3;
    const xs: number[] = [], ys: number[] = [];
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const r of rects) { xs.push(r.x0 - this.m, r.x1 + this.m); ys.push(r.y0 - this.m, r.y1 + this.m); x0 = Math.min(x0, r.x0); y0 = Math.min(y0, r.y0); x1 = Math.max(x1, r.x1); y1 = Math.max(y1, r.y1); }
    if (!rects.length) { x0 = y0 = 0; x1 = y1 = 1; }
    const F = this.m * 3;
    this.frame = { x0: x0 - F, y0: y0 - F, x1: x1 + F, y1: y1 + F };
    xs.push(this.frame.x0, this.frame.x1); ys.push(this.frame.y0, this.frame.y1);
    this.bx = xs; this.by = ys;
  }

  /** Orthogonal path from port a to port b, including both port points. */
  route(a: End, b: End): Pt[] {
    const m = this.m;
    const S = [a.p[0] + NX[a.side] * m, a.p[1] + NY[a.side] * m], T = [b.p[0] + NX[b.side] * m, b.p[1] + NY[b.side] * m];
    const xs = uniq([...this.bx, S[0], T[0]]), ys = uniq([...this.by, S[1], T[1]]);
    const nx = xs.length, ny = ys.length, N = nx * ny;
    // Cost multipliers: nodes, horizontal edges (i→i+1), vertical edges (j→j+1). 2 = clearance zone, 3 = object interior
    grow(N);
    const node = B.node.subarray(0, N).fill(0), hE = B.hE.subarray(0, N).fill(0), vE = B.vE.subarray(0, N).fill(0);
    const mark = (arr: Uint8Array, i0: number, i1: number, j0: number, j1: number, v: number) => {
      for (let i = i0; i <= i1; i++) for (let j = j0; j <= j1; j++) { const k = i * ny + j; if (arr[k] < v) arr[k] = v; }
    };
    const paint = (r: Rect, v: number) => {
      // Nodes inside the open interval (r.x0, r.x1) × (r.y0, r.y1), and edges crossing into it
      const ia = lowerBound(xs, r.x0 + 1e-9), ib = lowerBound(xs, r.x1 - 1e-9) - 1;      // xs[ia..ib] lies strictly inside
      const ja = lowerBound(ys, r.y0 + 1e-9), jb = lowerBound(ys, r.y1 - 1e-9) - 1;
      if (ja <= jb) {
        if (ia <= ib) mark(node, ia, ib, ja, jb, v);
        // Horizontal edge i→i+1 on row j (strictly inside) overlaps (x0, x1): xs[i] < x1 and xs[i+1] > x0
        const ea = Math.max(0, lowerBound(xs, r.x0 + 1e-9) - 1), eb = Math.min(nx - 2, lowerBound(xs, r.x1 - 1e-9) - 1);
        if (ea <= eb) mark(hE, ea, eb, ja, jb, v);
      }
      if (ia <= ib) {
        const fa = Math.max(0, lowerBound(ys, r.y0 + 1e-9) - 1), fb = Math.min(ny - 2, lowerBound(ys, r.y1 - 1e-9) - 1);
        if (fa <= fb) mark(vE, ia, ib, fa, fb, v);
      }
    };
    for (const r of this.rects) paint({ x0: r.x0 - m + 1e-6, y0: r.y0 - m + 1e-6, x1: r.x1 + m - 1e-6, y1: r.y1 + m - 1e-6 }, 1);
    for (const r of this.rects) paint(r, 2);
    const W = [1, 3, 1000];
    const si = lowerBound(xs, S[0] - 1e-7), sj = lowerBound(ys, S[1] - 1e-7), ti = lowerBound(xs, T[0] - 1e-7), tj = lowerBound(ys, T[1] - 1e-7);
    const start = si * ny + sj, goal = ti * ny + tj, endDir = (b.side + 2) % 4;
    // Invalidate g / prev with a "generation number" instead of clearing each time
    const stamp = ++B.cur, g = B.g, prev = B.prev, seen = B.seen;
    const G = (st: number) => (seen[st] === stamp ? g[st] : Infinity);
    const h = (k: number) => Math.abs(xs[(k / ny) | 0] - T[0]) + Math.abs(ys[k % ny] - T[1]);
    const heap = new Heap();
    const s0 = start * 4 + a.side; g[s0] = 0; prev[s0] = -1; seen[s0] = stamp; heap.push(h(start), s0);
    let found = -1, best = Infinity, guard = 0;
    while (heap.size && guard++ < 400000) {
      const fTop = heap.f[0], st = heap.pop(), k = st >> 2, d = st & 3, gc = g[st];
      if (fTop >= best) break;
      if (fTop > gc + h(k) + 1e-9) continue;                               // Stale heap entry
      if (k === goal) { const fin = gc + (d === endDir ? 0 : this.bend * (d === b.side ? 2 : 1)); if (fin < best) { best = fin; found = st; } continue; }
      const i = (k / ny) | 0, j = k % ny;
      for (let nd = 0; nd < 4; nd++) {
        if (nd === (d + 2) % 4) continue;                                   // No U-turns
        let ni = i, nj = j, w = 0, len = 0;
        if (nd === 0) { if (i >= nx - 1) continue; ni = i + 1; w = hE[k]; len = xs[ni] - xs[i]; }
        else if (nd === 2) { if (i <= 0) continue; ni = i - 1; w = hE[ni * ny + j]; len = xs[i] - xs[ni]; }
        else if (nd === 1) { if (j >= ny - 1) continue; nj = j + 1; w = vE[k]; len = ys[nj] - ys[j]; }
        else { if (j <= 0) continue; nj = j - 1; w = vE[i * ny + nj]; len = ys[j] - ys[nj]; }
        const nk = ni * ny + nj, ns = nk * 4 + nd;
        const c = gc + len * W[w] + (nd !== d ? this.bend : 0);
        if (c < G(ns)) { g[ns] = c; prev[ns] = st; seen[ns] = stamp; heap.push(c + h(nk), ns); }
      }
    }
    if (found < 0) return elbow(a, b, m);
    const pts: Pt[] = [];
    for (let st = found; st >= 0; st = prev[st]) { const k = st >> 2; pts.push([xs[(k / ny) | 0], ys[k % ny]]); }
    pts.reverse();
    return simplify([[...a.p], ...pts, [...b.p]]);
  }
}

/** Remove duplicate points and collinear intermediate points. */
export function simplify(p: Pt[]): Pt[] {
  const q: Pt[] = [];
  for (const x of p) if (!q.length || Math.abs(x[0] - q[q.length - 1][0]) > 1e-7 || Math.abs(x[1] - q[q.length - 1][1]) > 1e-7) q.push(x);
  const o: Pt[] = [];
  for (const x of q) {
    while (o.length >= 2) {
      const a = o[o.length - 2], b = o[o.length - 1];
      const col = (Math.abs(a[0] - b[0]) < 1e-7 && Math.abs(b[0] - x[0]) < 1e-7) || (Math.abs(a[1] - b[1]) < 1e-7 && Math.abs(b[1] - x[1]) < 1e-7);
      if (col) o.pop(); else break;
    }
    o.push(x);
  }
  return o;
}

/** Simple right-angle route (while dragging or if no route is found): extend from ports with one or two bends between them. */
export function elbow(a: End, b: End, m: number): Pt[] {
  const S = [a.p[0] + NX[a.side] * m, a.p[1] + NY[a.side] * m], T = [b.p[0] + NX[b.side] * m, b.p[1] + NY[b.side] * m];
  const ha = a.side % 2 === 0, hb = b.side % 2 === 0;
  let mid: Pt[];
  if (ha && hb) { const x = (S[0] + T[0]) / 2; mid = [[x, S[1]], [x, T[1]]]; }
  else if (!ha && !hb) { const y = (S[1] + T[1]) / 2; mid = [[S[0], y], [T[0], y]]; }
  else if (ha) mid = [[T[0], S[1]]];
  else mid = [[S[0], T[1]]];
  return simplify([[...a.p], S, ...mid, T, [...b.p]]);
}

/** If facing objects are too close for both port extensions, connect their sides with a single straight segment. */
function closeFacing(A: Rect, B: Rect, a: End, b: End, close: number): Pt[] | null {
  if ((a.side + 2) % 4 !== b.side) return null;
  if (a.side % 2 === 0) {
    const gap = a.side === 0 ? B.x0 - A.x1 : A.x0 - B.x1;
    const lo = Math.max(A.y0, B.y0), hi = Math.min(A.y1, B.y1);
    if (gap < 0 || gap > close || hi - lo < 1e-6) return null;
    const y = Math.min(hi - (hi - lo) * 0.2, Math.max(lo + (hi - lo) * 0.2, (a.p[1] + b.p[1]) / 2));
    return [[a.p[0], y], [b.p[0], y]];
  }
  const gap = a.side === 1 ? B.y0 - A.y1 : A.y0 - B.y1;
  const lo = Math.max(A.x0, B.x0), hi = Math.min(A.x1, B.x1);
  if (gap < 0 || gap > close || hi - lo < 1e-6) return null;
  const x = Math.min(hi - (hi - lo) * 0.2, Math.max(lo + (hi - lo) * 0.2, (a.p[0] + b.p[0]) / 2));
  return [[x, a.p[1]], [x, b.p[1]]];
}

/** Offset overlapping interior segments on the same horizontal/vertical line (keep port segments fixed); avoid objects by trying centered offsets, then either side; skip if none fit. */
export function nudge(routes: Route[], gap: number, maxSpread: number, obstacles: Rect[] = []) {
  const hits = (axis: number, c: number, lo: number, hi: number) => obstacles.some((R) => (axis === 1
    ? c > R.y0 + 1e-6 && c < R.y1 - 1e-6 && hi > R.x0 + 1e-6 && lo < R.x1 - 1e-6
    : c > R.x0 + 1e-6 && c < R.x1 - 1e-6 && hi > R.y0 + 1e-6 && lo < R.y1 - 1e-6));
  for (const axis of [1, 0]) {          // 1: horizontal segments (group by y, offset along y); 0: vertical segments
    const segs: { r: Route; i: number; c: number; lo: number; hi: number; ord: number }[] = [];
    for (const r of routes) {
      const p = r.pts;
      for (let i = 1; i < p.length - 2; i++) {
        const a = p[i], b = p[i + 1];
        const isH = Math.abs(a[1] - b[1]) < 1e-7, isV = Math.abs(a[0] - b[0]) < 1e-7;
        if ((axis === 1 && !isH) || (axis === 0 && !isV)) continue;
        const o = 1 - axis, lo = Math.min(a[o], b[o]), hi = Math.max(a[o], b[o]);
        if (hi - lo < 1e-7) continue;
        // Sort by adjacent segment directions at both ends (incoming/outgoing segments above go on top) to reduce crossings.
        const ord = (p[i - 1][axis] + p[i + 2][axis]) / 2 - a[axis];
        segs.push({ r, i, c: a[axis], lo, hi, ord });
      }
    }
    segs.sort((p, q) => p.c - q.c || p.lo - q.lo);
    let s = 0;
    while (s < segs.length) {
      let e = s + 1;
      while (e < segs.length && Math.abs(segs[e].c - segs[s].c) < 1e-6) e++;
      // Cluster overlapping intervals on the same line.
      const line = segs.slice(s, e);
      let k = 0;
      while (k < line.length) {
        let hi = line[k].hi, q = k + 1;
        while (q < line.length && line[q].lo < hi - 1e-6) { hi = Math.max(hi, line[q].hi); q++; }
        const cl = line.slice(k, q);
        if (cl.length > 1) {
          cl.sort((p, r) => p.ord - r.ord || (p.r.key < r.r.key ? -1 : 1));
          const g = Math.min(gap, maxSpread / (cl.length - 1)), n1 = cl.length - 1;
          const plans = [(n: number) => (n - n1 / 2) * g, (n: number) => n * g, (n: number) => (n - n1) * g];
          const plan = plans.find((f) => cl.every((x, n) => !hits(axis, x.c + f(n), x.lo, x.hi)));
          if (plan) cl.forEach((x, n) => { const off = plan(n); x.r.pts[x.i][axis] += off; x.r.pts[x.i + 1][axis] += off; });
        }
        k = q;
      }
      s = e;
    }
  }
}

/** Route a set of connections: select ports, find paths, and stagger. rects contains all objects (obstacles); conns contains only connections to draw. */
export function routeAll(rects: Record<string, Rect>, conns: Conn[], o: RouteOpts): Record<string, Route> {
  const ports = assignPorts(rects, conns, o.margin);
  const R = new Router(Object.values(rects), o);
  const out: Record<string, Route> = {};
  const list: Route[] = [];
  for (const c of conns) {
    const pp = ports[c.key]; if (!pp) continue;
    const A = rects[c.a], B = rects[c.b];
    const pts = (o.close ? closeFacing(A, B, pp.a, pp.b, o.close) : null) || R.route(pp.a, pp.b);
    const r = { key: c.key, kind: c.kind, a: pp.a, b: pp.b, pts };
    out[c.key] = r; list.push(r);
  }
  nudge(list, o.gap ?? o.margin * 0.35, o.margin * 0.75, Object.values(rects));
  return out;
}

/** Rounded polyline. */
export function pathD(p: Pt[], radius: number) {
  if (!p.length) return '';
  let d = `M ${f(p[0][0])} ${f(p[0][1])}`;
  for (let i = 1; i < p.length - 1; i++) {
    const a = p[i - 1], b = p[i], c = p[i + 1];
    const l1 = Math.hypot(b[0] - a[0], b[1] - a[1]), l2 = Math.hypot(c[0] - b[0], c[1] - b[1]);
    const r = Math.min(radius, l1 / 2, l2 / 2);
    if (r < 1e-6) { d += ` L ${f(b[0])} ${f(b[1])}`; continue; }
    const u = [(b[0] - a[0]) / l1, (b[1] - a[1]) / l1], w = [(c[0] - b[0]) / l2, (c[1] - b[1]) / l2];
    d += ` L ${f(b[0] - u[0] * r)} ${f(b[1] - u[1] * r)} Q ${f(b[0])} ${f(b[1])} ${f(b[0] + w[0] * r)} ${f(b[1] + w[1] * r)}`;
  }
  const z = p[p.length - 1];
  return d + ` L ${f(z[0])} ${f(z[1])}`;
}
const f = (x: number) => Math.round(x * 1000) / 1000;

/** Label position: midpoint of the longest segment, avoiding end stubs where possible; len is that segment's length. */
export function labelAt(p: Pt[]) {
  let best = -1, bl = -1;
  const inner = p.length > 3;
  for (let i = 0; i < p.length - 1; i++) {
    if (inner && (i === 0 || i === p.length - 2)) continue;
    const l = Math.hypot(p[i + 1][0] - p[i][0], p[i + 1][1] - p[i][1]);
    if (l > bl) { bl = l; best = i; }
  }
  if (best < 0) return { m: p[0] || [0, 0], len: 0, horiz: true };
  const a = p[best], b = p[best + 1];
  return { m: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], len: bl, horiz: Math.abs(a[1] - b[1]) < 1e-7 };
}

/** Translate the entire path when both endpoints move during dragging. */
export const shift = (p: Pt[], dx: number, dy: number) => p.map((q) => [q[0] + dx, q[1] + dy]);

/** Candidate label positions: 0.5 / 0.3 / 0.7 along each segment, longest first, avoiding end stubs where possible; prefer segments that fit the label. */
export function labelSpots(p: Pt[], w: number, h: number): Pt[] {
  const segs: { a: Pt; b: Pt; len: number; fit: boolean }[] = [];
  const inner = p.length > 3;
  for (let i = 0; i < p.length - 1; i++) {
    const a = p[i], b = p[i + 1], len = Math.hypot(b[0] - a[0], b[1] - a[1]);
    const hor = Math.abs(a[1] - b[1]) < 1e-7;
    segs.push({ a, b, len: len * (inner && (i === 0 || i === p.length - 2) ? 0.5 : 1), fit: len >= (hor ? w : h) + Math.min(w, h) * 0.6 });
  }
  segs.sort((x, y) => +y.fit - +x.fit || y.len - x.len);
  const out: Pt[] = [];
  for (const sg of segs) for (const t of sg.fit ? [0.5, 0.3, 0.7, 0.18, 0.82] : [0.5]) out.push([sg.a[0] + (sg.b[0] - sg.a[0]) * t, sg.a[1] + (sg.b[1] - sg.a[1]) * t]);
  return out;
}
/** Place each connection label without overlapping objects or placed labels; if no position fits, use the first candidate for required labels and hide others (visible on hover). */
export function placeLabels(items: { key: string; pts: Pt[]; w: number; h: number; required?: boolean }[], obstacles: Rect[]) {
  const placed: Rect[] = [], out: Record<string, Pt | null> = {};
  const hit = (r: Rect) => placed.some((q) => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0)
    || obstacles.some((q) => r.x0 < q.x1 && r.x1 > q.x0 && r.y0 < q.y1 && r.y1 > q.y0);
  for (const it of items) {
    const cand = labelSpots(it.pts, it.w, it.h);
    const box = (m: Pt): Rect => ({ x0: m[0] - it.w / 2, x1: m[0] + it.w / 2, y0: m[1] - it.h / 2, y1: m[1] + it.h / 2 });
    let got = cand.find((m) => !hit(box(m)));
    if (!got && it.required && cand.length) got = cand[0];
    out[it.key] = got || null;
    if (got) placed.push(box(got));
  }
  return out;
}
