<template>
  <div class="vp publish-wizard">
    <div class="vp-row kind-row">
      <span class="vp-small vp-muted">{{ $t('publishWizard.assignmentType') }}</span>
      <el-radio-group v-model="form.kind" size="small" :disabled="step > 0" data-k="pw-kind">
        <el-radio-button value="cell">{{ $t('publishWizard.plcLabScenarioLibrary') }}</el-radio-button>
        <el-radio-button value="factory">{{ $t('publishWizard.submitAFactoryFactoryDesign') }}</el-radio-button>
      </el-radio-group>
      <span class="vp-small vp-muted">{{ form.kind === 'factory' ? $t('publishWizard.studentsBuildAFactoryIn') : $t('publishWizard.studentsWritePlcProgramsIn') }}</span>
    </div>
    <el-steps :active="step" finish-status="success" simple style="margin-bottom: 12px">
      <el-step :title="factory ? $t('publishWizard.defineRequirements') : $t('publishWizard.selectScenario')" /><el-step :title="$t('publishWizard.classSchedule')" /><el-step :title="factory ? $t('common.automatedChecks') : $t('publishWizard.faultsAssistance')" /><el-step :title="$t('publishWizard.confirmPublication')" />
    </el-steps>

    <!-- Factory submission: requirements (markdown, preview on the right) -->
    <div v-show="step === 0 && factory" class="pw-pane pw-scene" data-k="pw-factory-brief">
      <div class="left wide">
        <el-input v-model="form.title" size="small" :placeholder="$t('publishWizard.assignmentNameEGDesign')" maxlength="80" style="margin-bottom: 6px" data-k="pw-title" />
        <el-input v-model="form.brief_md" type="textarea" :rows="14" resize="none" :placeholder="$t('publishWizard.requirementsMarkdownSupportedHeading')" data-k="pw-brief" />
        <div class="vp-small vp-muted" style="margin-top: 4px">{{ $t('publishWizard.specifyWhatTheFactoryShould') }}</div>
      </div>
      <div class="right">
        <div class="vp-small vp-muted" style="margin-bottom: 4px">{{ $t('publishWizard.studentPreview') }}</div>
        <div class="vp-md" v-html="md(form.brief_md || $t('publishWizard.noRequirementsYet'))" />
      </div>
    </div>

    <div v-show="step === 0 && !factory" class="pw-pane pw-scene">
      <div class="left">
        <el-input v-model="kw" size="small" :placeholder="$t('publishWizard.searchScenarios')" clearable style="margin-bottom: 6px" />
        <div v-if="!scenes.length" class="vp-empty">{{ $t('publishWizard.theScenarioLibraryIsEmpty') }}</div>
        <div class="vp-list scene-list">
          <div v-for="s in shown" :key="s.id" class="vp-item" :class="{ on: form.scene === s.id }" @click="pickScene(s)" :data-scene="s.id">
            <div class="vp-row sp"><span class="t"><el-icon v-if="form.scene === s.id" class="vp-pass"><CircleCheckFilled /></el-icon>{{ s.level !== null && s.level !== undefined ? s.level + '. ' : '' }}{{ s.name }}</span></div>
            <div class="vp-small vp-muted">{{ $t('publishWizard.n0IO1Failure', [s.io_count, s.faults.length, s.has_reference ? $t('publishWizard.referenceSolutionIncluded') : '']) }}</div>
            <div class="vp-small" v-if="s.error" style="color: var(--el-color-danger)">{{ $t('publishWizard.invalidScenarioFile0', [s.error]) }}</div>
          </div>
        </div>
      </div>
      <div class="right">
        <div v-if="!detail" class="vp-empty">{{ $t('publishWizard.selectAScenarioToView') }}</div>
        <template v-else>
          <div v-if="detail.warnings?.length" class="warn vp-small">
            <b>{{ $t('publishWizard.prePublishChecks') }}</b><div v-for="w in detail.warnings" :key="w">· {{ w }}</div>
          </div>
          <el-tabs v-model="dtab">
            <el-tab-pane :label="$t('common.assignmentBrief')" name="md"><div class="vp-md" v-html="md(detail.task_md || '')" /></el-tab-pane>
            <el-tab-pane :label="$t('publishWizard.grading0Criteria', [detail.rules.length])" name="rules">
              <table class="vp-tbl"><tr><th>{{ $t('courseEditor.criterion') }}</th><th>{{ $t('publishWizard.requirements') }}</th><th class="num">{{ $t('publishWizard.points') }}</th></tr>
                <tr v-for="r in detail.rules" :key="r.key"><td>{{ r.label || r.key }}</td><td>{{ humanRule(r) }}</td><td class="num">{{ r.weight }}</td></tr></table>
            </el-tab-pane>
            <el-tab-pane :label="$t('publishWizard.iO0', [detail.io.length])" name="io">
              <table class="vp-tbl"><tr><th>{{ $t('common.name') }}</th><th>{{ $t('common.direction') }}</th><th>{{ $t('common.address') }}</th><th>{{ $t('common.description') }}</th></tr>
                <tr v-for="e in detail.io" :key="e.name"><td class="mono">{{ e.name }}</td><td>{{ e.dir === 'in' ? $t('common.input') : $t('common.output') }}</td><td class="mono">{{ e.addr }}</td><td class="vp-muted">{{ e.desc || e.comment || '' }}</td></tr></table>
            </el-tab-pane>
            <el-tab-pane :label="$t('publishWizard.hints0', [detail.hints.length])" name="hints">
              <div v-for="(h, i) in detail.hints" :key="i" class="vp-card vp-small" style="margin-bottom: 6px"><b>{{ $t('publishWizard.hint0', [i + 1]) }}</b><div class="vp-md" v-html="md(h)" /></div>
              <div v-if="!detail.hints.length" class="vp-muted vp-small">{{ $t('publishWizard.thisScenarioHasNoHints') }}</div>
            </el-tab-pane>
          </el-tabs>
        </template>
      </div>
    </div>

    <div v-show="step === 1" class="pw-pane">
      <el-form label-width="110px" size="small">
        <el-form-item :label="$t('opsApp.class')">
          <el-select v-model="form.class_id" :placeholder="$t('common.selectClass')" style="width: 260px">
            <el-option v-for="c in classes" :key="c.id" :value="c.id" :label="$t('common.n01Members', [c.name, c.students])" />
          </el-select>
          <span v-if="!classes.length" class="vp-small vp-muted" style="margin-left: 8px">{{ $t('publishWizard.noClassesYetCreateOne') }}</span>
        </el-form-item>
        <el-form-item :label="$t('publishWizard.assignmentName')"><el-input v-model="form.title" style="width: 360px" /></el-form-item>
        <el-form-item :label="$t('publishWizard.startTime')">
          <el-date-picker v-model="form.start_at" type="datetime" value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:mm" :placeholder="$t('publishWizard.startNow')" clearable />
          <span class="vp-small vp-muted" style="margin-left: 8px">{{ $t('publishWizard.studentsCannotSeeThisAssignment') }}</span>
        </el-form-item>
        <el-form-item :label="$t('common.deadline')">
          <el-date-picker v-model="form.due" type="datetime" value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:mm" :placeholder="$t('common.noTimeLimit')" clearable />
          <el-checkbox v-model="form.allow_late" style="margin-left: 12px">{{ $t('publishWizard.allowSubmissionsAfterTheDeadline') }}</el-checkbox>
        </el-form-item>
        <el-form-item :label="$t('publishWizard.submissionLimit')">
          <el-input-number v-model="form.max_subs" :min="0" :max="100" controls-position="right" style="width: 120px" />
          <span class="vp-small vp-muted" style="margin-left: 8px">{{ $t('publishWizard.n0Unlimited') }}</span>
        </el-form-item>
        <el-form-item :label="$t('publishWizard.gradingRubric')"><el-checkbox v-model="form.show_details">{{ $t('publishWizard.studentsCanSeeTheResult', [factory ? $t('publishWizard.check') : $t('courseEditor.criterion')]) }}</el-checkbox></el-form-item>
        <el-form-item :label="$t('common.correctAnswer')">
          <el-select v-model="form.reveal" style="width: 160px" data-k="pw-reveal">
            <el-option v-for="o in REVEAL_OPTS" :key="o.v" :value="o.v" :label="o.l" />
          </el-select>
          <span class="vp-small vp-muted" style="margin-left: 8px">{{ revealHint(form.reveal, form.due) }}</span>
        </el-form-item>
        <el-form-item :label="$t('common.description')"><el-input v-model="form.descr" type="textarea" :rows="3" :placeholder="$t('publishWizard.optionalAdditionalInstructionsForStu')" style="width: 460px" /></el-form-item>
      </el-form>
    </div>

    <!-- Factory submission: deterministic automated checks (the same factory always yields the same results) -->
    <div v-show="step === 2 && factory" class="pw-pane" data-k="pw-checks">
      <div class="vp-small vp-muted" style="margin-bottom: 8px">{{ $t('publishWizard.selectedAutomaticChecksAreWeighted') }}</div>
      <div class="chk"><el-checkbox v-model="chk.valid" data-k="chk-valid">{{ $t('publishWizard.modelValidationPassesWithNo') }}</el-checkbox></div>
      <div class="chk">
        <el-checkbox v-model="chk.blocksOn" data-k="chk-blocks">{{ $t('publishWizard.requiredEquipment') }}</el-checkbox>
        <div v-if="chk.blocksOn" class="chk-sub">
          <div v-for="(b, i) in chk.blocks" :key="i" class="vp-row" style="margin-bottom: 4px">
            <el-select v-model="b.type" size="small" filterable :placeholder="$t('publishWizard.equipmentType')" style="width: 200px" :data-k="'chk-type-' + i">
              <el-option-group v-for="g in typeGroups" :key="g.name" :label="g.name">
                <el-option v-for="t in g.items" :key="t.type" :value="t.type" :label="t.label" />
              </el-option-group>
            </el-select>
            <span class="vp-small">{{ $t('publishWizard.atLeast') }}</span><el-input-number v-model="b.min" :min="1" :max="99" size="small" controls-position="right" style="width: 90px" /><span class="vp-small">{{ $t('experiments.machines') }}</span>
            <el-button size="small" text @click="chk.blocks.splice(i, 1)"><el-icon><Delete /></el-icon></el-button>
          </div>
          <el-button size="small" text type="primary" @click="chk.blocks.push({ type: '', min: 1 })"><el-icon><Plus /></el-icon>{{ $t('publishWizard.addEquipmentType') }}</el-button>
        </div>
      </div>
      <div class="chk vp-row">
        <el-checkbox v-model="chk.plcOn" data-k="chk-plc">{{ $t('publishWizard.onePlcMustControlAt') }}</el-checkbox>
        <el-input-number v-model="chk.plcMin" :min="1" :max="99" size="small" controls-position="right" style="width: 90px" :disabled="!chk.plcOn" /><span class="vp-small">{{ $t('publishWizard.machinesViaSignalWires') }}</span>
      </div>
      <div class="chk vp-row">
        <el-checkbox v-model="chk.goodOn" data-k="chk-good">{{ $t('publishWizard.minimumGoodPartsAfterSimulation') }}</el-checkbox>
        <el-input-number v-model="chk.goodMin" :min="1" :max="10000000" size="small" controls-position="right" style="width: 120px" :disabled="!chk.goodOn" /><span class="vp-small">{{ $t('common.pcs') }}</span>
      </div>
      <div class="chk vp-row">
        <el-checkbox v-model="chk.oeeOn" data-k="chk-oee">{{ $t('publishWizard.afterSimulationEquipment') }}</el-checkbox>
        <el-input v-model="chk.oeeBlock" size="small" :placeholder="$t('publishWizard.idOrNameEG')" style="width: 150px" :disabled="!chk.oeeOn" />
        <span class="vp-small">{{ $t('publishWizard.mustHaveAnOeeOf') }}</span><el-input-number v-model="chk.oeeMin" :min="1" :max="100" size="small" controls-position="right" style="width: 90px" :disabled="!chk.oeeOn" /><span class="vp-small">%</span>
      </div>
      <div class="chk vp-row" v-if="chk.goodOn || chk.oeeOn">
        <span class="vp-small">{{ $t('experiments.simulationDuration') }}</span><el-input-number v-model="chk.hours" :min="0.5" :max="24" :step="0.5" size="small" controls-position="right" style="width: 100px" /><span class="vp-small">{{ $t('publishWizard.hoursFixedRandomSeedFor') }}</span>
      </div>
    </div>

    <div v-show="step === 2 && !factory" class="pw-pane">
      <el-form label-width="96px" size="small">
        <el-form-item :label="$t('common.hint')"><el-switch v-model="form.hints" :active-text="$t('publishWizard.showStudentsTheScenarioS')" />
          <span v-if="detail?.hints?.length" class="vp-small vp-muted" style="margin-left: 8px">{{ $t('publishWizard.total0PreviewInThe', [detail.hints.length]) }}</span></el-form-item>
        <el-form-item :label="$t('common.aiTutor')"><el-switch v-model="form.tutor" :active-text="$t('publishWizard.allowStudentsToAskThe')" /></el-form-item>
        <el-form-item :label="$t('publishWizard.injectableFailures')">
          <div class="vp-small vp-muted" style="width: 100%">{{ $t('publishWizard.selectFailuresYouCanInject') }}</div>
          <el-checkbox-group v-model="faultSel">
            <div v-for="(f, i) in sceneFaults" :key="i"><el-checkbox :value="i">{{ faultLabel(f) }}</el-checkbox></div>
          </el-checkbox-group>
          <div v-if="!sceneFaults.length" class="vp-small vp-muted">{{ $t('publishWizard.thisScenarioHasNoInjectable') }}</div>
        </el-form-item>
        <el-form-item :label="$t('publishWizard.initialFailures')">
          <div class="vp-small vp-muted" style="width: 100%">{{ $t('publishWizard.troubleshootingTaskTheseFailuresAre') }}</div>
          <el-checkbox-group v-model="startSel">
            <div v-for="(f, i) in sceneFaults" :key="i"><el-checkbox :value="i">{{ faultLabel(f) }}</el-checkbox></div>
          </el-checkbox-group>
        </el-form-item>
      </el-form>
    </div>

    <div v-show="step === 3" class="pw-pane">
      <div class="vp-kv confirm">
        <span>{{ $t('common.type') }}</span><span>{{ factory ? $t('publishWizard.submitAFactoryFactoryDesign') : $t('common.plcLab') }}</span>
        <template v-if="!factory"><span>{{ $t('common.scenario') }}</span><span>{{ scene?.name }}</span></template>
        <span>{{ $t('opsApp.class') }}</span><span>{{ classes.find((c) => c.id === form.class_id)?.name || '—' }}</span>
        <span>{{ $t('publishWizard.assignmentName') }}</span><span>{{ form.title }}</span>
        <span>{{ $t('common.time') }}</span><span>{{ form.start_at || $t('publishWizard.startNow') }} → {{ form.due || $t('common.noTimeLimit') }}{{ form.due ? (form.allow_late ? $t('publishWizard.lateSubmissionsAllowed') : $t('publishWizard.noLateSubmissions')) : '' }}</span>
        <span>{{ $t('publishWizard.submissions') }}</span><span>{{ form.max_subs || $t('common.unrestricted') }}{{ form.show_details ? '' : $t('publishWizard.totalScoreOnly') }}</span>
        <span>{{ $t('common.correctAnswer') }}</span><span>{{ REVEAL_OPTS.find((o) => o.v === form.reveal)?.l }}</span>
        <template v-if="factory">
          <span>{{ $t('common.automatedChecks') }}</span><span>{{ checkList.length ? checkList.map((c) => c.label).join($t('common.k344')) : $t('publishWizard.noneManualGradingOnly') }}</span>
        </template>
        <template v-else>
          <span>{{ $t('publishWizard.hintsAiTutor') }}</span><span>{{ form.hints ? $t('publishWizard.showHints') : $t('publishWizard.hideHints') }} / {{ form.tutor ? $t('operatorPanel.on') : $t('operatorPanel.off') }}</span>
          <span>{{ $t('publishWizard.injectableFailures') }}</span><span>{{ faultSel.map((i) => faultLabel(sceneFaults[i])).join($t('common.k360')) || $t('common.none') }}</span>
          <span>{{ $t('publishWizard.initialFailures') }}</span><span>{{ startSel.map((i) => faultLabel(sceneFaults[i])).join($t('common.k360')) || $t('common.none') }}</span>
        </template>
      </div>
      <div v-if="!factory && detail?.warnings?.length" class="warn vp-small" style="margin-top: 10px">{{ $t('publishWizard.thereAre0PrePublish', [detail.warnings.length]) }}</div>
      <div class="vp-small vp-muted" style="margin-top: 10px">{{ factory ? $t('publishWizard.afterPublishingStudentsWillSee')
        : $t('publishWizard.afterPublishingStudentsWillSee2') }}</div>
    </div>

    <div class="vp-row sp pw-foot">
      <el-button size="small" @click="emit('cancel')">{{ $t('common.cancel') }}</el-button>
      <span>
        <el-button size="small" :disabled="step === 0" @click="step--">{{ $t('common.back') }}</el-button>
        <el-button v-if="step < 3" size="small" type="primary" :disabled="!canNext" data-k="pw-next" @click="step++">{{ $t('common.next') }}</el-button>
        <el-button v-else size="small" type="primary" :loading="saving" data-k="pw-publish" @click="publish">{{ $t('courseEditor.publish') }}</el-button>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { get, post } from '../../api';
import { md } from '../../editor/md';
import { faultLabel, humanRule, REVEAL_OPTS, revealHint, teachBus } from './util';
import './panel.css';

const props = defineProps<{ classId?: number; kind?: string }>();
const emit = defineEmits<{ (e: 'done', id: number): void; (e: 'cancel'): void }>();
const step = ref(0);
const scenes = ref<any[]>([]);
const classes = ref<any[]>([]);
const types = ref<any[]>([]);
const kw = ref('');
const saving = ref(false);
const detail = ref<any>(null);
const dtab = ref('md');
const BRIEF = $t('publishWizard.requirementsBuildASmallFactory');
const form = reactive<any>({ kind: props.kind || 'cell', scene: '', class_id: props.classId || null, title: '', due: null, start_at: null, descr: '', hints: true, tutor: true,
  allow_late: true, max_subs: 0, show_details: true, reveal: 'submit', brief_md: BRIEF });
const chk = reactive<any>({ valid: true, blocksOn: false, blocks: [{ type: 'plc', min: 1 }], plcOn: false, plcMin: 1, goodOn: false, goodMin: 100, oeeOn: false, oeeBlock: '', oeeMin: 60, hours: 8 });
const faultSel = ref<number[]>([]);
const startSel = ref<number[]>([]);
const factory = computed(() => form.kind === 'factory');
const scene = computed(() => scenes.value.find((s) => s.id === form.scene));
const sceneFaults = computed(() => scene.value?.faults || []);
const shown = computed(() => scenes.value.filter((s) => !kw.value || (s.name + s.id + (s.desc || '')).includes(kw.value)));
const typeName = (t: string) => types.value.find((x) => x.type === t)?.label || t;
const typeGroups = computed(() => {
  const m: Record<string, any[]> = {};
  for (const t of types.value) (m[t.cat || $t('common.other')] ||= []).push(t);
  return Object.entries(m).map(([name, items]) => ({ name, items }));
});
/** Selected automated checks → server checks (vfactory/teach/factory.py format); label is for the confirmation page only. */
const checkList = computed(() => {
  const out: any[] = [];
  if (chk.valid) out.push({ kind: 'valid', label: $t('publishWizard.modelCheckFoundNoErrors') });
  if (chk.blocksOn) for (const b of chk.blocks) if (b.type) out.push({ kind: 'block', type: b.type, min: b.min, label: $t('publishWizard.n0Count1Units', [typeName(b.type), b.min]) });
  if (chk.plcOn) out.push({ kind: 'plc_control', min: chk.plcMin, label: $t('publishWizard.plcControls0Machines', [chk.plcMin]) });
  if (chk.goodOn) out.push({ kind: 'good', min: chk.goodMin, label: $t('publishWizard.goodPartsAfter0Hours', [chk.hours, chk.goodMin]) });
  if (chk.oeeOn && chk.oeeBlock) out.push({ kind: 'oee', block: chk.oeeBlock, min: chk.oeeMin, label: $t('publishWizard.oeeOf01', [chk.oeeBlock, chk.oeeMin]) });
  return out;
});
const canNext = computed(() => (step.value === 0 ? (factory.value ? !!form.title.trim() && !!form.brief_md.trim() : !!form.scene)
  : step.value === 1 ? !!form.class_id && !!form.title : step.value === 2 && factory.value ? !(chk.oeeOn && !chk.oeeBlock) : true));

async function pickScene(s: any) {
  if (s.error) return;
  form.scene = s.id;
  form.title = s.name;
  faultSel.value = s.faults.map((_: any, i: number) => i);
  startSel.value = [];
  detail.value = await get(`/api/teach/scenes/${s.id}`);
  dtab.value = detail.value.warnings?.length ? 'rules' : 'md';
}
async function publish() {
  saving.value = true;
  try {
    let r: any;
    if (factory.value) {
      const { kind, class_id, title, due, start_at, descr, allow_late, max_subs, show_details, reveal, brief_md } = form;
      r = await post('/api/teach/assignments', { kind, class_id, title, due, start_at, descr, allow_late, show_details, reveal, brief_md, max_subs: max_subs || null,
        checks: checkList.value.map(({ label: _l, ...c }) => c), hours: chk.hours });
    } else {
      const f = sceneFaults.value;
      r = await post('/api/teach/assignments', { ...form, kind: undefined, brief_md: undefined, max_subs: form.max_subs || null, faults: faultSel.value.map((i) => f[i]),
        start_faults: startSel.value.map((i) => f[i]) });
    }
    ElMessage.success($t('publishWizard.published'));
    emit('done', r.id);
  } finally { saving.value = false; }
}
async function loadClasses() {
  classes.value = await get('/api/teach/classes');
  if (!form.class_id && classes.value.length === 1) form.class_id = classes.value[0].id;
}
watch(() => teachBus.classes, loadClasses);
watch(step, (s) => { if (s === 1) loadClasses(); });
watch(() => form.kind, (k) => { if (k === 'factory' && !form.title) form.title = $t('publishWizard.factoryDesignAssignment'); if (k === 'cell' && form.title === $t('publishWizard.factoryDesignAssignment')) form.title = ''; });
onMounted(async () => {
  if (form.kind === 'factory' && !form.title) form.title = $t('publishWizard.factoryDesignAssignment');
  scenes.value = await get('/api/teach/scenes');
  types.value = (await get('/api/teach/factory/types', true).catch(() => ({ types: [] }))).types || [];
  await loadClasses();
});
</script>

<style scoped>
.publish-wizard { background: transparent; }
.kind-row { margin-bottom: 10px; }
.pw-pane { min-height: 340px; max-height: 56vh; overflow: auto; }
.pw-scene { display: flex; gap: 12px; }
.pw-scene .left { width: 260px; flex: none; display: flex; flex-direction: column; min-height: 0; }
.pw-scene .left.wide { width: 52%; }
.pw-scene .right { flex: 1; min-width: 0; overflow: auto; border-left: 1px solid var(--el-border-color-lighter); padding-left: 12px; }
.scene-list { overflow: auto; }
.warn { background: var(--el-color-warning-light-9); border: 1px solid var(--el-color-warning-light-5); border-radius: 5px; padding: 6px 10px; margin-bottom: 6px; }
.pw-foot { border-top: 1px solid var(--el-border-color-lighter); padding-top: 10px; margin-top: 10px; }
.confirm { font-size: 13px; gap: 8px 16px; }
.chk { margin-bottom: 10px; }
.chk-sub { margin: 6px 0 0 24px; }
</style>
