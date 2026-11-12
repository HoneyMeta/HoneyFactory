<template>
  <div class="gantt">
    <div class="lg" v-if="legend.length">
      <span v-for="l in legend" :key="l.key" class="chip"><i :style="{ background: l.color }" />{{ l.label }}</span>
      <span v-if="data?.dropped_shorter_than_s" class="muted small">{{ $t('ganttChart.intervalsShorterThan0S', [Math.round(data.dropped_shorter_than_s)]) }}</span>
    </div>
    <Chart v-if="data && data.rows.length" :option="opt" :height="h" @click="(p: any) => emit('pick', p)" />
    <p v-else class="muted small">{{ $t('ganttChart.noDataForThisTime') }}</p>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { CH, PALETTE } from '../design/chart';
/**
 * Gantt chart. props.data uses the response from GET /api/p/{pid}/analysis/gantt directly:
 *  - by=resource: rows=equipment, items=[row index, start seconds, end seconds, time category], colored by category (running/starved/blocked/failure/changeover…)
 *  - by=order / part: rows=orders or parts, items=[row index, start seconds, end seconds, equipment index], colored by equipment; order rows include due-date markers
 * Times are simulation seconds; data.base is the timestamp at t=0. Drag the bottom slider to zoom. Event pick: clicked interval.
 */
import * as echarts from 'echarts';
import { computed } from 'vue';
import Chart from './Chart.vue';

const props = withDefaults(defineProps<{ data: any; height?: number }>(), { height: 0 });
const emit = defineEmits(['pick']);
const PAL = PALETTE;
const isRes = computed(() => props.data?.by === 'resource');
const cls = computed<Record<string, any>>(() => Object.fromEntries((props.data?.classes || []).map((c: any) => [c.key, c])));
const legend = computed(() => {
  if (!props.data) return [];
  if (isRes.value) { const used = new Set(props.data.items.map((x: any) => x[3])); return props.data.classes.filter((c: any) => used.has(c.key)); }
  return (props.data.stations || []).map((s: any, i: number) => ({ key: s.id, label: s.name, color: PAL[i % PAL.length] }));
});
const h = computed(() => props.height || Math.max(180, (props.data?.rows.length || 1) * 24 + 90));
const base = computed(() => new Date(props.data.base).getTime());
const two = (n: number) => String(n).padStart(2, '0');
const tfmt = (ms: number) => { const d = new Date(ms); return `${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}`; };
const dfmt = (s: number) => (s >= 3600 ? (s / 3600).toFixed(1) + $t('common.hours2') : s >= 60 ? Math.round(s / 60) + $t('ganttChart.min') : Math.round(s) + $t('ganttChart.s'));
function renderItem(params: any, api: any) {
  const cat = api.value(0), s = api.coord([api.value(1), cat]), e = api.coord([api.value(2), cat]);
  const hh = Math.min(22, api.size([0, 1])[1] * 0.64);
  const r = echarts.graphic.clipRectByRect({ x: s[0], y: s[1] - hh / 2, width: Math.max(1, e[0] - s[0]), height: hh },
    { x: params.coordSys.x, y: params.coordSys.y, width: params.coordSys.width, height: params.coordSys.height });
  return r && { type: 'rect', shape: r, style: api.style() };
}
const opt = computed(() => {
  const d = props.data, b = base.value, rows = d.rows;
  const color = (k: any) => (isRes.value ? cls.value[k]?.color || CH.offline : PAL[k % PAL.length]);
  const lab = (k: any) => (isRes.value ? cls.value[k]?.label || k : d.stations?.[k]?.name || k);
  const data = d.items.map((it: any) => ({ value: [it[0], b + it[1] * 1000, b + it[2] * 1000, it[3]], itemStyle: { color: color(it[3]) } }));
  const series: any[] = [{ type: 'custom', renderItem, encode: { x: [1, 2], y: 0 }, data, clip: true }];
  const due = rows.map((r: any, i: number) => (r.due_t != null ? [b + r.due_t * 1000, i] : null)).filter(Boolean);
  if (due.length) series.push({ type: 'scatter', name: $t('ganttChart.dueDate'), symbol: 'triangle', symbolSize: 11, symbolRotate: 180, itemStyle: { color: CH.bad }, data: due, z: 5 });
  return {
    animation: false,
    tooltip: { formatter: (p: any) => p.seriesType === 'scatter' ? $t('ganttChart.n0Due1', [rows[p.value[1]].name, tfmt(p.value[0])])
      : `<b>${rows[p.value[0]].name}</b><br/>${lab(p.value[3])}<br/>${tfmt(p.value[1])} – ${tfmt(p.value[2])}${$t('common.k459')}${dfmt((p.value[2] - p.value[1]) / 1000)}${$t('common.k460')}` },
    grid: { left: 150, right: 24, top: 10, bottom: 56 },
    xAxis: { type: 'time', min: b + d.t0 * 1000, max: b + d.t1 * 1000, axisLabel: { formatter: (v: number) => tfmt(v).slice(6) + (new Date(v).getHours() === 0 ? '\n' + tfmt(v).slice(0, 5) : '') } },
    yAxis: { type: 'category', inverse: true, data: rows.map((r: any) => r.name + (r.parts != null ? $t('ganttChart.n01', [r.done, r.parts]) : '')), axisLabel: { width: 140, overflow: 'truncate' } },
    dataZoom: [{ type: 'slider', xAxisIndex: 0, height: 16, bottom: 10, labelFormatter: (v: number) => tfmt(v).slice(6) }, { type: 'inside', xAxisIndex: 0 }],
    series,
  };
});
</script>

<style scoped>
.lg { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-bottom: 4px; align-items: center; }
.chip { font-size: 12px; color: var(--hm-text-2); display: inline-flex; align-items: center; gap: 4px; }
.chip i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
</style>
