<template>
  <div class="page" v-if="d">
    <div class="page-head"><h2>{{ $t('common.home') }}</h2><span class="sub">{{ $t('home.dataTime0Today1', [d.now, d.kpi.day]) }}</span><span class="grow" />
      <el-button @click="router.push('/mes/screen')"><el-icon><FullScreen /></el-icon>{{ $t('home.shopFloorDisplay') }}</el-button></div>
    <div class="grid g6">
      <div class="kpi"><small>{{ $t('home.pouredReceivedToday') }}</small><b>{{ d.kpi.production.castings }}</b><i>{{ $t('common.pcs') }}</i></div>
      <div class="kpi"><small>{{ $t('home.machinedToday') }}</small><b>{{ d.kpi.production.machined }}</b><i>{{ $t('common.pcs') }}</i></div>
      <div class="kpi ok"><small>{{ $t('home.storedToday') }}</small><b>{{ d.kpi.production.stored }}</b><i>{{ $t('home.shipped0', [d.kpi.production.shipped]) }}</i></div>
      <div class="kpi" :class="d.kpi.quality.scrap_rate > 0.03 ? 'bad' : ''"><small>{{ $t('common.scrapRate') }}</small><b>{{ pct(d.kpi.quality.scrap_rate, 2) }}</b><i>{{ $t('home.scrap0Rework1', [d.kpi.quality.scrap, d.kpi.quality.rework]) }}</i></div>
      <div class="kpi"><small>{{ $t('common.avgOee') }}</small><b>{{ pct(avgOee) }}</b><i>{{ $t('home.n0Alarms', [d.kpi.equipment.alarms]) }}</i></div>
      <div class="kpi"><small>{{ $t('home.powerToday') }}</small><b>{{ Math.round(d.kpi.energy.kwh) }}</b><i>{{ $t('home.kwhPerTonne0', [d.kpi.energy.kwh_per_t || '—']) }}</i></div>
    </div>
    <div class="grid g4" style="margin-top:14px">
      <div class="todo click" @click="router.push('/mes/e/ncr?f_status=open')"><el-icon><Warning /></el-icon><b>{{ d.todo.ncr }}</b>{{ $t('home.openNcrs') }}</div>
      <div class="todo click" @click="router.push('/mes/e/repair_order')"><el-icon><SetUp /></el-icon><b>{{ d.todo.repair }}</b>{{ $t('home.openRepairs') }}</div>
      <div class="todo click" @click="router.push('/mes/equipment/maint')"><el-icon><Calendar /></el-icon><b>{{ d.todo.maint }}</b>{{ $t('home.checksPmDue') }}</div>
      <div class="todo click" @click="router.push('/mes/machining/tools')"><el-icon><Tools /></el-icon><b>{{ d.todo.tool }}</b>{{ $t('home.cuttingToolAlerts') }}</div>
    </div>
    <div class="grid g3" style="margin-top:14px">
      <div class="card" style="grid-column: span 2"><h3>{{ $t('home.outputLast24H') }} <small>{{ $t('home.hourly') }}</small></h3><Chart :option="hourOpt" :height="270" /></div>
      <div class="card"><h3>{{ $t('home.equipmentStatus') }}</h3><Chart :option="statusOpt" :height="270" @click="router.push('/mes/equipment/monitor')" /></div>
    </div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h3>{{ $t('home.wipWorkOrders') }} <el-button link type="primary" @click="router.push('/mes/production/gantt')">{{ $t('home.scheduling') }}</el-button></h3>
        <div v-for="o in d.orders" :key="o.id" class="wo click" @click="router.push('/mes/e/work_order?id=' + o.id)">
          <div><b>{{ o.code }}</b> <span class="muted small">{{ $t('home.n0Due1', [o.customer, (o.due || '').slice(5, 16)]) }}</span></div>
          <el-progress :percentage="Math.min(100, Math.round((o.qty_done || 0) / o.qty * 100))" :stroke-width="10" :format="() => `${o.qty_done || 0}/${o.qty}`" />
        </div>
        <p v-if="!d.orders.length" class="muted">{{ $t('home.noWorkOrdersInProgress') }}</p>
      </div>
      <div class="card"><h3>{{ $t('home.activeAlarms') }} <el-button link type="primary" @click="router.push('/mes/e/alarm')">{{ $t('home.all') }}</el-button></h3>
        <div v-for="a in d.alarms" :key="a.id" class="al"><span class="bad">●</span> <b>{{ a.equipment__label }}</b> {{ a.msg }} <span class="muted small">{{ (a.start || '').slice(11, 16) }}</span></div>
        <p v-if="!d.alarms.length" class="ok">{{ $t('home.equipmentIsRunningNormallyNo') }}</p>
        <h3 style="margin-top:14px">{{ $t('home.todaySTopDefects') }}</h3>
        <Chart :option="paretoOpt" :height="150" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, pct } from '../api';
import Chart from '../../components/Chart.vue';
import { CH } from '../../design/chart';

const router = useRouter();
const d = ref<any>(null);
let timer: any;
async function load() { d.value = await get('/api/dash/home'); }
onMounted(() => { load(); timer = setInterval(load, 15000); });
onUnmounted(() => clearInterval(timer));
const avgOee = computed(() => { const o = (d.value?.kpi.equipment.oee || []).filter((x: any) => x.OEE != null); return o.length ? o.reduce((a: number, x: any) => a + x.OEE, 0) / o.length : null; });
const hourOpt = computed(() => {
  const hs = d.value.hours, H = d.value.hourly;
  const s = (k: string) => hs.map((h: string) => H[h]?.[k] || 0);
  return { tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 40, right: 12, top: 30, bottom: 24 },
    xAxis: { type: 'category', data: hs.map((h: string) => h.slice(6, 11)) }, yAxis: { type: 'value' },
    series: [{ name: $t('home.pouring'), type: 'bar', data: s('poured').map((v: number, i: number) => v + (H[hs[i]]?.received || 0)) }, { name: $t('common.machining'), type: 'bar', data: s('machined') },
      { name: $t('common.goodsReceipt'), type: 'line', smooth: true, data: s('stored') }, { name: $t('common.scrapped'), type: 'line', data: s('scrap'), itemStyle: { color: CH.bad } }] };
});
const ST: Record<string, [string, string]> = { running: [$t('common.running'), CH.ok], idle: [$t('common.idle'), CH.idle], setup: [$t('common.changeover'), CH.setup], down: [$t('common.down'), CH.bad], offline: [$t('common.offline'), CH.offline] };
const statusOpt = computed(() => ({ tooltip: {}, legend: { bottom: 0 },
  series: [{ type: 'pie', radius: ['45%', '70%'], label: { formatter: '{b}\n{c}' },
    data: Object.entries(d.value.status).map(([k, v]) => ({ name: ST[k]?.[0] || k, value: v, itemStyle: { color: ST[k]?.[1] } })) }] }));
const paretoOpt = computed(() => { const p = d.value.kpi.quality.pareto.slice(0, 5);
  return { grid: { left: 110, right: 20, top: 4, bottom: 4 }, xAxis: { type: 'value', show: false }, yAxis: { type: 'category', inverse: true, data: p.map((x: any) => x.name) },
    series: [{ type: 'bar', data: p.map((x: any) => x.n), label: { show: true, position: 'right' }, itemStyle: { color: CH.primary } }] }; });
</script>

<style scoped>
.todo { background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); box-shadow: var(--hm-e1); padding: 12px 14px; display: flex; align-items: center; gap: 10px;
  color: var(--hm-text-2); font-size: var(--hm-fs-sm); transition: border-color var(--hm-dur-2) var(--hm-ease), box-shadow var(--hm-dur-2) var(--hm-ease); }
.todo:hover { border-color: var(--hm-border-strong); box-shadow: var(--hm-e2); }
.todo b { font-size: var(--hm-fs-2xl); font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; color: var(--hm-text); font-weight: 600; }
.todo .el-icon { font-size: 18px; color: var(--hm-primary); background: var(--hm-primary-soft); border-radius: var(--hm-r-md); width: 32px; height: 32px; padding: 7px; flex: none; }
.wo { padding: 6px 0; border-bottom: 1px dashed var(--hm-border); } .wo :deep(.el-progress__text) { font-size: var(--hm-fs-xs) !important; font-family: var(--hm-font-num); color: var(--hm-text-2); min-width: 64px; text-align: right; } .al { padding: 4px 0; font-size: var(--hm-fs-sm); }
</style>
