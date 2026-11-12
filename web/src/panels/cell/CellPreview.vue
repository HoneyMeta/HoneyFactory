<template>
  <div ref="host" class="cpv">
    <div class="cpv-bar">
      <button v-for="v in VIEWS" :key="v.k" :class="{ on: view === v.k }" @click="setView(v.k)">{{ v.n }}</button>
      <label><input v-model="tags" type="checkbox" @change="rebuild" /> {{ $t('common.no2') }}</label>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Control-cell 3D preview: shares component models with the factory 3D view (CellModel in scene_ext/cell.ts), animated from live frames during runs.
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DRenderer } from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { CellModel } from '../../scene_ext/cell';

const props = defineProps<{ cell: any; live?: any; selected?: string }>();
const host = ref<HTMLElement>();
const VIEWS = [{ k: 'iso', n: $t('cellPreview.isometric') }, { k: 'top', n: $t('view3D.topView') }, { k: 'front', n: $t('view3D.frontView') }];
const view = ref('iso'), tags = ref(false);
let renderer: THREE.WebGLRenderer, labels: CSS2DRenderer, scene: THREE.Scene, camera: THREE.PerspectiveCamera, controls: OrbitControls;
let model: CellModel, ro: ResizeObserver | null = null, raf = 0, clock = new THREE.Clock(), selBox: THREE.BoxHelper | null = null, grid: THREE.GridHelper | null = null;

/** Light background (--hm-canvas) + fine cobalt-gray grid. */
function setupBackdrop() {
  scene.background = new THREE.Color(0xf3f6fa);
  grid = new THREE.GridHelper(30, 60, 0xb9c6d6, 0xdde4ee); grid.position.y = -0.001; scene.add(grid);
}

function setView(k: string) {
  view.value = k;
  const [L, W] = props.cell?.size || [8, 4], d = Math.max(L, W * 1.6);
  const tgt = new THREE.Vector3(0, 0.4, 0);
  if (k === 'top') camera.position.set(0, d * 1.25, 0.001);
  else if (k === 'front') camera.position.set(0, d * 0.25, d * 0.95);
  else camera.position.set(d * 0.45, d * 0.55, d * 0.75);
  controls.target.copy(tgt); controls.update();
}
function rebuild() {
  if (!model) return;
  scene.remove(model.group);
  model.clear();
  model = new CellModel({ labels: tags.value });
  model.build(props.cell || { components: [] }, props.cell?.size);
  model.idle();
  scene.add(model.group);
  markSel();
}
function markSel() {
  if (selBox) { scene.remove(selBox); selBox = null; }
  const cv = props.selected ? model?.comps.get(props.selected) : null;
  if (cv) { selBox = new THREE.BoxHelper(cv.g, 0x1463d6); scene.add(selBox); }
}
onMounted(() => {
  const el = host.value!;
  renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  el.prepend(renderer.domElement);
  labels = new CSS2DRenderer(); labels.domElement.className = 'cpv-labels'; el.appendChild(labels.domElement);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(40, 1, 0.05, 200);
  controls = new OrbitControls(camera, labels.domElement); controls.enableDamping = true; controls.maxPolarAngle = Math.PI * 0.49;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x6b7380, 1.4));
  const sun = new THREE.DirectionalLight(0xffffff, 1.8); sun.position.set(-4, 9, 6); sun.castShadow = true; sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -7, right: 7, top: 5, bottom: -5, near: 0.5, far: 30 }); scene.add(sun);
  setupBackdrop();
  model = new CellModel({ labels: tags.value });
  model.build(props.cell || { components: [] }, props.cell?.size); model.idle(); scene.add(model.group);
  const resize = () => { const w = el.clientWidth, h = el.clientHeight; renderer.setSize(w, h); labels.setSize(w, h); camera.aspect = w / Math.max(1, h); camera.updateProjectionMatrix(); };
  ro = new ResizeObserver(resize); ro.observe(el); resize();
  setView('iso');
  const loop = () => {
    raf = requestAnimationFrame(loop);
    const dt = Math.min(0.1, clock.getDelta());
    if (props.live) model.tick(dt, clock.elapsedTime);
    selBox?.update();
    controls.update(); renderer.render(scene, camera); labels.render(scene, camera);
  };
  loop();
});
watch(() => props.cell, () => rebuild());
watch(() => props.live, (v) => { if (v && model) model.push(v); });
watch(() => props.selected, () => markSel());
onBeforeUnmount(() => { cancelAnimationFrame(raf); ro?.disconnect(); model?.clear(); renderer?.dispose(); labels?.domElement.remove(); });
</script>

<style scoped>
.cpv { position: relative; width: 100%; height: 100%; min-height: 160px; border-radius: var(--hm-r-md, 8px); overflow: hidden; background: var(--hm-canvas, #f3f6fa); border: 1px solid var(--hm-border, #e2e8f0); }
.cpv :deep(canvas) { display: block; }
.cpv :deep(.cpv-labels) { position: absolute; inset: 0; pointer-events: none; }
.cpv :deep(.cell-tag) { font: 10px Consolas, monospace; color: var(--tx, var(--el-text-color-primary)); background: color-mix(in srgb, var(--bg2, #fff) 85%, transparent); border: 1px solid var(--ln, #ccc); padding: 0 4px; border-radius: 3px; white-space: nowrap; }
.cpv-bar { position: absolute; top: 6px; left: 6px; display: flex; gap: 4px; align-items: center; font-size: 11px; color: var(--tx, var(--el-text-color-primary)); z-index: 2; }
.cpv-bar button { background: color-mix(in srgb, var(--bg2, #fff) 88%, transparent); color: inherit; border: 1px solid var(--ln2, var(--el-border-color)); border-radius: 3px; padding: 1px 7px; cursor: pointer; font-size: 11px; }
.cpv-bar button.on { border-color: var(--hm-primary, #1463d6); color: var(--hm-primary, #1463d6); background: var(--hm-primary-soft, #e8f0fd); font-weight: 600; }
.cpv-bar label { display: flex; gap: 3px; align-items: center; background: color-mix(in srgb, var(--bg2, #fff) 88%, transparent); border: 1px solid var(--ln2, var(--el-border-color)); padding: 0 6px; border-radius: 3px; }
</style>
