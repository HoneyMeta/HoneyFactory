<template>
  <div class="ch" data-k="course-home">
    <!-- Header: title, stats, resume last lesson; illustration on the right -->
    <section class="ch-hero" data-tour="ch-hero">
      <div class="ch-hero-text">
        <h1>{{ $t('common.myCourses') }}</h1>
        <p>{{ $t('courseHome.eachCourseHasACard') }}</p>
        <div class="ch-stats">
          <div><b data-k="stat-courses">{{ map.courses.length }}</b><span>{{ $t('courseHome.courses') }}</span></div>
          <div><b>{{ lessonsDone }}</b><span>{{ $t('courseHome.lessonsCompleted') }}</span></div>
          <div><b>{{ homeworkCount }}</b><span>{{ $t('courseHome.schoolAssignments') }}</span></div>
        </div>
      </div>
      <img v-if="hero.src" class="ch-hero-art" :src="hero.src" :srcset="hero.srcset" alt="" />
      <div v-if="resume" class="ch-resume" data-k="resume" data-tour="ch-resume">
        <div class="cr-ico"><el-icon :size="20"><component :is="KIND_ICON[resume.kind] || 'VideoPlay'" /></el-icon></div>
        <div class="cr-t"><small>{{ $t('common.resumeLastLesson') }}</small><b>{{ resume.title }}</b><span>{{ resume.where }}</span></div>
        <el-button type="primary" size="small" @click="emit('open-lesson', resume.aid, resume.focus)">{{ $t('common.continue') }}</el-button>
      </div>
    </section>

    <div class="ch-toolbar">
      <el-radio-group v-model="filter" size="small" data-k="course-filter" data-tour="ch-filter">
        <el-radio-button value="doing">{{ $t('courseHome.inProgress0', [counts.doing]) }}</el-radio-button>
        <el-radio-button value="done">{{ $t('courseHome.completed0', [counts.done]) }}</el-radio-button>
        <el-radio-button value="all">{{ $t('courseHome.all0', [map.courses.length]) }}</el-radio-button>
      </el-radio-group>
      <el-input v-model="q" size="small" clearable :placeholder="$t('courseHome.searchCoursesAndLessons')" class="ch-search" data-k="course-search"><template #prefix><el-icon><Search /></el-icon></template></el-input>
      <span class="grow" />
      <span v-if="!desk.on && isStudent()" class="ch-hint" data-k="web-mine-hint"><el-icon><InfoFilled /></el-icon>{{ $t('courseHome.inTheDesktopClientYou') }}</span>
      <span v-else-if="desk.on && isStudent()" class="ch-hint"><el-icon><OfficeBuilding /></el-icon>{{ $t('courseHome.yourFactoriesAreUnderMy') }}</span>
      <template v-if="desk.on">
        <input ref="pkgFile" type="file" accept=".vfhw,.vfplant" style="display: none" @change="pickPkg" />
        <el-button size="small" @click="pkgFile?.click()"><el-icon><FolderOpened /></el-icon>{{ $t('common.openAssignmentPackage') }}</el-button>
      </template>
      <GuideButton area="courses" />
    </div>

    <div v-if="loading && !loaded" class="ch-grid"><div v-for="i in 3" :key="i" class="cc skel" /></div>
    <div v-else-if="shown.length" class="ch-grid" data-k="course-grid" data-tour="ch-grid">
      <article v-for="c in shown" :key="c.class_id + ':' + c.course" class="cc course-card" :class="courseState(c)" :data-course="c.course" tabindex="0"
               @click="emit('open-course', c)" @keydown.enter="emit('open-course', c)">
        <div class="cc-cover">
          <img v-if="courseCover(c)" :src="courseCover(c)" alt="" loading="lazy" />
          <div v-else class="cc-ph"><el-icon :size="40"><Reading /></el-icon></div>
          <span class="cc-badge" :class="courseState(c)">{{ STATE_CN[courseState(c)] }}</span>
        </div>
        <div class="cc-body">
          <div class="cc-kinds"><span v-for="k in c.kinds || []" :key="k" class="kchip" :class="k">{{ KIND_CN[k] || k }}</span></div>
          <h3 class="cc-title">{{ c.name }}</h3>
          <p class="cc-desc">{{ c.desc || $t('courseHome.k4846') }}</p>
          <div class="cc-meta"><el-icon><Collection /></el-icon>{{ $t('courseHome.n0Chapters1Lessons', [c.chapters.length, c.total]) }}<span class="dot">·</span>{{ c.class_name }}</div>
          <div class="cc-prog"><div class="bar"><i :style="{ width: pct(c) + '%' }" /></div><span class="mono">{{ c.done }}/{{ c.total }}</span></div>
          <div class="cc-next">
            <template v-if="nextLesson(c)"><span class="vp-muted">{{ $t('courseHome.nextLesson') }}</span><b :title="nextLesson(c)!.title">{{ nextLesson(c)!.title }}</b></template>
            <template v-else-if="courseState(c) === 'done'"><el-icon class="vp-pass"><CircleCheckFilled /></el-icon><b>{{ $t('courseDetail.allComplete') }}</b></template>
            <template v-else><el-icon><Lock /></el-icon><span class="vp-muted">{{ $t('courseHome.laterLessonsAreStillLocked') }}</span></template>
          </div>
        </div>
        <footer class="cc-foot">
          <span class="cc-more">{{ $t('courseHome.courseDetails') }}<el-icon><ArrowRight /></el-icon></span>
          <el-button v-if="cardAct(c)" size="small" :type="cardAct(c)!.mode === 'review' ? 'default' : 'primary'" data-k="card-continue" :data-mode="cardAct(c)!.mode" :data-aid="cardAct(c)!.aid"
                     @click.stop="runCard(c)"><el-icon><component :is="cardAct(c)!.mode === 'review' ? 'RefreshLeft' : 'VideoPlay'" /></el-icon>{{ cardAct(c)!.label }}</el-button>
        </footer>
      </article>
    </div>
    <div v-else class="ch-empty" data-k="course-empty" data-tour="ch-empty">
      <img v-if="emptyArt.src" :src="emptyArt.src" :srcset="emptyArt.srcset" alt="" />
      <b>{{ map.courses.length ? (q ? $t('courseHome.courseNotFound') : filter === 'done' ? $t('courseHome.noCompletedCoursesYet') : $t('courseHome.noCoursesInProgress')) : $t('courseHome.noCoursesYet') }}</b>
      <span v-if="!map.courses.length">{{ isTeacher() ? $t('courseHome.thisIsTheStudentCourse') : $t('courseHome.coursesAppearHereOnceYour') }}</span>
      <el-button v-else size="small" @click="filter = 'all'; q = ''">{{ $t('courseHome.viewAllCourses') }}</el-button>
    </div>

    <!-- School assignments: standalone assignments outside courses; the desktop client also includes assignments from the school server -->
    <section class="ch-hw" data-k="homework" data-tour="ch-homework">
      <header><h2>{{ $t('common.schoolAssignments') }}</h2><span class="vp-small vp-muted">{{ $t('courseHome.standaloneAssignmentsFromYourTeacher', [desk.on ? $t('courseHome.whenTheDesktopClientIs') : '']) }}</span></header>
      <SchoolWork v-if="desk.on" ref="swEl" class="ch-sw" @open="onSchoolOpen" />
      <div v-if="map.tasks.length" class="ch-hw-grid">
        <div v-for="a in map.tasks" :key="a.id" class="vp-item task-card" :data-aid="a.id" :data-kind="a.kind" @click="emit('open-lesson', a.id, 'tasks')">
          <div class="hw-top"><span class="kchip" :class="a.kind">{{ KIND_CN[a.kind] || $t('common.plcLab') }}</span>
            <el-tag v-if="a.best !== null && a.best !== undefined" size="small" :type="a.best >= 99.5 ? 'success' : a.best >= 60 ? 'warning' : 'danger'">{{ $t('common.n0Min', [a.best]) }}</el-tag>
            <el-tag v-else size="small" type="info">{{ a.submissions ? $t('courseHome.awaitingGrading') : $t('courseHome.notSubmitted') }}</el-tag></div>
          <div class="t">{{ a.title }}</div>
          <div class="vp-small vp-muted">{{ a.class_name }}<template v-if="a.kind !== 'factory'"> · {{ a.scene_name }}</template></div>
          <div class="hw-due" :class="{ over: a.overdue }"><el-icon><Clock /></el-icon>{{ a.due ? (a.overdue ? $t('courseHome.pastDue') : $t('welcome.due')) + a.due : $t('common.noTimeLimit') }}</div>
          <div class="vp-row" style="margin-top: 8px">
            <el-progress class="vp-grow" :percentage="Math.round(a.best || 0)" :stroke-width="5" :show-text="false" />
            <el-button size="small" type="primary" plain @click.stop="emit('open-lesson', a.id, 'tasks')">{{ a.kind === 'factory' ? $t('courseHome.viewRequirements') : a.submissions ? $t('common.continue') : $t('common.start') }}</el-button>
          </div>
        </div>
      </div>
      <div v-else-if="!desk.on" class="ch-empty small">
        <span>{{ $t('courseHome.noStandaloneAssignmentsRightNow') }}</span>
      </div>
    </section>
    <PackageOpen ref="pkgEl" v-model="pkgDlg" @own="(r: any) => emit('own-package', r)" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// 4.6 Student "Courses" page: course cards (collapsed by default, expand for chapters), filters, search, and a separate school assignments section.
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { desk, get, post } from '../../api';
import { themed } from '../../brand';
import { isStudent, isTeacher } from './util';
import { courseCover, courseState, KIND_CN, KIND_ICON, nextLesson, pct } from './courses';
import SchoolWork from './SchoolWork.vue';
import GuideButton from '../../components/GuideButton.vue';
import PackageOpen from './PackageOpen.vue';
import './panel.css';

/** open-lesson start: 'start' = open the lesson and start it as if "Start Lesson" were clicked (enter sandbox). */
const emit = defineEmits<{ (e: 'open-course', c: any): void; (e: 'open-lesson', aid: number, focus?: string, start?: 'start'): void; (e: 'own-package', r: any): void }>();
const STATE_CN: Record<string, string> = { done: $t('entityPage.completed'), doing: $t('courseHome.inProgress'), new: $t('courseHome.notStarted') };
const map = reactive<any>({ courses: [], tasks: [] });
const loading = ref(false);
const loaded = ref(false);
const filter = ref<'doing' | 'done' | 'all'>('doing');
const q = ref('');
const swEl = ref<any>(null);
try { const f = localStorage.getItem('vf_course_filter'); if (f === 'doing' || f === 'done' || f === 'all') filter.value = f; } catch { /* */ }
watch(filter, (v) => { try { localStorage.setItem('vf_course_filter', v); } catch { /* */ } });

const hero = computed(() => themed('courses-hero'));
const emptyArt = computed(() => themed('empty-courses'));
const counts = computed(() => ({ doing: map.courses.filter((c: any) => courseState(c) !== 'done').length, done: map.courses.filter((c: any) => courseState(c) === 'done').length }));
const lessonsDone = computed(() => map.courses.reduce((n: number, c: any) => n + (c.done || 0), 0));
const homeworkCount = computed(() => map.tasks.length);
const shown = computed(() => {
  const k = q.value.trim().toLowerCase();
  return map.courses.filter((c: any) => (filter.value === 'all' || (filter.value === 'done' ? courseState(c) === 'done' : courseState(c) !== 'done'))
    && (!k || [c.name, c.desc, c.class_name, ...c.chapters.flatMap((ch: any) => [ch.title, ...ch.lessons.map((l: any) => l.title)])].some((x: string) => String(x || '').toLowerCase().includes(k))));
});
/** Resume last lesson: the last opened lesson, if still listed on the Courses page. */
const resume = computed<any>(() => {
  let aid = 0;
  try { aid = Number(localStorage.getItem('vf_teach_aid') || 0); } catch { /* */ }
  if (!aid) return null;
  for (const c of map.courses) for (const ch of c.chapters) for (const l of ch.lessons) if (l.aid === aid && !l.locked)
    return { aid, title: l.title, kind: l.kind, where: `${c.name} · ${ch.title}`, focus: `${c.class_id}:${c.course}` };
  const t = map.tasks.find((x: any) => x.id === aid);
  return t ? { aid, title: t.title, kind: t.kind, where: $t('courseHome.schoolAssignments0', [t.class_name || '']), focus: 'tasks' } : null;
});
/** Course card buttons:
 *  - In progress: "Continue Learning" = current lesson (last opened, unfinished), otherwise the next unlocked lesson — open and start (same as "Start Lesson");
 *  - Not started: "Start Learning" = open and start the first lesson;
 *  - All completed: "Review" = open the first lesson for review (without entering the sandbox). */
function cardAct(c: any): { mode: 'continue' | 'start' | 'review'; label: string; aid: number } | null {
  const flat: any[] = (c.chapters || []).flatMap((ch: any) => ch.lessons || []);
  if (!flat.length) return null;
  const st = courseState(c);
  if (st === 'done') return { mode: 'review', label: $t('courseHome.review'), aid: flat[0].aid };
  const open = (l: any) => l && !l.locked && l.state !== 'done';
  const started = (l: any) => (l.sandbox && l.sandbox !== 'none') || l.submissions || (l.best !== null && l.best !== undefined);
  if (st === 'new' && !flat.some(started)) { const first = flat.find((l) => !l.locked) || flat[0]; return first.locked ? null : { mode: 'start', label: $t('courseHome.startLearning'), aid: first.aid }; }
  let last = 0;
  try { last = Number(localStorage.getItem('vf_teach_aid') || 0); } catch { /* */ }
  const pick = flat.find((l) => l.aid === last && open(l)) || flat.find((l) => open(l) && started(l)) || flat.find((l) => l.aid === c.next) || flat.find(open);
  return pick ? { mode: 'continue', label: $t('courseHome.continueLearning'), aid: pick.aid } : null;
}
function runCard(c: any) {
  const a = cardAct(c);
  if (!a) return;
  const f = c.class_id + ':' + c.course;
  if (a.mode === 'review') emit('open-lesson', a.aid, f);
  else emit('open-lesson', a.aid, f, 'start');
}
function focusOf(aid: number) {
  for (const c of map.courses) for (const ch of c.chapters) for (const l of ch.lessons) if (l.aid === aid) return `${c.class_id}:${c.course}`;
  return 'tasks';
}
async function load() {
  loading.value = true;
  try {
    if (desk.on) await post('/api/client/local/ensure', {}).catch(() => undefined);
    Object.assign(map, await get('/api/teach/my/courses'));
    if (filter.value === 'doing' && !counts.value.doing && map.courses.length) filter.value = 'all';
  } finally { loading.value = false; loaded.value = true; }
}
async function onSchoolOpen(aid: number) { await load(); emit('open-lesson', aid, focusOf(aid)); }
// Assignment packages (desktop client): open .vfhw; the launcher supplies desk.openPath when a package is double-clicked.
const pkgFile = ref<HTMLInputElement | null>(null);
const pkgDlg = ref(false);
const pkgEl = ref<any>(null);
function pickPkg(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = '';
  if (f) { pkgDlg.value = true; pkgEl.value?.openFile(f); }
}
function takePath() {
  if (!desk.openPath || !pkgEl.value) return;
  const p = desk.openPath; desk.openPath = '';
  pkgEl.value.openPath(p);
}
watch([() => desk.openPath, pkgEl], takePath, { flush: 'post' });
defineExpose({ load, map, focusOf });
onMounted(async () => { await load(); takePath(); });
</script>

<style scoped>
/* 5.0.1: Light theme (shared with HoneyMOM): white cards, thin borders, cobalt blue primary; type badges use light status-color backgrounds and dark text. */
.ch { color: var(--hm-text); max-width: calc(1720px * var(--hm-scale)); margin: 0 auto; padding: var(--hm-sp-4) var(--hm-sp-5) 40px; box-sizing: border-box; }
.ch-hero { position: relative; display: flex; align-items: stretch; min-height: 180px; border-radius: var(--hm-r-lg); overflow: hidden; border: 1px solid var(--hm-border); box-shadow: var(--hm-e1);
  background: radial-gradient(700px 260px at 92% -20%, rgba(11, 165, 196, .08), transparent 60%), radial-gradient(500px 220px at 100% 120%, rgba(217, 130, 43, .06), transparent 60%), var(--hm-surface); }
.ch-hero-text { position: relative; z-index: 1; padding: 24px 28px 20px; max-width: 680px; }
.ch-hero h1 { margin: 0 0 6px; font-size: var(--hm-fs-2xl); font-weight: var(--hm-fw-semibold); letter-spacing: .5px; color: var(--hm-text); }
.ch-hero p { margin: 0; color: var(--hm-text-2); font-size: var(--hm-fs-sm); line-height: 1.7; }
.ch-stats { display: flex; gap: 10px; margin-top: 16px; }
.ch-stats div { display: flex; flex-direction: column; position: relative; min-width: 92px; padding: 7px 12px 7px 14px; border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); background: var(--hm-surface); overflow: hidden; }
.ch-stats div::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--hm-primary); opacity: .7; }
.ch-stats b { font-size: var(--hm-fs-xl); font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; font-weight: 600; color: var(--hm-text); line-height: 1.2; }
.ch-stats span { font-size: var(--hm-fs-xs); color: var(--hm-text-3); }
.ch-hero-art { position: absolute; right: 0; top: 0; height: 100%; max-width: 70%; object-fit: cover; object-position: right center; pointer-events: none;
  filter: saturate(.7) brightness(1.03); -webkit-mask-image: linear-gradient(90deg, transparent, #000 28%); mask-image: linear-gradient(90deg, transparent, #000 28%); }
.ch-resume { position: absolute; right: 18px; bottom: 16px; z-index: 2; display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: var(--hm-r-lg);
  background: var(--hm-glass-strong); border: 1px solid var(--hm-border); box-shadow: var(--hm-e2); backdrop-filter: var(--hm-glass-blur); max-width: 380px; }
.cr-ico { width: 38px; height: 38px; border-radius: var(--hm-r-md); display: grid; place-items: center; background: var(--hm-primary-soft); color: var(--hm-primary); flex: none; }
.cr-t { display: flex; flex-direction: column; min-width: 0; }
.cr-t small { font-size: var(--hm-fs-2xs); color: var(--hm-text-3); }
.cr-t b, .cr-t span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cr-t span { font-size: var(--hm-fs-xs); color: var(--hm-text-3); }
.ch-toolbar { display: flex; align-items: center; gap: 12px; margin: var(--hm-gap) 0; flex-wrap: wrap; }
.ch-search { width: 240px; }
.grow { flex: 1; }
.ch-hint { display: inline-flex; align-items: center; gap: 5px; font-size: var(--hm-fs-xs); color: var(--hm-text-2); background: var(--hm-surface-2); border: 1px solid var(--hm-border); border-radius: var(--hm-r-pill); padding: 3px 10px; }
.ch-hint .el-icon { color: var(--hm-primary); }
.ch-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(calc(300px * var(--hm-scale)), 1fr)); gap: var(--hm-gap); }
.cc { display: flex; flex-direction: column; background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); overflow: hidden; cursor: pointer; box-shadow: var(--hm-e1);
  transition: transform var(--hm-dur-2) var(--hm-ease), box-shadow var(--hm-dur-2) var(--hm-ease), border-color var(--hm-dur-2) var(--hm-ease); outline: none; }
.cc:hover, .cc:focus-visible { transform: translateY(-1px); box-shadow: var(--hm-e2); border-color: var(--el-color-primary-light-5); }
.cc.skel { height: 360px; cursor: default; background: linear-gradient(90deg, var(--hm-surface-2), var(--hm-surface-3), var(--hm-surface-2)); background-size: 200% 100%; animation: sk 1.2s infinite; }
@keyframes sk { to { background-position: -200% 0; } }
.cc-cover { position: relative; aspect-ratio: 16 / 9; background: var(--hm-surface-2); overflow: hidden; border-bottom: 1px solid var(--hm-border); }
.cc-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cc-ph { width: 100%; height: 100%; display: grid; place-items: center; color: var(--hm-primary); background: linear-gradient(135deg, var(--hm-primary-soft), var(--hm-cyan-soft)); }
.cc-badge { position: absolute; left: 12px; top: 12px; font-size: var(--hm-fs-2xs); line-height: 18px; padding: 1px 9px; border-radius: var(--hm-r-pill); background: var(--hm-offline-soft); color: var(--hm-offline-ink); border: 1px solid var(--hm-hairline); }
.cc-badge.doing { background: var(--hm-setup-soft); color: var(--hm-setup-ink); } .cc-badge.done { background: var(--hm-run-soft); color: var(--hm-run-ink); }
.cc-body { padding: 12px 16px 4px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
.cc-kinds { display: flex; gap: 5px; flex-wrap: wrap; min-height: 20px; }
.kchip { font-size: var(--hm-fs-2xs); padding: 1px 7px; border-radius: var(--hm-r-xs); background: var(--hm-offline-soft); color: var(--hm-offline-ink); }
.kchip.cell { background: var(--hm-setup-soft); color: var(--hm-setup-ink); } .kchip.plant, .kchip.point { background: var(--hm-amber-soft); color: var(--hm-amber-ink); } .kchip.quiz, .kchip.factory { background: var(--hm-run-soft); color: var(--hm-run-ink); }
.kchip.diagnose { background: var(--hm-fault-soft); color: var(--hm-fault-ink); } .kchip.mes { background: var(--hm-cyan-soft); color: var(--hm-cyan-ink); }
.cc-title { margin: 2px 0 0; font-size: var(--hm-fs-lg); font-weight: var(--hm-fw-semibold); line-height: 1.35; color: var(--hm-text); }
.cc-desc { margin: 0; font-size: var(--hm-fs-xs); line-height: 1.6; color: var(--hm-text-3); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 38px; }
.cc-meta { font-size: var(--hm-fs-xs); color: var(--hm-text-3); display: flex; align-items: center; gap: 4px; }
.cc-meta .dot { margin: 0 2px; }
.cc-prog { display: flex; align-items: center; gap: 8px; margin-top: 4px; font-size: var(--hm-fs-xs); color: var(--hm-text-2); }
.cc-prog .bar { flex: 1; height: 6px; border-radius: 3px; background: var(--hm-surface-3); overflow: hidden; }
.cc-prog .bar i { display: block; height: 100%; background: var(--hm-primary); border-radius: 3px; }
.cc.done .cc-prog .bar i { background: var(--hm-run); }
.cc-next { display: flex; align-items: center; gap: 6px; font-size: var(--hm-fs-xs); min-height: 22px; color: var(--hm-text-3); }
.cc-next b { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--hm-text); }
.cc-foot { display: flex; align-items: center; justify-content: space-between; padding: 10px 16px 14px; }
.cc-foot :deep(.el-button .el-icon) { margin-right: 4px; }
.cc-more { font-size: var(--hm-fs-xs); color: var(--hm-primary); display: inline-flex; align-items: center; gap: 2px; }
.ch-empty { display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 36px 10px; color: var(--hm-text-3); text-align: center; }
.ch-empty img { width: 240px; max-width: 70%; }
.ch-empty b { color: var(--hm-text); font-size: var(--hm-fs-md); }
.ch-empty.small { padding: 14px; }
.ch-hw { margin-top: 28px; }
.ch-hw > header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px; border-top: 1px solid var(--hm-border); padding-top: 18px; flex-wrap: wrap; }
.ch-hw h2 { margin: 0; font-size: var(--hm-fs-lg); font-weight: var(--hm-fw-semibold); color: var(--hm-text); }
.ch-sw { margin-bottom: 12px; }
.ch-hw-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(calc(280px * var(--hm-scale)), 1fr)); gap: 12px; }
.task-card { border-radius: var(--hm-r-lg); padding: 12px 14px; background: var(--hm-surface); }
.task-card .hw-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.task-card .t { font-weight: 600; font-size: var(--hm-fs-md); margin-bottom: 2px; }
.hw-due { display: flex; align-items: center; gap: 4px; font-size: var(--hm-fs-xs); color: var(--hm-text-3); margin-top: 4px; }
.hw-due.over { color: var(--hm-fault-ink); }
.mono { font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; }
@media (max-width: 900px) { .ch { padding: 12px; } .ch-hero-art { opacity: .35; } .ch-resume { position: static; margin: 0 16px 14px; } .ch-hero { flex-direction: column; } }
html.compact .ch { padding: 10px 14px 24px; } html.compact .ch-hero { min-height: 150px; } html.compact .ch-hero-text { padding: 16px 22px 14px; }
</style>