<template>
  <div class="gv" ref="host" data-tour="gv-canvas" :class="{ placing: !!ed.placing, picking: !!ed.pick, lod: zoom < 0.5, lod2: zoom < 0.35 }" @drop="onDrop" @dragover.prevent @mousedown.capture="onDown" @contextmenu.prevent>
    <VueFlow id="vfg" :nodes="nodes" :edges="edges" :min-zoom="0.08" :max-zoom="2.5" :snap-to-grid="true" :snap-grid="[10, 10]"
      :delete-key-code="null" :multi-selection-key-code="['Control', 'Meta', 'Shift']" :selection-key-code="null" :pan-on-drag="[1, 2]" :selection-on-drag="true" :select-nodes-on-drag="false" :zoom-on-double-click="false"
      :connection-radius="28" :default-edge-options="{ type: 'smoothstep' }" :is-valid-connection="validConn" @pane-ready="onReady"
      @nodes-change="onNodesChange" @node-drag-start="onDragStart" @node-drag="onDrag" @node-drag-stop="onDragStop"
      @connect-start="onConnectStart" @connect="onConnect" @connect-end="onConnectEnd"
      @edge-click="onEdgeClick" @pane-click="onPaneClick" @node-click="onNodeClick" @node-mouse-enter="(e: any) => (ed.hoverId = e.node.id)" @node-mouse-leave="ed.hoverId = ''" @node-double-click="onNodeDbl"
      @pane-context-menu="(e: any) => openMenu(e, 'pane')" @node-context-menu="(e: any) => openMenu(e.event, 'node', e.node.id)"
      @edge-context-menu="(e: any) => openMenu(e.event, 'edge', e.edge.id)">
      <template #node-block="p"><BlockNode :id="p.id" :data="p.data" :selected="p.selected" /></template>
      <template #node-vgroup="p"><GroupNode :id="p.id" :data="p.data" :selected="p.selected" /></template>
      <template #node-note="p"><NoteNode :id="p.id" :data="p.data" :selected="p.selected" /></template>
      <Background variant="lines" :gap="20" :line-width="1" pattern-color="#e3e9f1" />
      <MiniMap v-if="showMini" pannable zoomable :node-color="miniColor" mask-color="rgba(226,232,240,.55)" />
      <Controls :show-interactive="false" />
    </VueFlow>

    <div class="gv-top">
      <div v-if="scope" class="gv-crumb"><a @click="scope = null">{{ ed.model.plant?.name || $t('common.factory') }}</a><span>›</span><b>{{ scope.name }}</b><small class="muted">{{ $t('graphView.submodelInternalsReadOnlyPreview') }}</small></div>
      <div v-if="ed.partTrace" class="gv-trace">
        <el-icon><Aim /></el-icon><b class="mono">{{ ed.partTrace.id }}</b>
        <span class="muted small">{{ $t('graphView.step0123', [ed.partTrace.i + 1, ed.partTrace.steps.length, traceStep?.station, traceStep?.event]) }} <span class="mono">{{ traceStep?.t?.slice(11) }}</span></span>
        <el-button size="small" text :disabled="ed.partTrace.i <= 0" @click="ed.partTrace.i--"><el-icon><ArrowLeft /></el-icon></el-button>
        <el-button size="small" text :disabled="ed.partTrace.i >= ed.partTrace.steps.length - 1" @click="ed.partTrace.i++"><el-icon><ArrowRight /></el-icon></el-button>
        <el-button size="small" text @click="ed.partTrace = null"><el-icon><Close /></el-icon></el-button>
      </div>
      <div class="gv-mini" data-tour="gv-tools">
        <el-tooltip :content="$t('graphView.autoLayoutByMaterialFlow')"><el-button size="small" text :disabled="!!scope" @click="autoLayout"><el-icon><Sort /></el-icon> {{ $t('graphView.autoLayout') }}</el-button></el-tooltip>
        <el-checkbox v-model="wireOn" size="small">{{ $t('graphView.showFlowRatesOnConnections') }}</el-checkbox>
        <el-checkbox v-model="showMini" size="small">{{ $t('graphView.minimap') }}</el-checkbox>
      </div>
    </div>
    <div class="gv-tools" v-if="selBlocks.length >= 2">
      <span class="muted">{{ $t('graphView.selected0', [selBlocks.length]) }}</span>
      <el-tooltip v-for="a in ALIGN" :key="a[0]" :content="a[1]"><el-button size="small" text @click="arrange(a[0], 'node')"><el-icon><component :is="a[2]" /></el-icon></el-button></el-tooltip>
      <el-button size="small" text @click="groupSel">{{ $t('graphView.groupCtrlG') }}</el-button>
    </div>
    <div class="gv-hint muted" v-if="!(ed.model?.blocks || []).length">{{ $t('graphView.dragABlockFromThe') }}</div>

    <div v-if="add.show" class="qa" :style="{ left: add.x + 'px', top: add.y + 'px' }" @mousedown.stop>
      <el-input ref="addInput" v-model="add.q" size="small" :placeholder="$t('graphView.searchBlockTypesEG')" clearable @keydown.enter="addList[0] && addType(addList[0].key)" @keydown.esc="add.show = false" />
      <div class="qa-list">
        <div v-for="t in addList" :key="t.key" class="qa-i" @click="addType(t.key)">
          <el-icon :style="{ color: t.color }"><component :is="t.icon" /></el-icon><span>{{ t.label }}</span><small>{{ t.cat }}</small>
        </div>
        <div v-if="!addList.length" class="muted small" style="padding:6px">{{ $t('graphView.noMatchingTypes') }}</div>
      </div>
    </div>

  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { Background } from '@vue-flow/background';
import { Controls } from '@vue-flow/controls';
import { MarkerType, useVueFlow, VueFlow } from '@vue-flow/core';
import { MiniMap } from '@vue-flow/minimap';
import { ElMessage } from 'element-plus';
import { get, P } from '../api';
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import BlockNode from './BlockNode.vue';
import GroupNode from './GroupNode.vue';
import NoteNode from './NoteNode.vue';
import { openBlockMenu, openLinkMenu, openPaneMenu } from './shell/contextMenu';
import { placeAt } from './shell/place';
import { layerOf, layerVisible, linkKind, linkVisible, relatedSet } from './shell/relations';
import { connectByLayer } from './shell/wiring';
import {
  arrange, blocksById, cloneOps, ed, exec, flash, focusOn, groupSel, makeBlock, newId, planPosNear,
  select, selBlocks, typeOf,
} from './store';
// Route conditions are model codes (e.g. the rework route); show the known ones in the UI language.
const condLabel = (c: string) => (c === '\u8fd4\u4fee' ? $t('graphView.reworkCond') : c);

const emit = defineEmits<{ (e: 'template'): void }>();
const { fitView, screenToFlowCoordinate, setCenter, findNode, getViewport, setViewport, viewport } = useVueFlow('vfg');
const host = ref<HTMLElement>();
const addInput = ref<any>();
const IMPLICIT = new Set(['melt', 'ladle', 'sand', 'mold']);
const CARD_W = 220;
const ALIGN: [string, string, string][] = [['left', $t('common.alignLeft'), 'Back'], ['top', $t('graphView.alignTop'), 'Top'], ['hcenter', $t('graphView.alignVerticalCenters'), 'Sort'], ['vcenter', $t('graphView.alignHorizontalCenters'), 'Switch'],
  ['hdist', $t('graphView.distributeHorizontally'), 'DCaret'], ['vdist', $t('graphView.distributeVertically'), 'More']];

const issueOf = computed(() => {
  const m: Record<string, string> = {};
  for (const i of ed.validation?.issues || []) if (i.id && m[i.id] !== 'error') m[i.id] = i.level;
  return m;
});
const cardH = (b: any) => { const t = typeOf(b); return 64 + 20 * Math.max(t.in.length, t.out.length) + 17 * Math.min(3, Object.keys(b.params || {}).length) + 26; };
const collapsed = computed(() => new Set((ed.model?.groups || []).filter((g: any) => g.collapsed).map((g: any) => g.id)));

function groupBox(gid: string) {
  const mem = (ed.model.blocks || []).filter((b: any) => b.group === gid);
  if (!mem.length) return null;
  const x0 = Math.min(...mem.map((b: any) => b.node[0])) - 24, y0 = Math.min(...mem.map((b: any) => b.node[1])) - 48;
  const x1 = Math.max(...mem.map((b: any) => b.node[0] + CARD_W)) + 24, y1 = Math.max(...mem.map((b: any) => b.node[1] + cardH(b))) + 24;
  return { x0, y0, x1, y1, n: mem.length };
}

const nodes = computed(() => {
  const m = ed.model; if (!m) return [];
  const out: any[] = [];
  for (const g of m.groups || []) {
    const bx = groupBox(g.id);
    const pos = bx ? { x: bx.x0, y: bx.y0 } : { x: g.node?.[0] || 0, y: g.node?.[1] || 0 };
    out.push({ id: g.id, type: 'vgroup', position: pos, selected: ed.sel.includes(g.id), zIndex: -1, class: 'n-group',
      data: { w: g.collapsed || !bx ? 260 : bx.x1 - bx.x0, h: g.collapsed || !bx ? 86 : bx.y1 - bx.y0, count: bx?.n || 0 } });
  }
  if (scope.value) return scopeNodes.value;
  for (const b of m.blocks || []) {
    if (!layerVisible(b.id)) continue;
    out.push({ id: b.id, type: 'block', class: traceNodes.value.has(b.id) ? (traceStep.value?.station === b.id ? 'n-trcur' : 'n-tr') : '', position: { x: b.node?.[0] || 0, y: b.node?.[1] || 0 }, selected: ed.sel.includes(b.id),
      hidden: collapsed.value.has(b.group), data: { err: issueOf.value[b.id] === 'error', warn: issueOf.value[b.id] === 'warn' } });
  }
  for (const n of m.notes || []) out.push({ id: n.id, type: 'note', position: { x: n.node[0], y: n.node[1] }, selected: ed.sel.includes(n.id), data: {}, style: { width: (n.size?.[0] || 220) + 'px' } });
  return out;
});

const edges = computed(() => {
  const m = ed.model; if (!m) return [];
  if (scope.value) return scopeEdges.value;
  const out: any[] = [], by = blocksById.value, col = collapsed.value;
  for (const l of m.links || []) {
    const A = by[l.from], B = by[l.to]; if (!A || !B) continue;
    if (linkKind(l) !== 'material') { if (!col.has(A.group) && !col.has(B.group) && linkVisible(l)) out.push(...ctlEdges(l)); continue; }
    if (!linkVisible(l)) continue;
    let s = l.from, t = l.to, sh = l.from_port || 'out', th = l.to_port || 'in';
    const ga = A.group && col.has(A.group) ? A.group : '', gb = B.group && col.has(B.group) ? B.group : '';
    if (ga && ga === gb) continue;
    if (ga) { s = ga; sh = 'out'; } else if (!typeOf(A).out.includes(sh)) { if (!typeOf(A).out.length) continue; sh = typeOf(A).out[0]; }
    if (gb) { t = gb; th = 'in'; } else if (!typeOf(B).in.includes(th)) { if (!typeOf(B).in.length) continue; th = typeOf(B).in[0]; }
    const implicit = IMPLICIT.has(l.from_port) || IMPLICIT.has(l.to_port);
    const via = l.via ? by[l.via] : null;
    const st = wireOn.value ? wire.value[l.id] : null;
    const lab = [via ? '🚚 ' + (via.name || via.id) : '', l.products?.length ? l.products.join('/') : '', l.cond ? $t('graphView.if0', [condLabel(l.cond)]) : '', l.weight ? `×${l.weight}` : '',
      st ? `${st.rate}/h${st.q ? $t('graphView.queued') + st.q : ''}` : ''].filter(Boolean).join(' · ');
    const tr = traceEdges.value.has(l.from + '>' + l.to);
    const hl = ed.highlight.includes(l.id), sel = ed.selLink === l.id;
    out.push({ id: l.id, source: s, target: t, sourceHandle: sh, targetHandle: th, type: 'smoothstep', label: lab || undefined,
      markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 }, animated: !!via, selected: sel, interactionWidth: 14,
      class: ['e', implicit ? 'e-imp' : '', via ? 'e-via' : '', l.from_port === 'ng' ? 'e-ng' : '', hl ? 'e-hl' : '', sel ? 'e-sel' : '', tr ? 'e-tr' : '', st && st.q >= 5 ? 'e-busy' : ''].join(' '),
      labelBgPadding: [6, 3], labelBgBorderRadius: 4 });
  }
  for (const b of m.blocks || []) {
    const op = b.params?.operator; if (!op || !by[op] || col.has(b.group) || col.has(by[op].group)) continue;
    out.push({ id: 'op:' + b.id, source: op, target: b.id, sourceHandle: 'op-out', targetHandle: 'op-in', type: 'default', selectable: false, focusable: false, class: 'e e-op' });
  }
  return out;
});
/** Draw each signal wire as two edges (inputs enter the PLC on the left, outputs exit on the right); network cables connect at the top. Label channel counts / protocols. */
function ctlEdges(l: any) {
  const hl = ed.highlight.includes(l.id) || hoverLinks.value.has(l.id), sel = ed.selLink === l.id;
  const cls = (k: string) => ['e', k, hl ? 'e-hl' : '', sel ? 'e-sel' : ''].join(' ');
  const base = { type: 'smoothstep', selected: sel, interactionWidth: 14, labelBgPadding: [5, 2], labelBgBorderRadius: 4 };
  if (linkKind(l) === 'network') return [{ ...base, id: 'net:' + l.id, source: l.from, target: l.to, sourceHandle: 'net-s', targetHandle: 'net-t', type: 'straight', label: l.protocol || $t('common.network'), class: cls('e-net') }];
  const plc = layerOf(l.to) === 'control' ? l.to : l.from, dev = plc === l.to ? l.from : l.to;
  const nin = (l.signals || []).filter((x: any) => x.dir === 'in').length, nout = (l.signals || []).filter((x: any) => x.dir === 'out').length;
  const r: any[] = [];
  if (nin) r.push({ ...base, id: `sig:${l.id}:in`, source: dev, target: plc, sourceHandle: 'sig-out', targetHandle: 'sig-in', label: $t('graphView.n0Inputs', [nin]), class: cls('e-sig'), markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 } });
  if (nout) r.push({ ...base, id: `sig:${l.id}:out`, source: plc, target: dev, sourceHandle: 'sig-out', targetHandle: 'sig-in', label: $t('graphView.n0Outputs', [nout]), class: cls('e-sig'), markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 } });
  if (!nin && !nout) r.push({ ...base, id: `sig:${l.id}:in`, source: dev, target: plc, sourceHandle: 'sig-out', targetHandle: 'sig-in', label: $t('graphView.noSignalAssigned'), class: cls('e-sig') });
  return r;
}
/** Canvas edge index → model connection index (each signal wire is drawn as two edges). */
const realLink = (eid: string) => (eid.startsWith('sig:') ? eid.split(':')[1] : eid.startsWith('net:') ? eid.slice(4) : eid);
const hoverLinks = computed(() => (ed.hoverId ? relatedSet(ed.hoverId).links : new Set<string>()));
const miniColor = (n: any) => (n.type === 'block' ? typeOf(blocksById.value[n.id]).color : n.type === 'vgroup' ? 'rgba(20,99,214,.18)' : '#d9b54a');

// ---------- Selection ----------
function onNodesChange(chs: any[]) {
  const sel = new Set(ed.sel); let touched = false;
  for (const c of chs) if (c.type === 'select') { touched = true; if (c.selected) sel.add(c.id); else sel.delete(c.id); }
  if (!touched) return;
  const arr = [...sel];
  if (arr.join() !== ed.sel.join()) { ed.sel = arr; if (arr.length) ed.selLink = ''; }
}
function onEdgeClick(e: any) { if (e.edge.id.startsWith('op:')) return; ed.sel = []; ed.selLink = realLink(e.edge.id); }
function onPaneClick(e: MouseEvent) {
  if (ed.placing) { const f = screenToFlowCoordinate({ x: e.clientX, y: e.clientY }); placeAt(e, { node: [Math.round((f.x - CARD_W / 2) / 10) * 10, Math.round((f.y - 30) / 10) * 10] }); return; }
  ed.sel = []; ed.selLink = ''; if (Date.now() - add.at > 400) add.show = false;
}
/** Graph picking (e.g., "identify the bottleneck" assignments): when ed.pick exists, clicking a node submits the answer. */
function onNodeClick(e: any) {
  const id = e.node?.id; if (!ed.pick || !blocksById.value[id]) return;
  const pk = ed.pick; ed.pick = null; pk.onPick(id);
}

// ---------- Dragging ----------
let dragStart: Record<string, { x: number; y: number }> = {};
function onDragStart({ nodes: ns }: any) {
  dragStart = {};
  for (const n of ns) {
    dragStart[n.id] = { ...n.position };
    if (n.type === 'vgroup') for (const b of ed.model.blocks.filter((x: any) => x.group === n.id)) dragStart[b.id] ||= { x: b.node[0], y: b.node[1] };
  }
}
function onDrag({ nodes: ns }: any) {
  for (const n of ns) {
    if (n.type !== 'vgroup' || !dragStart[n.id]) continue;
    const dx = n.position.x - dragStart[n.id].x, dy = n.position.y - dragStart[n.id].y;
    for (const b of ed.model.blocks.filter((x: any) => x.group === n.id)) {
      if (ns.some((k: any) => k.id === b.id)) continue;
      const gn = findNode(b.id); if (gn) gn.position = { x: dragStart[b.id].x + dx, y: dragStart[b.id].y + dy };
    }
  }
}
function onDragStop({ nodes: ns }: any) {
  const ops: any[] = [], moved = new Set(ns.map((n: any) => n.id));
  const by = blocksById.value;
  for (const n of ns) {
    const x = Math.round(n.position.x), y = Math.round(n.position.y);
    if (by[n.id]) { if (by[n.id].node?.[0] !== x || by[n.id].node?.[1] !== y) ops.push({ op: 'update_block', id: n.id, set: { node: [x, y] } }); }
    else if (n.type === 'vgroup' && dragStart[n.id]) {
      const dx = x - Math.round(dragStart[n.id].x), dy = y - Math.round(dragStart[n.id].y);
      if (!dx && !dy) continue;
      for (const b of ed.model.blocks.filter((k: any) => k.group === n.id && !moved.has(k.id))) ops.push({ op: 'update_block', id: b.id, set: { node: [b.node[0] + dx, b.node[1] + dy] } });
      const g = ed.model.groups.find((k: any) => k.id === n.id);
      ops.push({ op: 'update_group', id: n.id, set: { node: [(g.node?.[0] || x) + dx, (g.node?.[1] || y) + dy] } });
    } else if (n.type === 'note') ops.push({ op: 'update_note', id: n.id, set: { node: [x, y] } });
  }
  if (ops.length) exec(ops, $t('graphView.moveCard'));
}

// ---------- Connections ----------
let connecting: any = null, connected = false;
function validConn(c: any) {
  const sh = String(c.sourceHandle), th = String(c.targetHandle);
  if (c.source === c.target || sh.startsWith('op') || th.startsWith('op')) return false;
  const ctl = (h: string) => h.startsWith('sig') || h.startsWith('net');
  return ctl(sh) === ctl(th);    // Material ports connect only to material ports; signal/network handles connect only to signal/network handles.
}
function onConnectStart(p: any) { connecting = p; connected = false; }
function onConnect(c: any) {
  connected = true;
  if (/^(sig|net)/.test(String(c.sourceHandle))) { if (!connectByLayer(c.source, c.target)) ElMessage.info($t('graphView.signalWiresConnectEquipmentTo')); return; }
  addLink(c.source, c.sourceHandle, c.target, c.targetHandle);
}
function onConnectEnd(e: any) {
  const ev = e?.clientX !== undefined ? e : e?.event?.clientX !== undefined ? e.event : e?.changedTouches?.[0];
  const c = connecting; connecting = null;
  if (!c || !ev) return;
  // The connect event may arrive after connect-end; wait one tick before checking whether a connection was made.
  setTimeout(() => {
    if (connected) return;
    // If released over another card (not a port), connect to its first compatible port.
    const over = document.elementFromPoint(ev.clientX, ev.clientY)?.closest('.vue-flow__node')?.getAttribute('data-id');
    const B = over && over !== c.nodeId ? blocksById.value[over] : null;
    if (B) {
      const t = typeOf(B);
      if (c.handleType === 'source' && t.in.length) { addLink(c.nodeId, c.handleId, B.id, t.in[0]); return; }
      if (c.handleType === 'target' && t.out.length) { addLink(B.id, t.out[0], c.nodeId, c.handleId); return; }
    }
    const r = host.value!.getBoundingClientRect();
    openAdd(ev.clientX - r.left, ev.clientY - r.top, { node: c.nodeId, handle: c.handleId, type: c.handleType });
  }, 30);
}
function linkOp(from: string, fp: string, to: string, tp: string, extra?: any) {
  const by = extra ? { ...blocksById.value, [extra.id]: extra } : blocksById.value, A = by[from], B = by[to];
  if (!A || !B || from === to) return null;
  if ((ed.model.links || []).some((l: any) => l.from === from && l.to === to && (l.from_port || 'out') === fp && (l.to_port || 'in') === tp)) return null;
  const link: any = { id: newId('L'), kind: 'material', from, from_port: fp || 'out', to, to_port: tp || 'in' };
  if (A.type === 'buffer' && B.type === 'buffer') {
    const tr = ed.model.blocks.find((b: any) => b.type === 'transporter');
    if (tr) link.via = tr.id; else ElMessage.warning($t('graphView.transportBetweenTwoBuffersRequires'));
  }
  return { op: 'add_link', link };
}
function addLink(from: string, fp: string, to: string, tp: string) {
  const op = linkOp(from, fp, to, tp); if (!op) return;
  exec([op], $t('common.connections')); ed.sel = []; ed.selLink = op.link.id;
}

// ---------- Quick add ----------
const add = reactive<any>({ show: false, x: 0, y: 0, q: '', pending: null, flow: [0, 0], at: 0 });
const addList = computed(() => {
  const q = add.q.trim().toLowerCase();
  return Object.entries(ed.cat?.types || {}).map(([key, t]: any) => ({ key, ...t }))
    .filter((t: any) => !add.pending || (add.pending.type === 'source' ? t.in.length : t.out.length))
    .filter((t: any) => !q || t.label.toLowerCase().includes(q) || t.key.includes(q) || t.cat.includes(q) || (t.help || '').includes(q))
    .sort((a: any, b: any) => Number(a.legacy) - Number(b.legacy)).slice(0, 14);
});
function openAdd(x?: number, y?: number, pending: any = null) {
  const r = host.value!.getBoundingClientRect();
  if (x === undefined) { x = r.width / 2 - 120; y = r.height / 2 - 120; }
  add.x = Math.min(x, r.width - 260); add.y = Math.min(y!, r.height - 300); add.q = ''; add.pending = pending; add.show = true; add.at = Date.now();
  const f = screenToFlowCoordinate({ x: r.left + x, y: r.top + y! });
  add.flow = [Math.round(f.x / 10) * 10, Math.round(f.y / 10) * 10];
  nextTick(() => addInput.value?.focus());
}
/** "+" on the card's right: add and connect equipment downstream. */
function onNodePlus(e: any) {
  const { id, port } = e.detail || {}; const r = host.value?.getBoundingClientRect();
  const el = document.querySelector(`.vue-flow__node[data-id="${id}"]`)?.getBoundingClientRect(); if (!r || !el) return;
  openAdd(Math.min(el.right - r.left + 14, r.width - 270), el.top - r.top, { node: id, handle: port || 'out', type: 'source' });
  const B = blocksById.value[id]; if (B) add.flow = [Math.round(((B.node?.[0] || 0) + 290) / 10) * 10, Math.round((B.node?.[1] || 0) / 10) * 10];
}
addEventListener('vf:node-plus', onNodePlus);
onUnmounted(() => removeEventListener('vf:node-plus', onNodePlus));
function addType(key: string, node = add.flow) {
  const b = makeBlock(key, planPosNear(node), node);
  const ops: any[] = [{ op: 'add_block', block: b }];
  const p = add.pending, t = typeOf(b);
  add.show = false;
  if (p) {
    const op = p.type === 'source' ? linkOp(p.node, p.handle || 'out', b.id, t.in[0], b) : linkOp(b.id, t.out[0], p.node, p.handle || 'in', b);
    if (op) ops.push(op);
  }
  exec(ops, (ops.length > 1 ? $t('graphView.addAndConnect') : $t('common.add2')) + t.label);
  select([b.id]); flash([b.id], 1500);
}
/** On open: fit all content if readable; for long lines, start at the beginning and keep cards readable. */
// On first open, fit all content (zoomed-out cards show only large names and status; see .gv.lod styles for semantic zoom instead of clipping half the graph for font size).
const zoom = computed(() => viewport.value?.zoom ?? 1), showMini = ref(false);
async function onReady() {
  await nextTick();
  await fitView({ padding: 0.08, maxZoom: 1 });
}
defineExpose({ openAdd, fit: () => fitView({ padding: 0.15, duration: 300 }) });

// ---------- Drag from library ----------
function onDrop(e: DragEvent) {
  const type = e.dataTransfer?.getData('vf/type'), tpl = e.dataTransfer?.getData('vf/tpl');
  const f = screenToFlowCoordinate({ x: e.clientX, y: e.clientY });
  const node = [Math.round((f.x - CARD_W / 2) / 10) * 10, Math.round((f.y - 30) / 10) * 10];
  if (type) { add.pending = null; addType(type, node); return; }
  if (tpl) {
    const t = (ed.templates || []).find((x: any) => x.id === tpl); if (!t?.blocks?.length) return;
    const b0 = t.blocks[0], pos = planPosNear(node);
    const { ops, ids } = cloneOps(t.blocks, t.links || [], [pos[0] - b0.pos[0], pos[1] - b0.pos[1]], [node[0] - (b0.node?.[0] || 0), node[1] - (b0.node?.[1] || 0)]);
    exec(ops, $t('graphView.insertTemplate') + t.name); select(ids); flash(ids);
  }
}

// ---------- Context menu (shared menu + graph-specific editing actions) ----------
const menu = reactive<any>({ flow: [0, 0] });
let downAt: number[] | null = null;
function onDown(e: MouseEvent) {
  if (e.button === 2) downAt = [e.clientX, e.clientY];
  if (!(e.target as HTMLElement).closest('.qa') && e.button === 0 && !(e.target as HTMLElement).closest('.vue-flow__handle')) add.show = false;
}
function openMenu(e: MouseEvent, kind: string, id?: string) {
  e.preventDefault();
  if (downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 5) { downAt = null; return; }   // Right-drag to pan
  const r = host.value!.getBoundingClientRect();
  const f = screenToFlowCoordinate({ x: e.clientX, y: e.clientY });
  menu.flow = [Math.round(f.x), Math.round(f.y)];
  add.show = false;
  if (kind === 'node' && id) {
    if (!blocksById.value[id]) return;
    if (!ed.sel.includes(id)) select([id]);
    openBlockMenu(e, id, 'graph', [
      ...(selBlocks.value.length ? [{ label: $t('graphView.moveToNewGroup'), kbd: 'Ctrl+G', run: groupSel }] : []),
      ...(selBlocks.value.some((b: any) => b.group) ? [{ label: $t('graphView.removeFromGroup'), run: ungroup }] : []),
      ...(selBlocks.value.length ? [{ label: $t('common.saveAsTemplate'), run: () => emit('template') }] : []),
    ]);
  } else if (kind === 'edge' && id) {
    if (id.startsWith('op:')) return;
    ed.sel = []; ed.selLink = realLink(id);
    openLinkMenu(e, realLink(id));
  } else {
    openPaneMenu(e, [
      { label: $t('graphView.addBlock'), kbd: 'Tab', run: () => openAdd(e.clientX - r.left, e.clientY - r.top) },
      { label: $t('graphView.addNote'), run: addNote },
      { label: $t('graphView.autoLayout'), run: autoLayout },
      { label: $t('common.fitAll'), kbd: 'Home', run: () => fitView({ padding: 0.15, duration: 300 }) },
    ], { node: menu.flow, pos: planPosNear(menu.flow) });
  }
}
function addNote() {
  const id = newId('N');
  exec([{ op: 'add_note', note: { id, text: '', node: menu.flow, size: [220, 90] } }], $t('graphView.addNote'));
}
function ungroup() { exec(selBlocks.value.filter((b: any) => b.group).map((b: any) => ({ op: 'update_block', id: b.id, set: { group: null } })), $t('graphView.removeFromGroup')); }


// ---------- Live flow on edges (parts/hour over the last hour) and queued parts ----------
const wireOn = ref(true), wire = ref<Record<string, any>>({});
let wireTimer: any = null, flowTimer: any = null, rates: Record<string, number> = {};
function refreshWire() {
  const buf = ed.runtime?.kpi?.buffers || {}, out: Record<string, any> = {};
  for (const l of ed.model?.links || []) {
    const by = blocksById.value, A = by[l.from], B = by[l.to];
    const q = buf[l.id] ?? buf[l.id + '@b'] ?? (B?.type === 'buffer' ? buf[B.id] : A?.type === 'buffer' ? buf[A.id] : undefined);
    // Flow is measured "machine to machine" (skipping buffers): edges connected to a buffer sum all flow through it.
    const links = ed.model?.links || [];
    const succ = (bid: string) => links.filter((x: any) => x.from === bid).map((x: any) => x.to);
    const pred = (bid: string) => links.filter((x: any) => x.to === bid).map((x: any) => x.from);
    const sum = (pairs: string[]) => { const v = pairs.map((k) => rates[k]).filter((x) => x !== undefined); return v.length ? v.reduce((a, b) => a + b, 0) : undefined; };
    const rate = B?.type === 'buffer' && A?.type !== 'buffer' ? sum(succ(B.id).map((x: string) => l.from + '>' + x))
      : A?.type === 'buffer' && B?.type !== 'buffer' ? sum(pred(A.id).map((x: string) => x + '>' + l.to)) : rates[l.from + '>' + l.to];
    if (q !== undefined || rate !== undefined) out[l.id] = { q: q || 0, rate: rate ?? 0 };
  }
  wire.value = out;
}
async function refreshRates() {
  if (!wireOn.value || !ed.pid) return;
  const r = await get(`${P(ed.pid)}/analysis/sankey?hours=1&level=block`, true).catch(() => null);
  if (!r) return;
  const nm = (x: any) => String(typeof x === 'number' ? r.nodes?.[x]?.name : x).replace(/\s*↺.*$/, '');
  const next: Record<string, number> = {};
  for (const k of r.links || []) next[nm(k.source) + '>' + nm(k.target)] = Math.round(k.value);   // Parts in the last hour = parts/hour
  rates = next; refreshWire();
}
onMounted(() => { wireTimer = setInterval(refreshWire, 2000); flowTimer = setInterval(refreshRates, 30000); refreshRates(); });
onUnmounted(() => { clearInterval(wireTimer); clearInterval(flowTimer); });

// ---------- Part tracking: highlight visited machines and edges from history, with step-through support ----------
const traceStep = computed(() => ed.partTrace?.steps?.[ed.partTrace.i]);
const traceNodes = computed(() => new Set<string>((ed.partTrace?.steps || []).slice(0, (ed.partTrace?.i ?? -1) + 1).map((x: any) => x.station)));
const traceEdges = computed(() => {
  const st = (ed.partTrace?.steps || []).slice(0, (ed.partTrace?.i ?? -1) + 1).map((x: any) => x.station), out = new Set<string>();
  for (let i = 1; i < st.length; i++) if (st[i] !== st[i - 1]) out.add(st[i - 1] + '>' + st[i]);
  return out;
});
watch(() => traceStep.value?.station, (sid) => { if (sid && blocksById.value[sid]) { const b = blocksById.value[sid]; setCenter(b.node[0] + CARD_W / 2, b.node[1] + 60, { zoom: Math.max(getViewport().zoom, 0.8), duration: 300 }); } });

// ---------- Double-click: enter submodels, open the unit editor for control units, locate other objects ----------
const scope = ref<any>(null);
const scopeNodes = computed(() => (scope.value?.blocks || []).map((b: any, i: number) => ({ id: 'sub:' + b.id, type: 'block', position: { x: b.node?.[0] ?? i * 260, y: b.node?.[1] ?? 0 },
  data: { sub: b }, draggable: false, connectable: false })));
const scopeEdges = computed(() => (scope.value?.links || []).map((l: any) => ({ id: 'sub:' + l.id, source: 'sub:' + l.from, target: 'sub:' + l.to, sourceHandle: l.from_port || 'out',
  targetHandle: l.to_port || 'in', type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16 }, class: 'e' })));
async function onNodeDbl(e: any) {
  const b = blocksById.value[e.node.id];
  if (b?.type === 'submodel') {
    const r = await get(`${P(ed.pid)}/submodels`, true).catch(() => null);
    const def = (r?.defs || r || []).find?.((d: any) => d.id === b.params?.def) || (r?.defs || {})[b.params?.def];
    if (def) { scope.value = { name: $t('common.n012', [b.name, def.name || b.params.def]), blocks: def.blocks || [], links: def.links || [] }; setTimeout(() => fitView({ padding: 0.2 }), 100); return; }
    ElMessage.warning($t('graphView.submodelDefinitionNotFound'));
    return;
  }
  if (b?.type === 'cell') { ed.leftPanel = 'cell-editor'; ed.leftOpen = true; select([b.id]); return; }
  focusOn(e.node.id);
}

// ---------- Auto-layout: layer by material flow (longest path), sort within layers by average upstream position ----------
function autoLayout() {
  const bs = (ed.model.blocks || []).filter((b: any) => !['operators', 'transporter'].includes(b.type));
  const ids = new Set(bs.map((b: any) => b.id));
  const links = (ed.model.links || []).filter((l: any) => ids.has(l.from) && ids.has(l.to) && l.from !== l.to && l.from_port !== 'ng');
  const pred: Record<string, string[]> = {}, succ: Record<string, string[]> = {};
  for (const b of bs) { pred[b.id] = []; succ[b.id] = []; }
  for (const l of links) { pred[l.to].push(l.from); succ[l.from].push(l.to); }
  const layer: Record<string, number> = {}, visiting = new Set<string>();
  const depth = (id: string): number => {
    if (layer[id] !== undefined) return layer[id];
    if (visiting.has(id)) return 0;                     // Break rework loops
    visiting.add(id);
    const d = pred[id].length ? Math.max(...pred[id].map((p) => depth(p) + 1)) : 0;
    visiting.delete(id); layer[id] = d; return d;
  };
  bs.forEach((b: any) => depth(b.id));
  const cols: Record<number, string[]> = {};
  for (const b of bs) (cols[layer[b.id]] ||= []).push(b.id);
  const order: Record<string, number> = {};
  for (const L of Object.keys(cols).map(Number).sort((a, b) => a - b)) {
    cols[L].sort((a, b) => {
      const ka = pred[a].length ? pred[a].reduce((t, p) => t + (order[p] ?? 0), 0) / pred[a].length : 0;
      const kb = pred[b].length ? pred[b].reduce((t, p) => t + (order[p] ?? 0), 0) / pred[b].length : 0;
      return ka - kb || a.localeCompare(b, 'en', { numeric: true });
    });
    cols[L].forEach((id, i) => { order[id] = i; });
  }
  const ops: any[] = [];
  // Stack cards in each column by actual height plus spacing; center the column on 0 to prevent overlap.
  const H = (id: string) => (findNode(id)?.dimensions?.height || 150) + 34;
  let bottom = 0;
  for (const L of Object.keys(cols).map(Number)) {
    const col = cols[L], total = col.reduce((t, id) => t + H(id), 0);
    let y = -total / 2;
    for (const id of col) { ops.push({ op: 'update_block', id, set: { node: [L * 290, Math.round(y / 10) * 10] } }); y += H(id); }
    bottom = Math.max(bottom, total / 2);
  }
  const others = (ed.model.blocks || []).filter((b: any) => !ids.has(b.id));
  others.forEach((b: any, i: number) => ops.push({ op: 'update_block', id: b.id, set: { node: [i * 260, Math.round((bottom + 80) / 10) * 10] } }));
  exec(ops, $t('graphView.autoLayout'));
  setTimeout(() => fitView({ padding: 0.12, duration: 300 }), 50);
}

// ---------- Locate ----------
watch(() => ed.focusReq, (r) => {
  if (!r || ed.view !== 'graph') return;
  if (!r.id) { fitView({ padding: 0.15, duration: 300 }); return; }
  const b = blocksById.value[r.id];
  const g = (ed.model.groups || []).find((x: any) => x.id === r.id);
  if (b) { if (b.group && collapsed.value.has(b.group)) exec([{ op: 'update_group', id: b.group, set: { collapsed: false } }], $t('common.expandGroup')); setCenter(b.node[0] + CARD_W / 2, b.node[1] + 60, { zoom: r.keepZoom ? getViewport().zoom : 1.1, duration: 400 }); }
  else if (g) { const bx = groupBox(g.id); if (bx) fitView({ nodes: [g.id], padding: 0.2, duration: 400 }); }
});
</script>
