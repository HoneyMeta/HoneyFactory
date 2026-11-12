// Floor plan geometry helpers (meters; plan Y points down; CAD angles: 0° points along +X, positive counterclockwise, screen up is 90°).
export type Pt = number[];

export const dist = (a: Pt, b: Pt) => Math.hypot(b[0] - a[0], b[1] - a[1]);
export const mid = (a: Pt, b: Pt): Pt => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
export const r2 = (x: number) => Math.round(x * 100) / 100;
export const rp = (p: Pt): Pt => [r2(p[0]), r2(p[1])];
export const same = (a: Pt, b: Pt, eps = 1e-6) => Math.abs(a[0] - b[0]) < eps && Math.abs(a[1] - b[1]) < eps;

/** Closest point on a segment: q closest point, t parameter (0~1), d distance. */
export function projSeg(p: Pt, a: Pt, b: Pt) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
  const t = L2 < 1e-12 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2));
  const q = [a[0] + t * dx, a[1] + t * dy];
  return { q, t, d: dist(p, q) };
}
/** Project a point onto an infinite line (unclamped). */
export function footLine(p: Pt, a: Pt, b: Pt) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L2 = dx * dx + dy * dy;
  const t = L2 < 1e-12 ? 0 : ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2;
  return { q: [a[0] + t * dx, a[1] + t * dy], t };
}

/** A wall is closed if its endpoints coincide (at least 4 points). */
export const isClosed = (pts: Pt[]) => pts.length >= 4 && same(pts[0], pts[pts.length - 1], 1e-3);
/** Element segments: close areas automatically; treat walls and aisles as polylines. */
export function segsOf(kind: string, pts: Pt[]): [Pt, Pt][] {
  const s: [Pt, Pt][] = [];
  for (let i = 0; i < pts.length - 1; i++) s.push([pts[i], pts[i + 1]]);
  if (kind === 'zones' && pts.length >= 3) s.push([pts[pts.length - 1], pts[0]]);
  return s;
}
export const polyLen = (pts: Pt[]) => pts.slice(1).reduce((t, q, i) => t + dist(pts[i], q), 0);

/** Point s meters along a polyline, with segment index and direction. */
export function pointAt(pts: Pt[], s: number) {
  let acc = 0;
  for (let i = 0; i < pts.length - 1; i++) {
    const L = dist(pts[i], pts[i + 1]);
    if (acc + L >= s || i === pts.length - 2) {
      const g = L < 1e-9 ? 0 : Math.max(0, Math.min(1, (s - acc) / L));
      const a = pts[i], b = pts[i + 1];
      return { p: [a[0] + (b[0] - a[0]) * g, a[1] + (b[1] - a[1]) * g], i, u: L < 1e-9 ? [1, 0] : [(b[0] - a[0]) / L, (b[1] - a[1]) / L] };
    }
    acc += L;
  }
  return { p: pts[0] || [0, 0], i: 0, u: [1, 0] };
}
/** Project a point onto a polyline; return distance s along it and distance d to it. */
export function sAt(pts: Pt[], p: Pt) {
  let acc = 0, best = { s: 0, d: Infinity, i: 0 };
  for (let i = 0; i < pts.length - 1; i++) {
    const L = dist(pts[i], pts[i + 1]), r = projSeg(p, pts[i], pts[i + 1]);
    if (r.d < best.d) best = { s: acc + r.t * L, d: r.d, i };
    acc += L;
  }
  return best;
}
/** Polyline section from s0~s1 (including intermediate vertices). */
export function subLine(pts: Pt[], s0: number, s1: number): Pt[] {
  const out: Pt[] = [pointAt(pts, s0).p];
  let acc = 0;
  for (let i = 1; i < pts.length - 1; i++) {
    acc += dist(pts[i - 1], pts[i]);
    if (acc > s0 + 1e-9 && acc < s1 - 1e-9) out.push(pts[i]);
  }
  out.push(pointAt(pts, s1).p);
  return out;
}

/** Wall doorway intervals [start, end] (distances along the wall, clamped to wall length with overlaps merged). */
export function doorSpans(w: any): [number, number][] {
  const total = polyLen(w.pts || []);
  const iv = (w.doors || []).map((d: any) => [Math.max(0, d.s - d.w / 2), Math.min(total, d.s + d.w / 2)] as [number, number]).filter((x: number[]) => x[1] - x[0] > 1e-3)
    .sort((a: number[], b: number[]) => a[0] - b[0]);
  const m: [number, number][] = [];
  for (const x of iv) { if (m.length && x[0] <= m[m.length - 1][1]) m[m.length - 1][1] = Math.max(m[m.length - 1][1], x[1]); else m.push([...x] as [number, number]); }
  return m;
}
/** Solid wall sections after doorway cutouts (polylines). Also usable for 3D walls: for (const seg of wallPieces(w)) … */
export function wallPieces(w: any): Pt[][] {
  const pts = w.pts || []; if (pts.length < 2) return [];
  const spans = doorSpans(w); if (!spans.length) return [pts];
  const total = polyLen(pts), out: Pt[][] = [];
  let s = 0;
  for (const [a, b] of spans) { if (a - s > 1e-3) out.push(subLine(pts, s, a)); s = b; }
  if (total - s > 1e-3) out.push(subLine(pts, s, total));
  return out;
}
/** Doorway geometry: start a, end b, wall direction u, width w. */
export function doorShapes(w: any) {
  return (w.doors || []).map((d: any, k: number) => {
    const a = pointAt(w.pts, Math.max(0, d.s - d.w / 2)), b = pointAt(w.pts, d.s + d.w / 2), c = pointAt(w.pts, d.s);
    return { k, a: a.p, b: b.p, c: c.p, u: c.u, w: d.w };
  });
}
/** When wall vertices change, doorways follow their segment and relative position within it. */
export function remapDoors(oldPts: Pt[], newPts: Pt[], doors: any[]) {
  if (!doors?.length) return doors;
  const cum = (pts: Pt[]) => { const c = [0]; for (let i = 1; i < pts.length; i++) c.push(c[i - 1] + dist(pts[i - 1], pts[i])); return c; };
  const co = cum(oldPts), cn = cum(newPts);
  return doors.map((d) => {
    let i = 0; while (i < co.length - 2 && co[i + 1] < d.s) i++;
    const Lo = co[i + 1] - co[i] || 1, f = (d.s - co[i]) / Lo;
    const j = Math.min(i, cn.length - 2); if (j < 0) return d;
    return { ...d, s: r2(cn[j] + f * (cn[j + 1] - cn[j])) };
  });
}

/** CAD angle (degrees, 0~360). */
export function angleDeg(a: Pt, b: Pt) { const g = (Math.atan2(-(b[1] - a[1]), b[0] - a[0]) * 180) / Math.PI; return (g + 360) % 360; }
export function polar(a: Pt, len: number, deg: number): Pt { const r = (deg * Math.PI) / 180; return [a[0] + len * Math.cos(r), a[1] - len * Math.sin(r)]; }
/** Orthogonal constraint: snap to X or Y, whichever has the larger offset. */
export function ortho(ref: Pt, p: Pt): Pt { return Math.abs(p[0] - ref[0]) >= Math.abs(p[1] - ref[1]) ? [p[0], ref[1]] : [ref[0], p[1]]; }

export function bbox(points: Pt[]) {
  if (!points.length) return null;
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  return { x0: Math.min(...xs), y0: Math.min(...ys), x1: Math.max(...xs), y1: Math.max(...ys) };
}
/** Nice tick interval: 1, 2, 5 × 10ⁿ, no smaller than min. */
export function niceStep(min: number) {
  const e = Math.pow(10, Math.floor(Math.log10(Math.max(min, 1e-6))));
  for (const m of [1, 2, 5, 10]) if (m * e >= min) return m * e;
  return 10 * e;
}
export const fmtM = (x: number) => (Math.abs(x) >= 100 || Number.isInteger(x) ? x.toFixed(0) : Math.abs(x) >= 10 ? x.toFixed(1) : x.toFixed(2));
/** Swap length and width when equipment is rotated 90°/270°. */
export const extOf = (b: any) => (Math.round((b.rot || 0) / 90) % 2 ? [b.size[1], b.size[0]] : [b.size[0], b.size[1]]);
