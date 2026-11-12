<template>
  <div ref="root" class="ce" :class="{ wide: isWide }">
    <div v-if="!cs.dev" class="ce-head">
      <el-select v-model="cs.bid" size="small" :placeholder="$t('cellEditor.selectControlCell')" class="ce-sel" @change="cs.comp = ''">
        <el-option v-for="b in cellBlocks" :key="b.id" :value="b.id" :label="`${b.id} ${b.name}`" />
      </el-select>
      <el-tooltip :content="$t('cellEditor.newControlCellBlock')"><el-button size="small" :disabled="!editable" @click="addCell()"><el-icon><Plus /></el-icon></el-button></el-tooltip>
      <el-dropdown v-if="editable" size="small" trigger="click" @command="loadScene">
        <el-button size="small" :disabled="!cs.bid">{{ $t('cellEditor.scenarioLibrary') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
        <template #dropdown><el-dropdown-menu class="ce-scenes">
          <el-dropdown-item v-for="s in scenes" :key="s.id" :command="s.id"><b class="lv">{{ s.level }}</b> {{ s.name }}</el-dropdown-item>
        </el-dropdown-menu></template>
      </el-dropdown>
      <el-tooltip v-if="!isWide" :content="$t('cellEditor.expandedEditorFloorPlan3d')"><el-button size="small" :disabled="!cs.bid" @click="openWide"><el-icon><FullScreen /></el-icon></el-button></el-tooltip>
    </div>

    <div v-if="cs.dev" class="ce-dev">
      <div class="ce-devbar small">
        <span class="muted">{{ $t('common.equipmentInterior') }}</span>
        <span class="grow" />
        <el-button v-if="cellBlocks.length" size="small" text type="primary" @click="cs.dev = ''">{{ $t('cellEditor.viewControlCell') }}</el-button>
      </div>
      <DeviceIo :pid="pid" :bid="cs.dev" />
    </div>

    <div v-else-if="!cellBlocks.length" class="ce-empty">
      <div class="ce-empty-ic"><el-icon><Cpu /></el-icon></div>
      <b>{{ $t('cellEditor.thisFactoryHasNoControl') }}</b>
      <p class="muted">{{ $t('cellEditor.aControlCellIsAn') }}</p>
      <template v-if="editable">
        <el-button type="primary" @click="addCell()"><el-icon><Plus /></el-icon>{{ $t('cellEditor.newBlankControlCell') }}</el-button>
        <el-dropdown trigger="click" @command="(sid: string) => addCell(sid)">
          <el-button>{{ $t('cellEditor.createFromLabScenario') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
          <template #dropdown><el-dropdown-menu class="ce-scenes">
            <el-dropdown-item v-for="s in scenes" :key="s.id" :command="s.id"><b class="lv">{{ s.level }}</b> {{ s.name }}</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
        <p class="muted small">{{ $t('cellEditor.labScenariosIncludeAComponent') }}</p>
      </template>
      <p v-else class="muted small">{{ $t('cellEditor.yourAccountHasViewOnly') }}</p>
    </div>

    <template v-else-if="cell">
      <div class="ce-status" :title="statusText">
        <span class="dot" :style="{ background: stColor }" /> <span class="st-t">{{ rt ? (STATE_CN[rt.state] || rt.state) : $t('cellEditor.notRunningNewCellsStart') }}</span>
        <span v-if="rt?.alarm" class="bad st-a">⚠ {{ rt.alarm }}</span>
        <span class="grow" />
        <span v-if="cellPlcs.length" class="st-plc">
          <a v-for="p in cellPlcs" :key="p" :title="$t('cellEditor.thePlcControllingThisCell')" @click="goTo(p)">{{ blockName(p) }}</a>
          <a class="muted" :title="$t('common.openPlcProgram')" @click="openProgram(cellPlcs[0])">{{ $t('common.program') }}</a>
        </span>
        <span v-else class="warn st-n" :title="$t('cellEditor.connectTheCellSI')">{{ $t('cellEditor.noPlcConnected') }}</span>
        <span class="muted st-n">{{ $t('cellEditor.components0IO1', [(cell.components || []).length, (cell.io || []).length]) }}</span>
        <el-tooltip :content="$t('cellEditor.applyTheCurrentDefinitionTo')">
          <el-button v-if="editable" size="small" type="primary" plain :loading="cs.busy" :disabled="!rt" @click="apply">{{ $t('common.apply') }}</el-button></el-tooltip>
      </div>

      <div v-if="!(cell.components || []).length" class="ce-hint">
        <span>{{ $t('cellEditor.noComponentsInThisCell') }}</span>
        <el-dropdown v-if="editable" trigger="click" @command="loadScene">
          <el-button size="small" type="primary" plain>{{ $t('cellEditor.loadLabScenarioLayout') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
          <template #dropdown><el-dropdown-menu class="ce-scenes">
            <el-dropdown-item v-for="s in scenes" :key="s.id" :command="s.id"><b class="lv">{{ s.level }}</b> {{ s.name }}</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
      </div>
      <div class="ce-main">
        <div v-if="editable" class="ce-pal" :class="{ open: palOpen }">
          <div class="pal-h" @click="palOpen = !palOpen"><el-icon><Box /></el-icon> {{ $t('cellEditor.componentLibrary') }} <span class="grow" /><el-icon><component :is="palOpen ? 'ArrowUp' : 'ArrowDown'" /></el-icon></div>
          <template v-if="palOpen || isWide">
            <div v-for="cat in cs.cat?.cats || []" :key="cat" class="pal-cat">
              <div class="pal-ct">{{ cat }}</div>
              <div class="pal-items">
                <button v-for="t in typesIn(cat)" :key="t" class="pal-it" :class="{ on: cs.tool === t }" :title="cs.cat.types[t].help || cs.cat.types[t].label"
                  @click="cs.tool = cs.tool === t ? '' : t"><i :class="['cpi', 'cpi-' + t]" />{{ cs.cat.types[t].label }}</button>
              </div>
            </div>
          </template>
        </div>
        <div class="ce-views">
          <div class="ce-top"><TopView :cell="cell" :live="live" :editable="editable" @change="onChange" /></div>
          <div v-if="isWide" class="ce-3d"><CellPreview :cell="cell" :live="live" :selected="cs.comp" /></div>
        </div>
      </div>

      <el-tabs v-model="tab" class="ce-tabs" stretch>
        <el-tab-pane :label="$t('common.components')" name="comps">
          <div class="ce-list">
            <div v-for="c in cell.components || []" :key="c.id" class="ce-it" :class="{ on: c.id === cs.comp }" @click="cs.comp = c.id">
              <b class="mono">{{ c.id }}</b><span>{{ labelOf(c) }}</span><span class="grow" />
              <span v-if="liveHot(c)" class="hot">●</span>
              <span class="muted small">{{ ioOf(cell, c.id).map((e: any) => e.addr).join(' ') }}</span>
            </div>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="$t('cellEditor.iOTable0', [(cell.io || []).length])" name="io">
          <div class="ce-iobar">
            <el-button size="small" :disabled="!editable" @click="regenIo(true)">{{ $t('cellEditor.addMissingIO') }}</el-button>
            <el-button size="small" :disabled="!editable" @click="regenIo(false)">{{ $t('cellEditor.reassignAddresses') }}</el-button>
            <span class="grow" /><span class="muted small">{{ $t('cellEditor.inputsISensorsButtonsOutputs') }}</span>
          </div>
          <div class="ce-io">
            <table>
              <thead><tr><th>{{ $t('common.name') }}</th><th>{{ $t('common.address') }}</th><th>{{ $t('common.direction') }}</th><th :title="$t('cellEditor.contactTypeForDigitalInputs')">{{ $t('common.contact') }}</th><th :title="$t('cellEditor.valueWhenReleasedNothingDetected')">{{ $t('cellEditor.defaultState') }}</th><th>{{ $t('cellEditor.componentSignal') }}</th><th :title="$t('cellEditor.plcAndChannelConnectedBy')">{{ $t('cellEditor.plcChannel') }}</th><th>{{ $t('common.value') }}</th><th v-if="rt" /></tr></thead>
              <tbody>
                <tr v-for="(e, i) in cell.io || []" :key="e.comp + '.' + e.signal" :class="{ sel: e.comp === cs.comp, forced: ioLive[e.name]?.forced }" @click="cs.comp = e.comp">
                  <td><input class="mono" :value="e.name" :disabled="!editable" @change="(ev: any) => setIo(+i, 'name', ev.target.value)" /></td>
                  <td><input class="mono addr" :value="e.addr" :disabled="!editable" @change="(ev: any) => setIo(+i, 'addr', ev.target.value)" /></td>
                  <td><span :class="e.dir === 'in' ? 'din' : 'dout'">{{ e.dir === 'in' ? $t('common.input') : $t('common.output') }}</span> <small class="muted">{{ e.type }}</small></td>
                  <td><span v-if="e.contact" :class="e.contact === 'NC' ? 'ncb' : 'muted'">{{ e.contact === 'NC' ? $t('common.nc') : $t('common.no3') }}</span><span v-else class="muted">—</span></td>
                  <td class="mono" :class="{ ncb: e.contact === 'NC' }">{{ e.dir === 'in' ? (e.type === 'BOOL' ? (e.idle ? 1 : 0) : (e.idle ?? 0)) : '' }}</td>
                  <td class="mono small">{{ e.comp }}.{{ e.signal }}</td>
                  <td class="small nowrap">
                    <a v-for="w in wiredOf(e.name)" :key="w.plc + w.ch" class="plc-ch" :title="$t('cellEditor.n0Channel1ClickTo', [w.plc_name, w.ch])" @click.stop="goTo(w.plc)">{{ w.plc_name }} · {{ w.ch }}</a>
                    <span v-if="!wiredOf(e.name).length" class="warn">{{ $t('cellEditor.notConnected') }}</span>
                  </td>
                  <td class="mono"><span :class="valCls(ioLive[e.name]?.value)">{{ fmtv(ioLive[e.name]?.value) }}</span></td>
                  <td v-if="rt" class="frc">
                    <template v-if="e.type === 'BOOL'"><button :title="$t('cellEditor.forceTo1')" @click.stop="doForce(e.name, true)">1</button><button :title="$t('cellEditor.forceTo0')" @click.stop="doForce(e.name, false)">0</button></template>
                    <button v-if="ioLive[e.name]?.forced" :title="$t('cellEditor.removeForce')" @click.stop="doForce(e.name, null)">×</button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </el-tab-pane>
        <el-tab-pane :label="$t('cellEditor.wiringDiagram')" name="wire">
          <IoWiring :cell="cell" :values="ioVals" :plc-state="rt?.cell?.plc" :plc-name="cellPlcs.map(blockName).join($t('common.k360'))" :wiring="wiringMap" />
        </el-tab-pane>
        <el-tab-pane :label="$t('common.run')" name="run">
          <div v-if="!rt" class="muted pad">{{ $t('cellEditor.onceTheFactoryIsRunning', [canFault() ? $t('cellEditor.injectFaults') : '']) }}</div>
          <template v-else>
            <div class="ce-sec">{{ $t('common.operatorPanel') }}</div>
            <OperatorPanel :pid="pid" :cell="cell" :live="live" />
            <div class="ce-sec">{{ $t('cellEditor.statistics') }} <span class="muted small">{{ $t('cellEditor.cellTime0', [fmtT(stats?.t)]) }}</span><span class="grow" />
              <el-button size="small" text type="primary" :loading="resetting" @click="resetCell">{{ $t('cellEditor.resetEquipment') }}</el-button></div>
            <div class="ce-kv">
              <template v-for="m in stats?.metrics || []" :key="m.key"><span>{{ m.label }}</span><b :class="{ bad: isBad(m) }">{{ fmtMetric(m) }}</b></template>
              <span>{{ $t('common.wip') }}</span><b>{{ stats?.wip ?? '—' }}</b>
            </div>
            <template v-if="canFault()">
            <div class="ce-sec">{{ $t('cellEditor.faultInjection') }}</div>
            <div class="ce-fault">
              <el-select v-model="fComp" size="small" :placeholder="$t('common.components')" filterable style="width: 46%">
                <el-option v-for="c in faultComps" :key="c.id" :value="c.id" :label="`${c.id} ${labelOf(c)}`" /></el-select>
              <el-select v-model="fKind" size="small" :placeholder="$t('common.fault')" style="width: 40%">
                <el-option v-for="k in faultKinds" :key="k" :value="k" :label="cs.cat.faults[k]" /></el-select>
              <el-button size="small" type="danger" plain :disabled="!fComp || !fKind" @click="inject">{{ $t('common.inject') }}</el-button>
            </div>
            <div v-for="f in activeFaults" :key="f.comp + f.kind" class="small fault-it">⚡ {{ f.comp }} {{ f.label }}</div>
            <el-button v-if="activeFaults.length" size="small" text type="primary" @click="clearFaults">{{ $t('cellEditor.clearAllFaults') }}</el-button>
            </template>
            <div class="ce-sec">{{ $t('cellEditor.event') }}</div>
            <div class="ce-ev"><div v-for="(e, i) in events" :key="i" class="small" :class="e.kind"><span class="mono muted">{{ fmtT(e.t) }}</span> {{ e.msg }}</div></div>
          </template>
        </el-tab-pane>
        <el-tab-pane name="check">
          <template #label>{{ $t('common.check') }}<span v-if="errCount" class="badge">{{ errCount }}</span></template>
          <div class="ce-list">
            <div v-for="(x, i) in cs.issues" :key="i" class="small" :class="x.level === 'error' ? 'bad' : 'warn'">{{ x.level === 'error' ? '✖' : '⚠' }} {{ x.msg }}</div>
            <div v-if="!cs.issues.length" class="muted small pad">{{ $t('cellEditor.noIssuesFound') }}</div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import './cell.css';
import { computed, getCurrentInstance, markRaw, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { del, get, P, post, toast } from '../../api';
import { blocksById, ed, exec, mode, openFloat, rtById, STATE_CN, STATE_COLOR } from '../../editor/store';
import { panelById } from '../../editor/shell/panels';
import { goTo } from '../../editor/shell/relations';
import DeviceIo from './DeviceIo.vue';
import { newCell, sceneList } from './api';
import CellPreview from './CellPreview.vue';
import IoWiring from './IoWiring.vue';
import OperatorPanel from './OperatorPanel.vue';
import { applyLive, canEditCell, canFault, cellBlocks, chOf, clone, commit, cs, curCell, curLive, followSelection, force, ioOf, labelOf, loadCat, pollIo, signalSyncOps, validate } from './state';
import TopView from './TopView.vue';

const props = defineProps<{ pid: string; wide?: boolean }>();
const tab = ref('comps'), palOpen = ref(false), scenes = ref<any[]>([]);
const root = ref<HTMLElement>(), width = ref(0);
const isWide = computed(() => !!props.wide || width.value >= 900);
const fComp = ref(''), fKind = ref('');
const events = ref<any[]>([]), activeFaults = ref<any[]>([]), stats = ref<any>(null);
const editable = computed(() => canEditCell() && ['paused', 'edit', 'running'].includes(mode.value) && mode.value !== 'replay');
const resetting = ref(false);
const statusText = computed(() => [rt.value ? (STATE_CN[rt.value.state] || rt.value.state) : $t('cellConsole.notRunning'), rt.value?.alarm].filter(Boolean).join(' · '));
const ioVals = computed<Record<string, any>>(() => ({ ...(cs.io?.inputs || {}), ...(cs.io?.outputs || {}) }));
const PCT = new Set(['sort_accuracy']);
const LOWER = new Set(['collisions', 'jams', 'dropped', 'hard_drops', 'part_contacts', 'interlock_violations', 'hard_reversals', 'sorted_wrong', 'racks.RK1.double']);
const isBad = (m: any) => LOWER.has(m.key) && !!m.value;
const fmtMetric = (m: any) => (m.value === null || m.value === undefined ? '—' : PCT.has(m.key) ? (m.value * 100).toFixed(1) + '%' : typeof m.value === 'boolean' ? (m.value ? $t('common.yes') : $t('common.no')) : m.value);
async function resetCell() {
  resetting.value = true;
  try { await post(P(props.pid) + `/cells/${cs.bid}/reset`, {}); toast($t('cellConsole.equipmentResetToItsInitial')); refreshRun(); }
  finally { resetting.value = false; }
}
const cell = curCell, live = curLive;
// 4.3: The PLC is a standalone device; follow model signal wires to find the PLC controlling this cell and each I/O channel
const sigLinks = computed(() => (ed.model?.links || []).filter((l: any) => l.kind === 'signal' && cs.bid && (l.from === cs.bid || l.to === cs.bid)));
const cellPlcs = computed(() => [...new Set(sigLinks.value.map((l: any) => (l.from === cs.bid ? l.to : l.from)))] as string[]);
const blockName = (id: string) => blocksById.value[id]?.name || id;
const wiringMap = computed<Record<string, any[]>>(() => {
  const m: Record<string, any[]> = {};
  for (const l of sigLinks.value) {
    const plc = l.from === cs.bid ? l.to : l.from;
    for (const s of l.signals || []) (m[s.point] ||= []).push({ plc, plc_name: blockName(plc), ch: s.ch || chOf(s.point), link: l.id });
  }
  return m;
});
const wiredOf = (name: string) => wiringMap.value[name] || [];
function openProgram(id: string) {
  const p = panelById('plc-editor-float');
  if (p) openFloat(p as any, { bid: id }, id); else window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor' } }));
}
const rt = computed(() => (cs.bid ? rtById.value[cs.bid] : null));
const stColor = computed(() => STATE_COLOR[rt.value?.state] || '#888');
const panelComps = computed(() => (cell.value?.components || []).filter((c: any) => ['button', 'estop', 'switch', 'potentiometer', 'lamp', 'display'].includes(c.type)));
const faultComps = computed(() => (cell.value?.components || []).filter((c: any) => (cs.cat?.fault_kinds?.[c.type] || []).length));
const faultKinds = computed(() => cs.cat?.fault_kinds?.[(cell.value?.components || []).find((c: any) => c.id === fComp.value)?.type] || []);
const errCount = computed(() => cs.issues.filter((x: any) => x.level === 'error').length);
const ioLive = computed<Record<string, any>>(() => Object.fromEntries((cs.io?.io || []).map((r: any) => [r.name, r])));
const typesIn = (cat: string) => Object.keys(cs.cat?.types || {}).filter((t) => cs.cat.types[t].cat === cat);
const fmtv = (v: any) => (v === undefined || v === null ? '—' : typeof v === 'boolean' ? (v ? '1' : '0') : String(v));
const valCls = (v: any) => (v === true ? 'v1' : v === false ? 'v0' : '');
const pctv = (v: any) => (typeof v === 'number' ? (v * 100).toFixed(1) + '%' : '—');
const fmtT = (t: any) => (typeof t === 'number' ? `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}` : '—');
function liveHot(c: any) { const v = live.value?.comps?.[c.id]; return !!(v && (v.d || v.on || (typeof v.v === 'number' && Math.abs(v.v) > 1e-4 && c.type.includes('conveyor')))); }

function onChange(c: any, label: string, regen = true) { commit(c, label, regen); }
function setIo(i: number, k: string, v: string) {
  const c = clone(cell.value); const e = c.io[i]; if (!e) return;
  v = v.trim(); if (k === 'name' && !/^[A-Za-z_][A-Za-z0-9_]*$/.test(v)) { toast($t('cellEditor.namesCanContainOnlyLetters')); return; }
  e[k] = v; commit(c, `I/O ${e.comp}.${e.signal} ${k === 'name' ? $t('common.rename') : $t('cellEditor.changeAddress')}`, false);
}
async function regenIo(keep: boolean) {
  const c = clone(cell.value);
  const r = await post('/api/cells/auto_io', { cell: c, keep });
  c.io = r.io; commit(c, keep ? $t('cellEditor.addMissingIO') : $t('cellEditor.reassignIOAddresses'), false);
}
async function apply() { await applyLive(props.pid); toast($t('cellEditor.appliedToTheRunningCell')); }
async function doForce(name: string, v: any) { await force(props.pid, name, v); pollIo(props.pid); }
async function inject() { await post(P(props.pid) + `/cells/${cs.bid}/faults`, { comp: fComp.value, kind: fKind.value }); refreshRun(); }
async function clearFaults() { await del(P(props.pid) + `/cells/${cs.bid}/faults`); refreshRun(); }
async function refreshRun() {
  if (!cs.bid || !rt.value) return;
  try {
    const [f, s, e] = await Promise.all([get(P(props.pid) + `/cells/${cs.bid}/faults`, true), get(P(props.pid) + `/cells/${cs.bid}/stats`, true),
      get(P(props.pid) + `/cells/${cs.bid}/events?limit=30`, true)]);
    activeFaults.value = f.active; stats.value = s; events.value = e.slice().reverse();
  } catch { /* Factory rebuild in progress */ }
}
async function addCell(scene?: string) {
  try { await newCell({ scene, open: false }); if (!palOpen.value && !scene) palOpen.value = true; } catch (e: any) { toast(e.message || String(e)); }
}
async function loadScene(sid: string) {
  const s = await get('/api/scenes/' + sid);
  const c = clone(s.cell); delete c.plc;                // The PLC is a standalone device: exclude the scenario's reference solution and wire according to the new I/O table
  exec([{ op: 'update_block', id: cs.bid, set: { 'params.cell': c, size: c.size } }, ...signalSyncOps(cs.bid, cell.value, c)], $t('cellEditor.loadScenario0', [s.name]));
  validate(c); toast($t('cellEditor.scenario0LoadedReferenceAnswers', [s.name]));
}
const self = getCurrentInstance()!.type;          // Use the same component for the large window (wide layout)
function openWide() {
  openFloat({ id: 'cell-editor-float', title: $t('cellEditor.controlCellEditor'), icon: 'Cpu', component: markRaw(self), size: [1180, 760] }, { wide: true });
}

let timer: any = null;
let ro: ResizeObserver | null = null;
onMounted(async () => {
  if (root.value) { ro = new ResizeObserver(() => { width.value = root.value?.clientWidth || 0; }); ro.observe(root.value); }
  await loadCat(); followSelection();
  if (canEditCell()) scenes.value = await sceneList();
  timer = setInterval(() => { if (tab.value === 'io' || tab.value === 'wire') pollIo(props.pid); if (tab.value === 'run') refreshRun(); }, 1000);
});
onBeforeUnmount(() => { clearInterval(timer); ro?.disconnect(); });
watch(() => (ed.sel || []).join(','), () => followSelection());
watch(() => ed.interior, (v) => { if (v) followSelection(); });
watch(() => cellBlocks.value.length, () => followSelection());
watch(() => [cs.bid, cell.value], () => { if (cell.value) validate(cell.value); }, { immediate: true });
watch(tab, (t) => { if (t === 'io' || t === 'wire') pollIo(props.pid); if (t === 'run') refreshRun(); });
watch(() => cs.comp, (id) => { if (id && faultComps.value.some((c: any) => c.id === id)) fComp.value = id; });
</script>
