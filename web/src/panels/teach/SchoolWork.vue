<template>
  <div class="school-work vp-card">
    <div class="vp-row sp">
      <b>{{ $t('common.schoolAssignments') }}</b>
      <span>
        <span v-if="st.connected" class="vp-small vp-muted">{{ st.url }} · {{ st.name }}</span>
        <el-button size="small" text :loading="loading" @click="load" :title="$t('common.refresh')"><el-icon><Refresh /></el-icon></el-button>
        <el-button v-if="desk.mode === 'standalone'" size="small" text data-k="sw-login" @click="toLogin" :title="$t('schoolWork.leaveStandaloneModeAndLog')">
          <el-icon><User /></el-icon>{{ $t('schoolWork.logInToSchoolServer') }}</el-button>
      </span>
    </div>
    <div v-if="!st.connected" class="vp-small vp-muted" style="margin-top: 4px">
      <template v-if="desk.mode === 'standalone'">{{ $t('schoolWork.standaloneModeNotConnectedTo') }}</template>
      <template v-else>{{ $t('schoolWork.theSchoolServerIsUnreachable') }}</template>
    </div>
    <div v-else-if="err" class="vp-small vp-fail" style="margin-top: 4px">{{ err }}</div>
    <template v-else-if="data">
      <div v-if="!items.length" class="vp-small vp-muted" style="margin-top: 4px">{{ $t('schoolWork.yourTeacherHasNotAssigned') }}</div>
      <div v-for="it in items" :key="it.aid" class="sw-item" :data-raid="it.aid">
        <span class="kind" :class="it.kind">{{ KIND_CN[it.kind] || it.kind }}</span>
        <span class="vp-grow">
          <span class="t">{{ it.title }}</span>
          <span class="vp-small vp-muted"> · {{ it.where }}{{ it.due ? $t('schoolWork.due') + it.due : '' }}</span>
        </span>
        <span class="sc" :class="it.best === null || it.best === undefined ? 'vp-muted' : it.best >= 60 ? 'vp-pass' : 'vp-fail'"
              :title="$t('schoolWork.highestScoreOnTheSchool')">{{ it.best ?? $t('schoolWork.notSubmitted') }}</span>
        <el-button size="small" :type="it.local_aid ? 'default' : 'primary'" plain :disabled="it.locked" :loading="busy === it.aid"
                   :title="it.locked ? $t('schoolWork.thisLessonIsLockedOn') : ''" @click="openIt(it)">{{ it.local_aid ? $t('common.continue') : $t('sections.workLocally') }}</el-button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// School assignments above "My Courses" in the client: list teacher-assigned work when connected to the school server. "Work Locally" installs it in a local sandbox, then it works like a course.
// The school server is the server the client logs in to (4.3 login model); no separate connection here. Direct standalone users to the login page.
import { computed, onMounted, reactive, ref } from 'vue';
import { desk, get, post, session } from '../../api';
import { router } from '../../router';
import './panel.css';

const emit = defineEmits<{ (e: 'open', localAid: number): void; (e: 'changed'): void }>();
const KIND_CN: Record<string, string> = { cell: 'PLC', plant: $t('common.line'), diagnose: $t('common.troubleshooting'), factory: $t('common.factoryDesign'), quiz: $t('common.quiz'), point: $t('common.clickToSelect'), mes: 'MES' };
const st = reactive<any>({ connected: false, url: '', name: '' });
const data = ref<any>(null);
const err = ref('');
const loading = ref(false);
const busy = ref<any>(null);

const items = computed(() => {
  const d = data.value;
  if (!d) return [];
  const out: any[] = [];
  for (const c of d.courses || []) for (const ch of c.chapters || []) for (const l of ch.lessons || [])
    out.push({ aid: l.aid, title: l.title, kind: l.kind, where: `${c.name} · ${c.class_name || ''}`, due: l.due, best: l.best, locked: l.locked, local_aid: l.local_aid });
  for (const t of d.tasks || []) out.push({ aid: t.id, title: t.title, kind: t.kind, where: t.class_name, due: t.due, best: t.best, locked: t.locked, local_aid: t.local_aid });
  return out;
});

async function load() {
  loading.value = true; err.value = '';
  try {
    const s = await get('/api/client/status', true);
    Object.assign(st, s.school || {});
    if (st.connected) data.value = await get('/api/client/school/my', true).catch((e: any) => { err.value = e.message; return null; });
  } catch { /* Not the desktop client */ } finally { loading.value = false; }
}
async function openIt(it: any) {
  busy.value = it.aid;
  try {
    const r = await post('/api/client/school/open', { remote_aid: it.aid });
    emit('open', r.local_aid);
  } finally { busy.value = null; }
}
/** Standalone → login page (end the local admin session; school assignments appear here after login). */
async function toLogin() {
  await post('/api/desktop/logout', {}).catch(() => null);
  session.token = ''; session.user = null;
  try { localStorage.removeItem('vf_token'); } catch { /* */ }
  desk.mode = '';
  router.push('/login');
}
onMounted(load);
defineExpose({ load });
</script>

<style scoped>
.school-work { margin-bottom: 10px; border-left: 3px solid var(--el-color-primary); }
.sw-item { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-top: 1px solid var(--el-border-color-extra-light); }
.sw-item:first-of-type { margin-top: 6px; }
.sw-item .t { font-size: 13px; }
.sc { font-family: var(--el-font-family); font-weight: 600; min-width: 34px; text-align: right; font-size: 12px; }
.kind { font-size: 11px; padding: 0 5px; border-radius: 3px; background: var(--el-fill-color); color: var(--el-text-color-secondary); }
</style>
