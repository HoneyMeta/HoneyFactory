<template>
  <div class="teach-page" :class="{ learner, studio: area === 'courses' && !learner }" :data-help="learner || area === 'courses' ? 'course' : 'teach'">
    <!-- Teachers in the desktop client: double-click .vfhw or select a file here to run a student's assignment package in a local review sandbox (students use "Open Assignment Package" on the Courses page) -->
    <div v-if="desk.on && !learner && area === 'teach'" class="tp-tools">
      <input ref="pkgFile" type="file" accept=".vfhw,.vfplant" style="display: none" @change="pickPkg" />
      <el-button size="small" data-k="teach-open-pkg" @click="pkgFile?.click()"><el-icon><FolderOpened /></el-icon>{{ $t('common.openAssignmentPackage') }}</el-button>
      <span class="vp-small vp-muted">{{ $t('teach.openAVfhwFileExported') }}</span>
      <PackageOpen ref="pkgEl" v-model="pkgDlg" />
    </div>

    <!-- Students (including standalone desktop client): "Courses": course cards → course details (drawer) → lesson (course chapters on the left, lesson on the right) -->
    <template v-if="learner">
      <!-- 5.0 Honey Cloud web: assignments run in the desktop client (factories run on students' computers); only courses and grades are shown here -->
      <div v-if="saasWeb" class="saas-learner" data-k="learner-saas-banner"><el-icon><Monitor /></el-icon>
        <span>{{ $t('teach.honeyCloudCompleteAssignmentsIn') }}</span></div>
      <el-dialog v-model="clientOpen" :title="$t('teach.completeThisLessonInThe')" width="min(680px, 96vw)" append-to-body data-k="lesson-client-dialog">
        <ClientLink :path="clientPath" :title="$t('teach.openThisLessonInThe')" :steps="$t('teach.theDesktopClientInstallsThis')" />
      </el-dialog>
      <CourseHome v-if="view === 'home'" ref="homeEl" @open-course="openCourse" @open-lesson="openLesson" @own-package="ownPkg" />
      <div v-else class="lesson-wrap"><div class="tp-box full"><TaskPanel :key="lessonKey" split :focus="focus" :initial-aid="lessonAid" :auto-enter="autoEnter" @home="goHome" /></div></div>
      <el-drawer v-model="detailOpen" :size="drawerSize" :with-header="false" append-to-body class="course-drawer" data-k="course-drawer">
        <CourseDetail v-if="detail" :course="detail" @open="(aid: number) => openLesson(aid, detail.class_id + ':' + detail.course)" />
      </el-drawer>
      <PasswordDialog v-model="pwOpen" :title="$t('teach.changeYourPasswordFirst')" :later-text="$t('common.maybeLater')" :intro="$t('teach.youAreUsingTheInitial')" @later="pwLater" />
    </template>

    <!-- Teacher "Courses": course authoring, course library, preview -->
    <template v-else-if="area === 'courses'">
      <CourseStudio v-if="!editId" ref="studioEl" @edit="(id: string) => (editId = id)" />
      <div v-else-if="!pv" class="ce-wrap"><CourseEditor :id="editId" @back="editId = ''" @preview="(v: any) => (pv = v)" @published="() => undefined" /></div>
      <div v-else class="pv-wrap" data-k="course-preview">
        <div class="pv-bar"><el-button size="small" text @click="pv = null; pvAid = 0"><el-icon><Back /></el-icon>{{ $t('teach.backToEditor') }}</el-button>
          <b>{{ $t('teach.preview0', [pv.name]) }}</b><span class="vp-small vp-muted">{{ $t('teach.tryTheLessonAsA') }}</span></div>
        <div class="pv-main">
          <div class="pv-detail"><CourseDetail :course="pv" @open="(aid: number) => (pvAid = aid)" /></div>
          <div class="pv-lesson tp-box">
            <TaskPanel v-if="pvAid" :key="'pv' + pvAid" :initial-aid="pvAid" no-map />
            <div v-else class="vp-empty pv-pick"><el-icon :size="34"><Reading /></el-icon><div>{{ $t('teach.selectALessonOnThe') }}</div></div>
          </div>
        </div>
      </div>
    </template>

    <!-- Teacher "Teaching": classes, assignments, submissions and grading -->
    <template v-else>
      <div class="page-head tp-head"><h2>{{ $t('common.teaching') }}</h2><span class="sub">{{ $t('teach.manageClassesRostersIndividualAssign') }}</span></div>
    <el-tabs v-model="tab" class="tp-tabs">
      <el-tab-pane :label="$t('common.teacherConsole')" name="console"><div class="tp-box"><TeacherConsole /></div></el-tab-pane>
      <el-tab-pane :label="$t('common.classesRosters')" name="classes"><div class="tp-box"><ClassManager /></div></el-tab-pane>
      <el-tab-pane :label="$t('teach.individualAssignments')" name="publish"><div class="tp-box narrow pad"><PublishWizard @done="tab = 'console'" @cancel="tab = 'console'" /></div></el-tab-pane>
    </el-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
// 4.6: student "Courses" (course cards, details, lesson, school assignments); teacher "Courses" (authoring, library, preview) and "Teaching" (console, classes, individual assignment).
// /courses and /teach share this page: both show Courses for students; for teachers, /courses shows "Courses" and /teach shows "Teaching".
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { teachBus } from '../panels/teach/util';
import { handleTeachOpen, isStudent } from '../editor/shell/teach';
import { desk, get, post, saasServer } from '../api';
import PasswordDialog from '../components/PasswordDialog.vue';
import ClientLink from '../components/ClientLink.vue';

const TaskPanel = defineAsyncComponent(() => import('../panels/teach/TaskPanel.vue'));
const PackageOpen = defineAsyncComponent(() => import('../panels/teach/PackageOpen.vue'));
const TeacherConsole = defineAsyncComponent(() => import('../panels/teach/TeacherConsole.vue'));
const ClassManager = defineAsyncComponent(() => import('../panels/teach/ClassManager.vue'));
const PublishWizard = defineAsyncComponent(() => import('../panels/teach/PublishWizard.vue'));
const CourseHome = defineAsyncComponent(() => import('../panels/teach/CourseHome.vue'));
const CourseDetail = defineAsyncComponent(() => import('../panels/teach/CourseDetail.vue'));
const CourseStudio = defineAsyncComponent(() => import('../panels/teach/CourseStudio.vue'));
const CourseEditor = defineAsyncComponent(() => import('../panels/teach/CourseEditor.vue'));
// Standalone desktop mode has only "Courses": local self-study and school assignments; classes, publishing, and the console require the school server
const learner = isStudent() || desk.mode === 'standalone';
const route = useRoute();
const area = computed(() => (route.path === '/courses' ? 'courses' : 'teach'));
const tab = ref(learner ? 'task' : (['console', 'classes', 'publish'].includes(String(route.query.tab)) ? String(route.query.tab) : 'console'));
const stop = handleTeachOpen(() => '');
watch(() => teachBus.review?.n, () => { if (teachBus.review) tab.value = 'console'; });   // Click a score in the gradebook → return to review in the console

// ---- Student: course cards → details → lesson (URL ?l=<assignment-id> selects the lesson, ?c=<class:course> opens course details; no page reload)
const view = ref<'home' | 'lesson'>('home');
const detail = ref<any>(null);
const detailOpen = ref(false);
const focus = ref('');
const lessonAid = ref(0);
const autoEnter = ref<boolean | 'start'>(false);
const lessonKey = ref(0);
const homeEl = ref<any>(null);
const drawerSize = computed(() => (innerWidth > 1900 ? '640px' : innerWidth > 1100 ? '560px' : '92vw'));
function setQuery(q: Record<string, string>) {
  const u = new URL(location.href);
  for (const k of ['l', 'c']) u.searchParams.delete(k);
  for (const [k, v] of Object.entries(q)) if (v) u.searchParams.set(k, v);
  history.replaceState(history.state, '', u.pathname + u.search + u.hash);
}
function openCourse(c: any) { detail.value = c; detailOpen.value = true; setQuery({ c: `${c.class_id}:${c.course}` }); }
watch(detailOpen, (v) => { if (!v && view.value === 'home') setQuery({}); });
async function focusFor(aid: number) {
  const m = homeEl.value?.map || await get('/api/teach/my/courses', true).catch(() => ({ courses: [] }));
  for (const c of m.courses || []) for (const ch of c.chapters) for (const l of ch.lessons) if (l.aid === aid) return `${c.class_id}:${c.course}`;
  return 'tasks';
}
// 5.0 Honey Cloud web (not desktop client): student clicks a lesson → "Open in Desktop Client" (vfactory://open?path=/courses?school=<assignment-id>)
const saasWeb = !desk.on && saasServer();
const clientOpen = ref(false), clientPath = ref('/courses');
/** Open a lesson. enter: true = enter the sandbox directly (assignment package, deep link); 'start' = same as "Start This Lesson" ("Start Learning / Continue Learning" on course cards). */
async function openLesson(aid: number, f?: string, enter: boolean | 'start' = false) {
  if (saasWeb) { clientPath.value = `/courses?school=${aid}`; clientOpen.value = true; return; }
  focus.value = f || await focusFor(aid);
  lessonAid.value = aid; autoEnter.value = enter; lessonKey.value++;
  detailOpen.value = false;
  view.value = 'lesson';
  try { localStorage.setItem('vf_teach_aid', String(aid)); } catch { /* */ }
  setQuery({ l: String(aid) });
}
function goHome() { view.value = 'home'; setQuery({}); }
/** Student opened their own assignment package: program/model is loaded into this assignment's sandbox; open the lesson and enter the sandbox. Factory files were imported into "My Factories". */
async function ownPkg(r: any) {
  if (r.myplant) { const { router } = await import('../router'); router.push(`/p/${encodeURIComponent(r.pid)}/workbench`); return; }
  await openLesson(r.aid, undefined, true);
}
// First login (initial password from teacher): prompt for a password change unless "Later" was clicked during this session.
const pwOpen = ref(false);
function pwLater() { try { sessionStorage.setItem('vf_pw_later', '1'); } catch { /* */ } }

// ---- Teacher: editor and preview in "Courses"
const editId = ref('');
const pv = ref<any>(null);
const pvAid = ref(0);
const studioEl = ref<any>(null);
watch(editId, (v) => { if (!v) { pv.value = null; pvAid.value = 0; } });

// Teachers open assignment packages in the desktop client (students use the course page): the launcher sets desk.openPath when a .vfhw file is double-clicked.
const pkgFile = ref<HTMLInputElement | null>(null);
const pkgDlg = ref(false);
const pkgEl = ref<any>(null);
function pickPkg(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = '';
  if (f) { pkgDlg.value = true; pkgEl.value?.openFile(f); }
}
function takePath() {
  if (learner || !desk.openPath || !pkgEl.value) return;
  const p = desk.openPath; desk.openPath = '';
  pkgEl.value.openPath(p);
}
watch([() => desk.openPath, pkgEl], takePath, { flush: 'post' });
/** 5.0 desktop deep links (vfactory://open?path=…): teacher /courses?edit=<course> | ?new=1 | ?copy=<course>; student /courses?school=<school-assignment-id>. */
async function deepLinks() {
  const q = route.query;
  if (!desk.on) return;
  if (!learner && area.value === 'courses') {
    if (q.edit) { const id = String(q.edit); const mine = await get('/api/teach/authoring', true).catch(() => []);
      const it = (mine || []).find((x: any) => x.id === id);
      if (it?.remote) await post(`/api/teach/authoring/${encodeURIComponent(id)}/fetch`, {});
      editId.value = id; }
    else if (q.new) editId.value = (await post('/api/teach/authoring', { name: $t('teach.newCourse') })).id;
    else if (q.copy) editId.value = (await post('/api/teach/authoring', { copy: String(q.copy) })).id;
  } else if (learner && q.school) {
    const r = await post('/api/client/school/open', { remote_aid: Number(q.school) });
    if (r?.local_aid) await openLesson(r.local_aid, undefined, true);
  }
}
onMounted(async () => {
  takePath();
  await deepLinks().catch(() => null);
  if (!learner) return;
  if (route.query.school) return;
  const l = Number(route.query.l || 0);
  if (l) await openLesson(l);
  else if (route.query.c) {
    const m = await get('/api/teach/my/courses', true).catch(() => ({ courses: [] }));
    const c = (m.courses || []).find((x: any) => `${x.class_id}:${x.course}` === String(route.query.c));
    if (c) openCourse(c);
  }
  if (isStudent()) {
    const me = await get('/api/teach/me', true).catch(() => null);
    let later = false;
    try { later = !!sessionStorage.getItem('vf_pw_later'); } catch { /* */ }
    if (me?.must_change_password && !later && view.value === 'home') pwOpen.value = true;
  }
});
onUnmounted(() => { stop(); });
</script>

<style scoped>
.teach-page { padding: var(--hm-sp-4) var(--hm-sp-5) var(--hm-sp-4); }
.tp-head { margin-bottom: 4px; }
.tp-tabs :deep(.el-tabs__header) { margin-bottom: 10px; }
.teach-page.learner, .teach-page.studio { padding: 0; min-height: calc(100vh - var(--vf-shell-top)); box-sizing: border-box; }
.saas-learner { display: flex; align-items: center; gap: 8px; margin: 10px 14px 0; padding: 8px 12px; border-radius: var(--hm-r-md); font-size: var(--hm-fs-sm);
  background: var(--hm-primary-soft); border: 1px solid var(--hm-primary-soft-2); color: var(--hm-text-2); }
.saas-learner .el-icon { color: var(--hm-primary); }
.tp-tools { display: flex; align-items: center; gap: 10px; margin: 2px 0 6px; flex-wrap: wrap; }
.tp-box { height: calc(100vh - 230px); min-height: 520px; border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); overflow: hidden; background: var(--hm-surface); box-shadow: var(--hm-e1); }
.lesson-wrap { padding: 10px 14px 12px; height: calc(100vh - var(--vf-shell-top)); box-sizing: border-box; display: flex; flex-direction: column; }
.tp-box.full { flex: 1; height: auto; min-height: 480px; }
.tp-box.narrow { max-width: 860px; }
.tp-box.pad { padding: 12px; height: auto; }
.ce-wrap { padding: 12px 16px; height: calc(100vh - var(--vf-shell-top)); box-sizing: border-box; }
.pv-wrap { padding: 10px 16px; height: calc(100vh - var(--vf-shell-top)); box-sizing: border-box; display: flex; flex-direction: column; gap: 8px; }
.pv-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.pv-bar b { color: var(--el-text-color-primary); }
.pv-main { flex: 1; min-height: 0; display: flex; gap: 12px; }
.pv-detail { width: 440px; flex: none; overflow: auto; border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); background: var(--hm-surface); box-shadow: var(--hm-e1); }
.pv-lesson { flex: 1; height: auto; min-width: 0; }
.pv-pick { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; }
</style>
<style>
.course-drawer .el-drawer__body { padding: 0; }
</style>

<style>
:root { --vf-shell-top: 86px; }            /* Top bar 52 + breadcrumbs 34 */
html.compact { --vf-shell-top: 72px; }     /* Compact: 44 + 28 */
</style>
