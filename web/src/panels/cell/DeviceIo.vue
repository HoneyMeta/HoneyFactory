<template>
  <div class="dio">
    <div class="dio-head">
      <b>{{ d?.name || bid }}</b><span class="muted small mono">{{ bid }}</span>
      <span class="grow" />
      <span class="dio-st" :class="d?.state">{{ stateText }}</span>
    </div>
    <div v-if="d?.waiting_plc" class="dio-wait">{{ $t('deviceIo.waitingForPlcEnableThe') }}</div>
    <p class="muted small dio-help">{{ $t('deviceIo.equipmentControlTagsOnThe') }}<template v-if="!d?.plcs?.length">{{ $t('deviceIo.thisEquipmentHasNoPlc') }}</template></p>
    <div v-if="!d" class="muted pad">{{ $t('common.loading') }}</div>
    <div v-else-if="!d.points.length" class="muted pad">{{ $t('deviceIo.thisEquipmentTypeHasNo') }}</div>
    <div v-else class="dio-cols">
      <div v-for="side in SIDES" :key="side.dir" class="dio-col">
        <div class="dio-ct">{{ side.title }}</div>
        <div v-for="p in d.points.filter((x: any) => x.dir === side.dir)" :key="p.name" class="dio-row" :class="{ on: p.value === true }">
          <i class="lamp" :class="{ on: p.value === true, num: p.type !== 'BOOL' }" />
          <div class="dio-nm">
            <span>{{ p.label }}</span> <span class="mono muted small">{{ p.name }}</span>
            <el-tooltip v-if="TIP[p.name] || p.help" :content="TIP[p.name] || p.help"><span class="q">?</span></el-tooltip>
          </div>
          <span class="mono val">{{ fmt(p) }}</span>
          <span v-if="p.wired.length" class="dio-ch">
            <a v-for="w in p.wired" :key="w.plc + w.ch" :title="$t('deviceIo.connectedToChannel1On', [w.plc_name, w.ch])" @click="goTo(w.plc)">{{ w.plc_name }} · {{ w.ch }}</a>
          </span>
          <span v-else-if="side.dir === 'out' && writable" class="dio-ch">
            <el-switch v-if="p.type === 'BOOL'" size="small" :model-value="!!p.value" @change="(v: any) => setPoint(p.name, v)" />
            <el-input-number v-else size="small" :model-value="Number(p.value) || 0" controls-position="right" style="width: 100px"
              @change="(v: any) => setPoint(p.name, v)" />
          </span>
          <span v-else class="muted small dio-ch">{{ $t('deviceIo.notWired') }}</span>
        </div>
      </div>
    </div>
    <div v-if="d?.plcs?.length" class="dio-plcs small">
      <span class="muted">{{ $t('deviceIo.controllingPlc') }}</span>
      <span v-for="p in d.plcs" :key="p.id" class="dio-plc"><a @click="goTo(p.id)">{{ p.name }}</a> <a class="muted" @click="openProgram(p.id)">{{ $t('cellInspector.openProgram') }}</a></span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { canEdit, get, P, post, toast } from '../../api';
import { ed, openFloat, STATE_CN } from '../../editor/store';
import { panelById } from '../../editor/shell/panels';
import { goTo } from '../../editor/shell/relations';
import { isStudent } from './state';

const props = defineProps<{ pid: string; bid: string }>();
const d = ref<any>(null);
const SIDES = [{ dir: 'in', title: $t('deviceIo.inputsEquipmentPlc') }, { dir: 'out', title: $t('deviceIo.outputsPlcEquipment') }];
const TIP: Record<string, string> = {
  Running: $t('deviceIo.n1WhileTheEquipmentIs'), Fault: $t('deviceIo.n1WhenTheEquipmentIs'), PartIn: $t('deviceIo.n1WhenAPartIs'), Count: $t('deviceIo.totalCompletedParts'),
  Enable: $t('deviceIo.whenThisChannelIsConnected'), Reset: $t('deviceIo.clearsTheEquipmentFaultOn'),
};
const writable = computed(() => canEdit() && !isStudent() && !ed.replay);
const stateText = computed(() => (d.value?.state === 'WaitPLC' ? $t('deviceIo.waitingForPlcEnable') : STATE_CN[d.value?.state] || d.value?.state || ''));
const fmt = (p: any) => (p.value === null || p.value === undefined ? '—' : typeof p.value === 'boolean' ? (p.value ? '1' : '0')
  : typeof p.value === 'number' ? String(+p.value.toFixed(2)) : String(p.value)) + (p.unit && typeof p.value === 'number' ? ' ' + p.unit : '');

let busy = '';
async function load() {
  if (!props.bid || !props.pid || busy === props.bid) return;      // A request for this device is still pending: do not send another
  const bid = props.bid;
  busy = bid;
  try {
    const r = await get(P(props.pid) + `/devices/${encodeURIComponent(bid)}/control`, true);
    if (bid === props.bid) d.value = r;                          // Discard stale responses received after switching devices
  } catch { /* Factory not running yet or rebuilding */ }
  finally { if (busy === bid) busy = ''; }
}
async function setPoint(name: string, value: any) {
  try { d.value = { ...d.value, points: (await post(P(props.pid) + `/devices/${encodeURIComponent(props.bid)}/control`, { point: name, value })).points }; }
  catch (e: any) { toast(e.message || String(e)); }
}
function openProgram(id: string) {
  const p = panelById('plc-editor-float');
  if (p) openFloat(p as any, { bid: id }, id); else window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor' } }));
}
let timer: any = null;
onMounted(() => { load(); timer = setInterval(load, 1000); });
onBeforeUnmount(() => clearInterval(timer));
watch(() => props.bid, () => { d.value = null; load(); });
</script>

<style>
.dio { display: grid; gap: 8px; padding: 2px 0; }
.dio-head { display: flex; align-items: center; gap: 6px; min-width: 0; white-space: nowrap; }
.dio-head .grow { flex: 1; }
.dio-st { font-size: 12px; padding: 1px 8px; border-radius: 9px; background: var(--el-fill-color); color: var(--el-text-color-regular); }
.dio-st.Executing { background: var(--el-color-success-light-8); color: var(--el-color-success-dark-2); }
.dio-st.WaitPLC { background: var(--el-color-warning-light-8); color: var(--el-color-warning-dark-2); }
.dio-st.Stopped { background: var(--el-color-danger-light-8); color: var(--el-color-danger); }
.dio-wait { font-size: 12px; padding: 6px 8px; border-radius: 6px; background: var(--el-color-warning-light-9); color: var(--el-color-warning-dark-2);
  border: 1px solid var(--el-color-warning-light-5); }
.dio-help { margin: 0; line-height: 1.6; }
.dio-cols { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; }
.dio-col { border: 1px solid var(--el-border-color-lighter); border-radius: 8px; padding: 6px 8px; background: var(--el-bg-color); }
.dio-ct { font-size: 12px; color: var(--el-text-color-secondary); margin-bottom: 4px; }
.dio-row { display: grid; grid-template-columns: 14px 1fr auto; grid-template-areas: 'l n v' '. c c'; align-items: center; column-gap: 6px;
  padding: 4px 0; border-bottom: 1px dashed var(--el-border-color-lighter); font-size: 12.5px; }
.dio-row:last-child { border-bottom: 0; }
.dio-row .lamp { grid-area: l; width: 10px; height: 10px; border-radius: 50%; background: var(--el-fill-color-darker); border: 1px solid var(--el-border-color); }
.dio-row .lamp.on { background: var(--el-color-success); border-color: var(--el-color-success-dark-2); }
.dio-row .lamp.num { border-radius: 2px; }
.dio-nm { grid-area: n; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dio-row .val { grid-area: v; }
.dio-ch { grid-area: c; font-size: 12px; display: flex; flex-wrap: wrap; gap: 6px; }
.dio-ch a, .dio-plcs a { color: var(--el-color-primary); cursor: pointer; }
.dio-plcs { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.dio-plc a + a { margin-left: 4px; }
.dio .q { display: inline-block; width: 14px; height: 14px; line-height: 14px; text-align: center; border-radius: 50%; font-size: 10px; cursor: help;
  background: var(--el-fill-color); color: var(--el-text-color-secondary); margin-left: 2px; }
</style>
