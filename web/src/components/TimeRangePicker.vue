<template>
  <span class="trp">
    <el-select :model-value="hours" :size="size" class="trp-sel" @update:model-value="(v: number) => emit('update:hours', v)">
      <el-option v-for="o in OPTIONS" :key="o.value" :value="o.value" :label="o.label" />
    </el-select>
    <el-checkbox v-if="showWarmup" :model-value="warmup" :size="size" @update:model-value="(v: any) => emit('update:warmup', !!v)">{{ $t('timeRangePicker.excludeWarmUp') }}</el-checkbox>
    <el-tooltip v-if="win" placement="bottom" :content="tip">
      <span class="trp-win muted small">{{ $t('timeRangePicker.simTime012', [win.from, win.to.slice(5), win.hours]) }}</span>
    </el-tooltip>
  </span>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
/**
 * Statistics time range selector shared by the analysis popup, Run Reports, and scenario reports.
 * v-model:hours: last N hours, 0 = all; v-model:warmup: whether to exclude the warm-up period.
 * win = API response {from, to, hours}, used to display the actual sim time range (server aligns the start to the hour).
 */
import { computed } from 'vue';

const props = withDefaults(defineProps<{ hours: number; warmup?: boolean; showWarmup?: boolean; win?: { from: string; to: string; hours: number } | null; size?: 'small' | 'default' }>(),
  { warmup: true, showWarmup: true, win: null, size: 'small' });
const emit = defineEmits<{ (e: 'update:hours', v: number): void; (e: 'update:warmup', v: boolean): void }>();
const OPTIONS = [{ value: 2, label: $t('timeRangePicker.last2Hours') }, { value: 8, label: $t('timeRangePicker.last8Hours') }, { value: 24, label: $t('timeRangePicker.last24H') }, { value: 72, label: $t('timeRangePicker.last3Days') }, { value: 0, label: $t('common.all') }];
const tip = computed(() => $t('timeRangePicker.theReportingPeriodUsesThe') + (props.warmup ? $t('timeRangePicker.warmUpExcluded') : $t('timeRangePicker.warmUpIncluded')) + $t('timeRangePicker.reportsAnalysisPanelsAndSolution'));
</script>

<style scoped>
.trp { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.trp-sel { width: 112px; }
.trp-win { white-space: nowrap; cursor: help; }
</style>
