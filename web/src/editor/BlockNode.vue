<template>
  <div class="bn" :class="['ly-' + layer, { sel: selected, hl: ed.highlight.includes(id), rel: related, err: data.err, warn: data.warn, buf: b.type === 'buffer', small: !rows && layer === 'process', ctl: layer !== 'process' }]"
    :style="{ '--c': t.color }">
    <span v-if="bp" class="bn-bp" :class="bp" :title="bp === 'on' ? $t('blockNode.breakpointSetRightClickBreakpoint') : $t('blockNode.breakpointDisabled')" />
    <div class="bn-h">
      <el-icon class="bn-ic"><component :is="t.icon" /></el-icon>
      <b :title="b.name">{{ b.name }}</b>
      <span v-if="ed.overlay && rt" class="bn-st" :style="{ background: STATE_COLOR[rt.state] || '#888' }" :title="STATE_CN[rt.state] || rt.state" />
    </div>
    <div class="bn-sub"><span class="mono">{{ b.id }}</span> · {{ t.label }}<span v-if="t.legacy" class="bn-adv">{{ $t('blockNode.advanced') }}</span></div>
    <!-- Control layer / communications layer / information system equipment: show I/O channel counts, protocols, and status -->
    <div v-if="layer !== 'process'" class="bn-ctl">
      <template v-if="b.type === 'plc'">
        <div><span>{{ $t('common.input') }}</span><b class="mono">{{ $t('common.n0Channels', [sig.in]) }}</b><span>{{ $t('common.output') }}</span><b class="mono">{{ $t('common.n0Channels', [sig.out]) }}</b></div>
        <div><span>{{ $t('archView.control') }}</span><b>{{ $t('archView.n0Machines', [sig.devices]) }}</b><span v-if="plcState" class="bn-plcst" :class="plcState.state">{{ plcState.label || plcState.state }}</span></div>
      </template>
      <template v-else>
        <div><span>{{ $t('common.network') }}</span><b>{{ $t('blockNode.n0Connections', [netCount]) }}</b><span v-if="b.params?.ip" class="mono">{{ b.params.ip }}</span></div>
      </template>
    </div>
    <div class="bn-ports" v-if="rows">
      <div v-for="i in rows" :key="i" class="bn-row">
        <span class="pin" v-if="t.in[i - 1]">{{ PORT_CN[t.in[i - 1]] || t.in[i - 1] }}
          <Handle type="target" :position="Position.Left" :id="t.in[i - 1]" :class="['h', 'h-' + t.in[i - 1]]" /></span>
        <span v-else />
        <span class="pout" v-if="t.out[i - 1]">{{ PORT_CN[t.out[i - 1]] || t.out[i - 1] }}
          <Handle type="source" :position="Position.Right" :id="t.out[i - 1]" :class="['h', 'h-' + t.out[i - 1]]" /></span>
      </div>
    </div>
    <div class="bn-p" v-if="summary.length">
      <div v-for="s in summary" :key="s[0]"><span>{{ s[0] }}</span><b class="mono">{{ s[1] }}</b></div>
    </div>
    <div v-if="ed.overlay && rt" class="bn-rt">
      <template v-if="rt.alarm"><span class="bad">⚠ {{ rt.alarm }}</span></template>
      <template v-else-if="b.type === 'buffer' && rt.cap">
        <div class="bar"><i :style="{ width: Math.min(100, rt.count / rt.cap * 100) + '%' }" /></div><span class="mono">{{ rt.count }}/{{ rt.cap }}</span>
      </template>
      <template v-else>
        <span>{{ STATE_CN[rt.state] || rt.state }}</span>
        <span v-if="rt.oee" class="mono">OEE {{ (rt.oee.OEE * 100).toFixed(0) }}%</span>
        <span v-if="rt.stock !== undefined" class="mono">{{ $t('blockNode.inventory0', [rt.stock]) }}</span>
        <span v-if="rt.agvs" class="mono">{{ $t('blockNode.vehicles01', [rt.agvs.filter((a: any) => a.state !== 'Idle').length, rt.agvs.length]) }}</span>
      </template>
    </div>
    <div v-if="watch.length" class="bn-w" :title="$t('blockNode.watchesRightClickWatchValues')">
      <div v-for="w in watch" :key="w[0]"><el-icon><View /></el-icon><span>{{ w[0] }}</span><b class="mono">{{ w[1] }}</b></div>
    </div>
    <!-- Signal handles: bottom for production equipment (left out, right in), sides for PLCs (left in, right out); network handles at the top -->
    <template v-if="layer === 'process'">
      <Handle type="source" :position="Position.Bottom" id="sig-out" class="hs hs-out" :title="$t('blockNode.dragToAPlcTo')" />
      <Handle type="target" :position="Position.Bottom" id="sig-in" class="hs hs-in" />
    </template>
    <template v-else-if="b.type === 'plc' || b.type === 'hmi'">
      <Handle type="target" :position="Position.Left" id="sig-in" class="hs hs-plc-in" :title="$t('blockNode.equipmentInputSignals')" />
      <Handle type="source" :position="Position.Right" id="sig-out" class="hs hs-plc-out" :title="$t('blockNode.dragToEquipmentToConnect')" />
    </template>
    <template v-if="layer !== 'process'">
      <Handle type="source" :position="Position.Top" id="net-s" class="hn hn-s" :title="$t('blockNode.dragToASwitchGateway')" />
      <Handle type="target" :position="Position.Top" id="net-t" class="hn hn-t" />
    </template>
    <!-- "+": add and connect equipment downstream (click +, then choose a type) -->
    <button v-if="t.out.length && !data?.sub && canEdit()" class="bn-plus nodrag" :title="$t('blockNode.addEquipmentDownstream')" @click.stop="plus">+</button>
    <Handle type="target" :position="Position.Top" id="op-in" class="h-hidden" :connectable="false" />
    <Handle type="source" :position="Position.Bottom" id="op-out" class="h-hidden" :connectable="false" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { Handle, Position } from '@vue-flow/core';
import { computed } from 'vue';
import { bpMark, watchRows } from './shell/graphdebug';
import { relatedSet } from './shell/relations';
import { canEdit } from '../api';
import { blocksById, ed, PORT_CN, rtById, STATE_CN, STATE_COLOR, typeOf } from './store';

const props = defineProps<{ id: string; data: any; selected?: boolean }>();
const b = computed(() => props.data?.sub || blocksById.value[props.id] || { name: props.id, id: props.id, params: {} });
const t = computed(() => typeOf(b.value));
const rt = computed(() => rtById.value[props.id]);
const layer = computed(() => t.value.layer || 'process');
function plus() { window.dispatchEvent(new CustomEvent('vf:node-plus', { detail: { id: props.id, port: t.value.out[0] } })); }
// Subtly highlight related cards when hovering over an object.
const related = computed(() => !!ed.hoverId && ed.hoverId !== props.id && relatedSet(ed.hoverId).ids.has(props.id));
const sig = computed(() => {
  const ls = (ed.model?.links || []).filter((l: any) => l.kind === 'signal' && (l.to === props.id || l.from === props.id));
  const all = ls.flatMap((l: any) => l.signals || []);
  return { in: all.filter((x: any) => x.dir === 'in').length, out: all.filter((x: any) => x.dir === 'out').length, devices: new Set(ls.map((l: any) => (l.to === props.id ? l.from : l.to))).size };
});
const netCount = computed(() => (ed.model?.links || []).filter((l: any) => l.kind === 'network' && (l.to === props.id || l.from === props.id)).length);
const plcState = computed(() => (ed.plcStatus || {})[props.id]);
const bp = computed(() => (props.data?.sub ? '' : bpMark(props.id)));
const watch = computed(() => (props.data?.sub ? [] : watchRows(props.id)));
const rows = computed(() => Math.max(t.value.in.length, t.value.out.length));
const KEYS = ['time', 'interval', 'capacity', 'batch', 'parts', 'pieces', 'count', 'length_m', 'speed_mps', 'pod_pct', 'success_pct', 'cycle_s', 'operator', 'ship_every_h'];
const summary = computed(() => {
  const p = b.value.params || {}, out: [string, string][] = [];
  for (const k of KEYS) {
    const d = t.value.params[k];
    if (!d || p[k] === undefined || p[k] === '' || p[k] === null || (k === 'capacity' && b.value.type === 'processor' && p[k] === 1)) continue;
    let v = String(p[k]); if (v.length > 18) v = v.slice(0, 17) + '…';
    out.push([d.label, v + (d.unit ? ' ' + d.unit : '')]);
    if (out.length >= 3) break;
  }
  if (b.value.signals?.length) out.push([$t('blockNode.customTags'), $t('common.n02', [b.value.signals.length])]);
  return out;
});
</script>
