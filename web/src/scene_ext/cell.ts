// Control cell (cell block) 3D: conveyors, sensors (light up when the beam detects a part), pushers, stops, swing arms, turntables, lift tables, pick-and-place manipulators, stacker cranes, grippers, motors,
// operator consoles (buttons/E-Stop/indicator lamps/digital displays), racks, pallet tables, and parts. Parts and actuators interpolate backend view() frames for smooth motion.
// register(scene) attaches mk_cell / up_cell to the FactoryScene instance; CellModel also powers the control cell editor's 3D preview.
import { $t } from '../i18n';
import * as THREE from 'three';
import { CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { session } from '../api';

// ---------------------------------------------------------------- Materials and utilities
const M = (c: number, o: any = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.6, metalness: 0.15, ...o });
const MAT = {
  alu: M(0xc3c9d0, { metalness: 0.7, roughness: 0.32 }), aluDark: M(0x8e969f, { metalness: 0.65, roughness: 0.38 }), leg: M(0x4b525a, { metalness: 0.55, roughness: 0.45 }),
  rubber: M(0x25292d, { roughness: 0.92 }), chrome: M(0xe9edf0, { metalness: 0.92, roughness: 0.16 }), black: M(0x1c2024, { roughness: 0.55 }),
  orange: M(0xf08a1c, { roughness: 0.45 }), yellow: M(0xf2c230, { roughness: 0.5 }), blue: M(0x2c66ad, { metalness: 0.3, roughness: 0.45 }),
  red: M(0xc9302c, { roughness: 0.45 }), green: M(0x2e9d5b, { roughness: 0.5 }), white: M(0xf0f2f4, { roughness: 0.6 }), grey: M(0x9aa2aa, { roughness: 0.6 }),
  motor: M(0x3d6b94, { metalness: 0.45, roughness: 0.4 }), wood: M(0xc69a62, { roughness: 0.85 }), floor: M(0xd5d9dc, { roughness: 0.95 }),
  glass: M(0x1b2833, { metalness: 0.5, roughness: 0.12 }), panel: M(0xdfe3e7, { metalness: 0.2, roughness: 0.55 }), crane: M(0xf2b01e, { metalness: 0.35, roughness: 0.45 }),
};
const PART_COLOR: Record<string, number> = { blue: 0x2f74c0, green: 0x3aa64a, grey: 0x9aa3ab, gray: 0x9aa3ab, red: 0xd0453a, yellow: 0xf0c419, orange: 0xec8a24,
  white: 0xeef0f2, black: 0x2a2d31 };
const LAMP_COLOR: Record<string, number> = { green: 0x22c55e, red: 0xef4444, yellow: 0xf5c518, blue: 0x3b82f6, white: 0xf8fafc, black: 0x334155 };

function box(w: number, h: number, d: number, m: THREE.Material, shadow = true) {
  const o = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m); o.castShadow = shadow; o.receiveShadow = true; return o;
}
function cylX(r: number, len: number, m: THREE.Material, seg = 16) {          // Axis along x
  const o = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg), m); o.rotation.z = Math.PI / 2; o.castShadow = true; o.receiveShadow = true; return o;
}
function cylY(r: number, h: number, m: THREE.Material, seg = 18) {
  const o = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, seg), m); o.castShadow = true; o.receiveShadow = true; return o;
}
function cylZ(r: number, len: number, m: THREE.Material, seg = 16) {          // Axis along z
  const o = new THREE.Mesh(new THREE.CylinderGeometry(r, r, len, seg), m); o.rotation.x = Math.PI / 2; o.castShadow = true; o.receiveShadow = true; return o;
}
const at = <T extends THREE.Object3D>(o: T, x: number, y: number, z: number) => { o.position.set(x, y, z); return o; };

let _belt: THREE.CanvasTexture | null = null, _roll: THREE.CanvasTexture | null = null, _hazard: THREE.CanvasTexture | null = null;
function beltTexture() {
  if (_belt) return _belt;
  const c = document.createElement('canvas'); c.width = 64; c.height = 64;
  const g = c.getContext('2d')!;
  g.fillStyle = '#2a2e33'; g.fillRect(0, 0, 64, 64);
  for (let i = 0; i < 500; i++) { const v = 40 + Math.random() * 20; g.fillStyle = `rgba(${v},${v + 2},${v + 5},0.5)`; g.fillRect(Math.random() * 64, Math.random() * 64, 1, 1); }
  g.fillStyle = 'rgba(85,92,100,0.9)'; g.fillRect(0, 0, 6, 64);
  g.fillStyle = 'rgba(20,22,25,0.9)'; g.fillRect(6, 0, 2, 64);
  _belt = new THREE.CanvasTexture(c); _belt.wrapS = _belt.wrapT = THREE.RepeatWrapping; _belt.colorSpace = THREE.SRGBColorSpace; _belt.anisotropy = 4;
  return _belt;
}
function rollerTexture() {
  if (_roll) return _roll;
  const c = document.createElement('canvas'); c.width = 64; c.height = 8;
  const g = c.getContext('2d')!;
  const gr = g.createLinearGradient(0, 0, 64, 0);
  gr.addColorStop(0, '#9aa3ab'); gr.addColorStop(0.45, '#f3f5f7'); gr.addColorStop(0.55, '#e3e7ea'); gr.addColorStop(1, '#8a939b');
  g.fillStyle = gr; g.fillRect(0, 0, 64, 8); g.fillStyle = 'rgba(40,45,50,0.55)'; g.fillRect(30, 0, 3, 8);
  _roll = new THREE.CanvasTexture(c); _roll.wrapS = _roll.wrapT = THREE.RepeatWrapping; _roll.colorSpace = THREE.SRGBColorSpace;
  return _roll;
}
function hazardTexture() {
  if (_hazard) return _hazard;
  const c = document.createElement('canvas'); c.width = 64; c.height = 16;
  const g = c.getContext('2d')!;
  g.fillStyle = '#f2c230'; g.fillRect(0, 0, 64, 16); g.fillStyle = '#1d2125';
  for (let x = -16; x < 80; x += 16) { g.beginPath(); g.moveTo(x, 16); g.lineTo(x + 8, 16); g.lineTo(x + 16, 0); g.lineTo(x + 8, 0); g.fill(); }
  _hazard = new THREE.CanvasTexture(c); _hazard.wrapS = THREE.RepeatWrapping; _hazard.colorSpace = THREE.SRGBColorSpace;
  return _hazard;
}
function digitTexture(text: string, color = '#ff3b30') {
  const c = document.createElement('canvas'); c.width = 128; c.height = 48;
  const g = c.getContext('2d')!;
  g.fillStyle = '#0c0f12'; g.fillRect(0, 0, 128, 48);
  g.font = 'bold 34px "Consolas","Courier New",monospace'; g.textAlign = 'right'; g.textBaseline = 'middle';
  g.fillStyle = 'rgba(255,59,48,0.12)'; g.fillText('8888', 120, 26);
  g.fillStyle = color; g.shadowColor = color; g.shadowBlur = 8; g.fillText(text, 120, 26);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; return t;
}

const partMats = new Map<string, THREE.MeshStandardMaterial>();
function partMat(color: string, material: string) {
  const k = color + '/' + material;
  let m = partMats.get(k);
  if (!m) {
    const c = PART_COLOR[color] ?? 0x7f8a94;
    m = material === 'metal' ? M(c, { metalness: 0.85, roughness: 0.28 }) : M(c, { metalness: 0.05, roughness: 0.5 });
    partMats.set(k, m);
  }
  return m;
}
const edgeMat = new THREE.LineBasicMaterial({ color: 0x1b1f24, transparent: true, opacity: 0.35 });

function makePart(p: any): THREE.Object3D {
  const g = new THREE.Group();
  const w = p.w || 0.25, h = p.h || 0.2, mat = partMat(p.c, p.m);
  if (p.k === 'part') {
    const body = cylY(w * 0.46, h, mat, 28); body.position.y = h / 2; g.add(body);
    const hole = cylY(w * 0.16, h + 0.002, M(0x2b3036, { metalness: 0.6, roughness: 0.4 }), 16); hole.position.y = h / 2; g.add(hole);
    const ch = new THREE.Mesh(new THREE.TorusGeometry(w * 0.46, 0.006, 6, 28), mat); ch.rotation.x = Math.PI / 2; ch.position.y = h; g.add(ch);
  } else if (p.k === 'pallet') {
    const ph = Math.min(0.1, h * 0.4);
    for (const z of [-w * 0.4, 0, w * 0.4]) { const s = box(w, ph * 0.45, w * 0.18, MAT.wood); s.position.set(0, ph * 0.225, z); g.add(s); }
    const top = box(w, ph * 0.35, w, MAT.wood); top.position.y = ph * 0.82; g.add(top);
    const cargo = box(w * 0.86, h - ph, w * 0.86, mat); cargo.position.y = ph + (h - ph) / 2; g.add(cargo);
    const e = new THREE.LineSegments(new THREE.EdgesGeometry(cargo.geometry), edgeMat); e.position.copy(cargo.position); g.add(e);
  } else if (p.k === 'tote') {
    const t = 0.018, fl = box(w, t, w, mat); fl.position.y = t / 2; g.add(fl);
    for (const [x, z, a, b] of [[0, w / 2 - t / 2, w, t], [0, -w / 2 + t / 2, w, t], [w / 2 - t / 2, 0, t, w], [-w / 2 + t / 2, 0, t, w]] as number[][]) {
      const wall = box(a, h, b, mat); wall.position.set(x, h / 2, z); g.add(wall);
    }
    const rim = box(w + 0.01, 0.015, w + 0.01, M(0x1f4f8a, { roughness: 0.5 })); rim.position.y = h - 0.0075; rim.scale.set(1, 1, 1);
    (rim.material as any).transparent = true; (rim.material as any).opacity = 0.0; g.add(rim);
  } else {
    const b = box(w, h, w, mat); b.position.y = h / 2; g.add(b);
    const e = new THREE.LineSegments(new THREE.EdgesGeometry(b.geometry), edgeMat); e.position.y = h / 2; g.add(e);
    const tape = box(w * 1.002, 0.004, w * 0.22, M(0xffffff, { transparent: true, opacity: 0.35, roughness: 0.4 }), false); tape.position.y = h + 0.002; g.add(tape);
  }
  return g;
}

// ---------------------------------------------------------------- Components
type Upd = (v: any, ctx: { t: number; dt: number; frac: number }) => void;
interface CV { g: THREE.Group; up?: Upd; d: any }

const P = (d: any, k: string, def: any) => (d.params && d.params[k] !== undefined && d.params[k] !== null ? d.params[k] : def);
const num = (x: any, d = 0) => (typeof x === 'number' && isFinite(x) ? x : d);

function legs(g: THREE.Group, L: number, W: number, top: number, x0 = 0) {
  const n = Math.max(2, Math.ceil(L / 1.6) + 1);
  for (let i = 0; i < n; i++) {
    const x = x0 - L / 2 + 0.12 + (L - 0.24) * i / (n - 1);
    for (const z of [-W / 2 + 0.03, W / 2 - 0.03]) { const l = box(0.04, top - 0.1, 0.04, MAT.leg); l.position.set(x, (top - 0.1) / 2, z); g.add(l); }
    const br = box(0.03, 0.03, W - 0.06, MAT.leg); br.position.set(x, 0.12, 0); g.add(br);
    for (const z of [-W / 2 + 0.03, W / 2 - 0.03]) { const f = box(0.09, 0.012, 0.09, MAT.aluDark); f.position.set(x, 0.006, z); g.add(f); }
  }
}

function mkConveyor(d: any): CV {
  const g = new THREE.Group();
  const L = num(d.size?.[0], 2), W = num(d.size?.[1], 0.6), top = num(d.pos?.[2], 0) + num(P(d, 'height', 0.25), 0.25);
  const roller = d.type === 'roller_conveyor';
  // Side rails (aluminum profiles)
  for (const s of [-1, 1]) {
    const side = box(L, 0.1, 0.035, MAT.alu); side.position.set(0, top - 0.035, s * (W / 2 + 0.018)); g.add(side);
    const lip = box(L, 0.012, 0.05, MAT.aluDark); lip.position.set(0, top + 0.01, s * (W / 2 + 0.025)); g.add(lip);
  }
  legs(g, L, W + 0.07, top - 0.08);
  let tex: THREE.Texture | null = null, rollMat: THREE.MeshStandardMaterial | null = null;
  if (roller) {
    rollMat = M(0xffffff, { map: rollerTexture().clone(), metalness: 0.75, roughness: 0.25 });
    rollMat.map!.needsUpdate = true;
    const n = Math.max(2, Math.floor(L / 0.075));
    const geo = new THREE.CylinderGeometry(0.026, 0.026, W, 14); geo.rotateX(Math.PI / 2);
    const im = new THREE.InstancedMesh(geo, rollMat, n); im.castShadow = true; im.receiveShadow = true;
    const m4 = new THREE.Matrix4();
    for (let i = 0; i < n; i++) { m4.makeTranslation(-L / 2 + (i + 0.5) * L / n, top - 0.026, 0); im.setMatrixAt(i, m4); }
    g.add(im);
  } else {
    tex = beltTexture().clone(); tex.needsUpdate = true; tex.repeat.set(L / 0.12, 1);
    const belt = box(L, 0.018, W, M(0xffffff, { map: tex, roughness: 0.88 })); belt.position.y = top - 0.009; g.add(belt);
    const under = box(L - 0.1, 0.03, W - 0.02, MAT.rubber, false); under.position.y = top - 0.07; g.add(under);
    for (const x of [-L / 2, L / 2]) { const dr = cylZ(0.045, W - 0.01, MAT.chrome, 18); dr.position.set(x, top - 0.045, 0); g.add(dr); }
    if (!P(d, 'motor', '')) {
      const mo = cylX(0.055, 0.2, MAT.motor, 16); mo.position.set(L / 2 - 0.16, top - 0.16, W / 2 + 0.12); g.add(mo);
      const gb = box(0.1, 0.1, 0.1, MAT.aluDark); gb.position.set(L / 2 - 0.02, top - 0.12, W / 2 + 0.1); g.add(gb);
    }
  }
  // Direction arrows (on side rails)
  const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.025, 0.06, 3), MAT.yellow); arrow.rotation.z = -Math.PI / 2;
  arrow.position.set(L / 2 - 0.25, top - 0.03, W / 2 + 0.04); g.add(arrow);
  return {
    g, d, up: (v: any) => {
      const o = num(v?.o, 0);
      if (tex) tex.offset.x = -o / 0.12;
      if (rollMat) rollMat.map!.offset.x = -o / (2 * Math.PI * 0.026);
      (arrow.material as any) = Math.abs(num(v?.v, 0)) > 1e-4 ? MAT.green : MAT.yellow;
    },
  };
}

function mkCurved(d: any): CV {
  const g = new THREE.Group();
  const W = num(d.size?.[1], 0.6), R = num(P(d, 'radius', 0.9), 0.9), ang = (num(P(d, 'angle', 90), 90) * Math.PI) / 180;
  const top = num(d.pos?.[2], 0) + num(P(d, 'height', 0.25), 0.25);
  const s = ang > 0 ? 1 : -1;
  // In plan coordinates: center at (0, s*R), entry at (0,0), entry azimuth a0 = atan2(-s*R, 0)
  const a0 = Math.atan2(-s * R, 0), a1 = a0 + ang;
  const inner = new THREE.Group(); inner.position.set(0, 0, s * R); g.add(inner);
  // Build the annular sector in the XY plane, rotate -90° about X to lay it flat: plane (px,py) → (px, py); XY angle = -plan angle
  const t0 = Math.min(-a0, -a1), tl = Math.abs(ang);
  const tex = beltTexture().clone(); tex.needsUpdate = true; tex.repeat.set(6, 6);
  const ring = new THREE.Mesh(new THREE.RingGeometry(R - W / 2, R + W / 2, 40, 1, t0, tl), M(0xffffff, { map: tex, roughness: 0.88, side: THREE.DoubleSide }));
  ring.rotation.x = -Math.PI / 2; ring.position.y = top; ring.receiveShadow = true; inner.add(ring);
  for (const rr of [R - W / 2 - 0.018, R + W / 2 + 0.018]) {
    const rail = new THREE.Mesh(new THREE.TorusGeometry(rr, 0.022, 6, 40, tl), MAT.alu); rail.rotation.x = -Math.PI / 2; rail.rotation.z = t0;
    rail.position.y = top - 0.02; rail.castShadow = true; inner.add(rail);
  }
  const base = new THREE.Mesh(new THREE.CylinderGeometry(R + W / 2, R + W / 2, 0.06, 40, 1, true, Math.PI / 2 + t0, tl),
    M(0x6b737b, { side: THREE.DoubleSide, metalness: 0.4, roughness: 0.5 }));
  base.position.y = top - 0.09; inner.add(base);
  for (const k of [0.15, 0.5, 0.85]) {
    const a = a0 + ang * k; const x = Math.cos(a) * R, z = Math.sin(a) * R;
    const l = box(0.05, top - 0.12, 0.05, MAT.leg); l.position.set(x, (top - 0.12) / 2, z); inner.add(l);
  }
  return { g, d, up: (v: any) => { tex.rotation = -num(v?.o, 0) / R; } };
}

function mkChainTransfer(d: any): CV {
  const g = new THREE.Group();
  const L = num(d.size?.[0], 0.6), W = num(d.size?.[1], 0.6), top = num(d.pos?.[2], 0) + num(P(d, 'height', 0.25), 0.25);
  const chains = new THREE.Group(); g.add(chains);
  for (const x of [-L * 0.3, 0, L * 0.3]) { const c = box(0.035, 0.03, W - 0.04, MAT.black); c.position.set(x, 0, 0); chains.add(c); }
  const base = box(L * 0.8, 0.08, 0.1, MAT.aluDark); base.position.set(0, top - 0.16, 0); g.add(base);
  return { g, d, up: (v: any) => { chains.position.y = top - 0.05 + 0.06 * num(v?.u, 0); } };
}

function mkEmitter(d: any): CV {
  const g = new THREE.Group();
  const z = num(d.pos?.[2], 0.27);
  const sig = P(d, 'trigger', 'auto') === 'signal';
  if (d.type === 'cell_entry') {
    for (const s of [-1, 1]) { const p = box(0.06, z + 0.75, 0.06, MAT.green); p.position.set(0, (z + 0.75) / 2, s * 0.42); g.add(p); }
    const bar = box(0.08, 0.08, 0.9, MAT.green); bar.position.set(0, z + 0.75, 0); g.add(bar);
    const sign = box(0.02, 0.16, 0.42, M(0x1f7a46, { emissive: 0x1f7a46, emissiveIntensity: 0.3 })); sign.position.set(-0.05, z + 0.62, 0); g.add(sign);
  } else if (sig) {   // Hopper: vertical feed tube
    const tube = box(0.34, 0.7, 0.34, M(0x9fc6e6, { transparent: true, opacity: 0.28, metalness: 0.1, roughness: 0.1 }), false); tube.position.set(0, z + 0.48, 0); g.add(tube);
    for (const [x, zz] of [[-0.17, -0.17], [0.17, -0.17], [-0.17, 0.17], [0.17, 0.17]]) { const p = box(0.025, 0.72, 0.025, MAT.alu); p.position.set(x, z + 0.48, zz); g.add(p); }
    const cap = box(0.38, 0.03, 0.38, MAT.aluDark); cap.position.set(0, z + 0.85, 0); g.add(cap);
  } else {            // Automatic feeding: inclined chute
    const chute = box(0.42, 0.02, 0.4, MAT.alu); chute.position.set(-0.22, z + 0.22, 0); chute.rotation.z = -0.45; g.add(chute);
    for (const s of [-1, 1]) { const w = box(0.44, 0.08, 0.015, MAT.orange); w.position.set(-0.22, z + 0.26, s * 0.2); w.rotation.z = -0.45; g.add(w); }
    const post = box(0.04, z + 0.3, 0.04, MAT.leg); post.position.set(-0.4, (z + 0.3) / 2, 0); g.add(post);
  }
  return { g, d };
}

function mkRemover(d: any): CV {
  const g = new THREE.Group();
  const L = num(d.size?.[0], 0.6), W = num(d.size?.[1], 0.6), z = num(d.pos?.[2], 0);
  const acc = P(d, 'accept', {}) || {};
  const exit = d.type === 'cell_exit';
  const col = exit ? 0x2f6fa8 : PART_COLOR[acc.color] ?? (acc.material === 'metal' ? 0x8b949c : 0x5d6b78);
  const mat = M(col, { roughness: 0.55, metalness: 0.15 });
  if (exit) {
    const pad = box(L, 0.012, W, M(0x2f6fa8, { transparent: true, opacity: 0.45 }), false); pad.position.set(0, z + 0.006, 0); g.add(pad);
    for (const s of [-1, 1]) { const p = box(0.06, z + 1.0, 0.06, MAT.blue); p.position.set(0, (z + 1.0) / 2, s * (W / 2 + 0.04)); g.add(p); }
    const bar = box(0.08, 0.08, W + 0.14, MAT.blue); bar.position.set(0, z + 1.0, 0); g.add(bar);
  } else {
    const h = Math.min(0.42, Math.max(0.2, num(P(d, 'depth', 0.6), 0.6) * 0.6)), t = 0.025;
    const fl = box(L, t, W, mat); fl.position.set(0, z + t / 2, 0); g.add(fl);
    for (const [x, zz, a, b] of [[0, W / 2 - t / 2, L, t], [0, -W / 2 + t / 2, L, t], [L / 2 - t / 2, 0, t, W], [-L / 2 + t / 2, 0, t, W]] as number[][]) {
      const w = box(a, h, b, mat); w.position.set(x, z + h / 2, zz); g.add(w);
    }
    const rim = box(L + 0.02, 0.02, W + 0.02, MAT.aluDark); rim.position.set(0, z + h, 0); rim.scale.set(1, 1, 1); g.add(rim);
    (rim as any).visible = false;
  }
  return { g, d };
}

function sensorPost(g: THREE.Group, z: number, back = 0.05) {
  const post = box(0.025, z, 0.025, MAT.leg); post.position.set(0, z / 2, back); g.add(post);
  const foot = box(0.07, 0.01, 0.07, MAT.aluDark); foot.position.set(0, 0.005, back); g.add(foot);
}

function led(r = 0.008) {
  const m = new THREE.Mesh(new THREE.SphereGeometry(r, 10, 8), new THREE.MeshStandardMaterial({ color: 0x3a3a3a, emissive: 0x000000, emissiveIntensity: 1.6 }));
  return m;
}
function setLed(m: THREE.Mesh, on: boolean, color = 0xff8a00) {
  const mt = m.material as THREE.MeshStandardMaterial;
  mt.emissive.setHex(on ? color : 0x000000); mt.color.setHex(on ? color : 0x3a3a3a);
}

function mkBeam(d: any): CV {
  const g = new THREE.Group();
  const z = num(d.pos?.[2], 0.35), range = num(P(d, 'range', 0.8), 0.8);
  sensorPost(g, z - 0.02, 0.05);
  const body = box(0.035, 0.06, 0.03, d.type === 'retro_sensor' ? M(0x2b5ea8, { roughness: 0.45 }) : M(0xf2c230, { roughness: 0.45 })); body.position.set(0, z, 0.02); g.add(body);
  const face = box(0.028, 0.04, 0.004, MAT.glass); face.position.set(0, z, 0.003); g.add(face);
  const l1 = led(); l1.position.set(-0.008, z + 0.032, 0.02); g.add(l1); setLed(l1, true, 0x22c55e);
  const l2 = led(); l2.position.set(0.008, z + 0.032, 0.02); g.add(l2);
  const bmat = new THREE.MeshBasicMaterial({ color: 0xff2a1a, transparent: true, opacity: 0.5, depthWrite: false });
  const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.006, 0.006, 1, 8), bmat); beam.rotation.x = Math.PI / 2; g.add(beam);
  const glow = new THREE.Mesh(new THREE.CylinderGeometry(0.016, 0.016, 1, 8), new THREE.MeshBasicMaterial({ color: 0xff5a1a, transparent: true, opacity: 0, depthWrite: false }));
  glow.rotation.x = Math.PI / 2; g.add(glow);
  const spot = new THREE.Mesh(new THREE.CircleGeometry(0.012, 12), new THREE.MeshBasicMaterial({ color: 0xff3b2a, transparent: true, opacity: 0.0, depthWrite: false }));
  g.add(spot);
  if (d.type === 'retro_sensor') {
    const refl = box(0.04, 0.05, 0.006, M(0xd23c3c, { roughness: 0.3, metalness: 0.4 })); refl.position.set(0, z, -range - 0.003); g.add(refl);
    const rp = box(0.02, z - 0.02, 0.02, MAT.leg); rp.position.set(0, (z - 0.02) / 2, -range - 0.02); g.add(rp);
  }
  const setLen = (len: number, hit: boolean) => {
    beam.scale.set(1, Math.max(0.005, len), 1); beam.position.set(0, z, -len / 2);
    glow.scale.set(1, Math.max(0.005, len), 1); glow.position.set(0, z, -len / 2); (glow.material as any).opacity = hit ? 0.28 : 0;
    bmat.opacity = hit ? 1 : 0.5; bmat.color.setHex(hit ? 0xffa21a : 0xff2a1a);
    spot.position.set(0, z, -len); (spot.material as any).opacity = hit ? 0.9 : 0;
  };
  setLen(range, false);
  return { g, d, up: (v: any) => { const hit = !!v?.d; setLen(hit ? num(v?.len, range) : range, hit); setLed(l2, hit); } };
}

function mkProx(d: any): CV {
  const g = new THREE.Group();
  const z = num(d.pos?.[2], 0.32), ind = d.type === 'inductive', range = num(P(d, 'range', 0.12), 0.12);
  sensorPost(g, z - 0.02, 0.06);
  const br = box(0.03, 0.04, 0.06, MAT.aluDark); br.position.set(0, z, 0.04); g.add(br);
  const barrel = cylZ(0.012, 0.075, ind ? M(0xc8ccd0, { metalness: 0.85, roughness: 0.25 }) : M(0x3b7bd4, { roughness: 0.4 }), 16); barrel.position.set(0, z, 0.0); g.add(barrel);
  const tip = cylZ(0.0125, 0.012, ind ? M(0xd9a441, { roughness: 0.5 }) : M(0x1e3f73, { roughness: 0.5 })); tip.position.set(0, z, -0.043); g.add(tip);
  const l = led(0.006); l.position.set(0, z + 0.013, 0.03); g.add(l);
  const zone = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.035, range, 12, 1, true),
    new THREE.MeshBasicMaterial({ color: ind ? 0xffc04d : 0x63a4ff, transparent: true, opacity: 0.12, depthWrite: false, side: THREE.DoubleSide }));
  zone.rotation.x = -Math.PI / 2; zone.position.set(0, z, -0.05 - range / 2); g.add(zone);
  return { g, d, up: (v: any) => { setLed(l, !!v?.d); (zone.material as any).opacity = v?.d ? 0.35 : 0.1; } };
}

function overheadArm(g: THREE.Group, z: number, side = 0.48) {
  const post = box(0.04, z + 0.06, 0.04, MAT.leg); post.position.set(0, (z + 0.06) / 2, side); g.add(post);
  const arm = box(0.03, 0.03, side + 0.02, MAT.alu); arm.position.set(0, z + 0.075, side / 2); g.add(arm);
  const foot = box(0.1, 0.012, 0.1, MAT.aluDark); foot.position.set(0, 0.006, side); g.add(foot);
}

function mkDown(d: any): CV {
  const g = new THREE.Group();
  const z = num(d.pos?.[2], 0.9), vis = d.type === 'vision_sensor', rad = num(P(d, 'radius', 0.1), 0.1);
  overheadArm(g, z);
  let screen: THREE.Mesh | null = null;
  if (vis) {
    const body = box(0.07, 0.06, 0.09, M(0x23272c, { metalness: 0.3, roughness: 0.4 })); body.position.set(0, z + 0.03, 0); g.add(body);
    const lens = cylY(0.022, 0.035, MAT.black); lens.position.set(0, z - 0.012, 0); g.add(lens);
    const ringl = new THREE.Mesh(new THREE.TorusGeometry(0.03, 0.006, 6, 20), new THREE.MeshStandardMaterial({ color: 0xffffff, emissive: 0x88ccff, emissiveIntensity: 0.6 }));
    ringl.rotation.x = Math.PI / 2; ringl.position.set(0, z - 0.03, 0); g.add(ringl);
    screen = ringl;
  } else {
    const body = box(0.05, 0.08, 0.06, M(0xd8dde2, { roughness: 0.4 })); body.position.set(0, z + 0.04, 0); g.add(body);
    const win = box(0.03, 0.004, 0.02, MAT.glass); win.position.set(0, z - 0.001, 0); g.add(win);
  }
  const coneMat = new THREE.MeshBasicMaterial({ color: vis ? 0x7cc4ff : 0xff3020, transparent: true, opacity: 0.08, depthWrite: false, side: THREE.DoubleSide });
  const cone = new THREE.Mesh(vis ? new THREE.ConeGeometry(rad, 1, 24, 1, true) : new THREE.CylinderGeometry(0.003, 0.003, 1, 6), coneMat);
  g.add(cone);
  const setH = (bottom: number, hit: boolean) => {
    const len = Math.max(0.01, z - 0.03 - bottom);
    cone.scale.set(1, len, 1); cone.position.set(0, bottom + len / 2, 0);
    coneMat.opacity = hit ? (vis ? 0.22 : 0.95) : (vis ? 0.07 : 0.4);
  };
  setH(0.25, false);
  return {
    g, d, up: (v: any) => {
      const hit = !!v?.d; setH(hit && v?.z !== null && v?.z !== undefined ? v.z : 0.25, hit);
      if (screen) (screen.material as any).emissiveIntensity = hit ? 1.6 : 0.5;
    },
  };
}

function mkEncoder(d: any): CV {
  const g = new THREE.Group();
  const z = num(d.pos?.[2], 0.27);
  const wheel = cylZ(0.035, 0.02, MAT.rubber, 20); wheel.position.set(0, z, 0); g.add(wheel);
  const spoke = box(0.06, 0.006, 0.022, MAT.yellow); spoke.position.set(0, z, 0); g.add(spoke);
  const arm = box(0.12, 0.015, 0.015, MAT.aluDark); arm.position.set(-0.06, z + 0.02, 0.02); arm.rotation.z = 0.3; g.add(arm);
  const bodyE = cylZ(0.022, 0.04, MAT.black); bodyE.position.set(0, z, 0.035); g.add(bodyE);
  return { g, d, up: (v: any) => { const a = -num(v?.n, 0) / 1000 / 0.035; wheel.rotation.y = 0; spoke.rotation.z = a; } };
}

function mkPusher(d: any): CV {
  const g = new THREE.Group();
  const z = num(d.pos?.[2], 0.35), stroke = num(P(d, 'stroke', 0.8), 0.8), hw = num(P(d, 'head', 0.4), 0.4);
  const bodyLen = stroke + 0.12, r = 0.035;
  // Cylinder body behind the pusher plate (+z); extends toward -z
  const body = cylZ(r, bodyLen, M(0xd8dde2, { metalness: 0.7, roughness: 0.3 }), 20); body.position.set(0, z, 0.08 + bodyLen / 2); g.add(body);
  for (const zz of [0.08, 0.08 + bodyLen]) { const cap = box(0.09, 0.09, 0.03, MAT.blue); cap.position.set(0, z, zz); g.add(cap); }
  const valve = box(0.05, 0.03, 0.08, MAT.black); valve.position.set(0, z + 0.06, 0.08 + bodyLen * 0.7); g.add(valve);
  for (const zz of [0.12, 0.08 + bodyLen - 0.04]) { const st = box(0.05, z - 0.04, 0.05, MAT.leg); st.position.set(0, (z - 0.04) / 2, zz); g.add(st); }
  const rod = cylZ(0.012, 1, MAT.chrome, 12); g.add(rod);
  const plate = box(hw, 0.16, 0.025, MAT.orange); g.add(plate);
  const guide = box(hw * 0.9, 0.02, 0.02, MAT.black); g.add(guide);
  const set = (p: number) => {
    plate.position.set(0, z, -p + 0.0125); guide.position.set(0, z - 0.08, -p + 0.0125);
    const len = 0.08 + p - 0.0125; rod.scale.set(1, Math.max(0.01, len), 1); rod.position.set(0, z, 0.08 - len / 2);
  };
  set(0);
  return { g, d, up: (v: any) => set(num(v?.p, 0)) };
}

function mkStopper(d: any): CV {
  const g = new THREE.Group();
  const width = num(P(d, 'width', d.size?.[1] ?? 0.6), 0.6), top = num(d.pos?.[2], 0) + 0.25;
  const base = box(0.1, 0.12, 0.16, MAT.aluDark); base.position.set(0, top - 0.17, 0); g.add(base);
  const cyl = cylY(0.025, 0.1, MAT.chrome); cyl.position.set(0, top - 0.09, 0); g.add(cyl);
  const tex = hazardTexture().clone(); tex.needsUpdate = true; tex.repeat.set(width / 0.12, 1);
  const blade = box(0.02, 0.07, width - 0.04, M(0xffffff, { map: tex, roughness: 0.5 })); g.add(blade);
  const set = (u: number) => { blade.position.set(0, top - 0.035 + 0.05 * u, 0); };
  set(0);
  return { g, d, up: (v: any) => set(num(v?.u, 0)) };
}

function mkPivot(d: any): CV {
  const g = new THREE.Group();
  const z = num(d.pos?.[2], 0.33), La = num(P(d, 'length', 0.85), 0.85);
  const post = cylY(0.035, z + 0.12, MAT.aluDark); post.position.set(0, (z + 0.12) / 2, 0); g.add(post);
  const cap = cylY(0.05, 0.04, MAT.orange); cap.position.set(0, z + 0.12, 0); g.add(cap);
  const drive = box(0.12, 0.1, 0.12, MAT.motor); drive.position.set(0, z + 0.19, 0); g.add(drive);
  const arm = new THREE.Group(); arm.position.set(0, z, 0); g.add(arm);
  const pad = box(La, 0.11, 0.028, MAT.orange); pad.position.set(La / 2, 0, 0); arm.add(pad);
  const edge = box(La, 0.1, 0.012, MAT.rubber); edge.position.set(La / 2, 0, -0.02); arm.add(edge);
  return { g, d, up: (v: any) => { arm.rotation.y = (num(v?.a, 0) * Math.PI) / 180; } };
}

function mkTurntable(d: any): CV {
  const g = new THREE.Group();
  const R = Math.min(num(d.size?.[0], 0.9), num(d.size?.[1], 0.9)) / 2, top = num(d.pos?.[2], 0) + num(P(d, 'height', 0.25), 0.25);
  const base = cylY(R * 0.55, top - 0.08, MAT.leg, 28); base.position.y = (top - 0.08) / 2; g.add(base);
  const skirt = cylY(R + 0.01, 0.05, MAT.aluDark, 40); skirt.position.y = top - 0.075; g.add(skirt);
  const disk = new THREE.Group(); disk.position.y = top; g.add(disk);
  const plate = cylY(R, 0.03, M(0x5d666f, { metalness: 0.5, roughness: 0.4 }), 40); plate.position.y = -0.035; disk.add(plate);
  const rmat = M(0xffffff, { map: rollerTexture().clone(), metalness: 0.75, roughness: 0.25 }); rmat.map!.needsUpdate = true;
  const n = Math.floor((2 * R * 0.86) / 0.075);
  for (let i = 0; i < n; i++) {
    const x = -R * 0.86 + (i + 0.5) * (2 * R * 0.86) / n; const half = Math.sqrt(Math.max(0, R * R - x * x)) * 0.92;
    const rl = cylZ(0.024, half * 2, rmat, 12); rl.position.set(x, -0.024, 0); disk.add(rl);
  }
  for (const s of [-1, 1]) { const gd = box(2 * R * 0.8, 0.05, 0.02, MAT.alu); gd.position.set(0, 0.0, s * R * 0.62); disk.add(gd); }
  const mark = box(0.08, 0.012, 0.03, MAT.yellow); mark.position.set(R * 0.9, -0.012, 0); disk.add(mark);
  return { g, d, up: (v: any) => { disk.rotation.y = -(num(v?.a, 0) * Math.PI) / 180; rmat.map!.offset.x -= num(v?.v, 0) * 0.016 / (2 * Math.PI * 0.024); } };
}

function mkLift(d: any): CV {
  const g = new THREE.Group();
  const L = num(d.size?.[0], 0.8), W = num(d.size?.[1], 0.7), z0 = num(d.pos?.[2], 0);
  const lo = z0 + num(P(d, 'height', 0.25), 0.25), hi = z0 + num(P(d, 'z_high', 1.0), 1.0);
  const H = hi + 0.35;
  for (const [x, zz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) { const p = box(0.06, H, 0.06, MAT.blue); p.position.set(x * (L / 2 + 0.04), H / 2, zz * (W / 2 + 0.04)); g.add(p); }
  for (const zz of [-1, 1]) { const b = box(L + 0.14, 0.06, 0.06, MAT.blue); b.position.set(0, H, zz * (W / 2 + 0.04)); g.add(b); }
  const plat = new THREE.Group(); g.add(plat);
  const deck = box(L, 0.05, W, M(0x6b747d, { metalness: 0.45, roughness: 0.4 })); deck.position.y = -0.06; plat.add(deck);
  const rmat = M(0xffffff, { map: rollerTexture().clone(), metalness: 0.75, roughness: 0.25 }); rmat.map!.needsUpdate = true;
  const n = Math.floor(L / 0.075);
  for (let i = 0; i < n; i++) { const r = cylZ(0.024, W - 0.04, rmat, 12); r.position.set(-L / 2 + (i + 0.5) * L / n, -0.024, 0); plat.add(r); }
  for (const zz of [-1, 1]) { const s = box(L, 0.06, 0.02, MAT.alu); s.position.set(0, 0.0, zz * (W / 2 - 0.01)); plat.add(s); }
  const sc = new THREE.Group(); g.add(sc);
  const arm1 = box(Math.hypot(L * 0.8, 1), 0.03, 0.03, MAT.aluDark), arm2 = arm1.clone(); sc.add(arm1, arm2);
  let travel = 0;
  return {
    g, d, up: (v: any) => {
      const zt = num(v?.z, lo); plat.position.y = zt;
      const hgt = Math.max(0.05, zt - 0.1), span = L * 0.8, len = Math.hypot(span, hgt);
      for (const [a, s] of [[arm1, 1], [arm2, -1]] as [THREE.Mesh, number][]) {
        a.scale.x = len / Math.hypot(L * 0.8, 1); a.position.set(0, hgt / 2 + 0.03, 0); a.rotation.z = s * Math.atan2(hgt, span);
      }
      travel += num(v?.v, 0) * 0.016; rmat.map!.offset.x = -travel / (2 * Math.PI * 0.024);
    },
  };
}

function mkPickPlace(d: any): CV {
  const g = new THREE.Group();
  const xs = num(P(d, 'x_stroke', 1.2), 1.2), zs = num(P(d, 'z_stroke', 0.6), 0.6), zt = num(d.pos?.[2], 0) + num(P(d, 'z_top', 1.1), 1.1);
  const beamH = zt + 0.32, side = 0.5;
  for (const x of [-0.25, xs + 0.25]) {
    const p = box(0.09, beamH, 0.09, MAT.alu); p.position.set(x, beamH / 2, side); g.add(p);
    const f = box(0.2, 0.015, 0.2, MAT.aluDark); f.position.set(x, 0.008, side); g.add(f);
  }
  const beam = box(xs + 0.6, 0.12, 0.1, MAT.alu); beam.position.set(xs / 2, beamH, side); g.add(beam);
  const track = box(xs + 0.5, 0.025, 0.03, MAT.black); track.position.set(xs / 2, beamH + 0.07, side - 0.03); g.add(track);
  const cable = box(xs * 0.5, 0.05, 0.06, M(0x2b2f33, { roughness: 0.8 })); cable.position.set(xs * 0.25, beamH + 0.11, side + 0.02); g.add(cable);
  const car = new THREE.Group(); g.add(car);
  const cb = box(0.2, 0.18, 0.16, MAT.orange); cb.position.set(0, beamH, side - 0.1); car.add(cb);
  const armH = box(0.08, 0.08, side - 0.05, MAT.alu); armH.position.set(0, beamH, (side - 0.1) / 2); car.add(armH);
  const zguide = box(0.07, 0.42, 0.07, MAT.aluDark); zguide.position.set(0, beamH - 0.1, 0); car.add(zguide);
  const zrod = new THREE.Group(); car.add(zrod);
  const rod = box(0.04, zs + 0.3, 0.04, MAT.chrome); rod.position.y = (zs + 0.3) / 2; zrod.add(rod);
  const flange = cylY(0.03, 0.02, MAT.aluDark); flange.position.y = 0.01; zrod.add(flange);
  const cup = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.022, 0.03, 18), MAT.black); cup.position.y = -0.012; zrod.add(cup);
  const vac = led(0.01); vac.position.set(0.03, 0.05, 0); zrod.add(vac);
  return {
    g, d, up: (v: any) => {
      car.position.x = num(v?.x, 0); zrod.position.y = zt - num(v?.z, 0); setLed(vac, !!v?.on, v?.g ? 0x22c55e : 0x3b82f6);
    },
  };
}

function mkRack(d: any): CV {
  const g = new THREE.Group();
  const L = num(d.size?.[0], 2.4), W = num(d.size?.[1], 0.6), cols = Math.max(1, num(P(d, 'cols', 4), 4)), rows = Math.max(1, num(P(d, 'rows', 3), 3));
  const ch = num(P(d, 'cell_h', 0.5), 0.5), base = num(P(d, 'base', 0.3), 0.3), z0 = num(d.pos?.[2], 0);
  const H = z0 + base + rows * ch + 0.1, cw = L / cols;
  for (let c = 0; c <= cols; c++) for (const s of [-1, 1]) { const u = box(0.06, H, 0.05, MAT.blue); u.position.set(-L / 2 + c * cw, H / 2, s * (W / 2)); g.add(u); }
  for (let c = 0; c <= cols; c++) for (let k = 0; k < Math.floor(H / 0.35); k++) {
    const br = box(0.02, 0.02, W, MAT.blue); br.position.set(-L / 2 + c * cw, 0.2 + k * 0.35, 0); br.rotation.x = k % 2 ? 0.5 : -0.5; g.add(br);
  }
  for (let r = 0; r < rows; r++) {
    const t = z0 + base + r * ch;
    for (const s of [-1, 1]) { const bm = box(L, 0.06, 0.04, MAT.orange); bm.position.set(0, t - 0.03, s * (W / 2 - 0.02)); g.add(bm); }
    for (let c = 0; c < cols; c++) for (const s of [-1, 1]) {
      const rail = box(cw - 0.08, 0.015, 0.06, MAT.grey); rail.position.set(-L / 2 + (c + 0.5) * cw, t - 0.008, s * W * 0.32); g.add(rail);
    }
  }
  return { g, d };
}

function mkCrane(d: any): CV {
  const g = new THREE.Group();
  const travel = num(P(d, 'travel', d.size?.[0] ?? 3), 3), Hm = 2.25;
  const rail = box(travel + 0.6, 0.06, 0.12, MAT.aluDark); rail.position.set(travel / 2, 0.03, 0); g.add(rail);
  for (const x of [-0.3, travel + 0.3]) { const p = box(0.16, 0.25, 0.3, M(0xd23c3c, { roughness: 0.5 })); p.position.set(x, 0.125, 0); g.add(p); }   // End buffer
  const mast = new THREE.Group(); g.add(mast);
  const bogie = box(0.5, 0.14, 0.3, MAT.crane); bogie.position.y = 0.13; mast.add(bogie);
  for (const s of [-1, 1]) { const m = box(0.06, Hm - 0.2, 0.08, MAT.crane); m.position.set(s * 0.12, Hm / 2 + 0.05, 0); mast.add(m); }
  const head = box(0.4, 0.08, 0.12, MAT.crane); head.position.y = Hm; mast.add(head);
  const cab = box(0.16, 0.25, 0.22, MAT.panel); cab.position.set(0.3, 0.32, 0); mast.add(cab);
  const carriage = new THREE.Group(); mast.add(carriage);
  const cbx = box(0.36, 0.16, 0.3, M(0xd99a16, { metalness: 0.3, roughness: 0.45 })); cbx.position.y = 0.06; carriage.add(cbx);
  const forks = new THREE.Group(); carriage.add(forks);
  for (const s of [-1, 1]) { const t = box(0.07, 0.025, 0.6, MAT.chrome); t.position.set(s * 0.12, 0.012, 0); forks.add(t); }
  return {
    g, d, up: (v: any) => {
      mast.position.x = num(v?.x, 0); carriage.position.y = num(v?.z, 0.2) + 0.0; forks.position.z = num(v?.f, 0); forks.position.y = 0.08 * num(v?.l, 0);
    },
  };
}

function mkGripper(d: any): CV {
  const g = new THREE.Group();
  const width = num(P(d, 'width', d.size?.[1] ?? 0.7), 0.7), z = num(d.pos?.[2], 0.35);
  for (const s of [-1, 1]) { const p = box(0.05, z + 0.3, 0.05, MAT.alu); p.position.set(0, (z + 0.3) / 2, s * (width / 2 + 0.06)); g.add(p); }
  const beam = box(0.08, 0.06, width + 0.18, MAT.alu); beam.position.set(0, z + 0.3, 0); g.add(beam);
  const jaws: THREE.Mesh[] = [];
  for (const s of [-1, 1]) {
    const j = box(0.12, 0.14, 0.02, MAT.orange); j.position.set(0, z, s * width / 2); g.add(j); jaws.push(j);
    const c = cylZ(0.02, 0.15, MAT.chrome); c.position.set(0, z + 0.2, s * (width / 2 - 0.07)); g.add(c);
  }
  return { g, d, up: (v: any) => { const u = num(v?.u, 0); jaws.forEach((j, i) => { j.position.z = (i ? 1 : -1) * (width / 2 - u * (width / 2 - 0.135)); }); } };
}

function mkMotor(d: any): CV {
  const g = new THREE.Group();
  const z = num(d.pos?.[2], 0) + 0.14;
  const body = cylX(0.09, 0.26, MAT.motor, 24); body.position.set(0, z, 0); g.add(body);
  for (let i = 0; i < 7; i++) { const f = new THREE.Mesh(new THREE.TorusGeometry(0.093, 0.006, 4, 24), MAT.motor); f.rotation.y = Math.PI / 2; f.position.set(-0.1 + i * 0.033, z, 0); g.add(f); }
  const end = cylX(0.08, 0.04, MAT.black, 24); end.position.set(-0.15, z, 0); g.add(end);
  const tb = box(0.09, 0.06, 0.09, MAT.motor); tb.position.set(0.02, z + 0.11, 0); g.add(tb);
  for (const x of [-0.08, 0.08]) { const ft = box(0.04, 0.06, 0.2, MAT.motor); ft.position.set(x, z - 0.09, 0); g.add(ft); }
  const shaft = new THREE.Group(); shaft.position.set(0.15, z, 0); g.add(shaft);
  const sh = cylX(0.018, 0.08, MAT.chrome); sh.position.x = 0.04; shaft.add(sh);
  const key = box(0.08, 0.008, 0.008, MAT.yellow); key.position.set(0.04, 0.02, 0); shaft.add(key);
  const plate = box(0.25, 0.012, 0.3, MAT.aluDark); plate.position.set(0, 0.006, 0); g.add(plate);
  const trip = led(0.012); trip.position.set(0.02, z + 0.15, 0.03); g.add(trip);
  let ang = 0;
  return { g, d, up: (v: any, c) => { ang += num(v?.s, 0) * c.dt * 25; shaft.rotation.x = ang; setLed(trip, !!v?.trip, 0xef4444); } };
}

function mkPanelItem(d: any): CV {
  const g = new THREE.Group();
  const z = num(d.pos?.[2], 0.95);
  const t = d.type, color = LAMP_COLOR[P(d, 'color', t === 'estop' ? 'red' : 'green')] ?? 0x22c55e;
  if (t === 'button') {
    const ring = cylY(0.028, 0.012, MAT.chrome, 20); ring.position.y = z + 0.006; g.add(ring);
    const cap = cylY(0.021, 0.018, new THREE.MeshStandardMaterial({ color, roughness: 0.35, emissive: color, emissiveIntensity: 0 }), 20); g.add(cap);
    return { g, d, up: (v: any) => { const on = !!v?.s; cap.position.y = z + (on ? 0.012 : 0.02); (cap.material as any).emissiveIntensity = on ? 0.7 : 0.05; } };
  }
  if (t === 'estop') {
    const plate = box(0.08, 0.006, 0.08, MAT.yellow); plate.position.y = z + 0.003; g.add(plate);
    const stem = cylY(0.012, 0.03, MAT.black); stem.position.y = z + 0.02; g.add(stem);
    const head = new THREE.Mesh(new THREE.SphereGeometry(0.034, 20, 10, 0, Math.PI * 2, 0, Math.PI / 2), M(0xd42a24, { roughness: 0.3 }));
    head.scale.y = 0.55; g.add(head);
    return { g, d, up: (v: any) => { head.position.y = z + (v?.s ? 0.02 : 0.034); } };
  }
  if (t === 'switch') {
    const base = cylY(0.026, 0.01, MAT.black, 20); base.position.y = z + 0.005; g.add(base);
    const knob = new THREE.Group(); knob.position.y = z + 0.02; g.add(knob);
    const kb = cylY(0.02, 0.018, MAT.black, 16); knob.add(kb);
    const bar = box(0.008, 0.012, 0.042, MAT.white); bar.position.y = 0.012; knob.add(bar);
    return { g, d, up: (v: any) => { knob.rotation.y = -num(v?.s, 0) * 0.8; } };
  }
  if (t === 'potentiometer') {
    const base = cylY(0.03, 0.006, MAT.white, 24); base.position.y = z + 0.003; g.add(base);
    const knob = new THREE.Group(); knob.position.y = z + 0.016; g.add(knob);
    knob.add(cylY(0.018, 0.02, MAT.black, 16));
    const mk = box(0.004, 0.022, 0.016, MAT.white); mk.position.set(0, 0.002, -0.01); knob.add(mk);
    const mx = num(P(d, 'max', 1000), 1000);
    return { g, d, up: (v: any) => { knob.rotation.y = -(num(v?.s, 0) / mx - 0.5) * 4.7; } };
  }
  if (t === 'lamp') {
    const base = cylY(0.025, 0.012, MAT.black, 20); base.position.y = z + 0.006; g.add(base);
    const dm = new THREE.MeshStandardMaterial({ color: new THREE.Color(color).multiplyScalar(0.45), roughness: 0.25, emissive: color, emissiveIntensity: 0, transparent: true, opacity: 0.95 });
    const dome = new THREE.Mesh(new THREE.SphereGeometry(0.021, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2), dm); dome.position.y = z + 0.012; g.add(dome);
    const halo = new THREE.Mesh(new THREE.SphereGeometry(0.04, 12, 8), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0, depthWrite: false }));
    halo.position.y = z + 0.02; g.add(halo);
    return { g, d, up: (v: any) => { const on = !!v?.on; dm.emissiveIntensity = on ? 2.2 : 0; dm.color.setHex(on ? color : new THREE.Color(color).multiplyScalar(0.4).getHex()); (halo.material as any).opacity = on ? 0.25 : 0; } };
  }
  // Seven-segment display
  const frame = box(0.17, 0.012, 0.075, MAT.black); frame.position.y = z + 0.006; g.add(frame);
  let shown = '';
  const scr = new THREE.Mesh(new THREE.PlaneGeometry(0.15, 0.056), new THREE.MeshBasicMaterial({ map: digitTexture('0') }));
  scr.rotation.x = -Math.PI / 2; scr.position.y = z + 0.0125; g.add(scr);
  return {
    g, d, up: (v: any) => {
      const s = String(Math.round(num(v?.v, 0)));
      if (s !== shown) { shown = s; const m = scr.material as THREE.MeshBasicMaterial; m.map?.dispose(); m.map = digitTexture(s.slice(-4)); m.needsUpdate = true; }
    },
  };
}

function mkPallet(d: any): CV {
  const g = new THREE.Group();
  const L = num(d.size?.[0], 0.9), W = num(d.size?.[1], 0.7), top = num(d.pos?.[2], 0) + num(P(d, 'height', 0.3), 0.3);
  const stand = box(L * 0.9, top - 0.12, W * 0.9, MAT.leg); stand.position.y = (top - 0.12) / 2; g.add(stand);
  for (const x of [-L * 0.4, 0, L * 0.4]) { const b = box(0.1, 0.06, W, MAT.wood); b.position.set(x, top - 0.09, 0); g.add(b); }
  const n = Math.max(3, Math.round(W / 0.14));
  for (let i = 0; i < n; i++) { const s = box(L, 0.022, W / n - 0.025, MAT.wood); s.position.set(0, top - 0.011, -W / 2 + (i + 0.5) * W / n); g.add(s); }
  return { g, d };
}

const MAKERS: Record<string, (d: any) => CV> = {
  belt_conveyor: mkConveyor, roller_conveyor: mkConveyor, curved_conveyor: mkCurved, chain_transfer: mkChainTransfer,
  emitter: mkEmitter, cell_entry: mkEmitter, remover: mkRemover, cell_exit: mkRemover,
  diffuse_sensor: mkBeam, retro_sensor: mkBeam, capacitive: mkProx, inductive: mkProx, vision_sensor: mkDown, height_sensor: mkDown, encoder: mkEncoder,
  pusher: mkPusher, stopper: mkStopper, pivot_arm: mkPivot, turntable: mkTurntable, lift: mkLift, pick_place: mkPickPlace, stacker_crane: mkCrane,
  gripper: mkGripper, motor: mkMotor, button: mkPanelItem, switch: mkPanelItem, estop: mkPanelItem, lamp: mkPanelItem, display: mkPanelItem,
  potentiometer: mkPanelItem, rack: mkRack, pallet: mkPallet,
};
export const PANEL_TYPES = new Set(['button', 'switch', 'estop', 'lamp', 'display', 'potentiometer']);

// ---------------------------------------------------------------- Interpolation
function lerpVal(a: any, b: any, f: number): any {
  if (typeof a === 'number' && typeof b === 'number') return a + (b - a) * f;
  if (Array.isArray(a) && Array.isArray(b)) return f < 0.5 ? a : b;
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const o: any = {};
    for (const k of Object.keys(b)) o[k] = k in a ? lerpVal(a[k], b[k], f) : b[k];
    return o;
  }
  return f < 0.5 ? a : b;
}
function lerpAngle(a: number, b: number, f: number) {
  let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return a + d * f;
}

type Frame = { t: number; comps: any; parts: Map<string, any> };

/** Control cell 3D model: build(def) creates components, push(view) receives frames, tick(dt) interpolates using the playback clock. */
export class CellModel {
  group = new THREE.Group(); comps = new Map<string, CV>(); partObjs = new Map<string, THREE.Object3D>(); def: any = null;
  frames: Frame[] = []; pt = -1; rate = 1; lastWall = 0; lastT = -1; labels = false; labelObjs: CSS2DObject[] = [];
  root = new THREE.Group(); partsRoot = new THREE.Group(); floorMat: THREE.MeshStandardMaterial | null = null; hitTargets: THREE.Object3D[] = [];
  lastView: any = null;

  constructor(opts: { labels?: boolean } = {}) { this.labels = !!opts.labels; this.group.add(this.root, this.partsRoot); }

  build(def: any, size?: number[]) {
    this.clear();
    this.def = def || { components: [] };
    const [L, W] = size || def?.size || [8, 4];
    // Cell floor: light epoxy flooring + yellow-black warning stripes
    const fl = box(L, 0.012, W, MAT.floor, false); fl.position.y = 0.006; fl.receiveShadow = true; this.root.add(fl);
    const tex = hazardTexture();
    for (const [x, z, a, b, rep] of [[0, -W / 2, L, 0.08, L], [0, W / 2, L, 0.08, L], [-L / 2, 0, 0.08, W, W], [L / 2, 0, 0.08, W, W]] as number[][]) {
      const t2 = tex.clone(); t2.needsUpdate = true; t2.repeat.set(rep / 0.3, 1); if (a < b) { t2.rotation = Math.PI / 2; t2.center.set(0.5, 0.5); }
      const s = box(a, 0.004, b, M(0xffffff, { map: t2, roughness: 0.7 }), false); s.position.set(x, 0.014, z); this.root.add(s);
    }
    this.buildConsoles();
    for (const c of this.def.components || []) this.addComp(c);
  }

  /** Group panel components into consoles by position. */
  buildConsoles() {
    const ps = (this.def.components || []).filter((c: any) => PANEL_TYPES.has(c.type));
    const used = new Set<any>();
    for (const p of ps) {
      if (used.has(p)) continue;
      const grp = [p]; used.add(p);
      for (let k = 0; k < grp.length; k++) for (const q of ps) if (!used.has(q) && Math.hypot(q.pos[0] - grp[k].pos[0], q.pos[1] - grp[k].pos[1]) < 0.45) { grp.push(q); used.add(q); }
      const xs = grp.map((c: any) => c.pos[0]), ys = grp.map((c: any) => c.pos[1]);
      const x0 = Math.min(...xs) - 0.12, x1 = Math.max(...xs) + 0.14, y0 = Math.min(...ys) - 0.12, y1 = Math.max(...ys) + 0.12;
      const zt = Math.min(...grp.map((c: any) => num(c.pos?.[2], 0.95))) - 0.004;
      const w = x1 - x0, d = y1 - y0, cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
      const ped = box(w * 0.8, zt - 0.12, d * 0.6, MAT.panel); ped.position.set(cx, (zt - 0.12) / 2, cy + d * 0.1); this.root.add(ped);
      const top = box(w, 0.1, d, M(0x3a4552, { metalness: 0.3, roughness: 0.45 })); top.position.set(cx, zt - 0.05, cy); this.root.add(top);
      const face = box(w - 0.02, 0.004, d - 0.02, M(0x58646f, { roughness: 0.5 }), false); face.position.set(cx, zt + 0.001, cy); this.root.add(face);
      const tag = box(w * 0.5, 0.05, 0.004, MAT.yellow, false); tag.position.set(cx, zt - 0.05, cy + d / 2 + 0.003); this.root.add(tag);
    }
  }

  addComp(c: any) {
    const mk = MAKERS[c.type]; if (!mk) return;
    const cv = mk(c);
    const [x, y] = c.pos || [0, 0];
    cv.g.position.set(x, 0, y); cv.g.rotation.y = -((c.rot || 0) * Math.PI) / 180;
    cv.g.userData.comp = c.id;
    // Panel components use pos[2] directly for height; other components already account for pos[2] internally
    this.root.add(cv.g); this.comps.set(c.id, cv);
    if (CLICKABLE.has(c.type)) {            // Clickable 3D console components: add an invisible pick box slightly larger than the button
      const z = num(c.pos?.[2], 0.95);
      const hit = new THREE.Mesh(new THREE.BoxGeometry(0.11, 0.09, 0.11), new THREE.MeshBasicMaterial({ visible: false }));
      hit.position.set(0, z + 0.03, 0); hit.userData = { panelComp: c.id, panelType: c.type };
      cv.g.add(hit); this.hitTargets.push(hit);
    }
    if (this.labels) {
      const el = document.createElement('div'); el.className = 'cell-tag'; el.textContent = c.label ? `${c.id} ${c.label}` : c.id;
      const lb = new CSS2DObject(el); lb.position.set(0, num(c.pos?.[2], 0) + 0.45, 0); cv.g.add(lb); this.labelObjs.push(lb);
    }
  }

  clear() {
    for (const o of [this.root, this.partsRoot]) {
      o.traverse((m: any) => { if (m.isCSS2DObject) m.element.remove(); if (m.geometry) m.geometry.dispose?.(); });
      o.clear();
    }
    this.comps.clear(); this.partObjs.clear(); this.labelObjs = []; this.frames = []; this.pt = -1; this.lastT = -1; this.hitTargets = [];
  }

  /** Receive a view (backend Cell.view()['cell']); frames holds the latest frames. */
  push(view: any) {
    if (!view) return;
    this.lastView = view;
    const now = performance.now() / 1000;
    const fr: Frame[] = [];
    for (const f of view.frames || []) fr.push({ t: f[0], comps: f[1], parts: new Map((f[2] || []).map((p: any) => [p.i, p])) });
    fr.push({ t: view.t, comps: view.comps, parts: new Map((view.parts || []).map((p: any) => [p.i, p])) });
    fr.sort((a, b) => a.t - b.t);
    let newest = this.lastT;
    for (const f of fr) if (f.t > this.lastT + 1e-6) { this.frames.push(f); newest = Math.max(newest, f.t); }
    if (newest < this.lastT - 1) { this.frames = fr; this.pt = -1; newest = fr[fr.length - 1].t; }    // Cell reset: time rolls back
    if (this.lastT >= 0 && newest > this.lastT && this.lastWall) {
      const r = (newest - this.lastT) / Math.max(0.05, now - this.lastWall);
      this.rate = this.rate * 0.7 + Math.min(60, r) * 0.3;
    }
    if (newest > this.lastT) { this.lastT = newest; this.lastWall = now; }
    while (this.frames.length > 2 && this.frames[0].t < this.lastT - 4) this.frames.shift();
  }

  tick(dt: number, t = 0) {
    const fs = this.frames;
    if (!fs.length) return;
    const last = fs[fs.length - 1].t, lag = Math.max(0.25, this.rate * 0.35);
    if (this.pt < 0 || this.pt < last - lag * 3 || this.pt > last) this.pt = Math.max(fs[0].t, last - lag);
    else this.pt = Math.min(last, this.pt + dt * this.rate);
    let i = fs.length - 1;
    while (i > 0 && fs[i - 1].t > this.pt) i--;
    const b = fs[i], a = i > 0 ? fs[i - 1] : b;
    const f = b.t > a.t ? Math.min(1, Math.max(0, (this.pt - a.t) / (b.t - a.t))) : 1;
    const ctx = { t, dt, frac: f };
    for (const [id, cv] of this.comps) {
      if (!cv.up) continue;
      const va = a.comps?.[id], vb = b.comps?.[id];
      cv.up(va && vb ? lerpVal(va, vb, f) : vb || va || {}, ctx);
    }
    const seen = new Set<string>();
    const show = (p: any, q: any) => {
      let o = this.partObjs.get(p.i);
      if (!o) { o = makePart(p); this.partsRoot.add(o); this.partObjs.set(p.i, o); }
      const pa = p.p, pb = (q || p).p;
      o.position.set(pa[0] + (pb[0] - pa[0]) * f, pa[2] + (pb[2] - pa[2]) * f, pa[1] + (pb[1] - pa[1]) * f);
      o.rotation.y = -lerpAngle(p.a || 0, (q || p).a || 0, f);
      o.rotation.z = (q || p).d ? 0.6 : 0;
      seen.add(p.i);
    };
    for (const [id, p] of a.parts) show(p, b.parts.get(id));
    if (f > 0.5) for (const [id, p] of b.parts) if (!seen.has(id)) show(p, p);
    for (const [id, o] of this.partObjs) if (!seen.has(id)) { this.partsRoot.remove(o); this.partObjs.delete(id); }
  }

  /** Keep actuators at their initial positions without live data (in the editor). */
  idle() { for (const cv of this.comps.values()) cv.up?.({}, { t: 0, dt: 0, frac: 0 }); }
}

// ---------------------------------------------------------------- Attach to FactoryScene
async function fetchDef(pid: string, bid: string) {
  try {
    const r = await fetch(`/api/p/${encodeURIComponent(pid)}/cells/${encodeURIComponent(bid)}`, { headers: session.token ? { Authorization: 'Bearer ' + session.token } : {} });
    if (!r.ok) return null;
    const j = await r.json();
    return j.cell || null;
  } catch { return null; }
}

/** Draft cell definition (render the draft in 3D before Workbench editor changes are applied). */
let draftLookup: ((pid: string, bid: string) => any) | null = null;
export function setDraftLookup(fn: (pid: string, bid: string) => any) { draftLookup = fn; }

function addStackLight(it: any, L: number, W: number) {
  const g = it.group;
  const post = box(0.04, 1.25, 0.04, MAT.leg); post.position.set(-L / 2 + 0.15, 0.625, -W / 2 + 0.15); g.add(post);
  const segs = [0xd23c3c, 0xf2c230, 0x2e9d5b];
  segs.forEach((c, i) => {
    const s = cylY(0.045, 0.08, new THREE.MeshStandardMaterial({ color: c, transparent: true, opacity: 0.55, roughness: 0.3 }), 16);
    s.position.set(-L / 2 + 0.15, 1.42 - i * 0.085, -W / 2 + 0.15); g.add(s);
  });
  const lamp = new THREE.Mesh(new THREE.SphereGeometry(0.05, 16, 10), new THREE.MeshStandardMaterial({ color: 0x888888, emissive: 0x888888, emissiveIntensity: 0.9 }));
  lamp.position.set(-L / 2 + 0.15, 1.52, -W / 2 + 0.15); g.add(lamp);
  it.lamp = lamp;
}

const CLICKABLE = new Set(['button', 'estop', 'switch']);

async function panelAct(pid: string, bid: string, comp: string, action: string, value: any = null) {
  try {
    const r = await fetch(`/api/p/${encodeURIComponent(pid)}/cells/${encodeURIComponent(bid)}/panel`, {
      method: 'POST', headers: { 'Content-Type': 'application/json', ...(session.token ? { Authorization: 'Bearer ' + session.token } : {}) },
      body: JSON.stringify({ comp, action, value, hold: 0.4 }),
    });
    if (!r.ok) console.warn($t('cell.controlPanelButton'), comp, r.status);
  } catch (e) { console.warn($t('cell.controlPanelButton'), e); }
}

/** Frame a machine, calculating camera distance from its size. The shell's F shortcut can call scene.frameItem(id) directly. */
export function frameItem(scene: any, id: string, fill = 1) {
  const it = scene.items?.get(id); if (!it) return false;
  const [L, W] = it.s?.size || [4, 4];
  const span = Math.max(L, W * 1.6, 3) / Math.max(0.3, fill);
  const tgt = it.group.position.clone(); tgt.y = 0.5;
  const yaw = it.group.rotation.y;
  const off = new THREE.Vector3(span * 0.35, span * 0.55, span * 0.78).applyAxisAngle(new THREE.Vector3(0, 1, 0), yaw);
  scene.controls.target.copy(tgt);
  scene.camera.position.copy(tgt.clone().add(off));
  scene.follow = false;
  scene.controls.update();
  return true;
}

/** 3D console: hold buttons to press, click E-Stop to latch/reset, click knobs to toggle. */
function installPanelPicking(scene: any) {
  if (scene._cellPick) return;
  scene._cellPick = true;
  const el: HTMLElement = scene.labels?.domElement || scene.renderer?.domElement;
  if (!el) return;
  const ray = new THREE.Raycaster(), m = new THREE.Vector2();
  let held: { bid: string; comp: string } | null = null;
  const pick = (e: PointerEvent) => {
    const targets: THREE.Object3D[] = [];
    const owner = new Map<THREE.Object3D, string>();
    for (const [id, it] of scene.items || []) {
      const md = it.parts?.model;
      if (it.s?.kind !== 'cell' || !md) continue;
      for (const h of md.hitTargets) { targets.push(h); owner.set(h, id); }
    }
    if (!targets.length) return null;
    const r = el.getBoundingClientRect();
    m.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    ray.setFromCamera(m, scene.camera);
    const hit = ray.intersectObjects(targets, false)[0];
    if (!hit) return null;
    const it = scene.items.get(owner.get(hit.object));
    return { bid: owner.get(hit.object)!, comp: hit.object.userData.panelComp, type: hit.object.userData.panelType, it };
  };
  el.addEventListener('pointerdown', (e: PointerEvent) => {
    if (e.button !== 0 || scene.editMode) return;
    const h = pick(e); if (!h) return;
    e.stopImmediatePropagation(); e.preventDefault();
    const pid = scene.meta?.id;
    const st = h.it?.parts?.model?.lastView?.comps?.[h.comp]?.s;
    if (h.type === 'button') { held = { bid: h.bid, comp: h.comp }; panelAct(pid, h.bid, h.comp, 'set', 1); }
    else if (h.type === 'estop') panelAct(pid, h.bid, h.comp, st ? 'release' : 'press');
    else panelAct(pid, h.bid, h.comp, 'toggle');
  }, true);
  const up = () => { if (held) { panelAct(scene.meta?.id, held.bid, held.comp, 'release'); held = null; } };
  el.addEventListener('pointerup', up, true);
  el.addEventListener('pointerleave', up, true);
  el.addEventListener('click', (e: MouseEvent) => { if (pick(e as PointerEvent)) { e.stopImmediatePropagation(); } }, true);
  scene.cellPanelAt = (e: MouseEvent) => !!pick(e as PointerEvent);      // Check double-clicks first: clicking a console button should not enter the machine

  let last = 0;
  el.addEventListener('pointermove', (e: PointerEvent) => {
    const now = performance.now(); if (now - last < 60) return; last = now;
    const h = pick(e);
    if (scene.hover) scene.hover.setPanelHot(!!h); else el.style.cursor = h ? 'pointer' : '';   // The hover module manages the cursor centrally (scene_ext/hover.ts)
    el.title = h ? $t('common.n01', [h.comp, h.type === 'button' ? $t('cell.holdToPress') : h.type === 'estop' ? $t('cell.clickToPressClickAgain') : $t('cell.clickToToggle')]) : '';
  });
}

export function register(scene: any) {
  (window as any).__vfCellScene = scene;          // Test hook: UI acceptance scripts use this to position the camera
  scene.frameItem = (id: string, fill = 1) => frameItem(scene, id, fill);
  installPanelPicking(scene);
  scene.mk_cell = function (this: any, it: any, L: number, W: number) {
    const model = new CellModel();
    it.group.add(model.group);
    it.parts = { model, rev: -1, draft: null, loading: false, L, W };
    it.h = 2.6;
    addStackLight(it, L, W);
    const draft = draftLookup?.(this.meta?.id, it.s.id) || it.s.cell || it.s.cfg?.cell;
    if (draft) { model.build(draft, [L, W]); model.idle(); it.parts.draft = draft; }
    else model.build({ components: [] }, [L, W]);
    const pid = this.meta?.id;
    // Students/teachers entering a sandbox (ID starts with sb-): frame the control cell directly
    if (String(pid || '').startsWith('sb-') && !this._cellFramed) {
      this._cellFramed = true;
      setTimeout(() => frameItem(this, it.s.id, 1.05), 400);
    }
    if (pid && !draft) {
      it.parts.loading = true;
      fetchDef(pid, it.s.id).then((d) => { it.parts.loading = false; if (d) { model.build(d, [L, W]); model.idle(); } });
    }
  };
  scene.up_cell = function (this: any, it: any, st: any, t: number, dt: number) {
    const ps = it.parts; if (!ps?.model) return;
    const v = st.cell;
    const draft = draftLookup?.(this.meta?.id, it.s.id);
    if (draft && draft !== ps.draft) { ps.draft = draft; ps.model.build(draft, [ps.L, ps.W]); ps.model.idle(); }
    else if (v && v.rev !== ps.rev && !ps.loading && !draft) {
      const first = ps.rev === -1; ps.rev = v.rev;
      if (!first || !ps.model.comps.size) {
        ps.loading = true;
        fetchDef(this.meta?.id, it.s.id).then((d) => { ps.loading = false; if (d) ps.model.build(d, [ps.L, ps.W]); });
      }
    } else if (v && ps.rev === -1) ps.rev = v.rev;
    if (v) ps.model.push(v);
    ps.model.tick(dt, t);
  };
}
