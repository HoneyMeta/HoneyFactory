<template>
  <div class="plc-root pw">
    <!-- Toolbar -->
    <div class="pw-bar" data-tour="plc-bar">
      <el-select v-model="bid" size="small" class="cellsel" data-tour="plc-select" :teleported="true" placeholder="PLC">
        <el-option v-for="o in options" :key="o.id" :value="o.id" :label="o.label" />
      </el-select>
      <span v-if="sess" class="plc-chip lang" :title="sess.lang === 'LD' ? $t('plcSide.ladderDiagram') : $t('plcWorkbench.structuredText')">{{ sess.lang === 'LD' ? $t('plcWorkbench.ldLadderDiagram') : $t('plcWorkbench.stStructuredText') }}</span>
      <i class="plc-sep" />
      <template v-if="sess">
        <button class="plc-btn" :title="$t('plcWorkbench.saveTheProjectCtrlS')" :disabled="!!SS.busy || ro" @click="sess.save()"><el-icon><DocumentChecked /></el-icon>{{ $t('common.save') }}<b v-if="sess.dirty" class="dot" /></button>
        <button class="plc-btn" :title="$t('plcWorkbench.compileAndCheckWithoutDownloading')" :disabled="!!SS.busy" data-act="compile" data-tour="plc-compile" @click="sess.compile()"><el-icon><Finished /></el-icon>{{ $t('common.compile') }}</button>
        <el-dropdown split-button size="small" type="primary" trigger="click" class="dl" :disabled="!!SS.busy || isExt || ro" @click="sess.download(false)" @command="(c: string) => sess.download(c === 'cold')">
          <span data-act="download" data-tour="plc-download"><el-icon style="vertical-align: -2px"><Download /></el-icon> {{ $t('common.download') }}</span>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item command="warm">{{ $t('plcWorkbench.downloadPreservesVariableValuesWhile') }}</el-dropdown-item>
            <el-dropdown-item command="cold">{{ $t('plcWorkbench.coldStartDownloadResetsAll') }}</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
        <i class="plc-sep" />
        <button class="plc-btn go" :class="{ on: st === 'RUN' }" :title="$t('common.run')" data-act="run" :disabled="isExt || !hasProg || ro" @click="act('run')"><el-icon><VideoPlay /></el-icon>{{ $t('common.run') }}</button>
        <button class="plc-btn st" :title="$t('plcWorkbench.stopAllOutputsBecome0')" data-act="stop" :disabled="isExt || !hasProg || ro" @click="act('stop')"><el-icon><VideoPause /></el-icon>{{ $t('common.stop') }}</button>
        <button class="plc-btn" :title="$t('plcWorkbench.stepExecuteOneCompleteScan')" :disabled="isExt || !hasProg || ro" @click="act('step', { kind: 'scan' })"><el-icon><Right /></el-icon>{{ $t('plcWorkbench.stepScanCycle') }}</button>
        <button class="plc-btn" :title="sess.lang === 'LD' ? $t('plcWorkbench.stepExecuteOneRungThen') : $t('plcWorkbench.stepExecuteOneStatementThen')" :disabled="isExt || !hasProg || ro" @click="act('step', { kind: 'stmt' })"><el-icon><Bottom /></el-icon>{{ sess.lang === 'LD' ? $t('plcWorkbench.stepRung') : $t('plcWorkbench.stepStatement') }}</button>
        <el-dropdown trigger="click" @command="more">
          <button class="plc-btn" :title="$t('plcWorkbench.moreBreakpointsForcingResetImport')"><el-icon><MoreFilled /></el-icon></button>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item v-if="isTeacher" command="reference" data-act="reference">{{ $t('plcWorkbench.loadReferenceSolutionReadOnly') }}</el-dropdown-item>
            <el-dropdown-item command="export" :divided="isTeacher">{{ $t('plcWorkbench.exportPlcopenXml') }}</el-dropdown-item>
            <template v-if="!ro">
            <el-dropdown-item command="clearbp" :disabled="!SS.online?.bps?.length">{{ $t('plcWorkbench.clearAllBreakpoints') }}</el-dropdown-item>
            <el-dropdown-item command="unforce" :disabled="!Object.keys(SS.online?.forced || {}).length">{{ $t('plcWorkbench.releaseAllForces') }}</el-dropdown-item>
            <el-dropdown-item command="warm" divided>{{ $t('plcWorkbench.warmResetRetainRetentiveVariables') }}</el-dropdown-item>
            <el-dropdown-item command="cold">{{ $t('plcWorkbench.coldResetResetAllValues') }}</el-dropdown-item>
            <el-dropdown-item command="import" divided>{{ $t('plcWorkbench.importPlcopenXml') }}</el-dropdown-item>
            <el-dropdown-item command="newld" divided>{{ $t('plcWorkbench.newLadderProgramReplaceCurrent') }}</el-dropdown-item>
            <el-dropdown-item command="newst">{{ $t('plcWorkbench.newStProgramReplaceCurrent') }}</el-dropdown-item>
            <el-dropdown-item command="reload" divided>{{ $t('plcWorkbench.reloadProject') }}</el-dropdown-item>
            <el-dropdown-item command="reset_program">{{ $t('plcWorkbench.restoreOriginalProgram0', [bid === '_sandbox' ? $t('plcWorkbench.samplePrograms') : $t('plcWorkbench.programsIncludedWithTheUnit')]) }}</el-dropdown-item>
            <el-dropdown-item command="reset_stats">{{ $t('plcWorkbench.resetScanTimeStatistics') }}</el-dropdown-item>
            </template>
          </el-dropdown-menu></template>
        </el-dropdown>
        <span class="grow" />
        <el-tooltip :content="$t('plcWorkbench.whenEnabledTheProgramShows')" placement="bottom">
          <el-switch v-model="SS.monitor" size="small" :active-text="$t('common.onlineMonitor')" data-tour="plc-monitor" />
        </el-tooltip>
        <span class="plc-chip" :class="st" data-state data-tour="plc-state">{{ STATE_CN[st] || st || '—' }}<i /></span>
        <span v-if="mismatch" class="plc-chip warn" :title="$t('plcWorkbench.theEditorProgramDiffersFrom')">{{ $t('plcWorkbench.notDownloaded') }}</span>
        <el-tooltip v-if="overrun" :content="overrun.tip" placement="bottom">
          <span class="plc-chip warn" data-overrun>{{ overrun.text }}</span>
        </el-tooltip>
        <span v-if="ro" class="plc-chip" :title="$t('plcWorkbench.viewingAStudentSandboxOr')">{{ $t('signals.readOnly2') }}</span>
        <span class="scan mono" :title="$t('plcWorkbench.scans0Cycle1Ms', [SS.online?.scan?.count ?? 0, SS.online?.scan?.cycle_ms ?? '—'])">
          {{ scanTxt }}
        </span>
      </template>
      <GuideButton area="plc" size="sm" />
    </div>
    <EmptyCells v-if="noCells && bid === '_sandbox'" banner :running="running" />
    <div v-if="tipOn && SS.online && !isExt" class="plc-banner tip">
      <span>{{ $t('plcWorkbench.debuggingTips') }}<b>{{ $t('workbench.rightClick') }}</b>{{ $t('plcWorkbench.n0CanBeForcedTo', [sess?.lang === 'LD' ? $t('plcWorkbench.element') : '', sess?.lang === 'LD' ? $t('plcWorkbench.clickTheDotToThe') : $t('plcWorkbench.clickToTheLeftOf'), sess?.lang === 'LD' ? $t('ladderEditor.rung') : $t('plcWorkbench.statement')]) }}</span>
      <button class="x" :title="$t('plcWorkbench.donTShowAgain')" @click="hideTip">×</button>
    </div>
    <div v-if="SS.online?.error" class="pw-err" @click="gotoErr(SS.online.error)">
      {{ $t('plcWorkbench.plcRuntimeError0', [SS.online.error.msg]) }}<template v-if="SS.online.error.line">{{ $t('plcWorkbench.line0', [SS.online.error.line]) }}</template><template v-else-if="SS.online.error.rung != null">{{ $t('plcWorkbench.rung0', [SS.online.error.rung + 1]) }}</template>
      {{ $t('plcWorkbench.stopEditTheProgramThen') }}
    </div>
    <!-- 4.5 "Why no response": diagnose unchanged outputs after a button press (shown only when this program matches the one running on the PLC; highlighted red in the ladder) -->
    <div v-if="diagOn" class="plc-banner bad pw-diag" data-k="plc-diag" @click="gotoDiag">
      <b>{{ $t('plcWorkbench.diagnostics') }}</b><span class="dmsg">{{ diagOn.msg }}</span>
      <span v-if="diagOn.rung !== undefined && diagOn.rung !== null" class="dgo">{{ $t('plcWorkbench.rung0IsHighlightedIn', [diagOn.rung + 1]) }}</span>
      <span v-else-if="diagOn.line" class="dgo">{{ $t('plcWorkbench.line02', [diagOn.line]) }}</span>
      <button class="x" :title="$t('common.gotIt')" @click.stop="dismissDiag">×</button>
    </div>
    <div v-if="isExt" class="pw-ext">{{ $t('plcWorkbench.thisUnitIsControlledBy', [SS.online?.external?.protocol_cn]) }}</div>

    <!-- Main content -->
    <div v-if="sess && SS.program" class="pw-main">
      <div class="tabs">
        <button v-for="t in TABS" :key="t.k" class="tab" :class="{ on: tab === t.k }" :data-tab="t.k" :data-tour="'plc-tab-' + t.k" @click="tab = t.k">
          <el-icon><component :is="t.icon" /></el-icon>{{ t.label }}<b v-if="t.k === 'msg' && SS.errors.length" class="cnt bad">{{ SS.errors.length }}</b>
          <b v-else-if="t.k === 'msg' && SS.warnings.length" class="cnt">{{ SS.warnings.length }}</b>
        </button>
        <button v-if="refSess" class="tab" :class="{ on: tab === 'ref' }" data-tab="ref" @click="tab = 'ref'"><el-icon><Reading /></el-icon>{{ $t('plcWorkbench.referenceSolutionReadOnly') }}</button>
        <span class="grow" />
        <span class="muted small">{{ SS.cell?.name || bid }} · {{ SS.program.name || $t('plcSide.mainProgram') }}</span>
      </div>
      <PlcHaltBar :pid="pid" />
      <div class="pane" data-tour="plc-pane">
        <LadderEditor v-if="tab === 'prog' && sess.lang === 'LD'" ref="ldRef" :key="'ld' + bid" :sess="sess" @xref="showXref" />
        <StEditor v-else-if="tab === 'prog'" ref="stRef" :key="'st' + bid" :sess="sess" />
        <VarTable v-else-if="tab === 'vars'" :sess="sess" />
        <IoTable v-else-if="tab === 'io'" :sess="sess" />
        <TimingChart v-else-if="tab === 'timing'" :key="'tc' + bid" :sess="sess" />
        <div v-else-if="tab === 'log'" class="pw-log"><RunLog :pid="pid" /></div>
        <XrefTable v-else-if="tab === 'xref'" :key="'xr' + bid" :sess="sess" :focus="xrefFocus" @goto="gotoErr" />
        <div v-else-if="tab === 'ref' && refSess" class="refv">
          <div class="plc-banner">{{ $t('plcWorkbench.referenceSolutionReadOnly0', [refInfo?.name, refSess.s.program.name]) }}
            <el-radio-group v-if="refInfo?.programs?.length > 1" v-model="refIdx" size="small" style="margin-left: 8px">
              <el-radio-button v-for="(r, i) in refInfo.programs" :key="i" :value="i">{{ r.lang === 'LD' ? $t('plcSide.ladderDiagram') : 'ST' }}</el-radio-button>
            </el-radio-group>
            <span class="muted">{{ $t('plcWorkbench.studentsCannotSeeThisView') }}</span></div>
          <div class="refbody">
            <LadderEditor v-if="refSess.s.program.lang === 'LD'" :key="'rl' + refIdx" :sess="refSess" readonly />
            <StEditor v-else :key="'rs' + refIdx" :sess="refSess" readonly />
          </div>
        </div>
        <div v-else-if="tab === 'msg'" class="msgs">
          <div v-if="!SS.compile" class="muted pad">{{ $t('plcWorkbench.notCompiledYetClickCompile') }}</div>
          <div v-else-if="!SS.errors.length && !SS.warnings.length" class="ok pad">{{ $t('plcWorkbench.compilationSuccessfulWithNoErrors') }}</div>
          <div v-for="(e, i) in SS.errors" :key="'e' + i" class="msg err" @click="gotoErr(e)">✖ <b>{{ where(e) }}</b>{{ e.msg }}</div>
          <div v-for="(e, i) in SS.warnings" :key="'w' + i" class="msg warn" @click="gotoErr(e)">⚠ <b>{{ where(e) }}</b>{{ e.msg }}</div>
        </div>
      </div>
      <!-- Footer: single-line compilation result -->
      <div class="pw-foot" @click="tab = 'msg'">
        <template v-if="SS.compile">
          <span :class="SS.errors.length ? 'bad' : 'ok'">{{ SS.errors.length ? $t('plcWorkbench.errors0', [SS.errors.length]) : $t('plcWorkbench.compilationSuccessful') }}</span>
          <span v-if="SS.warnings.length" class="warnc">{{ $t('plcWorkbench.warnings0', [SS.warnings.length]) }}</span>
          <span v-if="SS.errors[0]" class="first" @click.stop="gotoErr(SS.errors[0])">{{ where(SS.errors[0]) }}{{ SS.errors[0].msg }}</span>
        </template>
        <span v-else class="muted">{{ $t('plcWorkbench.notCompiled') }}</span>
        <span class="grow" />
        <span class="muted">{{ $t('plcWorkbench.variables0IO1', [(SS.program.vars || []).length, SS.io.length]) }}<template v-if="sess.lang === 'LD'"> {{ $t('plcWorkbench.rung02', [SS.program.source.rungs.length]) }}</template></span>
      </div>
    </div>
    <div v-else class="pad muted">{{ $t('plcWorkbench.loadingPlcProgram') }}</div>
    <input ref="fileIn" type="file" accept=".xml" style="display: none" @change="doImport" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import './plc.css';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { useCells } from './cells';
import EmptyCells from './EmptyCells.vue';
import IoTable from './IoTable.vue';
import LadderEditor from './LadderEditor.vue';
import { downloadFile, plcApi, STATE_CN } from './plcApi';
import { normalize, Sess, useSession } from './session';
import StEditor from './StEditor.vue';
import VarTable from './VarTable.vue';
import TimingChart from './TimingChart.vue';
import XrefTable from './XrefTable.vue';
import PlcHaltBar from './PlcHaltBar.vue';
import GuideButton from '../components/GuideButton.vue';
import { canEdit, get, session } from '../api';
import { C } from './plcApi';
import { reactive } from 'vue';
import RunLog from '../panels/teach/RunLog.vue';
import { useCoach } from '../panels/teach/coach';

const props = defineProps<{ pid: string; bid?: string; tab?: string }>();
const { bid, options, noCells, running } = useCells(() => props.pid, () => props.bid);
let tipSeen = false;
try { tipSeen = localStorage.getItem('vf_plc_tip') === '1'; } catch { /* Private browsing mode */ }
const tipOn = ref(!tipSeen);
function hideTip() { tipOn.value = false; try { localStorage.setItem('vf_plc_tip', '1'); } catch { /* */ } }
const TABS = [{ k: 'prog', label: $t('common.program'), icon: 'EditPen' }, { k: 'vars', label: $t('common.variable'), icon: 'List' }, { k: 'io', label: $t('ioTable.iOMonitor'), icon: 'Switch' },
  { k: 'timing', label: $t('plcWorkbench.timingChart'), icon: 'DataLine' }, { k: 'log', label: $t('common.logs'), icon: 'Tickets' }, { k: 'xref', label: $t('plcWorkbench.crossReference'), icon: 'Connection' },
  { k: 'msg', label: $t('plcWorkbench.compilerMessages'), icon: 'Warning' }];
/** Read-only: teachers observing student sandboxes and read-only accounts. */
const ro = computed(() => !canEdit());
const isTeacher = computed(() => ['teacher', 'admin', 'engineer'].includes(session.user?.role));
const xrefFocus = ref('');
function showXref(name: string) { xrefFocus.value = name; tab.value = 'xref'; }
// ---- Reference answer (read-only comparison, T18)
const refInfo = ref<any>(null);
const refIdx = ref(0);
const refSess = computed(() => {
  const p = refInfo.value?.programs?.[refIdx.value];
  if (!p) return null;
  const s = reactive<any>({ pid: props.pid, bid: '__ref', program: normalize(p), io: SS.value.io, online: null, monitor: false, errors: [], warnings: [],
    compile: null, sel: [], selRung: -1, rev: 0, undo: [], redo: [], clip: null });
  const noop = () => undefined;
  return { s, get dirty() { return false; }, get lang() { return s.program.lang; }, change: noop, snap: noop, undoOne: noop, redoOne: noop, save: noop,
    act: async () => undefined, symbols: () => (sessRef.value ? sessRef.value.symbols() : []), typeOf: () => undefined, compileQuiet: async () => null } as any;
});
async function loadReference() {
  try {
    refInfo.value = await get(`${C(props.pid, bid.value)}/reference`);
    refIdx.value = 0;
    tab.value = 'ref';
  } catch { /* Already notified */ }
}
// ---- Scan overrun (S26)
const overrun = computed(() => {
  const sc = SS.value.online?.scan;
  if (!sc || isExt.value || !sc.over) return null;
  const heavy = sc.avg_ms > sc.cycle_ms || sc.over_pct >= 10;
  return { text: heavy ? $t('plcWorkbench.scanOverruns0', [sc.over_pct]) : $t('plcWorkbench.scanOverruns02', [sc.over]),
    tip: $t('plcWorkbench.scanTimeExceededThe0', [sc.cycle_ms, sc.max_ms.toFixed(1), sc.over_recent]) +
      (heavy ? $t('plcWorkbench.theProgramMayContainLengthy') : $t('plcWorkbench.anOccasionalOverrunUsuallyMeans')) };
});
// ---- Preserve changes before leaving (S41): autosave the project on window close/page navigation (no download to PLC); prompt on refresh/browser close
function beforeUnload(e: BeforeUnloadEvent) { if (sessRef.value?.dirty && !ro.value) { e.preventDefault(); e.returnValue = ''; } }
window.addEventListener('beforeunload', beforeUnload);
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload);
  const s = sessRef.value;
  if (s && s.dirty && !ro.value) s.save(true).then(() => ElMessage.info($t('plcWorkbench.plcProgramChangesSavedAutomatically'))).catch(() => undefined);
});
const tab = ref(props.tab || 'prog');
const sessRef = shallowRef<Sess | null>(null);
const sess = computed(() => sessRef.value);
const ldRef = ref<any>();
const stRef = ref<any>();
const fileIn = ref<HTMLInputElement>();
let release: (() => void) | null = null;

watch(bid, async (b) => {
  release?.(); release = null;
  if (!b) return;
  const s = useSession(props.pid, b);
  sessRef.value = s;
  release = s.use();
  try { await s.load(); } catch { /* Already notified */ }
}, { immediate: true });
onBeforeUnmount(() => release?.());

const Sx = computed(() => sessRef.value?.s as any);
// Use S in the template (switches with the session)
const SS = computed(() => Sx.value || { errors: [], warnings: [], io: [], online: null, program: null });
defineExpose({ SS });
// ---- 4.5 diagnostics: when the coach (run log) detects "no response to a press", store the cause in this PLC's session (red ladder highlights, ST line markers)
const co = useCoach(props.pid);
const dismissed = ref(0);
const diagOn = computed<any>(() => {
  const d = co.s.diag;
  if (!d || d.plc !== bid.value || d.seq <= dismissed.value) return null;
  if (d.hash && SS.value.onlineHash && d.hash !== SS.value.onlineHash) return null;      // Diagnostics refer to an older program
  return d;
});
watch(diagOn, (d) => { const s = sessRef.value?.s as any; if (s) s.diag = d ? { ...d } : null; }, { immediate: true });
watch(sessRef, () => { const s = sessRef.value?.s as any; if (s) s.diag = diagOn.value ? { ...diagOn.value } : null; });
function dismissDiag() { dismissed.value = co.s.diag?.seq || 0; }
function gotoDiag() {
  const d = diagOn.value; if (!d) return;
  gotoErr(d.rung !== undefined && d.rung !== null ? { rung: d.rung, elem: d.elems?.[0] } : { line: d.line });
}
function onGoto(e: any) {
  const d = e.detail || {};
  if (d.pid !== props.pid || (d.plc && d.plc !== bid.value)) return;
  gotoErr(d.rung !== undefined && d.rung !== null ? { rung: d.rung, elem: d.elems?.[0] } : { line: d.line });
}
window.addEventListener('vf:plc-goto', onGoto);
onBeforeUnmount(() => window.removeEventListener('vf:plc-goto', onGoto));
function onTab(e: any) { if (e.detail?.tab && (!e.detail.pid || e.detail.pid === props.pid)) tab.value = e.detail.tab; }
window.addEventListener('vf:plc-tab', onTab);
onBeforeUnmount(() => window.removeEventListener('vf:plc-tab', onTab));
const st = computed(() => SS.value.online?.state || '');
const isExt = computed(() => st.value === 'EXTERNAL');
const hasProg = computed(() => !!SS.value.online?.hash || !!SS.value.onlineHash);
const mismatch = computed(() => !isExt.value && SS.value.projectHash && SS.value.onlineHash !== undefined && sessRef.value?.dirty === false
  ? SS.value.onlineHash !== SS.value.projectHash : !!sessRef.value?.dirty && !!SS.value.onlineHash);
const scanTxt = computed(() => {
  const sc = SS.value.online?.scan;
  if (!sc || isExt.value) return '';
  return $t('plcWorkbench.scan0MsAverage1', [sc.last_ms.toFixed(2), Number(sc.avg_ms).toFixed(2), sc.max_ms.toFixed(2), sc.cycle_ms]);
});

async function act(action: string, extra: any = {}) {
  try { await sessRef.value!.act({ action, ...extra }); } catch { /* Already notified */ }
}
function where(e: any) {
  if (e.line) return $t('plcWorkbench.line01', [e.line, e.col ? $t('plcWorkbench.column0', [e.col]) : '']);
  if (e.rung !== undefined && e.rung !== null) return $t('plcWorkbench.rung03', [e.rung + 1]);
  if (e.var) return $t('plcWorkbench.variable0', [e.var]);
  return '';
}
function gotoErr(e: any) {
  tab.value = e.var ? 'vars' : 'prog';
  nextTick(() => {
    if (e.line && stRef.value) stRef.value.gotoLine(e.line);
    if (e.rung !== undefined && e.rung !== null) {
      const s = sessRef.value!.s;
      if (e.elem) { s.sel = [e.elem]; s.selRung = -1; } else { s.sel = []; s.selRung = e.rung; }
      nextTick(() => document.querySelector(`.lde [data-rung="${e.rung}"]`)?.scrollIntoView({ block: 'nearest' }));
    }
  });
}
async function more(c: string) {
  const s = sessRef.value!;
  if (c === 'clearbp') await act('breakpoint', { clear: true });
  else if (c === 'unforce') await act('unforce_all');
  else if (c === 'warm' || c === 'cold') await act('reset', { cold: c === 'cold' });
  else if (c === 'import') fileIn.value?.click();
  else if (c === 'reference') await loadReference();
  else if (c === 'reset_stats') await act('reset_stats');
  else if (c === 'export') await downloadFile(plcApi.exportUrl(props.pid, bid.value), `${props.pid}-${bid.value}-plc.xml`);
  else if (c === 'reset_program') {
    await ElMessageBox.confirm($t('plcWorkbench.discardTheCurrentProgramIncluding'), $t('plcWorkbench.restoreOriginalProgram'), { type: 'warning' });
    await act('reset_program'); await s.load(true); s.clearCompile(); ElMessage.success($t('plcWorkbench.originalProgramRestored'));
  } else if (c === 'reload') { if (s.dirty) await ElMessageBox.confirm($t('plcWorkbench.unsavedChangesInTheEditor'), $t('plcWorkbench.reload'), { type: 'warning' }); await s.load(true); s.clearCompile(); }
  else if (c === 'newld' || c === 'newst') {
    await ElMessageBox.confirm($t('plcWorkbench.theCurrentProgramWillBe'), $t('plcWorkbench.newProgram'), { type: 'warning' });
    s.change((p) => {
      const n = normalize({ id: p.id, name: p.name, vars: p.vars, lang: c === 'newld' ? 'LD' : 'ST',
        source: c === 'newld' ? { rungs: [{ comment: '', elements: [] }] } : $t('plcWorkbench.programMainWriteYourProgram') });
      Object.assign(p, n);
    });
    s.clearCompile();
  }
}
async function doImport(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = '';
  if (!f) return;
  const s = sessRef.value!;
  const txt = await f.text();
  const r = await plcApi.importXml(props.pid, bid.value, txt, false);
  s.change((p) => Object.assign(p, normalize(r.program)));
  s.clearCompile();
  s.applyCompile(r.compile);
  ElMessage.success($t('plcWorkbench.imported0', [f.name]) + (r.warnings?.length ? $t('plcWorkbench.n0NotesSeeCompilerMessages', [r.warnings.length]) : ''));
  if (r.warnings?.length) s.s.warnings = [...(r.compile.warnings || []), ...r.warnings.map((w: string) => ({ msg: w }))];
}
// Ctrl+S: handled by the ladder and ST editors when focused; leave the Workbench global shortcut alone
</script>

<script lang="ts">
export default { name: 'PlcWorkbench' };
</script>

<style scoped>
.pw { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ld-bg); }
.pw-bar { display: flex; align-items: center; gap: 5px; padding: 6px 8px; border-bottom: 1px solid var(--ld-ln); background: var(--ld-card); flex-wrap: wrap; }
.cellsel { width: 190px; }
.lang { font-weight: 600; }
.dot { display: inline-block; width: 6px; height: 6px; border-radius: 50%; background: var(--ld-halt); margin-left: 2px; }
.dl :deep(.el-button) { height: 28px; }
.scan { font-size: 11px; color: var(--ld-mu); white-space: nowrap; }
.pw-err { padding: 5px 12px; background: var(--ld-bad-bg); color: var(--ld-bad); border-bottom: 1px solid var(--ld-bad); cursor: pointer; font-size: 12.5px; }
.pw-ext { padding: 5px 12px; background: var(--ld-info-bg); color: var(--ld-tx); border-bottom: 1px solid var(--ld-ln); font-size: 12px; }
.pw-main { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.tabs { display: flex; align-items: center; gap: 2px; padding: 0 8px; background: var(--ld-bar); border-bottom: 1px solid var(--ld-ln); overflow-x: auto; overflow-y: hidden; scrollbar-width: none; }
.tabs > .muted { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tab { display: flex; align-items: center; gap: 5px; height: 32px; padding: 0 12px; border: 0; border-bottom: 2px solid transparent; background: none; color: var(--hm-text-2, #44536a);
  cursor: pointer; font: inherit; font-size: 12.5px; white-space: nowrap; flex: none; }
.tab.on { color: var(--ld-sel); border-bottom-color: var(--ld-sel); font-weight: 600; }
.tab:hover { color: var(--ld-sel); }
.cnt { min-width: 16px; height: 16px; line-height: 16px; border-radius: 8px; padding: 0 4px; background: var(--ld-warn); color: #fff; font-size: 10px; }
.cnt.bad { background: var(--ld-bad); }
.pane { flex: 1; min-height: 0; overflow: hidden; }
.refv { display: flex; flex-direction: column; height: 100%; }
.refbody { flex: 1; min-height: 0; }
.pw-log { height: 100%; padding: 6px 10px; box-sizing: border-box; background: var(--ld-card); }
.pw-diag { cursor: pointer; line-height: 1.5; }
.pw-diag .dmsg { flex: 1; min-width: 200px; }
.pw-diag .dgo { font-weight: 600; white-space: nowrap; }
.msgs { height: 100%; overflow: auto; padding: 6px 0; background: var(--ld-card); }
.msg { padding: 5px 14px; cursor: pointer; border-bottom: 1px solid var(--ld-ln); font-size: 12.5px; }
.msg:hover { background: var(--ld-hov); }
.msg.err { color: var(--ld-bad); } .msg.warn { color: var(--ld-warn); }
.msg b { font-weight: 600; margin-right: 6px; }
.pw-foot { display: flex; align-items: center; gap: 12px; height: 24px; padding: 0 10px; border-top: 1px solid var(--ld-ln); background: var(--ld-card); font-size: 11.5px; cursor: pointer; }
.pw-foot .ok { color: var(--ld-pow); } .pw-foot .bad { color: var(--ld-bad); } .warnc { color: var(--ld-warn); }
.first { color: var(--ld-mu); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 50%; }
.pad { padding: 16px; } .ok { color: var(--ld-pow); } .small { font-size: 11.5px; } .grow { flex: 1; }
</style>
