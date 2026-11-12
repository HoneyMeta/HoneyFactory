<template>
  <!-- Local MES not running (or starting/switching factories): select a local factory to start MES; create a demo factory if none exist -->
  <div class="page mes-start">
    <div class="page-head" data-tour="mes-head">
      <h2>MES</h2>
      <span class="sub">{{ $t('mesStart.teachingMesWorkOrdersScheduling') }}</span>
      <span class="grow" />
      <el-button v-if="st?.state === 'running' && mes.picking" data-k="mes-resume" @click="mes.picking = false"><el-icon><Back /></el-icon>{{ $t('mesStart.backToMes0', [st.plant_name]) }}</el-button>
      <GuideButton area="mes" />
    </div>

    <el-alert v-if="st && !st.available" type="warning" :closable="false" show-icon :title="$t('mesStart.mesModuleNotInstalled')"
      :description="$t('mesStart.thisDesktopClientDoesNot')" class="al" />
    <el-alert v-if="mes.failed" type="warning" :closable="false" show-icon :title="$t('mesStart.cannotRetrieveLocalMesStatus')" :description="$t('mesStart.theLocalServiceIsNot')" class="al" />
    <el-alert v-if="st?.stopped_why && st.state === 'stopped'" type="info" :closable="false" show-icon :title="$t('mesStart.mesStopped') + st.stopped_why" class="al" data-k="mes-stopped" />
    <el-alert v-if="st?.state === 'error'" type="error" :closable="false" show-icon :title="$t('mesStart.mesError') + (st.error || '')" class="al" />

    <div v-if="mes.starting || st?.state === 'starting' || connecting" class="card starting" data-k="mes-starting">
      <el-icon class="is-loading" :size="22"><Loading /></el-icon>
      <div><b>{{ connecting ? $t('mesStart.connectingToMes') : $t('mesStart.startingMes0', [startName]) }}</b>
        <div class="muted small">{{ $t('mesStart.enableMqttOpcUaFor') }}</div></div>
    </div>

    <template v-else-if="st">
      <div class="steps" data-tour="mes-steps">
        <span class="stp"><b>1</b>{{ $t('mesStart.selectALocalFactory') }}</span><i class="ar" /><span class="stp"><b>2</b>{{ $t('mesStart.startMesRestartsTheFactory') }}</span><i class="ar" />
        <span class="stp"><b>3</b>{{ $t('mesStart.useTheLeftMesMenu') }}</span>
      </div>
      <div v-if="st.plants.length" class="grid g-auto plants" data-tour="mes-plants" style="--min: 300px">
        <div v-for="p in st.plants" :key="p.id" class="pl card" :class="{ on: sel === p.id }" :data-pid="p.id" tabindex="0" @click="sel = p.id" @keyup.enter="sel = p.id"
          @dblclick="emit('start', p.id)">
          <div class="pl-h">
            <el-icon class="pl-i"><component :is="p.sandbox ? 'School' : 'OfficeBuilding'" /></el-icon>
            <b class="pl-n" :title="p.name">{{ p.name }}</b>
            <span v-if="p.fit" class="tag-st st-running">{{ $t('common.recommended') }}</span>
            <span v-if="p.running" class="tag-st st-setup">{{ $t('mesStart.mesRunning') }}</span>
          </div>
          <div class="pl-m muted">{{ $t('mesStart.n01Machines2Recognized', [p.sandbox ? $t('common.labSandbox') : $t('mesStart.localFactories'), p.stations, p.mes_devices, p.protocols ? $t('mesStart.protocolsEnabled') : '']) }}</div>
          <div v-if="!p.fit" class="pl-m warn small">{{ $t('mesStart.mesDoesNotRecognizeAll') }}</div>
        </div>
      </div>
      <div v-else class="card empty" data-k="mes-empty" data-tour="mes-empty">
        <el-icon :size="36" class="em-i"><OfficeBuilding /></el-icon>
        <div class="em-t">{{ $t('mesStart.noLocalPlantsOnThis') }}</div>
        <div class="em-d">{{ $t('mesStart.mesConnectsOnlyToPlants') }}</div>
        <div style="margin-top: 12px">
          <el-button type="primary" :loading="busy === 'new'" data-k="mes-new" data-tour="mes-new" @click="newShowcase"><el-icon><Plus /></el-icon>{{ $t('mesStart.createLocalDemoPlant') }}</el-button>
          <el-button v-if="st.mode === 'server'" @click="toDownload">{{ $t('mesStart.downloadToThisComputer') }}</el-button>
        </div>
      </div>
      <div v-if="st.plants.length" class="acts">
        <el-button type="primary" :disabled="!sel || !st.available" data-k="mes-open" data-tour="mes-open" @click="emit('start', sel)">
          <el-icon><VideoPlay /></el-icon>{{ runningSel ? $t('mesStart.openMes') : $t('mesStart.startAndOpenMes') }}</el-button>
        <el-button v-if="st.state === 'running'" @click="emit('stop')">{{ $t('mesStart.stopMes0', [st.plant_name]) }}</el-button>
        <el-button text :loading="busy === 'new'" @click="newShowcase"><el-icon><Plus /></el-icon>{{ $t('mesStart.createLocalDemoPlant') }}</el-button>
        <span class="grow" />
        <span class="muted small">{{ $t('common.idle2') }}
          <el-select v-model="idle" size="small" style="width: 110px" data-k="mes-idle-min" @change="saveIdle">
            <el-option v-for="o in [15, 30, 60, 120, 0]" :key="o" :label="o ? o + $t('ganttChart.min') : $t('mesStart.doNotStopAutomatically')" :value="o" />
          </el-select> {{ $t('mesStart.stopAutomaticallyAfter') }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { post as vpost, put as vput } from '../api';
import GuideButton from '../components/GuideButton.vue';
import { mes } from './api';

const emit = defineEmits(['start', 'stop', 'reload']);
const route = useRoute(), router = useRouter();
const st = computed(() => mes.st);
const sel = ref(String(route.query.pid || ''));
const busy = ref('');
const idle = ref(30);
const runningSel = computed(() => st.value?.state === 'running' && st.value.pid === sel.value);
const startName = computed(() => st.value?.plants?.find((p: any) => p.id === (mes.starting || st.value?.pid))?.name || st.value?.plant_name || '');
// MES running, session not fetched yet (just started or switched factories)
const connecting = computed(() => st.value?.state === 'running' && !mes.picking && !mes.starting);
watch(st, (v) => {
  if (!v) return;
  idle.value = v.idle_min;
  const ids = (v.plants || []).map((p: any) => p.id);
  if (!sel.value || !ids.includes(sel.value)) sel.value = (v.state === 'running' && v.pid) || (ids.includes(v.last_pid) && v.last_pid) || v.plants?.find((p: any) => p.fit)?.id || ids[0] || '';
}, { immediate: true });

async function saveIdle(v: number) { mes.st = { ...mes.st, ...(await vput('/api/desktop/mes/settings', { idle_min: v })) }; }
async function newShowcase() {
  busy.value = 'new';
  try {
    const r = await vpost('/api/client/myplants', { name: $t('mesStart.myDemoPlant'), template: 'showcase' });
    ElMessage.success($t('mesStart.localPlantCreated0', [r.name]));
    sel.value = r.id;
    emit('reload');
  } finally { busy.value = ''; }
}
function toDownload() {
  ElMessage.info($t('mesStart.inAllPlantsOpenThe'));
  router.push('/');
}
</script>

<style scoped>
.al { margin-bottom: 12px; }
.steps { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin: 0 0 14px; font-size: var(--hm-fs-xs); color: var(--hm-text-2); }
.stp { display: inline-flex; align-items: center; gap: 6px; }
.stp b { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%; background: var(--hm-primary-soft); color: var(--hm-primary); font-size: 11px; }
.ar { width: 14px; height: 1px; background: var(--hm-border-strong); }
.pl { cursor: pointer; display: flex; flex-direction: column; gap: 6px; transition: box-shadow var(--hm-dur-2) var(--hm-ease), border-color var(--hm-dur-2) var(--hm-ease); }
.pl:hover { border-color: var(--hm-border-strong); box-shadow: var(--hm-e2); }
.pl.on { border-color: var(--hm-primary); box-shadow: 0 0 0 1px var(--hm-primary) inset, var(--hm-e1); }
.pl-h { display: flex; align-items: center; gap: 8px; min-width: 0; }
.pl-i { color: var(--hm-primary); font-size: 20px; flex: none; }
.pl-n { font-size: var(--hm-fs-md); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; color: var(--hm-text); }
.pl-m { font-size: var(--hm-fs-xs); }
.acts { display: flex; align-items: center; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
.starting { display: flex; gap: 12px; align-items: center; max-width: 720px; }
.starting .el-icon { color: var(--hm-primary); }
.empty { max-width: 560px; margin: 40px auto; text-align: center; padding: 30px; }
.em-i { color: var(--hm-primary); } .em-t { font-size: var(--hm-fs-lg); font-weight: 600; margin-top: 6px; color: var(--hm-text); }
.em-d { font-size: var(--hm-fs-sm); color: var(--hm-text-2); margin-top: 6px; line-height: 1.7; }
</style>
