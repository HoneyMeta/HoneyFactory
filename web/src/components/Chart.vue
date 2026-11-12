<template><div ref="el" class="vf-chart" :style="{ height: height + 'px', width: '100%' }" /></template>

<script setup lang="ts">
// ECharts container: since 5.0.1, uses HoneyMOM's theme (design/chart.ts: PALETTE colors, axes, tooltips, legends, donut labels; text scales with --hm-scale) + responsive sizing.
// Pages define only data and chart types, not hardcoded colors; use CH from design/chart.ts for semantic colors.
import * as echarts from 'echarts';
import { onMounted, onUnmounted, ref, watch } from 'vue';
import { chartScale, themed, themeName } from '../design/chart';

const props = withDefaults(defineProps<{ option: any; height?: number }>(), { height: 260 });
const emit = defineEmits(['click']);
const el = ref<HTMLElement>();
let chart: echarts.ECharts | null = null, ro: ResizeObserver | null = null, k = 1;
/** 4.6: append tooltips to body to avoid overflow clipping in floating panels and cards; explicit appendToBody: false takes precedence. */
/** Once appended to body, position relative to the viewport: flip left if space is tight on the right, and clamp all edges to keep tooltips on screen. */
function place(point: number[], _p: any, _d: any, _r: any, size: any) {
  const r = el.value?.getBoundingClientRect();
  const [w, h] = size?.contentSize || [0, 0];
  if (!r) return [point[0] + 16, point[1] - h / 2];
  let x = point[0] + 16, y = point[1] - h / 2;
  if (r.left + x + w > innerWidth - 8) x = point[0] - 16 - w;
  x = Math.max(8 - r.left, Math.min(innerWidth - 8 - w - r.left, x));
  y = Math.max(8 - r.top, Math.min(innerHeight - 8 - h - r.top, y));
  return [x, y];
}
const WRAP = 'max-width: min(560px, calc(100vw - 24px)); white-space: normal; box-shadow: 0 2px 6px rgba(15,32,60,.08), 0 10px 28px rgba(15,32,60,.12); border-radius: 8px;';
const pop = (t: any) => (t && typeof t === 'object' && !Array.isArray(t)
  ? { appendToBody: true, ...(t.position === undefined ? { position: place } : {}), ...t, extraCssText: WRAP + (t.extraCssText || '') } : t);
function opt(o: any) {
  const x = themed(o, props.height, k);
  if (x?.tooltip) x.tooltip = Array.isArray(x.tooltip) ? x.tooltip.map(pop) : pop(x.tooltip);
  return x;
}
onMounted(() => {
  k = chartScale();
  chart = echarts.init(el.value!, themeName(k));
  chart.on('click', (p) => emit('click', p));
  chart.setOption(opt(props.option));
  ro = new ResizeObserver(() => chart?.resize()); ro.observe(el.value!);
});
watch(() => props.option, (o) => chart?.setOption(opt(o), true), { deep: true });
onUnmounted(() => { ro?.disconnect(); chart?.dispose(); });
</script>
