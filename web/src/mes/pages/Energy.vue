<template>
  <div class="page" v-if="d">
    <div class="page-head"><h2>{{ $t('mesNav.energyAnalysis') }}</h2><span class="sub">{{ $t('energy.cumulativeEquipmentElectricityMeterR') }}</span><span class="grow" />
      <el-select v-model="days" style="width:120px" @change="load"><el-option v-for="x in [1, 7, 30]" :key="x" :label="$t('common.last0Days', [x])" :value="x" /></el-select></div>
    <div class="grid g4">
      <div class="kpi"><small>{{ $t('energy.totalPower') }}</small><b>{{ Math.round(d.total_kwh) }}</b><i>kWh</i></div>
      <div class="kpi"><small>{{ $t('energy.melted') }}</small><b>{{ d.melt_t }}</b><i>t</i></div>
      <div class="kpi" :class="d.kwh_per_t > 650 ? 'warn' : 'ok'"><small>{{ $t('energy.furnaceKwhT') }}</small><b>{{ d.kwh_per_t ?? '—' }}</b><i>{{ $t('energy.kwhTIndustryBenchmark600') }}</i></div>
      <div class="kpi"><small>{{ $t('energy.totalEnergyPerPart') }}</small><b>{{ d.kwh_per_piece ?? '—' }}</b><i>{{ $t('energy.kwhPc0PcsReceived', [d.good]) }}</i></div>
    </div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h3>{{ $t('energy.hourlyPowerLast48H') }} <small>{{ $t('energy.stackedByEquipmentType') }}</small></h3><Chart :option="hourly" :height="300" /></div>
      <div class="card"><h3>{{ $t('energy.powerByMachine') }}</h3><Chart :option="rank" :height="300" /></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>{{ $t('energy.energySavingTips') }}</h3><p class="small">{{ d.peak_note }}</p><p class="small muted">{{ $t('energy.peakOffPeakPeriods0', [tou]) }}</p></div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { computed, onMounted, ref } from 'vue';
import { get } from '../api';
import Chart from '../../components/Chart.vue';
import { CH } from '../../design/chart';

const d = ref<any>(null), days = ref(7), tou = ref('');
const ET: Record<string, string> = { furnace: $t('energy.inductionFurnace'), treatment: $t('energy.nodularization'), sand: $t('energy.sandPreparation'), molding: $t('energy.molding'), cooling: $t('energy.cooling'), shotblast: $t('energy.shotBlasting'), cnc: $t('common.machining'), deburr: $t('energy.deburring'), inspection: $t('energy.testing'),
  warehouse: $t('energy.asRs'), agv: 'AGV', crew: $t('common.teams'), receiving: $t('energy.receive') };
async function load() { d.value = await get('/api/energy/summary?days=' + days.value); }
onMounted(async () => { load(); const s = await get('/api/e/setting?f_key=tou'); tou.value = s.items[0]?.value || ''; });
const hourly = computed(() => {
  const hs = Object.keys(d.value.hourly), types = [...new Set(hs.flatMap((h) => Object.keys(d.value.hourly[h])))];
  return { tooltip: { trigger: 'axis' }, legend: { top: 0, type: 'scroll' }, grid: { left: 50, right: 10, top: 30, bottom: 26 }, xAxis: { type: 'category', data: hs.map((h) => h.slice(11, 16)) },
    yAxis: { type: 'value', name: 'kWh' }, series: types.map((t) => ({ name: ET[t] || t, type: 'bar', stack: 'a', data: hs.map((h) => +(d.value.hourly[h][t] || 0).toFixed(1)) })) };
});
const rank = computed(() => { const r = d.value.by_equipment.slice(0, 12);
  return { tooltip: {}, grid: { left: 120, right: 40, top: 10, bottom: 20 }, xAxis: { type: 'value' }, yAxis: { type: 'category', inverse: true, data: r.map((x: any) => x.name) },
    series: [{ type: 'bar', data: r.map((x: any) => Math.round(x.kwh)), itemStyle: { color: CH.primary }, label: { show: true, position: 'right' } }] }; });
</script>
