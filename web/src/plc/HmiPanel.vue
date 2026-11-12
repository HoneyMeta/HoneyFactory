<template>
  <div class="plc-root hmi">
    <div class="hb">
      <el-select v-model="sid" size="small" style="width: 170px" :placeholder="$t('hmiPanel.selectScreen')" @change="loadScreen">
        <el-option v-for="h in list" :key="h.id" :value="h.id" :label="h.name + (SRC[srcOf(h)] ? '  · ' + SRC[srcOf(h)] : '')" />
      </el-select>
      <button v-if="!ro" class="plc-btn" :title="$t('hmiPanel.newScreen')" @click="newScreen"><el-icon><Plus /></el-icon>{{ $t('common.new') }}</button>
      <button v-if="!ro" class="plc-btn" :title="$t('hmiPanel.restoreHiddenBuiltInScreens')" @click="restoreHidden"><el-icon><RefreshLeft /></el-icon></button>
      <template v-if="scr">
        <i class="plc-sep" />
        <el-input v-model="scr.name" size="small" style="width: 140px" :disabled="mode === 'run'" />
        <el-select v-model="scr.cell" size="small" style="width: 170px" :placeholder="$t('hmiPanel.linkedPlc')" :disabled="mode === 'run'">
          <el-option v-for="o in options" :key="o.id" :value="o.id" :label="o.label" />
        </el-select>
        <el-radio-group v-if="!ro" v-model="mode" size="small">
          <el-radio-button value="edit">{{ $t('hmiPanel.configure') }}</el-radio-button>
          <el-radio-button value="run">{{ $t('common.run') }}</el-radio-button>
        </el-radio-group>
        <el-tooltip v-if="SRC[srcOf(scr)]" :content="SRC_TIP[srcOf(scr)]" placement="bottom"><span class="plc-chip src">{{ SRC[srcOf(scr)] }}</span></el-tooltip>
        <span class="grow" />
        <el-tooltip v-if="canShip" :content="$t('hmiPanel.storeThisScreenInThe')" placement="bottom">
          <button class="plc-btn" data-act="ship" @click="shipToModel"><el-icon><Upload /></el-icon>{{ $t('hmiPanel.saveToFactoryModel') }}</button>
        </el-tooltip>
        <span v-if="sess" class="plc-chip" :class="sess.s.online?.state">{{ STATE_CN[sess.s.online?.state] || '—' }}<i /></span>
        <span v-if="autoAt && !dirty" class="muted small" :title="$t('hmiPanel.automaticallySavesAfter15')">{{ $t('hmiPanel.autosaved0', [autoAt]) }}</span>
        <button v-if="!ro" class="plc-btn pri" :disabled="!dirty" @click="save()"><el-icon><DocumentChecked /></el-icon>{{ $t('common.save') }}</button>
        <button v-if="!ro" class="plc-btn" :title="$t('hmiPanel.deleteScreen')" @click="remove"><el-icon><Delete /></el-icon></button>
      </template>
    </div>
    <EmptyCells v-if="noCells" banner :running="running" :title="$t('hmiPanel.thisFactoryHasNoPlc')" />
    <div v-if="scr" class="hm">
      <!-- Widget library -->
      <div v-if="mode === 'edit'" class="pal">
        <div class="pt">{{ $t('hmiPanel.controls') }}</div>
        <button v-for="w in WIDGETS" :key="w.type" class="pi" :data-w="w.type" @click="addWidget(w.type)"><el-icon><component :is="w.icon" /></el-icon>{{ w.cn }}</button>
        <div class="tip muted">{{ $t('hmiPanel.clickAControlToAdd') }}</div>
      </div>
      <!-- Screen -->
      <div class="cv-wrap" @pointerdown.self="selId = ''">
        <div class="cv" :class="{ edit: mode === 'edit' }" :style="{ width: scr.size[0] + 'px', height: scr.size[1] + 'px' }" @pointerdown.self="selId = ''">
          <div v-for="w in scr.widgets" :key="w.id" class="w" :class="['w-' + w.type, { sel: selId === w.id && mode === 'edit' }]"
            :style="{ left: w.x + 'px', top: w.y + 'px', width: w.w + 'px', height: w.h + 'px' }" :data-wid="w.id"
            @pointerdown="mode === 'edit' && startMove($event, w)">
            <!-- Button -->
            <button v-if="w.type === 'button'" class="hbtn" :style="{ background: w.color || '#1463d6' }" :class="{ dn: pressed === w.id || (w.mode === 'toggle' && (usePanel(w) ? panelOn[w.id] : isOn(w))) }"
              @pointerdown="mode === 'run' && press(w, true)" @pointerup="mode === 'run' && press(w, false)" @pointerleave="mode === 'run' && pressed === w.id && press(w, false)">
              {{ w.label || $t('common.button') }}</button>
            <!-- Switch -->
            <div v-else-if="w.type === 'switch'" class="hsw" :class="{ on: isOn(w) }" @click="mode === 'run' && toggle(w)">
              <span class="knob" /><b>{{ w.label || $t('hmiPanel.switch') }}</b><small>{{ isOn(w) ? 'ON' : 'OFF' }}</small>
            </div>
            <!-- Indicator lamp -->
            <div v-else-if="w.type === 'lamp'" class="hlamp">
              <span class="bulb" :style="isOn(w) ? { background: w.color || '#22c55e', boxShadow: `0 0 16px ${w.color || '#22c55e'}` } : {}" />
              <b>{{ w.label || $t('ioWiring.indicatorLamp') }}</b>
            </div>
            <!-- Numeric display -->
            <div v-else-if="w.type === 'number'" class="hnum">
              <small>{{ w.label || w.var }}</small><b class="mono">{{ numText(w) }}</b><i>{{ w.unit }}</i>
            </div>
            <!-- Numeric input -->
            <div v-else-if="w.type === 'input'" class="hnum">
              <small>{{ w.label || w.var }}</small>
              <input class="mono" :placeholder="numText(w)" :disabled="mode !== 'run'" @keydown.enter="writeNum(w, ($event.target as any).value); ($event.target as any).value = ''" />
            </div>
            <!-- Bar graph -->
            <div v-else-if="w.type === 'bar'" class="hbar">
              <small>{{ w.label || w.var }}</small>
              <div class="bt"><div class="bf" :style="{ height: barPct(w) + '%', background: w.color || '#1463d6' }" /></div>
              <b class="mono">{{ numText(w) }}</b>
            </div>
            <!-- Trend -->
            <div v-else-if="w.type === 'trend'" class="htr">
              <div class="trh"><small>{{ w.label || $t('livePanel.trends') }}</small><span v-for="(v, i) in trendVars(w)" :key="v" class="lg" :style="{ color: COLORS[i % COLORS.length] }">● {{ v }}</span></div>
              <svg :viewBox="`0 0 ${Math.max(10, w.w)} ${Math.max(10, w.h - 22)}`" preserveAspectRatio="none" class="trs">
                <polyline v-for="(v, i) in trendVars(w)" :key="v" :points="trendPts(w, v)" fill="none" :stroke="COLORS[i % COLORS.length]" stroke-width="1.6" />
              </svg>
            </div>
            <!-- Text / background frame -->
            <div v-else-if="w.type === 'text'" class="htext" :style="{ fontSize: (w.size || 16) + 'px', color: w.color }">{{ w.label || $t('hmiPanel.text') }}</div>
            <div v-else-if="w.type === 'rect'" class="hrect" :style="{ borderColor: w.color || 'var(--ld-ln)' }"><small>{{ w.label }}</small></div>
            <i v-if="mode === 'edit' && selId === w.id" class="rs" @pointerdown.stop="startResize($event, w)" />
            <span v-if="mode === 'edit' && w.var && w.type !== 'text'" class="vtag mono">{{ w.var }}</span>
          </div>
          <div v-if="!scr.widgets.length" class="empty muted">{{ mode === 'edit' ? $t('hmiPanel.selectAControlOnThe') : $t('hmiPanel.theScreenIsEmptySwitch') }}</div>
        </div>
      </div>
      <!-- Properties -->
      <div v-if="mode === 'edit'" class="props">
        <template v-if="sel">
          <div class="pt">{{ $t('hmiPanel.n0Properties', [WIDGETS.find((x) => x.type === sel.type)?.cn]) }}</div>
          <label>{{ $t('hmiPanel.text2') }}</label><el-input v-model="sel.label" size="small" />
          <template v-if="sel.type !== 'text' && sel.type !== 'rect' && sel.type !== 'trend'">
            <label>{{ $t('hmiPanel.boundVariable') }}</label>
            <el-select v-model="sel.var" size="small" filterable allow-create :placeholder="$t('hmiPanel.selectAVariable')" data-prop="var">
              <el-option-group v-for="g in groups(sel.type)" :key="g.label" :label="g.label">
                <el-option v-for="s in g.items" :key="s.name" :value="s.name" :label="s.name">
                  <span class="mono">{{ s.name }}</span><span class="opt-i">{{ s.addr || s.type }} {{ s.info }}</span>
                </el-option>
              </el-option-group>
            </el-select>
          </template>
          <template v-if="sel.type === 'trend'">
            <label>{{ $t('hmiPanel.trendVariablesMax4') }}</label>
            <el-select v-model="sel.vars" size="small" multiple filterable :multiple-limit="4">
              <el-option v-for="s in symbols('number')" :key="s.name" :value="s.name" :label="s.name" />
            </el-select>
          </template>
          <template v-if="(sel.type === 'button' || sel.type === 'switch') && scr.cell !== '_sandbox'">
            <el-checkbox v-model="sel.panel" size="small">{{ $t('hmiPanel.pressPhysicalButtonsOnThe') }}</el-checkbox>
            <div class="tip muted">{{ $t('hmiPanel.checkedOperatesTheUnitPanel') }}</div>
          </template>
          <template v-if="sel.type === 'button'">
            <label>{{ $t('scenarios.action') }}</label>
            <el-select v-model="sel.mode" size="small" data-prop="mode">
              <el-option value="momentary" :label="$t('hmiPanel.momentaryActiveWhileHeldResets')" />
              <el-option value="toggle" :label="$t('hmiPanel.maintainedTogglesWithEachPress')" />
            </el-select>
            <template v-if="!sel.panel">
              <label>{{ $t('common.contact') }}</label>
              <el-select v-model="sel.nc" size="small" data-prop="nc">
                <el-option :value="false" :label="$t('hmiPanel.noPressed1EG')" />
                <el-option :value="true" :label="$t('hmiPanel.ncPressed0EG')" />
              </el-select>
            </template>
          </template>
          <template v-if="sel.type === 'bar' || sel.type === 'trend'">
            <label>{{ $t('common.scope') }}</label>
            <div class="row"><el-input-number v-model="sel.min" size="small" controls-position="right" /><el-input-number v-model="sel.max" size="small" controls-position="right" /></div>
          </template>
          <template v-if="sel.type === 'number' || sel.type === 'bar' || sel.type === 'input'"><label>{{ $t('common.unit') }}</label><el-input v-model="sel.unit" size="small" /></template>
          <template v-if="sel.type === 'text'"><label>{{ $t('hmiPanel.fontSize') }}</label><el-input-number v-model="sel.size" size="small" :min="10" :max="48" /></template>
          <template v-if="['button', 'lamp', 'bar', 'text', 'rect'].includes(sel.type)"><label>{{ $t('common.color') }}</label><el-color-picker v-model="sel.color" size="small" /></template>
          <label>{{ $t('hmiPanel.positionSize') }}</label>
          <div class="row mono small">{{ sel.x }}, {{ sel.y }} · {{ sel.w }}×{{ sel.h }}</div>
          <button class="plc-btn st" style="margin-top: 10px" @click="delWidget"><el-icon><Delete /></el-icon>{{ $t('hmiPanel.deleteControl') }}</button>
        </template>
        <template v-else>
          <div class="pt">{{ $t('hmiPanel.screen') }}</div>
          <label>{{ $t('hmiPanel.sizePixels') }}</label>
          <div class="row"><el-input-number v-model="scr.size[0]" size="small" :min="320" :max="1920" :step="20" /><el-input-number v-model="scr.size[1]" size="small" :min="240" :max="1080" :step="20" /></div>
          <div class="tip muted">{{ $t('hmiPanel.selectAControlToEdit') }}</div>
        </template>
      </div>
    </div>
    <div v-else class="pad muted">{{ $t('hmiPanel.noScreensYetClickNew') }}</div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import './plc.css';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onBeforeUnmount, reactive, ref, shallowRef, watch } from 'vue';
import { ed, exec } from '../editor/store';
import { useCells } from './cells';
import EmptyCells from './EmptyCells.vue';
import { canEdit, P, post } from '../api';
import { FB_FIELD_TYPE, fmtVal, plcApi, STATE_CN } from './plcApi';
import { Sess, useSession } from './session';

const props = defineProps<{ pid: string; bid?: string; screen?: string }>();
const { options, bid: defBid, noCells, running, hmiScreen, loaded: cellsLoaded } = useCells(() => props.pid, () => props.bid);
const ro = computed(() => !canEdit());
const SRC: Record<string, string> = { model: $t('hmiPanel.includedWithUnit'), seed: $t('hmiPanel.includedWithSoftware'), auto: $t('entityPage.autoGenerated'), demo: $t('hmiPanel.demo') };
const SRC_TIP: Record<string, string> = {
  model: $t('hmiPanel.thisScreenIsStoredIn'),
  seed: $t('hmiPanel.aScreenIncludedWithThe'),
  auto: $t('hmiPanel.aPanelGeneratedFromThe'),
  demo: $t('hmiPanel.aDemoScreenForThe'),
};
const srcOf = (h: any) => String(h?.source || '').split('+').pop() as string;
const WIDGETS = [
  { type: 'button', cn: $t('common.button'), icon: 'Pointer', w: 110, h: 46 }, { type: 'switch', cn: $t('hmiPanel.switch'), icon: 'Switch', w: 130, h: 46 },
  { type: 'lamp', cn: $t('ioWiring.indicatorLamp'), icon: 'Sunny', w: 110, h: 46 }, { type: 'number', cn: $t('hmiPanel.numericDisplay'), icon: 'Odometer', w: 140, h: 58 },
  { type: 'input', cn: $t('hmiPanel.numericInput'), icon: 'EditPen', w: 140, h: 58 }, { type: 'bar', cn: $t('hmiPanel.barGraph'), icon: 'Histogram', w: 70, h: 170 },
  { type: 'trend', cn: $t('hmiPanel.trendChart'), icon: 'TrendCharts', w: 360, h: 180 }, { type: 'text', cn: $t('hmiPanel.text2'), icon: 'Document', w: 160, h: 30 },
  { type: 'rect', cn: $t('hmiPanel.groupBox'), icon: 'Crop', w: 260, h: 160 },
];
const COLORS = ['#1463d6', '#15a34a', '#d99a16', '#dc2b2b'];
const list = ref<any[]>([]);
const sid = ref(props.screen || '');
const scr = ref<any>(null);
const saved = ref('');
const mode = ref<'edit' | 'run'>('run');
const selId = ref('');
const pressed = ref('');
const sel = computed(() => scr.value?.widgets.find((w: any) => w.id === selId.value));
const dirty = computed(() => !!scr.value && JSON.stringify(scr.value) !== saved.value);
const sessRef = shallowRef<Sess | null>(null);
const sess = computed(() => sessRef.value);
let release: (() => void) | null = null;
const hist = reactive<Record<string, number[]>>({});

async function loadList() {
  list.value = (await plcApi.hmiList(props.pid)).items;
  if (!sid.value && list.value.length) {
    // 4.3: bid can be a PLC block, HMI block (its specified screen / bound PLC's screen), or PLC-controlled equipment
    const want = props.bid ? defBid.value : '';
    const scrId = hmiScreen.value;
    sid.value = (list.value.find((h) => scrId && h.id === scrId) || list.value.find((h) => want && h.cell === want) || list.value[0]).id;
    await loadScreen();
  }
  if (!list.value.length) mode.value = 'edit';
}
async function loadScreen() {
  if (!sid.value) return;
  const d = await plcApi.hmiGet(props.pid, sid.value);
  d.widgets ||= []; d.size ||= [960, 560];
  scr.value = d; saved.value = d.new ? '' : JSON.stringify(d); selId.value = '';
}
async function newScreen() {
  const r: any = await ElMessageBox.prompt($t('hmiPanel.screenName'), $t('hmiPanel.newHmiScreen'), { inputValue: $t('hmiPanel.operatorPanel') }).catch(() => null);
  if (!r) return;
  let i = list.value.length + 1;
  while (list.value.some((h) => h.id === 'screen' + i)) i++;
  scr.value = { id: 'screen' + i, name: r.value || $t('hmiPanel.screen'), cell: defBid.value || '_sandbox', size: [960, 560], widgets: [] };
  sid.value = scr.value.id; saved.value = ''; mode.value = 'edit';
  await save(true);
  if (noCells.value) ElMessage.info({ message: $t('hmiPanel.thisFactoryHasNoPlc2'), duration: 6000 });
}
async function save(quiet = false) {
  if (ro.value || !scr.value) return;
  const d = await plcApi.hmiPut(props.pid, scr.value.id, scr.value);
  saved.value = JSON.stringify(scr.value = { ...scr.value, ...d, new: undefined });
  list.value = (await plcApi.hmiList(props.pid)).items;
  autoAt.value = new Date().toLocaleTimeString();
  if (!quiet) ElMessage.success($t('hmiPanel.screenSaved'));
}
// Auto-save configuration after 1.5 s of inactivity to avoid losing changes when the window closes
const autoAt = ref('');
let autoT: any = null;
watch(() => (scr.value ? JSON.stringify(scr.value) : ''), () => {
  clearTimeout(autoT);
  if (!dirty.value || ro.value || !scr.value || scr.value.new) return;
  autoT = setTimeout(() => save(true).catch(() => undefined), 1500);
});
onBeforeUnmount(() => { clearTimeout(autoT); if (dirty.value && !ro.value && scr.value) save(true).catch(() => undefined); });
async function restoreHidden() {
  const r = await plcApi.hmiRestore(props.pid);
  await loadList();
  ElMessage.success(r.restored ? $t('hmiPanel.hiddenScreensRestored0', [r.restored]) : $t('hmiPanel.noHiddenScreens'));
}
async function remove() {
  const src = String(scr.value.source || '');
  const msg = src.startsWith('user+') ? $t('hmiPanel.deleteYourSavedVersionAnd', [SRC[srcOf(scr.value)], scr.value.name])
    : SRC[src] ? $t('hmiPanel.hideTheScreen1From', [SRC[src], scr.value.name]) : $t('hmiPanel.deleteTheScreen0', [scr.value.name]);
  await ElMessageBox.confirm(msg, $t('common.delete'), { type: 'warning' });
  await plcApi.hmiDel(props.pid, scr.value.id);
  scr.value = null; sid.value = '';
  await loadList();
}
const canShip = computed(() => !!scr.value && (ed.model?.blocks || []).some((b: any) => b.id === scr.value.cell && (b.type === 'plc' || b.type === 'cell')));
function shipToModel() {
  const b = (ed.model?.blocks || []).find((x: any) => x.id === scr.value.cell);
  if (!b) return;
  const clean = JSON.parse(JSON.stringify(scr.value));
  for (const k of ['source', 'saved_at', 'new', 'cell']) delete clean[k];
  const key = b.type === 'plc' ? 'params.hmi' : 'params.cell.hmi';     // 4.3: screens are stored on the PLC block
  const list0 = ((b.type === 'plc' ? b.params?.hmi : b.params?.cell?.hmi) || []).filter((h: any) => h.id !== clean.id);
  exec([{ op: 'update_block', id: b.id, set: { [key]: [...list0, clean] } }], $t('hmiPanel.saveHmiScreen0To', [clean.name, b.name || b.id]));
  ElMessage.success($t('hmiPanel.writtenTo0DraftSave', [b.name || b.id]));
}
function addWidget(type: string) {
  const d = WIDGETS.find((x) => x.type === type)!;
  const n = scr.value.widgets.length;
  const w: any = { id: 'w' + Date.now().toString(36), type, x: 24 + (n % 6) * 30, y: 24 + (n % 6) * 30, w: d.w, h: d.h, label: '', var: '' };
  if (type === 'button') w.mode = 'momentary';
  if (type === 'bar' || type === 'trend') { w.min = 0; w.max = 100; }
  if (type === 'trend') w.vars = [];
  scr.value.widgets.push(w);
  selId.value = w.id;
}
function delWidget() { scr.value.widgets = scr.value.widgets.filter((w: any) => w.id !== selId.value); selId.value = ''; }
const snap = (v: number) => Math.round(v / 10) * 10;
function track(e: PointerEvent, fn: (dx: number, dy: number) => void) {
  const x0 = e.clientX, y0 = e.clientY;
  const mv = (ev: PointerEvent) => fn(ev.clientX - x0, ev.clientY - y0);
  const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); };
  addEventListener('pointermove', mv); addEventListener('pointerup', up);
}
function startMove(e: PointerEvent, w: any) {
  if ((e.target as HTMLElement).closest('.rs')) return;
  selId.value = w.id;
  const x = w.x, y = w.y;
  track(e, (dx, dy) => { w.x = Math.max(0, Math.min(scr.value.size[0] - w.w, snap(x + dx))); w.y = Math.max(0, Math.min(scr.value.size[1] - w.h, snap(y + dy))); });
}
function startResize(e: PointerEvent, w: any) {
  const ww = w.w, hh = w.h;
  track(e, (dx, dy) => { w.w = Math.max(40, snap(ww + dx)); w.h = Math.max(24, snap(hh + dy)); });
}

// ---------------- Runtime
const cellId = computed(() => scr.value?.cell || defBid.value);
watch(cellId, async (b) => {
  release?.(); release = null; sessRef.value = null;
  if (!b) return;
  const s = useSession(props.pid, b);
  sessRef.value = s; release = s.use();
  try { await s.load(); } catch { /* Already notified */ }
}, { immediate: true });
onBeforeUnmount(() => release?.());
const on = () => sessRef.value?.s.online;
function val(name: string) {
  const o = on(); if (!o || !name) return undefined;
  if (name.includes('.')) { const [b, f] = name.split('.'); const k = Object.keys(o.vars || {}).find((x) => x.toUpperCase() === b.toUpperCase()); return k ? o.vars[k]?.[f.toUpperCase()] : undefined; }
  const io = (o.io || []).find((r: any) => r.name.toUpperCase() === name.toUpperCase());
  if (io) return io.value;
  const k = Object.keys(o.vars || {}).find((x) => x.toUpperCase() === name.toUpperCase());
  return k ? o.vars[k] : undefined;
}
const isOn = (w: any) => !!val(w.var);
function numText(w: any) {
  const v = val(w.var);
  if (v === undefined) return '—';
  const f = String(w.var || '').split('.')[1]?.toUpperCase();
  return fmtVal(v, f ? FB_FIELD_TYPE[f] : on()?.types?.[w.var]);
}
function barPct(w: any) { const v = Number(val(w.var) || 0); const lo = w.min ?? 0, hi = w.max ?? 100; return Math.max(0, Math.min(100, ((v - lo) / ((hi - lo) || 1)) * 100)); }
function isInput(name: string) { return (sessRef.value?.s.io || []).some((e: any) => e.dir === 'in' && e.name.toUpperCase() === String(name).toUpperCase()); }
function groups(type: string) {
  const io = new Map((sessRef.value?.s.io || []).map((e: any) => [e.name.toUpperCase(), e]));
  const ak = (a?: string) => { const m = /^%[IQM]([XWBD]?)(\d+)(?:\.(\d+))?/i.exec(a || ''); return m ? (m[1] && m[1].toUpperCase() !== 'X' ? 1e6 : 0) + Number(m[2]) * 8 + Number(m[3] || 0) : 1e9; };
  const list = symbols(type).map((x: any) => { const e: any = io.get(x.name.toUpperCase()); return { ...x, dir: e?.dir, addr: e?.addr, info: e?.comment || x.info || '' }; });
  const by = (d: string | undefined) => list.filter((x: any) => x.dir === d).sort((a: any, b: any) => ak(a.addr) - ak(b.addr));
  return [{ label: $t('hmiPanel.inputsIButtonsSensors'), items: by('in') }, { label: $t('hmiPanel.outputsQActuatorsIndicatorLamps'), items: by('out') },
    { label: $t('hmiPanel.programVariables'), items: list.filter((x: any) => !x.dir).sort((a: any, b: any) => a.name.localeCompare(b.name)) }].filter((g) => g.items.length);
}
async function setVar(name: string, v: any, release_ = false) {
  if (ro.value) return;
  const s = sessRef.value; if (!s || !name) { ElMessage.warning($t('hmiPanel.thisControlIsNotBound')); return; }
  try {
    if (isInput(name)) await s.act({ action: 'force', name, value: release_ ? null : v });
    else await s.act({ action: 'write', name, value: v });
  } catch { /* Already notified */ }
}
/** Press a physical button on the unit console (control-layer panel interface: the unit handles NC wiring and E-Stop latching; 3D buttons move too). */
const usePanel = (w: any) => !!w.panel && !!scr.value?.cell && scr.value.cell !== '_sandbox';
const panelOn = reactive<Record<string, boolean>>({});
async function panel(w: any, action: string) {
  // 4.3: the screen is bound to a PLC block; buttons belong to the control unit connected by signal wire (device / point in the I/O table)
  const e: any = (sessRef.value?.s.io || []).find((r: any) => String(r.name).toUpperCase() === String(w.var || '').toUpperCase());
  const dev = e?.device || scr.value.cell, comp = e?.point || w.var;
  try { await post(`${P(props.pid)}/cells/${encodeURIComponent(dev)}/panel`, { comp, action, hold: 0 }); sessRef.value?.poll(); } catch { /* Already notified */ }
}
async function press(w: any, down: boolean) {
  if (ro.value) return;
  if (usePanel(w)) {
    if (w.mode === 'toggle') { if (down) { panelOn[w.id] = !panelOn[w.id]; await panel(w, panelOn[w.id] ? 'press' : 'release'); } return; }
    pressed.value = down ? w.id : '';
    await panel(w, down ? 'press' : 'release');
    return;
  }
  if (w.mode === 'toggle') { if (down) await setVar(w.var, !isOn(w)); return; }
  pressed.value = down ? w.id : '';
  const v = w.nc ? !down : down;                    // NC button: pressed = 0
  if (isInput(w.var)) await setVar(w.var, v, !down);  // Bound input tag: force on press, release force on release
  else await setVar(w.var, v);
}
async function toggle(w: any) { if (usePanel(w)) { panelOn[w.id] = !panelOn[w.id]; await panel(w, 'toggle'); return; } await setVar(w.var, !isOn(w)); }
async function writeNum(w: any, v: string) { if (v !== '') await setVar(w.var, v); }
function symbols(type: string) {
  const all = sessRef.value?.symbols() || [];
  if (['button', 'switch', 'lamp'].includes(type)) return all.filter((s) => s.type === 'BOOL');
  return all.filter((s) => s.type !== 'BOOL' && !['TON', 'TOF', 'TP', 'CTU', 'CTD', 'CTUD', 'R_TRIG', 'F_TRIG', 'SR', 'RS'].includes(s.type));
}
const trendVars = (w: any) => (w.vars?.length ? w.vars : w.var ? [w.var] : []);
watch(() => sessRef.value?.s.lastPoll, () => {
  if (!scr.value) return;
  for (const w of scr.value.widgets) if (w.type === 'trend') for (const v of trendVars(w)) {
    const x = Number(val(v)); const k = v.toUpperCase();
    (hist[k] ||= []).push(Number.isFinite(x) ? x : 0);
    if (hist[k].length > 240) hist[k].splice(0, hist[k].length - 240);
  }
});
function trendPts(w: any, v: string) {
  const d = hist[v.toUpperCase()] || [];
  const W = Math.max(10, w.w), H = Math.max(10, w.h - 22);
  const lo = w.min ?? 0, hi = w.max ?? 100;
  const n = d.length;
  return d.map((y, i) => `${W - ((n - 1 - i) / 239) * W},${H - ((y - lo) / ((hi - lo) || 1)) * H}`).join(' ');       // Newest on the right
}
// If an object (PLC / HMI block / equipment) is specified, wait for the PLC list to load before choosing the screen
if (!props.bid) loadList();
else if (cellsLoaded.value) loadList();
else { const stop = watch(cellsLoaded, (v) => { if (v) { stop(); loadList(); } }); }
</script>

<style scoped>
.hmi { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ld-bg); }
.hb { display: flex; align-items: center; gap: 6px; padding: 6px 8px; border-bottom: 1px solid var(--ld-ln); background: var(--ld-card); flex-wrap: wrap; }
.hm { flex: 1; min-height: 0; display: flex; }
.pal { width: 120px; flex: none; border-right: 1px solid var(--ld-ln); padding: 6px; overflow: auto; background: var(--ld-card); }
.pt { font-weight: 600; margin: 2px 2px 8px; }
.pi { display: flex; align-items: center; gap: 6px; width: 100%; height: 30px; margin-bottom: 4px; padding: 0 8px; border: 1px solid var(--ld-ln); border-radius: 5px; background: var(--ld-bg);
  color: var(--ld-tx); cursor: pointer; font: inherit; }
.pi:hover { border-color: var(--ld-sel); }
.tip { font-size: 11px; line-height: 1.6; margin-top: 8px; }
.cv-wrap { flex: 1; min-width: 0; overflow: auto; padding: 16px; background: var(--ld-bar); }
.cv { position: relative; background: var(--hmi-panel); border-radius: 6px; box-shadow: 0 2px 12px var(--ld-shadow); color: var(--hmi-tx); }
.cv.edit { background-image: radial-gradient(var(--hmi-grid) 1px, transparent 1px); background-size: 10px 10px; }
.w { position: absolute; box-sizing: border-box; }
.cv.edit .w { cursor: move; outline: 1px dashed var(--hmi-grid); }
.w.sel { outline: 2px solid var(--hmi-sel) !important; }
.rs { position: absolute; right: -5px; bottom: -5px; width: 11px; height: 11px; background: var(--hmi-sel); border-radius: 2px; cursor: nwse-resize; }
.vtag { position: absolute; left: 0; top: -15px; font-size: 10px; color: var(--hmi-sel); white-space: nowrap; }
.hbtn { width: 100%; height: 100%; border: 0; border-radius: 6px; color: #fff; font: 600 14px "Microsoft YaHei", sans-serif; cursor: pointer;
  box-shadow: 0 3px 0 var(--ld-shadow), inset 0 1px 0 rgba(255, 255, 255, .25); }
.hbtn.dn { transform: translateY(2px); box-shadow: 0 1px 0 var(--ld-shadow), inset 0 2px 6px var(--ld-shadow); filter: brightness(.9); }
.cv.edit .hbtn, .cv.edit .hsw { pointer-events: none; }
.hsw { display: flex; align-items: center; gap: 8px; height: 100%; padding: 0 10px; background: var(--hmi-card); border: 1px solid var(--hmi-ln); border-radius: 23px; cursor: pointer; }
.hsw .knob { width: 34px; height: 20px; border-radius: 10px; background: var(--hmi-off); position: relative; flex: none; transition: background .15s; }
.hsw .knob::after { content: ''; position: absolute; top: 2px; left: 2px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: left .15s; }
.hsw.on .knob { background: var(--ld-on-led); } .hsw.on .knob::after { left: 16px; }
.hsw small { margin-left: auto; color: var(--hmi-mu); }
.hlamp { display: flex; align-items: center; gap: 10px; height: 100%; padding: 0 8px; }
.bulb { width: 28px; height: 28px; border-radius: 50%; background: var(--hmi-off); border: 2px solid var(--hmi-ln); flex: none; }
.hnum { display: flex; flex-direction: column; justify-content: center; height: 100%; padding: 4px 10px; background: var(--hmi-lcd); border-radius: 6px; color: var(--hmi-lcd-tx); position: relative; }
.hnum small { color: var(--hmi-lcd-mu); font-size: 11px; } .hnum b { font-size: 20px; } .hnum i { position: absolute; right: 8px; bottom: 6px; color: var(--hmi-lcd-mu); font-style: normal; font-size: 11px; }
.hnum input { height: 24px; border: 1px solid var(--hmi-lcd-mu); border-radius: 3px; background: transparent; color: var(--hmi-lcd-tx); padding: 0 6px; }
.hbar { display: flex; flex-direction: column; align-items: center; height: 100%; gap: 3px; }
.hbar small { font-size: 11px; color: var(--hmi-mu); }
.bt { position: relative; flex: 1; width: 26px; background: var(--hmi-card); border: 1px solid var(--hmi-ln); border-radius: 3px; overflow: hidden; }
.bf { position: absolute; left: 0; right: 0; bottom: 0; }
.htr { display: flex; flex-direction: column; height: 100%; background: var(--hmi-card); border: 1px solid var(--hmi-ln); border-radius: 6px; overflow: hidden; }
.trh { display: flex; gap: 8px; align-items: center; height: 22px; padding: 0 8px; font-size: 11px; border-bottom: 1px solid var(--hmi-ln); }
.trs { flex: 1; width: 100%; background: repeating-linear-gradient(0deg, transparent 0 24px, var(--hmi-ln) 24px 25px); }
.htext { height: 100%; display: flex; align-items: center; font-weight: 600; }
.hrect { height: 100%; border: 2px solid; border-radius: 8px; } .hrect small { position: relative; top: -10px; left: 10px; background: var(--hmi-panel); padding: 0 6px; color: var(--hmi-mu); }
.empty { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: var(--hmi-mu); }
.props { width: 230px; flex: none; border-left: 1px solid var(--ld-ln); padding: 8px 10px; overflow: auto; background: var(--ld-card); display: flex; flex-direction: column; gap: 4px; }
.src { background: var(--ld-info-bg); }
.opt-i { margin-left: 10px; color: var(--ld-mu); font-size: 11.5px; }
.props label { color: var(--ld-mu); font-size: 11.5px; margin-top: 6px; }
.row { display: flex; gap: 4px; } .small { font-size: 11.5px; } .pad { padding: 16px; } .grow { flex: 1; }
</style>
