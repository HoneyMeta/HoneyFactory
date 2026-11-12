<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('mesNav.oee') }}</h2><span class="sub">{{ $t('oee.oeeAvailabilityPerformanceQualityDat') }}</span><span class="grow" />
      <el-select v-model="hours" style="width:130px" @change="load"><el-option v-for="h in [2, 8, 24, 72, 168]" :key="h" :label="$t('oee.last0Hours', [h])" :value="h" /></el-select></div>
    <div class="card" v-if="d"><h3>{{ $t('oee.oeeByMachine') }} <small>{{ d.from }} ~ {{ d.to }}</small></h3><Chart :option="bars" :height="300" @click="(p: any) => pick(d.rows[p.dataIndex])" />
      <el-table :data="d.rows" size="small" highlight-current-row @row-click="pick">
        <el-table-column prop="code" :label="$t('common.equipment')" width="90" /><el-table-column prop="name" :label="$t('common.name')" />
        <el-table-column label="OEE"><template #default="{ row }"><b :class="row.OEE < .6 ? 'bad' : row.OEE < .8 ? 'warn' : 'ok'">{{ pct(row.OEE) }}</b></template></el-table-column>
        <el-table-column :label="$t('oee.availability')"><template #default="{ row }">{{ pct(row.A) }}</template></el-table-column>
        <el-table-column :label="$t('oee.performance')"><template #default="{ row }">{{ pct(row.P) }}</template></el-table-column>
        <el-table-column :label="$t('oee.quality')"><template #default="{ row }">{{ pct(row.Q) }}</template></el-table-column>
        <el-table-column prop="good" :label="$t('common.good')" /><el-table-column prop="bad" :label="$t('mobile.defective')" />
        <el-table-column :label="$t('oee.downH')"><template #default="{ row }">{{ lossOf(row.loss, 'down') }}</template></el-table-column>
        <el-table-column :label="$t('oee.changeoverH')"><template #default="{ row }">{{ lossOf(row.loss, 'setup') }}</template></el-table-column>
        <el-table-column :label="$t('oee.idleH')"><template #default="{ row }">{{ lossOf(row.loss, 'idle') }}</template></el-table-column>
      </el-table></div>
    <div class="card" style="margin-top:14px" v-if="tr"><h3>{{ $t('oee.n0Last24H', [curName]) }} <small>{{ $t('oee.hourlyOeeStateTimeline') }}</small></h3>
      <Chart :option="trend" :height="220" />
      <div class="tl"><div v-for="s in tr.timeline" :key="s.id" :class="'s-' + s.state" :style="seg(s)" :title="`${s.state} ${s.start} ~ ${s.end || $t('oee.now')}`" /></div>
      <div class="small muted">{{ $t('oee.greenRunningYellowIdleBlue') }}</div></div>
  </div>
</template>

<script setup lang="ts">
// /api/oee loss buckets: HoneyMOM keys them in Chinese and adds English aliases (down/setup/idle); prefer the aliases
const LOSS_ZH: Record<string, string> = { down: '\u505c\u673a', setup: '\u6362\u578b\u6362\u5200', idle: '\u5f85\u673a/\u7b49\u5f85' };
const lossOf = (l: any, k: string) => l?.[k] ?? l?.[LOSS_ZH[k]];
import { $t } from '../../i18n';
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { get, pct } from '../api';
import Chart from '../../components/Chart.vue';
import { CH } from '../../design/chart';

const route = useRoute();
const d = ref<any>(null), hours = ref(24), tr = ref<any>(null), curName = ref('');
async function load() { d.value = await get('/api/equipment/oee?hours=' + hours.value); }
async function pick(r: any) { if (!r) return; curName.value = `${r.code} ${r.name}`; tr.value = await get('/api/equipment/oee_trend/' + r.id); }
onMounted(async () => { await load(); const id = Number(route.query.eid); const r = d.value.rows.find((x: any) => x.id === id) || d.value.rows.find((x: any) => x.etype === 'cnc'); pick(r); });
const bars = computed(() => ({ tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 40, right: 10, top: 30, bottom: 30 },
  xAxis: { type: 'category', data: d.value.rows.map((r: any) => r.code) }, yAxis: { type: 'value', max: 1, axisLabel: { formatter: (v: number) => v * 100 + '%' } },
  series: ['OEE', 'A', 'P', 'Q'].map((k, i) => ({ name: ['OEE', $t('oee.availability'), $t('oee.performance'), $t('oee.quality')][i], type: i ? 'line' : 'bar', data: d.value.rows.map((r: any) => r[k]), symbolSize: 5 })) }));
const trend = computed(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 40, right: 10, top: 16, bottom: 26 }, xAxis: { type: 'category', data: tr.value.points.map((p: any) => p.t.slice(11, 16)) },
  yAxis: { type: 'value', max: 1 }, series: [{ type: 'bar', data: tr.value.points.map((p: any) => p.OEE), itemStyle: { color: CH.primary } }] }));
const T = (s: string) => new Date(s.replace(' ', 'T')).getTime();
function seg(s: any) {
  const end = T(tr.value.now), start = end - 24 * 3600e3;
  const a = Math.max(start, T(s.start)), b = Math.min(end, s.end ? T(s.end) : end);
  return { left: ((a - start) / (end - start) * 100) + '%', width: Math.max(0.1, (b - a) / (end - start) * 100) + '%' };
}
</script>

<style scoped>
.tl { position: relative; height: 22px; background: var(--hm-surface-3); border-radius: var(--hm-r-sm); margin: 10px 0 4px; overflow: hidden; } .tl div { position: absolute; top: 0; bottom: 0; }
.s-Executing { background: var(--hm-run); } .s-Idle { background: var(--hm-idle); } .s-Setup { background: var(--hm-setup); } .s-Stopped { background: var(--hm-fault); }
</style>
