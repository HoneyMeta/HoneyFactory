<template>
  <div ref="host" class="ctv" tabindex="0" @keydown="onKey">
    <svg ref="svg" :viewBox="vb" preserveAspectRatio="xMidYMid meet" @pointerdown="onDown" @pointermove="onMove" @pointerup="onUp" @wheel.prevent="onWheel">
      <defs>
        <pattern id="ctv-grid" :width="0.1" :height="0.1" patternUnits="userSpaceOnUse"><path d="M0.1 0 L0 0 0 0.1" fill="none" class="g1" :stroke-width="px * 0.6" /></pattern>
        <pattern id="ctv-grid5" :width="0.5" :height="0.5" patternUnits="userSpaceOnUse"><rect width="0.5" height="0.5" fill="url(#ctv-grid)" />
          <path d="M0.5 0 L0 0 0 0.5" fill="none" class="g2" :stroke-width="px" /></pattern>
        <marker id="ctv-ar" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="4" markerHeight="4" orient="auto"><path d="M0 0 L10 5 L0 10 z" class="arr" /></marker>
      </defs>
      <rect :x="-L / 2" :y="-W / 2" :width="L" :height="W" fill="url(#ctv-grid5)" class="floor" :stroke-width="px * 2" />
      <g v-for="c in comps" :key="c.id" :transform="`translate(${posOf(c)[0]},${posOf(c)[1]}) rotate(${c.rot || 0})`" class="cp" :class="[c.type, { sel: c.id === cs.comp, hot: live?.comps?.[c.id]?.d }]"
        :data-id="c.id">
        <!-- Conveyor -->
        <template v-if="['belt_conveyor', 'roller_conveyor'].includes(c.type)">
          <rect :x="-sz(c)[0] / 2" :y="-sz(c)[1] / 2" :width="sz(c)[0]" :height="sz(c)[1]" class="belt" :stroke-width="px * 1.5" />
          <template v-if="c.type === 'roller_conveyor'"><line v-for="i in rollers(c)" :key="i" :x1="-sz(c)[0] / 2 + i * 0.075" :x2="-sz(c)[0] / 2 + i * 0.075" :y1="-sz(c)[1] / 2 + 0.02" :y2="sz(c)[1] / 2 - 0.02" class="rl" :stroke-width="px * 1.2" /></template>
          <line :x1="-sz(c)[0] / 2 + 0.15" :x2="sz(c)[0] / 2 - 0.15" y1="0" y2="0" class="flow" :stroke-width="px * 1.6" marker-end="url(#ctv-ar)" />
        </template>
        <path v-else-if="c.type === 'curved_conveyor'" :d="arcPath(c)" class="belt" :stroke-width="px * 1.5" />
        <template v-else-if="c.type === 'chain_transfer'"><rect :x="-sz(c)[0] / 2" :y="-sz(c)[1] / 2" :width="sz(c)[0]" :height="sz(c)[1]" class="chain" :stroke-width="px * 1.5" />
          <line x1="0" x2="0" :y1="-sz(c)[1] / 2 + 0.05" :y2="sz(c)[1] / 2 - 0.05" class="flow" :stroke-width="px * 1.6" marker-end="url(#ctv-ar)" /></template>
        <!-- Inlet/outlet -->
        <template v-else-if="['emitter', 'cell_entry'].includes(c.type)"><path d="M-0.16 -0.16 L0.18 0 L-0.16 0.16 Z" class="emit" :stroke-width="px * 1.5" /></template>
        <template v-else-if="['remover', 'cell_exit'].includes(c.type)"><rect :x="-sz(c)[0] / 2" :y="-sz(c)[1] / 2" :width="sz(c)[0]" :height="sz(c)[1]" class="bin" :class="binColor(c)" :stroke-width="px * 1.5" /></template>
        <!-- Sensors: beam points along -y -->
        <template v-else-if="['diffuse_sensor', 'retro_sensor', 'capacitive', 'inductive'].includes(c.type)">
          <line x1="0" y1="0" x2="0" :y2="-beam(c)" class="beam" :stroke-width="px * 1.6" />
          <rect x="-0.035" y="-0.02" width="0.07" height="0.05" class="sens" :stroke-width="px" />
        </template>
        <template v-else-if="['vision_sensor', 'height_sensor'].includes(c.type)"><circle :r="prm(c, 'radius', 0.1)" class="cam" :stroke-width="px * 1.4" /><rect x="-0.04" y="-0.03" width="0.08" height="0.06" class="sens" :stroke-width="px" /></template>
        <circle v-else-if="c.type === 'encoder'" r="0.05" class="sens" :stroke-width="px" />
        <!-- Actuators -->
        <template v-else-if="c.type === 'pusher'"><rect x="-0.05" y="0.04" width="0.1" :height="(prm(c, 'stroke', 0.8) as number) * 0.6 + 0.15" class="act" :stroke-width="px" />
          <rect :x="-(prm(c, 'head', 0.4) as number) / 2" :y="-(live?.comps?.[c.id]?.p || 0) - 0.01" :width="prm(c, 'head', 0.4)" height="0.03" class="plate" /></template>
        <rect v-else-if="c.type === 'stopper'" x="-0.025" :y="-(prm(c, 'width', 0.6) as number) / 2" width="0.05" :height="prm(c, 'width', 0.6)" class="stop" :class="{ up: (live?.comps?.[c.id]?.u || 0) > 0.5 }" />
        <template v-else-if="c.type === 'pivot_arm'"><circle r="0.05" class="act" /><line x1="0" y1="0" :x2="Math.cos(arm(c)) * (prm(c, 'length', 0.85) as number)" :y2="-Math.sin(arm(c)) * (prm(c, 'length', 0.85) as number)" class="plate-l" :stroke-width="px * 4" /></template>
        <template v-else-if="c.type === 'turntable'"><circle :r="Math.min(...sz(c)) / 2" class="tt" :stroke-width="px * 1.5" />
          <line :x1="0" :y1="0" :x2="Math.cos(ttA(c)) * Math.min(...sz(c)) * 0.42" :y2="Math.sin(ttA(c)) * Math.min(...sz(c)) * 0.42" class="flow" :stroke-width="px * 1.6" marker-end="url(#ctv-ar)" /></template>
        <template v-else-if="c.type === 'lift'"><rect :x="-sz(c)[0] / 2" :y="-sz(c)[1] / 2" :width="sz(c)[0]" :height="sz(c)[1]" class="lift" :stroke-width="px * 1.5" />
          <path :d="`M${-sz(c)[0] / 2} ${-sz(c)[1] / 2} L${sz(c)[0] / 2} ${sz(c)[1] / 2} M${sz(c)[0] / 2} ${-sz(c)[1] / 2} L${-sz(c)[0] / 2} ${sz(c)[1] / 2}`" class="lift-x" :stroke-width="px" /></template>
        <template v-else-if="c.type === 'pick_place'"><line x1="-0.2" y1="0" :x2="(prm(c, 'x_stroke', 1.2) as number) + 0.2" y2="0" class="gantry" :stroke-width="px * 5" />
          <circle :cx="live?.comps?.[c.id]?.x || 0" cy="0" r="0.06" class="tool" :class="{ on: live?.comps?.[c.id]?.g }" /></template>
        <template v-else-if="c.type === 'stacker_crane'"><line x1="0" y1="0" :x2="prm(c, 'travel', 3)" y2="0" class="gantry" :stroke-width="px * 3" />
          <rect :x="(live?.comps?.[c.id]?.x || 0) - 0.15" y="-0.15" width="0.3" height="0.3" class="crane" />
          <rect :x="(live?.comps?.[c.id]?.x || 0) - 0.1" :y="Math.min(0, live?.comps?.[c.id]?.f || 0)" width="0.2" :height="Math.abs(live?.comps?.[c.id]?.f || 0)" class="fork" /></template>
        <template v-else-if="c.type === 'gripper'"><rect x="-0.08" :y="-sz(c)[1] / 2" width="0.16" :height="sz(c)[1]" class="grip" :stroke-width="px * 1.2" /></template>
        <template v-else-if="c.type === 'motor'"><rect :x="-0.15" y="-0.1" width="0.3" height="0.2" rx="0.04" class="motor" :stroke-width="px" /></template>
        <template v-else-if="c.type === 'rack'"><rect :x="-sz(c)[0] / 2" :y="-sz(c)[1] / 2" :width="sz(c)[0]" :height="sz(c)[1]" class="rack" :stroke-width="px * 1.5" />
          <line v-for="i in Math.max(0, (prm(c, 'cols', 4) as number) - 1)" :key="i" :x1="-sz(c)[0] / 2 + i * sz(c)[0] / (prm(c, 'cols', 4) as number)" :x2="-sz(c)[0] / 2 + i * sz(c)[0] / (prm(c, 'cols', 4) as number)"
            :y1="-sz(c)[1] / 2" :y2="sz(c)[1] / 2" class="rack-l" :stroke-width="px" /></template>
        <rect v-else-if="c.type === 'pallet'" :x="-sz(c)[0] / 2" :y="-sz(c)[1] / 2" :width="sz(c)[0]" :height="sz(c)[1]" class="pallet" :stroke-width="px * 1.2" />
        <!-- Panel -->
        <circle v-else-if="PANEL.has(c.type)" r="0.045" class="pn" :class="[c.type, panelColor(c), { on: live?.comps?.[c.id]?.on || live?.comps?.[c.id]?.s }]" :stroke-width="px" />
        <rect v-else x="-0.1" y="-0.1" width="0.2" height="0.2" class="act" />
        <!-- Selection outline + number -->
        <rect v-if="c.id === cs.comp" :x="-hit(c)[0] / 2 - 0.04" :y="-hit(c)[1] / 2 - 0.04" :width="hit(c)[0] + 0.08" :height="hit(c)[1] + 0.08" class="selbox" :stroke-width="px * 1.5" />
        <rect :x="-hit(c)[0] / 2" :y="-hit(c)[1] / 2" :width="hit(c)[0]" :height="hit(c)[1]" class="hitbox" />
      </g>
      <!-- Live parts -->
      <g v-if="live" class="parts">
        <rect v-for="p in live.parts || []" :key="p.i" :x="p.p[0] - p.w / 2" :y="p.p[1] - p.w / 2" :width="p.w" :height="p.w" :transform="`rotate(${(p.a || 0) * 57.2958} ${p.p[0]} ${p.p[1]})`"
          :class="['pt', 'c-' + p.c]" :stroke-width="px" />
      </g>
      <g class="tags"><text v-for="c in comps.filter((k: any) => !PANEL.has(k.type) || k.id === cs.comp)" :key="c.id" :x="posOf(c)[0]" :y="posOf(c)[1] + tagDy(c)" :font-size="px * 11" text-anchor="middle" class="tag" :class="{ sel: c.id === cs.comp }">{{ c.id }}</text></g>
      <rect v-if="ghost" :x="ghost[0] - 0.12" :y="ghost[1] - 0.12" width="0.24" height="0.24" class="ghost" :stroke-width="px * 1.5" />
    </svg>
    <div v-if="!comps.length" class="ctv-empty">{{ $t('topView.floorPlanCellBoundaryYellow') }}<br />{{ $t('topView.selectAComponentInThe') }}</div>
    <div class="ctv-bar">
      <span class="mono">{{ cursor[0].toFixed(2) }}, {{ cursor[1].toFixed(2) }} m</span>
      <span v-if="cs.tool" class="tool-tip">{{ $t('topView.clickToPlace0Esc', [typeOf(cs.tool).label]) }}</span>
      <span v-else class="muted">{{ $t('topView.dragToMoveRTo') }}</span>
      <span class="grow" />
      <button class="zb" :title="$t('planView.fitToWindow')" @click="zoom = 1; pan = [0, 0]">⤢</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { computed, ref } from 'vue';
import { clone, cs, defaultComp, newCompId, round, typeOf } from './state';

const props = defineProps<{ cell: any; live?: any; editable?: boolean }>();
const emit = defineEmits<{ (e: 'change', cell: any, label: string, regen?: boolean): void }>();
const PANEL = new Set(['button', 'switch', 'estop', 'lamp', 'display', 'potentiometer']);
const host = ref<HTMLElement>(), svg = ref<SVGSVGElement>();
const zoom = ref(1), pan = ref([0, 0]);
const cursor = ref([0, 0]), ghost = ref<number[] | null>(null);
const dragPos = ref<{ id: string; pos: number[] } | null>(null);     // Temporary drag position (commit on release for undo support)
const posOf = (c: any) => (dragPos.value && dragPos.value.id === c.id ? dragPos.value.pos : c.pos);
const L = computed(() => props.cell?.size?.[0] || 8), W = computed(() => props.cell?.size?.[1] || 4);
const comps = computed(() => props.cell?.components || []);
const vb = computed(() => {
  const m = 0.4, w = (L.value + 2 * m) / zoom.value, h = (W.value + 2 * m) / zoom.value;
  return `${-w / 2 + pan.value[0]} ${-h / 2 + pan.value[1]} ${w} ${h}`;
});
const px = computed(() => {        // Meters per screen pixel
  const el = svg.value; const w = el?.clientWidth || 600, h = el?.clientHeight || 300;
  const vw = (L.value + 0.8) / zoom.value, vh = (W.value + 0.8) / zoom.value;
  return Math.max(vw / w, vh / h);
});
const sz = (c: any) => c.size || typeOf(c.type).size || [0.5, 0.5];
const prm = (c: any, k: string, d: any) => (c.params?.[k] ?? typeOf(c.type).params?.[k]?.default ?? d);
const rollers = (c: any) => Math.max(0, Math.floor(sz(c)[0] / 0.075) - 1);
const beam = (c: any) => {
  const v = props.live?.comps?.[c.id];
  if (v?.d && v.len !== undefined) return v.len;
  return +(prm(c, 'range', 0.6) as number) || 0.6;
};
const arm = (c: any) => ((props.live?.comps?.[c.id]?.a || 0) * Math.PI) / 180;
const ttA = (c: any) => ((props.live?.comps?.[c.id]?.a || 0) * Math.PI) / 180;
const binColor = (c: any) => 'c-' + (c.params?.accept?.color || (c.params?.accept?.material === 'metal' ? 'grey' : c.type === 'cell_exit' ? 'exit' : 'none'));
const panelColor = (c: any) => 'c-' + (c.params?.color || (c.type === 'estop' ? 'red' : 'none'));
function hit(c: any) {
  const t = c.type;
  if (['belt_conveyor', 'roller_conveyor', 'chain_transfer', 'remover', 'cell_exit', 'lift', 'rack', 'pallet', 'turntable', 'gripper'].includes(t)) return sz(c);
  if (t === 'pick_place') return [Math.max(0.3, +prm(c, 'x_stroke', 1.2) * 2 + 0.4), 0.25];
  if (t === 'stacker_crane') return [Math.max(0.3, +prm(c, 'travel', 3) * 2), 0.3];
  if (t === 'curved_conveyor') return [0.5, 0.5];
  if (t === 'pivot_arm') return [0.25, 0.25];
  if (t === 'pusher') return [+prm(c, 'head', 0.4), 0.25];
  return [0.18, 0.18];
}
function tagDy(c: any) { const h = hit(c)[1]; return -h / 2 - 0.06; }
function arcPath(c: any) {
  const R = +prm(c, 'radius', 0.9), ang = (+prm(c, 'angle', 90) * Math.PI) / 180, W2 = sz(c)[1] / 2, s = ang > 0 ? 1 : -1;
  const cx = 0, cy = s * R, a0 = Math.atan2(-s * R, 0), a1 = a0 + ang;
  const pt = (r: number, a: number) => `${(cx + Math.cos(a) * r).toFixed(3)} ${(cy + Math.sin(a) * r).toFixed(3)}`;
  const big = Math.abs(ang) > Math.PI ? 1 : 0, sw = ang > 0 ? 1 : 0;
  return `M${pt(R - W2, a0)} A${R - W2} ${R - W2} 0 ${big} ${sw} ${pt(R - W2, a1)} L${pt(R + W2, a1)} A${R + W2} ${R + W2} 0 ${big} ${1 - sw} ${pt(R + W2, a0)} Z`;
}

// ---------------- Interaction ----------------
function toWorld(e: PointerEvent | WheelEvent) {
  const el = svg.value!; const pt = el.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY;
  const m = el.getScreenCTM(); if (!m) return [0, 0];
  const p = pt.matrixTransform(m.inverse()); return [p.x, p.y];
}
let drag: any = null;
function onDown(e: PointerEvent) {
  host.value?.focus();
  const [x, y] = toWorld(e);
  if (cs.tool && props.editable) {
    const cell = clone(props.cell); cell.components ||= [];
    const id = newCompId(cell, cs.tool);
    cell.components.push(defaultComp(cs.tool, id, [x, y]));
    emit('change', cell, $t('topView.add01', [typeOf(cs.tool).label, id]), true);
    cs.comp = id; cs.tool = ''; ghost.value = null;
    return;
  }
  const g = (e.target as Element).closest('g.cp') as SVGGElement | null;
  if (!g) { cs.comp = ''; drag = { pan: true, x: e.clientX, y: e.clientY, p0: [...pan.value] }; svg.value?.setPointerCapture(e.pointerId); return; }
  const id = g.dataset.id!; cs.comp = id;
  if (!props.editable) return;
  const c = comps.value.find((k: any) => k.id === id);
  drag = { id, x0: x, y0: y, pos0: [...c.pos], moved: false };
  svg.value?.setPointerCapture(e.pointerId);
}
function onMove(e: PointerEvent) {
  const [x, y] = toWorld(e); cursor.value = [x, y];
  if (cs.tool) { ghost.value = [round(x), round(y)]; return; }
  if (!drag) return;
  if (drag.pan) {
    const k = px.value; pan.value = [drag.p0[0] - (e.clientX - drag.x) * k, drag.p0[1] - (e.clientY - drag.y) * k]; return;
  }
  const nx = round(drag.pos0[0] + x - drag.x0), ny = round(drag.pos0[1] + y - drag.y0);
  if (nx !== drag.pos0[0] || ny !== drag.pos0[1] || drag.moved) { dragPos.value = { id: drag.id, pos: [nx, ny, drag.pos0[2] ?? 0] }; drag.moved = true; }
}
function onUp() {
  if (drag && !drag.pan && drag.moved && dragPos.value) {
    const cell = clone(props.cell); const c = cell.components.find((k: any) => k.id === drag.id);
    if (c) { c.pos = dragPos.value.pos; emit('change', cell, $t('cellInspector.move0', [drag.id]), false); }
  }
  drag = null; dragPos.value = null;
}
function onWheel(e: WheelEvent) {
  const k = e.deltaY < 0 ? 1.15 : 1 / 1.15;
  zoom.value = Math.max(0.5, Math.min(8, zoom.value * k));
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') { cs.tool = ''; ghost.value = null; return; }
  if (!props.editable || !cs.comp) return;
  const cell = clone(props.cell); const c = cell.components.find((k: any) => k.id === cs.comp); if (!c) return;
  const step = e.shiftKey ? 0.25 : 0.05;
  if (e.key === 'r' || e.key === 'R') { c.rot = ((c.rot || 0) + (e.shiftKey ? -90 : 90) + 360) % 360; if (c.rot > 180) c.rot -= 360; emit('change', cell, $t('topView.rotate0', [c.id]), false); }
  else if (e.key === 'Delete' || e.key === 'Backspace') {
    cell.components = cell.components.filter((k: any) => k.id !== cs.comp); emit('change', cell, $t('cellInspector.delete0', [cs.comp]), true); cs.comp = '';
  } else if (e.key.startsWith('Arrow')) {
    const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key as 'ArrowLeft']!;
    c.pos = [round(c.pos[0] + d[0]), round(c.pos[1] + d[1]), c.pos[2] ?? 0]; emit('change', cell, $t('cellInspector.move0', [c.id]), false);
  } else return;
  e.preventDefault();
}
</script>

<style scoped>
/* Colors: UI uses Workbench variables (--bg0~3, --tx, --mu, --ln, --sel, mapped to --hm-* tokens, light theme only); equipment colors (orange pusher, yellow sensor…) match the 3D view and are defined here. */
.ctv {
  --pv-bg: var(--hm-canvas, #f3f6fa); --pv-floor: var(--hm-surface, #fff); --pv-ln: var(--ln, var(--el-border-color-lighter));
  --pv-ln2: var(--ln2, var(--el-border-color)); --pv-tx: var(--tx, var(--el-text-color-primary)); --pv-mu: var(--mu, var(--el-text-color-secondary));
  --pv-sel: var(--sel, var(--el-color-primary)); --pv-eq: color-mix(in srgb, var(--pv-tx) 58%, var(--pv-bg)); --pv-eq2: color-mix(in srgb, var(--pv-tx) 35%, var(--pv-bg));
  --pv-yellow: #c99a12; --pv-orange: #e07a14; --pv-blue: #1f5fb8; --pv-green: #15a34a; --pv-red: #dc2b2b; --pv-hot: #e07000; --pv-cam: #0a85a8;
  position: relative; display: flex; flex-direction: column; height: 100%; min-height: 180px; outline: none; background: var(--pv-bg);
  border: 1px solid var(--pv-ln); border-radius: var(--hm-r-md, 8px); overflow: hidden;
}
svg { flex: 1; width: 100%; min-height: 0; cursor: default; user-select: none; touch-action: none; }
.floor { fill: var(--pv-floor); stroke: var(--pv-yellow); stroke-dasharray: 0.12 0.08; }
.g1 { stroke: var(--pv-ln); opacity: .5; } .g2 { stroke: var(--pv-ln2); opacity: .8; }
.arr { fill: var(--pv-yellow); }
.belt { fill: var(--pv-eq); stroke: var(--pv-mu); } .rl { stroke: var(--pv-eq2); } .flow { stroke: var(--pv-yellow); fill: none; }
.chain { fill: var(--pv-eq); stroke: var(--pv-mu); stroke-dasharray: 0.04 0.03; }
.emit { fill: var(--pv-green); stroke: color-mix(in srgb, var(--pv-green) 50%, white); }
.bin { fill: color-mix(in srgb, var(--pv-mu) 22%, transparent); stroke: var(--pv-mu); stroke-dasharray: 0.05 0.03; }
.bin.c-blue { fill: color-mix(in srgb, #2f74c0 35%, transparent); stroke: #2f74c0; } .bin.c-green { fill: color-mix(in srgb, #3aa64a 35%, transparent); stroke: #3aa64a; }
.bin.c-grey { fill: color-mix(in srgb, #9aa3ab 40%, transparent); } .bin.c-red { fill: color-mix(in srgb, var(--pv-red) 35%, transparent); stroke: var(--pv-red); }
.bin.c-exit { fill: color-mix(in srgb, var(--pv-sel) 22%, transparent); stroke: var(--pv-sel); stroke-dasharray: none; }
.bin.c-orange { fill: color-mix(in srgb, #ec8a24 35%, transparent); }
.beam { stroke: color-mix(in srgb, #ff3c28 60%, transparent); stroke-dasharray: 0.03 0.02; } .cp.hot .beam { stroke: var(--pv-hot); stroke-dasharray: none; }
.sens { fill: var(--pv-yellow); stroke: var(--pv-tx); } .cp.hot .sens { fill: var(--pv-hot); }
.cam { fill: color-mix(in srgb, var(--pv-cam) 18%, transparent); stroke: var(--pv-cam); stroke-dasharray: 0.02 0.02; } .cp.hot .cam { fill: color-mix(in srgb, var(--pv-cam) 40%, transparent); }
.act { fill: var(--pv-eq); stroke: var(--pv-mu); } .plate { fill: var(--pv-orange); } .plate-l { stroke: var(--pv-orange); stroke-linecap: round; }
.stop { fill: color-mix(in srgb, var(--pv-yellow) 45%, transparent); } .stop.up { fill: var(--pv-yellow); }
.tt { fill: var(--pv-eq); stroke: var(--pv-mu); } .lift { fill: color-mix(in srgb, var(--pv-blue) 25%, transparent); stroke: var(--pv-blue); } .lift-x { stroke: var(--pv-blue); }
.gantry { stroke: var(--pv-mu); stroke-linecap: round; opacity: .8; } .tool { fill: var(--pv-orange); } .tool.on { fill: var(--pv-green); }
.crane { fill: #f2b01e; } .fork { fill: var(--pv-tx); }
.grip { fill: color-mix(in srgb, var(--pv-orange) 25%, transparent); stroke: var(--pv-orange); } .motor { fill: #3d6b94; stroke: var(--pv-mu); }
.rack { fill: color-mix(in srgb, var(--pv-blue) 18%, transparent); stroke: var(--pv-blue); } .rack-l { stroke: var(--pv-orange); } .pallet { fill: #c69a62; stroke: #8a6a3e; }
.pn { fill: var(--pv-eq); stroke: var(--pv-tx); } .pn.c-green { fill: #22c55e; } .pn.c-red { fill: #ef4444; } .pn.c-yellow { fill: #f5c518; } .pn.c-blue { fill: #3b82f6; }
.pn.c-white { fill: #f8fafc; } .pn.estop { fill: #d42a24; stroke: var(--pv-yellow); } .pn.display { fill: #0c0f12; stroke: #ff3b30; } .pn.lamp { opacity: .55; } .pn.lamp.on { opacity: 1; }
.hitbox { fill: transparent; cursor: move; }
.selbox { fill: none; stroke: var(--pv-sel); stroke-dasharray: 0.04 0.03; }
.tag { fill: var(--pv-tx); opacity: .8; pointer-events: none; font-family: Consolas, monospace; } .tag.sel { fill: var(--pv-sel); opacity: 1; font-weight: 700; }
.pt { stroke: color-mix(in srgb, var(--pv-tx) 60%, transparent); } .pt.c-blue { fill: #2f74c0; } .pt.c-green { fill: #3aa64a; } .pt.c-grey { fill: #9aa3ab; } .pt.c-red { fill: #d0453a; }
.pt.c-yellow { fill: #f0c419; } .pt.c-orange { fill: #ec8a24; } .pt.c-white { fill: #eef0f2; }
.ghost { fill: color-mix(in srgb, var(--pv-sel) 20%, transparent); stroke: var(--pv-sel); stroke-dasharray: 0.03 0.02; pointer-events: none; }
.ctv-bar { display: flex; align-items: center; gap: 10px; padding: 3px 8px; font-size: 11px; color: var(--pv-mu); background: var(--pv-floor); border-top: 1px solid var(--pv-ln); }
.ctv-bar .grow { flex: 1; } .tool-tip { color: var(--pv-sel); } .mono { font-family: Consolas, monospace; }
.zb { background: none; border: 1px solid var(--pv-ln2); color: inherit; border-radius: 3px; cursor: pointer; padding: 0 6px; }
.ctv-empty { position: absolute; inset: 0 0 24px 0; display: flex; align-items: center; justify-content: center; text-align: center; color: var(--pv-mu); font-size: 12px; pointer-events: none; padding: 0 20px; }
</style>
