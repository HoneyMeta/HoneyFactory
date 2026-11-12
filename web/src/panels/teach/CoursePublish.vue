<template>
  <div class="vp course-publish">
    <div class="cp-body">
      <div class="side">
        <div v-for="c in list" :key="c.id" class="vp-item" :class="{ on: sel === c.id }" @click="sel = c.id" :data-course="c.id">
          <div class="vp-row sp"><span class="t">{{ c.name }}</span><span class="vp-small vp-muted">{{ $t('coursePublish.n0Lessons', [c.lessons]) }}</span></div>
          <div class="vp-small vp-muted" style="margin-top: 3px">{{ c.classes.length ? $t('coursePublish.publishedTo') + c.classes.map((x: any) => x.class_name).join($t('common.k360')) : $t('coursePublish.notPublished') }}</div>
        </div>
      </div>
      <div class="main" v-if="course">
        <div class="vp-small" style="margin-bottom: 8px">{{ course.desc }}</div>
        <div v-for="ch in course.chapters" :key="ch.id" class="ch">
          <div class="chtitle">{{ ch.title }}</div>
          <div v-for="(l, i) in ch.lessons" :key="l.id" class="ln vp-small"><span class="kind" :class="l.kind">{{ KIND_CN[l.kind] }}</span>{{ l.title }}</div>
        </div>
      </div>
    </div>
    <div class="cp-foot">
      <el-form inline size="small" @submit.prevent>
        <el-form-item :label="$t('common.publishToClass')">
          <el-select v-model="classId" :placeholder="$t('common.selectClass')" style="width: 220px">
            <el-option v-for="c in classes" :key="c.id" :value="c.id" :label="$t('common.n01Members', [c.name, c.students])" />
          </el-select>
        </el-form-item>
        <el-form-item><el-switch v-model="openAll" :active-text="$t('coursePublish.openAllLessonsNoSequential')" /></el-form-item>
        <el-form-item><el-switch v-model="tutor" :active-text="$t('coursePublish.allowAiTutor')" /></el-form-item>
        <el-form-item :label="$t('common.deadline')">
          <el-date-picker v-model="due" type="datetime" value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:mm" :placeholder="$t('common.noTimeLimit')" clearable style="width: 180px" data-k="cp-due" />
        </el-form-item>
        <el-form-item :label="$t('common.correctAnswer')">
          <el-select v-model="reveal" style="width: 130px" data-k="cp-reveal"><el-option v-for="o in REVEAL_OPTS" :key="o.v" :value="o.v" :label="o.l" /></el-select>
        </el-form-item>
      </el-form>
      <div class="vp-small vp-muted" style="margin: -6px 0 6px" data-k="cp-reveal-hint">{{ $t('coursePublish.quizzesAndMultipleChoiceQuestions', [revealHint(reveal, due)]) }}</div>
      <div class="vp-row sp">
        <span class="vp-small vp-muted">{{ $t('coursePublish.publishingCreatesOneAssignmentPer') }}</span>
        <span>
          <el-button size="small" @click="emit('cancel')">{{ $t('common.cancel') }}</el-button>
          <el-button size="small" type="primary" :disabled="!sel || !classId" :loading="saving" @click="publish">{{ $t('common.publishCourse') }}</el-button>
        </span>
      </div>
      <div v-if="!classes.length" class="vp-small vp-fail" style="margin-top: 6px">{{ $t('coursePublish.noClassesYetCreateA') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref, watch } from 'vue';
import { get, post } from '../../api';
import { REVEAL_OPTS, revealHint, teachBus } from './util';
import './panel.css';

const props = defineProps<{ classId?: number; course?: string }>();
const emit = defineEmits<{ (e: 'done', v: { course: string; class_id: number }): void; (e: 'cancel'): void }>();
const KIND_CN: Record<string, string> = { cell: 'PLC', plant: $t('common.line'), diagnose: $t('common.troubleshooting'), quiz: $t('common.quiz'), point: $t('common.clickToSelect'), mes: 'MES' };
const list = ref<any[]>([]);
const classes = ref<any[]>([]);
const sel = ref(props.course || '');
const classId = ref<number | null>(props.classId || null);
const openAll = ref(false);
const tutor = ref(true);
const due = ref<string | null>(null);
const reveal = ref('submit');
const saving = ref(false);
const course = computed(() => list.value.find((c) => c.id === sel.value));

async function publish() {
  saving.value = true;
  try {
    const r = await post(`/api/teach/courses/${sel.value}/publish`, { class_id: classId.value, open_all: openAll.value, tutor: tutor.value, due: due.value || null, reveal: reveal.value });
    ElMessage.success(r.created ? $t('coursePublish.published0AssignmentsCreated', [r.created]) : $t('coursePublish.thisCourseWasAlreadyPublished'));
    emit('done', { course: sel.value, class_id: classId.value! });
  } finally { saving.value = false; }
}
watch(() => teachBus.classes, async () => { classes.value = await get('/api/teach/classes'); });
onMounted(async () => {
  [list.value, classes.value] = await Promise.all([get('/api/teach/courses'), get('/api/teach/classes')]);
  if (!sel.value && list.value.length) sel.value = list.value.find((c) => c.id === 'machining')?.id || list.value[0].id;
  if (!classId.value && classes.value.length === 1) classId.value = classes.value[0].id;
});
</script>

<style scoped>
.course-publish { background: transparent; }
.cp-body { display: flex; gap: 12px; height: 46vh; min-height: 300px; }
.cp-body .side { width: 240px; flex: none; overflow: auto; display: flex; flex-direction: column; gap: 6px; }
.cp-body .main { flex: 1; overflow: auto; border-left: 1px solid var(--el-border-color-lighter); padding-left: 12px; }
.chtitle { font-weight: 600; font-size: 13px; margin: 8px 0 4px; }
.ln { padding: 2px 0; display: flex; gap: 6px; align-items: center; }
.kind { font-size: 11px; padding: 0 5px; border-radius: 3px; background: var(--el-fill-color); color: var(--el-text-color-secondary); }
.kind.plant { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.kind.diagnose { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
.cp-foot { border-top: 1px solid var(--el-border-color-lighter); padding-top: 10px; margin-top: 10px; }
</style>
