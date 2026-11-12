<template><Chart :option="opt" :height="height" @click="(p: any) => p.data?.ev && emit('pick', p.data.ev)" /></template>

<script setup lang="ts">
import { $t } from '../i18n';
import { CH } from '../design/chart';
/**
 * Optimization scatter plot: one point per candidate, Pareto frontier connected in red, recommended solution enlarged.
 * props.result = optimization experiment result (kind=optimize); x, y are metric keys (default: first two objectives). Event pick: selected candidate.
 */
import { computed } from 'vue';
import Chart from './Chart.vue';

const props = withDefaults(defineProps<{ result: any; x?: string; y?: string; height?: number }>(), { height: 340 });
const emit = defineEmits(['pick']);
const meta = computed<Record<string, any>>(() => Object.fromEntries((props.result.kpis || []).map((k: any) => [k.key, k])));
const xk = computed(() => props.x || props.result.objectives[0]?.key);
const yk = computed(() => props.y || props.result.objectives[1]?.key || 'wip_avg');
const lab = (k: string) => (meta.value[k]?.label || k) + (meta.value[k]?.unit ? $t('common.n0', [meta.value[k].unit]) : '');
const desc = (e: any) => Object.entries(e.values).map(([k, v]) => `${k}=${v}`).join($t('common.k521'));
const opt = computed(() => {
  const ev = props.result.evals || [];
  const pt = (e: any) => ({ value: [e.kpi[xk.value], e.kpi[yk.value]], ev: e });
  const front = ev.filter((e: any) => e.front).sort((a: any, b: any) => a.kpi[xk.value] - b.kpi[xk.value]);
  const best = props.result.best;
  return {
    tooltip: { formatter: (p: any) => p.data?.ev ? `<b>#${p.data.ev.i + 1}</b> ${desc(p.data.ev)}<br/>${lab(xk.value)} ${p.value[0]}<br/>${lab(yk.value)} ${p.value[1]}${p.data.ev.feasible ? '' : $t('paretoChart.brSpanStyleColorCh')}` : '' },
    legend: { top: 0, right: 0, data: [$t('paretoChart.candidate'), $t('paretoChart.constraintsNotMet'), $t('paretoChart.paretoFront'), $t('common.recommended')] },
    grid: { left: 70, right: 20, top: 34, bottom: 44 },
    xAxis: { type: 'value', name: lab(xk.value), nameLocation: 'middle', nameGap: 26, scale: true },
    yAxis: { type: 'value', name: lab(yk.value), nameLocation: 'middle', nameGap: 50, nameRotate: 90, scale: true },
    series: [
      { name: $t('paretoChart.candidate'), type: 'scatter', symbolSize: 9, itemStyle: { color: CH.primary, opacity: 0.7 }, data: ev.filter((e: any) => e.feasible && !e.front).map(pt) },
      { name: $t('paretoChart.constraintsNotMet'), type: 'scatter', symbolSize: 8, symbol: 'diamond', itemStyle: { color: CH.offline }, data: ev.filter((e: any) => !e.feasible).map(pt) },
      { name: $t('paretoChart.paretoFront'), type: 'line', showSymbol: true, symbol: 'emptyCircle', symbolSize: 11, itemStyle: { color: CH.bad }, lineStyle: { type: 'dashed' }, data: front.map(pt) },
      { name: $t('common.recommended'), type: 'scatter', symbol: 'pin', symbolSize: 30, itemStyle: { color: CH.ok }, data: best ? [pt(best)] : [] },
    ],
  };
});
</script>
