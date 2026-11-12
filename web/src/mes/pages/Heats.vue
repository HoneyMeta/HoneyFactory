<template>
  <div class="page" v-if="d">
    <div class="page-head"><h2>{{ $t('mesNav.heatAnalysis') }}</h2><span class="sub">{{ $t('heats.chemistryPowerConsumptionAndTapping') }}</span><span class="grow" />
      <el-button @click="router.push('/mes/e/heat')">{{ $t('mesNav.heatRecords') }}</el-button></div>
    <div class="grid g4">
      <div class="kpi"><small>{{ $t('heats.heats') }}</small><b>{{ d.rows.length }}</b></div>
      <div class="kpi"><small>{{ $t('heats.avgKwhT') }}</small><b>{{ d.avg.kwh_per_t ?? '—' }}</b><i>kWh/t</i></div>
      <div class="kpi"><small>{{ $t('heats.averageCarbonEquivalent') }}</small><b>{{ d.avg.CE ?? '—' }}</b><i>{{ $t('heats.target415445') }}</i></div>
      <div class="kpi"><small>{{ $t('heats.ceOutOfWindow') }}</small><b :class="ceOut ? 'bad' : 'ok'">{{ ceOut }}</b><i>{{ $t('heats.heats2') }}</i></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>{{ $t('heats.chemistryEnergyTrend') }}</h3><Chart :option="trend" :height="300" /></div>
    <div class="card" style="margin-top:14px"><h3>{{ $t('heats.heatDetails') }}</h3>
      <el-table :data="[...d.rows].reverse()" size="small" max-height="420" @row-click="(r: any) => router.push('/mes/trace?heat=' + r.code)">
        <el-table-column prop="code" :label="$t('common.heat')" width="130" /><el-table-column prop="furnace__label" :label="$t('heats.furnace')" />
        <el-table-column :label="$t('common.start')" width="110"><template #default="{ row }">{{ (row.start || '').slice(5, 16) }}</template></el-table-column>
        <el-table-column prop="C" label="C" /><el-table-column prop="Si" label="Si" /><el-table-column prop="CE" label="CE" />
        <el-table-column prop="tap_temp" :label="$t('heats.tappingTemp')" /><el-table-column prop="kwh_per_t" :label="$t('heats.kwhT')" /><el-table-column prop="mg_avg" :label="$t('heats.averageResidualMagnesium')" />
        <el-table-column prop="castings" :label="$t('workbench.castings')" /><el-table-column :label="$t('heats.scrapRate')"><template #default="{ row }">{{ row.scrap_rate == null ? '—' : pct(row.scrap_rate) }}</template></el-table-column>
        <el-table-column :label="$t('common.status')"><template #default="{ row }">{{ ST[row.status] }}</template></el-table-column>
      </el-table></div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, pct } from '../api';
import Chart from '../../components/Chart.vue';
import { CH } from '../../design/chart';

const router = useRouter(), d = ref<any>(null);
const ST: Record<string, string> = { melting: $t('heats.melting'), holding: $t('heats.holdingTapping'), done: $t('heats.end') };
onMounted(async () => { d.value = await get('/api/foundry/heats?n=80'); });
const ceOut = computed(() => d.value.rows.filter((r: any) => r.CE && (r.CE < 4.15 || r.CE > 4.45)).length);
const trend = computed(() => { const r = d.value.rows;
  return { tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 50, right: 60, top: 30, bottom: 30 }, xAxis: { type: 'category', data: r.map((x: any) => x.code.slice(-6)) },
    yAxis: [{ type: 'value', name: '%', scale: true }, { type: 'value', name: 'kWh/t', scale: true }],
    series: [{ name: 'C', type: 'line', data: r.map((x: any) => x.C) }, { name: 'Si', type: 'line', data: r.map((x: any) => x.Si) }, { name: 'CE', type: 'line', data: r.map((x: any) => x.CE) },
      { name: $t('heats.kwhT'), type: 'bar', yAxisIndex: 1, data: r.map((x: any) => x.kwh_per_t), itemStyle: { color: CH.soft } }] }; });
</script>
