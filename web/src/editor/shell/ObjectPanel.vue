<template>
  <div v-if="b" class="op">
    <!-- Layers and navigation -->
    <div class="op-top">
      <span class="op-layer" :style="{ background: layerInfo.color }">{{ layerInfo.label }}</span>
      <span class="grow" />
      <el-tooltip :content="$t('objectPanel.backAlt')"><el-button size="small" text :disabled="!canBack" @click="goBack"><el-icon><Back /></el-icon></el-button></el-tooltip>
      <el-tooltip :content="$t('objectPanel.forwardAlt')"><el-button size="small" text :disabled="!canFwd" @click="goFwd"><el-icon><Right /></el-icon></el-button></el-tooltip>
    </div>

    <!-- Quick actions by object type -->
    <div class="op-acts">
      <template v-if="layer === 'process'">
        <el-dropdown v-if="edit" trigger="click" @command="(c: string) => addPlcControl(b.id, c === '_new' ? undefined : c)">
          <el-button size="small" type="warning" plain><el-icon><Cpu /></el-icon>&nbsp;{{ rel.plcs.length ? $t('objectPanel.connectAnotherPlc') : $t('archView.addPlcControl') }}</el-button>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item command="_new">{{ $t('objectPanel.createANewPlcNearby') }}</el-dropdown-item>
            <el-dropdown-item v-for="p in plcs" :key="p.id" :command="p.id" :disabled="rel.plcs.includes(p.id)">{{ $t('objectPanel.connectToExisting0', [p.name]) }}</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
        <el-button size="small" @click="openInterior"><el-icon><Grid /></el-icon>{{ $t('objectPanel.equipmentInternals') }}</el-button>
        <el-button v-if="b.type === 'cell'" size="small" @click="openConsoleFor(b.id)"><el-icon><Operation /></el-icon>{{ $t('objectPanel.operatorPanel') }}</el-button>
      </template>
      <template v-if="b.type === 'plc'">
        <el-button size="small" type="warning" @click="openProgram"><el-icon><EditPen /></el-icon>{{ $t('objectPanel.programming') }}</el-button>
        <el-button v-if="cellOf" size="small" @click="openConsoleFor(cellOf)"><el-icon><Operation /></el-icon>{{ $t('objectPanel.operatorPanel') }}</el-button>
        <el-button v-if="canEdit()" size="small" @click="plcCmd(plcSt?.state === 'RUN' ? 'stop' : 'run')"><el-icon><component :is="plcSt?.state === 'RUN' ? 'VideoPause' : 'VideoPlay'" /></el-icon>&nbsp;{{ plcSt?.state === 'RUN' ? $t('objectPanel.stopPlc') : $t('objectPanel.runPlc') }}</el-button>
        <el-dropdown v-if="edit" trigger="click" @command="(c: string) => addPlcControl(c, b.id)">
          <el-button size="small"><el-icon><Plus /></el-icon>{{ $t('objectPanel.controlAMachine') }}</el-button>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item v-for="d in devicesFree" :key="d.id" :command="d.id">{{ d.name }}</el-dropdown-item>
            <el-dropdown-item v-if="!devicesFree.length" disabled>{{ $t('objectPanel.noEquipmentAvailableToConnect') }}</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
      </template>
      <template v-if="layer !== 'process' && edit">
        <el-dropdown trigger="click" @command="(c: string) => addNetwork(b.id, c === '_new' ? undefined : c)">
          <el-button size="small"><el-icon><Connection /></el-icon>{{ $t('objectPanel.connectToNetwork') }}</el-button>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item v-for="n in netTargets" :key="n.id" :command="n.id" :disabled="rel.network.includes(n.id)">{{ $t('objectPanel.connectTo0', [n.name]) }}</el-dropdown-item>
            <el-dropdown-item command="_new" divided>{{ $t('objectPanel.createASwitch') }}</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
      </template>
      <el-button v-if="['gateway', 'scada', 'mes'].includes(b.type)" size="small" @click="openPanelId('signals')"><el-icon><Tickets /></el-icon>{{ $t('objectPanel.tagList') }}</el-button>
      <el-tooltip v-if="layer === 'process'" :content="$t('objectPanel.toggleBreakpointF9')"><el-button size="small" :disabled="!edit" @click="toggleDefaultBp([b.id])"><el-icon><Flag /></el-icon>{{ $t('objectPanel.breakpoint') }}</el-button></el-tooltip>
    </div>

    <!-- Relationships: each item links to its target -->
    <el-collapse v-model="open" class="op-rel">
      <el-collapse-item name="rel">
        <template #title><b>{{ $t('objectPanel.connections') }}</b><small class="muted">{{ $t('objectPanel.items0ClickToNavigate', [relCount]) }}</small></template>
        <div v-if="rel.upstream.length || rel.downstream.length" class="op-row"><span class="op-k">{{ $t('common.material') }}</span>
          <div class="op-chips"><span v-for="x in rel.upstream" :key="'u' + x" class="op-chip" @click="goTo(x)" @mouseenter="ed.hoverId = x" @mouseleave="ed.hoverId = ''">← {{ nm(x) }}</span>
            <span v-for="x in rel.downstream" :key="'d' + x" class="op-chip" @click="goTo(x)" @mouseenter="ed.hoverId = x" @mouseleave="ed.hoverId = ''">{{ nm(x) }} →</span></div></div>
        <div v-if="rel.plcs.length" class="op-row"><span class="op-k">{{ $t('objectPanel.controlledBy') }}</span>
          <div class="op-chips"><span v-for="x in rel.plcs" :key="x" class="op-chip ctl" @click="goTo(x)">{{ nm(x) }}<i v-if="plcStatus[x]" :class="['op-st', plcStatus[x].state]">{{ plcStatus[x].label || plcStatus[x].state }}</i></span></div></div>
        <!-- Signal table: equipment shows which signal connects to which PLC channel; PLCs show all their channels -->
        <table v-if="rel.signals.length" class="op-sig">
          <tr><th>{{ b.type === 'plc' ? $t('common.channel') : $t('objectPanel.signals') }}</th><th></th><th>{{ b.type === 'plc' ? $t('objectPanel.equipmentSignal') : $t('objectPanel.plcChannel') }}</th><th v-if="ioVals">{{ $t('common.value') }}</th></tr>
          <tr v-for="s in sortedSignals" :key="s.link + s.point + s.ch">
            <template v-if="b.type === 'plc'">
              <td class="mono">{{ s.ch }}</td><td :class="s.dir">{{ s.dir === 'in' ? '←' : '→' }}</td>
              <td><a @click="goTo(s.device)">{{ nm(s.device) }}</a> · {{ pointLabel(s.device, s.point) }}</td>
            </template>
            <template v-else>
              <td>{{ pointLabel(b.id, s.point) }}</td><td :class="s.dir">{{ s.dir === 'in' ? '→' : '←' }}</td>
              <td><a @click="goTo(s.plc)">{{ nm(s.plc) }}</a> · <span class="mono">{{ s.ch }}</span></td>
            </template>
            <td v-if="ioVals" class="mono">{{ fmtVal(ioVals[s.ch + '|' + s.device]) }}</td>
          </tr>
        </table>
        <div v-if="rel.devices.length" class="op-row"><span class="op-k">{{ $t('objectPanel.controlledEquipment') }}</span>
          <div class="op-chips"><span v-for="x in rel.devices" :key="x" class="op-chip" @click="goTo(x)" @mouseenter="ed.hoverId = x" @mouseleave="ed.hoverId = ''">{{ nm(x) }}</span></div></div>
        <div v-if="rel.network.length" class="op-row"><span class="op-k">{{ $t('common.network') }}</span>
          <div class="op-chips"><span v-for="x in rel.network" :key="x" class="op-chip net" @click="goTo(x)">{{ nm(x) }}</span></div></div>
        <div v-if="rel.path.length" class="op-row"><span class="op-k">{{ $t('objectPanel.dataReporting') }}</span>
          <div class="op-path"><template v-for="(x, i) in rel.path" :key="x"><span v-if="i" class="muted">→</span><span class="op-chip" :class="layerOf(x)" @click="goTo(x)">{{ nm(x) }}</span></template></div></div>
        <p v-if="!relCount" class="muted small">{{ $t('objectPanel.notConnectedToOtherEquipment', [layer === 'process' ? $t('objectPanel.useAddPlcControlTo') : $t('objectPanel.useConnectToNetworkTo')]) }}</p>
      </el-collapse-item>
    </el-collapse>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Upper Objects panel (4.3): layers, navigation, type-specific shortcuts, and clickable "Links" (upstream/downstream material flow, PLC signals, network and data reporting paths).
import { computed, onUnmounted, ref, watch } from 'vue';
import { canEdit, get, P, post } from '../../api';
import { blocksById, ed, openFloat, typeOf } from '../store';
import { toggleDefaultBp } from './graphdebug';
import { panelById } from './panels';
import { canBack, canFwd, goBack, goFwd, goTo, layerOf, relationsOf } from './relations';
import { addNetwork, addPlcControl, controlPoints } from './wiring';

const props = defineProps<{ id: string }>();
const b = computed(() => blocksById.value[props.id]);
const t = computed(() => typeOf(b.value));
const layer = computed(() => t.value.layer || 'process');
const layerInfo = computed(() => ed.cat?.layers?.[layer.value] || { label: layer.value, color: '#888' });
const edit = computed(() => canEdit() && !ed.modelLocked);
const rel = computed(() => (ed.model, relationsOf(props.id)));
const relCount = computed(() => rel.value.upstream.length + rel.value.downstream.length + rel.value.plcs.length + rel.value.devices.length + rel.value.network.length);
const open = ref(['rel']);
const plcStatus = computed(() => ed.plcStatus || {});
const plcSt = computed(() => plcStatus.value[props.id]);
const nm = (id: string) => blocksById.value[id]?.name || id;
const plcs = computed(() => (ed.model?.blocks || []).filter((x: any) => x.type === 'plc'));
const devicesFree = computed(() => (ed.model?.blocks || []).filter((x: any) => (ed.cat?.types?.[x.type]?.layer || 'process') === 'process' && !rel.value.devices.includes(x.id)
  && !['operators', 'transporter', 'worker_crew', 'agv_fleet', 'submodel'].includes(x.type)));
const netTargets = computed(() => (ed.model?.blocks || []).filter((x: any) => x.id !== props.id && ['switch', 'gateway', 'scada', 'mes', 'plc', 'hmi'].includes(x.type)));
const sortedSignals = computed(() => [...rel.value.signals].sort((a, c) => (a.dir === c.dir ? a.ch.localeCompare(c.ch, 'en', { numeric: true }) : a.dir === 'in' ? -1 : 1)));
function pointLabel(dev: string, point: string) {
  const D = blocksById.value[dev]; if (!D) return point;
  const cp = controlPoints(D.type), x = [...cp.in, ...cp.out].find((p: any) => p.name === point);
  return x ? $t('common.n012', [x.label, point]) : point;
}

// Live PLC channel values (PLC-layer I/O interface; hide the "Value" column if unavailable)
const ioVals = ref<Record<string, any> | null>(null);
let timer: any = null;
async function loadIo() {
  if (b.value?.type !== 'plc' || ed.replay) { ioVals.value = null; return; }
  const r = await get(`${P(ed.pid)}/plc/${encodeURIComponent(props.id)}/io`, true).catch(() => null);
  ioVals.value = Array.isArray(r) ? Object.fromEntries(r.map((x: any) => [x.ch + '|' + x.device, x.forced === true ? $t('objectPanel.n0Forced', [fmtVal(x.value)]) : x.value])) : null;   // forced indicates a forced value; value is the effective value
}
watch(() => props.id, () => { clearInterval(timer); ioVals.value = null; loadIo(); timer = setInterval(loadIo, 1500); }, { immediate: true });
onUnmounted(() => clearInterval(timer));
const fmtVal = (v: any) => (v === undefined || v === null ? '' : typeof v === 'boolean' ? (v ? '1' : '0') : typeof v === 'number' ? +v.toFixed(2) : String(v));

function openPanelId(id: string) { window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id } })); }
/** PLC programming window: open by PLC block (the PLC-layer floating window accepts bid). */
function openProgram() {
  const p = panelById('plc-editor-float');
  if (p) openFloat(p as any, { bid: props.id }, props.id); else openPanelId('plc-editor');
}
/** Operator panel (control unit buttons and indicator lamps): reopen here after closing. */
const cellOf = computed(() => rel.value.devices.find((d: string) => blocksById.value[d]?.type === 'cell') || '');
async function openConsoleFor(cellId: string) {
  const m = await import('../../panels/cell/state');
  m.cs.bid = cellId; m.openConsole(true);
}
async function plcCmd(action: string) { await post(`${P(ed.pid)}/cells/${encodeURIComponent(props.id)}/plc`, { action }).catch(() => null); }
/** Equipment internals: control unit editor (shows control tags for regular equipment). */
function openInterior() { ed.interior = props.id; openPanelId('cell-editor'); }
</script>

<style>
.op { display: grid; gap: 8px; margin-bottom: 10px; }
.op-top { display: flex; align-items: center; gap: 4px; }
.op-layer { color: #fff; font-size: 11px; padding: 1px 8px; border-radius: 9px; }
.op-acts { display: flex; flex-wrap: wrap; gap: 6px; } .op-acts .el-button + .el-button { margin-left: 0; }
.op-rel .el-collapse-item__header { height: 32px; font-size: 12.5px; }
.op-row { display: flex; gap: 8px; align-items: flex-start; margin: 4px 0; } .op-k { flex: none; width: 64px; color: var(--mu); font-size: 12px; padding-top: 2px; }
.op-chips, .op-path { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
.op-chip { padding: 1px 8px; border-radius: var(--hm-r-pill); background: var(--hm-surface-2); border: 1px solid var(--ln); cursor: pointer; font-size: 12px; white-space: nowrap; }
.op-chip:hover { border-color: var(--sel); color: var(--sel); background: var(--hm-primary-soft); }
.op-chip.ctl, .op-chip.control { border-color: color-mix(in srgb, var(--sig) 55%, transparent); } .op-chip.net, .op-chip.network { border-color: color-mix(in srgb, var(--net) 55%, transparent); } .op-chip.it { border-color: color-mix(in srgb, var(--hm-run) 55%, transparent); }
.op-st { font-style: normal; margin-left: 6px; font-size: 10.5px; padding: 0 5px; border-radius: 7px; background: var(--hm-offline-ink); color: #fff; }
.op-st.RUN { background: var(--hm-run-ink); } .op-st.HALT { background: var(--hm-fault); }
.op-sig { width: 100%; border-collapse: collapse; font-size: 12px; margin: 4px 0; }
.op-sig th { text-align: left; color: var(--mu); font-weight: 500; padding: 2px 4px; border-bottom: 1px solid var(--ln); }
.op-sig td { padding: 2px 4px; border-bottom: 1px dashed var(--ln); } .op-sig a { color: var(--sel); cursor: pointer; }
.op-sig td.in { color: var(--hm-run-ink); } .op-sig td.out { color: var(--sig); }
</style>
