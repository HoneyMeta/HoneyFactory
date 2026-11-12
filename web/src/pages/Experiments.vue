<template>
  <div class="page">
    <div class="page-head" data-tour="exp-head"><h2>{{ $t('common.experimentsOptimization') }}</h2>
      <span class="sub one" :title="$t('experiments.scenarioComparisonParametersLevelsRe')">{{ $t('experiments.scenarioComparisonParametersLevelsRe') }}</span>
      <template v-if="edit && tab === 'exp'">
        <el-button type="primary" data-tour="exp-new" @click="openNew"><el-icon><Plus /></el-icon>{{ $t('experiments.newExperiment') }}</el-button>
        <el-button data-tour="exp-opt" @click="openOpt"><el-icon><TrendCharts /></el-icon>{{ $t('experiments.parameterOptimization') }}</el-button>
        <el-tooltip :content="$t('experiments.addDemoFactoryExamplesA')" placement="bottom">
          <el-button :loading="seeding" data-tour="exp-samples" @click="fillSamples">{{ $t('experiments.populateWithExamples') }}</el-button></el-tooltip></template>
      <GuideButton area="experiments" /></div>
    <el-tabs v-model="tab" data-tour="exp-tabs">
      <el-tab-pane :label="$t('common.experimentsOptimization')" name="exp">
        <div class="grid main">
          <div class="card list" data-tour="exp-list">
            <div v-for="e in list" :key="e.id" class="it click" :class="{ on: cur?.id === e.id }" @click="openExp(e.id)">
              <span class="kd" :class="e.kind">{{ e.kind === 'optimize' ? $t('experiments.optimize') : $t('experiments.compare') }}</span><b>{{ e.name }}</b><span class="tag-st" :class="'st-' + e.status">{{ ST[e.status] }}</span>
              <div class="small muted">{{ $t('experiments.n01H2Replications', [e.kind === 'optimize' ? $t('experiments.upTo0Candidates', [e.spec?.budget]) : $t('experiments.scenarios0', [e.variants.length]), e.hours, e.reps, e.created.slice(5, 16)]) }}</div>
              <el-progress v-if="e.status === 'running' || e.status === 'queued'" :percentage="Math.round(e.progress * 100)" :stroke-width="6" />
            </div>
            <div v-if="!list.length" class="muted small empty">{{ $t('experiments.noExperimentsYetClickNew') }}
              <div v-if="edit" style="margin-top:8px"><el-button size="small" :loading="seeding" @click="fillSamples">{{ $t('experiments.populateWithExamples') }}</el-button></div></div>
          </div>
          <div class="card detail" v-if="cur">
            <h3>{{ cur.name }} <small>{{ $t('experiments.n0H1Replications2', [cur.hours, cur.reps, cur.username, cur.created]) }}</small><span class="grow" />
              <template v-if="cur.status === 'done'">
                <el-button size="small" @click="download(`${api}/experiments/${cur.id}/export.xlsx`)"><el-icon><Download /></el-icon>&nbsp;Excel</el-button>
                <el-button size="small" @click="download(`${api}/experiments/${cur.id}/export.csv`)">CSV</el-button></template>
              <el-popconfirm v-if="edit" :title="$t('experiments.deleteThisExperiment')" @confirm="remove"><template #reference><el-button size="small" type="danger" plain>{{ $t('common.delete') }}</el-button></template></el-popconfirm></h3>
            <div v-if="cur.status !== 'done'"><el-progress :percentage="Math.round(cur.progress * 100)" />
              <p class="muted small">{{ cur.status === 'failed' ? $t('experiments.failed') + cur.result?.error : $t('experiments.computingInTheBackgroundEach') }}</p></div>
            <!-- Scenario comparison -->
            <template v-else-if="cur.kind !== 'optimize'">
              <div class="concl"><div v-for="t in conclText" :key="t">{{ t }}</div></div>
              <el-alert v-if="q && !q.ok" type="warning" :closable="false" show-icon class="qa" :title="$t('experiments.theResultsAreNotReliable', [q.recommended_reps])">
                <div v-for="w in q.warnings.slice(0, -1)" :key="w" class="small">{{ w }}</div>
                <el-button v-if="edit" size="small" style="margin-top:6px" @click="rerun">{{ $t('experiments.runAgainWith0Replications', [q.recommended_reps]) }}</el-button></el-alert>
              <p v-if="q?.clamped_note" class="small muted">{{ q.clamped_note }}</p>
              <div class="kbar"><span class="small muted">{{ $t('experiments.viewMetrics') }}</span>
                <el-segmented v-model="ck" size="small" :options="cur.result.kpis.filter((k: any) => MAIN.includes(k.key)).map((k: any) => ({ label: k.label, value: k.key }))" /></div>
              <CiBarChart :rows="ciRows" :title="kmeta[ck]?.label" :unit="kmeta[ck]?.unit" :percent="ck === 'scrap_rate'" :height="250" />
              <el-table :data="cur.result.rows" size="small" style="margin-top:6px" row-key="name">
                <el-table-column type="expand"><template #default="{ row }">
                  <div class="reps"><b>{{ $t('experiments.eachReplication') }}</b>{{ $t('experiments.seed0', [row.reps.map((x: any) => x.seed).join($t('common.k360'))]) }}
                    <el-table :data="row.reps" size="small"><el-table-column :label="$t('experiments.seed')" prop="seed" width="80" />
                      <el-table-column v-for="k in cur.result.kpis.filter((k: any) => MAIN.includes(k.key))" :key="k.key" :label="k.label" align="right"><template #default="{ row: x }">{{ show(x[k.key], k.key) }}</template></el-table-column>
                      <el-table-column :label="$t('common.bottleneck')" min-width="140"><template #default="{ row: x }">{{ x.bottleneck[0]?.name }}</template></el-table-column></el-table></div></template></el-table-column>
                <el-table-column :label="$t('common.solution')" min-width="170" fixed><template #default="{ row }"><b>{{ row.name }}</b><span v-if="row.name === cur.result.best" class="tag-st st-done" style="margin-left:4px">{{ $t('common.recommended') }}</span>
                  <div class="small muted wrap">{{ row.changes.map(chg).join($t('common.k344')) || $t('experiments.currentConfiguration') }}</div></template></el-table-column>
                <el-table-column v-for="k in cur.result.kpis.filter((k: any) => SHOWK.includes(k.key))" :key="k.key" :label="k.label + (k.unit ? ` ${k.unit}` : '')" min-width="112" align="right">
                  <template #default="{ row }"><b class="mono">{{ show(row.kpi[k.key], k.key) }}</b><span v-if="row.ci?.[k.key]?.half != null" class="small muted mono">{{ ciText(row.ci[k.key], k.key) }}</span>
                    <div v-if="row.delta[k.key] != null && row !== cur.result.rows[0]" class="small" :class="row.delta[k.key] * k.better > 0.005 ? 'ok' : row.delta[k.key] * k.better < -0.005 ? 'bad' : 'muted'">
                      {{ row.delta[k.key] > 0 ? '+' : '' }}{{ (row.delta[k.key] * 100).toFixed(1) }}%<span v-if="cur.result.reps > 1">{{ row.diff?.[k.key]?.significant ? $t('experiments.significant') : $t('forkPanel.notSignificant') }}</span></div></template></el-table-column>
                <el-table-column :label="$t('common.bottleneck')" min-width="150"><template #default="{ row }"><span class="small">{{ row.bottleneck_mode || row.bottleneck[0]?.name }}
                  <span v-if="row.bottleneck_mode_n && row.bottleneck_mode_n < row.reps.length" class="muted">{{ $t('experiments.n01Replications', [row.bottleneck_mode_n, row.reps.length]) }}</span></span></template></el-table-column>
              </el-table>
              <p class="small muted">{{ $t('experiments.isTheHalfWidthOf') }}</p>
            </template>
            <!-- Parameter optimization -->
            <template v-else>
              <div class="concl"><div v-for="t in conclText" :key="t">{{ t }}</div></div>
              <el-alert v-if="q && !q.ok" type="warning" :closable="false" show-icon class="qa" :title="$t('experiments.differencesBetweenCandidatesMayBe')">
                <div v-for="w in q.warnings" :key="w" class="small">{{ w }}</div></el-alert>
              <div class="grid g2" style="margin-top:10px">
                <div><div class="kbar"><span class="small muted">{{ $t('experiments.xAxis') }}</span><el-select v-model="px" size="small" style="width:130px"><el-option v-for="k in cur.result.kpis" :key="k.key" :label="k.label" :value="k.key" /></el-select>
                  <span class="small muted">{{ $t('experiments.yAxis') }}</span><el-select v-model="py" size="small" style="width:130px"><el-option v-for="k in cur.result.kpis" :key="k.key" :label="k.label" :value="k.key" /></el-select></div>
                  <ParetoChart :result="cur.result" :x="px" :y="py" :height="320" @pick="(e: any) => (sel = e)" /></div>
                <div><div class="kbar small muted">{{ $t('experiments.convergenceBest0SatisfyingThe', [kmeta[cur.result.objectives[0].key]?.label]) }}</div><Chart :option="convOpt" :height="320" /></div>
              </div>
              <div v-if="sel" class="concl small" style="margin-top:6px">{{ $t('experiments.candidate012', [sel.i + 1, Object.entries(sel.values).map(([k, v]) => `${k}=${v}`).join($t('common.k521')), cur.result.objectives.map((o: any) => `${kmeta[o.key]?.label} ${show(sel.kpi[o.key], o.key)}`).join($t('common.k521'))]) }}<span v-if="!sel.feasible" class="bad">{{ $t('experiments.constraintsNotSatisfied') }}</span></div>
              <el-table :data="evalRows" size="small" style="margin-top:8px" max-height="420">
                <el-table-column label="#" width="50"><template #default="{ row }">{{ row.i + 1 }}</template></el-table-column>
                <el-table-column label="" width="90"><template #default="{ row }"><span v-if="row.i === cur.result.best?.i" class="tag-st st-done">{{ $t('common.recommended') }}</span><span v-else-if="row.front" class="tag-st st-running">{{ $t('experiments.paretoFront') }}</span>
                  <span v-else-if="!row.feasible" class="tag-st st-failed">{{ $t('experiments.infeasible') }}</span></template></el-table-column>
                <el-table-column v-for="p in cur.result.params" :key="p.label" :label="p.label" align="right" min-width="90"><template #default="{ row }">{{ row.values[p.label] }}</template></el-table-column>
                <el-table-column v-for="k in optCols" :key="k" :label="kmeta[k]?.label" align="right" min-width="100"><template #default="{ row }"><span class="mono">{{ show(row.kpi[k], k) }}</span></template></el-table-column>
              </el-table>
            </template>
          </div>
        </div>
      </el-tab-pane>
      <el-tab-pane :label="$t('common.runWhatIfFromHere')" name="fork"><div class="card"><ForkPanel :pid="pid" /></div></el-tab-pane>
    </el-tabs>

    <!-- New experiment -->
    <el-dialog v-model="dlg" :title="$t('experiments.newExperiment2')" width="min(940px, 96vw)">
      <el-form label-width="80px" size="small" inline>
        <el-form-item :label="$t('common.name')"><el-input v-model="nx.name" style="width:220px" /></el-form-item>
        <el-form-item :label="$t('experiments.simulationDuration')"><el-input-number v-model="nx.hours" :min="0.5" :max="168" /> {{ $t('common.hours') }}</el-form-item>
        <el-form-item :label="$t('experiments.replications')"><el-input-number v-model="nx.reps" :min="1" :max="30" /></el-form-item>
        <el-form-item :label="$t('common.warmUp')"><el-input-number v-model="nx.warmup_h" :min="0" :max="48" :step="0.5" /> {{ $t('common.hours') }}</el-form-item>
        <el-form-item :label="$t('experiments.initialSeed')"><el-input-number v-model="nx.seed" :min="1" :controls="false" style="width:80px" /></el-form-item>
      </el-form>
      <p class="small muted">{{ $t('experiments.aScenarioCanBeA') }}<b>{{ $t('experiments.modelVersions') }}</b>{{ $t('experiments.forComparingTwoLayoutsOr') }}<b>{{ $t('experiments.planShift') }}</b>{{ $t('experiments.theBaselineScenarioTheCurrent') }}</p>
      <el-radio-group v-model="mode" size="small" style="margin-bottom:8px"><el-radio-button value="variants">{{ $t('experiments.defineScenariosIndividually') }}</el-radio-button><el-radio-button value="factors">{{ $t('experiments.parametersLevelsFullFactorial') }}</el-radio-button></el-radio-group>
      <template v-if="mode === 'variants'">
        <div v-for="(v, vi) in nx.variants" :key="vi" class="vr">
          <div class="vh"><el-input v-model="v.name" size="small" style="width:220px" /><span class="grow" /><el-button link type="danger" @click="nx.variants.splice(vi, 1)">{{ $t('experiments.deleteScenario') }}</el-button></div>
          <ChangeRow v-for="(c, ci) in v.changes" :key="ci" :c="c" @del="v.changes.splice(ci, 1)" />
          <el-button size="small" link type="primary" @click="v.changes.push({ type: 'param', count: 1 })">{{ $t('forkPanel.change') }}</el-button>
        </div>
        <el-button size="small" @click="nx.variants.push({ name: $t('experiments.scenario') + (nx.variants.length + 1), changes: [{ type: 'param' }] })">{{ $t('experiments.scenario2') }}</el-button>
      </template>
      <template v-else>
        <div v-for="(f, fi) in nx.factors" :key="fi" class="vr">
          <ChangeRow :c="f" factor @del="nx.factors.splice(fi, 1)" />
          <div class="cr"><span class="small muted" style="width:52px">{{ $t('experiments.levels') }}</span><el-input v-model="f.levelsText" size="small" style="width:300px" :placeholder="$t('experiments.separateWithCommasForExample')" />
            <el-input v-model="f.label" size="small" style="width:150px" :placeholder="$t('experiments.shortNameOptional')" /></div>
        </div>
        <el-button size="small" @click="nx.factors.push({ type: 'param', levelsText: '' })">{{ $t('experiments.factor') }}</el-button>
        <span class="small muted" style="margin-left:10px">{{ $t('experiments.n0ScenariosBaselineWillBe', [combos, (combos + 1) * nx.reps]) }}</span>
      </template>
      <template #footer><el-button type="primary" :loading="busy" @click="create">{{ $t('experiments.startComputing') }}</el-button></template>
    </el-dialog>

    <!-- Parameter optimization -->
    <el-dialog v-model="odlg" :title="$t('experiments.parameterOptimization2')" width="min(940px, 96vw)">
      <el-form label-width="80px" size="small" inline>
        <el-form-item :label="$t('common.name')"><el-input v-model="ox.name" style="width:200px" /></el-form-item>
        <el-form-item :label="$t('audit.method')"><el-select v-model="ox.method" style="width:150px"><el-option :label="$t('experiments.geneticAlgorithm')" value="ga" /><el-option :label="$t('experiments.randomSearch')" value="random" /></el-select></el-form-item>
        <el-form-item :label="$t('experiments.candidateLimit')"><el-input-number v-model="ox.budget" :min="4" :max="200" /></el-form-item>
        <el-form-item :label="$t('experiments.population')"><el-input-number v-model="ox.pop" :min="4" :max="30" /></el-form-item>
        <el-form-item :label="$t('experiments.simulationDuration')"><el-input-number v-model="ox.hours" :min="0.5" :max="168" /> {{ $t('common.hours') }}</el-form-item>
        <el-form-item :label="$t('experiments.perReplication')"><el-input-number v-model="ox.reps" :min="1" :max="10" /> {{ $t('forkPanel.times') }}</el-form-item>
      </el-form>
      <h4>{{ $t('experiments.tunableParameters') }} <small class="muted">{{ $t('experiments.rangeStepOrEnterLevels') }}</small></h4>
      <div v-for="(p, i) in ox.params" :key="i" class="vr">
        <ChangeRow :c="p" factor opt @del="ox.params.splice(i, 1)" />
        <div class="cr"><span class="small muted">{{ $t('experiments.from') }}</span><el-input-number v-model="p.lo" size="small" :controls="false" style="width:80px" /><span class="small muted">{{ $t('workbench.to') }}</span>
          <el-input-number v-model="p.hi" size="small" :controls="false" style="width:80px" /><span class="small muted">{{ $t('experiments.step') }}</span><el-input-number v-model="p.step" size="small" :controls="false" style="width:70px" />
          <span class="small muted">{{ $t('experiments.orLevels') }}</span><el-input v-model="p.levelsText" size="small" style="width:180px" :placeholder="$t('experiments.forExampleNormal603')" /></div>
      </div>
      <el-button size="small" @click="ox.params.push({ type: 'param', lo: 1, hi: 3, step: 1 })">{{ $t('experiments.parameter') }}</el-button>
      <h4>{{ $t('details.target') }}</h4>
      <div v-for="(o, i) in ox.objectives" :key="'o' + i" class="cr">
        <el-select v-model="o.sense" size="small" style="width:90px"><el-option :label="$t('floatLayer.maximize')" value="max" /><el-option :label="$t('experiments.minimize')" value="min" /></el-select>
        <el-select v-model="o.key" size="small" style="width:160px"><el-option v-for="k in KPIS" :key="k[0]" :label="k[1]" :value="k[0]" /></el-select>
        <el-button link type="danger" @click="ox.objectives.splice(i, 1)"><el-icon><Close /></el-icon></el-button></div>
      <el-button size="small" @click="ox.objectives.push({ key: 'wip_avg', sense: 'min' })">{{ $t('experiments.objective') }}</el-button><span class="small muted" style="margin-left:8px">{{ $t('experiments.specifyAParetoFrontWhen') }}</span>
      <h4>{{ $t('experiments.constraints') }}</h4>
      <div v-for="(c, i) in ox.constraints" :key="'c' + i" class="cr">
        <el-select v-model="c.key" size="small" style="width:160px"><el-option v-for="k in KPIS" :key="k[0]" :label="k[1]" :value="k[0]" /></el-select>
        <el-select v-model="c.op" size="small" style="width:70px"><el-option label="≤" value="<=" /><el-option label="≥" value=">=" /></el-select>
        <el-input-number v-model="c.value" size="small" :controls="false" style="width:100px" />
        <el-button link type="danger" @click="ox.constraints.splice(i, 1)"><el-icon><Close /></el-icon></el-button></div>
      <el-button size="small" @click="ox.constraints.push({ key: 'scrap_rate', op: '<=', value: 0.05 })">{{ $t('experiments.constraint') }}</el-button>
      <template #footer><el-button type="primary" :loading="busy" @click="createOpt">{{ $t('experiments.startOptimization') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, defineComponent, h, onMounted, onUnmounted, reactive, ref, resolveComponent, watch } from 'vue';
import { canEdit, del, download, get, P, pct, post } from '../api';
import Chart from '../components/Chart.vue';
import { CH } from '../design/chart';
import CiBarChart from '../components/CiBarChart.vue';
import ForkPanel from '../components/ForkPanel.vue';
import GuideButton from '../components/GuideButton.vue';
import ParetoChart from '../components/ParetoChart.vue';

const props = defineProps<{ pid: string }>();
const api = P(props.pid), edit = canEdit();
const tab = ref('exp');
const list = ref<any[]>([]), cur = ref<any>(null), dlg = ref(false), odlg = ref(false), busy = ref(false), mode = ref('variants');
const meta = ref<any>({ stations: [], buffers: {}, editable: {} }), roles = ref<string[]>([]), types = ref<any>({}), tagsOf = reactive<Record<string, string[]>>({});
const nx = reactive<any>({ name: '', hours: 24, reps: 3, warmup_h: 3, seed: 42, variants: [], factors: [] });
const ox = reactive<any>({ name: '', method: 'ga', budget: 24, pop: 8, hours: 8, reps: 1, params: [], objectives: [], constraints: [] });
const ck = ref('good_per_h'), px = ref(''), py = ref(''), sel = ref<any>(null), seeding = ref(false), versions = ref<any[]>([]);
const q = computed(() => cur.value?.result?.quality || null);
const conclText = computed(() => (cur.value?.result?.text || []).filter((t: string) => !(q.value?.warnings || []).includes(t) && t !== q.value?.clamped_note));
function ciText(c: any, k: string) { return c.clamped ? ` ${show(c.lo, k)}–${show(c.hi, k)}` : ` ±${show(c.half, k)}`; }
const ST: Record<string, string> = { queued: $t('experiments.queued'), running: $t('experiments.computing'), done: $t('common.done'), failed: $t('experiments.failed2') };
const KPIS: [string, string][] = [['good', $t('common.acceptedQty')], ['good_per_h', $t('experiments.hourlyOutput')], ['scrap_rate', $t('common.scrapRate')], ['wip_avg', $t('experiments.averageWip')], ['lead_mean', $t('experiments.averageProductionCycleTime')],
  ['lead_p90', $t('experiments.productionCycleTimeP90')], ['energy_total', $t('common.power')], ['kwh_per_good', $t('experiments.energyPerPart')], ['energy_cost', $t('experiments.electricityCost')], ['peak_kw', $t('experiments.peakDemand')], ['co2_kg', $t('energyPanel.carbonEmissions')], ['escape', $t('experiments.missedInspectionsGroundTruth')]];
const MAIN = ['good_per_h', 'scrap_rate', 'wip_avg', 'lead_mean', 'energy_total', 'energy_cost', 'peak_kw'];
const SHOWK = ['good_per_h', 'scrap_rate', 'wip_avg', 'lead_mean', 'kwh_per_good', 'energy_cost', 'peak_kw'];
const kmeta = computed<Record<string, any>>(() => Object.fromEntries((cur.value?.result?.kpis || []).map((k: any) => [k.key, k])));
const show = (v: any, k: string) => (v == null ? '—' : k === 'scrap_rate' ? (v * 100).toFixed(2) + '%' : Math.abs(v) >= 100 ? Math.round(v) : (+v).toFixed(2));
const WD: Record<string, number[]> = { all: [1, 2, 3, 4, 5, 6, 7], six: [1, 2, 3, 4, 5, 6], five: [1, 2, 3, 4, 5] };
const SHIFT_PRESETS: Record<string, { label: string; shifts: any[] }> = {
  cont: { label: $t('experiments.continuousProductionNoShifts'), shifts: [] },
  three: { label: $t('experiments.threeShiftsDay715'), shifts: [{ name: $t('experiments.dayShift'), start: '07:00', end: '15:00' }, { name: $t('experiments.eveningShift'), start: '15:00', end: '23:00' }, { name: $t('experiments.nightShift'), start: '23:00', end: '07:00' }] },
  two: { label: $t('experiments.twoShiftsDay715'), shifts: [{ name: $t('experiments.dayShift'), start: '07:00', end: '15:00' }, { name: $t('experiments.eveningShift'), start: '15:00', end: '23:00' }] },
  one: { label: $t('experiments.singleShift817'), shifts: [{ name: $t('experiments.dayShift2'), start: '08:00', end: '17:00' }] },
};
const WD_LABEL: Record<string, string> = { all: $t('experiments.daily'), six: $t('experiments.mondayToSaturday'), five: $t('experiments.mondayToFriday') };
function planLabel(c: any) { return $t('experiments.n01', [SHIFT_PRESETS[c.preset || 'two']?.label || $t('mesNav.shift'), WD_LABEL[c.wd || 'six']]); }
function setPlan(c: any) { c.shifts = SHIFT_PRESETS[c.preset || 'two'].shifts; c.workdays = WD[c.wd || 'six']; c.label = planLabel(c); }
function chg(c: any) {
  if (c.type === 'version') return c.n === 'draft' ? $t('experiments.currentDraftNotApplied') : $t('experiments.modelVersion0', [c.n]);
  if (c.type === 'plan') return c.label || $t('experiments.changeProductionPlan');
  return c.type === 'add' ? $t('experiments.add1MachinesBasedOn', [c.template, c.count]) : c.type === 'remove' ? $t('experiments.remove0', [c.station]) : c.type === 'param' ? `${c.station}.${c.key}=${c.value}`
    : c.type === 'setpoint' ? `${c.station} ${c.tag}=${c.value}` : c.type === 'crew' ? $t('experiments.n01Workers', [c.role, c.value]) : $t('experiments.buffer01', [c.name, c.value]);
}
const ciRows = computed(() => {
  const best = cur.value.result.best;
  return cur.value.result.rows.map((r: any) => ({ name: r.name, mean: r.ci?.[ck.value]?.mean ?? r.kpi[ck.value], lo: r.ci?.[ck.value]?.lo, hi: r.ci?.[ck.value]?.hi, highlight: r.name === best && r !== cur.value.result.rows[0] }));
});
const evalRows = computed(() => [...cur.value.result.evals].sort((a: any, b: any) => (b.i === cur.value.result.best?.i ? 1 : 0) - (a.i === cur.value.result.best?.i ? 1 : 0) || (b.front ? 1 : 0) - (a.front ? 1 : 0) || (b.feasible ? 1 : 0) - (a.feasible ? 1 : 0)));
const optCols = computed(() => [...new Set([...cur.value.result.objectives.map((o: any) => o.key), ...cur.value.result.constraints.map((c: any) => c.key), 'good_per_h', 'wip_avg', 'scrap_rate'])]);
const convOpt = computed(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 50, right: 14, top: 14, bottom: 30 },
  xAxis: { type: 'category', name: $t('experiments.candidates'), data: cur.value.result.history.map((x: any) => x.n) }, yAxis: { type: 'value', scale: true },
  series: [{ type: 'line', step: 'end', data: cur.value.result.history.map((x: any) => x.best), itemStyle: { color: CH.ok } },
    { type: 'scatter', symbolSize: 6, itemStyle: { color: CH.primary, opacity: 0.5 }, data: cur.value.result.evals.map((e: any) => e.kpi[cur.value.result.objectives[0].key]) }] }));
const combos = computed(() => nx.factors.reduce((n: number, f: any) => n * Math.max(1, levels(f.levelsText).length), nx.factors.length ? 1 : 0));
function levels(t: string) { return String(t || '').split(/[,\uff0c]/).map((x) => x.trim()).filter(Boolean).map((x) => (isFinite(+x) ? +x : x)); }

let timer: any;
async function load() { list.value = await get(api + '/experiments', true); if (cur.value && cur.value.status !== 'done' && cur.value.status !== 'failed') openExp(cur.value.id); }
async function openExp(id: number) {
  cur.value = await get(`${api}/experiments/${id}`, true); sel.value = null;
  if (cur.value.kind === 'optimize' && cur.value.result?.objectives) { px.value = cur.value.result.objectives[0]?.key; py.value = cur.value.result.objectives[1]?.key || 'wip_avg'; }
}
onMounted(async () => {
  await load(); if (list.value[0]) openExp(list.value[0].id);
  timer = setInterval(load, 3000);
  meta.value = await get(api + '/meta');
  const crew = meta.value.stations.find((s: any) => s.kind === 'crew'); roles.value = (crew?.cfg.roles || []).map((r: any) => r.name);
  roles.value.push(...meta.value.stations.filter((s: any) => s.kind === 'operators').map((s: any) => s.name));
  try { types.value = (await get('/api/catalog', true)).types || {}; } catch { /* ignore */ }
  versions.value = await get(api + '/versions', true).catch(() => []);
});
onUnmounted(() => clearInterval(timer));
watch(tab, (t) => { if (t === 'exp') load(); });
async function loadTags(sid: string) { if (sid && !tagsOf[sid]) { const s = await get(`${api}/station/${sid}`); tagsOf[sid] = Object.entries(s.tags).filter(([, x]: any) => x.w).map(([k]) => k); } }
function keysOf(sid: string) {
  const t = types.value[meta.value.stations.find((x: any) => x.id === sid)?.type];
  const out: Record<string, string> = {};
  if (t) for (const [k, p] of Object.entries<any>(t.params)) if (['num', 'int', 'expr'].includes(p.t)) out[k] = p.label;
  return Object.keys(out).length ? out : meta.value.editable;
}

// One row per change / factor / tunable parameter (shared target selector)
const CT: Record<string, string> = { param: $t('experiments.equipmentParameters'), add: $t('experiments.addEquipment'), remove: $t('experiments.removeEquipment'), setpoint: $t('experiments.setpoint'), crew: $t('experiments.staffingLevel'), buffer: $t('forkPanel.bufferCapacity'),
  version: $t('experiments.modelVersions'), plan: $t('experiments.planShift') };
const ChangeRow = defineComponent({
  props: { c: { type: Object, required: true }, factor: Boolean, opt: Boolean }, emits: ['del'],
  setup(p, { emit }) {
    const S = (n: string) => resolveComponent(n) as any;
    const sel = (model: string, opts: [string, string][], w: number, extra: any = {}) => h(S('ElSelect'), { modelValue: p.c[model], 'onUpdate:modelValue': (v: any) => { p.c[model] = v; extra.onChange?.(v); },
      size: 'small', filterable: true, style: `width:${w}px`, placeholder: extra.ph || '', allowCreate: extra.create }, () => opts.map(([k, l]) => h(S('ElOption'), { key: k, value: k, label: l })));
    const inp = (model: string, w: number, ph = '') => h(S('ElInput'), { modelValue: p.c[model], 'onUpdate:modelValue': (v: any) => (p.c[model] = v), size: 'small', style: `width:${w}px`, placeholder: ph });
    const num = (model: string, min = 0) => h(S('ElInputNumber'), { modelValue: p.c[model], 'onUpdate:modelValue': (v: any) => (p.c[model] = v), size: 'small', min });
    return () => {
      const c: any = p.c;
      const sts: [string, string][] = meta.value.stations.filter((s: any) => !['crew', 'agv'].includes(s.kind)).map((s: any) => [s.id, `${s.id} ${s.name}`]);
      const types_: [string, string][] = Object.entries(CT).filter(([k]) => !(p.factor && k === 'remove')).filter(([k]) => !(p.opt && k === 'setpoint'))
        .filter(([k]) => !((p.factor || p.opt) && (k === 'version' || k === 'plan'))) as any;
      const kids: any[] = [sel('type', types_, 110, { onChange: (t: string) => { if (t === 'plan') { c.preset = c.preset || 'two'; c.wd = c.wd || 'six'; setPlan(c); } } })];
      if (c.type === 'add') { kids.push(sel('template', sts, 170, { ph: $t('experiments.templateMachine') })); if (!p.factor) { kids.push(num('count', 1)); kids.push(h('span', { class: 'small' }, $t('experiments.machines'))); } }
      else if (c.type === 'remove') kids.push(sel('station', sts, 170));
      else if (c.type === 'param') { kids.push(sel('station', sts, 160)); kids.push(sel('key', Object.entries(keysOf(c.station)).map(([k, l]) => [k, $t('common.n012', [l, k])]) as any, 170, { ph: $t('common.parameters'), create: true })); if (!p.factor) kids.push(inp('value', 100, $t('common.value'))); }
      else if (c.type === 'setpoint') { kids.push(sel('station', sts, 160, { onChange: loadTags })); kids.push(sel('tag', (tagsOf[c.station] || []).map((t) => [t, t]) as any, 200)); if (!p.factor) kids.push(inp('value', 90, $t('common.value'))); }
      else if (c.type === 'crew') { kids.push(sel('role', roles.value.map((r) => [r, r]) as any, 170, { create: true })); if (!p.factor) kids.push(num('value', 0)); }
      else if (c.type === 'buffer') { kids.push(sel('name', Object.entries(meta.value.buffers).map(([k, n]) => [k, $t('forkPanel.n0Current1', [k, n])]) as any, 170)); if (!p.factor) kids.push(num('value', 1)); }
      else if (c.type === 'version') {
        kids.push(sel('n', [['draft', $t('experiments.currentDraftUnappliedChanges')], ...versions.value.map((v: any) => [v.n, $t('experiments.n0123Blocks', [v.n, v.note || '', String(v.t).slice(5, 16), v.blocks])])] as any, 330, { ph: $t('experiments.selectAModelVersion') }));
        kids.push(h('span', { class: 'small muted' }, $t('experiments.placeThisFirstToApply')));
      } else if (c.type === 'plan') {
        kids.push(sel('preset', Object.entries(SHIFT_PRESETS).map(([k, v]) => [k, v.label]) as any, 250, { onChange: () => setPlan(c) }));
        kids.push(sel('wd', Object.entries(WD_LABEL) as any, 120, { onChange: () => setPlan(c) }));
      }
      kids.push(h(S('ElButton'), { link: true, type: 'danger', onClick: () => emit('del') }, () => '×'));
      return h('div', { class: 'cr' }, kids);
    };
  },
});

function openNew() {
  const cnc = meta.value.stations.find((s: any) => ['cnc', 'processor'].includes(s.kind));
  Object.assign(nx, { name: $t('experiments.capacityImprovementComparison'), hours: 24, reps: 3, warmup_h: 3, seed: 42,
    variants: [{ name: $t('experiments.addOne') + (cnc?.name || ''), changes: [{ type: 'add', template: cnc?.id, count: 1 }] }],
    factors: [{ type: 'add', template: cnc?.id, levelsText: '0, 1, 2', label: $t('experiments.addEquipment2') }] });
  dlg.value = true;
}
function toFactor(f: any) {
  const o: any = { type: f.type, levels: levels(f.levelsText), label: f.label || undefined };
  for (const k of ['station', 'key', 'name', 'template', 'role', 'tag']) if (f[k] != null) o[k] = f[k];
  return o;
}
async function create() {
  busy.value = true;
  try {
    const body: any = { name: nx.name, hours: nx.hours, reps: nx.reps, warmup_h: nx.warmup_h, seed: nx.seed };
    if (mode.value === 'factors') { if (!combos.value) { ElMessage.error($t('experiments.enterTheFactorLevels')); return; } body.factors = nx.factors.map(toFactor); }
    else body.variants = nx.variants;
    const r = await post(api + '/experiments', body); dlg.value = false; ElMessage.success($t('experiments.evaluationStartedFor0Alternatives', [r.variants])); await load(); openExp(r.id);
  } finally { busy.value = false; }
}
function openOpt() {
  const cnc = meta.value.stations.find((s: any) => ['cnc', 'processor'].includes(s.kind));
  const buf = Object.keys(meta.value.buffers)[0];
  Object.assign(ox, { name: $t('experiments.capacityWipOptimization'), method: 'ga', budget: 24, pop: 8, hours: 8, reps: 1,
    params: [{ type: 'add', template: cnc?.id, lo: 0, hi: 2, step: 1 }, ...(buf ? [{ type: 'buffer', name: buf, lo: 10, hi: 50, step: 10 }] : [])],
    objectives: [{ key: 'good_per_h', sense: 'max' }, { key: 'wip_avg', sense: 'min' }], constraints: [{ key: 'scrap_rate', op: '<=', value: 0.05 }] });
  odlg.value = true;
}
async function createOpt() {
  busy.value = true;
  try {
    const params = ox.params.map((p: any) => {
      const o: any = { kind: p.type, lo: p.lo, hi: p.hi, step: p.step };
      for (const k of ['station', 'key', 'name', 'template', 'role']) if (p[k] != null) o[k] = p[k];
      const lv = levels(p.levelsText); if (lv.length) o.levels = lv;
      return o;
    });
    const r = await post(api + '/optimize', { ...ox, params }); odlg.value = false; ElMessage.success($t('experiments.optimizationStarted')); await load(); openExp(r.id);
  } finally { busy.value = false; }
}
async function fillSamples() {
  seeding.value = true;
  try {
    const r = await post(api + '/experiments/samples', {});
    ElMessage.success(r.added ? $t('experiments.added0ExampleExperiments', [r.added]) : $t('experiments.theExampleExperimentsAreAlready'));
    await load(); if (list.value[0]) openExp(list.value[0].id);
  } finally { seeding.value = false; }
}
async function rerun() {
  const c = cur.value;
  const body: any = { name: $t('experiments.n01Replications2', [c.name, q.value.recommended_reps]), hours: c.hours, reps: q.value.recommended_reps, variants: c.variants,
    seed: c.result?.design?.seed0 ?? 42 };
  if (c.result?.design?.warmup_h != null) body.warmup_h = c.result.design.warmup_h;
  const r = await post(api + '/experiments', body); ElMessage.success($t('experiments.evaluationRestartedWithTheRecommende')); await load(); openExp(r.id);
}
async function remove() { await del(`${api}/experiments/${cur.value.id}`); cur.value = null; load(); }
</script>

<style scoped>
.main { grid-template-columns: 300px minmax(0, 1fr); }
.list { max-height: calc(100vh - 190px); overflow: auto; } .it { padding: 8px; border-radius: 8px; border-bottom: 1px solid var(--hm-border); cursor: pointer; } .it:hover { background: var(--hm-surface-3); } .it.on { background: var(--hm-primary-soft); box-shadow: inset 3px 0 0 var(--hm-primary); }
.it b { margin-right: 6px; }
.kd { font-size: 11px; border-radius: 4px; padding: 0 5px; margin-right: 6px; background: var(--hm-setup-soft); color: var(--hm-setup-ink); } .kd.optimize { background: var(--hm-run-soft); color: var(--hm-run-ink); }
.detail { overflow-x: auto; }
.page-head .sub.one { flex: 1 1 0; min-width: 120px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.concl { background: var(--hm-surface-2); border: 1px solid var(--hm-border); color: var(--hm-text-2); border-radius: var(--hm-r-md); padding: 10px 12px; line-height: 1.8; }
.kbar { display: flex; align-items: center; gap: 6px; margin: 10px 0 4px; flex-wrap: wrap; }
.wrap { white-space: normal; } .reps { padding: 4px 12px 8px 40px; }
.qa { margin: 8px 0 4px; } .empty { line-height: 1.7; }
.vr { border: 1px solid var(--ln); border-radius: 8px; padding: 8px 10px; margin-bottom: 8px; } .vh { display: flex; align-items: center; margin-bottom: 6px; }
:deep(.cr) { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
h4 { margin: 12px 0 6px; font-size: 13.5px; } h4 small { font-weight: 400; }
@media (max-width: 900px) { .main { grid-template-columns: 1fr !important; } }
</style>

<style>
</style>
