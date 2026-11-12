// 3D hover and selection feedback (4.4, like buildings in RTS games):
//   - Outline equipment / AGVs / personnel under the pointer (dark teal on hover, thicker cobalt blue when selected, thin light cyan for related objects); add a ground selection box for selected equipment;
//   - Picking: pointermove only records coordinates; raycast at most once per frame against the cached selectable objects;
//   - Outlines: temporarily attach outlined objects to a mask scene, render "related / hovered / selected" into three mask channels, then detect edges in one fullscreen fragment pass,
//     scoping mask rendering and compositing to the objects' screen bounds (scissor); no extra rendering when nothing is selected or hovered.
// register(scene) attaches scene.hover (HoverFx) to FactoryScene; Workbench View3D sets callbacks and supplies selected/related sets.
import { $t } from '../i18n';
import * as THREE from 'three';

export type HoverHit = { id: string; obj: THREE.Object3D; agv?: string; worker?: string };
type Kind = 'sel' | 'hov' | 'rel';

// 5.0.1 light theme: selected = cobalt blue (matching 2D selection), hovered / related = dark teal; visible on light floors and gray equipment
const COLOR = { sel: new THREE.Color(0x1463d6), hov: new THREE.Color(0x087f9e), rel: new THREE.Color(0x087f9e) };

const VERT = 'varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }';
// Mask r = selected, g = hovered, b = related. Outer outline: outside the mask but near masked pixels; thin interior fill.
const FRAG = `
uniform sampler2D mask; uniform vec2 texel; uniform float px;
uniform vec3 cSel; uniform vec3 cHov; uniform vec3 cRel;
varying vec2 vUv;
void main() {
  vec4 m = texture2D(mask, vUv);
  vec3 n1 = vec3(0.0), n2 = vec3(0.0), n3 = vec3(0.0);
  for (int i = 0; i < 8; i++) {
    float a = float(i) * 0.785398 + 0.2;
    vec2 d = vec2(cos(a), sin(a)) * texel * px;
    n1 = max(n1, texture2D(mask, vUv + d * 1.5).rgb);
    n2 = max(n2, texture2D(mask, vUv + d * 3.0).rgb);
    n3 = max(n3, texture2D(mask, vUv + d * 4.5).rgb);
  }
  ${$t('hover.lineWidthSelected45')}
  float aS = max(max(n1.r, n2.r), n3.r * 0.85) * (1.0 - m.r);
  float aH = max(n1.g, n2.g * 0.9) * (1.0 - m.g);
  float aR = n1.b * (1.0 - m.b) * 0.6;
  vec3 col = cRel; float al = aR;
  col = mix(col, cHov, aH); al = max(al, aH);
  col = mix(col, cSel, aS); al = max(al, aS);
  if (al < 0.02) {                      ${$t('hover.objectFillSubtleOnHover')}
    float fh = m.g * 0.16, fs = m.r * 0.08;
    if (fh >= fs) { col = cHov; al = fh; } else { col = cSel; al = fs; }
  }
  if (al < 0.01) discard;
  gl_FragColor = vec4(col, al);
}`;

/** Rounded ground selection box: expand the L×W footprint by pad, with line width w. */
function ringGeo(L: number, W: number, pad: number, w: number, round = false) {
  const rr = (s: THREE.Shape | THREE.Path, hx: number, hy: number, r: number) => {
    s.moveTo(-hx + r, -hy); s.lineTo(hx - r, -hy); s.quadraticCurveTo(hx, -hy, hx, -hy + r); s.lineTo(hx, hy - r); s.quadraticCurveTo(hx, hy, hx - r, hy);
    s.lineTo(-hx + r, hy); s.quadraticCurveTo(-hx, hy, -hx, hy - r); s.lineTo(-hx, -hy + r); s.quadraticCurveTo(-hx, -hy, -hx + r, -hy);
  };
  const hx = L / 2 + pad, hy = W / 2 + pad, r = round ? Math.min(hx, hy) * 0.999 : Math.min(0.9, Math.min(hx, hy) * 0.35);
  const s = new THREE.Shape(); rr(s, hx + w, hy + w, r + w);
  const h = new THREE.Path(); rr(h, hx, hy, r); s.holes.push(h);
  const g = new THREE.ShapeGeometry(s, 4); g.rotateX(-Math.PI / 2); return g;
}

export class HoverFx {
  s: any; el: HTMLElement;
  /** on = normal; pick = click selection (outline, no cursor change); off = no picking (measuring, placement, roaming). */
  mode: 'on' | 'pick' | 'off' = 'on';
  hit: HoverHit | null = null; busy = false; panelHot = false;
  onHover: (h: HoverHit | null) => void = () => {};
  onBusy: (b: boolean) => void = () => {};
  sets: Record<Kind, THREE.Object3D[]> = { sel: [], hov: [], rel: [] };
  ids: Record<Kind, string[]> = { sel: [], hov: [], rel: [] };
  perf = { picks: 0, pickMs: 0, fxFrames: 0, fxMs: 0 };
  private px = 0; private py = 0; private inside = false; private dirty = false; private down = false; private quiet = 0; private lastPick = 0; private camAt = 0;
  private ray = new THREE.Raycaster(); private ndc = new THREE.Vector2(); private hits: THREE.Intersection[] = [];
  private list: THREE.Object3D[] = []; private listRev = -1;
  private rt = new THREE.WebGLRenderTarget(4, 4, { depthBuffer: false, type: THREE.UnsignedByteType });
  private maskScene = new THREE.Scene(); private maskMat = new THREE.MeshBasicMaterial({ color: 0xffffff, depthTest: false, depthWrite: false, blending: THREE.AdditiveBlending, side: THREE.DoubleSide, fog: false, transparent: false });
  private fsScene = new THREE.Scene(); private fsCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1); private fsMat: THREE.ShaderMaterial;
  private size = new THREE.Vector2(); private v = new THREE.Vector3(); private cc = new THREE.Color();
  private boxes = new Map<THREE.Object3D, THREE.Box3>(); private boxTick = 0; private all: THREE.Object3D[] = [];
  private rings = new THREE.Group(); private ringMat = new THREE.MeshBasicMaterial({ color: COLOR.sel, transparent: true, opacity: 0.9, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, fog: false });
  private hovRing: THREE.Mesh | null = null; private hovRingMat = new THREE.MeshBasicMaterial({ color: COLOR.hov, transparent: true, opacity: 0.55, depthWrite: false, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, fog: false });
  private ringOf = new Map<THREE.Mesh, THREE.Object3D>();

  constructor(s: any) {
    this.s = s; this.el = s.labels.domElement;
    this.maskScene.matrixWorldAutoUpdate = false;
    this.maskScene.overrideMaterial = this.maskMat;
    this.fsMat = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG, transparent: true, depthTest: false, depthWrite: false,
      uniforms: { mask: { value: this.rt.texture }, texel: { value: new THREE.Vector2(1, 1) }, px: { value: 1 }, cSel: { value: COLOR.sel }, cHov: { value: COLOR.hov }, cRel: { value: COLOR.rel } },
    });
    const q = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.fsMat); q.frustumCulled = false; this.fsScene.add(q);
    this.rings.renderOrder = 7; s.scene.add(this.rings);
    const el = this.el;
    el.addEventListener('pointermove', this.onMove);
    el.addEventListener('pointerleave', this.onLeave);
    el.addEventListener('pointerdown', this.onDown);
    addEventListener('pointerup', this.onUp);
    el.addEventListener('wheel', this.onWheel, { passive: true });
    s.controls.addEventListener('change', this.onCam);
    s.beforeRender.push(this.pre);
    s.afterRender.push(this.post);
    s.disposers.push(() => this.dispose());
  }

  // ---------- Input ----------
  private onMove = (e: PointerEvent) => { this.px = e.clientX; this.py = e.clientY; this.inside = true; this.dirty = true; };
  private onLeave = () => { this.inside = false; this.dirty = true; };
  private onDown = () => { this.down = true; this.setBusy(true); };
  private onUp = () => { if (!this.down) return; this.down = false; this.dirty = true; this.setBusy(false); };
  private onWheel = () => { this.quiet = performance.now() + 220; this.dirty = true; this.setBusy(true); };
  private onCam = () => { this.camAt = performance.now(); };
  private setBusy(b: boolean) { if (b !== this.busy) { this.busy = b; this.onBusy(b); } }

  /** Selectable scene objects: equipment groups, individual AGVs and people; rebuild when equipment changes (scene.pickRev changes). */
  private refreshList() {
    const s = this.s; if (s.pickRev === this.listRev) return;
    this.listRev = s.pickRev; this.list.length = 0;
    for (const it of s.items.values()) {
      if (it.agvs) for (const g of it.agvs.values()) this.list.push(g);
      if (it.s.kind !== 'crew' && it.s.kind !== 'agv' && it.group) this.list.push(it.group);
    }
    for (const w of s.workers.values()) this.list.push(w.g);
  }

  /** Object at screen coordinates (same as click selection: skip hidden objects, floors and walls). */
  hitAt(cx: number, cy: number): HoverHit | null {
    const s = this.s, r = this.el.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    this.ndc.set(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1);
    this.refreshList();
    this.ray.setFromCamera(this.ndc, s.camera);
    this.hits.length = 0;
    for (const g of this.list) if (g.visible && g.parent) this.ray.intersectObject(g, true, this.hits);
    this.hits.sort((a, b) => a.distance - b.distance);
    for (const h of this.hits) {
      let o: any = h.object, top: any = null, agv = '', worker = '', ok = true;
      while (o) {
        if (!o.visible) { ok = false; break; }
        if (o.userData.agv && !top) { agv = o.userData.agv; top = o; }
        if (o.userData.worker && !top) { worker = o.userData.worker; top = o; }
        if (o.userData.id) { if (!top) top = o; break; }
        o = o.parent;
      }
      if (!ok || !o) continue;
      const out: HoverHit = { id: o.userData.id, obj: top };
      if (agv) out.agv = agv; if (worker) out.worker = worker;
      return out;
    }
    return null;
  }

  private pick() {
    const t0 = performance.now();
    const s = this.s;
    const h = !this.inside || this.down || this.mode === 'off' || s.walk?.on || s.tc?.dragging ? null : this.hitAt(this.px, this.py);
    this.lastPick = performance.now(); this.perf.picks++; this.perf.pickMs += this.lastPick - t0;
    const same = h && this.hit ? h.id === this.hit.id && h.obj === this.hit.obj : h === this.hit;
    if (same) return;
    this.hit = h; this.updCursor(); this.buildHovRing(); this.onHover(h);
  }
  updCursor() {
    const hot = this.mode === 'on' && (this.panelHot || (!!this.hit && !this.down));
    const c = hot ? 'pointer' : '';
    if (this.el.style.cursor !== c) this.el.style.cursor = c;
  }
  setPanelHot(on: boolean) { if (on !== this.panelHot) { this.panelHot = on; this.updCursor(); } }
  setMode(m: 'on' | 'pick' | 'off') { if (m === this.mode) return; this.mode = m; this.dirty = true; this.updCursor(); }

  // ---------- Outline sets ----------
  /** 3D objects for an ID: equipment group; AGV fleet = each vehicle; team = each person. */
  objsOf(id: string): THREE.Object3D[] {
    const s = this.s, it = s.items.get(id); if (!it) return [];
    if (it.s.kind === 'crew') return [...s.workers.values()].map((w: any) => w.g);
    const out: THREE.Object3D[] = [];
    if (it.agvs) out.push(...it.agvs.values());
    if (it.group?.parent) out.push(it.group);
    return out;
  }
  set(kind: Kind, ids: string[], objs?: THREE.Object3D[]) {
    this.ids[kind] = ids;
    this.sets[kind] = objs || ids.flatMap((id) => this.objsOf(id));
    this.all = [...new Set([...this.sets.sel, ...this.sets.hov, ...this.sets.rel])];
    for (const o of [...this.boxes.keys()]) if (!this.all.includes(o)) this.boxes.delete(o);
    this.boxTick = 0;
    if (kind === 'sel') { this.buildRings(); this.buildHovRing(); }
  }

  // ---------- Ground selection box ----------
  private footprint(o: THREE.Object3D): [number, number] | null {
    const id = o.userData.id, it = this.s.items.get(id);
    if (o.userData.agv) return [1.6, 1.1];
    if (o.userData.worker) return [0.8, 0.8];
    if (!it || it.group !== o) return null;
    const [L, W] = it.s.size || [2, 2]; return [L, W];
  }
  private buildRings() {
    for (const m of this.ringOf.keys()) { m.geometry.dispose(); this.rings.remove(m); }
    this.ringOf.clear();
    for (const o of this.sets.sel.slice(0, 40)) {
      const fp = this.footprint(o); if (!fp) continue;
      const small = !!(o.userData.agv || o.userData.worker);
      const m = new THREE.Mesh(ringGeo(fp[0], fp[1], small ? 0.25 : 0.45, small ? 0.12 : 0.2, !!o.userData.worker), this.ringMat);
      m.renderOrder = 7; this.rings.add(m); this.ringOf.set(m, o);
    }
  }
  private buildHovRing() {
    if (this.hovRing) { this.hovRing.geometry.dispose(); this.rings.remove(this.hovRing); this.ringOf.delete(this.hovRing); this.hovRing = null; }
    const o = this.hit?.obj; if (!o || this.sets.sel.includes(o)) return;
    const fp = this.footprint(o); if (!fp) return;
    const small = !!(o.userData.agv || o.userData.worker);
    this.hovRing = new THREE.Mesh(ringGeo(fp[0], fp[1], small ? 0.25 : 0.45, small ? 0.08 : 0.12, !!o.userData.worker), this.hovRingMat);
    this.hovRing.renderOrder = 7; this.rings.add(this.hovRing); this.ringOf.set(this.hovRing, o);
  }

  // ---------- Per frame ----------
  private pre = (_dt: number, t: number) => {
    const now = performance.now();
    // While the camera moves (damping, following), objects under the pointer change: repick at most every 120 ms
    if (this.inside && !this.down && now - this.camAt < 60 && now - this.lastPick > 120) this.dirty = true;
    // Stationary pointer, moving objects (AGVs, personnel arriving/leaving): recheck every 250 ms
    else if (this.inside && !this.down && now - this.lastPick > 250) this.dirty = true;
    if (this.dirty && now >= this.quiet) {
      this.dirty = false; this.pick();
      if (this.busy && !this.down) this.setBusy(false);   // Mouse wheel stopped
    }
    if (this.ringOf.size) {
      this.ringMat.opacity = 0.72 + 0.22 * Math.sin(t * 4);
      for (const [m, o] of this.ringOf) {
        m.visible = o.visible && !!o.parent;
        if (!m.visible) continue;
        o.getWorldPosition(this.v); m.position.set(this.v.x, this.v.y + 0.06, this.v.z);
        m.rotation.y = o.userData.worker ? 0 : o.rotation.y;
      }
    }
  };

  /** Combined screen bounds of these objects (canvas CSS pixels, y down); return false if all are offscreen. */
  private rx0 = 0; private ry0 = 0; private rx1 = 0; private ry1 = 0;
  private screenRect(W: number, H: number) {
    const cam = this.s.camera;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, behind = false;
    const recompute = this.boxTick++ % 12 === 0;
    for (const o of this.all) {
      if (!o.visible || !o.parent) continue;
      let b = this.boxes.get(o);
      const moving = !!(o.userData.agv || o.userData.worker);
      if (!b) { b = new THREE.Box3(); this.boxes.set(o, b); b.setFromObject(o); }
      else if (recompute || moving) b.setFromObject(o);
      if (b.isEmpty()) continue;
      for (let i = 0; i < 8; i++) {
        this.v.set(i & 1 ? b.max.x : b.min.x, i & 2 ? b.max.y : b.min.y, i & 4 ? b.max.z : b.min.z).project(cam);
        if (this.v.z > 1) { behind = true; continue; }
        const sx = (this.v.x + 1) / 2 * W, sy = (1 - this.v.y) / 2 * H;
        if (sx < x0) x0 = sx; if (sx > x1) x1 = sx; if (sy < y0) y0 = sy; if (sy > y1) y1 = sy;
      }
    }
    if (behind) { x0 = 0; y0 = 0; x1 = W; y1 = H; }
    x0 = Math.max(0, Math.floor(x0 - 12)); y0 = Math.max(0, Math.floor(y0 - 12)); x1 = Math.min(W, Math.ceil(x1 + 12)); y1 = Math.min(H, Math.ceil(y1 + 12));
    if (!(x1 > x0 && y1 > y0)) return false;
    this.rx0 = x0; this.ry0 = y0; this.rx1 = x1; this.ry1 = y1; return true;
  }

  private post = () => {
    if (!this.all.length) return;
    const t0 = performance.now();
    const R: THREE.WebGLRenderer = this.s.renderer, pr = R.getPixelRatio();
    R.getDrawingBufferSize(this.size);
    const W = this.size.x / pr, H = this.size.y / pr;
    if (!this.screenRect(W, H)) return;
    if (this.rt.width !== this.size.x || this.rt.height !== this.size.y) this.rt.setSize(this.size.x, this.size.y);
    const oldAuto = R.autoClear, oldAlpha = R.getClearAlpha(); R.getClearColor(this.cc);
    const x = this.rx0, y = H - this.ry1, w = this.rx1 - this.rx0, h = this.ry1 - this.ry0;
    // Mask (render-target scissor box uses device pixels, with origin at bottom left)
    this.rt.scissor.set(Math.floor(x * pr), Math.floor(y * pr), Math.ceil(w * pr), Math.ceil(h * pr)); this.rt.scissorTest = true;
    R.setRenderTarget(this.rt); R.autoClear = false; R.setClearColor(0x000000, 0); R.clear(true, false, false);
    const ch = this.maskScene.children as THREE.Object3D[];
    for (const k of ['rel', 'hov', 'sel'] as Kind[]) {
      const arr = this.sets[k]; if (!arr.length) continue;
      this.maskMat.color.setRGB(k === 'sel' ? 1 : 0, k === 'hov' ? 1 : 0, k === 'rel' ? 1 : 0);
      for (const o of arr) if (o.visible && o.parent) ch.push(o);        // Borrow only the children list; leave parents unchanged (world matrices are up to date)
      if (ch.length) R.render(this.maskScene, this.s.camera);
      ch.length = 0;
    }
    R.setRenderTarget(null);
    // Composite: run edge detection only within the bounding box
    this.fsMat.uniforms.texel.value.set(1 / this.size.x, 1 / this.size.y);
    this.fsMat.uniforms.px.value = pr;
    R.setScissor(x + 4, y + 4, Math.max(1, w - 8), Math.max(1, h - 8)); R.setScissorTest(true);
    R.render(this.fsScene, this.fsCam);
    R.setScissorTest(false);
    R.setClearColor(this.cc, oldAlpha); R.autoClear = oldAuto;
    this.perf.fxFrames++; this.perf.fxMs += performance.now() - t0;
  };

  /** Test hook: IDs currently hovered and outlined. */
  state() {
    return { hovered: this.hit?.id || '', agv: this.hit?.agv || '', worker: this.hit?.worker || '', cursor: this.el.style.cursor, busy: this.busy,
      outlined: { hover: [...this.ids.hov], selected: [...this.ids.sel], related: [...this.ids.rel] }, rings: this.ringOf.size, perf: { ...this.perf } };
  }

  dispose() {
    const el = this.el;
    el.removeEventListener('pointermove', this.onMove); el.removeEventListener('pointerleave', this.onLeave); el.removeEventListener('pointerdown', this.onDown);
    removeEventListener('pointerup', this.onUp); el.removeEventListener('wheel', this.onWheel);
    this.s.controls.removeEventListener('change', this.onCam);
    for (const m of this.ringOf.keys()) m.geometry.dispose();
    this.rt.dispose(); this.fsMat.dispose(); this.maskMat.dispose(); this.ringMat.dispose(); this.hovRingMat.dispose();
  }
}

export function register(scene: any) {
  if (scene.hover) return;
  if (!scene.beforeRender) { scene.beforeRender = []; scene.afterRender = []; scene.disposers = []; }
  scene.hover = new HoverFx(scene);
  (window as any).__vfScene = scene;            // Test hook: hover3d_ui.js reads __vfScene.hover.state() and screenOf(id)
}
