// Automatic material transfer (4.6): add conveyors where floor-plan material links span a 3D gap (> 1.5 m) without transfer equipment,
// so parts no longer "teleport" across open space.
//   - Use floor-plan routing (routeAll in editor/plan/route.ts, with the same ports and obstacle avoidance); lay 3D equipment along the same polyline;
//     parallel lines offset in the floor plan are not offset in 3D; merge overlapping segments into a shared trunk, with turntables at branches;
//   - Lay the full route when endpoints are over 1.5 m apart; fill small gaps of 0.4~1.5 m with short sections (none for touching endpoints);
//   - Between machines: belt conveyors (Kenney conveyor models, matching built-in conveyor sections), with 90° turntables at corners;
//     if one end is a buffer / material store / incoming / outgoing: roller conveyors (unpowered rollers + side plates + legs); fill even small gaps;
//     across floor-plan aisles: elevate the section (3.2 m aisle bridge, lifts at both ends), with no legs in the aisle;
//   - Links via transport vehicles (via): no conveyors; draw AGV travel lines on the floor (actual vehicle paths: fleet corridor polylines / straight lines without a route network) + direction arrows;
//     with an AGV route network in the layout, vehicles follow it; the "Walls / Areas / Aisles / Route Network" layer already draws it, so do not duplicate it here;
//   - Molten iron and ladles (melt / ladle) use crane and ladle animations, not conveyors; molding sand and molds (sand / mold) use belts without part animations;
//   - Part animation: simulation links are instantaneous; use changes in buffer counts (kpi.buffers: the link's own small buffer or endpoint buffers)
//     to place a box on the corresponding conveyor section and move it along the full route over a short interval (scaled by simulation speed, 0.8~6 s), without changing the simulation.
// Rebuild only when geometry changes (equipment position / size / floor, links, aisles, filters); rollers, legs, belt sections, and boxes are instanced meshes;
// Hide rollers and legs when zoomed out (> 130 m, semantic zoom). The "Material Transfer (Auto)" layer controls visibility (scene.setLayer('transfer')).
// Test hooks: window.__vfScene.transfer.sections() / moversNow() / spawn(link) / preview(model) / stats().
import * as THREE from 'three';
import { watch } from 'vue';
import { routeAll, type Conn, type Pt, type Rect } from '../editor/plan/route';
import { extOf } from '../editor/plan/geom';
import { ed } from '../editor/store';

/** Route lengths above MIN_LEN count as gaps (lay full conveyor sections); also fill small FEED_MIN~MIN_LEN gaps to hide visible floor seams between machines. */
const MIN_LEN = 1.5, FEED_MIN = 0.4;
/** Match routing parameters at typical floor-plan zoom levels (6~9 pixels per meter). */
const RK = 8, MARGIN = Math.max(0.3, Math.min(1.5, 14 / RK));
// No parallel offsets (gap 0): lines offset in the floor plan share one 3D trunk (merge overlapping segments), rather than parallel conveyors
const RO = { margin: MARGIN, bend: MARGIN * 3, gap: 0, close: MARGIN * 2 };
const HIDE = new Set(['agv_fleet', 'worker_crew', 'transporter', 'operators']);
const STORE = new Set(['buffer', 'storage', 'sink', 'source', 'warehouse', 'receiving']);
const NO_PARTS = new Set(['sand', 'mold']);
const SKIP = new Set(['melt', 'ladle']);
const NONPROC = new Set(['plc', 'hmi', 'gateway', 'switch', 'scada', 'mes']);
const BELT_W = 0.75, ROLL_W = 0.65, H = 0.8, BRIDGE_H = 3.2, LOD_FAR = 130;

export type Section = { link: string; from: string; to: string; kind: 'belt' | 'roller' | 'agv'; len: number; pts: Pt[]; floor: string; over: boolean; parts: boolean; queue: string; dir: number };
type Mover = { sec: number; t: number; T: number };

const mat = (c: number, o: any = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.6, metalness: 0.25, ...o });

function agvTexture() {
  const c = document.createElement('canvas'); c.width = 128; c.height = 64;
  const g = c.getContext('2d')!;
  g.fillStyle = 'rgba(242,140,40,0.30)'; g.fillRect(0, 6, 128, 52);
  g.fillStyle = 'rgba(242,140,40,0.95)'; g.fillRect(0, 4, 128, 5); g.fillRect(0, 55, 128, 5);
  g.strokeStyle = 'rgba(255,255,255,0.95)'; g.lineWidth = 7; g.lineCap = 'round'; g.lineJoin = 'round';
  g.beginPath(); g.moveTo(50, 18); g.lineTo(70, 32); g.lineTo(50, 46); g.stroke();
  const t = new THREE.CanvasTexture(c); t.wrapS = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}

/** Instance group: collect matrices first, then create one InstancedMesh. */
class Batch {
  m: THREE.Matrix4[] = [];
  constructor(public geo: THREE.BufferGeometry, public mt: THREE.Material | THREE.Material[], public shadow = true) {}
  add(m: THREE.Matrix4) { this.m.push(m); }
  build(): THREE.InstancedMesh | null {
    if (!this.m.length) return null;
    const im = new THREE.InstancedMesh(this.geo, this.mt as any, this.m.length);
    this.m.forEach((x, i) => im.setMatrixAt(i, x));
    im.castShadow = this.shadow; im.receiveShadow = true; im.instanceMatrix.needsUpdate = true; im.computeBoundingSphere();
    return im;
  }
}
const Q = new THREE.Quaternion(), V = new THREE.Vector3(), S = new THREE.Vector3();
const trs = (x: number, y: number, z: number, yaw: number, sx: number, sy: number, sz: number, pitch = 0) => {
  Q.setFromEuler(new THREE.Euler(0, yaw, pitch, 'YXZ'));
  return new THREE.Matrix4().compose(V.set(x, y, z), Q, S.set(sx, sy, sz));
};

export class Transfer {
  s: any; group = new THREE.Group(); detail = new THREE.Group(); moverMesh: THREE.InstancedMesh;
  secs: Section[] = []; paths: { pts: THREE.Vector3[]; acc: number[]; len: number }[] = [];
  movers: Mover[] = []; visible = true; dirty = true; rev = 0;
  private last: Record<string, number> | null = null; private lastState: any = null; private rr: Record<string, number> = {};
  private agvTex = agvTexture(); private stops: (() => void)[] = [];
  private kenney: any = null;

  constructor(s: any) {
    this.s = s;
    this.group.name = 'transfer'; this.group.add(this.detail);
    const box = new THREE.BoxGeometry(0.46, 0.34, 0.46);
    this.moverMesh = new THREE.InstancedMesh(box, mat(0xb07a3a, { roughness: 0.8, metalness: 0.05 }), 400);
    this.moverMesh.count = 0; this.moverMesh.castShadow = true; this.moverMesh.frustumCulled = false;
    s.scene.add(this.group);
    // Rebuild only when the geometry signature changes (300 ms debounce while dragging equipment)
    let tm: any = null;
    this.stops.push(watch(() => sig(), () => { clearTimeout(tm); tm = setTimeout(() => { this.dirty = true; }, 300); }));
    s.beforeRender.push(this.pre);
    s.disposers.push(() => this.dispose());
  }

  setVisible(on: boolean) { this.visible = on; this.group.visible = on; if (!on) { this.movers.length = 0; this.moverMesh.count = 0; } }

  // ---------- Generation ----------
  rebuild() {
    this.dirty = false; this.rev++;
    for (const o of [...this.group.children]) if (o !== this.detail) this.group.remove(o);
    for (const o of [...this.detail.children]) this.detail.remove(o);
    this.group.traverse((o: any) => { if (o.isInstancedMesh && o !== this.moverMesh) o.dispose?.(); });
    this.secs = []; this.paths = []; this.movers.length = 0; this.last = null;
    const m = ed.model; if (!m?.blocks || !this.s.meta) return;
    this.secs = sections(m);
    this.group.add(this.moverMesh);
    const s = this.s, floors = m.plant?.layout?.floors || [];
    const fz = (id: string) => floors.find((f: any) => f.id === id)?.z || 0;
    const steel = mat(0x8a96a3), dark = mat(0x3d444b), yel = mat(0xf2c230, { roughness: 0.5 }), roller = mat(0xb9c2cb, { metalness: 0.6, roughness: 0.35 }), belt = mat(0x2d3238, { roughness: 0.9, metalness: 0.05 });
    const unit = new THREE.BoxGeometry(1, 1, 1);
    const rollGeo = new THREE.CylinderGeometry(0.035, 0.035, 1, 8).rotateX(Math.PI / 2);
    const B = { rail: new Batch(unit, steel), leg: new Batch(unit, dark, false), roll: new Batch(rollGeo, roller, false), slab: new Batch(unit, belt), turn: new Batch(unit, steel),
      disc: new Batch(new THREE.CylinderGeometry(0.5, 0.5, 1, 20), dark, false), tower: new Batch(unit, yel), guard: new Batch(unit, mat(0x6b747d, { transparent: true, opacity: 0.55 }), false) };
    const kn = this.kenneyParts();
    const knB = kn ? kn.map((k: any) => new Batch(k.geo, k.mat)) : null;
    const aisles = aisleRects(m);
    const agvPos: number[] = [], agvUv: number[] = [], agvIdx: number[] = [];
    const runs: Record<string, any[]> = {}, corners: Record<string, { p: Pt; floor: string; belt: boolean; hs: Set<number> }> = {};
    this.secs.forEach((sec) => {
      const z0 = fz(sec.floor);
      const P = (q: Pt, h: number) => s.P(q[0], q[1], z0 + h) as THREE.Vector3;
      if (sec.kind === 'agv') {                       // Floor travel line: a colored strip with arrows (UV along its length)
        let acc = 0;
        for (let i = 0; i < sec.pts.length - 1; i++) {
          const a = P(sec.pts[i], 0.035), b = P(sec.pts[i + 1], 0.035), d = b.clone().sub(a), len = d.length(); if (len < 0.05) continue;
          const n = new THREE.Vector3(-d.z, 0, d.x).normalize().multiplyScalar(0.55), k = agvPos.length / 3;
          for (const p of [a.clone().add(n), a.clone().sub(n), b.clone().add(n), b.clone().sub(n)]) agvPos.push(p.x, p.y, p.z);
          agvUv.push(acc / 1.4, 1, acc / 1.4, 0, (acc + len) / 1.4, 1, (acc + len) / 1.4, 0); acc += len;
          agvIdx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2);
        }
        this.paths.push(pathOf(sec.pts.map((q) => P(q, 0.4))));
        return;
      }
      // Part path: set each segment's height based on elevation; add a vertical point at height transitions (lift tower)
      const pts = sec.pts, path3: THREE.Vector3[] = [];
      for (let i = 0; i < pts.length - 1; i++) {
        const a = pts[i], b = pts[i + 1], over = crosses(a, b, aisles), h = over ? BRIDGE_H : H;
        const prevH = i > 0 ? (crosses(pts[i - 1], a, aisles) ? BRIDGE_H : H) : h;
        if (i === 0 && over) path3.push(P(a, H + 0.25));             // Lift tower at the port: rise first
        if (prevH !== h) path3.push(P(a, prevH + 0.25));
        path3.push(P(a, h + 0.25));
        if (i === pts.length - 2) { path3.push(P(b, h + 0.25)); if (over) path3.push(P(b, H + 0.25)); }
        // Conveyors: group horizontal / vertical segments by supporting line, then merge overlaps (one shared trunk for multiple links)
        const hor = Math.abs(a[1] - b[1]) < 1e-6, c = hor ? a[1] : a[0], lo = Math.min(hor ? a[0] : a[1], hor ? b[0] : b[1]), hi = Math.max(hor ? a[0] : a[1], hor ? b[0] : b[1]);
        if (hi - lo < 1e-3) continue;
        (runs[`${sec.floor}|${hor ? 'h' : 'v'}|${Math.round(c * 1000)}`] ||= []).push({ lo, hi, c, hor, belt: sec.kind === 'belt', floor: sec.floor });
      }
      for (let i = 1; i < pts.length - 1; i++) {
        const k = `${sec.floor}|${Math.round(pts[i][0] * 1000)}|${Math.round(pts[i][1] * 1000)}`;
        const cn = (corners[k] ||= { p: pts[i], floor: sec.floor, belt: false, hs: new Set<number>() });
        cn.belt ||= sec.kind === 'belt';
        cn.hs.add(crosses(pts[i - 1], pts[i], aisles) ? BRIDGE_H : H); cn.hs.add(crosses(pts[i], pts[i + 1], aisles) ? BRIDGE_H : H);
      }
      this.paths.push(pathOf(path3));
    });
    // Merge overlapping / adjacent collinear segments; leave room for turntables at corner endpoints
    const isCorner = (floor: string, p: Pt) => !!corners[`${floor}|${Math.round(p[0] * 1000)}|${Math.round(p[1] * 1000)}`];
    for (const list of Object.values(runs)) {
      list.sort((p, q) => p.lo - q.lo);
      const merged: any[] = [];
      for (const r of list) { const t = merged[merged.length - 1]; if (t && r.lo <= t.hi + 0.05) { t.hi = Math.max(t.hi, r.hi); t.belt ||= r.belt; } else merged.push({ ...r }); }
      for (const r of merged) {
        const A: Pt = r.hor ? [r.lo, r.c] : [r.c, r.lo], Bp: Pt = r.hor ? [r.hi, r.c] : [r.c, r.hi];
        this.run(B, knB, kn, A, Bp, r.belt, crosses(A, Bp, aisles), isCorner(r.floor, A), isCorner(r.floor, Bp), fz(r.floor), aisles);
      }
    }
    // Turntable (same height) / lift tower (different segment heights)
    for (const cn of Object.values(corners)) {
      const W = cn.belt ? BELT_W : ROLL_W, c = s.P(cn.p[0], cn.p[1], fz(cn.floor)) as THREE.Vector3, hs = [...cn.hs], hh = Math.max(...hs);
      if (hs.length > 1) B.tower.add(trs(c.x, c.y + hh / 2, c.z, 0, W + 0.2, hh, W + 0.2));
      else { B.turn.add(trs(c.x, c.y + (hh - 0.06) / 2, c.z, 0, W, hh - 0.06, W)); B.disc.add(trs(c.x, c.y + hh - 0.03, c.z, 0, W * 0.9, 0.05, W * 0.9)); }
    }
    for (const [k, b] of Object.entries(B)) { const im = b.build(); if (im) (k === 'leg' || k === 'roll' ? this.detail : this.group).add(im); }
    if (knB) for (const b of knB) { const im = b.build(); if (im) this.group.add(im); }
    if (agvIdx.length) {
      const g = new THREE.BufferGeometry();
      g.setAttribute('position', new THREE.Float32BufferAttribute(agvPos, 3)); g.setAttribute('uv', new THREE.Float32BufferAttribute(agvUv, 2)); g.setIndex(agvIdx);
      const ribbon = new THREE.Mesh(g, new THREE.MeshBasicMaterial({ map: this.agvTex, transparent: true, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -1 }));
      ribbon.renderOrder = 2; ribbon.name = 'agv-path'; this.group.add(ribbon);
    }
    this.group.visible = this.visible;
  }

  /** Straight conveyor section (a → b): belt (Kenney conveyor sections) or rollers (side plates + rollers), with paired legs every 1.6 m; elevated sections crossing aisles have no aisle legs and a safety net underneath.
   *  ca / cb: this end is at a corner (leave room for half a turntable). */
  run(B: any, knB: Batch[] | null, kn: any[] | null, a0: Pt, b0: Pt, belt: boolean, over: boolean, ca: boolean, cb: boolean, z0: number, aisles: Rect[]) {
    const s = this.s, W = belt ? BELT_W : ROLL_W, top = over ? BRIDGE_H : H;
    const dx = b0[0] - a0[0], dy = b0[1] - a0[1], L = Math.hypot(dx, dy); if (L < 1e-3) return;
    const ux = dx / L, uy = dy / L, yaw = -Math.atan2(dy, dx), t0 = ca ? W / 2 : 0, len = L - t0 - (cb ? W / 2 : 0);
    if (len < 0.05) return;
    const a: Pt = [a0[0] + ux * t0, a0[1] + uy * t0];
    const P = (q: Pt, h = 0) => s.P(q[0], q[1], z0 + h) as THREE.Vector3;
    const mid = P([a[0] + ux * len / 2, a[1] + uy * len / 2]);
    if (belt && knB && kn && !over) {                                 // Kenney conveyor section (same model as built-in equipment conveyors)
      const n = Math.max(1, Math.round(len / 1.6)), pl = len / n;
      for (let k = 0; k < n; k++) {
        const c = P([a[0] + ux * (k + 0.5) * pl, a[1] + uy * (k + 0.5) * pl]);
        const m4 = trs(c.x, c.y, c.z, yaw, pl / 2 * 1.01, H / 0.4, W);
        knB.forEach((bt, j) => bt.add(m4.clone().multiply(kn[j].local)));
      }
      return;
    }
    if (belt) B.slab.add(trs(mid.x, mid.y + top - 0.06, mid.z, yaw, len, 0.1, W * 0.86));
    for (const sd of [-1, 1]) B.rail.add(trs(mid.x - uy * sd * W / 2, mid.y + top - 0.02, mid.z + ux * sd * W / 2, yaw, len, belt ? 0.16 : 0.12, 0.05));   // Plan normal (plan y → world z)
    if (!belt) for (let d = 0.12; d < len; d += 0.22) { const c = P([a[0] + ux * d, a[1] + uy * d]); B.roll.add(trs(c.x, c.y + top - 0.04, c.z, yaw + Math.PI / 2, 1, 1, W * 0.94)); }
    for (let d = Math.min(0.3, len / 2); d < len; d += 1.6) {
      const q: Pt = [a[0] + ux * d, a[1] + uy * d];
      if (over && inAny(q, aisles, 0.3)) continue;
      for (const sd of [-1, 1]) { const c = P([q[0] - uy * sd * (W / 2 - 0.04), q[1] + ux * sd * (W / 2 - 0.04)]); B.leg.add(trs(c.x, c.y + (top - 0.1) / 2, c.z, yaw, 0.06, top - 0.1, 0.06)); }
    }
    if (over) B.guard.add(trs(mid.x, mid.y + top - 0.24, mid.z, yaw, len, 0.03, W * 0.9));   // Catch net under the aisle bridge (semi-transparent)
    if (over) for (const [q, c] of [[a0, ca], [b0, cb]] as [Pt, boolean][]) {      // Elevated section ends at a port (not a corner): place a lift tower at the port
      if (c) continue; const p = P(q); B.tower.add(trs(p.x, p.y + top / 2, p.z, yaw, W + 0.2, top, W + 0.2));
    }
  }

  /** Split the Kenney conveyor model into geometry + material + model-local matrix for instancing; fall back to a procedural belt if not loaded. */
  kenneyParts() {
    if (this.kenney !== null) return this.kenney || null;
    const g = this.s.assets?.lib?.get('conveyor-long-stripe-sides');
    if (!g) { this.kenney = false; return null; }
    g.scene.updateMatrixWorld(true);
    const out: any[] = [];
    g.scene.traverse((o: any) => { if (o.isMesh) out.push({ geo: o.geometry, mat: o.material, local: o.matrixWorld.clone() }); });
    this.kenney = out.length ? out : false;
    return this.kenney || null;
  }

  // ---------- Part animation ----------
  private pre = (dt: number) => {
    if (this.dirty && this.s.meta && ed.model) this.rebuild();
    if (!this.visible || !this.secs.length) return;
    const cam = this.s.camera.position.distanceTo(this.s.controls.target);
    this.detail.visible = cam < LOD_FAR;
    const st = this.s.state;
    if (st && st !== this.lastState) { this.lastState = st; this.onState(st); }
    const run = st && !st.paused;
    const m4 = new THREE.Matrix4(); let n = 0;
    for (let i = this.movers.length - 1; i >= 0; i--) {
      const mv = this.movers[i];
      if (run) mv.t += dt;
      if (mv.t >= mv.T) { this.movers.splice(i, 1); continue; }
    }
    for (const mv of this.movers) {
      const p = this.paths[mv.sec]; if (!p || n >= 400) continue;
      const q = at(p, (mv.t / mv.T) * p.len);
      m4.makeTranslation(q.x, q.y, q.z); this.moverMesh.setMatrixAt(n++, m4);
    }
    this.moverMesh.count = n; this.moverMesh.instanceMatrix.needsUpdate = true;
    this.agvTex.offset.x -= dt * 0.25;
  };

  /** Buffer count changes → place boxes on the corresponding conveyor segment (link/downstream buffer: increase; upstream buffer: decrease; distribute round-robin across links sharing a buffer). */
  private onState(st: any) {
    const buf: Record<string, number> = st.kpi?.buffers || {};
    const prev = this.last; this.last = { ...buf };
    if (!prev) return;
    const speed = Math.max(1, +st.speed || 1);
    const byQ: Record<string, number[]> = {};
    this.secs.forEach((s, i) => { if (s.parts && s.queue) (byQ[s.queue + ':' + s.dir] ||= []).push(i); });
    for (const [key, list] of Object.entries(byQ)) {
      const [q, d] = [key.slice(0, key.lastIndexOf(':')), +key.slice(key.lastIndexOf(':') + 1)];
      if (!(q in buf) || !(q in prev)) continue;
      let k = d > 0 ? buf[q] - prev[q] : prev[q] - buf[q];
      k = Math.min(k, 6);
      for (let j = 0; j < k; j++) { const r = (this.rr[key] = ((this.rr[key] ?? -1) + 1) % list.length); this.spawnSec(list[r], speed, j); }
    }
  }
  spawnSec(i: number, speed = 10, lag = 0) {
    const p = this.paths[i]; if (!p || this.movers.length >= 400) return;
    if (this.movers.filter((m) => m.sec === i).length >= 14) return;
    const T = Math.max(0.8, Math.min(6, p.len / (0.4 * speed)));
    this.movers.push({ sec: i, t: -lag * 0.35, T });
  }

  // ---------- Test hooks ----------
  sections() { return this.secs.map((s, i) => ({ ...s, pts: s.pts.map((q) => [+q[0].toFixed(2), +q[1].toFixed(2)]), len: +s.len.toFixed(2), idx: i })); }
  moversNow() {
    return this.movers.filter((m) => m.t >= 0).map((m) => { const p = this.paths[m.sec], q = at(p, (m.t / m.T) * p.len); return { link: this.secs[m.sec].link, f: +(m.t / m.T).toFixed(3), x: +(q.x + this.s.cx).toFixed(2), y: +(q.z + this.s.cy).toFixed(2), h: +q.y.toFixed(2) }; });
  }
  /** Compute conveyor segments for a model (e.g. a repositioned copy) without changing the scene, for tests/previews. */
  preview(model: any) { return sections(model).map((x) => ({ link: x.link, kind: x.kind, len: +x.len.toFixed(2), over: x.over })); }
  spawn(link: string) { const i = this.secs.findIndex((s) => s.link === link); if (i >= 0) this.spawnSec(i, 1); return i >= 0; }
  stats() {
    let inst = 0, calls = 0;
    this.group.traverse((o: any) => { if (o.isInstancedMesh) { inst += o.count; calls++; } else if (o.isMesh) calls++; });
    return { sections: this.secs.length, instances: inst, drawCalls: calls, rev: this.rev, detail: this.detail.visible };
  }

  dispose() { for (const f of this.stops) f(); this.stops = []; this.s.scene.remove(this.group); }
}

// ---------- Pure functions: routes → conveyor segments ----------
function sig() {
  const m = ed.model; if (!m) return '';
  const bl = (m.blocks || []).map((b: any) => [b.id, b.type, b.pos?.[0], b.pos?.[1], b.size?.[0], b.size?.[1], b.rot || 0, b.floor || ''].join(','));
  const ln = (m.links || []).filter((l: any) => (l.kind || 'material') === 'material').map((l: any) => [l.id, l.from, l.to, l.from_port, l.to_port, l.via || ''].join(','));
  const L = m.plant?.layout || {};
  return JSON.stringify([bl, ln, L.aisles || [], (L.paths?.edges || []).length, L.floors || [], ed.filter?.layers || {}]);
}

const visibleLayer = (b: any) => ed.filter?.layers?.[ed.cat?.types?.[b.type]?.layer || (NONPROC.has(b.type) ? 'x' : 'process')] !== false;

/** Obstacle rectangles match the floor plan: production equipment uses its footprint; control/communication/information systems use their floor-plan symbol size (at RK scale). */
function rectOf(b: any): Rect {
  if (!NONPROC.has(b.type)) { const [w, h] = extOf(b); return { x0: b.pos[0] - w / 2, y0: b.pos[1] - h / 2, x1: b.pos[0] + w / 2, y1: b.pos[1] + h / 2 }; }
  const s = Math.max(0.8, Math.min(1.3, RK / 7)) / RK; return { x0: b.pos[0] - 22 * s, y0: b.pos[1] - 19 * s, x1: b.pos[0] + 22 * s, y1: b.pos[1] + 19 * s };
}

export function sections(m: any): Section[] {
  const blocks: any[] = (m.blocks || []).filter((b: any) => b.pos && b.size);
  const by: Record<string, any> = Object.fromEntries(blocks.map((b) => [b.id, b]));
  const links: any[] = (m.links || []).filter((l: any) => (l.kind || 'material') === 'material' && by[l.from] && by[l.to] && l.from !== l.to);
  const out: Section[] = [];
  const queueOf = (l: any): [string, number] => {
    const A = by[l.from], B = by[l.to];
    if (A.type === 'buffer' && B.type === 'buffer') return ['', 0];
    if (A.type === 'buffer') return [A.id, -1];          // Upstream buffer decreases = a part departs
    if (B.type === 'buffer') return [B.id, 1];           // Downstream buffer increases = a part arrives
    return [l.id, 1];                                    // The link's own small buffer
  };
  const floorsOf = new Set(blocks.map((b) => b.floor || 'F1'));
  const pathsOn = (m.plant?.layout?.paths?.edges || []).length > 0;
  for (const f of floorsOf) {
    const on = blocks.filter((b) => (b.floor || 'F1') === f && visibleLayer(b));
    const R: Record<string, Rect> = Object.fromEntries(on.map((b) => [b.id, rectOf(b)]));
    const conns: Conn[] = [];
    for (const l of links) {
      if (!R[l.from] || !R[l.to] || l.via) continue;
      if (SKIP.has(l.from_port) || SKIP.has(l.to_port)) continue;
      if (HIDE.has(by[l.from].type) || HIDE.has(by[l.to].type)) continue;
      conns.push({ key: l.id, a: l.from, b: l.to, kind: 'material' });
    }
    const routed = routeAll(R, conns, RO);
    for (const l of links) {
      const A = by[l.from], B = by[l.to];
      if ((A.floor || 'F1') !== f) continue;
      if (l.via) {                                          // Transfer vehicle: actual travel path
        const tr = by[l.via]; if (!tr || (B.floor || 'F1') !== f) continue;
        let pts: Pt[] | null = null;
        if (tr.type === 'agv_fleet') {
          const nodes = tr.params?.nodes || {}, cy = +(tr.params?.corridor_y ?? 0);
          const node = (b: any) => nodes[b.id] || nodes[String(b.id).toLowerCase().replace(/\d+$/, '')] || b.pos;
          const a = node(A), b = node(B);
          pts = Math.abs(a[1] - b[1]) > 0.5 || Math.abs(a[1] - cy) > 0.5 ? [[a[0], a[1]], [a[0], cy], [b[0], cy], [b[0], b[1]]] : [[a[0], a[1]], [b[0], b[1]]];
        } else if (tr.type === 'transporter' && !(pathsOn && (tr.params?.network ?? true))) pts = [[A.pos[0], A.pos[1]], [B.pos[0], B.pos[1]]];
        if (!pts) continue;
        const len = plen(pts);
        if (len > MIN_LEN) out.push({ link: l.id, from: l.from, to: l.to, kind: 'agv', len, pts, floor: f, over: false, parts: false, queue: '', dir: 0 });
        continue;
      }
      const r = routed[l.id]; if (!r) continue;
      const len = plen(r.pts), store = STORE.has(A.type) || STORE.has(B.type);
      if (len < FEED_MIN) continue;                       // Skip touching segments; bridge gaps of 0.4~1.5 m with a short segment to hide visible floor gaps
      const [queue, dir] = queueOf(l);
      const parts = !(NO_PARTS.has(l.from_port) || NO_PARTS.has(l.to_port)) && !!queue;
      out.push({ link: l.id, from: l.from, to: l.to, kind: store ? 'roller' : 'belt', len, pts: r.pts.map((q) => [q[0], q[1]]), floor: f, over: false, parts, queue, dir });
    }
  }
  const aisles = aisleRects(m);
  for (const s of out) if (s.kind !== 'agv') s.over = s.pts.some((q, i) => i < s.pts.length - 1 && crosses(q, s.pts[i + 1], aisles));
  return out;
}

const plen = (p: Pt[]) => p.reduce((t, q, i) => (i ? t + Math.hypot(q[0] - p[i - 1][0], q[1] - p[i - 1][1]) : 0), 0);

/** Aisles (layout polylines + width): convert only horizontal/vertical segments to rectangles; ignore diagonal segments. */
function aisleRects(m: any): Rect[] {
  const out: Rect[] = [];
  for (const a of m.plant?.layout?.aisles || []) {
    const w = (a.w ?? 3) / 2;
    for (let i = 0; i < (a.pts || []).length - 1; i++) {
      const p = a.pts[i], q = a.pts[i + 1];
      if (Math.abs(p[0] - q[0]) < 1e-6) out.push({ x0: p[0] - w, x1: p[0] + w, y0: Math.min(p[1], q[1]), y1: Math.max(p[1], q[1]) });
      else if (Math.abs(p[1] - q[1]) < 1e-6) out.push({ x0: Math.min(p[0], q[0]), x1: Math.max(p[0], q[0]), y0: p[1] - w, y1: p[1] + w });
    }
  }
  return out;
}
function crosses(a: Pt, b: Pt, rs: Rect[]) {
  const x0 = Math.min(a[0], b[0]), x1 = Math.max(a[0], b[0]), y0 = Math.min(a[1], b[1]), y1 = Math.max(a[1], b[1]);
  return rs.some((r) => x0 < r.x1 && x1 > r.x0 && y0 < r.y1 && y1 > r.y0);
}
const inAny = (q: Pt, rs: Rect[], pad: number) => rs.some((r) => q[0] > r.x0 - pad && q[0] < r.x1 + pad && q[1] > r.y0 - pad && q[1] < r.y1 + pad);

function pathOf(pts: THREE.Vector3[]) {
  const acc = [0];
  for (let i = 1; i < pts.length; i++) acc.push(acc[i - 1] + pts[i].distanceTo(pts[i - 1]));
  return { pts, acc, len: acc[acc.length - 1] || 0 };
}
function at(p: { pts: THREE.Vector3[]; acc: number[]; len: number }, d: number) {
  const { pts, acc } = p; if (pts.length < 2) return pts[0]?.clone() || new THREE.Vector3();
  let i = 1; while (i < acc.length - 1 && acc[i] < d) i++;
  const seg = acc[i] - acc[i - 1], f = seg > 1e-9 ? Math.max(0, Math.min(1, (d - acc[i - 1]) / seg)) : 0;
  return pts[i - 1].clone().lerp(pts[i], f);
}

export function register(scene: any) {
  if (scene.transfer) return;
  if (!scene.beforeRender) { scene.beforeRender = []; scene.afterRender = []; scene.disposers = []; }
  scene.transfer = new Transfer(scene);
  scene.blockOf = (id: string) => (ed.model?.blocks || []).find((b: any) => b.id === id);   // Equipment modeling parameters (mk_conveyor uses length_m to determine the number of runs)
  if (scene.layers && scene.layers.transfer === false) scene.transfer.setVisible(false);
}
