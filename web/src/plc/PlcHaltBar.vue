<template>
  <!-- Non-modal banner when the PLC is halted at a breakpoint or stepping (visible even with the editor closed). Mount one in the shell: <PlcHaltBar :pid="pid" />; each PLC panel also mounts one, but only one is shown at a time. -->
  <transition name="phb">
    <div v-if="mine && halted.length" class="plc-root phb" data-plc-halt role="status">
      <div v-for="c in halted" :key="c.bid" class="row">
        <span class="dot" />
        <b>{{ $t('plcHaltBar.plcPausedAt0', [where(c)]) }}</b>
        <span class="muted">{{ $t('plcHaltBar.n01OutputsRemainUnchanged', [c.name, c.halt?.reason === 'breakpoint' ? $t('common.breakpoint') : $t('common.step')]) }}</span>
        <button class="plc-btn go" data-act="halt-continue" :title="$t('plcHaltBar.resumeExecutionPausesAgainAt')" @click="act(c, { action: 'run' })"><el-icon><VideoPlay /></el-icon>{{ $t('common.continue') }}</button>
        <button class="plc-btn" data-act="halt-step" :title="c.lang === 'LD' ? $t('plcHaltBar.executeOneRungThenPause') : $t('plcHaltBar.executeOneStatementThenPause')" @click="act(c, { action: 'step', kind: 'stmt' })"><el-icon><Bottom /></el-icon>{{ $t('common.step') }}</button>
        <button v-if="c.halt?.reason === 'breakpoint'" class="plc-btn" :title="$t('plcHaltBar.removeThisBreakpointAndResume')" @click="clearAndRun(c)">{{ $t('plcHaltBar.removeBreakpointAndResume') }}</button>
        <button class="plc-btn" :title="$t('plcHaltBar.openThePlcProgramAt')" @click="open(c)"><el-icon><EditPen /></el-icon>{{ $t('assistantDock.viewProgram') }}</button>
      </div>
    </div>
  </transition>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, markRaw, onBeforeUnmount, ref } from 'vue';
import { openFloat } from '../editor/store';
import { plcAct, usePlcWatch } from './plcWatch';

const props = defineProps<{ pid: string }>();
const { status } = usePlcWatch(props.pid);
// Show only one banner at a time (both shell and panel may have one mounted)
const W = window as any;
W.__vfHaltBarSeq = (W.__vfHaltBarSeq || 0) + 1;
const id: number = W.__vfHaltBarSeq;
const owners: number[] = (W.__vfHaltBarOwners ||= []);
owners.push(id);
const tickRef = ref(0);
const mine = computed(() => { void tickRef.value; return owners[0] === id; });
onBeforeUnmount(() => { const i = owners.indexOf(id); if (i >= 0) owners.splice(i, 1); window.dispatchEvent(new Event('vf:halt-owner')); });
const onOwner = () => tickRef.value++;
window.addEventListener('vf:halt-owner', onOwner);
onBeforeUnmount(() => window.removeEventListener('vf:halt-owner', onOwner));
const halted = computed(() => (status.cells || []).filter((c: any) => c.state === 'HALT'));

function where(c: any) {
  const h = c.halt || {};
  if (h.line) return $t('common.row0', [h.line]);
  if (h.rung !== undefined && h.rung !== null) return $t('common.rung0', [h.rung + 1]);
  return $t('plcHaltBar.endOfScanCycle');
}
async function act(c: any, body: any) { try { await plcAct(props.pid, c.bid, body); } catch { /* Already notified */ } }
async function clearAndRun(c: any) {
  const h = c.halt || {};
  await act(c, h.line ? { action: 'breakpoint', line: h.line, on: false } : { action: 'breakpoint', rung: h.rung, on: false });
  await act(c, { action: 'run' });
}
function open(c: any) {
  import('./PlcWorkbench.vue').then((m) => openFloat({ id: 'plc-editor-float', title: $t('common.plcProgramming'), icon: 'EditPen', component: markRaw(m.default), size: [1240, 760] },
    { bid: c.bid }, c.bid));
}
</script>

<style scoped>
.phb { position: fixed; top: 92px; left: 50%; transform: translateX(-50%); z-index: 3000; display: flex; flex-direction: column; gap: 4px; padding: 8px 12px;
  border-radius: 8px; background: var(--ld-card); border: 1px solid var(--ld-halt); box-shadow: 0 8px 24px var(--ld-shadow); max-width: min(980px, 92vw); }
.row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--ld-halt); box-shadow: 0 0 0 4px var(--ld-halt-bg); }
.muted { color: var(--ld-mu); font-size: 12px; }
.plc-btn { height: 26px; }
.phb-enter-active, .phb-leave-active { transition: opacity .15s, transform .15s; }
.phb-enter-from, .phb-leave-to { opacity: 0; transform: translate(-50%, -6px); }
</style>
