// Floor-plan sketch: reduce factory/template layouts to rectangles in a small SVG (start-page "New" previews and "Recently Opened" thumbnails when no screenshot exists).
// Same data format as backend vfactory/sketch.py: { floor: [width, depth], areas: [[x0, x1, color]], r: [[x, y, w, h, type]] }; coordinates in meters, x/y denote centers.
export type Sketch = { floor: number[]; areas?: any[][]; r: any[][] };

const CONTROL = new Set(['plc', 'hmi', 'soft_plc']), NETWORK = new Set(['gateway', 'switch', 'router', 'iot_gateway']), IT = new Set(['scada', 'mes', 'erp', 'historian']);
const SKIP = new Set(['transporter', 'operators', 'agv_fleet', 'crew']);
const kindOf = (t: string) => (CONTROL.has(t) ? 'c' : NETWORK.has(t) ? 'n' : IT.has(t) ? 'i' : t === 'cell' ? 'u' : 'p');
const r2 = (v: any, d = 0) => { const n = Number(v); return Number.isFinite(n) ? Math.round(n * 100) / 100 : d; };

/** Compute a sketch from the editor model (ed.model). */
export function sketchFromModel(m: any, limit = 300): Sketch | null {
  if (!m) return null;
  const rects: any[][] = [];
  for (const b of m.blocks || []) {
    if (!b || SKIP.has(b.type)) continue;
    let [w, h] = [r2(b.size?.[0], 3), r2(b.size?.[1] ?? b.size?.[0], 3)];
    if (Math.round(r2(b.rot)) % 180 === 90) [w, h] = [h, w];
    const x = r2(b.pos?.[0]), y = r2(b.pos?.[1]);
    rects.push([x, y, w, h, kindOf(b.type)]);
    if (b.type === 'cell') for (const c of b.params?.cell?.components || []) {
      const small = /sensor|button|switch|lamp|estop|knob|display|pot|encoder|proximity|photo/.test(String(c.type || ''));
      let [cw, ch] = [r2(c.size?.[0], 0.5), r2(c.size?.[1] ?? c.size?.[0], 0.5)];
      if (Math.round(r2(c.rot)) % 180 === 90) [cw, ch] = [ch, cw];
      rects.push([r2(x + r2(c.pos?.[0])), r2(y + r2(c.pos?.[1])), Math.max(cw, 0.25), Math.max(ch, 0.25), small ? 's' : 'e']);
    }
    if (rects.length >= limit) break;
  }
  if (!rects.length) return null;
  const fl = m.plant?.floor || m.layout?.floor;
  const floor = Array.isArray(fl) && fl.length >= 2 ? [r2(fl[0], 40), r2(fl[1], 30)]
    : [Math.max(...rects.map((r) => r[0] + r[2] / 2)) + 2, Math.max(...rects.map((r) => r[1] + r[3] / 2)) + 2];
  const areas = (m.areas || []).filter((a: any) => Array.isArray(a?.x)).slice(0, 20).map((a: any) => [r2(a.x[0]), r2(a.x[1]), String(a.color || '')]);
  return { floor, areas, r: rects };
}

const FILL: Record<string, string> = { p: '#3f74c4', c: '#d9822b', n: '#7a5ad8', i: '#1f8f4e', u: '#0a8aa6', e: '#6c8fb0', s: '#d9a93a' };
const esc = (s: string) => s.replace(/[^#0-9a-fA-F]/g, '');

/** Render as an SVG string (viewBox fits the sketch, scaled proportionally and centered). Light canvas background (--hm-canvas) with a fine cobalt-gray grid. */
export function sketchSvg(sk: Sketch | null | undefined, w = 320, h = 180): string {
  const bg = '#f3f6fa', grid = '#e2e8f0', edge = '#cbd5e1';
  if (!sk || !sk.r?.length) {
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"><rect width="${w}" height="${h}" fill="${bg}"/>`
      + gridLines(w, h, grid) + `<rect x="${w * 0.2}" y="${h * 0.25}" width="${w * 0.6}" height="${h * 0.5}" rx="6" fill="none" stroke="${edge}" stroke-dasharray="6 5" stroke-width="1.5"/></svg>`;
  }
  // Bounds: all rectangle outlines, not the entire plant, so equipment does not occupy just one corner
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y, rw, rh] of sk.r) { x0 = Math.min(x0, x - rw / 2); y0 = Math.min(y0, y - rh / 2); x1 = Math.max(x1, x + rw / 2); y1 = Math.max(y1, y + rh / 2); }
  const pad = Math.max(1, (x1 - x0) * 0.06, (y1 - y0) * 0.06);
  x0 -= pad; y0 -= pad; x1 += pad; y1 += pad;
  const s = Math.min(w / (x1 - x0), h / (y1 - y0));
  const ox = (w - (x1 - x0) * s) / 2, oy = (h - (y1 - y0) * s) / 2;
  const X = (v: number) => +(ox + (v - x0) * s).toFixed(1), Y = (v: number) => +(oy + (v - y0) * s).toFixed(1);
  const fill = FILL;
  let out = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}"><rect width="${w}" height="${h}" fill="${bg}"/>` + gridLines(w, h, grid);
  for (const a of sk.areas || []) {
    const ax0 = Math.max(X(a[0]), 0), ax1 = Math.min(X(a[1]), w);
    if (ax1 - ax0 < 2) continue;
    const c = esc(String(a[2] || '')) || '#e9eef3';
    out += `<rect x="${ax0}" y="${Y(y0 + pad * 0.4)}" width="${(ax1 - ax0).toFixed(1)}" height="${(Y(y1 - pad * 0.4) - Y(y0 + pad * 0.4)).toFixed(1)}" fill="${c}" opacity="0.55"/>`;
  }
  // Draw cell frames below components
  const order = [...sk.r].sort((a, b) => (a[4] === 'u' ? -1 : 0) - (b[4] === 'u' ? -1 : 0));
  for (const [x, y, rw, rh, k] of order) {
    const pw = Math.max(1.5, rw * s), ph = Math.max(1.5, rh * s);
    const f = fill[k] || fill.p;
    if (k === 'u') out += `<rect x="${(X(x - rw / 2)).toFixed(1)}" y="${(Y(y - rh / 2)).toFixed(1)}" width="${pw.toFixed(1)}" height="${ph.toFixed(1)}" rx="3" fill="${f}" fill-opacity="0.1" stroke="${f}" stroke-width="1.2"/>`;
    else out += `<rect x="${(X(x - rw / 2)).toFixed(1)}" y="${(Y(y - rh / 2)).toFixed(1)}" width="${pw.toFixed(1)}" height="${ph.toFixed(1)}" rx="${Math.min(3, pw / 4, ph / 4).toFixed(1)}" fill="${f}" fill-opacity="${k === 'e' ? 0.75 : 0.9}"/>`;
  }
  return out + '</svg>';
}
function gridLines(w: number, h: number, c: string) {
  let g = '';
  for (let x = 20; x < w; x += 20) g += `<line x1="${x}" y1="0" x2="${x}" y2="${h}" stroke="${c}" stroke-width="1"/>`;
  for (let y = 20; y < h; y += 20) g += `<line x1="0" y1="${y}" x2="${w}" y2="${y}" stroke="${c}" stroke-width="1"/>`;
  return g;
}
export const sketchUrl = (sk: Sketch | null | undefined, w = 320, h = 180) => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(sketchSvg(sk, w, h));
