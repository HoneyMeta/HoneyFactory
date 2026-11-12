<template>
  <Chart v-if="rows.length" :option="opt" :height="height || Math.max(220, rows.length * 24 + 60)" @click="(p: any) => emit('pick', rows[p.dataIndex])" />
  <p v-else class="muted small">{{ $t('bottleneckPanel.noStatisticsAvailable') }}</p>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { CH } from '../design/chart';
/**
 * Stacked equipment time chart (running/changeover/starved/blocked/failure/idle/planned downtime/off-shift/disabled).
 * props.data = response from GET /api/p/{pid}/analysis/stats; showPassive=true also includes passive objects such as buffers, sources/sinks, and worker pools.
 * ids limits the chart to specific equipment. The pick event emits the selected object (including seconds, share, oee).
 */
import { computed } from 'vue';
import Chart from './Chart.vue';

const props = withDefaults(defineProps<{ data: any; height?: number; showPassive?: boolean; ids?: string[] }>(), { height: 0, showPassive: false });
const emit = defineEmits(['pick']);
const rows = computed(() => (props.data?.objects || []).filter((o: any) => (props.showPassive || !o.passive) && (!props.ids?.length || props.ids.includes(o.id))));
const hrs = (s: number) => (s / 3600).toFixed(s >= 36000 ? 0 : 1);
const opt = computed(() => {
  const cl = props.data.classes.filter((c: any) => rows.value.some((o: any) => o.share[c.key]));
  return {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any[]) => {
      const o = rows.value[ps[0].dataIndex];
      return `<b>${o.name}</b>${o.oee != null ? $t('timeBreakdownChart.oee0', [(o.oee * 100).toFixed(1)]) : ''}<br/>` + ps.filter((p) => p.value > 0)
        .map((p) => $t('timeBreakdownChart.n0123H', [p.marker, p.seriesName, (p.value * 100).toFixed(1), hrs(o.seconds[cl[p.seriesIndex].key] || 0)])).join('<br/>');
    } },
    legend: { top: 0, itemWidth: 12, itemHeight: 10, textStyle: { fontSize: 12 } },
    grid: { left: 150, right: 54, top: 30, bottom: 20 },
    xAxis: { type: 'value', max: 1, axisLabel: { formatter: (v: number) => v * 100 + '%' } },
    yAxis: { type: 'category', inverse: true, data: rows.value.map((o: any) => o.name), axisLabel: { width: 140, overflow: 'truncate' } },
    series: cl.map((c: any, i: number) => ({ name: c.label, type: 'bar', stack: 's', barMaxWidth: 18, itemStyle: { color: c.color }, data: rows.value.map((o: any) => o.share[c.key] || 0),
      label: i === cl.length - 1 ? { show: true, position: 'right', formatter: (p: any) => { const o = rows.value[p.dataIndex]; return o.oee != null ? `${(o.oee * 100).toFixed(0)}%` : ''; }, color: CH.text3, fontSize: 11 } : undefined })),
  };
});
</script>
