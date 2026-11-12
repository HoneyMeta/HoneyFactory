<template><Chart :option="opt" :height="height" /></template>

<script setup lang="ts">
import { $t } from '../i18n';
import { CH } from '../design/chart';
/**
 * Mean + 95% confidence interval comparison (one point and error bar per scenario; bars=true draws bars from 0).
 * props.rows = [{ name, mean, lo, hi, highlight? }] (omit error bars if lo/hi are null); title, unit; percent=true displays percentages.
 */
import { computed } from 'vue';
import Chart from './Chart.vue';

const props = withDefaults(defineProps<{ rows: any[]; title?: string; unit?: string; percent?: boolean; height?: number; bars?: boolean }>(),
  { height: 240, title: '', unit: '', percent: false, bars: false });
const f = (v: number) => (v == null ? '—' : props.percent ? (v * 100).toFixed(2) + '%' : Math.abs(v) >= 100 ? Math.round(v).toString() : (+v).toFixed(2));
function renderErr(params: any, api: any) {
  const x = api.value(0), lo = api.coord([x, api.value(1)]), hi = api.coord([x, api.value(2)]);
  const w = Math.min(16, api.size([1, 0])[0] * 0.3);
  const st = { stroke: CH.text, lineWidth: 1.4 };
  return { type: 'group', children: [
    { type: 'line', shape: { x1: lo[0], y1: lo[1], x2: hi[0], y2: hi[1] }, style: st },
    { type: 'line', shape: { x1: lo[0] - w / 2, y1: lo[1], x2: lo[0] + w / 2, y2: lo[1] }, style: st },
    { type: 'line', shape: { x1: hi[0] - w / 2, y1: hi[1], x2: hi[0] + w / 2, y2: hi[1] }, style: st }] };
}
const range = computed(() => {
  const vs = props.rows.flatMap((r) => [r.mean, r.lo, r.hi]).filter((v) => v != null && isFinite(v));
  if (!vs.length) return {};
  let lo = Math.min(...vs), hi = Math.max(...vs);
  const pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.05 || 1;
  lo -= pad; hi += pad;
  if (props.bars || (lo < 0 && Math.min(...vs) >= 0)) lo = Math.min(0, lo);
  return { min: +lo.toPrecision(4), max: +hi.toPrecision(4) };
});
const color = (r: any, i: number) => (r.highlight ? CH.ok : i === 0 ? CH.offline : CH.primary);
const opt = computed(() => ({
  title: props.title ? { text: props.title + (props.unit ? $t('common.n0', [props.unit]) : ''), textStyle: { fontSize: 13 } } : undefined,
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any[]) => { const r = props.rows[ps[0].dataIndex];
    return `<b>${r.name}</b><br/>${$t('ciBarChart.mean')} ${f(r.mean)}` + (r.lo != null ? `<br/>${$t('ciBarChart.n95Interval')} ${f(r.lo)} ~ ${f(r.hi)}` : $t('ciBarChart.brOnly1ReplicationNo')); } },
  grid: { left: 60, right: 16, top: props.title ? 36 : 14, bottom: 46 },
  xAxis: { type: 'category', data: props.rows.map((r) => r.name), axisLabel: { interval: 0, fontSize: 11, width: 110, overflow: 'truncate' } },
  yAxis: { type: 'value', scale: !props.bars, min: props.bars ? range.value.min : undefined, axisLabel: { formatter: (v: number) => (props.percent ? (v * 100).toFixed(1) + '%' : +v.toPrecision(4)) } },
  series: [
    props.bars
      ? { type: 'bar', barMaxWidth: 44, data: props.rows.map((r, i) => ({ value: r.mean, itemStyle: { color: color(r, i) } })) }
      : { type: 'scatter', symbolSize: 13, data: props.rows.map((r, i) => ({ value: r.mean, itemStyle: { color: color(r, i) } })), z: 11,
        label: { show: true, position: 'right', distance: 10, fontSize: 11, color: CH.text, formatter: (p: any) => f(p.value) } },
    { type: 'custom', renderItem: renderErr, encode: { x: 0, y: [1, 2] }, data: props.rows.map((r, i) => (r.lo != null ? [i, r.lo, r.hi] : null)).filter(Boolean), z: 10, tooltip: { show: false } },
  ],
}));
</script>
