<template>
  <div class="plc-root ps">
    <div class="ps-h">
      <el-select v-model="bid" size="small" style="flex: 1" placeholder="PLC">
        <el-option v-for="o in options" :key="o.id" :value="o.id" :label="o.label" />
      </el-select>
    </div>
    <EmptyCells v-if="noCells && bid === '_sandbox'" compact :running="running" :title="$t('plcSide.noPlcYetAPractice')"
      :desc="$t('plcSide.thePracticePlcIsNot')" />
    <template v-if="sess && S.program">
      <div class="ps-st">
        <span class="plc-chip" :class="st">{{ STATE_CN[st] || '—' }}<i /></span>
        <span class="muted small">{{ S.program.lang === 'LD' ? $t('plcSide.ladderDiagram') : 'ST' }} · {{ S.program.name || $t('plcSide.mainProgram') }}</span>
        <span class="grow" />
        <span v-if="S.online?.scan && st !== 'EXTERNAL'" class="mono small muted" :title="$t('plcSide.lastScanDurationScanCycle')">{{ S.online.scan.last_ms.toFixed(2) }}/{{ S.online.scan.cycle_ms }} ms</span>
      </div>
      <div v-if="st === 'HALT'" class="ps-halt">{{ $t('plcSide.n0OutputsRemainUnchanged', [S.online?.label || $t('common.pause')]) }}
        <button v-if="!ro" class="plc-btn go" @click="act('run')">{{ $t('common.continue') }}</button>
        <button v-if="!ro" class="plc-btn" @click="sessRef?.act({ action: 'step', kind: 'stmt' })">{{ $t('common.step') }}</button></div>
      <div v-if="S.online?.scan?.over && st !== 'EXTERNAL'" class="ps-msg warn" :title="$t('plcSide.scanCycle0MsLongest', [S.online.scan.cycle_ms, S.online.scan.max_ms.toFixed(1)])">{{ $t('plcSide.scansExceedingTheCycleTime', [S.online.scan.over, S.online.scan.max_ms.toFixed(1)]) }}</div>
      <div v-if="S.online?.error" class="ps-err">✖ {{ S.online.error.msg }}</div>
      <div v-if="st === 'EXTERNAL'" class="ps-ext">{{ $t('plcSide.externalPlc012', [S.online.external?.protocol_cn, S.online.external?.connected ? $t('common.connected') : $t('externalPanel.notConnected'), S.online.external?.peer]) }}
        <div v-if="S.online.external?.error" class="bad">{{ S.online.external.error }}</div></div>
      <div class="ps-btns">
        <button class="plc-btn pri" :title="$t('plcSide.openTheLdStProgramming')" data-act="open-editor" @click="openEditor()"><el-icon><EditPen /></el-icon>{{ $t('common.program2') }}</button>
        <button class="plc-btn" :disabled="!!S.busy || st === 'EXTERNAL' || ro" :title="$t('plcSide.compileTheCurrentProgramAnd')" @click="sess.download(false)"><el-icon><Download /></el-icon>{{ $t('common.download') }}</button>
        <button class="plc-btn go" :class="{ on: st === 'RUN' }" :disabled="st === 'EXTERNAL' || ro" :title="$t('plcSide.runThePlcProgram')" @click="act('run')"><el-icon><VideoPlay /></el-icon>{{ $t('common.run') }}</button>
        <button class="plc-btn st" :disabled="st === 'EXTERNAL' || ro" :title="$t('plcSide.stopThePlcAllOutputs')" @click="act('stop')"><el-icon><VideoPause /></el-icon>{{ $t('common.stop') }}</button>
        <button class="plc-btn" :title="$t('plcSide.openTheHmiScreen')" @click="openHmi()"><el-icon><Monitor /></el-icon>HMI</button>
      </div>
      <div v-if="S.errors.length" class="ps-msg bad" @click="openEditor('msg')">{{ $t('plcSide.compileErrors01', [S.errors.length, S.errors[0].msg]) }}</div>
      <div v-else-if="sess.dirty" class="ps-msg warn">{{ $t('plcSide.programChangesHaveNotBeen') }}</div>
      <div class="ps-tip muted">{{ $t('plcSide.iOMonitorClick1') }}</div>
      <div class="ps-io"><IoTable :sess="sess" compact /></div>
    </template>
    <div v-else class="muted pad">{{ $t('plcSide.reading') }}</div>
    <PlcHaltBar :pid="pid" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import './plc.css';
import { computed, markRaw, onBeforeUnmount, shallowRef, watch } from 'vue';
import { openFloat } from '../editor/store';
import { useCells } from './cells';
import EmptyCells from './EmptyCells.vue';
import IoTable from './IoTable.vue';
import PlcHaltBar from './PlcHaltBar.vue';
import { canEdit } from '../api';
import { STATE_CN } from './plcApi';
import { Sess, useSession } from './session';

const props = defineProps<{ pid: string }>();
const { bid, options, noCells, running } = useCells(() => props.pid);
const ro = computed(() => !canEdit());
const sessRef = shallowRef<Sess | null>(null);
const sess = computed(() => sessRef.value as Sess);
const S = computed(() => (sessRef.value?.s || { errors: [], online: null, program: null }) as any);
const st = computed(() => S.value.online?.state || '');
let release: (() => void) | null = null;
watch(bid, async (b) => {
  release?.(); release = null;
  if (!b) return;
  const s = useSession(props.pid, b);
  sessRef.value = s; release = s.use();
  try { await s.load(); } catch { /* Already notified */ }
}, { immediate: true });
onBeforeUnmount(() => release?.());
async function act(a: string) { try { await sessRef.value!.act({ action: a }); } catch { /* Already notified */ } }
function openEditor(tab = 'prog') {
  import('./PlcWorkbench.vue').then((m) => openFloat({ id: 'plc-editor-float', title: $t('common.plcProgramming'), icon: 'Cpu', component: markRaw(m.default), size: [1240, 760] },
    { bid: bid.value, tab }, bid.value));
}
function openHmi() {
  import('./HmiPanel.vue').then((m) => openFloat({ id: 'plc-hmi', title: $t('plcIndex.hmiScreens'), icon: 'Monitor', component: markRaw(m.default), size: [1000, 640] }, { bid: bid.value }));
}
</script>

<style scoped>
.ps { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ld-card); }
.ps-h { display: flex; gap: 6px; padding: 8px; border-bottom: 1px solid var(--ld-ln); }
.ps-st { display: flex; align-items: center; gap: 8px; padding: 6px 8px; }
.ps-btns { display: flex; gap: 4px; padding: 0 8px 8px; flex-wrap: wrap; }
.ps-err { margin: 0 8px 6px; padding: 4px 8px; border-radius: 4px; background: var(--ld-bad-bg); color: var(--ld-bad); font-size: 12px; }
.ps-ext { margin: 0 8px 6px; padding: 4px 8px; border-radius: 4px; background: var(--ld-info-bg); font-size: 12px; }
.ps-msg { margin: 0 8px 6px; font-size: 12px; cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ps-msg.bad, .bad { color: var(--ld-bad); } .ps-msg.warn { color: var(--ld-warn); }
.ps-tip { padding: 0 8px 4px; font-size: 11.5px; line-height: 1.5; }
.ps-halt { margin: 0 8px 6px; padding: 5px 8px; border-radius: 4px; background: var(--ld-halt-bg); font-size: 12px; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.ps-halt .plc-btn { height: 22px; }
.ps-io { flex: 1; min-height: 0; border-top: 1px solid var(--ld-ln); }
.small { font-size: 11.5px; } .pad { padding: 14px; } .grow { flex: 1; }
</style>
