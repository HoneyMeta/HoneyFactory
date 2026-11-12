<template>
  <div class="v3" ref="root">
    <div ref="host" class="scene-host" :class="{ placing: !!ed.placing, picking: !!ed.pick }" @pointerdown.capture="onHostDown" @contextmenu.prevent="onCtx" @click.capture="onHostClick" @dblclick="onDbl" @drop="onDrop3" @dragover.prevent />
    <View3DHover :hit="hoverHit" :busy="hoverBusy || !!rect || tool === 'walk'" :suppress="hoverSuppress" />
    <div v-if="rect" class="v3-rect" :style="rectStyle" />
    <div v-if="layers.heat && heatMode === 'state' && bn" class="v3-bnp">
      <b>{{ $t('common.bottleneckAnalysis') }}</b><small class="muted">{{ $t('view3D.last0HoursActivePeriod', [bn.hours || 8, bn.confidence_label || '']) }}</small>
      <p>{{ bn.verdict }}</p>
      <div v-for="(it, i) in (bn.items || []).slice(0, 3)" :key="i" class="v3-bnr" @click="focusBn(it)">
        <span class="rk" :class="{ top: it.rank === 1 }">#{{ it.rank }}</span><span class="nm">{{ it.name }}{{ it.n > 1 ? ` ×${it.n}` : '' }}</span>
        <b class="mono">{{ Math.round(((it.share ?? it.active) <= 1 ? (it.share ?? it.active) * 100 : (it.share ?? it.active))) }}%</b>
      </div>
      <small v-if="(bn.excluded || []).length" class="muted" :title="bn.excluded.map((x: any) => $t('common.n01', [x.name, x.reason])).join($t('common.k344'))">{{ $t('view3D.machinesExcluded0HoverFor', [bn.excluded.length]) }}</small>
    </div>
    <div class="v3-bar" data-tour="v3-bar">
      <el-dropdown size="small" @command="viewCmd"><el-button size="small"><el-icon><Camera /></el-icon>{{ $t('view3D.view') }}</el-button>
        <template #dropdown><el-dropdown-menu><el-dropdown-item command="overview">{{ $t('view3D.overview') }}</el-dropdown-item><el-dropdown-item command="top">{{ $t('view3D.topView') }}</el-dropdown-item>
          <el-dropdown-item command="front">{{ $t('view3D.frontView') }}</el-dropdown-item><el-dropdown-item v-for="a in ed.model?.areas || []" :key="a.name" :command="'a:' + a.name">{{ a.name }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
      <el-popover placement="bottom-start" :width="230" trigger="click"><template #reference><el-button size="small"><el-icon><Files /></el-icon>{{ $t('view3D.layers') }}</el-button></template>
        <div class="v3-lay">
          <el-checkbox v-for="(n, k) in LAYERS" :key="k" v-model="layers[k]" @change="(v: any) => setLayer(k as string, v)">{{ n }}</el-checkbox>
          <template v-if="layers.heat"><div class="muted small">{{ $t('view3D.coloring') }}</div>
            <el-radio-group v-model="heatMode" size="small" @change="updHeat"><el-radio-button value="state">{{ $t('common.bottleneck') }}</el-radio-button><el-radio-button value="oee">OEE</el-radio-button><el-radio-button value="power">{{ $t('common.power2') }}</el-radio-button></el-radio-group></template>
        </div></el-popover>
      <el-button size="small" :type="layers.heat && heatMode === 'state' ? 'warning' : ''" data-tour="v3-bottleneck" @click="toggleBottleneck"><el-icon><Histogram /></el-icon>{{ $t('view3D.bottleneckAnalysis') }}</el-button>
      <el-button size="small" :type="track ? 'primary' : ''" data-tour="v3-track" @click="track ? stopTrack() : startTrack()"><el-icon><Aim /></el-icon>&nbsp;{{ track ? $t('view3D.stopFollowing') : $t('dockLists.followAPart') }}</el-button>
      <el-button-group size="small">
        <el-tooltip :content="$t('view3D.measureTheDistanceBetweenTwo')"><el-button :type="tool === 'measure' ? 'primary' : ''" @click="setTool('measure')"><el-icon><Odometer /></el-icon></el-button></el-tooltip>
        <el-tooltip :content="$t('view3D.firstPersonWalkthroughWasdTo')"><el-button :type="tool === 'walk' ? 'primary' : ''" @click="setTool('walk')"><el-icon><Avatar /></el-icon></el-button></el-tooltip>
      </el-button-group>
      <el-dropdown size="small" trigger="click" @command="camCmd"><el-button size="small"><el-icon><Camera /></el-icon>{{ $t('view3D.bookmarks') }}</el-button>
        <template #dropdown><el-dropdown-menu>
          <el-dropdown-item command="save"><el-icon><Plus /></el-icon> {{ $t('view3D.bookmarkTheCurrentView') }}</el-dropdown-item>
          <el-dropdown-item v-for="(c, i) in cams" :key="i" :command="'go:' + i" :divided="i === 0">{{ c.name }}</el-dropdown-item>
          <el-dropdown-item v-if="cams.length" command="clear" divided>{{ $t('view3D.clearBookmarks') }}</el-dropdown-item>
        </el-dropdown-menu></template></el-dropdown>
      <template v-if="editable && ed.sel.length >= 2">
        <el-dropdown size="small" trigger="click" @command="(c: string) => arrange(c, 'pos')"><el-button size="small">{{ $t('view3D.align') }}</el-button>
          <template #dropdown><el-dropdown-menu><el-dropdown-item v-for="a in ALIGN" :key="a[0]" :command="a[0]">{{ a[1] }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
      </template>
      <el-popover v-if="editable && ed.sel.length" placement="bottom" :width="230" trigger="click">
        <template #reference><el-button size="small">{{ $t('view3D.array') }}</el-button></template>
        <div class="rt-pop">
          <div class="row"><span>{{ $t('view3D.copies') }}</span><el-input-number v-model="arr.n" size="small" :min="1" :max="20" style="width:90px" /></div>
          <div class="row"><span>{{ $t('view3D.xSpacing') }}</span><el-input-number v-model="arr.dx" size="small" :step="0.5" :controls="false" style="width:80px" /><span>m</span></div>
          <div class="row"><span>{{ $t('view3D.ySpacing') }}</span><el-input-number v-model="arr.dy" size="small" :step="0.5" :controls="false" style="width:80px" /><span>m</span></div>
          <el-button size="small" type="primary" @click="doArray">{{ $t('view3D.create0Copies', [arr.n]) }}</el-button>
          <p class="muted small">{{ $t('view3D.alsoCopyConnectionsBetweenThe') }}</p>
        </div>
      </el-popover>
      <span class="grow" />
      <span v-if="tool === 'walk'" class="v3-tip">{{ $t('view3D.walkthroughActiveWasdToMove') }}</span>
      <span v-else-if="tool === 'measure'" class="v3-tip">{{ $t('view3D.clickTwoPointsOnThe', [mA && mB ? $t('common.k546') + Math.hypot(mB[0] - mA[0], mB[1] - mA[1]).toFixed(2) + ' m' : '']) }}</span>
      <span v-else-if="editable" class="v3-tip">{{ $t('view3D.clickEquipmentAndDragThe') }}</span>
      <el-tooltip :content="$t('view3D.screenshot')"><el-button size="small" text @click="shot"><el-icon><Picture /></el-icon></el-button></el-tooltip>
      <el-tooltip :content="$t('view3D.fullScreen')"><el-button size="small" text @click="fullscreen"><el-icon><FullScreen /></el-icon></el-button></el-tooltip>
    </div>
    <div v-if="layers.heat && heatMode === 'state'" class="v3-legend">
      <span v-for="(c, k) in STATE_COLOR" :key="k"><i :style="{ background: c }" />{{ STATE_CN[k] }}</span>
    </div>
    <div v-if="track" class="v3-track">
      <div class="tb-head"><b class="mono">◎ {{ track.id }}</b><span class="grow">{{ track.where }}<span v-if="track.moving" class="mv"> {{ $t('view3D.moving') }}</span></span>
        <el-checkbox v-model="follow" size="small" @change="(v: any) => scene?.setFollow(v)">{{ $t('view3D.followView') }}</el-checkbox>
        <el-button size="small" @click="ed.partReq = { id: track.id, n: Date.now() }">{{ $t('view3D.partRecord') }}</el-button><el-button size="small" @click="startTrack()">{{ $t('view3D.followAnotherPart') }}</el-button>
        <el-button size="small" text @click="stopTrack">×</el-button></div>
      <div class="tb-steps"><template v-for="(s, i) in meta?.route || []" :key="i"><span :class="i < track.idx ? 'done' : i === track.idx ? 'cur' : ''">{{ s.name }}</span><i v-if="i < meta.route.length - 1">›</i></template></div>
    </div>
    <div v-if="loading" class="v3-load muted">{{ $t('view3D.loading3dScene') }}</div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, shallowRef, watch } from 'vue';
import { get, P } from '../api';
import { FactoryScene } from '../scene';
import { panelById, registerSceneExtensions } from './shell/panels';
import View3DHover from './View3DHover.vue';
import { ElMessageBox } from 'element-plus';
import { Box3, Vector3 } from 'three';
import { ctxTools, openBlockMenu, openPaneMenu } from './shell/contextMenu';
import { bpMark, watchRows } from './shell/graphdebug';
import { layerOf, layerVisible, relatedSet } from './shell/relations';
import { placeAt, placeBlock } from './shell/place';
import { arrange, blocksById, cloneOps, ed, exec, flash, mode, openFloat, select, snapNeighbors, STATE_CN, STATE_COLOR, viewState } from './store';

const root = ref<HTMLElement>(), host = ref<HTMLElement>();
const scene = shallowRef<FactoryScene | null>(null);
const loading = ref(true), meta = ref<any>(null);
const LAYERS: Record<string, string> = { labels: $t('view3D.equipmentLabels'), kpi: $t('view3D.showOeePartCountIn'), flow: $t('view3D.processFlowLines'), layout: $t('view3D.wallsAreasAislesRoadNetwork'), transfer: $t('view3D.materialTransportAutomatic'), people: $t('view3D.people'), agv: $t('view3D.agvsStations'), heat: $t('view3D.heatmapColoring') };
const layers = reactive<Record<string, boolean>>({ labels: true, kpi: false, flow: true, layout: true, transfer: true, people: true, agv: true, heat: false });
const heatMode = ref('state');
const track = ref<any>(null), follow = ref(true);
const KIND: Record<string, string> = { induction_furnace: 'furnace', sand_system: 'sand', molding_line: 'molding', cooling_line: 'cooling', shot_blast: 'shotblast',
  deburr_cell: 'deburr', agv_fleet: 'agv', worker_crew: 'crew' };
const editable = computed(() => ['paused', 'edit'].includes(mode.value));
let timer: any = null, timers: any[] = [];

const elevOf = (b: any) => ((ed.model?.plant?.layout?.floors || []).find((f: any) => f.id === b.floor)?.z || 0);
/** Running layout + draft: use draft positions, dimensions, and names; also render blocks added in the draft. */
function merged() {
  const by = blocksById.value, have = new Set<string>();
  const stations = meta.value.stations.filter((s: any) => by[s.id] || s.kind === 'crew').map((s: any) => {
    const b = by[s.id]; have.add(s.id);
    return b ? { ...s, pos: b.pos, size: b.size, rot: b.rot || 0, name: b.name, elev: elevOf(b) } : s;
  });
  for (const b of ed.model.blocks) {
    if (have.has(b.id)) continue;
    const kind = KIND[b.type] || b.type;
    if (kind === 'agv' || kind === 'crew') continue;
    stations.push({ id: b.id, name: b.name, kind, type: b.type, pos: b.pos, size: b.size, rot: b.rot || 0, cfg: b.type === 'cell' ? { cell: b.params?.cell } : {}, elev: elevOf(b) });
  }
  return { ...meta.value, stations, areas: ed.model.areas || meta.value.areas };
}
async function build() {
  scene.value?.dispose();
  meta.value = await get(P(ed.pid) + '/meta');
  const s = new FactoryScene(host.value!);
  registerSceneExtensions(s);
  scene.value = s;
  await s.build(merged());
  s.onPick = (id) => select([id]);
  s.onEditPick = (id) => (id ? select([id]) : (ed.sel = []));
  s.onMoved = (id, pos, rot) => { if (blocksById.value[id]) exec([{ op: 'update_block', id, set: { pos: snapNeighbors(id, pos), rot } }], $t('view3D.moveIn3d')); };
  for (const [k, v] of Object.entries(layers)) s.setLayer(k, v);
  s.setEdit(editable.value);
  if (viewState.value) s.setState(viewState.value);
  s.setLayout(ed.model?.plant?.layout, ed.model?.plant?.layout?.floors || []);
  const hv = (s as any).hover;
  if (hv) { hv.onHover = onSceneHover; hv.onBusy = (b: boolean) => { hoverBusy.value = b; }; hoverMode(); applySel(); applyHover(); }
  // Restore the last camera view (otherwise auto-frame the entire factory)
  try { const c = JSON.parse(localStorage.getItem('vf_cam_' + ed.pid) || 'null'); if (c?.pos && c?.target) { s.setCam(c); s.autoView = false; } } catch { /* */ }
  loading.value = false;
}
function setLayer(k: string, v: boolean) { layers[k] = v; scene.value?.setLayer(k, v); if (k === 'heat' && v) updHeat(); }
function toggleBottleneck() {
  const on = !(layers.heat && heatMode.value === 'state');
  heatMode.value = 'state'; setLayer('heat', on);
}
const HEAT_STATE: Record<string, number | null> = { Executing: 0, Setup: 0.35, Idle: 0.5, Starved: 0.55, Blocked: 0.8, Stopped: 1, Planned: null };
function focusBn(it: any) { const id = (it.ids || [])[0]; if (id && blocksById.value[id]) { select(it.ids.filter((x: string) => blocksById.value[x])); scene.value?.focusClose(id); } }
// Bottleneck analysis: use the analysis API's active period method (last 8 hours, excluding warm-up); color by utilization, outline the top 3 in red, and show rank labels
const bn = ref<any>(null); let bnAt = 0;
async function loadBn() {
  if (Date.now() - bnAt < 30000 && bn.value) return;
  bnAt = Date.now();
  bn.value = await get(P(ed.pid) + '/analysis/bottleneck?hours=8&warmup=1', true).catch(() => null);
}
async function updHeat() {
  const st = viewState.value; if (!layers.heat || !st) return;
  const vals: Record<string, number | null> = {}, ranks: Record<string, string> = {};
  if (heatMode.value === 'state') {
    await loadBn();
    const by = bn.value?.by_station || {};
    for (const s of st.stations) { const x = by[s.id]; vals[s.id] = x ? (x.util ?? null) : (HEAT_STATE[s.state] ?? 0.5); }
    for (const [id, x] of Object.entries(by) as any) {
      if (x.rank && x.rank <= 3) { const sh = x.share ?? x.util ?? 0; ranks[id] = $t('view3D.bottleneck012', [x.rank, x.tie ? $t('bottleneckPanel.tie2') : '', Math.round((sh <= 1 ? sh * 100 : sh))]); }
    }
  } else {
    const maxP = Math.max(1, ...st.stations.map((s: any) => s.power || 0));
    for (const s of st.stations) vals[s.id] = heatMode.value === 'oee' ? (s.oee ? 1 - s.oee.OEE : null) : (s.power || 0) / maxP;
  }
  scene.value?.setHeat(vals, ranks);
}
function viewCmd(c: string) { c.startsWith('a:') ? scene.value?.viewPreset('area', (ed.model.areas || []).find((a: any) => a.name === c.slice(2))) : scene.value?.viewPreset(c); }
function shot() { const a = document.createElement('a'); a.href = scene.value!.snapshot(); a.download = `${ed.pid}-${(viewState.value?.time || '').replace(/[: ]/g, '')}.png`; a.click(); }
function fullscreen() { document.fullscreenElement ? document.exitFullscreen() : root.value?.requestFullscreen(); }

// ---------- Follow a Part ----------
async function startTrack(id?: string) {
  if (!id) id = (await get(P(ed.pid) + '/track/suggest')).id;
  if (!id) { ElMessage.warning($t('view3D.noWipIsCurrentlyAvailable')); return; }
  track.value = { id, idx: -1, first: true, where: $t('view3D.locating') };
  if (!layers.flow) setLayer('flow', true);
  await nextTick(); pollTrack();
}
function stopTrack() { track.value = null; scene.value?.setTrack(null); scene.value?.setFollow(false); scene.value?.setStep(-1); }
async function pollTrack() {
  const t = track.value; if (!t || ed.replay) return;
  const loc = await get(`${P(ed.pid)}/track/${t.id}`, true).catch(() => null); if (!loc || track.value !== t) return;
  const route = meta.value?.route || [];
  let idx = route.findIndex((s: any) => (s.ids || []).includes(loc.station));
  const m = /(\d+)%/.exec(loc.where || '');
  if (route[idx]?.kind === 'cooling' && m && Number(m[1]) >= 60) idx += 1;
  if (['FG', 'SHIPPED'].includes(loc.status) && !loc.agv) idx = route.length - 1;
  if (idx < 0 || loc.agv) idx = t.idx;
  Object.assign(t, { idx, where: loc.where, moving: loc.moving });
  scene.value?.setStep(idx);
  scene.value?.setTrack(loc.pos ? loc : null, `<b>${t.id}</b><br>${loc.where}`);
  if (t.first && loc.pos) { t.first = false; scene.value?.setFollow(follow.value); }
}


// ---------- Tools: distance measurement, walkthrough, box selection, context menu, bookmarks, array ----------
const ALIGN: [string, string][] = [['left', $t('common.alignLeft')], ['right', $t('planView.alignRight')], ['top', $t('planView.alignTop')], ['bottom', $t('planView.alignBottom')], ['hcenter', $t('planView.alignVerticalCenters')], ['vcenter', $t('planView.alignHorizontalCenters')], ['hdist', $t('view3D.distributeHorizontally')], ['vdist', $t('view3D.distributeVertically')]];
const tool = ref(''), mA = ref<number[] | null>(null), mB = ref<number[] | null>(null);
function setTool(t: string) {
  tool.value = tool.value === t ? '' : t;
  scene.value?.setWalk(tool.value === 'walk');
  if (tool.value !== 'measure') { mA.value = mB.value = null; scene.value?.showMeasure(null, null); }
  // 4.6: "Cancel Measurement" is the first context menu item while measuring.
  ctxTools.measure['3d'] = tool.value === 'measure' ? () => { if (tool.value === 'measure') setTool('measure'); } : null;
}
const rect = ref<any>(null);
const rectStyle = computed(() => { const r = rect.value, h = host.value!.getBoundingClientRect(); return { left: Math.min(r.x0, r.x1) - h.left + 'px', top: Math.min(r.y0, r.y1) - h.top + 'px', width: Math.abs(r.x1 - r.x0) + 'px', height: Math.abs(r.y1 - r.y0) + 'px' }; });
function onHostDown(e: PointerEvent) {
  if (e.button !== 0) return;
  if (tool.value === 'measure') {
    const g = scene.value?.groundAt(e); if (!g) return;
    if (!mA.value || mB.value) { mA.value = g; mB.value = null; } else mB.value = g;
    scene.value?.showMeasure(mA.value, mB.value); e.stopPropagation(); return;
  }
  if (e.shiftKey && tool.value === '') {
    e.stopPropagation(); e.preventDefault();
    rect.value = { x0: e.clientX, y0: e.clientY, x1: e.clientX, y1: e.clientY };
    const mv = (ev: PointerEvent) => { rect.value.x1 = ev.clientX; rect.value.y1 = ev.clientY; };
    const up = () => {
      removeEventListener('pointermove', mv); removeEventListener('pointerup', up);
      const r = rect.value; rect.value = null;
      if (Math.abs(r.x1 - r.x0) > 4 || Math.abs(r.y1 - r.y0) > 4) select((scene.value?.idsInRect(r.x0, r.y0, r.x1, r.y1) || []).filter((id) => blocksById.value[id]), true);
    };
    addEventListener('pointermove', mv); addEventListener('pointerup', up);
  }
}
function onHostClick(e: MouseEvent) {
  if (ed.pick) { e.stopPropagation(); const id = scene.value?.pickId(e); if (id && blocksById.value[id]) { const pk = ed.pick; ed.pick = null; pk.onPick(id); } return; }
  if (ed.placing) { e.stopPropagation(); const g = scene.value?.groundAt(e); if (g) placeAt(e, { pos: g }); return; }
  if (tool.value === 'measure') e.stopPropagation();
}
/** Drop library assets into 3D at the ground position under the pointer. */
function onDrop3(e: DragEvent) {
  const type = e.dataTransfer?.getData('vf/type'); if (!type) return;
  const g = scene.value?.groundAt(e as any); if (g) placeBlock(type, { pos: g });
}
// Right-click: equipment → shared equipment menu (breakpoints, watches, failures); ground → camera views, distance measurement, etc.
function onCtx(e: MouseEvent) {
  const id = scene.value?.pickId(e);
  if (id) hoverSuppress.value = id;            // Hide the hover card while the context menu is open
  if (id && blocksById.value[id]) {
    if (!ed.sel.includes(id)) select([id]);
    openBlockMenu(e, id, '3d', []);
    return;
  }
  const g = scene.value?.groundAt(e);
  openPaneMenu(e, [
    { label: $t('view3D.view2'), children: [{ label: $t('view3D.overview'), run: () => viewCmd('overview') }, { label: $t('view3D.topView'), run: () => viewCmd('top') }, { label: $t('view3D.frontView'), run: () => viewCmd('front') }] },
    ...(tool.value === 'measure' ? [] : [{ label: $t('common.measureDistance'), run: () => setTool('measure') }]), { label: $t('view3D.firstPersonWalkthrough'), run: () => setTool('walk') },
  ], g ? { pos: g } : undefined);
}
const cams = computed<any[]>(() => ed.model?.plant?.cameras || []);
async function camCmd(c: string) {
  if (c === 'save') {
    const { value } = await ElMessageBox.prompt($t('view3D.bookmarkName'), $t('view3D.saveView'), { inputValue: $t('view3D.view0', [cams.value.length + 1]) }).catch(() => ({ value: null as any }));
    if (!value) return;
    exec([{ op: 'update_plant', set: { 'plant.cameras': [...cams.value, { name: value, ...scene.value!.getCam() }] } }], $t('view3D.saveViewBookmark'));
  } else if (c === 'clear') exec([{ op: 'update_plant', set: { 'plant.cameras': null } }], $t('view3D.clearViewBookmarks'));
  else if (c.startsWith('go:')) { if (tool.value === 'walk') setTool('walk'); scene.value?.setCam(cams.value[+c.slice(3)]); }
}
const arr = reactive({ n: 2, dx: 6, dy: 0 });
function doArray() {
  const bs = ed.sel.map((id: string) => blocksById.value[id]).filter(Boolean); if (!bs.length) return;
  const ids = new Set(bs.map((b: any) => b.id));
  const links = (ed.model.links || []).filter((l: any) => ids.has(l.from) && ids.has(l.to));
  const newIds: string[] = [], depth = ed.undo.length;
  for (let k = 1; k <= arr.n; k++) {   // Execute each copy in sequence (IDs avoid previously generated ones), then merge the undo steps into one
    const { ops, ids: nid } = cloneOps(bs, links, [arr.dx * k, arr.dy * k], [arr.dx * 40 * k, arr.dy * 40 * k + (arr.dx ? 0 : 150 * k)]);
    exec(ops, ''); newIds.push(...nid);
  }
  const steps = ed.undo.splice(depth);
  ed.undo.push({ ops: steps.flatMap((h: any) => h.ops), inv: [...steps].reverse().flatMap((h: any) => h.inv), label: $t('view3D.arrayCopy0Copies', [arr.n]) });
  select(newIds); flash(newIds);
}
function onEsc(e: KeyboardEvent) { if (e.key === 'Escape' && tool.value) setTool(tool.value); }

function onKey(e: KeyboardEvent) {
  if (ed.view !== '3d' || !editable.value || (e.target as HTMLElement).closest('input:not([type=radio]):not([type=checkbox]),textarea')) return;
  if ((e.key === 'r' || e.key === 'R') && !e.ctrlKey) scene.value?.rotateSelected(e.shiftKey ? -90 : 90);
}

// ---------- Hover (4.4): outline + info card + cross-view sync (ed.hoverId); double-click to open equipment / PLC programming ----------
const hoverHit = shallowRef<any>(null), hoverBusy = ref(false), hoverSuppress = ref('');
let myHover = '';
const hv = () => (scene.value as any)?.hover;
function onSceneHover(h: any) {
  hoverHit.value = h;
  if (!h || h.id !== hoverSuppress.value) hoverSuppress.value = '';
  const id = h?.id || '';
  if (id) { if (ed.hoverId !== id) ed.hoverId = id; } else if (myHover && ed.hoverId === myHover) ed.hoverId = '';
  myHover = id;
  applyHover();
}
/** Outline the hovered object in light blue and related objects (its PLC, PLC-controlled equipment, upstream/downstream objects, network path) faintly; also sync outlines with hover in other views. */
function applyHover() {
  const x = hv(); if (!x) return;
  const id = ed.hoverId, h = hoverHit.value;
  if (!id) { x.set('hov', []); x.set('rel', []); return; }
  x.set('hov', [id], h && h.id === id ? [h.obj] : undefined);
  const skip = new Set(['agv_fleet', 'worker_crew']);
  x.set('rel', blocksById.value[id] ? [...relatedSet(id).ids].filter((r) => r !== id && blocksById.value[r] && !skip.has(blocksById.value[r].type)).slice(0, 40) : []);
}
function applySel() { hv()?.set('sel', ed.sel.filter((id: string) => blocksById.value[id]).slice(0, 40)); }
function hoverMode() { hv()?.setMode(tool.value || ed.placing ? 'off' : ed.pick ? 'pick' : 'on'); }
watch(() => ed.hoverId, applyHover);
watch(() => ed.sel, applySel);
watch(() => [tool.value, !!ed.placing, !!ed.pick], hoverMode);
function onDbl(e: MouseEvent) {
  const s: any = scene.value; if (!s?.hover || tool.value || ed.placing || ed.pick) return;
  if (s.cellPanelAt?.(e)) return;                              // Double-clicked an operator panel button
  const h = s.hover.hitAt(e.clientX, e.clientY); const b = h && blocksById.value[h.id]; if (!b) return;
  hoverSuppress.value = h.id;
  if (b.type === 'plc') {                                      // PLC → program
    const p = panelById('plc-editor-float');
    if (p) openFloat(p as any, { bid: h.id }, h.id); else window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor' } }));
  } else if (!h.agv && !h.worker && (b.type === 'cell' || layerOf(h.id) === 'process') && !['agv_fleet', 'worker_crew', 'transporter', 'operators'].includes(b.type)) {
    ed.interior = h.id;                                        // Control unit / equipment → equipment internals
    window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'cell-editor' } }));
  } else {                                                     // Gateway, MES, AGV, workers, etc.: zoom in
    s.focusObject(h.obj);
  }
}

// SOP walkthrough (the design workspace SOP panel writes ed.sop): move the camera on each step; use the saved view if available, otherwise aim at the target equipment
function followSop() {
  const st = ed.sop?.step; if (!st || !scene.value) return;
  const c = st.camera || {};
  if ((c.mode === 'walk') !== (tool.value === 'walk')) setTool('walk');   // Keep in sync with the toolbar walkthrough button
  if (c.pos && c.look) scene.value.goCam(c);
  else if (st.target?.block) { if (c.mode === 'walk') scene.value.setWalk(true); else { scene.value.setWalk(false); scene.value.focusClose(st.target.block); } }
}
watch(() => ed.sop?.n, followSop);
// Breakpoint / watch markers in the view (red dots and values on labels)
watch(() => [ed.bps, ed.watchVals, ed.watches], () => {
  if (!scene.value) return;
  const m: Record<string, any> = {};
  for (const b of ed.model?.blocks || []) { const bp = bpMark(b.id), w = watchRows(b.id); if (bp || w.length) m[b.id] = { bp, w: w.map((x) => x[0] + ' ' + x[1]).join(' · ') }; }
  scene.value.marks = m;
}, { deep: true });
/** Equipment bounding box in screen coordinates (for AI Tutor "Look here" and guided-tour spotlights in 3D); return null if off-screen. */
function rect3d(id: string): DOMRect | null {
  const sc: any = scene.value, it = sc?.items?.get(id);
  if (!sc || !it?.group || !it.group.visible) return null;
  const bx = new Box3().setFromObject(it.group);
  if (bx.isEmpty()) return null;
  const r = sc.renderer.domElement.getBoundingClientRect();
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity, front = 0;
  for (const x of [bx.min.x, bx.max.x]) for (const y of [bx.min.y, bx.max.y]) for (const z of [bx.min.z, bx.max.z]) {
    const v = new Vector3(x, y, z).project(sc.camera);
    if (v.z < 1) front++;
    const sx = r.left + ((v.x + 1) / 2) * r.width, sy = r.top + ((1 - v.y) / 2) * r.height;
    x0 = Math.min(x0, sx); y0 = Math.min(y0, sy); x1 = Math.max(x1, sx); y1 = Math.max(y1, sy);
  }
  if (!front || x1 < r.left || x0 > r.right || y1 < r.top || y0 > r.bottom) return null;
  return new DOMRect(x0, y0, x1 - x0, y1 - y0);
}
onMounted(async () => {
  (window as any).__vf3dRect = rect3d;
  await build();
  // For SOPs and reports: current camera view and screenshot
  ed.capture = () => scene.value?.snapshot();
  timers = [setInterval(pollTrack, 800), setInterval(updHeat, 2000), setInterval(() => { if (scene.value) ed.camera = scene.value.viewCam(); }, 600)];
  followSop();
  addEventListener('keydown', onKey); addEventListener('keydown', onEsc);
});
watch(viewState, (r) => scene.value?.setState(r));
watch(editable, (v) => scene.value?.setEdit(v));
// Layer filtering (4.3): hide equipment on hidden layers
function applyFilter() { const sc: any = scene.value; if (!sc?.items) return; for (const [id, it] of sc.items) if (it.group && it.s?.kind !== 'agv' && it.s?.kind !== 'crew') it.group.visible = layerVisible(id); }
watch(() => [ed.filter, ed.model?.blocks?.length, meta.value], () => nextTick(applyFilter), { deep: true });
watch(() => ed.model?.blocks, () => {
  clearTimeout(timer);
  timer = setTimeout(() => { if (scene.value && meta.value) { scene.value.sync(merged()); applySel(); } }, 300);   // Redraw the selection box when dimensions change
}, { deep: true });
watch(() => ed.sel, (s) => { if (scene.value) scene.value.selected = s[0] || ''; });
watch(() => ed.focusReq, (r) => { if (r?.id && ed.view === '3d') { const s: any = scene.value; s?.frameItem ? s.frameItem(r.id) : s?.focusClose(r.id); } else if (r && !r.id && ed.view === '3d') scene.value?.viewPreset('overview'); });
watch(() => ed.trackReq, (r) => { if (r?.id) startTrack(r.id); });
watch(() => ed.model?.plant?.layout, (L) => scene.value?.setLayout(L, L?.floors || []), { deep: true });
watch(() => ed.rebuild3d, () => build());
function saveCam() { try { if (scene.value && !scene.value.autoView && !scene.value.walk?.on) localStorage.setItem('vf_cam_' + ed.pid, JSON.stringify(scene.value.getCam())); } catch { /* */ } }
addEventListener('beforeunload', saveCam);
onUnmounted(() => { if ((window as any).__vf3dRect === rect3d) delete (window as any).__vf3dRect; ctxTools.measure['3d'] = null; if (myHover && ed.hoverId === myHover) ed.hoverId = ''; saveCam(); removeEventListener('beforeunload', saveCam); ed.capture = null; ed.camera = null; clearTimeout(timer); timers.forEach(clearInterval); removeEventListener('keydown', onKey); removeEventListener('keydown', onEsc); scene.value?.setWalk(false); scene.value?.dispose(); });
defineExpose({ setLayer });
</script>
