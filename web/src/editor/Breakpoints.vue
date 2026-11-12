<template>
  <div class="bp">
    <div class="bp-h">{{ $t('breakpoints.conditionalSimulationBreakpoints') }} <small class="muted">{{ $t('breakpoints.theEntireFactoryPausesWhen') }}</small></div>
    <div class="bp-add">
      <el-select v-model="f.kind" size="small" style="width:150px">
        <el-option v-for="(v, k) in KINDS" :key="k" :value="k" :label="v" />
      </el-select>
      <el-select v-if="needsId" v-model="f.id" size="small" filterable :placeholder="f.kind === 'buffer' ? $t('breakpoints.bufferQueue') : f.kind === 'alarm' ? $t('breakpoints.anyEquipment') : $t('common.equipment')" clearable style="width:170px">
        <el-option v-for="o in idOptions" :key="o.id" :value="o.id" :label="o.label" />
      </el-select>
      <el-select v-if="['state', 'state_for'].includes(f.kind)" v-model="f.state" size="small" style="width:96px">
        <el-option v-for="(v, k) in STATE_CN" :key="k" :value="k" :label="v" />
      </el-select>
      <el-input-number v-if="f.kind === 'state_for'" v-model="f.minutes" size="small" :min="1" :controls="false" style="width:70px" /><span v-if="f.kind === 'state_for'" class="muted small">{{ $t('breakpoints.min') }}</span>
      <el-select v-if="f.kind === 'kpi'" v-model="f.key" size="small" style="width:110px"><el-option v-for="(v, k) in KPI" :key="k" :value="k" :label="v" /></el-select>
      <el-input v-if="f.kind === 'tag'" v-model="f.tag" size="small" :placeholder="$t('breakpoints.tagEGBathTemperature')" style="width:190px" />
      <el-select v-if="f.kind === 'event'" v-model="f.ekind" size="small" clearable :placeholder="$t('breakpoints.eventType')" style="width:110px"><el-option v-for="(v, k) in EK" :key="k" :value="k" :label="v" /></el-select>
      <template v-if="['buffer', 'kpi', 'tag'].includes(f.kind)">
        <el-select v-model="f.op" size="small" style="width:66px"><el-option v-for="o in ['<', '<=', '>', '>=', '==']" :key="o" :value="o" :label="o" /></el-select>
        <el-input-number v-model="f.value" size="small" :controls="false" style="width:80px" />
      </template>
      <el-input v-if="f.kind === 'time'" v-model="f.at" size="small" placeholder="YYYY-MM-DD HH:MM" style="width:150px" />
      <el-checkbox v-model="f.once" size="small">{{ $t('breakpoints.pauseOnce') }}</el-checkbox>
      <el-button size="small" type="primary" :disabled="!edit" @click="add"><el-icon><Plus /></el-icon> {{ $t('breakpoints.addBreakpoint') }}</el-button>
      <el-button size="small" :disabled="!edit" @click="runTo">{{ $t('breakpoints.runToThisCondition') }}</el-button>
    </div>
    <div v-for="b in list" :key="b.id" class="iss">
      <el-switch :model-value="b.enabled" size="small" :disabled="!edit" @change="(v: any) => toggle(b, v)" />
      <el-icon class="warn"><Flag /></el-icon><span>{{ b.name }}</span><small class="muted">{{ $t('breakpoints.hits01', [b.hits, b.once ? $t('breakpoints.pauseOnce2') : '']) }}</small>
      <span class="grow" /><el-button size="small" text type="danger" :disabled="!edit" @click="remove(b)"><el-icon><Delete /></el-icon></el-button>
    </div>
    <p v-if="!list.length" class="muted small">{{ $t('breakpoints.noBreakpointsYetWhenA') }}<br>{{ $t('breakpoints.theQuickestWayInThe') }}<b>{{ $t('breakpoints.rightClickEquipmentBreakpoint') }}</b>{{ $t('breakpoints.orSelectEquipmentAndPress') }} <b>F9</b>{{ $t('breakpoints.equipmentWithBreakpointsShowsA') }}</p>
    <!-- PLC program breakpoints (LD rungs / ST lines): separate from the simulation condition breakpoints above; pause only that PLC when hit -->
    <template v-if="plcBps.length || plcHalted.length">
      <div class="bp-h" style="margin-top:12px">{{ $t('breakpoints.plcBreakpoints') }} <small class="muted">{{ $t('breakpoints.clickARungOrLine') }}</small></div>
      <div v-for="h in plcHalted" :key="'h' + h.bid" class="iss halted">
        <el-icon class="bad"><VideoPause /></el-icon><span><b>{{ h.name }}</b> {{ $t('breakpoints.pausedAt0', [h.halt?.label || h.label]) }}</span><span class="grow" />
        <el-button size="small" :disabled="!edit" @click="plcAct(h.bid, { action: 'run' })">{{ $t('common.continue') }}</el-button>
        <el-button size="small" :disabled="!edit" @click="plcAct(h.bid, { action: 'step', kind: 'stmt' })">{{ $t('common.step') }}</el-button>
      </div>
      <div v-for="x in plcBps" :key="x.bid + ':' + (x.line ?? x.rung)" class="iss">
        <el-icon class="warn"><Cpu /></el-icon><span>{{ x.name }} · {{ x.label }}</span><span class="grow" />
        <el-button size="small" text type="danger" :disabled="!edit" @click="plcAct(x.bid, { action: 'breakpoint', ...(x.line !== undefined ? { line: x.line } : { rung: x.rung }), on: false })"><el-icon><Delete /></el-icon></el-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { canEdit, del, get, P, patch, post } from '../api';
import { ctl, ed, STATE_CN } from './store';

const edit = canEdit();
const KINDS: Record<string, string> = { state: $t('breakpoints.equipmentEntersState'), state_for: $t('breakpoints.equipmentTimeInStateExceeds'), alarm: $t('breakpoints.alarmOccurs'), buffer: $t('breakpoints.bufferPartCount'), kpi: $t('breakpoints.factoryWideMetric'), tag: $t('breakpoints.tagValue'), event: $t('breakpoints.eventOccurs'), time: $t('breakpoints.simTimeReaches') };
const KPI: Record<string, string> = { good: $t('common.acceptedQty'), scrap: $t('common.scrapped'), castings: $t('breakpoints.castingsIncoming'), machined: $t('common.machining'), shipped: $t('breakpoints.shipped'), escape: $t('breakpoints.missedInspection') };
const EK: Record<string, string> = { fault: $t('common.fault'), alarm: $t('common.alarm'), repair: $t('common.repair'), tool: $t('common.toolChange'), plan: $t('common.plan'), scenario: $t('common.scenario') };
const f = reactive<any>({ kind: 'state', id: '', state: 'Stopped', minutes: 5, key: 'good', op: '>=', value: 0, tag: '', ekind: 'fault', at: '', once: false });
const list = ref<any[]>([]);
const needsId = computed(() => ['state', 'state_for', 'alarm', 'buffer', 'tag', 'event'].includes(f.kind));
const idOptions = computed(() => {
  if (f.kind === 'buffer') return Object.keys(ed.runtime?.kpi?.buffers || {}).map((k) => ({ id: k, label: $t('breakpoints.n01Pcs', [k, ed.runtime.kpi.buffers[k]]) }));
  return (ed.model?.blocks || []).map((b: any) => ({ id: b.id, label: `${b.id} ${b.name}` }));
});
function cond() {
  const c: any = { kind: f.kind };
  if (needsId.value && f.id) c.id = f.id;
  if (['state', 'state_for'].includes(f.kind)) c.state = f.state;
  if (f.kind === 'state_for') c.minutes = f.minutes;
  if (f.kind === 'kpi') c.key = f.key;
  if (f.kind === 'tag') c.tag = f.tag;
  if (f.kind === 'event' && f.ekind) c.ekind = f.ekind;
  if (['buffer', 'kpi', 'tag'].includes(f.kind)) { c.op = f.op; c.value = f.value; }
  if (f.kind === 'time') c.at = f.at;
  return c;
}
async function load() { list.value = await get(P(ed.pid) + '/breakpoints', true).catch(() => []); loadPlc(); }
// PLC breakpoints (from the PLC layer's state API)
const plc = ref<any>({ cells: [] });
async function loadPlc() { plc.value = await get(P(ed.pid) + '/plc/status', true).catch(() => ({ cells: [] })); }
const plcBps = computed(() => (plc.value.cells || []).flatMap((c: any) => (c.bps || []).map((b: any) => ({ ...b, bid: c.bid, name: c.name }))));
const plcHalted = computed(() => (plc.value.cells || []).filter((c: any) => c.halt));
async function plcAct(bid: string, body: any) { await post(`${P(ed.pid)}/cells/${encodeURIComponent(bid)}/plc`, body); loadPlc(); }
let plcTimer: any = null;
async function add() {
  if (needsId.value && !f.id && f.kind !== 'alarm') { ElMessage.warning($t('breakpoints.selectEquipmentFirst')); return; }
  await post(P(ed.pid) + '/breakpoints', { cond: cond(), once: f.once }); load();
}
async function runTo() {
  const r = await ctl('run_to', { cond: cond(), hours: 24 });
  ElMessage.info($t('breakpoints.runInBackgroundUntil') + r.goal);
}
async function toggle(b: any, v: boolean) { await patch(`${P(ed.pid)}/breakpoints/${b.id}`, { enabled: v }); load(); }
async function remove(b: any) { await del(`${P(ed.pid)}/breakpoints/${b.id}`); load(); }
onMounted(() => { load(); addEventListener('vf:breakpoints-changed', load); plcTimer = setInterval(loadPlc, 2000); });
onUnmounted(() => { removeEventListener('vf:breakpoints-changed', load); clearInterval(plcTimer); });
defineExpose({ load });
</script>
