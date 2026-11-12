<template>
  <div class="ep">
    <div class="bar"><slot name="title"><b>{{ $t('energyPanel.energyElectricityCosts') }}</b></slot><span class="muted small" v-if="e">{{ e.from }} ~ {{ e.to }}</span><span class="grow" />
      <el-button size="small" @click="load" :loading="busy"><el-icon><Refresh /></el-icon></el-button>
      <el-button v-if="editable && canEdit()" size="small" @click="openSet">{{ $t('energyPanel.tariffEmissionsSettings') }}</el-button></div>
    <template v-if="e">
      <div class="grid g6 tiles">
        <div class="kpi"><small>{{ $t('common.power') }}</small><b>{{ Math.round(e.kwh) }}</b><i>{{ $t('energyPanel.kwhPerPart0', [e.kwh_per_good ?? '—']) }}</i></div>
        <div class="kpi"><small>{{ $t('energyPanel.electricityCostTimeOfUse') }}</small><b>{{ Math.round(e.cost) }}</b><i>{{ $t('energyPanel.cnyAverageRate0', [e.avg_price ?? '—']) }}</i></div>
        <div class="kpi warn"><small>{{ $t('energyPanel.n15MinutePeakDemand') }}</small><b>{{ e.peak_kw }}</b><i>kW · {{ e.peak_at || '—' }}</i></div>
        <div class="kpi"><small>{{ $t('energyPanel.monthlyDemandCharge') }}</small><b>{{ e.demand_cost_month }}</b><i>{{ $t('energyPanel.cny0CnyKwMonth', [e.settings.demand_price]) }}</i></div>
        <div class="kpi"><small>{{ $t('energyPanel.carbonEmissions') }}</small><b>{{ (e.co2_kg / 1000).toFixed(2) }}</b><i>{{ $t('energyPanel.tCo0KgKwh', [e.settings.co2_kg_per_kwh]) }}</i></div>
        <div class="kpi"><small>{{ $t('energyPanel.electricityCostPerPart') }}</small><b>{{ e.cost_per_good ?? '—' }}</b><i>{{ $t('energyPanel.cnyPartGoodParts0', [e.good]) }}</i></div>
      </div>
      <div class="grid g2" style="margin-top:12px">
        <div><div class="st">{{ $t('energyPanel.powerCurve15MinuteAverage') }}</div><Chart :option="curveOpt" :height="250" /></div>
        <div class="grid g2" style="gap:8px">
          <div><div class="st">{{ $t('energyPanel.byState') }}</div><Chart :option="clsOpt" :height="250" /></div>
          <div><div class="st">{{ $t('energyPanel.byTariffPeriod') }}</div><Chart :option="perOpt" :height="250" /></div>
        </div>
      </div>
      <div class="st" style="margin-top:10px">{{ $t('energyPanel.equipmentEnergyRankingByState') }}</div>
      <Chart :option="stOpt" :height="Math.max(200, Math.min(e.by_station.length, 15) * 22 + 50)" />
    </template>
    <el-dialog v-model="dlg" :title="$t('energyPanel.tariffEmissionsSettings')" width="min(620px, 96vw)" append-to-body>
      <p class="small muted">{{ $t('energyPanel.timeOfUseRatesVary') }}</p>
      <div v-for="(t, i) in s.tou" :key="i" class="r">
        <el-input v-model="t.name" size="small" style="width:70px" />
        <el-time-select v-model="t.start" start="00:00" step="00:30" end="24:00" size="small" style="width:105px" />–
        <el-time-select v-model="t.end" start="00:00" step="00:30" end="24:00" size="small" style="width:105px" />
        <el-input-number v-model="t.price" :step="0.05" :min="0" size="small" :controls="false" style="width:80px" /> {{ $t('energyPanel.cnyKwh') }}
        <el-button link type="danger" @click="s.tou.splice(i, 1)"><el-icon><Delete /></el-icon></el-button></div>
      <el-button size="small" @click="s.tou.push({ name: $t('energyPanel.standard'), start: '00:00', end: '08:00', price: 0.65 })">{{ $t('energyPanel.period') }}</el-button>
      <el-form label-width="150px" size="small" style="margin-top:10px">
        <el-form-item :label="$t('energyPanel.otherPeriodRate')"><el-input-number v-model="s.default_price" :step="0.05" :min="0" /> {{ $t('energyPanel.cnyKwh') }}</el-form-item>
        <el-form-item :label="$t('energyPanel.demandRate')"><el-input-number v-model="s.demand_price" :step="1" :min="0" /> {{ $t('energyPanel.cnyKwMonth') }}</el-form-item>
        <el-form-item :label="$t('energyPanel.gridEmissionsFactor')"><el-input-number v-model="s.co2_kg_per_kwh" :step="0.01" :min="0" /> kg CO₂/kWh</el-form-item>
      </el-form>
      <template #footer><el-button type="primary" @click="saveSet">{{ $t('common.save') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { CH } from '../design/chart';
/**
 * Energy panel (fetches its own data): props.pid identifies the factory; hours sets the lookback window (0 = all, warm-up excluded automatically); editable shows "Electricity and Carbon Settings".
 * Fetch data via GET /api/p/{pid}/analysis/energy; save settings via PUT /api/p/{pid}/energy/settings.
 */
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { canEdit, get, P, put } from '../api';
import Chart from './Chart.vue';

const props = withDefaults(defineProps<{ pid: string; hours?: number; warmup?: boolean; editable?: boolean }>(), { hours: 24, warmup: true, editable: true });
const e = ref<any>(null), busy = ref(false), dlg = ref(false);
const s = reactive<any>({ tou: [] });
const PER: Record<string, string> = { [$t('energyPanel.criticalPeak')]: CH.bad, [$t('energyPanel.peak')]: CH.amber, [$t('energyPanel.standard')]: CH.warn, [$t('energyPanel.offPeak')]: CH.ok };
const pc = (n: string, i = 0) => PER[n] || [CH.primary, CH.violet, CH.cyan][i % 3];
async function load() { busy.value = true; try { e.value = await get(`${P(props.pid)}/analysis/energy?hours=${props.hours}&warmup=${props.warmup ? 1 : 0}`); } finally { busy.value = false; } }
onMounted(load);
watch(() => [props.pid, props.hours, props.warmup], load);
function openSet() { Object.assign(s, JSON.parse(JSON.stringify(e.value.settings))); dlg.value = true; }
async function saveSet() { await put(`${P(props.pid)}/energy/settings`, s); dlg.value = false; load(); }
const curveOpt = computed(() => {
  const c = e.value.curve;
  const areas: any[] = [];
  let st = 0;
  for (let i = 1; i <= c.length; i++) {
    if (i === c.length || c[i].period !== c[st].period) { areas.push([{ xAxis: c[st].t, itemStyle: { color: pc(c[st].period) + '22' } }, { xAxis: c[i - 1].t }]); st = i; }
  }
  return { tooltip: { trigger: 'axis', formatter: (ps: any[]) => `${ps[0].axisValue}${$t('common.k459')}${c[ps[0].dataIndex].period}${$t('common.k460')}<br/>${ps[0].value} kW` },
    grid: { left: 50, right: 14, top: 14, bottom: 30 }, xAxis: { type: 'category', data: c.map((x: any) => x.t), axisLabel: { formatter: (v: string) => v.slice(6) } },
    yAxis: { type: 'value', name: 'kW' },
    series: [{ type: 'line', showSymbol: false, data: c.map((x: any) => x.kw), areaStyle: { opacity: 0.12 }, itemStyle: { color: CH.primary },
      markArea: { silent: true, data: areas }, markLine: { symbol: 'none', data: [{ yAxis: e.value.peak_kw, name: $t('energyPanel.peak2') }], lineStyle: { color: CH.bad, type: 'dashed' }, label: { position: 'insideEndTop', formatter: $t('energyPanel.peakCKw'), color: CH.bad } } }] };
});
const clsMeta = computed<Record<string, any>>(() => Object.fromEntries(e.value.classes.map((c: any) => [c.key, c])));
const clsOpt = computed(() => ({ tooltip: { formatter: $t('energyPanel.bBrCKwhD') },
  series: [{ type: 'pie', radius: ['26%', '48%'], label: { formatter: '{b}\n{d}%', fontSize: 11, overflow: 'none' }, labelLine: { length: 6, length2: 6 },
    data: Object.entries(e.value.by_cls).map(([k, v]) => ({ name: clsMeta.value[k]?.label || k, value: v, itemStyle: { color: clsMeta.value[k]?.color } })) }] }));
const perOpt = computed(() => ({ tooltip: { formatter: (p: any) => `${p.name}<br/>${e.value.kwh_by_period[p.name]} kWh · ${p.value} ${$t('energyPanel.cny')}` },
  series: [{ type: 'pie', radius: ['26%', '48%'], label: { formatter: $t('energyPanel.bCCny'), fontSize: 11, overflow: 'none' }, labelLine: { length: 6, length2: 6 },
    data: Object.entries(e.value.cost_by_period).map(([k, v], i) => ({ name: k, value: v, itemStyle: { color: pc(k, i) } })) }] }));
const stOpt = computed(() => {
  const rows = e.value.by_station.slice(0, 15);
  const keys = e.value.classes.filter((c: any) => rows.some((r: any) => r.by_cls[c.key]));
  return { tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } }, legend: { top: 0, textStyle: { fontSize: 11 } }, grid: { left: 140, right: 40, top: 28, bottom: 16 },
    xAxis: { type: 'value', name: 'kWh' }, yAxis: { type: 'category', inverse: true, data: rows.map((r: any) => r.name), axisLabel: { width: 130, overflow: 'truncate' } },
    series: keys.map((c: any) => ({ name: c.label, type: 'bar', stack: 'e', barMaxWidth: 16, itemStyle: { color: c.color }, data: rows.map((r: any) => r.by_cls[c.key] || 0) })) };
});
</script>

<style scoped>
.bar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; flex-wrap: wrap; }
.st { font-size: 12.5px; color: var(--hm-text-2); margin-bottom: 2px; }
.tiles .kpi b { font-size: 19px; }
.r { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; flex-wrap: wrap; }
@media (max-width: 1100px) { .g6 { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) { .g6, .g2 { grid-template-columns: 1fr 1fr; } }
</style>
