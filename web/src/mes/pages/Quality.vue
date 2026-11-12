<template>
  <div class="page" v-if="d">
    <div class="page-head"><h2>{{ $t('mesNav.qualityOverview') }}</h2><span class="sub">{{ $t('common.last0Days', [days]) }}</span><span class="grow" />
      <el-radio-group v-model="days" @change="load"><el-radio-button :value="1">{{ $t('quality.n1Day') }}</el-radio-button><el-radio-button :value="7">{{ $t('quality.n7Days') }}</el-radio-button><el-radio-button :value="30">{{ $t('quality.n30Days') }}</el-radio-button></el-radio-group></div>
    <div class="grid g4">
      <div class="kpi"><small>{{ $t('quality.endoscopeInspections') }}</small><b>{{ d.endo.total }}</b></div>
      <div class="kpi" :class="d.endo.rate > 0.1 ? 'bad' : 'warn'"><small>{{ $t('quality.endoscopeNgRate') }}</small><b>{{ pct(d.endo.rate) }}</b><i>NG {{ d.endo.ng }}</i></div>
      <div class="kpi bad click" @click="router.push('/mes/e/ncr?f_status=open')"><small>{{ $t('quality.openNcrs') }}</small><b>{{ (d.status.open || 0) + (d.status.reviewing || 0) }}</b><i>{{ $t('quality.closed0', [d.status.closed || 0]) }}</i></div>
      <div class="kpi click" @click="router.push('/mes/quality/spc')"><small>{{ $t('quality.cylinderBoreProcessCapability') }}</small><b>{{ spc?.Cpk ?? '—' }}</b><i>{{ $t('quality.cpk133IsGood') }}</i></div>
    </div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h3>{{ $t('quality.defectPareto') }}</h3><Chart :option="pareto" :height="300" /></div>
      <div class="card"><h3>{{ $t('quality.nonconformanceDisposition') }}</h3><Chart :option="disp" :height="300" /></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, pct } from '../api';
import Chart from '../../components/Chart.vue';
import { CH } from '../../design/chart';

const router = useRouter();
const d = ref<any>(null), spc = ref<any>(null), days = ref(7);
async function load() { d.value = await get('/api/quality/summary?days=' + days.value); }
onMounted(async () => { load(); spc.value = await get('/api/quality/spc?char=BORE_DIA'); });
const pareto = computed(() => {
  const p = d.value.pareto, tot = p.reduce((a: number, x: any) => a + x.n, 0) || 1; let acc = 0;
  return { tooltip: { trigger: 'axis' }, grid: { left: 40, right: 40, top: 20, bottom: 60 }, xAxis: { type: 'category', data: p.map((x: any) => x.name), axisLabel: { rotate: 25 } },
    yAxis: [{ type: 'value' }, { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } }],
    series: [{ type: 'bar', data: p.map((x: any) => x.n), itemStyle: { color: CH.primary } }, { type: 'line', yAxisIndex: 1, data: p.map((x: any) => +((acc += x.n) / tot * 100).toFixed(1)), itemStyle: { color: CH.amber } }] };
});
const DISP: Record<string, string> = { pending: $t('quality.awaitingDisposition'), rework: $t('quality.rework'), scrap: $t('common.scrapped'), concession: $t('quality.useAsIs'), return: $t('quality.return') };
const disp = computed(() => ({ tooltip: {}, legend: { bottom: 0 }, series: [{ type: 'pie', radius: ['40%', '68%'], data: Object.entries(d.value.disposition).map(([k, v]) => ({ name: DISP[k] || k, value: v })) }] }));
</script>
