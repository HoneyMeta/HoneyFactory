<template>
  <Chart v-if="data && data.links.length" :option="opt" :height="height || Math.max(260, data.nodes.length * 28)" @click="(p: any) => emit('pick', p.data)" />
  <p v-else class="muted small">{{ $t('sankeyChart.noPartMovementsRecordedDuring') }}</p>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { CH, PALETTE } from '../design/chart';
/**
 * Material flow Sankey chart. props.data = response from GET /api/p/{pid}/analysis/sankey {nodes:[{name,label,kind}], links:[{source,target,value}], loops}.
 * Return flows such as rework are split into "(return flow)" nodes on the server to keep the graph acyclic. Event pick: selected node or link data.
 */
import { computed } from 'vue';
import Chart from './Chart.vue';

const props = withDefaults(defineProps<{ data: any; height?: number }>(), { height: 0 });
const emit = defineEmits(['pick']);
const KIND_COLOR: Record<string, string> = { source: CH.ok, receiving: CH.ok, molding: CH.amber, cooling: CH.amber, shotblast: CH.amber, processor: CH.warn, cnc: CH.primary,
  batch: CH.amber, inspect: CH.violet, inspection: CH.violet, rework: CH.violet, assembly: CH.cyan, split: CH.cyan, sink: CH.primary, storage: CH.primary, warehouse: CH.primary,
  deburr: PALETTE[7], conveyor: PALETTE[7], submodel: PALETTE[7], scrap: CH.bad, ship: CH.ok, loop: CH.offline };
const opt = computed(() => {
  const lab: Record<string, string> = Object.fromEntries(props.data.nodes.map((n: any) => [n.name, n.label]));
  return {
    tooltip: { trigger: 'item', formatter: (p: any) => p.dataType === 'edge' ? `${lab[p.data.source]} → ${lab[p.data.target]}${$t('common.k546')}<b>${p.data.value}</b> ${$t('common.pcs')}` : $t('sankeyChart.n01Pcs', [lab[p.name], p.value]) },
    series: [{
      type: 'sankey', left: 8, right: 110, top: 10, bottom: 10, nodeGap: 10, nodeWidth: 14, layoutIterations: 64, draggable: true, emphasis: { focus: 'adjacency' },
      data: props.data.nodes.map((n: any) => ({ name: n.name, itemStyle: { color: KIND_COLOR[n.kind] || CH.text3, borderWidth: 0 } })),
      links: props.data.links, lineStyle: { color: 'gradient', curveness: 0.5, opacity: 0.35 },
      label: { formatter: (p: any) => lab[p.name] || p.name, fontSize: 12, color: CH.text },
    }],
  };
});
</script>
