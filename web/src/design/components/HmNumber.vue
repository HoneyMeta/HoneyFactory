<template><span class="hm-num" :title="title">{{ text }}<small v-if="unit" class="hm-unit">{{ unit }}</small></span></template>

<script setup lang="ts">
// Number: consistent formatting (thousands separators, decimal places, percentages), animated on value changes (respects reduced motion).
import { computed } from 'vue';
import { fmtBy } from '../format';
import { useTickUp } from '../motion';

const props = withDefaults(defineProps<{ value?: number | string | null; format?: string; digits?: number; unit?: string; tick?: boolean; title?: string }>(),
  { format: 'num', tick: true });
const isNum = computed(() => props.value !== null && props.value !== undefined && props.value !== '' && !isNaN(Number(props.value)));
const shown = useTickUp(() => (props.tick && isNum.value ? Number(props.value) : null));
const text = computed(() => {
  if (!isNum.value) return props.value === null || props.value === undefined || props.value === '' ? '—' : String(props.value);
  const v = props.tick && shown.value !== null && shown.value !== undefined ? shown.value : Number(props.value);
  // Use the target value's decimal places throughout the animation to avoid fluctuating precision
  const target = Number(props.value);
  const digits = props.digits ?? (props.format === 'num' ? (Number.isInteger(target) ? 0 : Math.abs(target) < 10 ? 2 : 1) : undefined);
  // Round only regular numbers; with percentage digits=0, 0.592 must display as 59%, not be rounded to 1 first
  return fmtBy(props.format === 'int' || (props.format === 'num' && digits === 0) ? Math.round(v) : v, props.format, digits);
});
</script>
