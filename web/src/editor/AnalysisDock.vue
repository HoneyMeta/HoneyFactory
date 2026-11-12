<template>
  <div class="an">
    <div class="an-bar">
      <el-radio-group v-model="tab" size="small" data-tour="an-tabs">
        <el-radio-button value="bottleneck">{{ $t('common.bottleneck') }}</el-radio-button><el-radio-button value="stats">{{ $t('analysisDock.timeBreakdown') }}</el-radio-button><el-radio-button value="sankey">{{ $t('analysisDock.materialFlow') }}</el-radio-button>
        <el-radio-button value="gantt">{{ $t('analysisDock.ganttChart') }}</el-radio-button><el-radio-button value="energy">{{ $t('analysisDock.energy') }}</el-radio-button>
      </el-radio-group>
      <TimeRangePicker v-model:hours="hours" v-model:warmup="warmup" :win="win" data-tour="an-range" />
      <el-button size="small" text @click="load"><el-icon><Refresh /></el-icon></el-button>
      <span class="muted small hint">{{ HINT[tab] }}</span>
      <span class="grow" />
      <el-button size="small" text data-tour="an-ai" @click="askAI">{{ $t('common.askAiToInterpret') }}</el-button>
      <el-button size="small" text data-tour="an-report" @click="openReport">{{ $t('analysisDock.viewFullChartInReports') }}</el-button>
      <GuideButton area="analysis" size="sm" />
    </div>
    <div class="an-body" data-tour="an-body">
    <div v-if="loading" class="muted small" style="padding:10px">{{ $t('analysisDock.calculating') }}</div>
    <template v-else>
      <BottleneckPanel v-if="tab === 'bottleneck' && data.bottleneck" :data="data.bottleneck" compact :top="6" :height="Math.max(140, chartH - 70)" @pick="pick" />
      <TimeBreakdownChart v-else-if="tab === 'stats' && data.stats" :data="data.stats" :height="chartH" @pick="pick" />
      <SankeyChart v-else-if="tab === 'sankey' && data.sankey" :data="data.sankey" :height="chartH" @pick="pick" />
      <GanttChart v-else-if="tab === 'gantt' && data.gantt" :data="data.gantt" :height="chartH" @pick="pick" />
      <EnergyPanel v-else-if="tab === 'energy'" :pid="ed.pid" :hours="hours" :warmup="warmup" :editable="canEdit()" />
    </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { canEdit, get, P } from '../api';
import { askAssistant } from '../assistant';
import BottleneckPanel from '../components/BottleneckPanel.vue';
import EnergyPanel from '../components/EnergyPanel.vue';
import GanttChart from '../components/GanttChart.vue';
import SankeyChart from '../components/SankeyChart.vue';
import TimeBreakdownChart from '../components/TimeBreakdownChart.vue';
import TimeRangePicker from '../components/TimeRangePicker.vue';
import GuideButton from '../components/GuideButton.vue';
import { blocksById, ed, focusOn, select } from './store';

const props = defineProps<{ height?: number }>();
const router = useRouter();
const tab = ref('bottleneck'), hours = ref(8), warmup = ref(true), loading = ref(false);
const data = reactive<any>({ bottleneck: null, stats: null, sankey: null, gantt: null });
const chartH = computed(() => Math.max(160, (props.height || 240) - 50));
const win = computed(() => { const d = data[tab.value]; return d?.from ? { from: d.from, to: d.to, hours: d.hours } : null; });
const HINT: Record<string, string> = { bottleneck: $t('analysisDock.activePeriodMethodWhichMachines'), stats: $t('analysisDock.howEachMachineSpendsIts'),
  sankey: $t('analysisDock.theActualPathsPartsTook'), gantt: $t('analysisDock.whatEachMachineWasDoing'), energy: $t('analysisDock.powerByStatePeakDemand') };
const REPORT_TAB: Record<string, string> = { bottleneck: 'sum', stats: 'time', sankey: 'flow', gantt: 'gantt', energy: 'energy' };
async function load() {
  if (tab.value === 'energy') return;
  loading.value = true;
  const w = `hours=${hours.value}&warmup=${warmup.value ? 1 : 0}`;
  try {
    const q = tab.value === 'bottleneck' ? `analysis/bottleneck?${w}` : tab.value === 'stats' ? `analysis/stats?${w}` : tab.value === 'sankey' ? `analysis/sankey?${w}&level=block`
      : `analysis/gantt?by=resource&hours=${Math.min(hours.value || 24, 24)}&warmup=${warmup.value ? 1 : 0}`;
    data[tab.value] = await get(`${P(ed.pid)}/${q}`, true).catch(() => null);
  } finally { loading.value = false; }
}
function pick(e: any) {
  let id = typeof e === 'string' ? e : e?.id || e?.name;
  if (tab.value === 'gantt' && Array.isArray(e?.value)) id = data.gantt?.rows?.[e.value[0]]?.id;
  if (id && blocksById.value[id]) { select([id]); focusOn(id); ed.rightTab = 'live'; }
}
function openReport() { router.push(`/p/${ed.pid}/reports?tab=${REPORT_TAB[tab.value]}&hours=${hours.value}&warmup=${warmup.value ? 1 : 0}`); }
function askAI() {
  const q: Record<string, string> = { bottleneck: $t('analysisDock.reviewTheBottleneckAnalysisIdentify'),
    stats: $t('analysisDock.analyzeTheRecentEquipmentTime'),
    sankey: $t('analysisDock.analyzeMaterialFlowHowDo'), gantt: $t('analysisDock.reviewTheEquipmentGanttChart'),
    energy: $t('analysisDock.analyzeEnergyUseWhereDoes') };
  askAssistant(q[tab.value]);
}
watch(tab, load);
watch([hours, warmup], load);
onMounted(load);
</script>

<style scoped>
.an-bar .hint { max-width: 360px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
