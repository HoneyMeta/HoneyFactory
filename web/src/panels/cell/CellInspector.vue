<template>
  <div class="ci">
    <div v-if="!cell" class="ci-empty">
      <template v-if="cellBlocks.length">
        <b>{{ $t('cellInspector.selectAControlCell') }}</b>
        <p class="muted small">{{ $t('cellInspector.clickAControlCellBlock') }}</p>
        <div v-for="b in cellBlocks" :key="b.id" class="ci-pick" @click="pick(b.id)"><i class="cpi cpi-cell" /><b class="mono">{{ b.id }}</b><span>{{ b.name }}</span></div>
      </template>
      <template v-else>
        <b>{{ $t('cellEditor.thisFactoryHasNoControl') }}</b>
        <p class="muted small">{{ $t('cellInspector.conveyorsSensorsAndActuatorsIn') }}</p>
        <div class="ci-btns">
          <el-button size="small" type="primary" :disabled="!canEditCell()" @click="create()"><el-icon><Plus /></el-icon>{{ $t('cellInspector.newControlCell') }}</el-button>
          <el-button size="small" :disabled="!canEditCell()" @click="create('s04_sort_color')">{{ $t('cellInspector.createFromTheSortBy') }}</el-button>
        </div>
      </template>
    </div>
    <!-- Components -->
    <template v-else-if="c">
      <div class="ci-head">
        <i :class="['cpi', 'cpi-' + c.type]" />
        <div class="grow"><b class="mono">{{ c.id }}</b> <b>{{ labelOf(c) }}</b><small v-if="labelOf(c) !== t.label" class="muted"> {{ t.label }}</small></div>
        <el-button size="small" text type="danger" :disabled="!editable" @click="remove"><el-icon><Delete /></el-icon></el-button>
      </div>
      <p v-if="t.help" class="muted small ci-help">{{ t.help }}</p>
      <div class="ci-sec">{{ $t('cellInspector.basic') }}</div>
      <div class="f"><label>{{ $t('common.no2') }}</label><el-input :model-value="c.id" size="small" class="mono" :disabled="!editable" @change="rename" /></div>
      <div class="f"><label>{{ $t('common.name') }}</label><el-input :model-value="c.label || ''" size="small" :placeholder="$t('cellInspector.optional')" :disabled="!editable" @change="(v: string) => set('label', v || undefined)" /></div>
      <div class="ci-sec">{{ $t('trace.position') }}</div>
      <div class="grid3">
        <div class="f"><label>X</label><el-input-number :model-value="c.pos[0]" size="small" :step="0.05" :controls="false" :disabled="!editable" @change="(v: any) => setPos(0, v)" /></div>
        <div class="f"><label>Y</label><el-input-number :model-value="c.pos[1]" size="small" :step="0.05" :controls="false" :disabled="!editable" @change="(v: any) => setPos(1, v)" /></div>
        <div class="f"><label>{{ $t('layoutProps.height') }}</label><el-input-number :model-value="c.pos[2] ?? 0" size="small" :step="0.05" :controls="false" :disabled="!editable" @change="(v: any) => setPos(2, v)" /></div>
        <div class="f"><label>{{ $t('cellInspector.rotation') }}</label><el-input-number :model-value="c.rot || 0" size="small" :step="90" :controls="false" :disabled="!editable" @change="(v: any) => set('rot', v)" /></div>
        <template v-if="hasSize">
          <div class="f"><label>{{ $t('common.length') }}</label><el-input-number :model-value="(c.size || t.size)[0]" size="small" :min="0.05" :step="0.1" :controls="false" :disabled="!editable" @change="(v: any) => setSize(0, v)" /></div>
          <div class="f"><label>{{ $t('common.width') }}</label><el-input-number :model-value="(c.size || t.size)[1]" size="small" :min="0.05" :step="0.1" :controls="false" :disabled="!editable" @change="(v: any) => setSize(1, v)" /></div>
        </template>
      </div>
      <div class="ci-sec">{{ $t('common.parameters') }}</div>
      <div v-for="(d, k) in t.params" :key="k" class="f" :class="{ wide: d.t === 'json' }">
        <label :title="d.help || String(k)">{{ d.label }}<el-tooltip v-if="d.help" :content="d.help" placement="left"><el-icon class="hq"><QuestionFilled /></el-icon></el-tooltip></label>
        <el-select v-if="REFS[String(k)]" :model-value="c.params?.[String(k)] || ''" size="small" clearable :disabled="!editable" :placeholder="$t('common.none')" @change="(v: any) => setParam(String(k), v || '')">
          <el-option v-for="o in refOpts(REFS[String(k)])" :key="o.id" :value="o.id" :label="`${o.id} ${labelOf(o)}`" /></el-select>
        <ParamInput v-else :d="d" :value="c.params?.[String(k)] ?? d.default" @set="(v: any) => setParam(String(k), v)" />
      </div>
      <div class="ci-sec">{{ $t('cellInspector.signalsIO') }}</div>
      <div v-for="e in ios" :key="e.name" class="ci-io" :class="{ forced: ioLive[e.name]?.forced }">
        <span :class="e.dir === 'in' ? 'din' : 'dout'">{{ e.dir === 'in' ? 'I' : 'Q' }}</span>
        <b class="mono">{{ e.name }}</b><span class="mono muted">{{ e.addr }}</span><span class="grow small muted">{{ e.signal }}</span>
        <span class="mono" :class="valCls(val(e))">{{ fmtv(val(e)) }}</span>
        <template v-if="rt && e.type === 'BOOL'"><button @click="doForce(e.name, true)">1</button><button @click="doForce(e.name, false)">0</button></template>
        <button v-if="ioLive[e.name]?.forced" @click="doForce(e.name, null)">×</button>
      </div>
      <div v-if="!ios.length" class="muted small">{{ $t('cellInspector.thisComponentHasNoI') }}</div>
      <div v-if="lv" class="ci-sec">{{ $t('cellInspector.liveStatus') }}</div>
      <div v-if="lv" class="mono small ci-live">{{ JSON.stringify(lv) }}</div>
    </template>
    <!-- Cell itself -->
    <template v-else>
      <div class="ci-head"><i class="cpi cpi-cell" /><div class="grow"><b>{{ blk?.name }}</b><small class="muted"> {{ $t('cellInspector.controlCell0', [cs.bid]) }}</small></div></div>
      <div class="ci-sec">{{ $t('cellInspector.cell') }}</div>
      <div class="grid3">
        <div class="f"><label>{{ $t('common.length') }}</label><el-input-number :model-value="cell.size?.[0] ?? 8" size="small" :min="1" :step="0.5" :controls="false" :disabled="!editable" @change="(v: any) => setCellSize(0, v)" /></div>
        <div class="f"><label>{{ $t('common.width') }}</label><el-input-number :model-value="cell.size?.[1] ?? 4" size="small" :min="1" :step="0.5" :controls="false" :disabled="!editable" @change="(v: any) => setCellSize(1, v)" /></div>
      </div>
      <div class="ci-sec">PLC</div>
      <template v-if="!('plc' in cell)">
        <div v-if="plcs.length" class="ci-plcs small">
          <span class="muted">{{ $t('cellInspector.controlledByPlc') }}</span>
          <span v-for="p in plcs" :key="p"><a @click="goTo(p)">{{ blocksById[p]?.name || p }}</a> <a class="muted" @click="openProgram(p)">{{ $t('cellInspector.openProgram') }}</a></span>
        </div>
        <p v-else class="muted small">{{ $t('cellInspector.noPlcConnectedClickAdd') }}</p>
      </template>
      <template v-else>
      <div class="f"><label>{{ $t('cellInspector.controlMode') }}</label>
        <el-select :model-value="cell.plc?.mode || 'internal'" size="small" :disabled="!editable" @change="(v: any) => setPlc('mode', v)">
          <el-option value="internal" :label="$t('cellInspector.builtInSoftPlc')" /><el-option value="external" :label="$t('cellInspector.externalPlcModbusOpcUa')" /></el-select></div>
      <div class="f"><label>{{ $t('cellInspector.scanCycle') }}</label><el-input-number :model-value="cell.plc?.scan_ms || 20" size="small" :min="5" :max="200" :controls="false" :disabled="!editable"
        @change="(v: any) => setPlc('scan_ms', v)" /><span class="unit">ms</span></div>
      </template>
      <div class="kv small">
        <span>{{ $t('common.components') }}</span><b>{{ (cell.components || []).length }}</b><span>{{ $t('common.input') }}</span><b>{{ (cell.io || []).filter((e: any) => e.dir === 'in').length }}</b>
        <span>{{ $t('common.output') }}</span><b>{{ (cell.io || []).filter((e: any) => e.dir === 'out').length }}</b><span>{{ $t('cellInspector.plcStatus') }}</span><b>{{ live?.plc || '—' }}</b>
      </div>
      <p class="muted small">{{ $t('cellInspector.arrangeComponentsAndEditThe') }}</p>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import './cell.css';
import { computed, onBeforeUnmount, onMounted, watch } from 'vue';
import { canEdit, toast } from '../../api';
import { newCell } from './api';
import ParamInput from '../../editor/ParamInput.vue';
import { blocksById, ed, mode, openFloat, rtById, select } from '../../editor/store';
import { panelById } from '../../editor/shell/panels';
import { goTo } from '../../editor/shell/relations';
import { canEditCell, cellBlocks, clone, commit, cs, curCell, curComp, curLive, followSelection, force, ioOf, labelOf, loadCat, pollIo, typeOf } from './state';

const props = defineProps<{ pid: string }>();
const REFS: Record<string, string[]> = { motor: ['motor'], conveyor: ['belt_conveyor', 'roller_conveyor', 'curved_conveyor'], rack: ['rack'] };
const cell = curCell, c = curComp, live = curLive;
const blk = computed(() => blocksById.value[cs.bid]);
const rt = computed(() => (cs.bid ? rtById.value[cs.bid] : null));
// 4.3: PLC controlling this cell (based on model signal wires)
const plcs = computed(() => [...new Set((ed.model?.links || []).filter((l: any) => l.kind === 'signal' && cs.bid && (l.from === cs.bid || l.to === cs.bid))
  .map((l: any) => (l.from === cs.bid ? l.to : l.from)))] as string[]);
function openProgram(id: string) {
  const p = panelById('plc-editor-float');
  if (p) openFloat(p as any, { bid: id }, id); else window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor' } }));
}
const t = computed(() => typeOf(c.value?.type));
const editable = computed(() => canEditCell() && mode.value !== 'replay');
const hasSize = computed(() => !!t.value.size && !['button', 'switch', 'estop', 'lamp', 'display', 'potentiometer', 'diffuse_sensor', 'retro_sensor', 'capacitive',
  'inductive', 'encoder', 'emitter', 'cell_entry'].includes(c.value?.type));
const ios = computed(() => ioOf(cell.value, c.value?.id));
const lv = computed(() => (c.value ? live.value?.comps?.[c.value.id] : null));
const ioLive = computed<Record<string, any>>(() => Object.fromEntries((cs.io?.io || []).map((r: any) => [r.name, r])));
const val = (e: any) => ioLive.value[e.name]?.value;
const fmtv = (v: any) => (v === undefined || v === null ? '—' : typeof v === 'boolean' ? (v ? '1' : '0') : String(v));
const valCls = (v: any) => (v === true ? 'v1' : v === false ? 'v0' : '');
const refOpts = (types: string[]) => (cell.value?.components || []).filter((o: any) => types.includes(o.type));

function edit(fn: (cc: any, comp: any) => void, label: string, regen = false) {
  const cc = clone(cell.value); const comp = cc.components.find((k: any) => k.id === cs.comp); if (!comp) return;
  fn(cc, comp); commit(cc, label, regen);
}
const set = (k: string, v: any) => edit((_, o) => { if (v === undefined) delete o[k]; else o[k] = v; }, $t('cellInspector.edit01', [cs.comp, k]));
const setPos = (i: number, v: number) => edit((_, o) => { o.pos = [...o.pos]; o.pos[i] = +v || 0; while (o.pos.length < 3) o.pos.push(0); }, $t('cellInspector.move0', [cs.comp]));
const setSize = (i: number, v: number) => edit((_, o) => { o.size = [...(o.size || t.value.size)]; o.size[i] = +v; }, $t('cellInspector.resize0', [cs.comp]));
// Parameters may change signals (reversible, dual-solenoid, trigger mode, servo…) → refresh I/O
const setParam = (k: string, v: any) => edit((_, o) => { o.params = { ...(o.params || {}) }; o.params[k] = v; }, `${cs.comp} ${t.value.params?.[k]?.label || k}`, true);
function rename(v: string) {
  v = String(v || '').trim(); const old = cs.comp;
  if (!/^[A-Za-z][A-Za-z0-9_]*$/.test(v) || v === old) return;
  if ((cell.value.components || []).some((k: any) => k.id === v)) return;
  const cc = clone(cell.value);
  for (const k of cc.components) {
    if (k.id === old) k.id = v;
    for (const pk of ['motor', 'conveyor', 'rack']) if (k.params?.[pk] === old) k.params[pk] = v;
  }
  for (const e of cc.io || []) if (e.comp === old) { e.comp = v; if (e.name === old || e.name.startsWith(old + '_')) e.name = v + e.name.slice(old.length); }
  cs.comp = v; commit(cc, $t('cellInspector.renameComponent01', [old, v]), false);
}
function remove() { const cc = clone(cell.value); cc.components = cc.components.filter((k: any) => k.id !== cs.comp); const id = cs.comp; cs.comp = ''; commit(cc, $t('cellInspector.delete0', [id]), true); }
function setCellSize(i: number, v: number) {
  const cc = clone(cell.value); cc.size = [...(cc.size || [8, 4])]; cc.size[i] = +v; commit(cc, $t('cellInspector.resizeCell'), false);
}
function setPlc(k: string, v: any) { const cc = clone(cell.value); cc.plc = { ...(cc.plc || {}), [k]: v }; commit(cc, `PLC ${k}`, false); }
async function doForce(name: string, v: any) { await force(props.pid, name, v); pollIo(props.pid); }

function pick(id: string) { select([id]); cs.bid = id; cs.comp = ''; }
async function create(scene?: string) { try { await newCell({ scene }); } catch (e: any) { toast(e.message || String(e)); } }

let timer: any = null;
onMounted(async () => { await loadCat(); followSelection(); timer = setInterval(() => { if (c.value && rt.value) pollIo(props.pid); }, 1000); });
onBeforeUnmount(() => clearInterval(timer));
watch(() => (ed.sel || []).join(','), () => followSelection());
</script>
