<template>
  <!-- Start page (4.5): first page after login. Recent files, templates, learning, resources, tips; students also see "Resume Lesson / Assignments / My Factories", teachers "Class Progress / Pending Review", admins "Server Status". -->
  <div class="wc" data-help="welcome" data-k="welcome" :data-role="role">
    <div class="wc-wrap">
      <!-- Banner -->
      <section class="wc-hero" :class="{ art: !!hero.src }">
        <img v-if="hero.src" class="wc-hero-img" :src="hero.src" :srcset="hero.srcset || undefined" alt="" />
        <div class="wc-hero-in">
          <div class="wc-hello">
            <small class="wc-kicker">{{ kicker }}</small>
            <h1>{{ $t('experiments.n01', [greet, session.user?.name || $t('welcome.hello')]) }}</h1>
            <p>{{ subline }}</p>
            <div class="wc-cta">
              <template v-for="a in heroActions" :key="a.k">
                <el-button :type="a.primary ? 'primary' : ''" :data-k="'wc-cta-' + a.k" @click="a.run()"><el-icon><component :is="a.icon" /></el-icon><span>{{ a.label }}</span></el-button>
              </template>
            </div>
          </div>
        </div>
        <div class="wc-hero-bar">
          <el-checkbox v-model="startPrefs.showWelcome" size="small" data-k="welcome-onstart">{{ $t('sections.showWelcomePageAtStartup') }}</el-checkbox>
          <span class="wc-sep" />
          <button class="wc-theme" data-k="wc-palette" @click="openCommandPalette()"><el-icon><Search /></el-icon><span>{{ $t('welcome.commandPaletteCtrlK') }}</span></button>
        </div>
      </section>

      <div class="wc-grid">
        <div class="wc-main">
          <!-- Student: resume last lesson -->
          <section v-if="showLearner" class="wc-sec" data-k="wc-continue">
            <header><h3>{{ $t('common.resumeLastLesson') }}</h3><span class="grow" /><a class="wc-link" @click="router.push('/teach')">{{ $t('welcome.courseMap') }}</a></header>
            <div v-if="cont" class="wc-cont" @click="openItem(cont.aid)">
              <img v-if="coverFor(cont.cid, cont.chid)" class="wc-cont-cv" :src="coverFor(cont.cid, cont.chid)" alt="" />
              <div v-else class="wc-cont-ic" :class="cont.kind"><el-icon :size="26"><component :is="cont.kind === 'cell' ? 'Cpu' : 'DataLine'" /></el-icon></div>
              <div class="wc-cont-m">
                <small class="muted">{{ cont.course }} · {{ cont.chapter }}</small>
                <b>{{ cont.title }}</b>
                <div class="wc-prog"><i :style="{ width: Math.round((cont.done / Math.max(1, cont.total)) * 100) + '%' }" /></div>
                <small class="muted">{{ $t('welcome.completed01Lessons', [cont.done, cont.total]) }}<template v-if="cont.best != null"> {{ $t('welcome.bestScoreForThisLesson', [cont.best]) }}</template></small>
              </div>
              <el-button type="primary" data-k="wc-continue-btn" @click.stop="openItem(cont.aid)">{{ cont.best != null ? $t('welcome.continue') : $t('common.start') }}<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button>
            </div>
            <EmptyState v-else-if="learn.loaded" kind="homework" compact :title="$t('welcome.noLessonsPublishedForYou')" :desc="$t('welcome.yourNextLessonWillAppear')" />
            <div v-else class="wc-skel" />
          </section>

          <!-- Student: assignments -->
          <section v-if="isStu" class="wc-sec" data-k="wc-homework">
            <header><h3>{{ $t('welcome.assignmentsDueSoon') }}</h3><small class="muted">{{ due.length ? $t('welcome.incomplete0', [due.length]) : '' }}</small></header>
            <div v-if="due.length" class="wc-rows">
              <div v-for="a in due.slice(0, 5)" :key="(a.school ? 's' : '') + a.id + a.title" class="wc-row" @click="openItem(a.id)">
                <el-icon class="wc-row-ic"><Notebook /></el-icon>
                <span class="wc-row-t">{{ a.title }}</span>
                <small class="muted">{{ a.class_name }}</small>
                <span class="grow" />
                <span class="wc-due" :class="{ over: a.overdue, soon: soon(a.due) }">{{ a.overdue ? $t('welcome.overdue') : $t('welcome.due') }}{{ (a.due || '').slice(5, 16) }}</span>
              </div>
            </div>
            <EmptyState v-else kind="homework" compact plain :title="$t('welcome.noAssignmentsDueSoon')" :desc="$t('welcome.assignmentsWithDueDatesWill')" />
          </section>
          <!-- Student: my courses (course covers + progress) -->
          <section v-if="showLearner && learn.courses.length" class="wc-sec" data-k="wc-courses">
            <header><h3>{{ $t('common.myCourses') }}</h3><span class="grow" /><a class="wc-link" @click="router.push('/teach')">{{ $t('welcome.courseMap') }}</a></header>
            <div class="wc-cards crs">
              <div v-for="c in learn.courses" :key="c.course + c.class_id" class="wc-pc" @click="c.next ? openLesson(c.next) : router.push('/teach')">
                <div class="wc-thumb"><img v-if="coverFor(c.course)" :src="coverFor(c.course)" alt="" /><div v-else class="wc-blank"><el-icon :size="28"><Reading /></el-icon></div></div>
                <div class="wc-pc-m"><b :title="c.name">{{ c.name }}</b>
                  <div class="wc-prog"><i :style="{ width: Math.round((c.done / Math.max(1, c.total)) * 100) + '%' }" /></div>
                  <small class="muted">{{ $t('welcome.n01Lessons2', [c.done, c.total, c.class_name ? ' · ' + c.class_name : '']) }}</small></div>
              </div>
            </div>
          </section>

          <!-- Admin: server status -->
          <section v-if="role === 'admin' && desk.mode !== 'standalone'" class="wc-sec" data-k="wc-server">
            <header><h3>{{ $t('welcome.serverStatus') }}</h3><span class="wc-ok"><i />{{ $t('welcome.runningNormally') }}</span><span class="grow" /><a class="wc-link" @click="router.push('/users')">{{ $t('welcome.usersRoles') }}</a></header>
            <div class="wc-kpis">
              <div><small>{{ $t('common.version') }}</small><b class="mono">{{ srv.version || '—' }}</b></div>
              <div><small>{{ $t('common.factory') }}</small><b>{{ plantsRunning }}<i>{{ $t('welcome.n0Running', [session.plants.length]) }}</i></b></div>
              <div><small>{{ $t('common.alarm') }}</small><b :class="alarmTotal ? 'bad' : 'ok'">{{ alarmTotal }}</b></div>
              <div><small>{{ $t('welcome.protocolClients') }}</small><b>{{ clientTotal }}</b></div>
              <div><small>{{ $t('common.labSandbox') }}</small><b>{{ srv.sandbox?.running ?? '—' }}<i v-if="srv.sandbox">{{ $t('welcome.n0Active', [srv.sandbox.loaded]) }}</i></b></div>
              <div><small>{{ $t('common.username') }}</small><b>{{ srv.users ?? '—' }}</b></div>
            </div>
            <div v-if="srv.ports?.opcua" class="wc-ports muted small">{{ $t('welcome.opcUa0Mqtt1', [srv.ports.opcua, srv.ports.mqtt]) }}</div>
          </section>

          <!-- Teacher: class progress, pending review -->
          <section v-if="role === 'teacher'" class="wc-sec" data-k="wc-classes">
            <header><h3>{{ $t('common.classProgress') }}</h3><span class="grow" /><a class="wc-link" @click="router.push('/teach')">{{ $t('welcome.teacherConsole') }}</a></header>
            <div v-if="classes.length" class="wc-classes">
              <div v-for="c in classes" :key="c.name" class="wc-cls" @click="router.push('/teach')">
                <b>{{ c.name }}</b><small class="muted">{{ $t('welcome.n0Students1Assignments', [c.students, c.n]) }}</small>
                <div class="wc-prog"><i :style="{ width: Math.round(c.rate * 100) + '%' }" /></div>
                <small class="muted">{{ $t('welcome.submissionRate0', [Math.round(c.rate * 100)]) }}<template v-if="c.avg != null"> {{ $t('welcome.average0Points', [c.avg]) }}</template></small>
              </div>
            </div>
            <EmptyState v-else-if="tLoaded" kind="homework" compact :title="$t('welcome.noAssignmentsYet')" :desc="$t('welcome.createClassesAndImportRosters')">
              <el-button size="small" type="primary" @click="router.push({ path: '/teach', query: { tab: 'courses' } })">{{ $t('welcome.openCourseLibrary') }}</el-button>
            </EmptyState>
            <div v-else class="wc-skel" />
          </section>
          <section v-if="role === 'teacher'" class="wc-sec" data-k="wc-review">
            <header><h3>{{ $t('welcome.submissionsToReview') }}</h3><small class="muted">{{ reviewTotal ? $t('welcome.total0', [reviewTotal]) : '' }}</small></header>
            <div v-if="review.length" class="wc-rows">
              <div v-for="r in review" :key="r.id" class="wc-row" @click="router.push('/teach')">
                <el-icon class="wc-row-ic"><Tickets /></el-icon>
                <span class="wc-row-t">{{ r.title }}</span><small class="muted">{{ r.class_name }}</small>
                <span class="grow" /><span class="wc-badge">{{ $t('welcome.submissions0', [r.n]) }}</span>
              </div>
            </div>
            <EmptyState v-else-if="tLoaded" kind="submissions" compact plain :title="$t('welcome.noSubmissionsAwaitingReview')" :desc="$t('welcome.submissionsAreGradedAutomaticallyTho')" />
            <div v-else class="wc-skel" />
          </section>

          <!-- Recent files -->
          <section v-if="!isStu || desk.on" class="wc-sec" data-k="wc-recent">
            <header><h3>{{ $t('welcome.recentlyOpened') }}</h3><span class="grow" /><a v-if="!isStu" class="wc-link" @click="router.push('/')">{{ $t('welcome.allFactories') }}</a><a v-else class="wc-link" @click="router.push('/mine')">{{ $t('welcome.myFactories') }}</a></header>
            <div v-if="recents.length" class="wc-cards">
              <div v-for="r in recents" :key="r.pid" class="wc-pc" :data-pid="r.pid" @click="openPlant(r.pid)">
                <div class="wc-thumb"><img :src="r.img" alt="" /><span v-if="r.st" class="wc-st" :class="r.st.c">{{ r.st.t }}</span></div>
                <div class="wc-pc-m"><b :title="r.name">{{ r.name }}</b><small class="muted">{{ ago(r.t) }}{{ r.blocks ? $t('welcome.n0Objects', [r.blocks]) : '' }}</small></div>
                <button class="wc-x" :title="$t('welcome.removeFromList')" @click.stop="forgetRecent(r.pid)"><el-icon><Close /></el-icon></button>
              </div>
            </div>
            <EmptyState v-else kind="recent" compact :plain="isStu || role === 'teacher'" :title="$t('welcome.noFactoriesOpenedYet')" :desc="isStu ? $t('welcome.createYourOwnFactoryFrom') : $t('welcome.createAFactoryFromA')">
              <el-button v-if="!isStu" size="small" @click="router.push('/')">{{ $t('common.allFactories') }}</el-button>
            </EmptyState>
          </section>

          <!-- Create new -->
          <section v-if="canCreate" class="wc-sec" data-k="wc-new">
            <header><h3>{{ $t('common.new') }}</h3><small class="muted">{{ mineMode ? $t('welcome.createYourOwnFactoryOn') : $t('welcome.createAFactoryFromA2') }}</small><span class="grow" />
              <a v-if="!mineMode" class="wc-link" @click="router.push('/?new=1')">{{ $t('welcome.moreOptions') }}</a></header>
            <div class="wc-cards tpl">
              <div v-for="t in tpls" :key="t.key" class="wc-pc wc-tpl" :data-tpl="t.key" @click="pickTpl(t)">
                <div class="wc-thumb"><img v-if="t.key !== 'blank'" :src="t.img" alt="" /><div v-else class="wc-blank"><el-icon :size="30"><Plus /></el-icon></div>
                  <span class="wc-grp">{{ t.groupShort }}</span></div>
                <div class="wc-pc-m"><b :title="t.name">{{ t.name }}</b><small class="muted wc-2l">{{ t.desc || (t.blocks ? t.blocks + $t('plants.machines') : '') }}</small></div>
              </div>
            </div>
          </section>

          <!-- Admin: progress by class (after recent files and create new) -->
          <section v-if="role === 'admin' && classes.length" class="wc-sec" data-k="wc-classes">
            <header><h3>{{ $t('common.classProgress') }}</h3><span class="grow" /><a class="wc-link" @click="router.push('/teach')">{{ $t('welcome.teacherConsole') }}</a></header>
            <div class="wc-classes">
              <div v-for="c in classes" :key="c.name" class="wc-cls" @click="router.push('/teach')">
                <b>{{ c.name }}</b><small class="muted">{{ $t('welcome.n0Students1Assignments', [c.students, c.n]) }}</small>
                <div class="wc-prog"><i :style="{ width: Math.round(c.rate * 100) + '%' }" /></div>
                <small class="muted">{{ $t('welcome.submissionRate0', [Math.round(c.rate * 100)]) }}<template v-if="c.avg != null"> {{ $t('welcome.average0Points', [c.avg]) }}</template></small>
              </div>
            </div>
          </section>
          <!-- Student (desktop client): my factories -->
          <section v-if="isStu && desk.on" class="wc-sec" data-k="wc-mine">
            <header><h3>{{ $t('common.myFactories') }}</h3><small class="muted">{{ $t('welcome.onlyOnThisComputer') }}</small><span class="grow" /><a class="wc-link" @click="router.push('/mine')">{{ $t('home.all') }}</a></header>
            <div v-if="mine.length" class="wc-rows">
              <div v-for="p in mine.slice(0, 4)" :key="p.id" class="wc-row" @click="openPlant(p.id)">
                <el-icon class="wc-row-ic"><OfficeBuilding /></el-icon><span class="wc-row-t">{{ p.name }}</span>
                <small class="muted">{{ $t('welcome.n0Objects1Plcs', [p.blocks, p.plcs]) }}</small><span class="grow" /><small class="muted">{{ p.updated || '' }}</small>
              </div>
            </div>
            <EmptyState v-else kind="mine" compact plain :title="$t('common.noFactoriesYet')" :desc="$t('welcome.createAsManyFactoriesAs')" />
          </section>
        </div>

        <aside class="wc-side">
          <section class="wc-sec" data-k="wc-learn">
            <header><h3>{{ $t('welcome.learn') }}</h3></header>
            <div class="wc-list">
              <div v-for="t in tuts" :key="t.id" class="wc-li" :data-tut="t.id" @click="runTut(t)">
                <img v-if="tutCover(t)" class="wc-li-cv" :src="tutCover(t)" alt="" />
                <el-icon v-else class="wc-li-ic"><component :is="t.icon || 'Reading'" /></el-icon>
                <div><b>{{ t.title }}</b><small v-if="t.badge" class="wc-chip">{{ t.badge }}</small><p v-if="t.desc">{{ t.desc }}</p></div>
              </div>
              <div class="wc-li" @click="router.push('/help')"><el-icon class="wc-li-ic"><QuestionFilled /></el-icon><div><b>{{ $t('common.helpCenter') }}</b><p>{{ $t('welcome.documentationForEveryFeaturePress') }}</p></div></div>
            </div>
          </section>
          <section class="wc-sec" data-k="wc-res">
            <header><h3>{{ $t('commandsCore.resources') }}</h3></header>
            <div class="wc-res">
              <a @click="openShortcuts()"><el-icon><Postcard /></el-icon>{{ $t('common.keyboardShortcuts') }}</a>
              <a data-k="wc-whatsnew" @click="openWhatsNew()"><el-icon><MagicStick /></el-icon>{{ $t('common.whatSNew') }}<small v-if="ui.version" class="muted">{{ ui.version }}</small></a>
              <a @click="openHelp('welcome')"><el-icon><Promotion /></el-icon>{{ $t('welcome.commandPaletteF1') }}</a>
              <a v-if="!isStu" @click="openDocs"><el-icon><Reading /></el-icon>{{ $t('common.apiDocumentation') }}</a>
              <a v-if="desk.on" @click="router.push('/settings')"><el-icon><Setting /></el-icon>{{ $t('common.settings') }}</a>
            </div>
          </section>
          <section class="wc-sec wc-tip" data-k="welcome-tip">
            <header><h3><el-icon><Opportunity /></el-icon>{{ $t('welcome.didYouKnow') }}</h3><span class="grow" /><button class="wc-tipn" :title="$t('welcome.nextTip')" @click="nextTip"><el-icon><ArrowRight /></el-icon></button></header>
            <transition name="wc-fade" mode="out-in"><p :key="tipI">{{ tips[tipI % tips.length] }}</p></transition>
            <div class="wc-dots"><i v-for="(_, i) in tips" :key="i" :class="{ on: i === tipI % tips.length }" /></div>
          </section>
        </aside>
      </div>
    </div>

    <el-dialog v-model="nd.open" :title="$t('common.newFactory')" width="min(560px, 94vw)" append-to-body :close-on-click-modal="!nd.busy" :show-close="!nd.busy">
      <div v-if="nd.t" class="wc-nd">
        <div class="wc-nd-pv"><img v-if="nd.t.key !== 'blank'" :src="nd.t.img" alt="" /><div v-else class="wc-blank"><el-icon :size="34"><Plus /></el-icon></div></div>
        <div class="wc-nd-m">
          <b>{{ nd.t.name }}</b><p class="muted small">{{ nd.t.desc }}</p>
          <el-input v-model="nd.name" data-k="wc-new-name" :placeholder="$t('welcome.nameYourFactory')" maxlength="40" @keyup.enter="create" />
          <small v-if="nd.busy" class="muted">{{ $t('welcome.creatingFactoryReadingTemplateCreati') }}</small>
        </div>
      </div>
      <template #footer><el-button :disabled="nd.busy" @click="nd.open = false">{{ $t('common.cancel') }}</el-button><el-button type="primary" :loading="nd.busy" data-k="wc-new-create" @click="create">{{ $t('welcome.createOpen') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
// Start page: a launch point like the SolidWorks "Welcome" dialog. All data comes from existing APIs: /api/overview (factories), /api/plants (templates), /api/client/myplants (students' desktop factories),
// /api/teach/my(/courses) (student lessons and assignments), /api/teach/assignments + submissions (teacher), /api/health + /api/teach/sandboxes + /api/admin/users (admin).
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { desk, get, post, session } from '../api';
import { brand, brandUrl, loadBrand, themed } from '../brand';
import EmptyState from '../components/EmptyState.vue';
import { learn, loadLearn, openLesson } from '../commands/core';
import { openCommandPalette } from '../commands/registry';
import { forgetRecent, recent, startPrefs, thumbOf } from '../start/recent';
import { sketchUrl } from '../start/sketch';
import { tutorials, type Tutorial } from '../start/tutorials';
import { openHelp, openShortcuts, openWhatsNew, ui } from '../start/ui';

const router = useRouter();
const role = computed(() => session.user?.role || '');
const isStu = computed(() => role.value === 'student');
const showLearner = computed(() => isStu.value || desk.mode === 'standalone');
/** Students in the desktop client: create under "My Factories" (local); other users with model editing access: server /api/plants. */
const mineMode = computed(() => isStu.value && desk.on);
const canCreate = computed(() => mineMode.value || ['admin', 'engineer'].includes(role.value));

// ---------- Banner ----------
loadBrand();
const hero = computed(() => (brand.loaded ? themed('welcome-hero') : { src: '', srcset: '' }));
/** Course covers (art assets): by chapter for PLC courses (basic logic / sorting and counting / transport and storage / line interlocks), by course otherwise. */
const PLC_CH: Record<string, string> = { c1: 'course-plc-logic', c2: 'course-plc-sorting', c3: 'course-plc-handling', c4: 'course-plc-line' };
const COURSE: Record<string, string> = { plc_basics: 'course-plc', machining: 'course-machining', foundry: 'course-foundry' };
function coverFor(course = '', chapter = '') {
  if (!brand.loaded) return '';
  return (course === 'plc_basics' && PLC_CH[chapter] ? brandUrl(PLC_CH[chapter] + '.png') : '') || (COURSE[course] ? brandUrl(COURSE[course] + '.png') : '');
}
const greet = (() => { const h = new Date().getHours(); return h < 5 ? $t('welcome.itSGettingLate') : h < 11 ? $t('welcome.goodMorning') : h < 13 ? $t('welcome.goodAfternoon') : h < 18 ? $t('welcome.goodAfternoon2') : $t('welcome.goodEvening'); })();
const kicker = computed(() => (desk.mode === 'standalone' ? $t('welcome.honeyfactoryStandalone') : desk.on ? $t('welcome.honeyfactoryDesktopClient') : $t('common.honeyfactory')) + (ui.version ? ' ' + ui.version : ''));
const subline = computed(() => ({
  student: $t('welcome.continueYourLastLessonOr'), teacher: $t('welcome.checkClassProgressReviewStudent'),
  admin: desk.mode === 'standalone' ? $t('welcome.allFactoriesAndCourseProgress') : $t('welcome.theServerIsRunningNormally'),
  engineer: $t('welcome.openARecentFactoryOr'), viewer: $t('welcome.selectAFactoryToView'),
} as Record<string, string>)[role.value] || $t('welcome.selectAFactoryToGet'));
const heroActions = computed(() => {
  const a: { k: string; label: string; icon: string; run: () => any; primary?: boolean }[] = [];
  if (showLearner.value) a.push({ k: 'continue', label: cont.value ? $t('common.resumeLastLesson') : $t('common.myCourses'), icon: 'VideoPlay', primary: true, run: () => (cont.value ? openItem(cont.value.aid) : router.push('/teach')) });
  if (role.value === 'teacher') a.push({ k: 'console', label: $t('common.teacherConsole'), icon: 'School', primary: true, run: () => router.push('/teach') }, { k: 'courses', label: $t('common.courseLibrary'), icon: 'Reading', run: () => router.push({ path: '/teach', query: { tab: 'courses' } }) });
  if (canCreate.value) a.push({ k: 'new', label: $t('common.newFactory'), icon: 'Plus', primary: !a.length, run: () => pickTpl(tpls.value[0]) });
  if (!isStu.value) a.push({ k: 'plants', label: $t('common.allFactories'), icon: 'Grid', run: () => router.push('/') });
  else if (desk.on) a.push({ k: 'mine', label: $t('common.myFactories'), icon: 'OfficeBuilding', run: () => router.push('/mine') });
  return a.slice(0, 3);
});

// ---------- Recent files ----------
const STC = (p: any) => (!p ? null : p.paused ? { t: $t('common.paused'), c: 'p' } : p.off ? { t: p.off, c: 'o' } : { t: $t('common.runningAt0', [p.speed]), c: 'r' });
const recents = computed(() => {
  void recent.tick;
  const known = new Set(session.plants.map((p: any) => p.id));
  const mineIds = new Set(mine.value.map((p: any) => p.id));
  return recent.items.filter((r) => known.has(r.pid) || mineIds.has(r.pid) || (desk.on && r.pid.startsWith('local-') && !mineLoaded.value))
    .filter((r) => !isStu.value || r.pid.startsWith('local-'))
    .slice(0, 8).map((r) => {
      const p = session.plants.find((x: any) => x.id === r.pid);
      return { ...r, name: p?.name || r.name, img: thumbOf(r.pid) || sketchUrl(r.sketch), st: STC(p) };
    });
});
/** Open a lesson: open directly if local (aid); otherwise, open school assignments on the teaching page if "Work Locally" has not been selected. */
function openItem(aid: number) { if (aid) openLesson(aid); else router.push('/teach'); }
function openPlant(pid: string) { router.push(`/p/${encodeURIComponent(pid)}/workbench`); }
function ago(t: number) {
  const s = (Date.now() - t) / 1000;
  if (s < 60) return $t('common.justNow'); if (s < 3600) return $t('common.n0MinAgo', [Math.floor(s / 60)]); if (s < 86400) return $t('common.n0HoursAgo', [Math.floor(s / 3600)]);
  if (s < 86400 * 7) return $t('welcome.n0DaysAgo', [Math.floor(s / 86400)]);
  const d = new Date(t); return $t('welcome.n01', [d.getMonth() + 1, d.getDate()]);
}

// ---------- Create new ----------
const tplRaw = ref<any[]>([]);
const ORDER = ['blank', 'showcase', 'machining', 'foundry', 'integrated'];
const tpls = computed(() => {
  const list = tplRaw.value.map((t) => ({ ...t, img: sketchUrl(t.sketch), groupShort: shortGroup(t.group || '', t.key) }));
  // Pick a few from each category: blank, full demo, full factory / course line, control unit demo; up to 8 (the rest under "More Options").
  const pick: any[] = [];
  const by = (f: (t: any) => boolean, n: number) => { for (const t of list.filter((x) => f(x) && !pick.includes(x))) { if (n-- <= 0) break; pick.push(t); } };
  by((t) => t.key === 'blank', 1); by((t) => t.key === 'showcase', 1);
  by((t) => String(t.key).startsWith('course:'), 3); by((t) => ORDER.includes(t.key), 3);
  by((t) => String(t.key).startsWith('cells/'), 8 - pick.length);     // Fill 8 slots: two rows of 4 at 1680 width; one row of 6 + one row of 2 at 2560.
  return pick.slice(0, 8);
});
function shortGroup(g: string, key: string) {
  if (key === 'blank') return $t('welcome.blank'); if (key === 'showcase') return $t('welcome.fullDemo');
  if (key.startsWith('cells/')) return $t('welcome.plcControlUnit'); if (key.startsWith('course:')) return g.replace(/^(\u8bfe\u7a0b\uff1a|Course:\s*)/, '').replace(/\s*[\uff08(][^\uff09)]*[\uff09)]/, '');
  return g || $t('plants.entireFactory');
}
const nd = reactive<{ open: boolean; t: any; name: string; busy: boolean }>({ open: false, t: null, name: '', busy: false });
function pickTpl(t: any) { if (!t) return; nd.t = t; nd.name = t.key === 'blank' ? $t('plants.newFactory2') : String(t.name).replace(/\s*[\uff08(][^\uff09)]*[\uff09)]/g, '').slice(0, 30); nd.open = true; }
async function create() {
  if (!nd.t || nd.busy) return;
  nd.busy = true;
  try {
    let id = '';
    if (mineMode.value) id = (await post('/api/client/myplants', { name: nd.name || nd.t.name, template: nd.t.key })).id;
    else id = (await post('/api/plants', { name: nd.name || $t('plants.newFactory2'), template: nd.t.key })).id;
    try { session.plants = (await get('/api/overview', true)).plants; } catch { /* */ }
    nd.open = false;
    openPlant(id);
  } finally { nd.busy = false; }
}

// ---------- Student: lessons, assignments, my factories ----------
const cont = computed(() => {
  let aid = 0; try { aid = Number(localStorage.getItem('vf_teach_aid') || 0); } catch { /* */ }
  const find = (pred: (l: any) => boolean) => {
    for (const c of learn.courses) for (const ch of c.chapters || []) for (const l of ch.lessons || []) if (pred(l)) return { c, ch, l };
    return null;
  };
  const hit = (aid && find((l) => l.aid === aid)) || (() => { const c = learn.courses.find((x: any) => x.next); return c ? find((l) => l.aid === c.next) : null; })();
  if (!hit && school.value) {
    // Desktop client online: school-server lessons (local_aid exists after "Work Locally"); click to open under school assignments on the "Teaching" page.
    const sc = (school.value.courses || []).find((c: any) => c.next);
    if (sc) for (const ch of sc.chapters || []) for (const l of ch.lessons || []) if (l.aid === sc.next)
      return { aid: l.local_aid || 0, title: l.title, course: sc.name, chapter: ch.title, kind: l.kind, done: sc.done, total: sc.total, best: l.best, cid: sc.course, chid: ch.id, school: true };
  }
  if (!hit) {
    const t = learn.tasks.find((x: any) => x.id === aid) || learn.tasks.find((x: any) => x.state !== 'done');
    return t ? { aid: t.id, title: t.title, course: t.class_name || $t('common.working'), chapter: t.scene_name || '', kind: t.kind, done: t.state === 'done' ? 1 : 0, total: 1, best: t.best, cid: '', chid: '' } : null;
  }
  return { aid: hit.l.aid, title: hit.l.title, course: hit.c.name, chapter: hit.ch.title, kind: hit.l.kind, done: hit.c.done, total: hit.c.total, best: hit.l.best, cid: hit.c.course, chid: hit.ch.id };
});
const myItems = ref<any[]>([]);
const school = ref<any>(null);       // School-server lessons and assignments when the desktop client is online (/api/client/school/my)
const schoolItems = computed(() => {
  const s2 = school.value; if (!s2) return [];
  const out: any[] = [];
  for (const c of s2.courses || []) for (const ch of c.chapters || []) for (const l of ch.lessons || []) out.push({ id: l.local_aid || 0, title: l.title, class_name: c.class_name || $t('opsApp.school'), due: l.due, state: l.state, locked: l.locked, overdue: !!(l.due && l.due < new Date().toISOString().slice(0, 16).replace('T', ' ')), school: true });
  for (const t of s2.tasks || []) out.push({ ...t, id: t.local_aid || 0, school: true });
  return out;
});
const due = computed(() => [...myItems.value, ...schoolItems.value].filter((a) => a.due && a.state !== 'done' && !a.locked).sort((a, b) => String(a.due).localeCompare(String(b.due))));
const soon = (d: string) => { const t = Date.parse(String(d).replace(' ', 'T')); return Number.isFinite(t) && t - Date.now() < 2 * 86400e3; };
const mine = ref<any[]>([]), mineLoaded = ref(false);

// ---------- Teacher: class progress, pending review ----------
const classes = ref<any[]>([]), review = ref<any[]>([]), reviewTotal = ref(0), tLoaded = ref(false);
async function loadTeacher() {
  const as: any[] = await get('/api/teach/assignments', true).catch(() => []);
  const m = new Map<string, any>();
  for (const a of as) {
    const k = a.class_name || $t('welcome.class') + a.class_id;
    const c = m.get(k) || { name: k, n: 0, students: 0, sub: 0, slots: 0, sum: 0, cnt: 0 };
    c.n++; c.students = Math.max(c.students, a.students || 0); c.sub += a.submitted || 0; c.slots += a.students || 0;
    if (a.avg != null) { c.sum += a.avg; c.cnt++; }
    m.set(k, c);
  }
  classes.value = [...m.values()].map((c) => ({ ...c, rate: c.slots ? c.sub / c.slots : 0, avg: c.cnt ? Math.round(c.sum / c.cnt) : null })).slice(0, 6);
  // Pending review: recent assignments with submissions where each student's latest submission is still unreviewed.
  const rows: any[] = [];
  for (const a of as.filter((x) => x.submitted).slice(0, 8)) {
    const subs: any[] = await get(`/api/teach/assignments/${a.id}/submissions`, true).catch(() => []);
    const latest = new Map<string, any>();
    for (const s of subs) if (!s.trial && !latest.has(s.username)) latest.set(s.username, s);
    const n = [...latest.values()].filter((s) => !s.reviewed_at).length;
    if (n) rows.push({ id: a.id, title: a.title, class_name: a.class_name, n });
  }
  review.value = rows.slice(0, 5); reviewTotal.value = rows.reduce((x, r) => x + r.n, 0);
  tLoaded.value = true;
}

// ---------- Admin: server status ----------
const srv = reactive<any>({ version: '', sandbox: null, users: null, ports: null });
const plantsRunning = computed(() => session.plants.filter((p: any) => !p.paused && !p.off).length);
const alarmTotal = computed(() => session.plants.reduce((s: number, p: any) => s + (p.alarms || 0), 0));
const clientTotal = computed(() => session.plants.reduce((s: number, p: any) => s + (p.clients || 0), 0));
async function loadAdmin() {
  const [h, ov, sb, us] = await Promise.all([fetch('/api/health').then((r) => r.json()).catch(() => ({})), get('/api/overview', true).catch(() => null),
    get('/api/teach/sandboxes', true).catch(() => null), get('/api/admin/users', true).catch(() => null)]);
  srv.version = h.version || ''; srv.sandbox = sb; srv.users = us?.users?.length ?? null;
  if (ov) { session.plants = ov.plants; srv.ports = ov.ports; }
}

// ---------- Learning ----------
const tuts = computed(() => tutorials.filter((t) => !t.roles || t.roles.includes(role.value)).slice(0, 5));
function lessonAid(course?: string, lesson?: string) {
  for (const c of learn.courses) if (c.course === course) for (const ch of c.chapters || []) for (const l of ch.lessons || []) if (l.id === lesson && !l.locked) return l.aid;
  return 0;
}
const PLC_LESSON_CH: Record<string, string> = { s01: 'c1', s02: 'c1', s03: 'c1', s08: 'c1', s04: 'c2', s05: 'c2', s06: 'c2', s07: 'c2', s09: 'c3', s10: 'c3', s11: 'c3', s12: 'c3', s13: 'c3', s14: 'c4', s15: 'c4' };
const tutCover = (t: Tutorial) => (t.course ? coverFor(t.course, PLC_LESSON_CH[t.lesson || ''] || '') : '');
function runTut(t: Tutorial) {
  if (t.run) return t.run();
  const aid = lessonAid(t.course, t.lesson);
  if (aid) return openLesson(aid);
  if (showLearner.value) return router.push('/teach');
  if (['teacher', 'admin'].includes(role.value)) return router.push({ path: '/teach', query: { tab: 'courses' } });
  openHelp(t.help || 'course', 'welcome');
}

// ---------- Tips ----------
const tips = [
  $t('welcome.pressCtrlKToOpen'),
  $t('welcome.pressF1ToOpenContextual'),
  $t('welcome.whenPausedInTheWorkbench'),
  $t('welcome.selectEquipmentAndPressF9'),
  $t('welcome.rightClickEquipmentWatchValues'),
  $t('welcome.ctrlFSearchesMoreThan'),
  $t('welcome.simulateFromHereCopiesThe'),
  $t('welcome.experimentComparisonsUseTheSame'),
  $t('welcome.thePlcIOTable'),
  $t('welcome.in3dDoubleClickEquipment'),
  $t('welcome.whenDrawingWallsInThe'),
  $t('welcome.selectASectionOfThe'),
];
const tipI = ref(Math.floor(Math.random() * tips.length));
let tipT: any;
function nextTip() { tipI.value++; clearInterval(tipT); tipT = setInterval(() => tipI.value++, 12000); }
function openDocs() { window.open('/docs'); }

onMounted(async () => {
  tipT = setInterval(() => tipI.value++, 12000);
  const jobs: Promise<any>[] = [loadLearn(true)];
  if (isStu.value) jobs.push(get('/api/teach/my', true).then((r) => { myItems.value = r || []; }).catch(() => {}));
  if (isStu.value && desk.on && desk.mode === 'server') jobs.push(get('/api/client/school/my', true).then((r) => { school.value = r; }).catch(() => {}));
  if (mineMode.value) jobs.push(get('/api/client/myplants', true).then((r) => { mine.value = r.plants || []; tplRaw.value = r.templates || []; }).catch(() => {}).finally(() => { mineLoaded.value = true; }));
  else if (canCreate.value) jobs.push(get('/api/plants', true).then((r) => {
    const info = r.template_info || {};
    tplRaw.value = Object.entries(r.templates || {}).map(([key, name]) => ({ key, name, ...(info[key] || {}) }));
  }).catch(() => {}));
  if (role.value === 'teacher' || role.value === 'admin') jobs.push(loadTeacher().catch(() => { tLoaded.value = true; }));
  if (role.value === 'admin' && desk.mode !== 'standalone') jobs.push(loadAdmin());
  await Promise.all(jobs);
});
onUnmounted(() => { clearInterval(tipT); });
</script>


<style scoped>
/* 5.0.1: same light theme as HoneyMOM (white cards + thin borders + cobalt blue primary, amber accents only) */
.wc { min-height: 100%; color: var(--hm-text); padding: var(--hm-sp-4) var(--hm-sp-5) var(--hm-sp-8); }
.wc-wrap { max-width: calc(1640px * var(--hm-scale)); margin: 0 auto; display: flex; flex-direction: column; gap: var(--hm-gap); }
.muted { color: var(--hm-text-3); } .grow { flex: 1; }

/* Banner: light card with illustration on the right */
.wc-hero { position: relative; border-radius: var(--hm-r-lg); overflow: hidden; color: var(--hm-text); min-height: 196px; display: flex; flex-direction: column;
  background-color: var(--hm-surface); border: 1px solid var(--hm-border); box-shadow: var(--hm-e1);
  background-image: radial-gradient(900px 320px at 90% -30%, rgba(11, 165, 196, .08), transparent 60%), radial-gradient(600px 260px at 105% 120%, rgba(217, 130, 43, .06), transparent 60%); }
.wc-hero:not(.art)::after { content: ''; position: absolute; inset: 0; pointer-events: none;
  background-image: linear-gradient(var(--hm-grid-line) 1px, transparent 1px), linear-gradient(90deg, var(--hm-grid-line) 1px, transparent 1px); background-size: 24px 24px;
  -webkit-mask-image: linear-gradient(90deg, transparent 30%, #000 75%); mask-image: linear-gradient(90deg, transparent 30%, #000 75%); }
.wc-hero-img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; object-position: right center; z-index: 0;
  filter: saturate(.7) brightness(1.03); -webkit-mask-image: linear-gradient(90deg, transparent 20%, #000 55%); mask-image: linear-gradient(90deg, transparent 20%, #000 55%); }
.wc-hero.art .wc-hello { max-width: 46%; }
.wc-hero-in { position: relative; z-index: 1; display: flex; gap: 20px; align-items: flex-start; padding: 26px 30px 12px; flex: 1; }
.wc-hello { flex: 1; min-width: 0; }
.wc-kicker { color: var(--hm-amber-ink); letter-spacing: 1.2px; font-size: var(--hm-fs-xs); font-weight: var(--hm-fw-medium); }
.wc-hello h1 { margin: 6px 0 6px; font-size: var(--hm-fs-2xl); font-weight: var(--hm-fw-semibold); letter-spacing: .3px; color: var(--hm-text); }
.wc-hello p { margin: 0 0 16px; color: var(--hm-text-2); font-size: var(--hm-fs-md); max-width: 640px; }
.wc-cta { display: flex; gap: 8px; flex-wrap: wrap; }
.wc-cta :deep(.el-button:not(.el-button--primary)) { background: var(--hm-glass-strong); }
.wc-cta :deep(.el-icon) { margin-right: 4px; }
.wc-hero-bar { position: relative; z-index: 1; display: flex; align-items: center; gap: 10px; padding: 8px 30px 14px; }
.wc-hero-bar :deep(.el-checkbox__label) { color: var(--hm-text-2); font-size: var(--hm-fs-xs); }
.wc-theme { border: 0; background: transparent; color: var(--hm-text-2); border-radius: var(--hm-r-sm); height: 26px; padding: 0 6px; cursor: pointer; display: inline-flex; align-items: center; gap: 5px; font: inherit; font-size: var(--hm-fs-xs); }
.wc-theme:hover { background: var(--hm-primary-soft); color: var(--hm-primary); }
.wc-sep { width: 1px; height: 14px; background: var(--hm-border-strong); }

/* Two columns */
.wc-grid { display: grid; grid-template-columns: minmax(0, 1fr) calc(340px * var(--hm-scale)); gap: var(--hm-gap); align-items: start; }
.wc-main, .wc-side { display: flex; flex-direction: column; gap: var(--hm-gap); min-width: 0; }
.wc-sec { background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); padding: 14px 16px 16px; box-shadow: var(--hm-e1); }
.wc-sec > header { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; min-height: 22px; }
.wc-sec h3 { margin: 0; font-size: var(--hm-fs-md); font-weight: var(--hm-fw-semibold); display: flex; align-items: center; gap: 6px; color: var(--hm-text); }
.wc-sec > header small { font-size: var(--hm-fs-xs); }
.wc-link { cursor: pointer; font-size: var(--hm-fs-xs); color: var(--hm-primary); white-space: nowrap; } .wc-link:hover { text-decoration: underline; }
.wc-skel { height: 64px; border-radius: var(--hm-r-md); background: linear-gradient(90deg, var(--hm-surface-2), var(--hm-surface-3), var(--hm-surface-2)); background-size: 200% 100%; animation: wc-sk 1.2s infinite linear; }
@keyframes wc-sk { to { background-position: -200% 0; } }

/* Cards: recent files, templates */
.wc-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(calc(210px * var(--hm-scale)), 1fr)); gap: 12px; }
.wc-cards.crs .wc-pc-m { gap: 5px; }
.wc-pc { position: relative; border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); overflow: hidden; cursor: pointer; background: var(--hm-surface);
  transition: border-color var(--hm-dur-2) var(--hm-ease), box-shadow var(--hm-dur-2) var(--hm-ease), transform var(--hm-dur-2) var(--hm-ease); }
.wc-pc:hover { border-color: var(--el-color-primary-light-5); box-shadow: var(--hm-e2); transform: translateY(-1px); }
.wc-thumb { position: relative; aspect-ratio: 16 / 9; background: var(--hm-surface-2); border-bottom: 1px solid var(--hm-border); }
.wc-thumb img { width: 100%; height: 100%; object-fit: cover; display: block; }
.wc-blank { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; color: var(--hm-text-3);
  background-image: linear-gradient(var(--hm-border) 1px, transparent 1px), linear-gradient(90deg, var(--hm-border) 1px, transparent 1px); background-size: 20px 20px; }
.wc-blank .el-icon { background: var(--hm-surface); border: 1.5px dashed var(--hm-text-3); border-radius: var(--hm-r-md); padding: 8px; width: 48px; height: 48px; }
.wc-st, .wc-grp { position: absolute; left: 8px; top: 8px; font-size: var(--hm-fs-2xs); border-radius: var(--hm-r-pill); padding: 1px 8px; line-height: 18px;
  background: var(--hm-glass-strong); color: var(--hm-text-2); border: 1px solid var(--hm-hairline); }
.wc-st.r { background: var(--hm-run-soft); color: var(--hm-run-ink); } .wc-st.p { background: var(--hm-idle-soft); color: var(--hm-idle-ink); } .wc-st.o { background: var(--hm-offline-soft); color: var(--hm-offline-ink); }
.wc-pc-m { padding: 8px 10px 10px; display: grid; gap: 2px; }
.wc-pc-m b { font-size: var(--hm-fs-sm); font-weight: var(--hm-fw-semibold); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wc-pc-m small { font-size: var(--hm-fs-xs); }
.wc-2l { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.5; min-height: 3em; }
.wc-x { position: absolute; right: 6px; top: 6px; border: 1px solid var(--hm-border); width: 24px; height: 24px; border-radius: var(--hm-r-sm); background: var(--hm-surface); color: var(--hm-text-2); cursor: pointer; display: none; align-items: center; justify-content: center; }
.wc-x:hover { color: var(--hm-fault-ink); border-color: var(--hm-fault); }
.wc-pc:hover .wc-x { display: inline-flex; }

/* Resume last lesson */
.wc-cont { display: flex; align-items: center; gap: 14px; padding: 12px; border-radius: var(--hm-r-md); background: var(--hm-surface-2); border: 1px solid var(--hm-border); cursor: pointer; }
.wc-cont:hover { border-color: var(--el-color-primary-light-5); }
.wc-cont-cv { width: 112px; height: 63px; object-fit: cover; border-radius: var(--hm-r-md); flex: none; border: 1px solid var(--hm-border); }
.wc-cont-ic { width: 52px; height: 52px; border-radius: var(--hm-r-lg); display: flex; align-items: center; justify-content: center; color: var(--hm-primary); background: var(--hm-primary-soft); flex: none; }
.wc-cont-ic.plant { color: var(--hm-cyan-ink); background: var(--hm-cyan-soft); }
.wc-cont-m { flex: 1; min-width: 0; display: grid; gap: 4px; } .wc-cont-m b { font-size: var(--hm-fs-lg); font-weight: var(--hm-fw-semibold); }
.wc-prog { height: 6px; border-radius: 99px; background: var(--hm-surface-3); overflow: hidden; max-width: 420px; }
.wc-prog i { display: block; height: 100%; background: var(--hm-primary); border-radius: 99px; }

/* List rows */
.wc-rows { display: grid; gap: 2px; }
.wc-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: var(--hm-r-md); cursor: pointer; font-size: var(--hm-fs-sm); min-width: 0; }
.wc-row:hover { background: var(--hm-surface-3); }
.wc-row-ic { color: var(--hm-text-3); flex: none; } .wc-row-t { font-weight: var(--hm-fw-medium); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.wc-row small { white-space: nowrap; }
.wc-due { font-size: var(--hm-fs-xs); color: var(--hm-text-3); white-space: nowrap; } .wc-due.soon { color: var(--hm-idle-ink); } .wc-due.over { color: var(--hm-fault-ink); }
.wc-badge { font-size: var(--hm-fs-xs); background: var(--hm-amber-soft); color: var(--hm-amber-ink); border-radius: var(--hm-r-pill); padding: 1px 9px; }
.wc-classes { display: grid; grid-template-columns: repeat(auto-fill, minmax(calc(230px * var(--hm-scale)), 1fr)); gap: 10px; }
.wc-cls { border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); padding: 10px 12px; display: grid; gap: 5px; cursor: pointer; }
.wc-cls:hover { border-color: var(--el-color-primary-light-5); background: var(--hm-surface-2); }

/* Server status (KPI tiles) */
.wc-ok { display: inline-flex; align-items: center; gap: 5px; font-size: var(--hm-fs-xs); color: var(--hm-run-ink); background: var(--hm-run-soft); border-radius: var(--hm-r-pill); padding: 0 8px; line-height: 20px; }
.wc-ok i { width: 6px; height: 6px; border-radius: 50%; background: var(--hm-run); }
.wc-kpis { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.wc-kpis > div { position: relative; background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); padding: 9px 12px 9px 14px; min-width: 0; overflow: hidden; }
.wc-kpis > div::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--hm-border-strong); opacity: .7; }
.wc-kpis small { display: block; color: var(--hm-text-3); font-size: var(--hm-fs-xs); }
.wc-kpis b { font-size: var(--hm-fs-xl); font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; font-weight: 600; white-space: nowrap; color: var(--hm-text); }
.wc-kpis i { font-style: normal; font-size: var(--hm-fs-xs); color: var(--hm-text-3); margin-left: 2px; font-family: var(--hm-font); font-weight: 400; }
.wc-kpis .ok { color: var(--hm-run-ink); } .wc-kpis .bad { color: var(--hm-fault-ink); }
.wc-ports { margin-top: 8px; }

/* Right column */
.wc-list { display: grid; grid-template-columns: minmax(0, 1fr); gap: 2px; }
.wc-li > div { min-width: 0; } .wc-li .wc-chip { display: inline-block; max-width: 100%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: middle; }
.wc-li { display: flex; gap: 10px; padding: 9px 8px; border-radius: var(--hm-r-md); cursor: pointer; } .wc-li:hover { background: var(--hm-surface-3); }
.wc-li-ic { flex: none; width: 30px; height: 30px; border-radius: var(--hm-r-md); background: var(--hm-primary-soft); color: var(--hm-primary); display: inline-flex; align-items: center; justify-content: center; font-size: 16px; margin-top: 1px; }
.wc-li-cv { flex: none; width: 64px; height: 36px; object-fit: cover; border-radius: var(--hm-r-sm); margin-top: 2px; border: 1px solid var(--hm-border); }
.wc-li b { font-size: var(--hm-fs-sm); font-weight: var(--hm-fw-semibold); } .wc-li p { margin: 2px 0 0; font-size: var(--hm-fs-xs); color: var(--hm-text-3); line-height: 1.55; }
.wc-chip { margin-left: 6px; font-size: var(--hm-fs-2xs); color: var(--hm-text-2); background: var(--hm-surface-2); border: 1px solid var(--hm-border); border-radius: var(--hm-r-pill); padding: 0 6px; white-space: nowrap; }
.wc-res { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
.wc-res a { display: flex; align-items: center; gap: 7px; padding: 8px 10px; border-radius: var(--hm-r-md); border: 1px solid var(--hm-border); cursor: pointer; font-size: var(--hm-fs-xs); color: var(--hm-text); text-decoration: none; }
.wc-res a:hover { border-color: var(--el-color-primary-light-5); background: var(--hm-primary-soft); } .wc-res a .el-icon { color: var(--hm-primary); } .wc-res a small { margin-left: auto; }
.wc-tip p { margin: 0; font-size: var(--hm-fs-sm); line-height: 1.75; min-height: 4.4em; color: var(--hm-text-2); }
.wc-tip h3 .el-icon { color: var(--hm-amber); }
.wc-tipn { border: 1px solid var(--hm-border); background: transparent; color: var(--hm-text-3); border-radius: var(--hm-r-sm); width: 26px; height: 24px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; }
.wc-tipn:hover { color: var(--hm-primary); border-color: var(--hm-primary); }
.wc-dots { display: flex; gap: 4px; margin-top: 10px; } .wc-dots i { width: 5px; height: 5px; border-radius: 50%; background: var(--hm-border-strong); } .wc-dots i.on { background: var(--hm-primary); width: 14px; border-radius: 3px; }
.wc-fade-enter-active, .wc-fade-leave-active { transition: opacity .25s; } .wc-fade-enter-from, .wc-fade-leave-to { opacity: 0; }

/* New item dialog */
.wc-nd { display: flex; gap: 14px; }
.wc-nd-pv { width: 220px; flex: none; aspect-ratio: 16 / 9; border-radius: var(--hm-r-md); overflow: hidden; border: 1px solid var(--hm-border); background: var(--hm-surface-2); }
.wc-nd-pv img { width: 100%; height: 100%; object-fit: cover; display: block; }
.wc-nd-m { flex: 1; display: grid; gap: 6px; align-content: start; } .wc-nd-m b { font-size: var(--hm-fs-md); } .wc-nd-m p { margin: 0; line-height: 1.6; }

@media (max-width: 1250px) { .wc-grid { grid-template-columns: minmax(0, 1fr); } .wc-kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } }
@media (max-width: 760px) { .wc-hero.art .wc-hello { max-width: none; } .wc { padding: 10px; } .wc-hero-in { flex-direction: column; padding: 18px; } .wc-nd { flex-direction: column; } .wc-nd-pv { width: 100%; } }
html.compact .wc { padding: 10px 14px 20px; } html.compact .wc-hero { min-height: 160px; } html.compact .wc-hero-in { padding: 18px 22px 8px; }
</style>