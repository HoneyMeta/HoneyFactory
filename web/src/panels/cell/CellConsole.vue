<template>
  <div class="cco">
    <div v-if="!cellBlocks.length" class="muted small pad">{{ $t('cellConsole.thisFactoryHasNoControl') }}</div>
    <template v-else>
      <div class="cco-h">
        <el-select v-if="cellBlocks.length > 1" v-model="cs.bid" size="small" style="width: 150px">
          <el-option v-for="b in cellBlocks" :key="b.id" :value="b.id" :label="`${b.id} ${b.name}`" /></el-select>
        <b v-else class="ttl" :title="blk?.name">{{ blk?.name }}</b>
        <span class="st" :class="'sk-' + (cstate?.kind || '')" data-k="console-state" :title="cstate?.text || rt?.alarm || rt?.hint || ''"><i :style="{ background: stateColor }" />{{ stateText }}
          <span v-if="rt?.alarm && !cstate" class="warn">· {{ rt.alarm }}</span></span>
        <span class="grow" />
        <span class="mono muted small" :title="$t('cellConsole.cellTimeStartsAt0')">{{ fmtT(live?.t) }}</span>
        <el-tooltip :content="$t('cellConsole.resetEquipmentClearPartsReset')">
          <el-button size="small" :loading="busy" :disabled="!canOperate" @click="reset"><el-icon><RefreshLeft /></el-icon>{{ $t('cellConsole.reset') }}</el-button></el-tooltip>
      </div>
      <!-- PLC has no program or is stopped: a normal starting state, not an alarm; clarify the next step (4.4) -->
      <div v-if="rt?.hint && !rt?.alarm" class="cco-hint" data-k="console-hint"><el-icon><InfoFilled /></el-icon>{{ rt.hint }}</div>
      <OperatorPanel :pid="pid" :cell="cell" :live="live" big />
      <div class="cco-f muted small">
        <span v-for="n in ncNames" :key="n" class="nc" :title="$t('cellConsole.n0IsAnNcInput', [n, n])">{{ $t('cellConsole.n0IsNc1When', [n]) }}</span>
        <span class="grow" />
        <a class="lnk" @click="openEditor">{{ $t('cellConsole.controlCellPanel') }}</a>
      </div>
      <!-- 4.5: Diagnostics, checklist, and run log—show what happened immediately after a button press -->
      <div v-if="co.s.diag && diagFresh" class="cco-diag" data-k="console-diag"><b>{{ $t('cellConsole.whyNothingIsHappening') }}</b>{{ co.s.diag.msg }}</div>
      <div class="cco-tabs">
        <button :class="{ on: sub === 'log' }" data-tab="console-log" @click="sub = 'log'">{{ $t('cellConsole.runLog') }}</button>
        <button v-if="co.s.checklist" :class="{ on: sub === 'check' }" data-tab="console-check" @click="sub = 'check'">{{ $t('cellConsole.checklist') }}
          <b v-if="co.s.checklist.total" class="cnt">{{ co.s.checklist.done }}/{{ co.s.checklist.total }}</b></button>
        <span class="grow" />
      </div>
      <div class="cco-sub">
        <RunLog v-if="sub === 'log'" :pid="pid" compact />
        <div v-else class="cco-ck"><Checklist :pid="pid" compact /></div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Floating cell operator panel (opens at the bottom right of the canvas by default in student control-cell sandboxes): large buttons, E-Stop, indicator lamps, numeric display, and equipment reset.
import { ElMessage } from 'element-plus';
import { computed, onBeforeUnmount, onMounted, ref } from 'vue';
import { canEdit, P, post, session } from '../../api';
import { blocksById, rtById, STATE_CN, STATE_COLOR } from '../../editor/store';
import OperatorPanel from './OperatorPanel.vue';
import RunLog from '../teach/RunLog.vue';
import Checklist from '../teach/Checklist.vue';
import { useCoach } from '../teach/coach';
import { cellBlocks, cs, curCell, curLive, followSelection } from './state';

const props = defineProps<{ pid: string }>();
const busy = ref(false);
const co = useCoach(props.pid);
const sub = ref('log');
const cstate = computed<any>(() => co.s.state);
/** One-line status: whether the PLC is running and which outputs are energized (4.5: never show "Idle" while the PLC is running). */
const stateText = computed(() => cstate.value?.text || (rt.value ? (rt.value.hint && !rt.value.alarm ? $t('cellConsole.waitingForPlcProgram') : STATE_CN[rt.value.state] || rt.value.state) : $t('cellConsole.notRunning')));
const stateColor = computed(() => ({ run: '#15a34a', idle: '#94a3b8', warn: '#d99a16', err: '#dc2b2b' } as any)[cstate.value?.kind] || STATE_COLOR[rt.value?.state] || '#888');
const diagFresh = computed(() => !!co.s.diag && Date.now() - (co.s.diag.wall || 0) < 120000 && co.s.at > 0);
const cell = curCell, live = curLive;
const blk = computed(() => blocksById.value[cs.bid]);
const rt = computed(() => (cs.bid ? rtById.value[cs.bid] : null));
const canOperate = computed(() => canEdit() || ['student', 'teacher'].includes(session.user?.role));
const ncNames = computed(() => (cell.value?.io || []).filter((e: any) => e.dir === 'in' && e.contact === 'NC').map((e: any) => e.name));
const fmtT = (t: any) => (typeof t === 'number' ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}` : '—');
async function reset() {
  busy.value = true;
  try {
    await post(P(props.pid) + `/cells/${cs.bid}/reset`, {});
    ElMessage.success($t('cellConsole.equipmentResetToItsInitial'));
  } finally { busy.value = false; }
}
function openEditor() { window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'cell-editor' } })); }
onMounted(() => followSelection());
// Follow the tutorial / AI Tutor's "Take me there": switch to the run log or checklist (tour.ts emits vf:console-tab)
function onTab(e: any) { const t = e.detail?.tab; if (t === 'log' || t === 'check') sub.value = t; }
addEventListener('vf:console-tab', onTab);
onBeforeUnmount(() => removeEventListener('vf:console-tab', onTab));
</script>

<style scoped>
.cco { display: flex; flex-direction: column; gap: 6px; padding: 8px 10px; height: 100%; box-sizing: border-box; color: var(--el-text-color-primary); background: var(--el-bg-color); }
.cco-h { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ttl { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 160px; }
.st { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; font-size: 12px; }
.st i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; }
.warn { color: var(--el-color-warning); }
.cco-hint { display: flex; align-items: center; gap: 6px; font-size: 12px; line-height: 1.5; color: var(--el-color-primary-dark-2, #ae7b12); background: var(--el-color-primary-light-9); border-radius: 4px; padding: 4px 8px; }
.grow { flex: 1; } .muted { color: var(--el-text-color-secondary); } .small { font-size: 11.5px; } .mono { font-family: Consolas, monospace; } .pad { padding: 10px; }
.cco-f { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.nc { background: var(--el-color-warning-light-9); color: var(--el-color-warning-dark-2); border-radius: 3px; padding: 0 5px; }
.lnk { cursor: pointer; color: var(--el-color-primary); }
.sk-run { color: var(--el-color-success); } .sk-err { color: var(--el-color-danger); } .sk-warn { color: var(--el-color-warning-dark-2, #b7791f); }
.cco-diag { font-size: 12px; line-height: 1.55; padding: 5px 8px; border-radius: 4px; background: var(--el-color-danger-light-9); color: var(--el-color-danger);
  border: 1px solid var(--el-color-danger-light-5); max-height: 74px; overflow: auto; }
.cco-diag b { margin-right: 2px; }
.cco-tabs { display: flex; gap: 2px; border-bottom: 1px solid var(--el-border-color-lighter); }
.cco-tabs button { border: 0; background: none; padding: 3px 10px; font-size: 12px; color: var(--el-text-color-secondary); cursor: pointer; border-bottom: 2px solid transparent; }
.cco-tabs button.on { color: var(--el-text-color-primary); border-bottom-color: var(--el-color-primary); }
.cco-tabs .cnt { font-size: 10px; font-weight: 600; margin-left: 3px; color: var(--el-color-primary); }
.cco-sub { flex: 1; min-height: 90px; display: flex; flex-direction: column; }
.cco-ck { flex: 1; min-height: 0; overflow: auto; }
</style>
