<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('mesNav.spc') }}</h2><span class="sub">{{ $t('spc.xRControlChartsSubgroup') }}</span><span class="grow" />
      <el-select v-model="char" style="width:160px" @change="load"><el-option v-for="c in d?.chars || ['BORE_DIA']" :key="c" :label="c" :value="c" /></el-select>
      <el-select v-model="station" clearable :placeholder="$t('spc.allEquipment')" style="width:140px" @change="load"><el-option v-for="s in d?.stations || []" :key="s" :label="s" :value="s" /></el-select>
      <el-select v-model="n" style="width:110px" @change="load"><el-option v-for="v in [125, 250, 500]" :key="v" :label="$t('spc.last0Pcs', [v])" :value="v" /></el-select>
      <el-button @click="load"><el-icon><Refresh /></el-icon></el-button></div>
    <div v-if="d && !d.enough" class="card muted">{{ $t('spc.notEnoughData0Measurements', [d.count]) }}</div>
    <template v-if="d && d.enough">
      <div class="grid g6">
        <div class="kpi"><small>{{ d.name }}</small><b>{{ d.mean.toFixed(4) }}</b><i>{{ $t('spc.n0Mean', [d.unit]) }}</i></div>
        <div class="kpi"><small>{{ $t('spc.spec') }}</small><b style="font-size:17px">{{ d.lsl ?? '—' }} ~ {{ d.usl ?? '—' }}</b></div>
        <div class="kpi" :class="cls(d.Cp)"><small>Cp</small><b>{{ d.Cp ?? '—' }}</b></div>
        <div class="kpi" :class="cls(d.Cpk)"><small>Cpk</small><b>{{ d.Cpk ?? '—' }}</b><i>{{ d.Cpk >= 1.33 ? $t('spc.capable') : d.Cpk >= 1 ? $t('spc.marginallyCapable') : $t('spc.notCapable') }}</i></div>
        <div class="kpi" :class="cls(d.Ppk)"><small>Ppk</small><b>{{ d.Ppk ?? '—' }}</b></div>
        <div class="kpi" :class="d.rules.length ? 'bad' : 'ok'"><small>{{ $t('spc.ruleViolations') }}</small><b>{{ d.rules.length }}</b><i>{{ d.rules.length ? $t('spc.outOfControlPoints') : $t('spc.inControl') }}</i></div>
      </div>
      <div class="card" style="margin-top:14px"><h3>{{ $t('spc.xChart') }}</h3><Chart :option="xopt" :height="280" /></div>
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h3>{{ $t('spc.rChart') }}</h3><Chart :option="ropt" :height="220" /></div>
        <div class="card"><h3>{{ $t('spc.histogram') }}</h3><Chart :option="hopt" :height="220" /></div>
      </div>
      <div class="card" style="margin-top:14px" v-if="d.rules.length"><h3>{{ $t('spc.ruleViolations2') }}</h3>
        <div v-for="r in d.rules" :key="r.i + r.rule" class="small">{{ $t('spc.subgroup012', [r.i + 1, d.times[r.i], r.rule]) }}</div></div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { get } from '../api';
import Chart from '../../components/Chart.vue';
import { CH } from '../../design/chart';

const d = ref<any>(null), char = ref('BORE_DIA'), station = ref(''), n = ref(125);
const cls = (v: number) => (v == null ? '' : v >= 1.33 ? 'ok' : v >= 1 ? 'warn' : 'bad');
async function load() { d.value = await get(`/api/quality/spc?char=${char.value}&station=${station.value}&n=${n.value}`); }
onMounted(load);
const line = (v: number, name: string, color: string) => ({ yAxis: v, name, lineStyle: { color, type: 'dashed' }, label: { formatter: `${name} ${v.toFixed(4)}`, position: 'insideEndTop' } });
const xopt = computed(() => {
  const x = d.value; const bad = new Set(x.rules.map((r: any) => r.i));
  return { tooltip: { trigger: 'axis' }, grid: { left: 70, right: 110, top: 20, bottom: 30 }, xAxis: { type: 'category', data: x.times.map((t: string) => t.slice(5, 16)) },
    yAxis: { type: 'value', scale: true }, series: [{ type: 'line', data: x.xbar.map((v: number, i: number) => ({ value: +v.toFixed(5), itemStyle: { color: bad.has(i) ? CH.bad : CH.primary }, symbolSize: bad.has(i) ? 9 : 5 })),
      markLine: { symbol: 'none', data: [line(x.ucl_x, 'UCL', CH.bad), line(x.xbb, 'CL', CH.ok), line(x.lcl_x, 'LCL', CH.bad),
        ...(x.usl != null ? [line(x.usl, 'USL', CH.violet)] : []), ...(x.lsl != null ? [line(x.lsl, 'LSL', CH.violet)] : [])] } }] };
});
const ropt = computed(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 70, right: 100, top: 16, bottom: 26 }, xAxis: { type: 'category', data: d.value.times.map((t: string) => t.slice(11, 16)) },
  yAxis: { type: 'value' }, series: [{ type: 'line', data: d.value.r.map((v: number) => +v.toFixed(5)), markLine: { symbol: 'none', data: [line(d.value.ucl_r, 'UCL', CH.bad), line(d.value.rbar, 'R̄', CH.ok)] } }] }));
const hopt = computed(() => { const h = d.value.hist; return { tooltip: {}, grid: { left: 50, right: 20, top: 16, bottom: 30 },
  xAxis: { type: 'category', data: h.counts.map((_: any, i: number) => ((h.edges[i] + h.edges[i + 1]) / 2).toFixed(4)) }, yAxis: { type: 'value' },
  series: [{ type: 'bar', data: h.counts, itemStyle: { color: CH.primary }, barCategoryGap: '5%' }] }; });
</script>
