// 3D factory: place equipment using the layout from /api/p/<factory>/meta and animate it using WebSocket state.
// Foundry equipment, CNC, and AGVs are generated procedurally; conveyors, robots, crates, boards, pipes, and people use Kenney open-source models (CC0, see public/models/*/LICENSE*).
import { $t, matches, variants } from './i18n';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';
import { CSS2DObject, CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import * as SkeletonUtils from 'three/examples/jsm/utils/SkeletonUtils.js';
import { wallPieces } from './editor/plan/geom';

const STATE_COLOR: Record<string, number> = { Executing: 0x2e9d5b, Idle: 0xe0a630, Setup: 0x3b82c4, Stopped: 0xd23c3c, Starved: 0xd9b23a, Blocked: 0x9b59b6, Planned: 0x7d7aa8 };
const STATE_CN: Record<string, string> = { Executing: $t('common.running'), Idle: $t('common.idle'), Setup: $t('scene.changeoverToolChange'), Stopped: $t('common.down'), Starved: $t('common.materialShortage'), Blocked: $t('common.blocked'), Planned: $t('common.plannedDowntime') };
const M = (c: number, o: any = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: 0.65, metalness: 0.15, ...o });
const box = (w: number, h: number, d: number, mat: THREE.Material, shadow = true) => {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.castShadow = shadow; m.receiveShadow = true; return m;
};
const cyl = (r: number, h: number, mat: THREE.Material, seg = 24) => {
  const m = new THREE.Mesh(new THREE.CylinderGeometry(r, r, h, seg), mat);
  m.castShadow = true; m.receiveShadow = true; return m;
};

const FACTORY = ['robot-arm-a', 'conveyor-long-stripe-sides', 'box-small', 'box-large', 'box-wide', 'cone', 'warning-traffic', 'screen-hanging-wide',
  'screen-panel-wide', 'scanner-high', 'pipe-large-long', 'hopper-high-round'];
const PEOPLE = ['character-male-a', 'character-female-a', 'character-male-b', 'character-female-b', 'character-male-c', 'character-female-c',
  'character-male-d', 'character-female-d'];

/** Model library: load once, clone on demand; callers fall back to procedural models on load failure. */
class Assets {
  lib = new Map<string, any>();
  async load() {
    const loader = new GLTFLoader();
    const jobs: [string, string][] = [...FACTORY.map((n) => ['factory', n] as [string, string]), ...PEOPLE.map((n) => ['people', n] as [string, string])];
    await Promise.all(jobs.map(async ([d, n]) => {
      try {
        const g = await loader.loadAsync(`/models/${d}/${n}.glb`);
        g.scene.traverse((o: any) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
        this.lib.set(n, g);
      } catch (e) { console.warn($t('scene.failedToLoadTheModel'), n, e); }
    }));
  }
  get(n: string, s = 1): THREE.Object3D | null {
    const g = this.lib.get(n); if (!g) return null;
    const o = g.scene.clone(true); o.scale.setScalar(s); return o;
  }
  /** Bake all model meshes into instanced meshes for repeated crates and pipes. */
  instanced(n: string, count: number, s = 1) {
    const g = this.lib.get(n); if (!g) return null;
    const grp = new THREE.Group(); const meshes: THREE.InstancedMesh[] = [];
    g.scene.updateMatrixWorld(true);
    g.scene.traverse((o: any) => {
      if (!o.isMesh) return;
      const geo = o.geometry.clone().applyMatrix4(o.matrixWorld).scale(s, s, s);
      const im = new THREE.InstancedMesh(geo, o.material, count); im.castShadow = true; im.receiveShadow = true; im.count = 0;
      grp.add(im); meshes.push(im);
    });
    return { grp, set(i: number, m4: THREE.Matrix4) { for (const im of meshes) im.setMatrixAt(i, m4); },
      count(n2: number) { for (const im of meshes) { im.count = n2; im.instanceMatrix.needsUpdate = true; } } };
  }
}

function chevronTexture() {
  const c = document.createElement('canvas'); c.width = 128; c.height = 64;
  const g = c.getContext('2d')!;
  g.fillStyle = 'rgba(0,140,255,0.55)'; g.fillRect(0, 10, 128, 44);
  g.strokeStyle = 'rgba(255,255,255,0.95)'; g.lineWidth = 9; g.lineCap = 'round';
  for (const x0 of [20, 84]) { g.beginPath(); g.moveTo(x0, 18); g.lineTo(x0 + 22, 32); g.lineTo(x0, 46); g.stroke(); }
  const t = new THREE.CanvasTexture(c); t.wrapS = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; return t;
}

function concreteTexture() {
  const c = document.createElement('canvas'); c.width = c.height = 512;
  const g = c.getContext('2d')!;
  // 5.0.1 light theme: light gray concrete floor + cobalt-gray grid (6 m cells, thin lines every 1 m), matching the 2D canvas grid.
  g.fillStyle = '#d3d9e0'; g.fillRect(0, 0, 512, 512);
  for (let i = 0; i < 9000; i++) { const v = 188 + Math.random() * 46; g.fillStyle = `rgba(${v},${v + 4},${v + 9},0.22)`; g.fillRect(Math.random() * 512, Math.random() * 512, 2, 2); }
  g.strokeStyle = 'rgba(60,90,135,0.10)'; g.lineWidth = 1.5;
  for (let k = 1; k < 6; k++) { const p = Math.round(k * 512 / 6) + 0.5; g.beginPath(); g.moveTo(p, 0); g.lineTo(p, 512); g.moveTo(0, p); g.lineTo(512, p); g.stroke(); }
  g.strokeStyle = 'rgba(55,85,130,0.30)'; g.lineWidth = 2; g.strokeRect(1, 1, 510, 510);
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8; return t;
}

function panelTexture() {
  const c = document.createElement('canvas'); c.width = 256; c.height = 256;
  const g = c.getContext('2d')!;
  g.fillStyle = '#d8dde2'; g.fillRect(0, 0, 256, 256);
  for (let x = 0; x < 256; x += 16) { g.fillStyle = 'rgba(120,130,140,0.35)'; g.fillRect(x, 0, 3, 256); g.fillStyle = 'rgba(255,255,255,0.5)'; g.fillRect(x + 4, 0, 2, 256); }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; return t;
}

export class FactoryScene {
  renderer: THREE.WebGLRenderer; labels: CSS2DRenderer; scene = new THREE.Scene(); camera: THREE.PerspectiveCamera; controls: OrbitControls;
  cx = 0; cy = 0; span = 150; meta: any; heat = new THREE.Group(); layers: Record<string, boolean> = { labels: true, flow: true, people: true, agv: true, heat: false, transfer: true }; items = new Map<string, any>(); state: any = null; onPick: (id: string) => void = () => {};
  /** Graph markers from the Workbench: { equipmentId: { bp: 'on'|'off'|'', w: watchText } }. */
  marks: Record<string, { bp: string; w: string }> = {};
  ray = new THREE.Raycaster(); mouse = new THREE.Vector2(); clock = new THREE.Clock(); selected = ''; assets = new Assets();
  nodes: Record<string, any> = {}; workers = new Map<string, any>(); bounds = { x0: 0, x1: 0, y0: 0, y1: 0 };
  // Transfer lines / tracking
  flow = new THREE.Group(); flowTex = chevronTexture(); flowSteps: CSS2DObject[] = []; showFlow = true;
  marker = new THREE.Group(); markerLabel!: CSS2DObject; trackPos: THREE.Vector3 | null = null; follow = false; curStep = -1;
  // Editing
  editMode = false; tc: TransformControls; tcHelper: THREE.Object3D; justDragged = false;
  onMoved: (id: string, pos: [number, number], rot: number) => void = () => {};
  onNodeMoved: (node: string, pos: [number, number]) => void = () => {};
  onEditPick: (id: string) => void = () => {};
  crane: any = null; furnaceArea: [number, number] | null = null;
  /** Extension hooks (scene_ext/*): called before/after each frame renders (hover outlines overlay via afterRender); cleaned up on dispose. */
  beforeRender: ((dt: number, t: number) => void)[] = []; afterRender: ((dt: number, t: number) => void)[] = []; disposers: (() => void)[] = [];
  /** Increment when pickable objects (equipment groups, AGVs, people) are added or removed to trigger a pick cache rebuild. */
  pickRev = 0;

  constructor(private el: HTMLElement) {
    // 3D quality (selected in client settings, stored in localStorage vf_quality): low = no antialiasing, 1x pixel ratio, no shadows, for integrated GPUs and older computers.
    const low = (() => { try { return localStorage.getItem('vf_quality') === 'low'; } catch { return false; } })();
    this.renderer = new THREE.WebGLRenderer({ antialias: !low, preserveDrawingBuffer: true });
    this.renderer.setPixelRatio(low ? 1 : Math.min(devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = !low;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    el.appendChild(this.renderer.domElement);
    this.labels = new CSS2DRenderer();
    this.labels.domElement.className = 'labels';
    el.appendChild(this.labels.domElement);
    // Light sky (close to --hm-canvas, slightly darker to distinguish the horizon).
    this.scene.background = new THREE.Color(0xe9eef5);
    this.scene.fog = new THREE.Fog(0xe9eef5, 180, 360);
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.5, 900);
    this.controls = new OrbitControls(this.camera, this.labels.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.47;
    this.controls.minDistance = 4; this.controls.maxDistance = 280;
    this.controls.addEventListener('start', () => { this.autoView = false; });
    // Cool skylight, gray ground reflection, and slightly weaker sunlight keep light gray equipment from washing out and shadows soft.
    this.scene.add(new THREE.HemisphereLight(0xf4f8ff, 0x8a929c, 1.3));
    const sun = new THREE.DirectionalLight(0xffffff, 1.55);
    sun.position.set(-40, 90, 50);
    sun.castShadow = true;
    sun.shadow.mapSize.set(4096, 4096);
    sun.shadow.bias = -0.0004;
    Object.assign(sun.shadow.camera, { left: -110, right: 110, top: 70, bottom: -70, near: 1, far: 260 });
    this.scene.add(sun);
    this.tc = new TransformControls(this.camera, this.labels.domElement);
    this.tc.setMode('translate'); this.tc.showY = false; this.tc.setTranslationSnap(0.5); this.tc.setSize(0.9);
    this.tcHelper = this.tc.getHelper(); this.scene.add(this.tcHelper);
    this.tc.addEventListener('dragging-changed', (e: any) => {
      this.controls.enabled = !e.value;
      if (e.value) { this.justDragged = true; return; }
      const o: any = this.tc.object; if (!o) return;
      const pos: [number, number] = [+(o.position.x + this.cx).toFixed(2), +(o.position.z + this.cy).toFixed(2)];
      if (o.userData.node) this.onNodeMoved(o.userData.node, pos);
      else if (o.userData.id) this.onMoved(o.userData.id, pos, Math.round(-o.rotation.y * 180 / Math.PI));
    });
    this.scene.add(this.flow, this.marker, this.heat);
    this.buildMarker();
    addEventListener('resize', () => this.resize());
    new ResizeObserver(() => this.resize()).observe(el);
    this.labels.domElement.addEventListener('click', (e) => this.pick(e));
    this.resize();
  }

  resize() {
    const w = this.el.clientWidth, h = this.el.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h); this.labels.setSize(w, h);
    this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
    if (this.autoView && this.bounds) this.viewPreset('overview');   // Reframe the factory on viewport resize until the user moves the camera.
  }
  lastDeclutter = 0;
  /** Auto-generated building shell (walls, roof trusses, window bands). */
  shellG = new THREE.Group();
  /** Label collision avoidance: place by priority (selected > alarm > breakpoint/watch > large equipment); collapse overlaps to status-colored dots. Selected or hovered equipment always shows its full name. */
  declutter() {
    if (!this.layers.labels) return;
    const W = this.el.clientWidth, H = this.el.clientHeight, v = new THREE.Vector3(), placed: number[][] = [];
    const list = [...this.items.values()].filter((it) => it.label);
    const pri = (it: any) => (it.s.id === this.selected ? 0 : it.label.element.classList.contains('alarm') ? 1 : this.marks[it.s.id] ? 2 : 3 + 1 / (1 + (it.s.size?.[0] || 1) * (it.s.size?.[1] || 1)));
    list.sort((a, b) => pri(a) - pri(b));
    for (const it of list) {
      const el = it.label.element as HTMLElement;
      it.label.getWorldPosition(v); v.project(this.camera);
      if (v.z > 1 || Math.abs(v.x) > 1.2 || Math.abs(v.y) > 1.2) continue;
      if (!el.classList.contains('mini')) { it.lw = el.offsetWidth || it.lw || 80; it.lh = el.offsetHeight || it.lh || 20; }
      const x = (v.x + 1) / 2 * W, y = (1 - v.y) / 2 * H - 14, w = it.lw || 80, h = it.lh || 20;
      const r = [x - w / 2, y - h, x + w / 2, y];
      const hit = placed.some((p) => r[0] < p[2] && r[2] > p[0] && r[1] < p[3] && r[3] > p[1]);
      const keep = pri(it) < 2 || !hit;
      el.classList.toggle('mini', !keep);
      if (keep) placed.push(r);
    }
  }
  /** Still in automatic overview (the user has not dragged the camera). */
  autoView = false;

  P(x: number, y: number, h = 0) { return new THREE.Vector3(x - this.cx, h, y - this.cy); }

  async build(meta: any) {
    await this.assets.load();
    this.meta = meta;
    const xs = meta.stations.filter((s: any) => s.kind !== 'crew').map((s: any) => s.pos[0]);
    const ys = meta.stations.filter((s: any) => s.kind !== 'crew').map((s: any) => s.pos[1]);
    const agv = meta.stations.find((s: any) => s.kind === 'agv');
    if (agv) Object.values(agv.cfg.nodes).forEach((n: any) => { xs.push(n[0]); ys.push(n[1]); });
    for (const a of meta.areas) { xs.push(a.x[0], a.x[1]); }
    if (meta.floor?.[0] && xs.length) { xs.push(Math.min(...xs, 0), Math.max(...xs, meta.floor[0])); ys.push(Math.min(...(ys.length ? ys : [0]), 0), Math.max(...(ys.length ? ys : [0]), meta.floor[1] || 0)); }   // Frame the entire building in the overview.
    if (!ys.length) ys.push(0, (meta.floor || [60, 40])[1]);
    if (!xs.length) xs.push(0, (meta.floor || [60, 40])[0]);
    const x0 = Math.min(...xs) - 4, x1 = Math.max(...xs) + 4, y0 = Math.min(...ys) - 6, y1 = Math.max(...ys) + 9;
    this.bounds = { x0, x1, y0, y1 };
    this.cx = (x0 + x1) / 2; this.cy = (y0 + y1) / 2;
    const span = Math.max(x1 - x0, (y1 - y0) * 2);
    // The left panel takes about 1/5 of the screen width; shift the target right to center the factory in the visible area.
    this.span = span;
    this.viewPreset('overview');
    this.buildFloor(meta, x0, x1, y0, y1);
    { const n0 = this.scene.children.length; this.buildShell(x0, x1, y0, y1); for (const o of this.scene.children.slice(n0)) this.shellG.add(o); this.scene.add(this.shellG); }
    this.buildCrane(meta, y0, y1);
    for (const s of meta.stations) this.addStation(s);
    this.buildFlow(meta.route);
    this.renderer.setAnimationLoop(() => this.frame());
  }

  label(html: string, cls = 'lbl') {
    const d = document.createElement('div'); d.innerHTML = html; d.className = cls;
    return new CSS2DObject(d);
  }

  // ---------- Building ----------
  buildFloor(meta: any, x0: number, x1: number, y0: number, y1: number) {
    const W = x1 - x0 + 16, D = y1 - y0 + 16;
    const tex = concreteTexture(); tex.repeat.set(W / 6, D / 6);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, D), new THREE.MeshStandardMaterial({ map: tex, roughness: 0.92 }));
    floor.rotation.x = -Math.PI / 2; floor.position.copy(this.P((x0 + x1) / 2, (y0 + y1) / 2, 0)); floor.receiveShadow = true;
    this.scene.add(floor);
    const yellow = M(0xf2c230, { roughness: 0.8 }), green = M(0x3aa26a, { roughness: 0.9 }), white = M(0xf4f6f7, { roughness: 0.9 });
    for (const a of meta.areas) {
      const w = a.x[1] - a.x[0];
      const pl = new THREE.Mesh(new THREE.PlaneGeometry(w - 0.6, y1 - y0 - 5), M(new THREE.Color(a.color).getHex(), { roughness: 1, transparent: true, opacity: 0.55 }));
      pl.rotation.x = -Math.PI / 2; pl.position.copy(this.P(a.x[0] + w / 2, (y0 + y1) / 2 - 2.5, 0.01)); pl.receiveShadow = true;
      this.scene.add(pl);
      const lab = this.label(`<div class="area">${a.name}</div>`); lab.position.copy(this.P(a.x[0] + w / 2, y1 + 0.5, 0)); this.scene.add(lab);
      // Yellow zone markings
      for (const ex of [a.x[0] + 0.3, a.x[1] - 0.3]) {
        const ln = box(0.14, 0.02, y1 - y0 - 5, yellow, false); ln.position.copy(this.P(ex, (y0 + y1) / 2 - 2.5, 0.02)); this.scene.add(ln);
      }
    }
    // Front pedestrian walkway (green + zebra crossings)
    const wy = y1 - 2.2;
    const walk = box(x1 - x0, 0.02, 2.2, green, false); walk.position.copy(this.P((x0 + x1) / 2, wy, 0.02)); this.scene.add(walk);
    for (let x = x0 + 1; x < x1; x += 1.2) { const z = box(0.5, 0.025, 2.0, white, false); z.position.copy(this.P(x, wy, 0.025)); if (Math.floor((x - x0) / 1.2) % 10 < 3) this.scene.add(z); }
    // AGV lane: yellow fill + white lines on both sides
    const agv = meta.stations.find((s: any) => s.kind === 'agv');
    if (agv) {
      const cy = agv.cfg.corridor_y ?? 0;
      const lane = box(x1 - x0, 0.02, 2.6, M(0xe9d27a, { roughness: 1 }), false); lane.position.copy(this.P((x0 + x1) / 2, cy, 0.02)); this.scene.add(lane);
      for (const dy of [-1.35, 1.35]) { const l = box(x1 - x0, 0.03, 0.12, white, false); l.position.copy(this.P((x0 + x1) / 2, cy + dy, 0.025)); this.scene.add(l); }
    }
  }

  buildShell(x0: number, x1: number, y0: number, y1: number) {
    const H = 11, steel = M(0x7d8a96, { metalness: 0.5, roughness: 0.5 }), concrete = M(0xa9adb1, { roughness: 0.95 });
    const ptex = panelTexture(); ptex.repeat.set((x1 - x0) / 4, 1);
    const panel = new THREE.MeshStandardMaterial({ map: ptex, roughness: 0.7, metalness: 0.2 });
    const glass = M(0x9fc6e6, { emissive: 0xbfdcf2, emissiveIntensity: 0.35, roughness: 0.2, metalness: 0.1 });
    const by = y0 - 1.2, L = x1 - x0 + 6;
    // Rear wall: plinth + color-coated steel panels + high window band
    const base = box(L, 1.4, 0.4, concrete); base.position.copy(this.P((x0 + x1) / 2, by, 0.7)); this.scene.add(base);
    const wall = box(L, H - 1.4, 0.25, panel); wall.position.copy(this.P((x0 + x1) / 2, by - 0.05, 1.4 + (H - 1.4) / 2)); this.scene.add(wall);
    for (let x = x0; x < x1; x += 6) { const w = box(4.2, 1.6, 0.1, glass, false); w.position.copy(this.P(x + 2.5, by + 0.12, H - 2.6)); this.scene.add(w); }
    // Side walls (lower to keep the view clear)
    for (const sx of [x0 - 3, x1 + 3]) {
      const sw = box(0.25, 4, y1 - y0 + 2.4, panel); sw.position.copy(this.P(sx, (y0 + y1) / 2, 2)); this.scene.add(sw);
    }
    // Wall-side steel columns + eave beams (omit the front and roof for a clear overhead view)
    for (let x = x0; x <= x1 + 0.1; x += 12) {
      const c = box(0.5, H, 0.5, steel); c.position.copy(this.P(x, by + 0.45, H / 2)); this.scene.add(c);
      const bk = box(0.3, 0.5, 1.6, steel, false); bk.position.copy(this.P(x, by + 1.2, H - 2.2)); this.scene.add(bk);
    }
    for (const sx of [x0 - 3, x1 + 3]) for (let y = by + 6; y < y1; y += 12) { const c = box(0.4, 4.6, 0.4, steel); c.position.copy(this.P(sx, y, 2.3)); this.scene.add(c); }
    const eave = box(x1 - x0 + 6, 0.45, 0.35, steel, false); eave.position.copy(this.P((x0 + x1) / 2, by + 0.45, H + 0.2)); this.scene.add(eave);
    // Crane runway beam (along the rear wall)
    const rail = box(x1 - x0, 0.3, 0.3, M(0xf2c230), false); rail.position.copy(this.P((x0 + x1) / 2, by + 1.2, H - 1.8)); this.scene.add(rail);
    // Rear-wall utility pipes (open-source models, instanced)
    const n = Math.ceil((x1 - x0) / 1.6);
    const pipe = this.assets.instanced('pipe-large-long', n, 0.8);
    if (pipe) {
      const m4 = new THREE.Matrix4();
      for (let i = 0; i < n; i++) { const q = this.P(x0 + 0.8 + i * 1.6, by + 0.9); m4.makeTranslation(q.x, 7.0, q.z); pipe.set(i, m4); }
      pipe.count(n); this.scene.add(pipe.grp);
    }
    // Suspended display boards
    for (const a of this.meta.areas) {
      const sc = this.assets.get('screen-hanging-wide', 3.2);
      if (!sc) break;
      sc.position.copy(this.P((a.x[0] + a.x[1]) / 2, by + 2.2, 6.6)); this.scene.add(sc);
      const cable = box(0.04, H - 8.8, 0.04, steel, false); cable.position.copy(this.P((a.x[0] + a.x[1]) / 2, by + 2.2, 8.8 + (H - 8.8) / 2)); this.scene.add(cable);
    }
    // Cones and bollards at lane entrances
    const agv = this.meta.stations.find((s: any) => s.kind === 'agv');
    const cy = agv?.cfg.corridor_y ?? y1 - 4;
    for (const a of this.meta.areas) {
      const tl = this.assets.get('warning-traffic', 1.4); if (!tl) break;
      tl.position.copy(this.P(a.x[0] + 0.6, cy + 1.9)); this.scene.add(tl);
    }
    for (const x of [x0 + 1, x1 - 1]) for (let k = 0; k < 3; k++) {
      const c = this.assets.get('cone', 2.2); if (!c) break;
      c.position.copy(this.P(x, cy - 0.9 + k * 0.9)); this.scene.add(c);
    }
  }

  /** Melting-area bridge crane: moves above the furnace opening and lowers its hook during electric furnace charging. */
  buildCrane(meta: any, y0: number, y1: number) {
    const area = meta.areas.find((a: any) => (a.kind === 'melting' || matches(a.name, 'scene.meltingArea')));
    if (!area || !meta.stations.some((s: any) => s.kind === 'furnace')) return;
    const H = 9.2, yel = M(0xf2c230, { metalness: 0.3, roughness: 0.5 }), dark = M(0x3d444b, { metalness: 0.5 });
    const a0 = area.x[0] + 1, a1 = area.x[1] - 1, b0 = y0 + 1, b1 = y1 - 4;
    for (const y of [b0, b1]) { const r = box(a1 - a0, 0.4, 0.4, dark, false); r.position.copy(this.P((a0 + a1) / 2, y, H)); this.scene.add(r); }
    const bridge = new THREE.Group();
    const beam = box(0.8, 0.9, b1 - b0, yel); beam.position.set(0, H + 0.5, 0); bridge.add(beam);
    for (const dz of [-(b1 - b0) / 2, (b1 - b0) / 2]) { const t = box(1.6, 0.6, 0.8, yel); t.position.set(0, H + 0.4, dz); bridge.add(t); }
    const trolley = new THREE.Group(); trolley.position.y = H + 1.1;
    trolley.add(box(1.5, 0.7, 1.5, dark));
    const rope = box(0.06, 1, 0.06, dark, false); trolley.add(rope);
    const hook = new THREE.Group(); hook.add(box(0.8, 0.6, 0.5, yel)); const bucket = cyl(0.8, 1.0, M(0x6a5a4a)); bucket.position.y = -0.9; hook.add(bucket); trolley.add(hook);
    bridge.add(trolley);
    bridge.position.copy(this.P(a0 + 2, (b0 + b1) / 2)); this.scene.add(bridge);
    this.crane = { bridge, trolley, rope, hook, H, park: [a0 + 2, (b0 + b1) / 2], drop: 0 };
  }
  upCrane(dt: number) {
    const c = this.crane; if (!c || !this.state) return;
    const fur = this.state.stations.find((s: any) => s.kind === 'furnace' && s.phase === 'Charging');
    const it = fur && this.items.get(fur.id);
    const tx = it ? it.s.pos[0] : c.park[0], ty = it ? it.s.pos[1] : c.park[1];
    const k = Math.min(1, dt * 0.8);
    const bx = c.bridge.position.x + (this.P(tx, 0).x - c.bridge.position.x) * k;
    c.bridge.position.x = bx;
    c.trolley.position.z += ((this.P(0, ty).z - c.bridge.position.z) - c.trolley.position.z) * k;
    const near = Math.abs(this.P(tx, 0).x - bx) < 0.4;
    c.drop += ((it && near ? 4.2 : 1.2) - c.drop) * k;
    c.hook.position.y = -c.drop; c.rope.scale.y = c.drop; c.rope.position.y = -c.drop / 2;
  }

  // ---------- Transfer lines ----------
  buildFlow(route: any[]) {
    this.flow.clear(); this.flowSteps.forEach((l) => l.element.remove()); this.flowSteps = [];
    if (!route?.length) return;
    const pts = route.map((s: any) => this.P(s.pos[0], s.pos[1], 0.09));
    const pos: number[] = [], uv: number[] = [], idx: number[] = []; let acc = 0; const w = 1.1;
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1]; const d = b.clone().sub(a); const len = d.length(); if (len < 0.1) continue;
      const n = new THREE.Vector3(-d.z, 0, d.x).normalize().multiplyScalar(w / 2); const k = pos.length / 3;
      for (const p of [a.clone().add(n), a.clone().sub(n), b.clone().add(n), b.clone().sub(n)]) pos.push(p.x, p.y, p.z);
      uv.push(acc / 1.8, 1, acc / 1.8, 0, (acc + len) / 1.8, 1, (acc + len) / 1.8, 0); acc += len;
      idx.push(k, k + 1, k + 2, k + 1, k + 3, k + 2);
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3)); geo.setAttribute('uv', new THREE.Float32BufferAttribute(uv, 2)); geo.setIndex(idx);
    const ribbon = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ map: this.flowTex, transparent: true, depthWrite: false, side: THREE.DoubleSide }));
    ribbon.renderOrder = 2; this.flow.add(ribbon);
    route.forEach((s: any, i: number) => {
      const disc = new THREE.Mesh(new THREE.CircleGeometry(0.85, 28), new THREE.MeshBasicMaterial({ color: 0x0a7cff, transparent: true, opacity: 0.85, depthWrite: false }));
      disc.rotation.x = -Math.PI / 2; disc.position.copy(pts[i]).setY(0.1); disc.renderOrder = 3; this.flow.add(disc);
      const lab = this.label(`<div class="step"><i>${i + 1}</i>${s.name}</div>`, 'lbl flat'); lab.position.copy(pts[i]).setY(0.6);
      this.flow.add(lab); this.flowSteps.push(lab);
    });
    this.setFlow(this.showFlow);
  }
  setFlow(on: boolean) {
    this.showFlow = on; this.flow.visible = on; this.el.classList.toggle('flow-on', on);
    this.flowSteps.forEach((l) => { l.visible = on; (l.element as HTMLElement).style.display = on ? '' : 'none'; });
  }
  setStep(i: number) {
    this.curStep = i;
    this.flowSteps.forEach((l, k) => l.element.classList.toggle('cur', k === i));
  }

  // ---------- Follow a Part ----------
  buildMarker() {
    const ring = new THREE.Mesh(new THREE.RingGeometry(1.0, 1.35, 40), new THREE.MeshBasicMaterial({ color: 0x00b4ff, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
    ring.rotation.x = -Math.PI / 2; ring.position.y = 0.15; ring.renderOrder = 4;
    const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.18, 0.18, 14, 12, 1, true), new THREE.MeshBasicMaterial({ color: 0x33c3ff, transparent: true, opacity: 0.35, blending: THREE.AdditiveBlending, depthWrite: false }));
    beam.position.y = 7;
    const gem = new THREE.Mesh(new THREE.OctahedronGeometry(0.45), new THREE.MeshBasicMaterial({ color: 0x00b4ff }));
    gem.position.y = 6.5;
    this.markerLabel = this.label('', 'lbl track'); this.markerLabel.position.y = 7.6;
    this.marker.add(ring, beam, gem, this.markerLabel); this.marker.visible = false;
    this.marker.userData = { ring, gem };
  }
  setTrack(loc: any | null, html = '') {
    if (!loc || !loc.pos) { this.marker.visible = false; this.trackPos = null; (this.markerLabel.element as HTMLElement).style.display = 'none'; return; }
    const p = this.P(loc.pos[0], loc.pos[1]);
    if (!this.trackPos || !this.marker.visible) this.marker.position.copy(p);
    this.trackPos = p; this.marker.visible = true;
    const el = this.markerLabel.element as HTMLElement; el.style.display = ''; el.innerHTML = html;
  }
  setFollow(on: boolean) {
    this.follow = on;
    if (on && this.trackPos) {
      const off = new THREE.Vector3(-10, 20, 24);
      this.controls.target.copy(this.trackPos); this.camera.position.copy(this.trackPos.clone().add(off));
    }
  }

  // ---------- Equipment ----------
  sync(meta: any) {           // Add, remove, or move equipment at runtime
    const ids = new Set(meta.stations.map((s: any) => s.id));
    for (const [id, it] of this.items) if (!ids.has(id)) { this.removeItem(id, it); }
    for (const s of meta.stations) {
      const it = this.items.get(s.id);
      if (!it) { this.addStation(s); continue; }
      it.s = s;
      if (this.tc.object !== it.group || !this.tc.dragging) {
        it.group.position.copy(this.P(s.pos[0], s.pos[1], s.elev || 0)); it.group.rotation.y = -(s.rot || 0) * Math.PI / 180;
      }
      if (it.label) (it.label.element.querySelector('b') as HTMLElement).textContent = s.kind === 'cnc' ? s.id : s.name;
    }
    this.meta = meta;
    this.buildFlow(meta.route);
  }
  removeItem(id: string, it: any) {
    if (this.tc.object === it.group) this.tc.detach();
    this.scene.remove(it.group); it.group.traverse((o: any) => { if (o.isCSS2DObject) o.element.remove(); });
    (it.ladles || []).forEach((l: any) => this.scene.remove(l));
    if (it.agvs && it.s.kind !== 'agv') for (const gr of it.agvs.values()) { this.scene.remove(gr); gr.traverse((o: any) => { if (o.isCSS2DObject) o.element.remove(); }); }
    this.items.delete(id); this.pickRev++;
  }

  addStation(s: any) {
    const g = new THREE.Group(); g.userData.id = s.id;
    const [x, y] = s.pos, [L, W] = s.size;
    g.position.copy(this.P(x, y, s.elev || 0)); g.rotation.y = -(s.rot || 0) * Math.PI / 180;
    const it: any = { s, group: g, parts: {} };
    const mk = (this as any)['mk_' + s.kind];
    if (mk) mk.call(this, it, L, W); else g.add(box(L, 1, W, M(0x999999)));
    if (!['agv', 'crew'].includes(s.kind)) {
      it.label = this.label(`<span class="dot"></span><b>${s.kind === 'cnc' ? s.id : s.name}</b><small></small>`);
      it.label.position.set(0, it.h || 3.5, 0); g.add(it.label);
    }
    if (s.kind !== 'agv' && s.kind !== 'crew') this.scene.add(g);
    this.items.set(s.id, it); this.pickRev++;
  }

  // Conveyor: joined Kenney belt segments along x
  conveyor(g: THREE.Object3D, len: number, width: number, h = 0.8, x = 0, z = 0) {
    const s = width; const n = Math.max(1, Math.round(len / (2 * s)));
    for (let i = 0; i < n; i++) {
      const c = this.assets.get('conveyor-long-stripe-sides'); if (!c) { const b = box(len, h, width, M(0x444a50)); b.position.set(x, h / 2, z); g.add(b); return h; }
      c.scale.set(len / (n * 2), h / 0.4, s); c.position.set(x - len / 2 + (i + 0.5) * len / n, 0, z); g.add(c);
    }
    return h;
  }

  mk_furnace(it: any) {
    const g = it.group;
    const base = box(3.8, 1.0, 3.8, M(0x59616b)); base.position.y = 0.5; g.add(base);
    const body = cyl(1.55, 1.9, M(0x6e5a4e)); body.position.y = 1.95; g.add(body);
    for (let i = 0; i < 4; i++) { const ring = new THREE.Mesh(new THREE.TorusGeometry(1.6, 0.08, 8, 32), M(0xb87333, { metalness: 0.6 })); ring.rotation.x = Math.PI / 2; ring.position.y = 1.3 + i * 0.4; g.add(ring); }
    const melt = cyl(1.2, 0.08, M(0x331100, { emissive: 0xff5500, emissiveIntensity: 0 })); melt.position.y = 2.92; g.add(melt);
    const light = new THREE.PointLight(0xff7a20, 0, 14); light.position.y = 3.6; g.add(light);
    // Furnace platforms, railings, control cabinets, cooling water pipes
    const deck = box(2.2, 0.15, 4.4, M(0x7b8794)); deck.position.set(-3.0, 1.2, 0); g.add(deck);
    const rail = M(0xf2c230);
    for (const z of [-2.1, 2.1]) { const r = box(2.2, 0.06, 0.06, rail); r.position.set(-3.0, 2.2, z); g.add(r); }
    const r2 = box(0.06, 0.06, 4.2, rail); r2.position.set(-4.05, 2.2, 0); g.add(r2);
    for (const [px, pz] of [[-4.05, -2.1], [-4.05, 2.1], [-1.95, -2.1], [-1.95, 2.1]]) { const p = box(0.06, 1.0, 0.06, rail); p.position.set(px, 1.7, pz); g.add(p); }
    const cab = box(1.2, 2.0, 0.6, M(0xdfe3e7)); cab.position.set(1.0, 1.0, -2.6); g.add(cab);
    const scr = box(0.5, 0.35, 0.02, M(0x113355, { emissive: 0x2288cc, emissiveIntensity: 0.8 })); scr.position.set(1.0, 1.55, -2.28); g.add(scr);
    const pipeM = M(0x3b82c4, { metalness: 0.5 });
    for (const dx of [-0.3, 0.3]) { const p = cyl(0.08, 2.4, pipeM, 10); p.rotation.x = Math.PI / 2; p.position.set(dx + 1.0, 0.25, -1.4); g.add(p); }
    it.parts = { melt, light }; it.h = 4.6;
  }
  up_furnace(it: any, st: any) {
    const k = Math.max(0, Math.min(1, ((st.temp ?? 25) - 700) / 800));
    const m = it.parts.melt.material; m.emissiveIntensity = k * 2.2; m.emissive.setHSL(0.02 + 0.1 * k, 1, 0.5);
    it.parts.light.intensity = k * 40;
    it.parts.melt.position.y = 2.2 + 0.72 * (st.fill ?? 0.5);
  }

  mk_treatment(it: any, L: number, W: number) {
    const g = it.group;
    const pf = box(L, 0.6, W, M(0x7b8794)); pf.position.y = 0.3; g.add(pf);
    const hood = box(1.4, 2.6, 1.4, M(0x9aa4ad)); hood.position.set(-L / 2 + 0.8, 1.9, 0); g.add(hood);
    const duct = cyl(0.3, 3.5, M(0x9aa4ad), 12); duct.position.set(-L / 2 + 0.8, 4.9, 0); g.add(duct);
    const hop = this.assets.get('hopper-high-round', 1.1); if (hop) { hop.position.set(L / 2 - 0.8, 0.6, -W / 2 + 0.7); g.add(hop); }
    it.ladles = [];
    for (let i = 0; i < 4; i++) {
      const lg = new THREE.Group(); lg.userData.id = it.s.id;
      const shell = cyl(0.6, 0.9, M(0x3a3f45)); shell.position.y = 0.45; lg.add(shell);
      const top = cyl(0.5, 0.05, M(0x221100, { emissive: 0xff6a10, emissiveIntensity: 0 })); top.position.y = 0.92; lg.add(top);
      const bail = new THREE.Mesh(new THREE.TorusGeometry(0.65, 0.04, 6, 20, Math.PI), M(0x222222)); bail.position.y = 0.9; lg.add(bail);
      lg.userData.top = top; lg.visible = false; this.scene.add(lg); it.ladles.push(lg);
    }
    it.h = 3.6;
  }
  up_treatment(it: any, st: any) {
    const s = it.s, pp = s.cfg.pour_point || [s.pos[0] + 10, s.pos[1]];
    (st.ladles || []).forEach((l: any, i: number) => {
      const lg = it.ladles[i]; if (!lg) return;
      lg.visible = true;
      const home = this.P(s.pos[0] + 0.6 + i * 1.3, s.pos[1] + 0.2, 0.6);
      const dest = this.P(pp[0], pp[1] + 1.2, 1.6);
      const t = l.state === 'AtPour' ? 1 : (l.state === 'ToPour' || l.state === 'Return') ? l.pos : 0;
      const target = home.clone().lerp(dest, t); target.y += Math.sin(Math.PI * t) * 2.2;
      lg.position.lerp(target, 0.25);
      lg.userData.top.material.emissiveIntensity = l.kg > 0 ? 1.8 : 0;
    });
  }

  mk_sand(it: any, L: number, W: number) {
    const g = it.group;
    for (let i = 0; i < 2; i++) { const s = cyl(1.4, 7, M(0xa9b2ba)); s.position.set(-L / 2 + 1.6 + i * 3.2, 3.5, -W / 2 + 1.6); g.add(s);
      const cone = new THREE.Mesh(new THREE.ConeGeometry(1.4, 1.2, 24), M(0xa9b2ba)); cone.position.set(s.position.x, 7.6, s.position.z); g.add(cone);
      const leg = M(0x56616c); for (const [dx, dz] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) { const l2 = box(0.15, 1.2, 0.15, leg); l2.position.set(s.position.x + dx, 0.6, s.position.z + dz); g.add(l2); } }
    const mixer = box(3.2, 2.2, 2.4, M(0x7d6b57)); mixer.position.set(L / 2 - 2, 1.1, 0.5); g.add(mixer);
    const bar = box(0.3, 1, 0.3, M(0x2e9d5b)); bar.position.set(L / 2 - 0.3, 0.5, W / 2 - 0.4); g.add(bar);
    this.conveyor(g, L - 2, 0.9, 0.6, -0.5, W / 2 - 1);
    it.parts = { bar }; it.h = 9;
  }
  up_sand(it: any, st: any) {
    const lv = (st.level ?? 50) / 100; it.parts.bar.scale.y = Math.max(0.05, lv * 3); it.parts.bar.position.y = lv * 1.5;
  }

  mk_molding(it: any, L: number, W: number) {
    const g = it.group;
    it.top = this.conveyor(g, L, W * 0.55, 0.9);
    const press = box(4, 4.2, W + 0.8, M(0x5f7d6b)); press.position.set(L / 2 - 3, 2.1, 0); g.add(press);
    const plate = box(4.05, 0.3, W + 0.85, M(0xf2c230)); plate.position.set(L / 2 - 3, 4.0, 0); g.add(plate);
    const pourer = box(2.2, 3.2, 2.2, M(0x8a5a3c)); pourer.position.set(-L / 2 + 1.5, 1.6, W / 2 + 1.4); g.add(pourer);
    const panel = this.assets.get('screen-panel-wide', 1.3); if (panel) { panel.position.set(L / 2 - 7, 0, W / 2 + 1.2); g.add(panel); }
    it.molds = new THREE.InstancedMesh(new THREE.BoxGeometry(1.1, 0.8, 1.6), M(0x6d6152), 40); it.molds.castShadow = true; g.add(it.molds);
    it.h = 5;
  }
  up_molding(it: any, st: any, t: number) {
    const L = it.s.size[0]; const n = 14; const m4 = new THREE.Matrix4();
    const pitch = (L - 6) / n;
    const shift = (t * 0.25) % pitch;
    for (let i = 0; i < n; i++) { m4.makeTranslation(L / 2 - 5 - i * pitch - shift, it.top + 0.4, 0); it.molds.setMatrixAt(i, m4); }
    it.molds.count = st.state === 'Executing' || st.waiting ? n : 0; it.molds.instanceMatrix.needsUpdate = true;
  }

  mk_cooling(it: any, L: number, W: number) {
    const g = it.group;
    it.top = this.conveyor(g, L, W * 0.7, 0.7);
    const roof = box(L, 0.15, W + 1, M(0x8f99a3, { transparent: true, opacity: 0.35 }), false); roof.position.y = 3.2; g.add(roof);
    const leg = M(0x56616c);
    for (let x = -L / 2; x <= L / 2; x += 4) for (const z of [-(W + 1) / 2, (W + 1) / 2]) { const p = box(0.12, 3.2, 0.12, leg); p.position.set(x, 1.6, z); g.add(p); }
    it.molds = new THREE.InstancedMesh(new THREE.BoxGeometry(0.9, 0.8, 1.4), M(0x5a4c3e), 160); it.molds.castShadow = true; g.add(it.molds);
    it.h = 4;
  }
  up_cooling(it: any, st: any) {
    const L = it.s.size[0]; const m4 = new THREE.Matrix4(); const arr = st.molds || [];
    arr.forEach((p: number, i: number) => { m4.makeTranslation(-L / 2 + 0.5 + p * (L - 1), it.top + 0.4, 0); it.molds.setMatrixAt(i, m4); });
    it.molds.count = Math.min(arr.length, 160); it.molds.instanceMatrix.needsUpdate = true;
  }

  mk_shotblast(it: any, L: number, W: number) {
    const g = it.group;
    const b = box(L, 4.6, W, M(0x56718a)); b.position.y = 2.3; g.add(b);
    const door = box(2.4, 3.2, 0.1, M(0x333a40, { emissive: 0xff9a40, emissiveIntensity: 0 })); door.position.set(0, 1.8, W / 2 + 0.05); g.add(door);
    const dust = cyl(0.6, 6, M(0x9aa4ad)); dust.position.set(L / 2 + 1, 3, -W / 2 + 1); g.add(dust);
    const rail = box(L + 3, 0.2, 0.2, M(0xf2c230)); rail.position.set(-1.5, 5.0, 0); g.add(rail);
    it.parts = { door }; it.h = 6.4;
  }
  up_shotblast(it: any, st: any, t: number) {
    it.parts.door.material.emissiveIntensity = st.busy ? 0.5 + 0.3 * Math.sin(t * 9) : 0;
  }

  mk_receiving(it: any, L: number, W: number) {
    const g = it.group;
    const dock = box(L, 1.1, W, M(0x9aa1a8)); dock.position.y = 0.55; g.add(dock);
    const door = box(L * 0.7, 4, 0.2, M(0xc9ced3)); door.position.set(0, 2.0 + 1.1, -W / 2 + 0.1); g.add(door);
    const im = this.assets.instanced('box-large', 12, 1.2);
    if (im) {
      const m4 = new THREE.Matrix4(); let k = 0;
      for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) for (let l = 0; l < 2; l++) { m4.makeTranslation(-L / 2 + 1.2 + i * 1.6, 1.1 + l * 0.66, -0.6 + j * 1.5); im.set(k++, m4); }
      im.count(k); g.add(im.grp);
    }
    it.h = 4;
  }

  mk_cnc(it: any, L: number, W: number) {
    const g = it.group;
    const body = box(L, 2.6, W, M(0xe6e8ea)); body.position.y = 1.3; g.add(body);
    const win = box(L * 0.55, 1.1, 0.05, M(0x223344, { transparent: true, opacity: 0.55, metalness: 0.4 })); win.position.set(-0.2, 1.6, W / 2 + 0.03); g.add(win);
    const band = box(L, 0.25, W + 0.02, M(0x2f6fa8)); band.position.y = 2.45; g.add(band);
    const head = box(0.5, 0.6, 0.5, M(0x777f88)); head.position.set(0, 1.9, 0.4); g.add(head);
    const part = box(0.7, 0.4, 0.5, M(0x4a4440)); part.position.set(0, 1.0, 0.4); g.add(part);
    const pend = box(0.5, 0.7, 0.12, M(0x3d444b)); pend.position.set(L / 2 + 0.1, 1.5, W / 2 - 0.3); pend.rotation.y = -0.5; g.add(pend);
    const scr = box(0.38, 0.28, 0.02, M(0x113355, { emissive: 0x2288cc, emissiveIntensity: 0.9 })); scr.position.set(L / 2 + 0.14, 1.65, W / 2 - 0.23); scr.rotation.y = -0.5; g.add(scr);
    const chip = box(0.8, 0.6, 0.8, M(0x5b6168)); chip.position.set(-L / 2 - 0.5, 0.3, -W / 2 + 0.5); g.add(chip);
    const light: THREE.Mesh[] = [];
    [0xd23c3c, 0xe0a630, 0x2e9d5b].forEach((c, i) => { const m = cyl(0.12, 0.22, M(c, { emissive: c, emissiveIntensity: 0.1 }), 12); m.position.set(L / 2 - 0.3, 2.85 + i * 0.23, -W / 2 + 0.3); g.add(m); light.push(m); });
    it.parts = { head, part, light }; it.h = 4;
  }
  up_cnc(it: any, st: any, t: number) {
    const on = { RED: 0, YELLOW: 1, GREEN: 2 }[st.light as string] ?? (st.state === 'Stopped' ? 0 : 1);
    it.parts.light.forEach((m: any, i: number) => m.material.emissiveIntensity = i === on ? (i === 0 ? 1.2 + Math.sin(t * 8) : 1.6) : 0.05);
    const run = st.state === 'Executing' && st.part;
    it.parts.part.visible = !!st.part;
    it.parts.head.position.x = run ? Math.sin(t * 1.7) * 0.8 : 0;
    it.parts.head.position.y = run ? 1.75 + Math.sin(t * 3.1) * 0.12 : 1.95;
  }

  mk_deburr(it: any, L: number, W: number) {
    const g = it.group;
    const fence = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(L, 2.2, W)), new THREE.LineBasicMaterial({ color: 0xe0a630 }));
    fence.position.y = 1.1; g.add(fence);
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(L, 2.2), new THREE.MeshBasicMaterial({ color: 0xe0a630, transparent: true, opacity: 0.08, side: THREE.DoubleSide, depthWrite: false }));
    for (const [x, z, r] of [[0, W / 2, 0], [0, -W / 2, 0], [L / 2, 0, Math.PI / 2], [-L / 2, 0, Math.PI / 2]]) { const p = mesh.clone(); p.position.set(x, 1.1, z); p.rotation.y = r; g.add(p); }
    const table = box(1.2, 0.8, 1.0, M(0x6b747d)); table.position.set(1.4, 0.4, 0); g.add(table);
    const arm = this.assets.get('robot-arm-a', 2.3);
    if (arm) {
      arm.position.y = 0.45; g.add(arm);
      const j = (n: string) => arm.getObjectByName(n)!;
      it.parts = { kenney: true, a: j('element-a'), b: j('element-b'), d: j('element-d'), e: j('element-e') };
    } else {
      const base = cyl(0.45, 0.8, M(0xf28c28)); base.position.y = 0.4; g.add(base);
      const j1 = new THREE.Group(); j1.position.y = 0.8; g.add(j1);
      const l1 = box(0.35, 1.6, 0.35, M(0xf28c28)); l1.position.y = 0.8; const j2 = new THREE.Group(); j2.add(l1); j1.add(j2);
      const j3 = new THREE.Group(); j3.position.y = 1.6; j2.add(j3);
      const l2 = box(0.3, 1.3, 0.3, M(0xf28c28)); l2.position.y = 0.65; j3.add(l2);
      it.parts = { j1, j2, j3 };
    }
    it.h = 3.4;
  }
  up_deburr(it: any, st: any) {
    const [a, b, c] = st.j || [0, -30, 60]; const r = Math.PI / 180;
    if (it.parts.kenney) {
      it.parts.a.rotation.y = a * r + Math.PI / 2; it.parts.b.rotation.z = (b + 30) * r * 0.9 - 0.35; it.parts.d.rotation.z = (c - 60) * r * 0.8 - 0.6;
      it.parts.e.rotation.z = -0.4;
    } else {
      it.parts.j1.rotation.y = a * r; it.parts.j2.rotation.z = (b + 30) * r * 0.8; it.parts.j3.rotation.z = (c - 60) * r - 0.9;
    }
  }

  mk_inspection(it: any, L: number, W: number) {
    const g = it.group;
    const b = box(L, 2.0, W, M(0xd9dde3)); b.position.y = 1.0; g.add(b);
    const gantry = box(L, 0.25, 0.3, M(0x52606d)); gantry.position.set(0, 3.0, 0); g.add(gantry);
    const pl = box(0.15, 1.0, 0.15, M(0x52606d)); pl.position.set(-L / 2 + 0.1, 2.5, 0); g.add(pl);
    const pr = pl.clone(); pr.position.x = L / 2 - 0.1; g.add(pr);
    const probe = cyl(0.05, 1.2, M(0x222222), 8); probe.position.set(0, 2.4, 0); g.add(probe);
    const lamp = box(0.9, 0.6, 0.05, M(0x111111, { emissive: 0x2e9d5b, emissiveIntensity: 0.2 })); lamp.position.set(0, 1.5, W / 2 + 0.03); g.add(lamp);
    const sc = this.assets.get('scanner-high', 1.5); if (sc) { sc.position.set(-L / 2 - 0.6, 0, 0); g.add(sc); }
    it.parts = { probe, lamp }; it.h = 3.8;
  }
  up_inspection(it: any, st: any, t: number) {
    it.parts.probe.position.y = st.state === 'Executing' ? 2.4 - Math.abs(Math.sin(t * 2)) * 0.5 : 2.4;
    it.parts.probe.position.x = st.state === 'Executing' ? ((st.hole || 1) % 5 - 2) * 0.5 : 0;
    const m = it.parts.lamp.material; m.emissive.setHex(st.last === 'NG' ? 0xd23c3c : 0x2e9d5b); m.emissiveIntensity = st.last ? 1.2 : 0.1;
  }

  mk_warehouse(it: any, L: number, W: number) {
    const g = it.group;
    const rackM = M(0x2f6fa8, { metalness: 0.5 }), upM = M(0xe07a20, { metalness: 0.4 });
    for (let r = 0; r < 4; r++) {
      const z = -W / 2 + 2 + r * (W - 4) / 3;
      for (let lv = 0; lv < 6; lv++) { const sh = box(L - 1, 0.08, 1.6, rackM, false); sh.position.set(0, 0.5 + lv * 1.3, z); g.add(sh); }
      for (let x = -L / 2 + 0.5; x <= L / 2 - 0.5; x += (L - 1) / 6) for (const dz of [-0.75, 0.75]) { const u = box(0.08, 7.6, 0.08, upM, false); u.position.set(x, 3.8, z + dz); g.add(u); }
    }
    const st = this.assets.instanced('box-small', 600, 1.3);
    it.stock = st;
    if (st) g.add(st.grp);
    else { it.stockIm = new THREE.InstancedMesh(new THREE.BoxGeometry(0.8, 0.7, 1.0), M(0x8c7a5a), 600); g.add(it.stockIm); }
    const crane = box(0.6, 8, 0.8, M(0xf2c94c)); crane.position.set(0, 4, -W / 2 + 2 + (W - 4) / 6); g.add(crane);
    it.parts = { crane }; it.h = 9;
  }
  up_warehouse(it: any, st: any) {
    const L = it.s.size[0], W = it.s.size[1]; const m4 = new THREE.Matrix4(); const n = Math.min(600, Math.ceil((st.stock || 0) / 4));
    for (let i = 0; i < n; i++) {
      const col = i % 12, lv = Math.floor(i / 12) % 6, row = Math.floor(i / 72) % 4;
      m4.makeTranslation(-L / 2 + 1 + col * (L - 2) / 12, 0.56 + lv * 1.3, -W / 2 + 2 + row * (W - 4) / 3);
      if (it.stock) it.stock.set(i, m4); else it.stockIm.setMatrixAt(i, m4);
    }
    if (it.stock) it.stock.count(n); else { it.stockIm.count = n; it.stockIm.instanceMatrix.needsUpdate = true; }
    it.parts.crane.position.x = -L / 2 + 1 + ((st.crane || 0) / 20) * (L - 2);
  }

  mk_agv(it: any) {
    const nodes = it.s.cfg.nodes;
    const names: Record<string, string> = { raw: $t('scene.rawCastingStaging'), cnc_in: $t('scene.machiningLineSideStorage'), fg: $t('scene.finishedGoodsAwaitingStorage'), asrs: $t('scene.automatedWarehouseEntrance'), store: $t('common.rawCastingStore'), charger: $t('scene.chargingStation') };
    for (const [k, p] of Object.entries(nodes) as any) {
      const ng = new THREE.Group(); ng.userData.node = k; ng.position.copy(this.P(p[0], p[1]));
      const pad = box(3.2, 0.06, 3.2, M(k === 'charger' ? 0x3b82c4 : 0x9aa4ad), false); pad.position.y = 0.03; ng.add(pad);
      const lab = this.label(`<div class="node n-${k}">${names[k] || k}</div>`); lab.position.y = 1.2; ng.add(lab);
      this.scene.add(ng);
      const im = this.assets.instanced('box-small', 120, 1.0);
      if (im) this.scene.add(im.grp);
      this.nodes[k] = { g: ng, im };
    }
    it.agvs = new Map<string, THREE.Group>();
  }
  up_agv(it: any, st: any) {
    for (const a of st.agvs || []) {
      let gr = it.agvs.get(a.id);
      if (!gr) {
        gr = new THREE.Group(); gr.userData.id = it.s.id; gr.userData.agv = a.id; this.pickRev++;
        const body = box(1.4, 0.45, 0.95, M(0xf28c28)); body.position.y = 0.3; gr.add(body);
        const lidar = cyl(0.12, 0.15, M(0x222222), 12); lidar.position.set(0.55, 0.6, 0); gr.add(lidar);
        const load = this.assets.get('box-wide', 1.2) || box(1.0, 0.5, 0.75, M(0x6d6152));
        load.position.y = 0.55; load.rotation.y = Math.PI / 2; gr.add(load); gr.userData.load = load;
        const bat = box(0.5, 0.08, 0.2, M(0x2e9d5b, { emissive: 0x2e9d5b, emissiveIntensity: 0.6 })); bat.position.set(0, 0.56, 0.48); gr.add(bat); gr.userData.bat = bat;
        const lab = this.label(`<span class="agv">${a.id}</span>`); lab.position.y = 1.6; gr.add(lab); gr.userData.lab = lab;
        gr.position.copy(this.P(a.x, a.y)); gr.visible = this.layers.agv; this.scene.add(gr); it.agvs.set(a.id, gr);
      }
      const tgt = this.P(a.x, a.y);
      const d = tgt.clone().sub(gr.position);
      if (d.length() > 0.02) gr.rotation.y = Math.atan2(-d.z, d.x);
      gr.position.lerp(tgt, 0.2);
      gr.userData.load.visible = a.load > 0;
      const bm = gr.userData.bat.material; const c = a.soc > 50 ? 0x2e9d5b : a.soc > 25 ? 0xe0a630 : 0xd23c3c; bm.color.setHex(c); bm.emissive.setHex(c);
      gr.userData.lab.element.innerHTML = `<span class="agv ${a.state}">${a.id} · ${a.soc}%</span>`;
    }
  }

  updateBuffers(buf: Record<string, number>) {
    const m4 = new THREE.Matrix4();
    for (const [node, nd] of Object.entries(this.nodes)) {
      const key = node === 'asrs' || node === 'charger' || node === 'store' ? '' : node;
      const im = nd.im; if (!im) continue;
      const n = key ? Math.min(120, Math.ceil((buf[key] || 0) / 3)) : 0; const o = nd.g.position;
      for (let i = 0; i < n; i++) { const c = i % 16, l = Math.floor(i / 16); m4.makeTranslation(o.x - 1.1 + (c % 4) * 0.72, l * 0.56, o.z - 1.1 + Math.floor(c / 4) * 0.72); im.set(i, m4); }
      im.count(n);
    }
  }

  // ---------- Workbench tools: picking, box selection, ground points, camera bookmarks, first-person walkthrough ----------
  ndc(e: { clientX: number; clientY: number }) {
    const r = this.renderer.domElement.getBoundingClientRect();
    return new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  }
  pickId(e: MouseEvent): string {
    this.ray.setFromCamera(this.ndc(e), this.camera);
    for (const h of this.ray.intersectObjects(this.scene.children.filter((o) => o !== this.tcHelper && o !== this.layoutG), true)) {
      let o: any = h.object;
      while (o && !o.userData.id) o = o.parent;
      if (o?.userData.id) return o.userData.id;
    }
    return '';
  }
  groundAt(e: MouseEvent): [number, number] | null {
    this.ray.setFromCamera(this.ndc(e), this.camera);
    const p = new THREE.Vector3();
    if (!this.ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), p)) return null;
    return [+(p.x + this.cx).toFixed(2), +(p.z + this.cy).toFixed(2)];
  }
  /** Equipment within a screen rectangle (clientX/Y). */
  idsInRect(x0: number, y0: number, x1: number, y1: number) {
    const r = this.renderer.domElement.getBoundingClientRect(), out: string[] = [];
    const [a, b, c, d] = [Math.min(x0, x1), Math.max(x0, x1), Math.min(y0, y1), Math.max(y0, y1)];
    for (const [id, it] of this.items) {
      if (['agv', 'crew'].includes(it.s.kind)) continue;
      const v = it.group.position.clone().project(this.camera);
      const sx = r.left + (v.x + 1) / 2 * r.width, sy = r.top + (1 - v.y) / 2 * r.height;
      if (v.z < 1 && sx >= a && sx <= b && sy >= c && sy <= d) out.push(id);
    }
    return out;
  }
  measureG = new THREE.Group();
  showMeasure(a: number[] | null, b: number[] | null) {
    if (!this.measureG.parent) this.scene.add(this.measureG);
    for (const o of [...this.measureG.children]) { this.measureG.remove(o); o.traverse((x: any) => { if (x.isCSS2DObject) x.element.remove(); }); }
    if (!a) return;
    const m = new THREE.MeshBasicMaterial({ color: 0xff5bd1 });
    for (const q of [a, b].filter(Boolean) as number[][]) { const d = new THREE.Mesh(new THREE.SphereGeometry(0.25, 12, 8), m); d.position.copy(this.P(q[0], q[1], 0.25)); this.measureG.add(d); }
    if (b) {
      const g = new THREE.BufferGeometry().setFromPoints([this.P(a[0], a[1], 0.25), this.P(b[0], b[1], 0.25)]);
      this.measureG.add(new THREE.Line(g, new THREE.LineBasicMaterial({ color: 0xff5bd1 })));
      const lab = this.label(`<span class="meas3">${Math.hypot(b[0] - a[0], b[1] - a[1]).toFixed(2)} m</span>`, 'lbl flat');
      lab.position.copy(this.P((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 1.2)); this.measureG.add(lab);
    }
  }
  getCam() { const t = this.controls.target, p = this.camera.position; return { pos: [p.x + this.cx, p.y, p.z + this.cy].map((x) => +x.toFixed(2)), target: [t.x + this.cx, t.y, t.z + this.cy].map((x) => +x.toFixed(2)) }; }
  setCam(c: any) {
    if (!c) return;
    this.setWalk(false);
    this.camera.position.set(c.pos[0] - this.cx, c.pos[1], c.pos[2] - this.cy); this.controls.target.set(c.target[0] - this.cx, c.target[1], c.target[2] - this.cy); this.follow = false;
  }
  /** Current view in world coordinates: pos is the camera position, look is the target; in walk mode, look is 5 m ahead. Used for SOP view recording. */
  viewCam() {
    const p = this.camera.position, w = this.walk;
    const l = w.on ? new THREE.Vector3(p.x - Math.sin(w.yaw) * Math.cos(w.pitch) * 5, p.y + Math.sin(w.pitch) * 5, p.z - Math.cos(w.yaw) * Math.cos(w.pitch) * 5) : this.controls.target;
    const r = (v: number) => +v.toFixed(2);
    return { mode: w.on ? 'walk' : 'orbit', pos: [r(p.x + this.cx), r(p.y), r(p.z + this.cy)], look: [r(l.x + this.cx), r(l.y), r(l.z + this.cy)] };
  }
  /** Move to a view: orbit uses the orbit camera; walk enters first-person mode facing look. */
  goCam(c: { mode?: string; pos: number[]; look: number[] }) {
    if (c.mode === 'walk') {
      this.setWalk(true);
      this.camera.position.set(c.pos[0] - this.cx, 1.7, c.pos[2] - this.cy);
      const dx = c.look[0] - c.pos[0], dy = c.look[1] - 1.7, dz = c.look[2] - c.pos[2], h = Math.hypot(dx, dz) || 1e-6;
      this.walk.yaw = Math.atan2(-dx, -dz); this.walk.pitch = Math.max(-1.2, Math.min(1.2, Math.atan2(dy, h)));
    } else this.setCam({ pos: c.pos, target: c.look });
  }
  walk: any = { on: false, keys: new Set<string>(), yaw: 0, pitch: 0, drag: false, lx: 0, ly: 0 };
  private _wk = (e: KeyboardEvent) => {
    if ((e.target as HTMLElement)?.closest?.('input,textarea')) return;
    const k = e.key.toLowerCase(); if (!['w', 'a', 's', 'd', 'arrowup', 'arrowdown', 'arrowleft', 'arrowright', 'shift'].includes(k)) return;
    if (e.type === 'keydown') this.walk.keys.add(k); else this.walk.keys.delete(k);
  };
  private _wm = (e: PointerEvent) => {
    if (e.type === 'pointerdown') { this.walk.drag = true; this.walk.lx = e.clientX; this.walk.ly = e.clientY; return; }
    if (e.type === 'pointerup') { this.walk.drag = false; return; }
    if (!this.walk.drag) return;
    this.walk.yaw -= (e.clientX - this.walk.lx) * 0.004; this.walk.pitch = Math.max(-1.2, Math.min(1.2, this.walk.pitch - (e.clientY - this.walk.ly) * 0.004));
    this.walk.lx = e.clientX; this.walk.ly = e.clientY;
  };
  /** First-person walkthrough: WASD/arrow keys to move, drag to look, Shift to speed up; eye height 1.7 m. */
  setWalk(on: boolean) {
    if (on === this.walk.on) return;
    this.walk.on = on; this.controls.enabled = !on; this.follow = false;
    const el = this.labels.domElement;
    if (on) {
      const t = this.controls.target;
      this.camera.position.set(t.x, 1.7, t.z + 6); this.walk.yaw = 0; this.walk.pitch = -0.1;
      addEventListener('keydown', this._wk); addEventListener('keyup', this._wk);
      el.addEventListener('pointerdown', this._wm); addEventListener('pointermove', this._wm); addEventListener('pointerup', this._wm);
    } else {
      this.walk.keys.clear();
      removeEventListener('keydown', this._wk); removeEventListener('keyup', this._wk);
      el.removeEventListener('pointerdown', this._wm); removeEventListener('pointermove', this._wm); removeEventListener('pointerup', this._wm);
      this.controls.target.set(this.camera.position.x, 0, this.camera.position.z - 8);
    }
  }
  walkStep(dt: number) {
    const w = this.walk, k = w.keys, sp = (k.has('shift') ? 9 : 3.5) * dt;
    const fx = -Math.sin(w.yaw), fz = -Math.cos(w.yaw), rx = Math.cos(w.yaw), rz = -Math.sin(w.yaw);
    let mx = 0, mz = 0;
    if (k.has('w') || k.has('arrowup')) { mx += fx; mz += fz; } if (k.has('s') || k.has('arrowdown')) { mx -= fx; mz -= fz; }
    if (k.has('d') || k.has('arrowright')) { mx += rx; mz += rz; } if (k.has('a') || k.has('arrowleft')) { mx -= rx; mz -= rz; }
    this.camera.position.x += mx * sp; this.camera.position.z += mz * sp; this.camera.position.y = 1.7;
    const look = new THREE.Vector3(fx * Math.cos(w.pitch), Math.sin(w.pitch), fz * Math.cos(w.pitch));
    this.camera.lookAt(this.camera.position.clone().add(look));
  }

  // ---------- Generic blocks (2.0 Model Editor) ----------
  lampOn(it: any, x: number, y: number, z: number) {
    const m = new THREE.Mesh(new THREE.SphereGeometry(0.2, 16, 12), new THREE.MeshStandardMaterial({ color: 0x888888, emissive: 0x888888, emissiveIntensity: 0.9 }));
    m.position.set(x, y, z); it.group.add(m); it.lamp = m;
  }
  pile(it: any, L: number, W: number, n: number, h0 = 0) {
    const cols = Math.max(1, Math.floor(L / 0.8)), rows = Math.max(1, Math.floor(W / 0.8));
    const mat = M(0xb07a3a); const out: THREE.Mesh[] = [];
    for (let i = 0; i < n; i++) {
      const c = i % cols, r = Math.floor(i / cols) % rows, l = Math.floor(i / (cols * rows));
      const b = box(0.62, 0.45, 0.62, mat); b.position.set(-L / 2 + 0.4 + c * 0.8, h0 + 0.23 + l * 0.48, -W / 2 + 0.4 + r * 0.8); b.visible = false;
      it.group.add(b); out.push(b);
    }
    return out;
  }
  showPile(boxes: THREE.Mesh[], frac: number) { const n = Math.round(boxes.length * Math.max(0, Math.min(1, frac))); boxes.forEach((b, i) => { b.visible = i < n; }); }
  mk_processor(it: any, L: number, W: number) {
    const g = it.group;
    const body = box(L * 0.92, 2.2, W * 0.8, M(0xe9ebee)); body.position.y = 1.1; g.add(body);
    const band = box(L * 0.93, 0.28, W * 0.82, M(0xd99a16)); band.position.y = 2.05; g.add(band);
    const glass = box(L * 0.5, 1.0, 0.05, M(0x1d2a35, { metalness: 0.6, roughness: 0.2 })); glass.position.set(-L * 0.12, 1.25, W * 0.4 + 0.03); g.add(glass);
    const panel = box(0.5, 0.9, 0.3, M(0x3b4650)); panel.position.set(L * 0.36, 1.5, W * 0.4 + 0.15); g.add(panel);
    this.lampOn(it, L * 0.4, 2.55, -W * 0.3); it.h = 3.3;
  }
  mk_batch(it: any, L: number, W: number) {
    const g = it.group;
    const body = box(L * 0.9, 2.8, W * 0.9, M(0x5b6670)); body.position.y = 1.4; g.add(body);
    const door = box(L * 0.55, 1.6, 0.08, M(0x2a2f35, { emissive: 0xff7a1a, emissiveIntensity: 0 })); door.position.set(0, 1.2, W * 0.45 + 0.05); g.add(door);
    const stack = cyl(0.25, 1.4, M(0x7b858f)); stack.position.set(L * 0.3, 3.5, -W * 0.25); g.add(stack);
    it.parts = { door }; this.lampOn(it, -L * 0.38, 3.0, W * 0.38); it.h = 4.4;
  }
  up_batch(it: any, st: any, t: number) { it.parts.door.material.emissiveIntensity = st.state === 'Executing' ? 0.5 + 0.15 * Math.sin(t * 3) : 0; }
  mk_buffer(it: any, L: number, W: number) {
    const g = it.group, y = M(0xf2c94c);
    for (const [x, z, l, w] of [[0, -W / 2, L, 0.12], [0, W / 2, L, 0.12], [-L / 2, 0, 0.12, W], [L / 2, 0, 0.12, W]]) { const b = box(l, 0.03, w, y, false); b.position.set(x, 0.02, z); g.add(b); }
    const n = Math.min(48, Math.max(4, Math.floor((L - 0.4) / 0.8) * Math.floor((W - 0.4) / 0.8) * 3));
    it.parts = { pile: this.pile(it, L - 0.4, W - 0.4, n) }; it.h = 2.2;
  }
  up_buffer(it: any, st: any) { this.showPile(it.parts.pile, st.cap ? st.count / st.cap : 0); }
  mk_conveyor(it: any, L: number, W: number) {
    // 4.6: If conveyor length (length_m) far exceeds its footprint (e.g., a 60 m cooling line in a 35 m space), fold it into multiple passes if width permits
    const lm = +((this as any).blockOf?.(it.s.id)?.params?.length_m) || L;
    const n = Math.max(1, Math.min(Math.floor(W / 0.75), Math.round(lm / Math.max(1, L)))), sw = n > 1 ? Math.min(0.9, (W - 0.15 * (n - 1)) / n) : Math.max(0.6, W * 0.8);
    const zs = Array.from({ length: n }, (_, k) => (n > 1 ? -W / 2 + sw / 2 + k * (W - sw) / (n - 1) : 0));
    let h = 0.8;
    for (const z of zs) h = this.conveyor(it.group, L - (n > 1 ? sw : 0), sw, 0.8, 0, z);
    for (let k = 0; k < n - 1; k++) {           // Turning sections at the ends
      const x = (k % 2 ? -1 : 1) * (L / 2 - sw / 2), t = box(sw, h, zs[k + 1] - zs[k] + sw, M(0x6f6e8c)); t.position.set(x, h / 2, (zs[k] + zs[k + 1]) / 2); it.group.add(t);
    }
    const mat = M(0xb07a3a); it.parts = { h, items: [] as THREE.Mesh[], zs, run: L - (n > 1 ? sw : 0) };
    const cap = Math.min(200, 40 * n);
    for (let i = 0; i < cap; i++) { const b = box(0.5, 0.35, 0.5, mat); b.visible = false; it.group.add(b); it.parts.items.push(b); }
    it.h = 2.2;
  }
  up_conveyor(it: any, st: any) {
    const { zs, run } = it.parts, n = zs.length, xs = st.items || [];
    it.parts.items.forEach((b: THREE.Mesh, i: number) => {
      b.visible = i < xs.length; if (!b.visible) return;
      const f = Math.min(0.9999, Math.max(0, xs[i])) * n, k = Math.floor(f), u = k % 2 ? 1 - (f - k) : f - k;
      b.position.set(-run / 2 + u * run, it.parts.h + 0.2, zs[k]);
    });
  }
  mk_source(it: any, L: number, W: number) {
    const g = it.group;
    const pad = box(L, 0.06, W, M(0x2e9d5b, { transparent: true, opacity: 0.35 }), false); pad.position.y = 0.03; g.add(pad);
    const pallet = box(Math.min(L - 0.4, 2.4), 0.15, Math.min(W - 0.4, 2.4), M(0x9a7b4f)); pallet.position.y = 0.1; g.add(pallet);
    for (const [x, z, l] of [[-0.45, -0.45, 0], [0.45, -0.45, 0], [-0.45, 0.45, 0], [0.45, 0.45, 0], [0, 0, 1]]) { const b = box(0.8, 0.6, 0.8, M(0xb07a3a)); b.position.set(x, 0.48 + l * 0.6, z); g.add(b); }
    it.h = 2.4;
  }
  mk_sink(it: any, L: number, W: number) {
    const g = it.group;
    const pad = box(L, 0.06, W, M(0x2f6fa8, { transparent: true, opacity: 0.3 }), false); pad.position.y = 0.03; g.add(pad);
    it.parts = { pile: this.pile(it, L - 0.4, W - 0.4, 36) }; it.h = 2.4;
  }
  up_sink(it: any, st: any) { this.showPile(it.parts.pile, (st.stock || 0) / 120); }
  mk_storage(it: any, L: number, W: number) {
    const g = it.group, frame = M(0x2f6fa8), shelf = M(0x8a96a3);
    const rows = Math.max(1, Math.floor(W / 3));
    for (let r = 0; r < rows; r++) {
      const z = -W / 2 + 1.5 + r * 3;
      for (let x = -L / 2 + 0.2; x <= L / 2 - 0.2; x += 2.4) { const p = box(0.1, 4.2, 1.2, frame); p.position.set(x, 2.1, z); g.add(p); }
      for (const y of [0.1, 1.4, 2.7, 4.0]) { const s2 = box(L - 0.3, 0.08, 1.2, shelf); s2.position.set(0, y, z); g.add(s2); }
    }
    it.parts = { pile: this.pile(it, L - 0.6, W - 0.6, 40, 1.45) }; it.h = 5;
  }
  up_storage(it: any, st: any) { this.showPile(it.parts.pile, (st.stock || 0) / 300); }
  mk_inspect(it: any, L: number, W: number) {
    const g = it.group;
    const b = box(L * 0.9, 0.9, W * 0.7, M(0xd9dde3)); b.position.y = 0.45; g.add(b);
    const arch = new THREE.Mesh(new THREE.TorusGeometry(Math.min(L, W) * 0.32, 0.12, 8, 24, Math.PI), M(0x7a5af5)); arch.position.y = 0.9; g.add(arch);
    const probe = cyl(0.06, 0.8, M(0x222222), 8); probe.position.set(0, 1.9, 0); g.add(probe);
    it.parts = { probe }; this.lampOn(it, L * 0.38, 1.4, W * 0.3); it.h = 2.8;
  }
  up_inspect(it: any, st: any, t: number) { it.parts.probe.position.y = st.state === 'Executing' ? 1.9 - Math.abs(Math.sin(t * 2)) * 0.4 : 1.9; }
  mk_rework(it: any, L: number, W: number) {
    const g = it.group;
    const top = box(L * 0.8, 0.08, W * 0.5, M(0x8a6b4a)); top.position.y = 0.9; g.add(top);
    for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) { const lg = box(0.08, 0.9, 0.08, M(0x3b4650)); lg.position.set(x * L * 0.37, 0.45, z * W * 0.22); g.add(lg); }
    const tool = box(0.6, 0.4, 0.4, M(0xa14fd6)); tool.position.set(-L * 0.2, 1.15, 0); g.add(tool);
    this.lampOn(it, L * 0.3, 1.3, 0); it.h = 2.4;
  }
  mk_assembly(it: any, L: number, W: number) {
    const g = it.group;
    const table = box(L * 0.7, 0.85, W * 0.6, M(0x6b747d)); table.position.y = 0.42; g.add(table);
    const arm = this.assets.get('robot-arm-a', 1.8); if (arm) { arm.position.set(-L * 0.3, 0.85, 0); g.add(arm); }
    this.lampOn(it, L * 0.35, 1.2, W * 0.25); it.h = 3;
  }
  mk_split(it: any, L: number, W: number) { this.mk_assembly(it, L, W); }
  mk_operators(it: any) {
    const g = it.group;
    const post = cyl(0.06, 2, M(0x3b4650), 8); post.position.y = 1; g.add(post);
    const sign = box(0.9, 0.6, 0.05, M(0xe07a20)); sign.position.y = 2.1; g.add(sign); it.h = 2.8;
  }
  mk_transporter(it: any, L: number, W: number) {
    const pad = box(L + 1, 0.05, W + 1, M(0xf28c28, { transparent: true, opacity: 0.35 }), false); pad.position.y = 0.03; it.group.add(pad);
    it.agvs = new Map<string, THREE.Group>(); it.h = 1.6;
  }
  up_transporter(it: any, st: any) { this.up_agv(it, st); }

  // ---------- 4.3 Control layer / communication layer / information systems: control cabinets, gateway boxes, racks, operator consoles ----------
  cabinet(it: any, w: number, h: number, d: number, col: number) {
    const g = it.group, c = box(w, h, d, M(col)); c.position.y = h / 2; g.add(c);
    const door = box(w * 0.92, h * 0.9, 0.02, M(0xdfe3e7)); door.position.set(0, h / 2, d / 2 + 0.01); g.add(door);
    return c;
  }
  mk_plc(it: any) {
    this.cabinet(it, 1.0, 2.0, 0.5, 0xc9ced4);
    const led = box(0.12, 0.12, 0.03, M(0x222222, { emissive: 0x22cc55, emissiveIntensity: 0 })); led.position.set(0.3, 1.75, 0.27); it.group.add(led);
    const rail = box(0.7, 0.18, 0.03, M(0x3b4650)); rail.position.set(-0.05, 1.45, 0.27); it.group.add(rail);
    it.parts = { led }; it.h = 2.6;
  }
  up_plc(it: any, st: any, t: number) {
    const m = it.parts.led.material, run = st.state !== 'Stopped' && st.state !== 'Halted';
    m.emissive.setHex(st.state === 'Halted' ? 0xffaa00 : 0x22cc55); m.emissiveIntensity = run ? 1 : 0.5 + 0.5 * Math.sin(t * 6);
  }
  mk_hmi(it: any) {
    const g = it.group, post = cyl(0.05, 1.3, M(0x3b4650), 8); post.position.y = 0.65; g.add(post);
    const scr = box(0.5, 0.36, 0.06, M(0x113355, { emissive: 0x2288cc, emissiveIntensity: 0.8 })); scr.position.y = 1.45; scr.rotation.x = -0.3; g.add(scr); it.h = 2.1;
  }
  mk_gateway(it: any) {
    const g = it.group, post = cyl(0.05, 1.2, M(0x3b4650), 8); post.position.y = 0.6; g.add(post);
    const bx = box(0.5, 0.32, 0.22, M(0x7a5af5)); bx.position.y = 1.36; g.add(bx);
    const ant = cyl(0.02, 0.35, M(0x222222), 6); ant.position.set(0.18, 1.7, 0); g.add(ant); it.h = 2.2;
  }
  mk_switch(it: any) {
    const g = it.group, rack = box(0.6, 1.8, 0.6, M(0x2a2f36)); rack.position.y = 0.9; g.add(rack);
    for (let i = 0; i < 3; i++) { const u = box(0.5, 0.08, 0.02, M(0x7a5af5, { emissive: 0x7a5af5, emissiveIntensity: 0.4 })); u.position.set(0, 1.2 + i * 0.15, 0.31); g.add(u); }
    it.h = 2.4;
  }
  mk_scada(it: any) {
    const g = it.group, desk = box(1.2, 0.75, 0.7, M(0x8a96a3)); desk.position.y = 0.375; g.add(desk);
    for (const x of [-0.3, 0.3]) { const sc = box(0.5, 0.32, 0.04, M(0x113355, { emissive: 0x2e9d5b, emissiveIntensity: 0.6 })); sc.position.set(x, 1.0, -0.15); g.add(sc); }
    it.h = 2;
  }
  mk_mes(it: any) {
    const g = it.group;
    for (const x of [-0.32, 0.32]) { const r = box(0.6, 2.0, 0.8, M(0x2a2f36)); r.position.set(x, 1, 0); g.add(r); const l = box(0.5, 0.05, 0.02, M(0x2e9d5b, { emissive: 0x2e9d5b, emissiveIntensity: 0.6 })); l.position.set(x, 1.6, 0.41); g.add(l); }
    it.h = 2.6;
  }

  // ---------- Floor plan layout: walls, areas, aisles, AGV route network (plant.layout) ----------
  layoutG = new THREE.Group();
  setLayout(L: any, floors: any[] = []) {
    if (!this.layoutG.parent) this.scene.add(this.layoutG);
    for (const o of [...this.layoutG.children]) { this.layoutG.remove(o); o.traverse((x: any) => { if (x.isCSS2DObject) x.element.remove(); }); }
    if (!L) return;
    const fz = (id?: string) => (floors.find((f: any) => f.id === id)?.z || 0);
    const wallM = M(0xc9ced3, { roughness: 0.9 });
    // Hide the generated building shell when the floor plan defines exterior walls (outer) to avoid duplicate walls
    this.shellG.visible = !(L.walls || []).some((w: any) => w.outer);
    for (const w of L.walls || []) {
      const t = w.t ?? 0.24, h = w.h ?? 4, z0 = fz(w.floor);
      for (const pts of wallPieces(w)) {   // Leave gaps for door openings defined in the floor plan
        for (let i = 0; i < pts.length - 1; i++) {
          const [a, b] = [pts[i], pts[i + 1]], len = Math.hypot(b[0] - a[0], b[1] - a[1]); if (len < 0.01) continue;
          const m = box(len + t, h, t, wallM); m.position.copy(this.P((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, z0 + h / 2));
          m.rotation.y = -Math.atan2(b[1] - a[1], b[0] - a[0]); this.layoutG.add(m);
        }
      }
    }
    for (const z of L.zones || []) {
      if ((z.pts || []).length < 3) continue;
      const shape = new THREE.Shape(z.pts.map((q: number[]) => new THREE.Vector2(q[0] - this.cx, -(q[1] - this.cy))));
      const m = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color: new THREE.Color(z.color || '#1463d6'), transparent: true, opacity: 0.18, depthWrite: false }));
      m.rotation.x = -Math.PI / 2; m.position.y = 0.025 + fz(z.floor); m.renderOrder = 2; this.layoutG.add(m);
      const c = z.pts.reduce((t: number[], q: number[]) => [t[0] + q[0] / z.pts.length, t[1] + q[1] / z.pts.length], [0, 0]);
      const lab = this.label(`<div class="area">${z.name || ''}</div>`, 'lbl flat'); lab.position.copy(this.P(c[0], c[1], 0.2 + fz(z.floor))); this.layoutG.add(lab);
    }
    const aisleM = new THREE.MeshBasicMaterial({ color: 0xf2c94c, transparent: true, opacity: 0.22, depthWrite: false });
    const lineM = new THREE.MeshBasicMaterial({ color: 0xf2c94c });
    for (const a of L.aisles || []) {
      const w = a.w ?? 3, z0 = fz(a.floor);
      for (let i = 0; i < a.pts.length - 1; i++) {
        const [p, q] = [a.pts[i], a.pts[i + 1]], len = Math.hypot(q[0] - p[0], q[1] - p[1]); if (len < 0.01) continue;
        const ang = -Math.atan2(q[1] - p[1], q[0] - p[0]), mid = this.P((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, z0 + 0.02);
        const m = new THREE.Mesh(new THREE.PlaneGeometry(len, w), aisleM); m.rotation.set(-Math.PI / 2, 0, ang); m.position.copy(mid); m.renderOrder = 3; this.layoutG.add(m);
        for (const side of [-1, 1]) {
          const e = new THREE.Mesh(new THREE.PlaneGeometry(len, 0.12), lineM); e.rotation.set(-Math.PI / 2, 0, ang);
          const nx = -(q[1] - p[1]) / len, ny = (q[0] - p[0]) / len;   // Normal to the aisle direction in plan coordinates
          e.position.copy(mid).add(new THREE.Vector3(nx * side * w / 2, 0.005, ny * side * w / 2)); this.layoutG.add(e);
        }
      }
    }
    const net = L.paths || {}; const nodes: Record<string, any> = Object.fromEntries((net.nodes || []).map((n: any) => [n.id, n]));
    const pathM = new THREE.MeshBasicMaterial({ color: 0xf28c28 });
    for (const e of net.edges || []) {
      const a = nodes[e.a], b = nodes[e.b]; if (!a || !b) continue;
      const len = Math.hypot(b.x - a.x, b.y - a.y), ang = -Math.atan2(b.y - a.y, b.x - a.x);
      const m = new THREE.Mesh(new THREE.PlaneGeometry(len, 0.14), pathM); m.rotation.set(-Math.PI / 2, 0, ang);
      m.position.copy(this.P((a.x + b.x) / 2, (a.y + b.y) / 2, 0.04)); this.layoutG.add(m);
      if (e.oneway) {
        const tri = new THREE.Mesh(new THREE.ConeGeometry(0.35, 0.8, 3), pathM); tri.rotation.set(0, 0, -Math.PI / 2); const g = new THREE.Group(); g.add(tri);
        g.position.copy(this.P(a.x + (b.x - a.x) * 0.6, a.y + (b.y - a.y) * 0.6, 0.12)); g.rotation.y = ang; this.layoutG.add(g);
      }
    }
    for (const n of net.nodes || []) {
      const col = n.kind === 'charger' ? 0x3b82c4 : n.kind === 'station' ? 0x2e9d5b : 0xf28c28;
      const d = new THREE.Mesh(new THREE.CylinderGeometry(n.kind === 'node' ? 0.28 : 0.7, n.kind === 'node' ? 0.28 : 0.7, 0.05, 20), new THREE.MeshBasicMaterial({ color: col }));
      d.position.copy(this.P(n.x, n.y, 0.05)); this.layoutG.add(d);
    }
    this.layoutG.visible = this.layers.layout !== false;
  }

  // ---------- Personnel ----------
  mkWorker(w: any) {
    const idx = [...w.id].reduce((a: number, c: string) => a + c.charCodeAt(0), 0) % PEOPLE.length;
    const gl = this.assets.lib.get(PEOPLE[idx]); if (!gl) return null;
    const root = SkeletonUtils.clone(gl.scene) as THREE.Object3D;
    const g = new THREE.Group(); g.userData.id = 'CREW'; g.userData.worker = w.id; g.add(root);
    const bb = new THREE.Box3().setFromObject(root); const s = 1.75 / Math.max(0.1, bb.max.y - bb.min.y); root.scale.setScalar(s);
    g.updateMatrixWorld(true);
    // Hard hat: attached to the head bone to follow animation
    const head = root.getObjectByName('head'), hm = root.getObjectByName('head-mesh');
    if (head && hm) {
      const hb = new THREE.Box3().setFromObject(hm); const hr = (hb.max.x - hb.min.x) / 2 * 0.86;
      const ws = new THREE.Vector3(); head.getWorldScale(ws);
      const hat = new THREE.Mesh(new THREE.SphereGeometry(hr / ws.x, 18, 10, 0, Math.PI * 2, 0, Math.PI / 2), M((w.lead === true || variants('scene.shiftLead').some((t) => String(w.role).includes(t))) ? 0xd23c3c : 0xf2c230, { roughness: 0.4 }));
      const brim = new THREE.Mesh(new THREE.CylinderGeometry(hr / ws.x * 1.15, hr / ws.x * 1.15, 0.02 / ws.x, 18), hat.material); hat.add(brim);
      hat.castShadow = true;
      const c = new THREE.Vector3((hb.min.x + hb.max.x) / 2, hb.max.y - hr * 0.62, (hb.min.z + hb.max.z) / 2);
      head.worldToLocal(c); hat.position.copy(c); head.add(hat);
    }
    const carry = this.assets.get('box-small', 0.9) || box(0.5, 0.4, 0.4, M(0x6d6152)); carry.position.set(0, 0.75, 0.38); carry.visible = false; g.add(carry);
    const lab = this.label(`<span class="wk">${w.role}</span>`); lab.position.y = 2.15; g.add(lab);
    const mixer = new THREE.AnimationMixer(root); const acts: Record<string, THREE.AnimationAction> = {};
    for (const c of gl.animations) acts[c.name] = mixer.clipAction(c);
    const o: any = { g, mixer, acts, cur: '', carry, lab };
    o.play = (n: string) => {
      if (o.cur === n || !acts[n]) return;
      const nx = acts[n]; nx.reset().fadeIn(0.25).play(); if (o.cur && acts[o.cur]) acts[o.cur].fadeOut(0.25); o.cur = n;
    };
    o.play('idle');
    g.position.copy(this.P(w.x, w.y)); this.scene.add(g); this.workers.set(w.id, o); this.pickRev++;
    return o;
  }
  up_crew(_it: any, st: any, _t: number, dt: number) {
    const seen = new Set<string>();
    for (const w of st.workers || []) {
      seen.add(w.id);
      const o = this.workers.get(w.id) || this.mkWorker(w); if (!o) continue;
      const tgt = this.P(w.x, w.y); const d = tgt.clone().sub(o.g.position); d.y = 0; const dist = d.length();
      if (dist > 10) o.g.position.copy(tgt); else o.g.position.lerp(tgt, Math.min(1, dt * 5));
      if (dist > 0.04) { const want = Math.atan2(d.x, d.z); o.g.rotation.y += Math.atan2(Math.sin(want - o.g.rotation.y), Math.cos(want - o.g.rotation.y)) * Math.min(1, dt * 8); }
      else if (w.state === 'work' && w.serving) {
        const it = this.items.get(w.serving);
        if (it) { const v = it.group.position.clone().sub(o.g.position); o.g.rotation.y = Math.atan2(v.x, v.z); }
      }
      const moving = (w.state === 'walk' || w.state === 'carry') && dist > 0.03;
      o.play(w.state === 'work' ? 'interact-right' : moving ? (w.state === 'carry' ? 'holding-both' : 'walk') : 'idle');
      if (o.acts.walk) o.acts.walk.timeScale = 1.4;
      o.carry.visible = w.state === 'carry';
      o.lab.element.classList.toggle('busy', w.state === 'work');
    }
    for (const [id, o] of this.workers) { const v = seen.has(id) && this.layers.people; o.g.visible = v; (o.lab.element as HTMLElement).style.display = v ? '' : 'none'; }
  }
  focusWorker(id: string) {
    const o = this.workers.get(id); if (!o) return;
    this.controls.target.copy(o.g.position);
    this.camera.position.copy(o.g.position.clone().add(new THREE.Vector3(-5, 9, 11)));
  }

  setState(s: any) { this.state = s; }

  frame() {
    const dt = Math.min(0.1, this.clock.getDelta()), t = this.clock.elapsedTime;
    if (this.state) {
      for (const st of this.state.stations) {
        const it = this.items.get(st.id); if (!it) continue;
        const up = (this as any)['up_' + st.kind]; if (up) up.call(this, it, st, t, dt);
        if (it.lamp) { const c = STATE_COLOR[st.state] ?? 0x888888; it.lamp.material.color.setHex(c); it.lamp.material.emissive.setHex(c); }
        if (it.label) {
          const el = it.label.element as HTMLElement;
          const c = '#' + (STATE_COLOR[st.state] ?? 0x888888).toString(16).padStart(6, '0');
          (el.querySelector('.dot') as HTMLElement).style.background = c;
          (el.querySelector('small') as HTMLElement).textContent = st.alarm ? ` ⚠ ${st.alarm}`
            : this.layers.kpi && st.oee ? ` OEE ${Math.round(st.oee.OEE * 100)}%${st.count !== undefined ? $t('scene.n0Pcs', [st.count]) : ''}` : ` ${st.phase || STATE_CN[st.state] || st.state}`;
          el.classList.toggle('alarm', !!st.alarm); el.classList.toggle('sel', st.id === this.selected);
          const mk = this.marks[st.id];
          el.classList.toggle('bp', mk?.bp === 'on'); el.classList.toggle('bpoff', mk?.bp === 'off');
          let wv = el.querySelector('em.wv') as HTMLElement | null;
          if (mk?.w) { if (!wv) { wv = document.createElement('em'); wv.className = 'wv'; el.appendChild(wv); } if (wv.textContent !== mk.w) wv.textContent = mk.w; } else if (wv) wv.remove();
        }
      }
      if (t - this.lastDeclutter > 0.25) { this.lastDeclutter = t; this.declutter(); }
      this.updateBuffers(this.state.kpi.buffers || {});
      this.upCrane(dt);
    }
    for (const o of this.workers.values()) o.mixer.update(dt);
    this.flowTex.offset.x -= dt * 0.9;
    if (this.marker.visible && this.trackPos) {
      const before = this.marker.position.clone();
      this.marker.position.lerp(this.trackPos, Math.min(1, dt * 3));
      const { ring, gem } = this.marker.userData; const k = 1 + 0.15 * Math.sin(t * 4); ring.scale.set(k, k, k); gem.rotation.y = t * 2; gem.position.y = 6.5 + Math.sin(t * 3) * 0.25;
      if (this.follow) { const dv = this.marker.position.clone().sub(before); this.camera.position.add(dv); this.controls.target.add(dv); }
    }
    if (this.walk.on) this.walkStep(dt); else this.controls.update();
    for (const f of this.beforeRender) f(dt, t);
    this.renderer.render(this.scene, this.camera);
    for (const f of this.afterRender) f(dt, t);
    this.labels.render(this.scene, this.camera);
  }

  // ---------- Picking / editing ----------
  pick(e: MouseEvent) {
    if (this.justDragged) { this.justDragged = false; return; }
    if (this.editMode && (this.tc as any).axis) return;
    const r = this.renderer.domElement.getBoundingClientRect();
    this.mouse.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    this.ray.setFromCamera(this.mouse, this.camera);
    const hits = this.ray.intersectObjects(this.scene.children.filter((o) => o !== this.tcHelper), true);
    for (const h of hits) {
      let o: any = h.object;
      while (o && !o.userData.id && !o.userData.node) o = o.parent;
      if (!o) continue;
      if (this.editMode) {
        if (o.userData.node) { this.tc.attach(o); this.onEditPick('AGV'); return; }
        const it = this.items.get(o.userData.id);
        if (it && !['agv', 'crew'].includes(it.s.kind)) this.tc.attach(it.group); else this.tc.detach();
        this.onEditPick(o.userData.id); return;
      }
      if (o.userData.id) { this.onPick(o.userData.id); return; }
    }
    if (this.editMode) { this.tc.detach(); this.onEditPick(''); }
  }

  setEdit(on: boolean) {
    this.editMode = on; if (!on) this.tc.detach();
    this.el.classList.toggle('editing', on);
  }
  rotateSelected(deg: number) {
    const o: any = this.tc.object; if (!o || !o.userData.id) return;
    o.rotation.y -= deg * Math.PI / 180;
    const pos: [number, number] = [+(o.position.x + this.cx).toFixed(2), +(o.position.z + this.cy).toFixed(2)];
    this.onMoved(o.userData.id, pos, ((Math.round(-o.rotation.y * 180 / Math.PI) % 360) + 360) % 360);
  }
  groundPoint(): [number, number] {
    const t = this.controls.target; return [+(t.x + this.cx).toFixed(1), +(t.z + this.cy).toFixed(1)];
  }

  // ---------- Cockpit tools ----------
  viewPreset(name: string, area?: any) {
    const s = this.span;
    const tgt = new THREE.Vector3(), pos = new THREE.Vector3();
    if (name === 'top') { tgt.set(0, 0, 0); pos.set(0, s * 0.95, 0.01); }
    else if (name === 'front') { tgt.set(0, 0, 0); pos.set(0, s * 0.22, s * 0.62); }
    else if (name === 'area' && area) { const x = (area.x[0] + area.x[1]) / 2 - this.cx, w = area.x[1] - area.x[0]; tgt.set(x, 0, 0); pos.set(x - w * 0.15, Math.max(30, w * 1.1), Math.max(34, w * 1.15)); }
    else {   // Overview: compute distance from the plant bounding box and viewport aspect ratio to fit the entire plant
      const b = this.bounds || { x0: -s / 2, x1: s / 2, y0: -s / 4, y1: s / 4 };
      const W = b.x1 - b.x0, D = b.y1 - b.y0, v = THREE.MathUtils.degToRad(this.camera.fov) / 2;
      const hf = Math.atan(Math.tan(v) * (this.camera.aspect || 1.6)), el = THREE.MathUtils.degToRad(50);
      const dist = Math.max((W / 2) * 1.06 / Math.tan(hf), ((D * Math.sin(el)) / 2 + 5) * 1.12 / Math.tan(v), 25);
      tgt.set(0, 0, 0); pos.set(0, dist * Math.sin(el), dist * Math.cos(el));
      this.controls.maxDistance = Math.max(280, dist * 1.6);
    }
    this.controls.target.copy(tgt); this.camera.position.copy(pos); this.follow = false;
    this.autoView = name === 'overview';
  }
  focusClose(id: string) {
    const it = this.items.get(id); if (!it) return;
    const p = it.group.position.clone();
    this.controls.target.copy(p); this.camera.position.copy(p.clone().add(new THREE.Vector3(-8, 14, 18))); this.follow = false;
  }
  setLayer(name: string, on: boolean) {
    this.layers[name] = on;
    if (name === 'flow') this.setFlow(on);
    if (name === 'labels') this.el.classList.toggle('hide-labels', !on);
    if (name === 'people') for (const o of this.workers.values()) { o.hidden = !on; o.g.visible = on && o.g.visible; (o.lab.element as HTMLElement).style.display = on ? '' : 'none'; }
    if (name === 'agv') { for (const it of this.items.values()) if (it.agvs) for (const g of it.agvs.values()) g.visible = on; for (const n of Object.values(this.nodes)) n.g.visible = on; }
    if (name === 'heat') this.heat.visible = on;
    if (name === 'layout') this.layoutG.visible = on;
    if (name === 'transfer') (this as any).transfer?.setVisible(on);      // Material transfer (automatic): scene_ext/transfer.ts
  }
  /** Heatmap: translucent overlay on each machine footprint; values 0~1 (green→yellow→red), null shown in gray. */
  /** ranks: top bottlenecks (equipment ID → label text); enclose each machine in a translucent red box with a floating label. */
  setHeat(values: Record<string, number | null>, ranks: Record<string, string> = {}) {
    for (const o of [...this.heat.children]) o.traverse((x: any) => { if (x.isCSS2DObject) x.element.remove(); });
    this.heat.clear();
    for (const [id, it] of this.items) {
      if (['agv', 'crew'].includes(it.s.kind) || !(id in values)) continue;
      const v = values[id];
      const col = v === null ? new THREE.Color(0x9aa4ad) : new THREE.Color().setHSL(0.33 * (1 - Math.max(0, Math.min(1, v))), 0.85, 0.5);
      const [L, W] = it.s.size;
      const m = new THREE.Mesh(new THREE.PlaneGeometry(L + 1.6, W + 1.6), new THREE.MeshBasicMaterial({ color: col, transparent: true, opacity: 0.55, depthWrite: false }));
      m.rotation.x = -Math.PI / 2; m.position.copy(it.group.position).setY(0.12); m.rotation.z = it.group.rotation.y; m.renderOrder = 5;
      this.heat.add(m);
      if (ranks[id]) {
        const h = it.h || 3.5, top = ranks[id].includes('#1');
        const bx = new THREE.Mesh(new THREE.BoxGeometry(L + 0.8, h + 0.6, W + 0.8), new THREE.MeshBasicMaterial({ color: top ? 0xe0393e : 0xe08a20, transparent: true, opacity: 0.16, depthWrite: false }));
        bx.position.copy(it.group.position).setY((h + 0.6) / 2); bx.rotation.y = it.group.rotation.y; bx.renderOrder = 6; this.heat.add(bx);
        const lab = this.label(`<span class="bnk${top ? ' top' : ''}">${ranks[id]}</span>`, 'lbl flat'); lab.position.copy(it.group.position).setY(h + 2.2); this.heat.add(lab);
      }
    }
    this.heat.visible = this.layers.heat;
  }
  snapshot(): string {
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL('image/png');
  }
  dispose() {
    this.renderer.setAnimationLoop(null);
    for (const f of this.disposers) try { f(); } catch { /* */ }
    this.renderer.dispose();
    this.el.innerHTML = '';
  }

  /** Zoom in on an object (AGV, person, gateway, etc.). */
  focusObject(o: THREE.Object3D) {
    const p = o.getWorldPosition(new THREE.Vector3());
    this.controls.target.copy(p); this.camera.position.copy(p).add(new THREE.Vector3(-5, 8, 10)); this.follow = false; this.autoView = false;
  }
  /** Equipment screen position (clientX/Y, at mid-height); returns null if off-screen. Used for UI tests. */
  screenOf(id: string, hFrac = 0.4): { x: number; y: number } | null {
    const it = this.items.get(id); if (!it) return null;
    const g = it.agvs?.size ? [...it.agvs.values()][0] : it.group;
    const v = g.position.clone(); v.y += (it.agvs?.size ? 0.4 : (it.h || 3) * hFrac);
    v.project(this.camera); if (v.z > 1 || Math.abs(v.x) > 1 || Math.abs(v.y) > 1) return null;
    const r = this.renderer.domElement.getBoundingClientRect();
    return { x: r.left + (v.x + 1) / 2 * r.width, y: r.top + (1 - v.y) / 2 * r.height };
  }

  focus(id: string) {
    const it = this.items.get(id); if (!it || it.s.kind === 'agv' || it.s.kind === 'crew') return;
    const p = it.group.position;
    this.controls.target.lerp(p.clone(), 0.6);
  }
}
