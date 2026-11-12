<template>
  <div class="fp">
    <p class="small muted" style="margin-top:0">{{ $t('forkPanel.createTwoCopiesOfThe') }}<b>{{ $t('forkPanel.rightNow') }}</b>{{ $t('forkPanel.wipEquipmentStatesFailuresShift') }}</p>
    <el-form inline size="small">
      <el-form-item :label="$t('forkPanel.simulationHorizon')"><el-input-number v-model="f.hours" :min="0.5" :max="72" :step="1" /> {{ $t('common.hours') }}</el-form-item>
      <el-form-item :label="$t('forkPanel.replications')"><el-input-number v-model="f.reps" :min="1" :max="10" /> {{ $t('forkPanel.times') }}</el-form-item>
    </el-form>
    <div v-for="(c, i) in f.changes" :key="i" class="cr">
      <el-select v-model="c.type" size="small" style="width:110px" @change="onType(c)"><el-option v-for="(n, k) in CT" :key="k" :label="n" :value="k" /></el-select>
      <template v-if="c.type !== 'buffer'">
        <el-select v-model="c.station" size="small" filterable :placeholder="$t('common.equipment')" style="width:170px" @change="loadTags(c.station)">
          <el-option v-for="s in stations" :key="s.id" :label="`${s.id} ${s.name}`" :value="s.id" /></el-select></template>
      <template v-if="c.type === 'param'">
        <el-select v-model="c.key" size="small" filterable allow-create :placeholder="$t('common.parameters')" style="width:150px">
          <el-option v-for="(n, k) in keysOf(c.station)" :key="k" :label="$t('common.n012', [n, k])" :value="k" /></el-select>
        <el-input v-model="c.value" size="small" style="width:120px" :placeholder="$t('forkPanel.valueOrExpression')" /></template>
      <template v-else-if="c.type === 'setpoint'">
        <el-select v-model="c.tag" size="small" filterable style="width:190px"><el-option v-for="t in tagsOf[c.station] || []" :key="t" :label="t" :value="t" /></el-select>
        <el-input v-model="c.value" size="small" style="width:90px" :placeholder="$t('common.value')" /></template>
      <template v-else-if="c.type === 'fault'">
        <el-select v-model="c.kind" size="small" style="width:190px"><el-option v-for="(n, k) in faultsOf(c.station)" :key="k" :label="n" :value="k" /></el-select></template>
      <template v-else-if="c.type === 'enable'"><el-switch v-model="c.value" :active-text="$t('common.running')" :inactive-text="$t('common.disabled')" /></template>
      <template v-else-if="c.type === 'buffer'">
        <el-select v-model="c.name" size="small" filterable style="width:170px"><el-option v-for="(n, k) in buffers" :key="k" :label="$t('forkPanel.n0Current1', [k, n])" :value="k" /></el-select>
        <el-input-number v-model="c.value" :min="1" size="small" /></template>
      <el-button link type="danger" @click="f.changes.splice(i, 1)"><el-icon><Close /></el-icon></el-button>
    </div>
    <div class="acts"><el-button size="small" @click="f.changes.push({ type: 'param', station: stations[0]?.id, key: '', value: '' })">{{ $t('forkPanel.change') }}</el-button><span class="grow" />
      <el-button type="primary" size="small" :loading="busy" :disabled="!canEdit()" @click="run">{{ $t('common.runWhatIfFromHere') }}</el-button></div>
    <template v-if="r">
      <div class="concl" style="margin-top:12px">{{ r.text }}<span class="muted small">&emsp;{{ $t('forkPanel.n0ReplicationsCompletedIn1', [r.reps, r.wall_s]) }}</span>
        <div v-for="e in r.errors" :key="e" class="bad small">{{ $t('forkPanel.changeNotApplied0', [e]) }}</div></div>
      <el-table :data="r.rows.filter((x: any) => SHOW.includes(x.key))" size="small" style="margin-top:8px">
        <el-table-column :label="$t('common.kpi')" min-width="110"><template #default="{ row }">{{ row.label }}<span class="muted small" v-if="row.unit"> {{ row.unit }}</span></template></el-table-column>
        <el-table-column :label="$t('forkPanel.continueAsIs')" align="right" min-width="120"><template #default="{ row }"><span class="mono">{{ v(row.base, row.key) }}</span></template></el-table-column>
        <el-table-column :label="r.name" align="right" min-width="120"><template #default="{ row }"><b class="mono">{{ v(row.whatif, row.key) }}</b></template></el-table-column>
        <el-table-column :label="$t('common.change')" align="right" min-width="110"><template #default="{ row }">
          <span v-if="row.rel != null" :class="row.rel * row.better > 0.005 ? 'ok' : row.rel * row.better < -0.005 ? 'bad' : 'muted'">{{ row.rel > 0 ? '+' : '' }}{{ (row.rel * 100).toFixed(1) }}%</span>
          <span v-if="r.reps > 1" class="small muted">{{ row.significant ? $t('forkPanel.significant') : $t('forkPanel.notSignificant') }}</span></template></el-table-column>
      </el-table>
      <Chart :option="curveOpt" :height="230" style="margin-top:8px" />
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { CH } from '../design/chart';
/**
 * Fork-from-now panel. props.pid identifies the factory; initial prefills changes (e.g. from "Project This Change" in the details panel: [{type:'param',station,key,value}]).
 * Calls POST /api/p/{pid}/fork; emits done(result).
 */
import { computed, onMounted, reactive, ref } from 'vue';
import { canEdit, get, P, post } from '../api';
import Chart from './Chart.vue';

const props = withDefaults(defineProps<{ pid: string; initial?: any[]; hours?: number }>(), { initial: () => [], hours: 4 });
const emit = defineEmits(['done']);
const CT: Record<string, string> = { param: $t('forkPanel.changeParameter'), setpoint: $t('common.writeSetpoint'), fault: $t('common.injectFailure'), enable: $t('forkPanel.disableEnable'), buffer: $t('forkPanel.bufferCapacity') };
const SHOW = ['good', 'good_per_h', 'scrap_rate', 'wip_avg', 'lead_mean', 'energy_total', 'energy_cost', 'peak_kw'];
const f = reactive<any>({ hours: props.hours, reps: 1, changes: JSON.parse(JSON.stringify(props.initial)) });
const stations = ref<any[]>([]), buffers = ref<any>({}), editable = ref<any>({}), catalog = ref<any>({}), tagsOf = reactive<Record<string, string[]>>({});
const busy = ref(false), r = ref<any>(null);
onMounted(async () => {
  const m = await get(P(props.pid) + '/meta');
  stations.value = m.stations.filter((s: any) => !['crew', 'agv'].includes(s.kind)); buffers.value = m.buffers || {}; editable.value = m.editable || {};
  try { catalog.value = (await get('/api/catalog', true)).types || {}; } catch { /* Use generic keys only when no catalog is available */ }
});
function keysOf(sid: string) {
  const s = stations.value.find((x: any) => x.id === sid);
  const t = catalog.value[s?.type];
  const out: Record<string, string> = {};
  if (t) for (const [k, p] of Object.entries<any>(t.params)) if (['num', 'int', 'expr', 'bool'].includes(p.t)) out[k] = p.label;
  return Object.keys(out).length ? out : editable.value;
}
const faults = reactive<Record<string, any>>({});
function faultsOf(sid: string) { return { failure: $t('forkPanel.equipmentFailureDowntime'), ...(faults[sid] || {}), clear: $t('common.clearFailure') }; }
async function loadTags(sid: string) {
  if (sid && !tagsOf[sid]) { const s = await get(`${P(props.pid)}/station/${sid}`); tagsOf[sid] = Object.entries(s.tags).filter(([, x]: any) => x.w).map(([k]) => k); faults[sid] = s.faults || {}; }
}
function onType(c: any) { if (c.type === 'enable' && typeof c.value !== 'boolean') c.value = false; if (c.type === 'fault' && !c.kind) c.kind = 'failure'; loadTags(c.station); }
async function run() {
  busy.value = true;
  try { r.value = await post(P(props.pid) + '/fork', f); emit('done', r.value); } finally { busy.value = false; }
}
const v = (c: any, k: string) => (c.mean == null ? '—' : k === 'scrap_rate' ? (c.mean * 100).toFixed(2) + '%' : Math.abs(c.mean) >= 100 || Number.isInteger(c.mean) ? Math.round(c.mean) : (+c.mean).toFixed(2))
  + (c.half != null ? ` ±${k === 'scrap_rate' ? (c.half * 100).toFixed(2) + '%' : (+c.half).toFixed(c.half >= 10 ? 0 : 2)}` : '');
const curveOpt = computed(() => ({ title: { text: $t('forkPanel.cumulativeGoodOutputPcs'), textStyle: { fontSize: 12 } }, tooltip: { trigger: 'axis' }, legend: { top: 0, right: 0 },
  grid: { left: 46, right: 14, top: 30, bottom: 26 }, xAxis: { type: 'category', data: r.value.base.curve.map((x: any) => x.t.slice(6)) }, yAxis: { type: 'value' },
  series: [{ name: $t('forkPanel.continueAsIs'), type: 'line', showSymbol: false, data: r.value.base.curve.map((x: any) => x.good), itemStyle: { color: CH.offline } },
    { name: r.value.name, type: 'line', showSymbol: false, data: r.value.whatif.curve.map((x: any) => x.good), itemStyle: { color: CH.primary } }] }));
</script>

<style scoped>
.cr { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
.acts { display: flex; align-items: center; gap: 8px; }
.concl { background: var(--hm-surface-2); border: 1px solid var(--hm-border); color: var(--hm-text-2); border-radius: var(--hm-r-md); padding: 10px 12px; line-height: 1.8; }
</style>
