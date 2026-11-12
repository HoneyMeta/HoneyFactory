<template>
  <!-- Architecture (4.3, fourth view): layered swimlanes, top to bottom: information systems → communications → control → production equipment (expandable sensors/actuators).
       Draw network cables (purple) and signal wires (orange dashed; bundle equipment ⇄ PLC signals, label "N channels", click to inspect each channel). Drag cards to arrange manually (stored in each block's arch: [x, y within swimlane]). -->
  <div class="av" ref="host" :class="{ placing: !!ed.placing, picking: !!ed.pick }">
    <div class="av-bar">
      <b class="av-title">{{ $t('archView.architecture') }}</b>
      <span class="muted small">{{ counts }}</span>
      <span class="grow" />
      <el-checkbox v-model="onlyCtl" size="small" data-tour="av-only" @change="saveOnly">{{ $t('archView.showOnlyEquipmentConnectedTo') }}</el-checkbox>
      <el-tooltip :content="$t('archView.clearManualPositionsAndAuto')"><el-button size="small" data-tour="av-auto" @click="autoAll"><el-icon><MagicStick /></el-icon> {{ $t('archView.autoLayout') }}</el-button></el-tooltip>
      <el-button size="small" @click="fit"><el-icon><FullScreen /></el-icon> {{ $t('common.fitAll') }}</el-button>
    </div>
    <div class="av-main" ref="mainEl" data-tour="av-canvas">
      <svg ref="svg" class="av-svg" :class="{ connecting: !!conn }" @wheel.prevent="onWheel" @mousedown="onDown" @mousemove="onMove" @mouseup="onUp" @mouseleave="onLeave" @contextmenu.prevent="onCtx" @dblclick="onDbl">
        <defs>
          <marker id="avarr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto"><path d="M0,0 L10,5 L0,10 z" class="av-arr" /></marker>
        </defs>
        <g :transform="`translate(${v.tx},${v.ty}) scale(${v.k})`">
          <!-- Swimlanes -->
          <g v-for="ln in lanes" :key="ln.key" :class="['av-lane', 'ly-' + ln.key]" :data-lane="ln.key">
            <rect :x="0" :y="ln.y" :width="width" :height="ln.h" class="av-lane-bg" :style="{ fill: lc(ln.key) }" />
            <line :x1="0" :y1="ln.y + ln.h" :x2="width" :y2="ln.y + ln.h" class="av-lane-sep" />
            <rect :x="0" :y="ln.y" width="6" :height="ln.h" :style="{ fill: lc(ln.key) }" />
            <text :x="18" :y="ln.y + 24" class="av-lane-t">{{ ln.label }}</text>
            <text :x="18" :y="ln.y + 42" class="av-lane-n">{{ $t('common.n02', [ln.count]) }}</text>
            <g v-if="ln.adds.length" :transform="`translate(18,${ln.y + 54})`" class="av-add" :data-add="ln.key"><title>{{ $t('archView.addEquipmentToThisLayer') }}</title>
              <rect width="58" height="22" rx="11" /><text x="29" y="15">{{ $t('archView.add') }}</text></g>
            <text v-for="a in ln.areas" :key="a.name" :x="a.x" :y="ln.y + 13" class="av-area">{{ a.name }}</text>
          </g>
          <!-- Material flow (faint), network cables, signal wires -->
          <g :class="{ hov: !!hoverRel }">
            <g v-for="m in matLines" :key="m.id" :class="['av-mw', relCls([m.id]), { sel: ed.selLink === m.id }]" :data-link="m.id" :data-a="m.a" :data-b="m.b">
              <path :d="m.d" class="av-mat" marker-end="url(#avarr)" /><path :d="m.d" class="av-wh" /><title>{{ m.title }}</title></g>
            <g v-for="w in wires" :key="w.key" :class="['av-w', 'av-' + w.kind, relCls(w.ids), { sel: w.ids.includes(ed.selLink), bad: !!w.fault }]" :data-link="w.ids[0]" :data-a="w.a" :data-b="w.b">
              <path :d="w.d" class="av-wl" /><path :d="w.d" class="av-wh" />
              <g v-if="w.label && wireLabels[w.key]" :transform="`translate(${wireLabels[w.key][0]},${wireLabels[w.key][1]})`" class="av-tag" :data-bundle="w.key">
                <rect :x="-w.label.length * 3.7 - 7" y="-9" :width="w.label.length * 7.4 + 14" height="18" rx="9" /><text y="4">{{ w.label }}</text>
                <title>{{ w.kind === 'signal' ? $t('archView.clickToExpandOrCollapse') : w.title }}</title></g>
              <title>{{ w.title }}</title>
            </g>
            <path v-if="conn" :d="conn.d" :class="['av-conn', conn.kind || (conn.over ? 'bad' : '')]" />
          </g>
          <!-- Cards -->
          <g v-for="n in nodes" :key="n.id" :transform="`translate(${n.x},${n.y})`" :data-id="n.id"
            :class="['av-n', 'ly-' + n.layer, relCls([], n.id), connCls(n.id), { sel: isSel(n.id), hl: ed.highlight.includes(n.id), err: !!issue[n.id] }]">
            <rect :width="n.w" :height="n.h" rx="8" class="av-nb" />
            <rect width="5" :height="n.h" rx="2" :style="{ fill: lc(n.layer) }" />
            <g v-if="n.layer === 'process'" :transform="`translate(12,10)`"><component :is="n.icon" width="22" height="22" class="av-ico" :style="{ color: n.color }" /></g>
            <g v-else transform="translate(26,24) scale(0.62)"><LayerSymbol :type="n.type" :color="lc(n.layer)" :state="plcState(n.id)" /></g>
            <text x="44" y="21" class="av-nm">{{ n.name }}</text>
            <text x="44" y="37" class="av-sub">{{ n.sub }}</text>
            <g v-if="n.badge" :transform="`translate(${n.w - 8},10)`" :class="['av-badge', n.badge.cls]">
              <rect :x="-n.badge.w" y="0" :width="n.badge.w" height="16" rx="8" /><text :x="-n.badge.w / 2" y="12">{{ n.badge.text }}</text></g>
            <circle v-if="rtById[n.id] && ed.overlay && n.layer === 'process'" :cx="n.w - 12" cy="38" r="4.5" :style="{ fill: STATE_COLOR[rtById[n.id].state] || '#888' }"><title>{{ rtById[n.id].state }}</title></circle>
            <g v-if="n.type === 'plc'" :transform="`translate(${n.w - 52},28)`" class="av-btn" :data-prog="n.id"><title>{{ $t('common.openPlcProgram') }}</title>
              <rect width="44" height="17" rx="8.5" /><text x="22" y="12.5">{{ $t('common.program') }}</text></g>
            <g v-if="n.points.length" :transform="`translate(${n.w - 30},${n.layer === 'process' ? 30 : 8})`" class="av-btn av-fx" :data-field="n.id"><title>{{ $t('archView.sensorsActuators0Channels', [n.points.length]) }}</title>
              <rect width="22" height="15" rx="7.5" /><text x="11" y="11">{{ field[n.id] ? '▴' : '▾' }}</text></g>
            <g v-if="field[n.id]" :transform="`translate(10,${BASE_H + 4})`" class="av-field">
              <g v-for="(p, i) in n.points" :key="i" :transform="`translate(${(i % 2) * ((n.w - 20) / 2)},${Math.floor(i / 2) * 18})`">
                <rect :width="(n.w - 26) / 2" height="15" rx="4" :class="p.dir" /><text x="5" y="11.5">{{ p.dir === 'out' ? '◀' : '▶' }} {{ p.point }}</text><title>{{ p.point }} · {{ p.ch }} · {{ p.plc }}</title></g>
            </g>
            <title>{{ $t('archView.n0123', [n.name, n.typeLabel, n.id, n.status ? '\n' + n.status : '']) }}</title>
          </g>
          <!-- Connection points: appear at each edge midpoint on card hover; drag to another card to connect (as in Floor Plan and flowchart views). -->
          <g v-if="portsOf" class="av-ports" :data-hov="portsOf.id">
            <circle v-for="q in portsOf.pts" :key="q.s" :cx="q.p[0]" :cy="q.p[1]" r="5.5" class="av-port" :data-port="portsOf.id + ':' + q.s">
              <title>{{ $t('archView.dragOntoAnotherDeviceTo') }}</title></circle>
          </g>
          <g v-if="conn && conn.tip" :transform="`translate(${conn.b[0]},${conn.b[1]})`" :class="['av-conn-tip', conn.kind ? '' : 'bad']">
            <rect x="10" y="8" :width="conn.tip.length * 12 + 12" height="20" rx="10" /><text x="16" y="22">{{ conn.tip }}</text></g>
          <!-- Render expanded signal bundles on top so cards do not obscure them. -->
          <template v-for="w in wires" :key="'s' + w.key">
            <g v-if="w.kind === 'signal' && open[w.key]" :transform="`translate(${(wireLabels[w.key] || w.m)[0] + 22},${(wireLabels[w.key] || w.m)[1] - 10})`" class="av-sigs">
              <rect :width="210" :height="w.sigs.length * 17 + 10" rx="6" />
              <text v-for="(s, i) in w.sigs" :key="i" x="8" :y="18 + i * 17" :class="s.dir"><tspan class="mono">{{ s.ch || '—' }}</tspan> {{ s.dir === 'out' ? '→' : '←' }} {{ s.point }} <tspan class="av-sd">{{ s.dev }}</tspan></text>
            </g>
          </template>
        </g>
      </svg>
      <div v-if="!nodes.length" class="av-empty">
        <b>{{ $t('archView.noControlOrNetworkDevices') }}</b>
        <p class="muted">{{ $t('archView.clickAddInTheControl') }}</p>
      </div>
    </div>
    <div class="av-foot mono">
      {{ $t('archView.zoom0ClickToSelect', [(v.k * 100).toFixed(0)]) }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { openBlockMenu, openCtx, openLinkMenu, openPaneMenu } from './shell/contextMenu';
import { panelById } from './shell/panels';
import { layerOf, layerVisible, linkKind, linkVisible, loadFilter, relatedSet } from './shell/relations';
import { addNetwork, addPlcControl } from './shell/wiring';
import { areaOf, blocksById, ed, exec, flash, makeBlock, openFloat, rtById, select, STATE_COLOR, typeOf, type Op } from './store';
import LayerSymbol from './plan/LayerSymbol.vue';
import { linkFault, nodeStatus, PLC_CN, plcState, useLive } from './plan/live';
import { CONN_CN, connectBlocks, connKind } from './plan/connect';
import { elbow, labelAt, pathD, placeLabels, routeAll, shift, type End, type Rect } from './plan/route';
import { canEdit } from '../api';

const host = ref<HTMLElement>(), svg = ref<SVGSVGElement>(), mainEl = ref<HTMLElement>();
const LANES = [{ key: 'it', label: $t('archView.informationSystems') }, { key: 'network', label: $t('archView.communications') }, { key: 'control', label: $t('archView.control') }, { key: 'process', label: $t('archView.productionEquipment') }];
const ADDS: Record<string, [string, string][]> = { it: [['mes', $t('archView.mesSystem')], ['scada', $t('archView.scadaStation')]], network: [['switch', $t('archView.switch')], ['gateway', $t('archView.industrialGateway')]],
  control: [['plc', 'PLC'], ['hmi', $t('archView.hmiTouchscreen')]], process: [] };
const PROTO_CN: Record<string, string> = { profinet: 'PROFINET', modbus_tcp: 'Modbus TCP', modbus: 'Modbus TCP', s7: 'S7', opcua: 'OPC UA', mqtt: 'MQTT', ethernet: $t('archView.ethernet') };
const X0 = 150, BASE_H = 50, GX = 34, GY = 22, TOP = 22, ROW = 66;   // GX / GY: gaps between cards for routing connections
const v = reactive({ k: 1, tx: 20, ty: 10 });
const open = reactive<Record<string, boolean>>({});        // Expanded signal bundles
const field = reactive<Record<string, boolean>>({});       // Equipment with expanded sensors/actuators
// Show only PLC-connected equipment: default to this when signal wires exist and no preference is set (architecture focuses on control relationships; showing dozens of machines adds clutter).
const onlyPref = ref<string | null>((() => { try { return localStorage.getItem('vf_arch_only'); } catch { return null; } })());
const onlyCtl = computed({ get: () => (onlyPref.value === null ? sigLinks.value.length > 0 : onlyPref.value === '1'), set: (x: boolean) => { onlyPref.value = x ? '1' : '0'; } });
const saveOnly = () => { try { localStorage.setItem('vf_arch_only', onlyPref.value || ''); } catch { /* */ } };
const lc = (layer: string) => ed.cat?.layers?.[layer]?.color || '#888';
const isSel = (id: string) => ed.sel.includes(id);
const issue = computed(() => Object.fromEntries((ed.validation?.issues || []).filter((i: any) => i.id && i.level === 'error').map((i: any) => [i.id, 1])));

// ---------- Data ----------
const links = computed<any[]>(() => ed.model?.links || []);
const sigLinks = computed(() => links.value.filter((l: any) => linkKind(l) === 'signal'));
const netLinks = computed(() => links.value.filter((l: any) => linkKind(l) === 'network'));
const ctlDevs = computed(() => new Set(sigLinks.value.flatMap((l: any) => [l.from, l.to])));
const shown = computed(() => (ed.model?.blocks || []).filter((b: any) => {
  if (b._parent || !layerVisible(b.id)) return false;
  if (layerOf(b.id) === 'process' && onlyCtl.value && !ctlDevs.value.has(b.id)) return false;
  return true;
}));
const counts = computed(() => {
  const c: Record<string, number> = {}; for (const b of ed.model?.blocks || []) c[layerOf(b.id)] = (c[layerOf(b.id)] || 0) + 1;
  return $t('archView.plcHmi0GatewaysSwitches', [c.control || 0, c.network || 0, c.it || 0, sigLinks.value.length, netLinks.value.length]);
});
/** Equipment sensors/actuators (individual signal channels). */
function pointsOf(id: string) {
  const out: any[] = [];
  for (const l of sigLinks.value) {
    if (l.from !== id && l.to !== id) continue;
    const plc = layerOf(l.to) === 'control' ? l.to : l.from; if (plc === id) continue;
    for (const s of l.signals || []) out.push({ point: s.point, ch: s.ch, dir: s.dir, plc: blocksById.value[plc]?.name || plc });
  }
  return out;
}
const neighbors = (id: string) => [...sigLinks.value, ...netLinks.value].filter((l: any) => l.from === id || l.to === id).map((l: any) => (l.from === id ? l.to : l.from));

// ---------- Auto layout (use arch for manually positioned cards) ----------
const layout = computed(() => {
  const by: Record<string, any> = {}, lanesOut: any[] = [];
  const of = (k: string) => shown.value.filter((b: any) => layerOf(b.id) === k);
  const W = (b: any) => (layerOf(b.id) === 'process' ? 176 : 196);
  const H = (b: any) => BASE_H + (field[b.id] ? Math.ceil(pointsOf(b.id).length / 2) * 18 + 8 : 0);
  // Production equipment: sort by zone and floor-plan X; use two rows if needed.
  const proc = of('process').sort((a: any, b: any) => (areaIdx(a) - areaIdx(b)) || a.pos[0] - b.pos[0] || a.pos[1] - b.pos[1]);
  const rows = proc.length > 24 ? 4 : proc.length > 16 ? 3 : proc.length > 8 ? 2 : 1;
  const pos: Record<string, number[]> = {};
  // Arrange column-first (up to rows units per column), in zone order; label each zone above its first equipment column.
  const colsOf: Record<number, any[]> = {};
  proc.forEach((b: any, i: number) => { const c = Math.floor(i / rows); (colsOf[c] ||= []).push(b); pos[b.id] = [X0 + c * (176 + GX), 0]; });
  const areaCols: any[] = []; let prevA = -99, prevC = -1;
  proc.forEach((b: any, i: number) => {
    const ai = areaIdx(b), c = Math.floor(i / rows);
    if (ai !== prevA && c !== prevC && ai < 999) { areaCols.push({ name: ed.model.areas?.[ai]?.name || '', x: X0 + c * (176 + GX) }); prevC = c; }
    prevA = ai;
  });
  // Row y positions within each column
  const rowY: Record<string, number> = {};
  for (const bs of Object.values(colsOf)) { let y = TOP; for (const b of bs) { rowY[b.id] = y; y += H(b) + GY; } }
  // Top three layers: center above connected objects' average X, then push apart left to right to avoid overlap.
  const cx: Record<string, number> = {};
  for (const b of proc) cx[b.id] = (b.arch ? b.arch[0] : pos[b.id][0]) + W(b) / 2;
  // First use connected objects already placed in lower layers (equipment for PLCs, PLCs for switches…); otherwise use same-layer connections (HMI follows its connected PLC).
  const lane0: Record<string, string> = {};
  for (const b of proc) lane0[b.id] = 'process';
  const place = (key: string, same: boolean) => {
    const bs = of(key);
    const want = bs.map((b: any) => {
      const nb = neighbors(b.id).filter((id) => cx[id] !== undefined && lane0[id] !== key);
      const sn = same ? neighbors(b.id).filter((id) => cx[id] !== undefined && lane0[id] === key) : [];
      const use = nb.length ? nb : sn;
      const d = b.arch ? b.arch[0] : use.length ? use.reduce((t, id) => t + cx[id], 0) / use.length - W(b) / 2 + (nb.length ? 0 : W(b) + GX) : 1e9;
      return { b, d, fixed: !!b.arch };
    }).sort((a: any, b: any) => a.d - b.d);
    let right = X0 - GX;
    for (const w of want) {
      if (w.d >= 1e9) w.d = Math.max(X0, right + GX);     // Place unconnected objects last.
      const xx = w.fixed ? w.d : Math.max(w.d, right + GX);
      pos[w.b.id] = [xx, 0]; rowY[w.b.id] = w.b.arch ? w.b.arch[1] : TOP; right = Math.max(right, xx + W(w.b)); cx[w.b.id] = xx + W(w.b) / 2; lane0[w.b.id] = key;
    }
  };
  for (const k of ['control', 'network', 'it']) { place(k, false); place(k, true); }
  for (const b of proc) if (b.arch) { pos[b.id] = [b.arch[0], 0]; rowY[b.id] = b.arch[1]; }
  // Swimlanes (top to bottom: information systems, communications, control, production equipment)
  let y = 0;
  for (const L of LANES) {
    if (ed.filter?.layers?.[L.key] === false) continue;
    const bs = of(L.key);
    const h = Math.max(96, ...bs.map((b: any) => rowY[b.id] + H(b) + 18));
    lanesOut.push({ ...L, y, h, count: bs.length, adds: ADDS[L.key], areas: L.key === 'process' ? areaCols : [] });
    for (const b of bs) by[b.id] = { x: pos[b.id][0], y: y + rowY[b.id], w: W(b), h: H(b), lane: L.key, laneY: y };
    y += h;
  }
  return { by, lanes: lanesOut, height: y };
});
const areaIdx = (b: any) => { const n = areaOf(b.pos || [0, 0]); const i = (ed.model?.areas || []).findIndex((a: any) => a.name === n); return i < 0 ? 999 : i; };
const lanes = computed(() => layout.value.lanes);
const width = computed(() => Math.max(900, ...Object.values(layout.value.by).map((n: any) => n.x + n.w + 60)));
// Drag offset
const drag = reactive<any>({ on: false, id: '', sx: 0, sy: 0, dx: 0, dy: 0, moved: false, pan: false, px: 0, py: 0 });
const conn = ref<{ from: string; side: number; a: number[]; b: number[]; over: string; kind: string; d: string; tip: string } | null>(null);
const nodes = computed(() => shown.value.filter((b: any) => layout.value.by[b.id]).map((b: any) => {
  const g = layout.value.by[b.id], t = typeOf(b), layer = layerOf(b.id);
  const moving = drag.on && drag.moved && isSel(b.id);
  const st = nodeStatus(b.id), ps = plcState(b.id);
  const b0 = b.type === 'plc' && ps ? { text: PLC_CN[ps], cls: ps } : st ? { text: st.text.split(' · ')[0], cls: st.cls } : null;
  const badge = b0 ? { ...b0, w: textW(b0.text, 6.2, 11) + 10 } : null;
  const sub = layer === 'process' ? `${b.id} · ${t.label.replace(/\s*[\uff08(][^\uff09)]*[\uff09)]/, '')}`
    : [b.id, b.type === 'plc' ? $t('archView.n0Machines', [(sigLinks.value.filter((l: any) => l.from === b.id || l.to === b.id)).length]) : '', b.params?.ip || ''].filter(Boolean).join(' · ');
  return { id: b.id, type: b.type, layer, name: clipW(b.name || b.id, g.w - 44 - (badge ? badge.w + 12 : 10), 7.4, 13.5),
    sub: clipW(sub, g.w - 44 - (b.type === 'plc' ? 58 : pointsOf(b.id).length ? 36 : 8), 6.2, 11), typeLabel: t.label, icon: t.icon || 'Box', color: t.color,
    x: g.x + (moving ? drag.dx : 0), y: g.y + (moving ? drag.dy : 0), w: g.w, h: g.h, badge, status: st?.text || '', points: pointsOf(b.id) };
}));
const nodeBy = computed(() => Object.fromEntries(nodes.value.map((n: any) => [n.id, n])));
// Text width estimate for the SVG cards (CJK glyphs are about twice as wide as Latin ones) and width-based clipping:
// English names / status words are longer than Chinese ones, so the budget is in pixels, not characters.
const textW = (s: string, latin: number, cjk: number) => [...s].reduce((t, c) => t + (c.charCodeAt(0) > 0x2e80 ? cjk : latin), 0);
function clipW(s: string, max: number, latin: number, cjk: number) {
  if (textW(s, latin, cjk) <= max) return s;
  let out = '';
  for (const c of s) { if (textW(out + c, latin, cjk) + latin > max) break; out += c; }
  return out + '…';
}
const clip = (s: string, n: number) => ([...s].reduce((t, c) => t + (c.charCodeAt(0) > 0x2e80 ? 2 : 1), 0) <= n * 2 ? s : [...s].slice(0, n - 1).join('') + '…');

// ---------- Connections (4.4: ports on card borders, orthogonal routing around cards, offset parallel lines; shares plan/route.ts with Floor Plan) ----------
const RO = { margin: 12, bend: 40, gap: 6, close: 26 };
/** Bundle signal wires / network cables by endpoint pair; keep material-flow lines (faint) separate. Recalculate routes only when layout (card positions, expansion) or connections change. */
const groups = computed(() => {
  const N = layout.value.by, gs: Record<string, any> = {}, mats: any[] = [];
  for (const l of [...netLinks.value, ...sigLinks.value]) {
    if (!linkVisible(l) || !N[l.from] || !N[l.to] || l.from === l.to) continue;
    const k = linkKind(l), key = k + ':' + [l.from, l.to].sort().join('|');
    const x = (gs[key] ||= { key, kind: k, a: l.from, b: l.to, ids: [], links: [] as any[] });
    x.ids.push(l.id); x.links.push(l);
  }
  if (ed.filter?.links?.material !== false) {
    for (const l of links.value) if (linkKind(l) === 'material' && N[l.from] && N[l.to] && l.from !== l.to && linkVisible(l)) mats.push({ key: 'm:' + l.id, kind: 'material', a: l.from, b: l.to, ids: [l.id] });
  }
  return { wires: Object.values(gs) as any[], mats };
});
const routes = computed(() => {
  const R: Record<string, Rect> = {};
  for (const [id, g] of Object.entries(layout.value.by) as any) R[id] = { x0: g.x, y0: g.y, x1: g.x + g.w, y1: g.y + g.h };
  return routeAll(R, [...groups.value.wires, ...groups.value.mats], RO);
});
/** Paths (use simple right-angle lines while dragging). */
function pathOf(key: string) {
  const r = routes.value[key]; if (!r) return null;
  let pts = r.pts;
  if (drag.on && drag.moved && (drag.dx || drag.dy)) {
    const ma = isSel(r.a.id), mb = isSel(r.b.id);
    if (ma && mb) pts = shift(pts, drag.dx, drag.dy);
    else if (ma || mb) { const mv = (e: End): End => (isSel(e.id) ? { ...e, p: [e.p[0] + drag.dx, e.p[1] + drag.dy] } : e); pts = elbow(mv(r.a), mv(r.b), RO.margin); }
  }
  return pts;
}
const wires = computed(() => groups.value.wires.map((g: any) => {
  const pts = pathOf(g.key); if (!pts) return null;
  const A = blocksById.value[g.a], B = blocksById.value[g.b], protos = new Set<string>(), sigs: any[] = [];
  let fault = '';
  for (const l of g.links) {
    if (l.protocol) protos.add(PROTO_CN[l.protocol] || l.protocol);
    const plc = layerOf(l.to) === 'control' ? l.to : l.from, dev = plc === l.to ? l.from : l.to;
    for (const s of l.signals || []) sigs.push({ ...s, dev: blocksById.value[dev]?.name || dev });
    const f = linkFault(l); if (f) fault = f;
  }
  const lab = labelAt(pts);
  const label = g.kind === 'signal' ? $t('common.n0Channels', [sigs.length]) : fault ? '⚠ ' + fault : [...protos].join('/');
  const title = g.kind === 'signal' ? $t('archView.signalWire012', [A?.name, B?.name, sigs.length]) : $t('archView.networkCable012', [A?.name, B?.name, protos.size ? $t('common.k459') + [...protos].join('/') + $t('common.k460') : '', fault ? $t('archView.communicationFault') + fault : '']);
  // Omit protocol labels if the segment is too short; show them in the hover title. Always show signal channel counts and failures.
  return { ...g, sigs, fault, pts, d: pathD(pts, 10), m: lab.m, label, title };
}).filter(Boolean) as any[]);
/** Place labels without overlapping each other or cards; always show signal channel counts and failures. Omit protocols if space is tight (view on hover). */
const wireLabels = computed(() => {
  const ws = wires.value.filter((w: any) => w.label).sort((p: any, q: any) => +!!q.fault - +!!p.fault || +(q.kind === 'signal') - +(p.kind === 'signal'));
  const obst = nodes.value.map((n: any) => ({ x0: n.x, y0: n.y, x1: n.x + n.w, y1: n.y + n.h }));
  return placeLabels(ws.map((w: any) => ({ key: w.key, pts: w.pts, w: w.label.length * 7.4 + 18, h: 20, required: w.kind === 'signal' || !!w.fault })), obst);
});
/** Material flow (faint): only between production equipment. */
const matLines = computed(() => groups.value.mats.map((g: any) => {
  const pts = pathOf(g.key); if (!pts) return null;
  return { id: g.ids[0], a: g.a, b: g.b, d: pathD(pts, 10), title: $t('archView.materialFlow01', [blocksById.value[g.a]?.name || g.a, blocksById.value[g.b]?.name || g.b]) };
}).filter(Boolean) as any[]);

// ---------- Connection points and drag-to-connect (same as Floor Plan) ----------
const portsOf = computed(() => {
  if (drag.on || drag.pan || ed.placing || ed.pick || !canEdit() || ed.modelLocked) return null;
  const id = conn.value ? conn.value.over : hoverId.value, n = id && nodeBy.value[id]; if (!n) return null;
  return { id, pts: [{ s: 0, p: [n.x + n.w, n.y + n.h / 2] }, { s: 1, p: [n.x + n.w / 2, n.y + n.h] }, { s: 2, p: [n.x, n.y + n.h / 2] }, { s: 3, p: [n.x + n.w / 2, n.y] }] };
});
const connCls = (id: string) => (conn.value && conn.value.over === id ? (conn.value.kind ? 'cn-ok' : 'cn-bad') : conn.value && conn.value.from === id ? 'cn-src' : '');
function connPreview() {
  const c = conn.value; if (!c) return;
  const N = [[1, 0], [0, 1], [-1, 0], [0, -1]][c.side], S = [c.a[0] + N[0] * 14, c.a[1] + N[1] * 14];
  c.d = pathD([c.a, S, c.side % 2 === 0 ? [c.b[0], S[1]] : [S[0], c.b[1]], c.b], 10);
  c.tip = c.over ? (c.kind ? CONN_CN[c.kind] : $t('common.cannotConnect')) : '';
}

// ---------- Hover highlighting ----------
const hoverId = ref('');
// Do not dim other cards while dragging wires or cards; keep targets visible.
const hoverRel = computed(() => (hoverId.value && blocksById.value[hoverId.value] && !conn.value && !(drag.on && drag.moved) ? relatedSet(hoverId.value) : null));
function relCls(ids: string[], id = '') {
  const r = hoverRel.value; if (!r) return '';
  if (id) return r.ids.has(id) ? 'rel' : 'dim';
  return ids.some((x) => r.links.has(x)) ? 'rel' : 'dim';
}

// ---------- View ----------
function world(e: MouseEvent) { const r = svg.value!.getBoundingClientRect(); return [(e.clientX - r.left - v.tx) / v.k, (e.clientY - r.top - v.ty) / v.k]; }
function fit() {
  const r = svg.value?.getBoundingClientRect(); if (!r || !r.width) return;
  const w = width.value, h = Math.max(200, layout.value.height);
  v.k = Math.max(0.25, Math.min(1.2, (r.width - 30) / w, (r.height - 30) / h));
  v.tx = Math.max(10, (r.width - w * v.k) / 2); v.ty = Math.max(10, (r.height - h * v.k) / 2);
}
function onWheel(e: WheelEvent) {
  const r = svg.value!.getBoundingClientRect(), mx = e.clientX - r.left, my = e.clientY - r.top;
  const k2 = Math.max(0.2, Math.min(3, v.k * Math.exp(-e.deltaY * 0.0015)));
  v.tx = mx - (mx - v.tx) * k2 / v.k; v.ty = my - (my - v.ty) * k2 / v.k; v.k = k2;
}

// ---------- Mouse ----------
let rdown: number[] | null = null;
function onDown(e: MouseEvent) {
  const tgt = e.target as Element, w = world(e);
  if (e.button === 2) rdown = [e.clientX, e.clientY];
  if (e.button === 1 || e.button === 2) { Object.assign(drag, { pan: true, px: e.clientX - v.tx, py: e.clientY - v.ty }); return; }
  if (e.button !== 0) return;
  const id = tgt.closest('[data-id]')?.getAttribute('data-id') || '';
  if (ed.pick) { if (id) { const pk = ed.pick; ed.pick = null; pk.onPick(id); } return; }
  const add = tgt.closest('[data-add]')?.getAttribute('data-add'); if (add) { addMenu(e, add); return; }
  const port = tgt.closest('[data-port]')?.getAttribute('data-port');
  if (port) {
    const i = port.lastIndexOf(':'), pid = port.slice(0, i), side = +port.slice(i + 1), q = portsOf.value?.pts.find((x) => x.s === side);
    if (q && nodeBy.value[pid]) { conn.value = { from: pid, side, a: [...q.p], b: w, over: '', kind: '', d: '', tip: '' }; connPreview(); }
    return;
  }
  const prog = tgt.closest('[data-prog]')?.getAttribute('data-prog'); if (prog) { select([prog]); openProgram(prog); return; }
  const fx = tgt.closest('[data-field]')?.getAttribute('data-field'); if (fx) { field[fx] = !field[fx]; return; }
  const bundle = tgt.closest('[data-bundle]')?.getAttribute('data-bundle');
  if (bundle && bundle.startsWith('signal:')) { open[bundle] = !open[bundle]; }
  const lk = tgt.closest('[data-link]')?.getAttribute('data-link');
  if (lk && !id) { ed.sel = []; ed.selLink = lk; return; }
  if (id) {
    if (e.shiftKey || e.ctrlKey) { if (isSel(id)) { ed.sel = ed.sel.filter((x: string) => x !== id); return; } select([id], true); }
    else if (!isSel(id)) select([id]);
    Object.assign(drag, { on: true, id, sx: w[0], sy: w[1], dx: 0, dy: 0, moved: false });
    return;
  }
  ed.sel = []; ed.selLink = '';
  Object.assign(drag, { pan: true, px: e.clientX - v.tx, py: e.clientY - v.ty });
}
function onMove(e: MouseEvent) {
  const w = world(e);
  if (drag.pan) { v.tx = e.clientX - drag.px; v.ty = e.clientY - drag.py; return; }
  if (conn.value) {
    const c = conn.value, el = e.target as Element, t = el.closest?.('[data-id]')?.getAttribute('data-id') || el.closest?.('[data-hov]')?.getAttribute('data-hov') || '';
    c.b = w; c.over = t && t !== c.from && blocksById.value[t] ? t : ''; c.kind = c.over ? connKind(c.from, c.over) : ''; connPreview();
    return;
  }
  if (drag.on) {
    const dx = w[0] - drag.sx, dy = w[1] - drag.sy;
    if (!drag.moved && Math.hypot(dx, dy) * v.k < 4) return;
    drag.moved = true; drag.dx = Math.round(dx / 2) * 2; drag.dy = Math.round(dy / 2) * 2; return;
  }
  const el = e.target as Element, hid = el.closest?.('[data-id]')?.getAttribute('data-id') || el.closest?.('[data-hov]')?.getAttribute('data-hov') || '';
  if (hid !== hoverId.value) hoverId.value = hid;
}
function onUp(e?: MouseEvent) {
  if (drag.pan) { drag.pan = false; return; }
  if (conn.value) {
    const c = conn.value; conn.value = null;
    if (c.over) connectBlocks(c.from, c.over);
    else if (e && Math.hypot(c.b[0] - c.a[0], c.b[1] - c.a[1]) * v.k > 30) ElMessage.info($t('archView.releaseOverAnotherCardTo'));
    return;
  }
  if (drag.on) {
    drag.on = false;
    if (drag.moved) {
      // Manual position: absolute x, y relative to the lane top (clamped within the lane; no lane switching).
      const ops: Op[] = [];
      for (const id of ed.sel) {
        const g = layout.value.by[id]; if (!g) continue;
        const ln = lanes.value.find((l: any) => l.key === g.lane);
        const ny = Math.max(TOP, Math.min((ln?.h || 200) + 140, g.y - g.laneY + drag.dy));
        ops.push({ op: 'update_block', id, set: { arch: [Math.max(X0, Math.round(g.x + drag.dx)), Math.round(ny)] } });
      }
      if (ops.length) exec(ops, $t('archView.arrangeArchitecture'));
    }
    drag.moved = false; drag.dx = drag.dy = 0;
  }
}
function onLeave() { hoverId.value = ''; if (conn.value) conn.value = null; onUp(); }
function onDbl(e: MouseEvent) {
  const id = (e.target as Element).closest('[data-id]')?.getAttribute('data-id'); if (!id) return;
  if (blocksById.value[id]?.type === 'plc') openProgram(id);
  else { select([id]); ed.rightTab = 'props'; }
}
function onCtx(e: MouseEvent) {
  if (rdown && Math.hypot(e.clientX - rdown[0], e.clientY - rdown[1]) > 5) { rdown = null; return; }
  rdown = null;
  const tgt = e.target as Element, id = tgt.closest('[data-id]')?.getAttribute('data-id'), lk = tgt.closest('[data-link]')?.getAttribute('data-link');
  if (id && blocksById.value[id]) {
    if (!isSel(id)) select([id]);
    const b = blocksById.value[id], layer = layerOf(id), extra: any[] = [];
    if (b.type === 'plc') extra.push({ label: $t('common.openPlcProgram'), kbd: $t('archView.doubleClick'), run: () => openProgram(id) });
    if (layer === 'process') {
      const plcs = (ed.model.blocks || []).filter((x: any) => x.type === 'plc');
      extra.push({ label: $t('archView.addPlcControl'), children: [{ label: $t('archView.createPlc'), run: () => addPlcControl(id) }, ...plcs.map((p: any) => ({ label: $t('archView.connectTo0', [p.name]), run: () => addPlcControl(id, p.id) }))] });
      if (pointsOf(id).length) extra.push({ label: field[id] ? $t('archView.collapseSensorsActuators') : $t('archView.expandSensorsActuators'), run: () => { field[id] = !field[id]; } });
    } else {
      const nets = (ed.model.blocks || []).filter((x: any) => ['switch', 'gateway'].includes(x.type) && x.id !== id);
      extra.push({ label: $t('archView.connectToNetwork'), children: [{ label: $t('archView.createSwitch'), run: () => addNetwork(id) }, ...nets.map((x: any) => ({ label: $t('archView.connectTo0', [x.name]), run: () => addNetwork(id, x.id) }))] });
    }
    if (b.arch) extra.push({ label: $t('archView.restoreAutomaticPosition'), run: () => exec([{ op: 'update_block', id, set: { arch: null } }], $t('archView.restoreAutomaticPosition')) });
    openBlockMenu(e, id, 'arch', extra);
  } else if (lk) {
    ed.sel = []; ed.selLink = lk;
    const g = wires.value.find((w: any) => w.ids.includes(lk));
    openLinkMenu(e, lk, g?.kind === 'signal' ? [{ label: open[g.key] ? $t('archView.collapseIndividualSignals') : $t('archView.expandIndividualSignals'), run: () => { open[g.key] = !open[g.key]; } }] : []);
  } else {
    const lane = laneAt(world(e)[1]);
    openPaneMenu(e, [
      ...(lane && ADDS[lane]?.length ? ADDS[lane].map(([t, n]) => ({ label: $t('archView.add0', [n]), run: () => addNode(t) })) : []),
      { label: $t('common.add'), children: Object.values(ADDS).flat().map(([t, n]) => ({ label: n, run: () => addNode(t) })) },
      { label: $t('archView.autoArrangeClearManualPositions'), run: autoAll }, { label: $t('common.fitAll'), kbd: 'Home', run: fit },
    ]);
  }
}
const laneAt = (y: number) => lanes.value.find((l: any) => y >= l.y && y < l.y + l.h)?.key || '';
function addMenu(e: MouseEvent, lane: string) {
  openCtx(e, [{ title: $t('archView.addTo') + (LANES.find((l) => l.key === lane)?.label || '') + $t('archView.k772'), items: ADDS[lane].map(([t, n]) => ({ label: n, hint: ed.cat?.types?.[t]?.help?.slice(0, 18) || '', run: () => addNode(t) })) }]);
}
/** Add equipment at the end of its lane; place near the plant's top-right corner in Floor Plan and at the far right in Graph. */
function addNode(type: string) {
  if (!ed.cat?.types?.[type]) return;
  const fl = ed.model?.plant?.floor || [60, 40], same = (ed.model.blocks || []).filter((b: any) => layerOf(b.id) === ed.cat.types[type].layer).length;
  const maxNode = Math.max(100, ...(ed.model.blocks || []).map((b: any) => b.node?.[0] || 0));
  const b: any = makeBlock(type, [Math.max(2, fl[0] - 3 - same * 2.5), 2 + (same % 4) * 2], [maxNode + 260, 60 + same * 140]);
  const lane = layout.value.lanes.find((l: any) => l.key === ed.cat.types[type].layer);
  const right = Math.max(X0 - GX, ...Object.values(layout.value.by).filter((g: any) => g.lane === lane?.key).map((g: any) => g.x + g.w));
  b.arch = [right + GX, TOP];
  exec([{ op: 'add_block', block: b }], $t('archView.add0', [ed.cat.types[type].label])); select([b.id]); flash([b.id], 1500);
}
function autoAll() {
  const ops: Op[] = (ed.model?.blocks || []).filter((b: any) => b.arch).map((b: any) => ({ op: 'update_block', id: b.id, set: { arch: null } }));
  if (ops.length) exec(ops, $t('archView.autoArrangeArchitecture')); setTimeout(fit, 50);
}
function openProgram(id: string) {
  const p = panelById('plc-editor-float');
  if (p) openFloat(p as any, { bid: id }, id); else window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor' } }));
}

watch(() => ed.focusReq, (r) => {
  if (!r || ed.view !== 'arch') return;
  if (!r.id) return fit();
  const n = nodeBy.value[r.id]; if (!n) return;
  const rr = svg.value!.getBoundingClientRect();
  v.k = Math.max(v.k, 0.8); v.tx = rr.width / 2 - (n.x + n.w / 2) * v.k; v.ty = rr.height / 2 - (n.y + n.h / 2) * v.k;
});
let stopLive: (() => void) | null = null;
onMounted(() => { if (!ed.filter) loadFilter(); stopLive = useLive(); setTimeout(fit, 30); });
onUnmounted(() => stopLive?.());
defineExpose({ fit });
</script>
