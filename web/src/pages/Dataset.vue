<template>
  <div class="page" v-if="info">
    <div class="page-head"><h2>{{ $t('common.dataset') }}</h2><span class="sub">{{ $t('dataset.exportAiTrainingDataWith') }}</span></div>
    <div class="grid g4">
      <div class="kpi"><small>{{ $t('dataset.availableDuration') }}</small><b>{{ info.hours }}</b><i>{{ $t('dataset.hoursMemoryRetainsTheLatest') }}</i></div>
      <div class="kpi"><small>{{ $t('common.tag') }}</small><b>{{ info.tags }}</b><i>{{ $t('dataset.numericTags') }}</i></div>
      <div class="kpi"><small>{{ $t('dataset.partRecords') }}</small><b>{{ info.parts }}</b><i>{{ $t('dataset.pcsIncludingActualDefects') }}</i></div>
      <div class="kpi"><small>{{ $t('dataset.labeledIntervals') }}</small><b>{{ Object.values(info.labels).reduce((a: number, b: any) => a + b, 0) }}</b><i>{{ Object.entries(info.labels).map(([k, v]) => `${LT[k] || k} ${v}`).join($t('common.k360')) || $t('livePanel.noneYet') }}</i></div>
    </div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h3>{{ $t('common.export') }}</h3>
        <el-form label-width="90px">
          <el-form-item :label="$t('dataset.timeRange')"><el-radio-group v-model="hours"><el-radio-button :value="2">{{ $t('timeRangePicker.last2Hours') }}</el-radio-button><el-radio-button :value="8">{{ $t('timeRangePicker.last8Hours') }}</el-radio-button>
            <el-radio-button :value="24">{{ $t('timeRangePicker.last24H') }}</el-radio-button></el-radio-group></el-form-item>
          <el-form-item :label="$t('common.tag')"><el-radio-group v-model="mode"><el-radio value="all">{{ $t('dataset.allTags') }}</el-radio><el-radio value="pick">{{ $t('dataset.selectTags') }}</el-radio></el-radio-group></el-form-item>
          <el-form-item v-if="mode === 'pick'" :label="$t('common.select')"><el-select v-model="keys" multiple filterable collapse-tags collapse-tags-tooltip style="width:100%" :placeholder="$t('dataset.enterASearchSuchAs')">
            <el-option v-for="k in info.keys" :key="k" :label="k" :value="k" /></el-select>
            <div style="margin-top:6px"><el-button v-for="p in PRESETS" :key="p[0]" size="small" @click="preset(p[1])">{{ p[0] }}</el-button></div></el-form-item>
        </el-form>
        <el-button type="primary" @click="go"><el-icon><Download /></el-icon>{{ $t('dataset.downloadDatasetZip') }}</el-button>
        <p class="small muted">{{ $t('dataset.forMoreLabeledAnomalySamples') }}</p></div>
      <div class="card"><h3>{{ $t('dataset.fileDescription') }}</h3>
        <el-table :data="FILES" size="small"><el-table-column prop="0" :label="$t('dataset.file')" width="110" /><el-table-column prop="1" :label="$t('common.content')" /></el-table>
        <h3 style="margin-top:12px">{{ $t('dataset.typicalUses') }}</h3>
        <ul class="small" style="padding-left:18px;line-height:1.9;margin:0">
          <li>{{ $t('dataset.anomalyDetectionPredictiveMaintenanc') }}</li>
          <li>{{ $t('dataset.qualityPredictionUsePouringParameter') }}</li>
          <li>{{ $t('dataset.toolWearSpindleLoadTools') }}</li></ul></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { onMounted, ref } from 'vue';
import { download, get, P } from '../api';

const props = defineProps<{ pid: string }>();
const api = P(props.pid), info = ref<any>(null), hours = ref(8), mode = ref('all'), keys = ref<string[]>([]);
const LT: Record<string, string> = { failure: $t('common.fault'), fault: $t('dataset.injectAnomaly'), planned: $t('common.plannedDowntime'), changeover: $t('common.changeover'), scenario: $t('common.scenario'), comm: $t('archView.communications') };
const FILES = [['tags.csv', $t('dataset.timeSeriesWideTableTime')], ['events.csv', $t('dataset.productionLogHeatsToolChanges')], ['parts.csv', $t('dataset.partRecordsPouringParametersActual')],
  ['labels.csv', $t('dataset.labeledIntervalsFailuresInjectedAnom')], ['README.md', $t('dataset.fieldDescription')]];
const PRESETS: [string, string][] = [[$t('dataset.spindleLoad'), 'Spindle/Load'], [$t('dataset.vibration'), 'Vibration'], [$t('store.sand'), 'Sand/'], [$t('heats.furnace'), 'Bath/'], [$t('common.power2'), 'PowerKW']];
function preset(p: string) { keys.value = [...new Set([...keys.value, ...info.value.keys.filter((k: string) => k.includes(p))])]; }
function go() { download(`${api}/dataset.zip?hours=${hours.value}${mode.value === 'pick' && keys.value.length ? '&keys=' + encodeURIComponent(keys.value.join(',')) : ''}`); }
onMounted(async () => { info.value = await get(api + '/dataset/info'); });
</script>
