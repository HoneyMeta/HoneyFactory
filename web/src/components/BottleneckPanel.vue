<template>
  <div v-if="data" class="bnp">
    <div class="bnp-verdict" :class="data.tie ? 'tie' : ''">
      <span class="bnp-conf" :class="'c-' + data.confidence">{{ $t('bottleneckPanel.confidence0', [data.confidence_label]) }}</span>
      {{ data.verdict }}
    </div>
    <Chart v-if="rows.length" :option="opt" :height="height || Math.max(150, rows.length * 26 + 50)" @click="(p: any) => emit('pick', rows[p.dataIndex]?.ids?.[0])" />
    <p v-else class="muted small">{{ $t('bottleneckPanel.noEquipmentWasEligibleFor') }}</p>
    <el-table v-if="!compact && rows.length" :data="rows" size="small" class="bnp-tb">
      <el-table-column label="#" width="64"><template #default="{ row }">{{ row.rank }}<span v-if="row.tie" class="bnp-tag">{{ $t('bottleneckPanel.tie') }}</span></template></el-table-column>
      <el-table-column :label="$t('bottleneckPanel.equipmentWorkstationGroup')" prop="name" min-width="130" />
      <el-table-column :label="$t('bottleneckPanel.bottleneckTime')" width="86" align="right"><template #default="{ row }"><b>{{ pct(row.share, 0) }}</b></template></el-table-column>
      <el-table-column :label="$t('bottleneckPanel.soleAlternating')" width="100" align="right"><template #default="{ row }">{{ pct(row.sole, 0) }} / {{ pct(row.shifting, 0) }}</template></el-table-column>
      <el-table-column :label="$t('bottleneckPanel.runningShare')" width="78" align="right"><template #default="{ row }">{{ pct(row.run, 0) }}</template></el-table-column>
      <el-table-column :label="$t('bottleneckPanel.upstreamDownstreamEvidenceBlockedSta')" min-width="260"><template #default="{ row }"><span class="small">{{ row.evidence_text || '—' }}</span></template></el-table-column>
    </el-table>
    <div v-if="excluded.length && compact" class="small muted bnp-ex" :title="excluded.map((e: any) => $t('common.n01', [e.name, e.reason])).join($t('common.k344'))">
      <b>{{ $t('bottleneckPanel.excludedFromAssessment') }}</b>{{ $t('bottleneckPanel.n0HoverForReason', [excluded.map((e: any) => e.name).join($t('common.k360'))]) }}</div>
    <div v-else-if="excluded.length" class="small muted bnp-ex">
      <b>{{ $t('bottleneckPanel.excludedFromAssessment') }}</b><span v-for="(e, i) in excluded" :key="i">{{ $t('common.n012', [e.name, e.reason]) }}<template v-if="i < excluded.length - 1">{{ $t('common.k344') }}</template></span>
    </div>
    <p v-if="!compact" class="small muted">{{ data.note }}</p>
  </div>
  <p v-else class="muted small">{{ $t('bottleneckPanel.noStatisticsAvailable') }}</p>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
/**
 * Bottleneck analysis (active-period method + blocked/starved evidence). props.data = response from GET /api/p/{pid}/analysis/bottleneck
 * (i.e. bottleneck_analysis / bottleneck in /report and /analysis/stats). compact = show only chart and conclusion in a floating panel. Event pick: selected equipment ID.
 */
import { computed } from 'vue';
import { pct } from '../api';
import Chart from './Chart.vue';
import { CH } from '../design/chart';

const props = withDefaults(defineProps<{ data: any; compact?: boolean; height?: number; top?: number }>(), { compact: false, height: 0, top: 8 });
const emit = defineEmits(['pick']);
const rows = computed(() => (props.data?.items || []).slice(0, props.top));
const excluded = computed(() => (props.data?.excluded || []).filter((e: any) => !props.compact || e.id));
const opt = computed(() => ({
  tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, formatter: (ps: any[]) => {
    const r = rows.value[ps[0].dataIndex];
    return `<b>${r.name}</b>${r.tie ? $t('bottleneckPanel.tie2') : ''}<br/>${$t('bottleneckPanel.bottleneckTime')} ${pct(r.share, 1)}${$t('bottleneckPanel.sole')} ${pct(r.sole, 1)}${$t('bottleneckPanel.alternating')} ${pct(r.shifting, 1)}<br/>${$t('bottleneckPanel.runningShare')} ${pct(r.run, 1)}`
      + (r.evidence_text ? `<br/><span style="color:${CH.text3}">${r.evidence_text}</span>` : '');
  } },
  legend: { top: 0 },
  grid: { left: 140, right: 76, top: 28, bottom: 18 },
  xAxis: { type: 'value', max: (v: any) => Math.max(0.1, Math.min(1, Math.ceil(v.max * 10) / 10)), axisLabel: { formatter: (v: number) => Math.round(v * 100) + '%' } },
  yAxis: { type: 'category', inverse: true, data: rows.value.map((r: any) => r.name), axisLabel: { width: 130, overflow: 'truncate', color: CH.text2 } },
  series: [
    { name: $t('bottleneckPanel.sole2'), type: 'bar', stack: 'b', barMaxWidth: 16, itemStyle: { color: CH.bad }, data: rows.value.map((r: any) => r.sole) },
    { name: $t('bottleneckPanel.alternatingWithOtherEquipment'), type: 'bar', stack: 'b', barMaxWidth: 16, itemStyle: { color: 'rgba(220, 43, 43, .35)', borderRadius: [0, 3, 3, 0] }, data: rows.value.map((r: any) => r.shifting),
      label: { show: true, position: 'right', color: CH.text2, fontSize: 11, formatter: (p: any) => { const r = rows.value[p.dataIndex]; return pct(r.share, 0) + (r.tie ? $t('bottleneckPanel.tie3') : ''); } } },
  ],
}));
</script>

<style scoped>
.bnp-verdict { background: var(--hm-fault-soft); border-left: 3px solid var(--hm-fault); border-radius: var(--hm-r-sm); padding: 8px 10px; margin-bottom: 8px; line-height: 1.7; font-size: var(--hm-fs-sm); color: var(--hm-text); }
.bnp-verdict.tie { background: var(--hm-idle-soft); border-left-color: var(--hm-idle); }
.bnp-conf { display: inline-block; font-size: var(--hm-fs-2xs); border-radius: var(--hm-r-xs); padding: 0 6px; margin-right: 6px; background: var(--hm-setup-soft); color: var(--hm-setup-ink); }
.bnp-conf.c-high { background: var(--hm-run-soft); color: var(--hm-run-ink); } .bnp-conf.c-low { background: var(--hm-idle-soft); color: var(--hm-idle-ink); }
.bnp-tag { margin-left: 4px; font-size: var(--hm-fs-2xs); color: var(--hm-idle-ink); background: var(--hm-idle-soft); border-radius: var(--hm-r-xs); padding: 0 4px; }
.bnp-tb { margin-top: 6px; }
.bnp-ex { margin-top: 6px; line-height: 1.7; }
.bnp-ex { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.bnp-ex:not([title]) { white-space: normal; }
</style>