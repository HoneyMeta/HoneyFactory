<template>
  <div class="vp lesson-wizard">
    <el-steps :active="step" finish-status="success" simple style="margin-bottom: 12px">
      <el-step :title="$t('lessonWizard.selectClass')" /><el-step :title="$t('lessonWizard.studentRoster')" /><el-step :title="$t('lessonWizard.selectCourseAndPublish')" />
    </el-steps>

    <div v-if="step === 0" class="lw-pane">
      <el-radio-group v-model="mode" style="margin-bottom: 10px">
        <el-radio value="old" :disabled="!classes.length">{{ $t('lessonWizard.useAnExistingClass') }}</el-radio><el-radio value="new">{{ $t('classManager.newClass') }}</el-radio>
      </el-radio-group>
      <div v-if="mode === 'old'">
        <div class="vp-list">
          <div v-for="c in classes" :key="c.id" class="vp-item" :class="{ on: classId === c.id }" @click="classId = c.id">
            <div class="t">{{ c.name }}</div><div class="vp-small vp-muted">{{ $t('lessonWizard.students0Assignments1', [c.students, c.assignments]) }}</div>
          </div>
        </div>
      </div>
      <el-input v-else v-model="newName" :placeholder="$t('lessonWizard.classNameEGElectrical')" style="width: 360px" />
    </div>

    <div v-else-if="step === 1" class="lw-pane">
      <div v-if="cls?.students" class="vp-small" style="margin-bottom: 8px">{{ $t('lessonWizard.thisClassAlreadyHas0', [cls.students]) }}</div>
      <div class="vp-small vp-muted" style="margin-bottom: 6px">{{ $t('lessonWizard.copyTheStudentIdAnd') }}</div>
      <el-input v-model="csv" type="textarea" :rows="7" :placeholder="$t('lessonWizard.studentIdNameS2026001Zhang')" @input="schedulePreview" />
      <div class="vp-row" style="margin-top: 6px">
        <el-button size="small" :disabled="!csv.trim()" @click="doPreview">{{ $t('classManager.preview') }}</el-button>
        <span v-if="preview" class="vp-small">{{ $t('lessonWizard.created0Added1Already', [preview.counts.new || 0, preview.counts.exists || 0, preview.counts.in_class || 0]) }}
          <span :class="{ 'vp-fail': preview.counts.error }">{{ $t('classManager.n0WithIssues', [preview.counts.error || 0]) }}</span></span>
        <span v-if="imported" class="vp-small vp-pass">{{ $t('lessonWizard.studentsImported0', [imported.added]) }}</span>
      </div>
      <div v-if="preview" class="prev-wrap"><table class="vp-tbl">
        <tr v-for="r in preview.rows" :key="r.line" :class="'st-' + r.status"><td class="num">{{ r.line }}</td><td class="mono">{{ r.username }}</td><td>{{ r.name }}</td><td class="vp-small">{{ r.msg || $t('classManager.createAccount') }}</td></tr>
      </table></div>
    </div>

    <div v-else class="lw-pane">
      <CoursePublish :class-id="classId!" @done="emit('done', $event)" @cancel="emit('cancel')" />
    </div>

    <div v-if="step < 2" class="vp-row sp lw-foot">
      <el-button size="small" @click="emit('cancel')">{{ $t('common.cancel') }}</el-button>
      <span>
        <el-button size="small" :disabled="step === 0" @click="step--">{{ $t('common.back') }}</el-button>
        <el-button v-if="step === 1 && preview && !imported" size="small" type="primary" plain :loading="busy" @click="doImport">{{ $t('classManager.importRoster') }}</el-button>
        <el-button size="small" type="primary" :disabled="!canNext" :loading="busy" @click="next">{{ $t('common.next') }}</el-button>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Teacher "Start a Lesson" wizard: select/create class → paste roster → select and publish course; three steps, ending at the course overview.
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { get, post } from '../../api';
import CoursePublish from './CoursePublish.vue';
import { classesChanged } from './util';
import './panel.css';

const emit = defineEmits<{ (e: 'done', v: { course: string; class_id: number }): void; (e: 'cancel'): void }>();
const step = ref(0);
const classes = ref<any[]>([]);
const mode = ref('new');
const classId = ref<number | null>(null);
const newName = ref('');
const csv = ref('');
const preview = ref<any>(null);
const imported = ref<any>(null);
const busy = ref(false);
const cls = computed(() => classes.value.find((c) => c.id === classId.value));
const canNext = computed(() => (step.value === 0 ? (mode.value === 'old' ? !!classId.value : !!newName.value.trim()) : !!(cls.value?.students || imported.value?.added)));

// Auto-preview after pasting (after half a second of inactivity), so teachers need not click "Preview".
let pvTimer: any = null;
function schedulePreview() {
  preview.value = null;
  clearTimeout(pvTimer);
  pvTimer = setTimeout(() => { if (csv.value.trim()) doPreview(); }, 500);
}
async function doPreview() { preview.value = await post(`/api/teach/classes/${classId.value}/roster`, { csv: csv.value, preview: true }); }
async function doImport() {
  busy.value = true;
  try {
    imported.value = await post(`/api/teach/classes/${classId.value}/roster`, { csv: csv.value });
    ElMessage.success($t('lessonWizard.studentsImported0', [imported.value.added]));
    classes.value = await get('/api/teach/classes');
    classesChanged();
  } finally { busy.value = false; }
}
async function next() {
  busy.value = true;
  try {
    if (step.value === 0 && mode.value === 'new') {
      const r = await post('/api/teach/classes', { name: newName.value.trim() });
      classesChanged();
      classes.value = await get('/api/teach/classes');
      classId.value = r.id; mode.value = 'old';
    }
    step.value++;
  } finally { busy.value = false; }
}
onMounted(async () => {
  classes.value = await get('/api/teach/classes');
  if (classes.value.length) { mode.value = 'old'; classId.value = classes.value[classes.value.length - 1].id; }
});
</script>

<style scoped>
.lw-pane { min-height: 300px; }
.lw-foot { border-top: 1px solid var(--el-border-color-lighter); padding-top: 10px; margin-top: 10px; }
.prev-wrap { max-height: 200px; overflow: auto; margin-top: 6px; }
.st-error td { background: var(--el-color-danger-light-9); color: var(--bad, var(--el-color-danger)); }
</style>
