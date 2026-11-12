<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('common.runReports') }}</h2>
      <TimeRangePicker v-model:hours="hours" v-model:warmup="warm" :win="r ? { from: r.from, to: r.to, hours: r.hours } : null" size="default" />
      <span class="grow" />
      <el-button @click="download(`${api}/report.xlsx?${qs}`)"><el-icon><Download /></el-icon>&nbsp;Excel</el-button>
      <el-button @click="download(`${api}/report/print?${qs}`)"><el-icon><Printer /></el-icon>&nbsp;PDF</el-button></div>
    <el-tabs v-model="tab" class="rtabs">
      <el-tab-pane :label="$t('livePanel.overview')" name="sum" />
      <el-tab-pane :label="$t('common.bottleneck')" name="bn" />
      <el-tab-pane :label="$t('analysisDock.timeBreakdown')" name="time" />
      <el-tab-pane :label="$t('analysisDock.materialFlow')" name="flow" />
      <el-tab-pane :label="$t('analysisDock.ganttChart')" name="gantt" />
      <el-tab-pane :label="$t('analysisDock.energy')" name="energy" />
    </el-tabs>
    <template v-if="r && tab === 'sum'">
      <div class="grid g6">
        <div class="kpi"><small>{{ $t('reports.pouredReceived') }}</small><b>{{ r.castings }}</b></div><div class="kpi ok"><small>{{ $t('common.acceptedQty') }}</small><b>{{ r.good }}</b><i>{{ $t('reports.n0PcsH', [r.good_per_h]) }}</i></div>
        <div class="kpi" :class="r.scrap_rate > 0.03 ? 'bad' : ''"><small>{{ $t('common.scrapRate') }}</small><b>{{ pct(r.scrap_rate, 2) }}</b><i>{{ $t('reports.scrap0', [r.scrap]) }}</i></div>
        <div class="kpi"><small>{{ $t('common.power') }}</small><b>{{ Math.round(r.energy_total) }}</b><i>{{ $t('home.kwhPerTonne0', [r.kwh_per_t ?? '—']) }}</i></div>
        <div class="kpi"><small>{{ $t('experiments.averageProductionCycleTime') }}</small><b>{{ r.lead.mean_h ?? '—' }}</b><i>h · P90 {{ r.lead.p90_h ?? '—' }}</i></div>
        <div class="kpi"><small>{{ $t('experiments.averageWip') }}</small><b>{{ r.wip_avg }}</b><i>{{ $t('reports.pcsPeak0SampledEvery', [r.wip_max ?? '—']) }}</i></div>
      </div>
      <div class="card concl" style="margin-top:14px"><h3>{{ $t('reports.conclusion') }}</h3><div v-for="f in r.findings" :key="f">· {{ f }}</div></div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h3>{{ $t('reports.hourlyThroughput') }} <small>{{ $t('common.pcs') }}</small></h3><Chart :option="hourOpt" :height="270" /></div>
        <div class="card"><h3>{{ $t('common.bottleneck') }} <small>{{ $t('reports.activePeriodMethodOpenThe') }}</small></h3><BottleneckPanel :data="r.bottleneck_analysis" compact :top="6" :height="210" /></div>
      </div>
      <div class="grid g4" style="margin-top:14px">
        <div class="card"><h3>{{ $t('reports.wip') }} <small>{{ $t('reports.hourlyAveragePcs') }}</small></h3><Chart :option="wipOpt" :height="220" /></div>
        <div class="card"><h3>{{ $t('reports.productionLeadTimeDistribution') }} <small>{{ $t('reports.fromProductionStartToInventory') }}</small></h3><Chart :option="leadOpt" :height="220" /></div>
        <div class="card"><h3>{{ $t('common.scrapReason') }}</h3><Chart :option="scrapOpt" :height="220" /></div>
        <div class="card"><h3>{{ $t('reports.energyByZone') }}</h3><Chart :option="enOpt" :height="220" /></div>
      </div>
    </template>
    <div class="card" v-if="r && tab === 'bn'"><h3>{{ $t('common.bottleneckAnalysis') }} <small>{{ $t('reports.n012TimeWith', [r.bottleneck_analysis.method_label, r.from, r.to, r.bottleneck_analysis.production_h]) }}</small></h3>
      <BottleneckPanel :data="r.bottleneck_analysis" :top="12" /></div>
    <div class="card" v-if="tab === 'time' && st"><h3>{{ $t('reports.equipmentTimeBreakdown') }} <small>{{ $t('reports.n012Hours3', [st.from, st.to, st.hours, warm && st.warmup_h ? $t('reports.warmUpExcluded0Hours', [st.warmup_h]) : '']) }}</small><span class="grow" />
      <el-checkbox v-model="passive" size="small">{{ $t('reports.includesBuffersSourcesSinksEtc') }}</el-checkbox></h3>
      <div class="grid g6 tiles">
        <div class="kpi ok"><small>{{ $t('common.acceptedQty') }}</small><b>{{ st.plant.good }}</b><i>{{ $t('reports.n0PcsH', [st.plant.good_per_h]) }}</i></div>
        <div class="kpi"><small>{{ $t('experiments.averageWip') }}</small><b>{{ st.plant.wip_avg }}</b><i>{{ $t('reports.peak0SampledEveryMinute', [st.plant.wip_max ?? '—']) }}</i></div>
        <div class="kpi"><small>{{ $t('experiments.averageProductionCycleTime') }}</small><b>{{ st.plant.lead_mean_h ?? '—' }}</b><i>h · P50 {{ st.plant.lead_p50_h ?? '—' }} · P90 {{ st.plant.lead_p90_h ?? '—' }}</i></div>
        <div class="kpi"><small>{{ $t('common.avgOee') }}</small><b>{{ pct(st.plant.oee_avg, 1) }}</b><i>{{ $t('reports.processingEquipment') }}</i></div>
        <div class="kpi"><small>{{ $t('common.scrapRate') }}</small><b>{{ pct(st.plant.scrap_rate, 2) }}</b><i>{{ $t('reports.scrap0', [st.plant.scrap]) }}</i></div>
        <div class="kpi bad"><small>{{ st.bottleneck?.tie ? $t('sections.tiedBottlenecks') : $t('common.bottleneck') }}</small><b style="font-size:15px">{{ bnName }}</b><i>{{ $t('reports.bottleneckTime0', [pct(st.plant.bottleneck[0]?.share, 0)]) }}</i></div>
      </div>
      <TimeBreakdownChart :data="st" :show-passive="passive" style="margin-top:12px" />
      <p class="small muted">{{ $t('reports.definitionsRunningProcessingStarvedN') }}</p></div>
    <div class="card" v-if="tab === 'flow' && sk"><h3>{{ $t('reports.materialFlowSankeyDiagram') }} <small>{{ $t('reports.n01ActualPathsOf', [sk.from, sk.to, sk.parts]) }}</small><span class="grow" />
      <el-segmented v-model="level" size="small" :options="[{ label: $t('reports.byTopLevelBlock'), value: 'block' }, { label: $t('reports.expandSubmodels'), value: 'station' }]" @change="loadTab" /></h3>
      <SankeyChart :data="sk" />
      <p v-if="sk.loops.length" class="small muted">{{ $t('reports.returnFlowsSuchAsRework', [sk.loops.map((l: any) => `${lab(l.source)} → ${lab(l.target)}`).join($t('common.k360'))]) }}</p></div>
    <div class="card" v-if="tab === 'gantt'"><h3>{{ $t('analysisDock.ganttChart') }} <span class="grow" />
      <el-segmented v-model="gby" size="small" :options="[{ label: $t('reports.byEquipment'), value: 'resource' }, { label: $t('reports.byOrder'), value: 'order' }, { label: $t('reports.byPart'), value: 'part' }]" @change="loadTab" />
      <el-select v-if="gby !== 'resource'" v-model="gorder" size="small" clearable :placeholder="$t('reports.allOrders')" style="width:140px" @change="loadTab">
        <el-option v-for="o in gt?.orders || []" :key="o" :label="o" :value="o" /></el-select></h3>
      <p class="small muted" v-if="gby === 'resource'">{{ $t('reports.showsEachMachineSTransitions') }}</p>
      <p class="small muted" v-else-if="gby === 'order'">{{ $t('reports.oneRowPerOrderThe') }}</p>
      <p class="small muted" v-else>{{ $t('reports.oneRowPerPartSuccessive') }}</p>
      <GanttChart v-if="gt" :data="gt" /></div>
    <div class="card" v-if="tab === 'energy'"><EnergyPanel :pid="pid" :hours="hours" :warmup="warm" /></div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { download, get, P, pct } from '../api';
import BottleneckPanel from '../components/BottleneckPanel.vue';
import Chart from '../components/Chart.vue';
import { CH } from '../design/chart';
import EnergyPanel from '../components/EnergyPanel.vue';
import GanttChart from '../components/GanttChart.vue';
import SankeyChart from '../components/SankeyChart.vue';
import TimeBreakdownChart from '../components/TimeBreakdownChart.vue';
import TimeRangePicker from '../components/TimeRangePicker.vue';

const props = defineProps<{ pid: string }>();
const route = useRoute();
const api = P(props.pid), hours = ref(route.query.hours != null ? Number(route.query.hours) : 24), warm = ref(route.query.warmup !== '0'), r = ref<any>(null);
const tab = ref(String(route.query.tab || 'sum'));
const st = ref<any>(null), sk = ref<any>(null), gt = ref<any>(null), passive = ref(false), level = ref('block'), gby = ref('resource'), gorder = ref('');
const qs = computed(() => `hours=${hours.value}&warmup=${warm.value ? 1 : 0}`);
const bnName = computed(() => { const b = st.value?.bottleneck; if (!b?.top?.length) return '—'; return b.items.filter((x: any) => b.top.includes(x.group)).map((x: any) => x.name).join($t('common.k360')); });
async function load() { r.value = await get(`${api}/report?${qs.value}`); }
async function loadTab() {
  if (tab.value === 'time') st.value = await get(`${api}/analysis/stats?${qs.value}`);
  if (tab.value === 'flow') sk.value = await get(`${api}/analysis/sankey?${qs.value}&level=${level.value}`);
  if (tab.value === 'gantt') {
    const h = gby.value === 'resource' ? Math.min(hours.value || 24, 24) : hours.value;
    gt.value = await get(`${api}/analysis/gantt?by=${gby.value}&hours=${h}&warmup=${warm.value ? 1 : 0}` + (gorder.value ? `&order=${encodeURIComponent(gorder.value)}` : ''));
  }
}
function reload() { load(); loadTab(); }
const lab = (id: string) => sk.value?.nodes.find((n: any) => n.name === id)?.label || id;
onMounted(reload);
watch(tab, loadTab);
watch([hours, warm], reload);
// Charts define data only: Chart.vue's hm theme handles colors, axes, and legends; use CH for semantic colors
const hourOpt = computed(() => ({ tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 40, right: 14, top: 30, bottom: 26 },
  xAxis: { type: 'category', data: r.value.series.map((x: any) => x.time.slice(6)) }, yAxis: { type: 'value' },
  series: [{ name: $t('common.acceptedQty'), type: 'bar', stack: 'o', data: r.value.series.map((x: any) => x.good), itemStyle: { color: CH.primary } },
    { name: $t('common.scrapped'), type: 'bar', stack: 'o', data: r.value.series.map((x: any) => x.scrap), itemStyle: { color: CH.bad } }] }));
const wipOpt = computed(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 40, right: 10, top: 10, bottom: 26 },
  xAxis: { type: 'category', data: r.value.series.map((x: any) => x.time.slice(6)) }, yAxis: { type: 'value' },
  series: [{ name: $t('reports.wip'), type: 'line', showSymbol: false, data: r.value.series.map((x: any) => x.wip), lineStyle: { width: 2 } }] }));
const leadOpt = computed(() => { const h = r.value.lead.hist; if (!h) return {};
  return { tooltip: {}, grid: { left: 40, right: 10, top: 10, bottom: 30 }, xAxis: { type: 'category', data: h.counts.map((_: any, i: number) => `${h.edges[i]}`), name: 'h' }, yAxis: { type: 'value' },
    series: [{ type: 'bar', data: h.counts, barCategoryGap: '8%' }] }; });
const scrapOpt = computed(() => ({ tooltip: {}, series: [{ type: 'pie', radius: ['35%', '60%'], data: Object.entries(r.value.scrap_by).map(([k, v]) => ({ name: k, value: v })) }] }));
const enOpt = computed(() => ({ tooltip: {}, series: [{ type: 'pie', radius: ['35%', '60%'], data: Object.entries(r.value.energy).filter(([, v]: any) => v > 0).map(([k, v]) => ({ name: k, value: v })) }] }));
</script>

<style scoped>
.concl { background: var(--hm-surface-2); line-height: 1.9; color: var(--hm-text-2); } .rtabs { margin-bottom: 2px; } .tiles .kpi b { font-size: 19px; }
.g4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
@media (max-width: 1100px) { .g6 { grid-template-columns: repeat(3, minmax(0, 1fr)); } .g4 { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>

