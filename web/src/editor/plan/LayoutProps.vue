<template>
  <!-- Properties for floor plan layout elements (walls, areas, aisles, road network nodes/links, dimensions): shown in the right "Properties" panel (replaces floating canvas property cards since 4.4) -->
  <div class="dt-lay">
    <div class="dt-head"><el-icon class="dt-ic" style="background:#5b6b80"><component :is="icon" /></el-icon>
      <div><b>{{ title }}</b><small><span v-if="sub" class="mono">{{ sub }}</span> {{ $t('layoutProps.floorPlanLayoutElement') }}</small></div></div>
    <div class="dt-actions">
      <el-tooltip :content="$t('layoutProps.copyCtrlCThenPress')" :show-after="300"><el-button size="small" @click="copyLay"><el-icon><CopyDocument /></el-icon> {{ $t('common.copy') }}</el-button></el-tooltip>
      <el-tooltip :content="$t('layoutProps.duplicateInPlaceCtrlD')" :show-after="300"><el-button size="small" @click="duplicateLay">{{ $t('common.duplicate') }}</el-button></el-tooltip>
      <el-tooltip :content="$t('planView.duplicateInRowsAndColumns')" :show-after="300"><el-button size="small" class="dl-arr" @click="pv.arrayOpen = true"><el-icon><Grid /></el-icon> {{ $t('planView.array') }}</el-button></el-tooltip>
      <el-tooltip :content="$t('layoutProps.deleteDel')" :show-after="300"><el-button size="small" type="danger" plain @click="removeLays()"><el-icon><Delete /></el-icon></el-button></el-tooltip>
    </div>

    <!-- Multiple selection -->
    <div v-if="!it" class="dt-sec">
      <div class="chips"><span v-for="s in pv.lsel" :key="s.kind + s.id" class="chip click" @click="pv.lsel = [s]">{{ LK_CN[s.kind] }} {{ s.id }}</span></div>
      <p class="muted small">{{ $t('layoutProps.useArrowKeysToNudge') }}</p>
    </div>

    <div v-else class="dt-sec">
      <div v-if="it.outer" class="dl-note">{{ $t('layoutProps.buildingExteriorWallsWorkLike') }}</div>
      <template v-if="s1.kind === 'zones'">
        <div class="f"><label>{{ $t('common.name') }}</label><el-input ref="nameInp" v-model="nm" size="small" @change="(x: string) => x && x !== it.name && setItem({ name: x })" /></div>
        <div class="f"><label>{{ $t('common.color') }}</label><el-color-picker :model-value="it.color" size="small" @change="(x: any) => setItem({ color: x })" />
          <span class="grow" /><span class="muted small">{{ $t('layoutProps.area0M', [area(it.pts).toFixed(1)]) }}</span></div>
      </template>
      <template v-if="s1.kind === 'walls'">
        <div class="grid2">
          <div class="f"><label>{{ $t('layoutProps.thickness') }}</label><el-input-number :model-value="it.t ?? 0.24" size="small" :step="0.05" :min="0.05" :controls="false" @change="(x: any) => setItem({ t: x })" /><span class="unit">m</span></div>
          <div class="f"><label>{{ $t('layoutProps.height') }}</label><el-input-number :model-value="it.h ?? 4" size="small" :step="0.5" :min="0.5" :controls="false" @change="(x: any) => setItem({ h: x })" /><span class="unit">m</span></div>
        </div>
        <div class="f"><label>{{ $t('layoutProps.closed') }}</label><el-switch :model-value="closed" size="small" @change="toggleClosed" /><span class="grow" /><span class="muted small">{{ $t('layoutProps.totalLength0M', [polyLen(it.pts).toFixed(2)]) }}</span></div>
        <div class="sub-t">{{ $t('layoutProps.doorOpenings') }} <el-button size="small" text type="primary" @click="addDoor"><el-icon><Plus /></el-icon> {{ $t('layoutProps.addDoorOpening') }}</el-button></div>
        <div v-for="(d, k) in it.doors || []" :key="k" class="f dl-door">
          <label>{{ $t('layoutProps.distanceFromStart') }}</label><el-input-number :model-value="d.s" size="small" :step="0.5" :min="0" :controls="false" @change="(x: any) => setDoor(k, { s: x })" /><span class="unit">m</span>
          <label class="l2">{{ $t('common.width') }}</label><el-input-number :model-value="d.w" size="small" :step="0.1" :min="0.3" :controls="false" @change="(x: any) => setDoor(k, { w: x })" /><span class="unit">m</span>
          <el-button size="small" text type="danger" :title="$t('layoutProps.deleteDoorOpening')" @click="delDoor(k)"><el-icon><Close /></el-icon></el-button>
        </div>
        <p v-if="!(it.doors || []).length" class="muted small">{{ $t('layoutProps.rightClickAWallAdd') }}</p>
      </template>
      <template v-if="s1.kind === 'aisles'">
        <div class="f"><label>{{ $t('planView.width') }}</label><el-input-number :model-value="it.w ?? 3" size="small" :step="0.5" :min="0.5" :controls="false" @change="(x: any) => setItem({ w: x })" /><span class="unit">m</span>
          <span class="grow" /><span class="muted small">{{ $t('planView.length0M', [polyLen(it.pts).toFixed(2)]) }}</span></div>
      </template>
      <template v-if="s1.kind === 'nodes'">
        <div class="f"><label>{{ $t('common.type') }}</label><el-select :model-value="it.kind || 'node'" size="small" @change="(x: any) => setItem({ kind: x, ...(x === 'node' ? { block: null } : {}) })">
          <el-option v-for="(n, k) in NODE_CN" :key="k" :value="k" :label="n" /></el-select></div>
        <div v-if="(it.kind || 'node') !== 'node'" class="f"><label>{{ $t('layoutProps.pickupDropOffEquipment') }}</label>
          <el-select :model-value="it.block || ''" size="small" filterable clearable :placeholder="$t('layoutProps.unboundUseNearestNode')" @change="(x: any) => setItem({ block: x || null })">
            <el-option v-for="b in bindable" :key="b.id" :value="b.id" :label="$t('common.n012', [b.name, b.id])" /></el-select>
          <el-tooltip :content="$t('layoutProps.clickAMachineOnThe')"><el-button size="small" text @click="pickBlock"><el-icon><Aim /></el-icon></el-button></el-tooltip></div>
        <p v-if="(it.kind || 'node') !== 'node'" class="muted small">{{ $t('layoutProps.whenBoundTheTransportFleet') }}</p>
        <div class="grid2">
          <div class="f"><label>X</label><el-input-number :model-value="it.x" size="small" :step="0.5" :controls="false" @change="(x: any) => setItem({ x })" /><span class="unit">m</span></div>
          <div class="f"><label>Y</label><el-input-number :model-value="it.y" size="small" :step="0.5" :controls="false" @change="(y: any) => setItem({ y })" /><span class="unit">m</span></div>
        </div>
      </template>
      <template v-if="s1.kind === 'edges'">
        <div class="f"><el-checkbox :model-value="!!it.oneway" size="small" @change="(x: any) => setItem({ oneway: x || null })">{{ $t('planView.oneWayTraffic') }}</el-checkbox>
          <el-button size="small" text @click="setItem({ a: it.b, b: it.a })"><el-icon><Sort /></el-icon> {{ $t('planView.reverseDirection') }}</el-button>
          <span class="grow" /><span class="muted small">{{ $t('planView.length0M', [edgeLen.toFixed(2)]) }}</span></div>
        <div class="f"><label>{{ $t('layoutProps.speedLimit') }}</label><el-input-number :model-value="it.vmax" size="small" :step="0.1" :min="0.05" :controls="false" :placeholder="$t('common.unrestricted')" @change="(x: any) => setItem({ vmax: x || null })" /><span class="unit">m/s</span></div>
        <p class="muted small">{{ $t('layoutProps.vehiclesUseTheLowerOf', [it.oneway ? $t('layoutProps.oneWayTravelOnlyFrom') + it.a + $t('layoutProps.to') + it.b + $t('common.k266') : '']) }}</p>
      </template>
      <template v-if="s1.kind === 'dims'">
        <div class="f"><label>{{ $t('layoutProps.length') }}</label><b class="mono">{{ dist(it.a, it.b).toFixed(2) }} m</b><span class="grow" /><span class="muted small">{{ $t('layoutProps.dragEitherEndpointToAdjust') }}</span></div>
      </template>
      <template v-if="['walls', 'zones', 'aisles'].includes(s1.kind)">
        <div class="sub-t">{{ $t('layoutProps.vertices0', [vpts.length]) }}<small class="muted">{{ $t('layoutProps.editCoordinatesOrSegmentLength') }}</small></div>
        <table class="dl-pts">
          <tr><th>#</th><th>X (m)</th><th>Y (m)</th><th :title="$t('layoutProps.distanceToTheNextVertex')">{{ $t('layoutProps.segmentLength') }}</th><th /></tr>
          <tr v-for="(q, i) in vpts" :key="i">
            <td class="muted">{{ i + 1 }}</td>
            <td><el-input-number :model-value="q[0]" size="small" :step="0.5" :controls="false" @change="(x: any) => setPt(i, 0, x)" /></td>
            <td><el-input-number :model-value="q[1]" size="small" :step="0.5" :controls="false" @change="(x: any) => setPt(i, 1, x)" /></td>
            <td><el-input-number v-if="segLen(i) !== null" :model-value="segLen(i)" size="small" :min="0.05" :step="0.5" :controls="false" @change="(x: any) => setSegLen(i, x)" /></td>
            <td><el-button size="small" text :disabled="vpts.length <= minPts" :title="$t('planView.deleteThisVertex')" @click="delPt(i)"><el-icon><Close /></el-icon></el-button></td>
          </tr>
        </table>
        <p class="muted small">{{ $t('layoutProps.dragSquaresToMoveVertices') }}</p>
      </template>
      <div v-for="(m, k) in myIssues" :key="k" class="dl-iss">⚠ {{ m }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { computed, nextTick, ref, watch } from 'vue';
import { ed } from '../store';
import { dist, isClosed, polyLen, r2 } from './geom';
import { copyLay, duplicateLay, L, LK_CN, NODE_CN, pv, removeLays, sel1, selItem, setItem as setItemS } from './state';

const ICON: Record<string, string> = { walls: 'Postcard', zones: 'Crop', aisles: 'Guide', nodes: 'Location', edges: 'Share', dims: 'Odometer' };
const s1 = sel1, it = selItem;
const nameInp = ref<any>();
const title = computed(() => (s1.value ? LK_CN[s1.value.kind] + (it.value?.name ? ' · ' + it.value.name : '') : $t('planView.layoutElementsSelected0', [pv.lsel.length])));
const sub = computed(() => s1.value?.id || '');
const icon = computed(() => (s1.value ? ICON[s1.value.kind] : 'Files'));
const setItem = (set: any) => setItemS(set);
// Use a local draft for the name field; commit on Enter / blur
const nm = ref('');
watch(() => [s1.value?.kind, s1.value?.id, it.value?.name], () => { nm.value = it.value?.name || ''; }, { immediate: true });

const closed = computed(() => !!it.value?.pts && isClosed(it.value.pts));
const vpts = computed<number[][]>(() => { const p = it.value?.pts || []; return s1.value?.kind === 'walls' && closed.value ? p.slice(0, -1) : p; });
const wrap = computed(() => s1.value?.kind === 'zones' || closed.value);
const minPts = computed(() => (wrap.value ? 3 : 2));
function segLen(i: number) {
  const p = vpts.value, n = p.length;
  if (i === n - 1 && !wrap.value) return null;
  return r2(dist(p[i], p[(i + 1) % n]));
}
const area = (p: number[][]) => Math.abs(p.reduce((t, q, i) => { const r = p[(i + 1) % p.length]; return t + q[0] * r[1] - r[0] * q[1]; }, 0)) / 2;
const edgeLen = computed(() => {
  const ns = L.value.paths?.nodes || [], a = ns.find((n: any) => n.id === it.value?.a), b = ns.find((n: any) => n.id === it.value?.b);
  return a && b ? Math.hypot(b.x - a.x, b.y - a.y) : 0;
});
/** Edit a vertex: update both endpoints of a closed wall together. */
function writePts(p: number[][]) { setItem({ pts: s1.value?.kind === 'walls' && closed.value ? [...p, [...p[0]]] : p }); }
function setPt(i: number, ax: number, x: number) { if (x === undefined || x === null) return; const p = vpts.value.map((q) => [...q]); p[i][ax] = r2(x); writePts(p); }
/** Change segment length: move the next vertex along this segment (keep other vertices fixed, like CAD "Lengthen"). */
function setSegLen(i: number, len: number) {
  if (!len || len <= 0) return;
  const p = vpts.value.map((q) => [...q]), n = p.length, j = (i + 1) % n, d = dist(p[i], p[j]);
  const u = d < 1e-9 ? [1, 0] : [(p[j][0] - p[i][0]) / d, (p[j][1] - p[i][1]) / d];
  p[j] = [r2(p[i][0] + u[0] * len), r2(p[i][1] + u[1] * len)];
  writePts(p);
}
function delPt(i: number) { const p = vpts.value.map((q) => [...q]); p.splice(i, 1); writePts(p); }
function toggleClosed(v: any) {
  const p = (it.value.pts as number[][]).map((q) => [...q]);
  if (v && !closed.value && p.length >= 3) setItem({ pts: [...p, [...p[0]]] });
  else if (!v && closed.value) setItem({ pts: p.slice(0, -1) });
}
function addDoor() {
  const p = it.value.pts as number[][]; let best = 0, s0 = 0, acc = 0;
  for (let i = 0; i < p.length - 1; i++) { const Lg = dist(p[i], p[i + 1]); if (Lg > best) { best = Lg; s0 = acc + Lg / 2; } acc += Lg; }
  const w = it.value.outer ? 4 : 1.2;
  setItem({ doors: [...(it.value.doors || []), { s: r2(s0), w: Math.min(w, Math.max(0.6, best - 0.4)) }] });
}
function setDoor(k: number, set: any) { const d = (it.value.doors || []).map((x: any) => ({ ...x })); Object.assign(d[k], set); setItem({ doors: d }); }
function delDoor(k: number) { const d = (it.value.doors || []).filter((_: any, i: number) => i !== k); setItem({ doors: d.length ? d : null }); }

const bindable = computed(() => (ed.model?.blocks || []).filter((b: any) => !['transporter', 'operators'].includes(b.type)));
function pickBlock() {
  const s = s1.value; if (!s) return;
  ed.pick = { prompt: $t('planView.clickAMachineToUse'), onPick: (bid: string) => setItemS({ block: bid }, s) };
}
const myIssues = computed(() => {
  const s = s1.value; if (!s || !['nodes', 'edges'].includes(s.kind)) return [];
  return (ed.validation?.issues || []).filter((i: any) => i.id === 'path:' + s.id).map((i: any) => i.msg);
});
// Double-click an area to focus the name field
watch(() => pv.focusName, async () => { await nextTick(); await nextTick(); const inp = nameInp.value as any; inp?.focus?.(); inp?.select?.(); });
</script>
