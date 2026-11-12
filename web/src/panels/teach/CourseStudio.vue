<template>
  <div class="cs" data-k="course-studio">
    <section class="cs-hero">
      <div>
        <h1>{{ $t('common.courses') }}</h1>
        <p>{{ $t('courseStudio.createCoursesWithPlcLabs') }}</p>
        <div class="vp-row" style="margin-top: 12px">
          <el-button type="primary" data-k="new-course" @click="webOnly ? hint('/courses?new=1', $t('courseStudio.newCourse')) : create()"><el-icon><Plus /></el-icon>{{ $t('courseStudio.newCourse') }}</el-button>
          <el-button @click="pubOpen = true; pubCourse = ''"><el-icon><Promotion /></el-icon>{{ $t('courseStudio.publishCourseToClass') }}</el-button>
          <span class="vp-small vp-muted">{{ $t('courseStudio.classesAssignmentsAndGradingAre') }}</span>
          <span v-if="webOnly" class="vp-small vp-muted" data-k="studio-saas-note">{{ $t('courseStudio.honeyCloudCreateAndPreview') }}</span>
          <span v-else-if="clientSaas" class="vp-small vp-muted" data-k="studio-client-note">{{ $t('courseStudio.createTestAndPreviewCourses') }}</span>
        </div>
      </div>
      <img v-if="hero.src" class="cs-art" :src="hero.src" :srcset="hero.srcset" alt="" />
    </section>

    <h2 class="cs-h">{{ $t('courseStudio.myCourses') }} <span class="vp-small vp-muted">{{ $t('courseStudio.n0Courses', [mine.length]) }}</span></h2>
    <div v-if="mine.length" class="cs-grid" data-k="my-courses">
      <article v-for="c in mine" :key="c.id" class="cc" :data-course="c.id">
        <div class="cc-cover" @click="editOf(c)"><img v-if="courseCover(c)" :src="courseCover(c)" alt="" />
          <span class="cc-badge" :class="c.version ? (c.dirty ? 'doing' : 'done') : ''">{{ c.remote ? $t('courseStudio.cloudV0', [c.version]) : c.version ? (c.dirty ? $t('courseStudio.v0UnpublishedChanges', [c.version]) : $t('courseEditor.publishedV0', [c.version])) : $t('common.draft') }}</span></div>
        <div class="cc-body">
          <div class="cc-kinds"><span v-for="k in c.kinds" :key="k" class="kchip" :class="k">{{ KIND_CN[k] || k }}</span></div>
          <h3 class="cc-title">{{ c.name }}</h3>
          <p class="cc-desc">{{ c.desc || $t('courseStudio.noDescriptionYet') }}</p>
          <div class="vp-small vp-muted">{{ $t('courseStudio.n0LessonsUpdated1', [c.lessons, (c.updated || '').slice(0, 16)]) }}</div>
        </div>
        <footer class="cc-foot">
          <el-button v-if="c.remote" size="small" type="primary" plain data-k="fetch-course" :loading="busy === c.id" @click="fetchRemote(c)"><el-icon><Download /></el-icon>{{ $t('courseStudio.downloadToEditLocally') }}</el-button>
          <el-button v-else size="small" type="primary" plain data-k="edit-course" @click="editOf(c)"><el-icon><Edit /></el-icon>{{ webOnly ? $t('courseStudio.editInDesktopClient') : $t('common.edit') }}</el-button>
          <el-button size="small" :disabled="!c.version" :title="c.version ? '' : $t('courseStudio.publishFromTheEditorFirst')" @click="pubOpen = true; pubCourse = c.id"><el-icon><Promotion /></el-icon>{{ $t('common.publishToClass') }}</el-button>
          <el-dropdown v-if="!webOnly && !c.remote" trigger="click" @command="(k: string) => cmd(k, c)">
            <el-button size="small" text><el-icon><MoreFilled /></el-icon></el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item command="copy">{{ $t('common.duplicate') }}</el-dropdown-item>
              <el-dropdown-item command="del" divided>{{ $t('courseStudio.deleteDraft') }}</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
        </footer>
      </article>
    </div>
    <div v-else class="cs-empty">
      <img v-if="empty.src" :src="empty.src" :srcset="empty.srcset" alt="" />
      <b>{{ $t('courseStudio.youHavenTCreatedAny') }}</b><span>{{ $t('courseStudio.clickNewCourseToStart') }}</span>
    </div>

    <h2 class="cs-h">{{ $t('common.courseLibrary') }} <span class="vp-small vp-muted">{{ $t('courseStudio.builtInCoursesAndCourses') }}</span></h2>
    <div class="cs-grid" data-k="library">
      <article v-for="c in library" :key="c.id" class="cc lib" :data-course="c.id">
        <div class="cc-cover"><img v-if="courseCover(c)" :src="courseCover(c)" alt="" />
          <span class="cc-badge">{{ c.origin === 'builtin' ? $t('scenarios.builtIn') : $t('courseStudio.sharedByTeachers') }}</span></div>
        <div class="cc-body">
          <div class="cc-kinds"><span v-for="k in c.kinds" :key="k" class="kchip" :class="k">{{ KIND_CN[k] || k }}</span></div>
          <h3 class="cc-title">{{ c.name }}</h3>
          <p class="cc-desc">{{ c.desc }}</p>
          <div class="vp-small vp-muted">{{ $t('courseHome.n0Chapters1Lessons', [c.chapters.length, c.lessons]) }}<template v-if="c.classes?.length"> {{ $t('courseStudio.publishedTo0', [c.classes.map((x: any) => x.class_name).join($t('common.k360'))]) }}</template></div>
        </div>
        <footer class="cc-foot">
          <el-button size="small" type="primary" plain @click="pubOpen = true; pubCourse = c.id"><el-icon><Promotion /></el-icon>{{ $t('common.publishToClass') }}</el-button>
          <el-button size="small" data-k="copy-course" @click="webOnly ? hint(`/courses?copy=${encodeURIComponent(c.id)}`, $t('courseStudio.copy0ToEdit', [c.name])) : create(c.id)"><el-icon><CopyDocument /></el-icon>{{ $t('courseStudio.copyToEdit') }}</el-button>
        </footer>
      </article>
    </div>
    <el-dialog v-model="hintOpen" :title="hintTitle" width="min(680px, 96vw)" append-to-body data-k="studio-client-dialog">
      <ClientLink :path="hintPath" :title="$t('courseStudio.createCoursesInTheDesktop')" :steps="$t('courseStudio.openCoursesInTheDesktop')" />
    </el-dialog>
    <el-dialog v-model="pubOpen" :title="$t('courseStudio.publishCourseToClass')" width="820px" append-to-body destroy-on-close class="fit-dialog">
      <CoursePublish :course="pubCourse" @done="onPublished" @cancel="pubOpen = false" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// 4.6 Teacher "Courses": authored courses (draft / published) + course library (built-in, shared); create, duplicate, edit, publish to classes.
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { del, desk, get, post, saasServer } from '../../api';
import ClientLink from '../../components/ClientLink.vue';
import { themed } from '../../brand';
import { courseCover, KIND_CN } from './courses';
import CoursePublish from './CoursePublish.vue';
import './panel.css';

const emit = defineEmits<{ (e: 'edit', id: string): void }>();
const mine = ref<any[]>([]);
const all = ref<any[]>([]);
const pubOpen = ref(false);
const pubCourse = ref('');
const hero = computed(() => themed('courses-hero'));
const empty = computed(() => themed('empty-courses'));
const library = computed(() => all.value.filter((c) => c.origin !== 'authored' || !mine.value.some((m) => m.id === c.id)));
async function load() { [mine.value, all.value] = await Promise.all([get('/api/teach/authoring'), get('/api/teach/courses')]); }
// 5.0 SaaS: browser authoring unavailable (factories run in the desktop client) — replace buttons with "Open in Desktop Client"; download courses authored on other computers to edit locally.
const webOnly = computed(() => !desk.on && saasServer());
const clientSaas = computed(() => desk.on && saasServer());
const hintOpen = ref(false), hintPath = ref(''), hintTitle = ref('');
function hint(path: string, title: string) { hintPath.value = path; hintTitle.value = title; hintOpen.value = true; }
function editOf(c: any) {
  if (webOnly.value) return hint(`/courses?edit=${encodeURIComponent(c.id)}`, $t('courseStudio.edit0', [c.name]));
  if (c.remote) return fetchRemote(c);
  emit('edit', c.id);
}
const busy = ref('');
async function fetchRemote(c: any) {
  busy.value = c.id;
  try { await post(`/api/teach/authoring/${encodeURIComponent(c.id)}/fetch`, {}); ElMessage.success($t('courseStudio.downloadedToThisComputerContinue')); emit('edit', c.id); } finally { busy.value = ''; }
}
async function create(copy?: string) {
  let name = '';
  if (!copy) {
    const r = await ElMessageBox.prompt($t('courseEditor.courseName'), $t('courseStudio.newCourse'), { inputValue: '', inputPlaceholder: $t('courseStudio.eGPlcBasicsQuiz'), confirmButtonText: $t('courseStudio.createAndEdit'), inputValidator: (v) => !!String(v || '').trim() || $t('courseStudio.enterAName') }).catch(() => null);
    if (!r) return;
    name = r.value;
  }
  const v = await post('/api/teach/authoring', copy ? { copy } : { name });
  ElMessage.success(copy ? $t('courseStudio.copyCreatedEditItThen') : $t('courseStudio.created'));
  emit('edit', v.id);
}
async function cmd(k: string, c: any) {
  if (k === 'copy') return create(c.version ? c.id : undefined);
  if (k === 'del') {
    await ElMessageBox.confirm($t('courseStudio.deleteDraft0VersionsAlready', [c.name]), $t('common.delete'), { type: 'warning' });
    await del(`/api/teach/authoring/${c.id}`);
    await load();
  }
}
function onPublished() { pubOpen.value = false; load(); }
onMounted(load);
defineExpose({ load });
</script>

<style scoped>
/* 5.0.1: light theme (shared with HoneyMOM) */
.cs { color: var(--hm-text); max-width: calc(1720px * var(--hm-scale)); margin: 0 auto; padding: var(--hm-sp-4) var(--hm-sp-5) 40px; box-sizing: border-box; }
.cs-hero { position: relative; border-radius: var(--hm-r-lg); overflow: hidden; border: 1px solid var(--hm-border); min-height: 190px; box-shadow: var(--hm-e1);
  background: radial-gradient(700px 260px at 92% -20%, rgba(11, 165, 196, .08), transparent 60%), radial-gradient(500px 220px at 100% 120%, rgba(217, 130, 43, .06), transparent 60%), var(--hm-surface); display: flex; }
.cs-hero > div { position: relative; z-index: 1; padding: 24px 28px; max-width: 640px; }
.cs-hero h1 { margin: 0 0 6px; font-size: var(--hm-fs-2xl); font-weight: var(--hm-fw-semibold); letter-spacing: .5px; }
.cs-hero p { margin: 0; line-height: 1.75; font-size: var(--hm-fs-sm); color: var(--hm-text-2); }
.cs-art { position: absolute; right: 0; top: 0; height: 100%; max-width: 62%; object-fit: cover; object-position: right center; pointer-events: none;
  filter: saturate(.7) brightness(1.03); -webkit-mask-image: linear-gradient(90deg, transparent, #000 28%); mask-image: linear-gradient(90deg, transparent, #000 28%); }
.cs-h { font-size: var(--hm-fs-lg); font-weight: var(--hm-fw-semibold); margin: 24px 0 12px; display: flex; align-items: baseline; gap: 10px; }
.cs-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(calc(290px * var(--hm-scale)), 1fr)); gap: var(--hm-gap); }
.cc { display: flex; flex-direction: column; background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); overflow: hidden; box-shadow: var(--hm-e1);
  transition: box-shadow var(--hm-dur-2) var(--hm-ease), transform var(--hm-dur-2) var(--hm-ease), border-color var(--hm-dur-2) var(--hm-ease); }
.cc:hover { transform: translateY(-1px); box-shadow: var(--hm-e2); border-color: var(--el-color-primary-light-5); }
.cc-cover { position: relative; aspect-ratio: 16 / 9; background: var(--hm-surface-2); cursor: pointer; overflow: hidden; border-bottom: 1px solid var(--hm-border); }
.cc-cover img { width: 100%; height: 100%; object-fit: cover; display: block; }
.cc-badge { position: absolute; left: 12px; top: 12px; font-size: var(--hm-fs-2xs); line-height: 18px; padding: 1px 9px; border-radius: var(--hm-r-pill); background: var(--hm-offline-soft); color: var(--hm-offline-ink); border: 1px solid var(--hm-hairline); }
.cc-badge.doing { background: var(--hm-idle-soft); color: var(--hm-idle-ink); } .cc-badge.done { background: var(--hm-run-soft); color: var(--hm-run-ink); }
.cc-body { padding: 12px 16px 4px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
.cc-kinds { display: flex; gap: 5px; flex-wrap: wrap; min-height: 20px; }
.cc-title { margin: 0; font-size: var(--hm-fs-lg); font-weight: var(--hm-fw-semibold); }
.cc-desc { margin: 0; font-size: var(--hm-fs-xs); line-height: 1.6; color: var(--hm-text-3); display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 38px; }
.cc-foot { display: flex; align-items: center; gap: 6px; padding: 10px 16px 14px; }
.kchip { font-size: var(--hm-fs-2xs); padding: 1px 7px; border-radius: var(--hm-r-xs); background: var(--hm-offline-soft); color: var(--hm-offline-ink); }
.kchip.cell { background: var(--hm-setup-soft); color: var(--hm-setup-ink); } .kchip.plant, .kchip.point { background: var(--hm-amber-soft); color: var(--hm-amber-ink); } .kchip.quiz, .kchip.factory { background: var(--hm-run-soft); color: var(--hm-run-ink); }
.kchip.diagnose { background: var(--hm-fault-soft); color: var(--hm-fault-ink); } .kchip.mes { background: var(--hm-cyan-soft); color: var(--hm-cyan-ink); }
.cs-empty { display: flex; flex-direction: column; align-items: center; gap: 6px; padding: 20px; color: var(--hm-text-3); text-align: center; background: var(--hm-surface); border: 1px dashed var(--hm-border-strong); border-radius: var(--hm-r-lg); }
.cs-empty img { width: 200px; } .cs-empty b { color: var(--hm-text); }
@media (max-width: 900px) { .cs-art { opacity: .3; } .cs { padding: 12px; } }
html.compact .cs { padding: 10px 14px 24px; } html.compact .cs-hero { min-height: 150px; }
</style>