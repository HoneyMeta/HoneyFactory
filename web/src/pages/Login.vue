<template>
  <div class="login hm-grid-bg" :class="{ art: !!bg }">
    <LangSwitch class="lang-pos" />
    <div class="lg-card">
    <div class="intro" :style="bg ? { backgroundImage: `url(${bg})` } : {}">
      <img :src="logoSrc()" :alt="$t('common.honeyfactory')" :class="{ word: wordmark }" />
      <h1 v-if="!wordmark">{{ $t('common.honeyfactory') }}</h1>
      <p>{{ $t('layout.industrialDigitalTwinSimulationPlatf') }}</p>
      <ul>
        <li>{{ $t('login.realisticSignalsDrivenByProcess') }}</li>
        <li>{{ $t('login.scenarioOrchestrationExperimentsAndO') }}</li>
        <li>{{ $t('login.integrationTestingForMesScada') }}</li>
        <li>{{ $t('login.plcLabCoursesLadderDiagram') }}</li>
      </ul>
    </div>
    <!-- Desktop client: server address + server account (from "Users & Roles" in the web app), or standalone use without a server -->
    <div v-if="desk.on" class="box">
      <h2>{{ $t('common.signIn') }}</h2>
      <el-form @submit.prevent="goDesk" label-position="top">
        <!-- 5.0: connect to Honey Cloud by default; schools/companies with self-hosted servers enter their own address (button, not an input, to preserve the input order below) -->
        <div class="srv-pick" data-k="login-srv-pick">
          <button type="button" :class="{ on: srvKind === 'cloud' }" data-k="login-cloud" :disabled="busy" @click="pickCloud">{{ $t('login.honeyCloud') }}</button>
          <button type="button" :class="{ on: srvKind === 'own' }" data-k="login-own" :disabled="busy" @click="pickOwn">{{ $t('login.schoolOrganizationServer') }}</button>
        </div>
        <div v-if="srvKind === 'cloud' && !cloudReady" class="cloud-tip">{{ $t('login.theHoneyCloudUrlIs') }}</div>
        <el-form-item :label="srvKind === 'cloud' ? $t('login.serverUrlHoneyCloud') : $t('login.serverUrl')">
          <el-input v-model="srv" size="large" :placeholder="$t('login.exampleHttp1921681')" :disabled="busy">
            <template #prefix><el-icon><Link /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item :label="$t('common.username')"><el-input v-model="u" size="large" :disabled="busy" /></el-form-item>
        <el-form-item :label="$t('common.password')"><el-input v-model="p" type="password" size="large" show-password :disabled="busy" @keyup.enter="goDesk" /></el-form-item>
        <el-button type="primary" size="large" style="width:100%" :loading="busy" @click="goDesk">{{ $t('common.signIn') }}</el-button>
      </el-form>
      <div class="demo">{{ $t('login.useYourWebAccountCreated') }}</div>
      <div class="alone"><el-button link type="info" :disabled="busy" @click="goAlone">{{ $t('login.useStandaloneMode') }}</el-button></div>
      <div class="foot">{{ $t('login.honeyfactory0DesktopClientHoneymeta', [desk.version]) }}</div>
    </div>
    <!-- First run of a production install (no administrator yet): create one here (GET/POST /api/setup/admin) -->
    <div v-else-if="setup.needed" class="box" data-test="setup-admin">
      <h2>{{ $t('login.setupTitle') }}</h2>
      <el-form @submit.prevent="createAdmin" label-position="top">
        <el-form-item :label="$t('login.setupName')"><el-input v-model="setup.name" size="large" autofocus /></el-form-item>
        <el-form-item :label="$t('common.username')"><el-input v-model="setup.username" size="large" /></el-form-item>
        <el-form-item :label="$t('login.setupPw')"><el-input v-model="setup.pw" type="password" size="large" show-password /></el-form-item>
        <el-form-item :label="$t('login.setupPw2')"><el-input v-model="setup.pw2" type="password" size="large" show-password @keyup.enter="createAdmin" /></el-form-item>
        <el-button type="primary" size="large" style="width:100%" :loading="busy" @click="createAdmin">{{ $t('login.setupBtn') }}</el-button>
      </el-form>
      <div class="demo">{{ $t('login.setupIntro') }}</div>
    </div>
    <div v-else class="box">
      <h2>{{ $t('common.signIn') }}</h2>
      <el-form @submit.prevent="go" label-position="top">
        <el-form-item :label="$t('common.username')"><el-input v-model="u" size="large" autofocus /></el-form-item>
        <el-form-item :label="$t('common.password')"><el-input v-model="p" type="password" size="large" show-password @keyup.enter="go" /></el-form-item>
        <el-button type="primary" size="large" style="width:100%" :loading="busy" @click="go">{{ $t('common.signIn') }}</el-button>
      </el-form>
      <div class="demo">{{ $t('login.studentsAndTeachersShouldSign') }}<br>{{ $t('login.seeTheInstallationInstructionsFor') }}</div>
      <div class="foot">{{ $t('login.honeymetaTechnologyZhengzhouCoLtd') }}</div>
    </div>
    </div>
    <!-- Initial-password login: change the password first (enter the new password twice, with clear rules). Required for students/teachers; admins/engineers can choose "Later" -->
    <PasswordDialog v-model="pwOpen" :old="pwOld" :must="pwMust" :title="$t('opsApp.changeYourInitialPassword')" :later-text="pwMust ? '' : $t('common.maybeLater')"
                    :intro="$t('login.youAreUsingTheInitial') + (pwMust ? '' : $t('login.changeItBeforeProductionDeployment'))" @done="pwDone" @later="pwDone" />
  </div>
</template>

<script setup lang="ts">
import { $t, isZh } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { desk, get, loadSession, post, session, setDeskSession } from '../api';
import PasswordDialog from '../components/PasswordDialog.vue';
import LangSwitch from '../components/LangSwitch.vue';
import { homeFor } from '../start/recent';
import { brand, firstBrand, loadBrand, logoFor, markUrl, themed } from '../brand';

loadBrand();
// Left illustration (login-bg artwork; top 45% reserved for logo and introduction); light theme only
const bg = computed(() => (brand.loaded ? themed('login-bg').src : ''));
// the delivered wordmark images spell the Chinese brand name: English shows the mark + a text title instead
const wordmark = computed(() => isZh && brand.loaded && !!firstBrand('logo-dark.png', 'logo-light.png'));
const logoSrc = () => (wordmark.value ? logoFor() : markUrl());


const u = ref(''), p = ref(''), busy = ref(false);
const WEAK = ['honey123', '123456', 'teach123'];   // Initial passwords from installation or roster import: require a password change on login
const router = useRouter(), route = useRoute();
const srv = ref('');
const cloud = ref(''), cloudReady = ref(false);
const norm = (s: string) => s.trim().replace(/\/+$/, '').toLowerCase();
const srvKind = computed(() => (cloud.value && norm(srv.value) === norm(cloud.value) ? 'cloud' : 'own'));
function pickCloud() { srv.value = cloud.value; }
function pickOwn() { if (srvKind.value === 'cloud') srv.value = ''; }
const setup = reactive({ needed: false, name: '', username: 'admin', pw: '', pw2: '' });
onMounted(async () => {
  if (!desk.on) {
    // production install without any administrator yet (backend: GET /api/setup/admin -> { needed }); older servers: 404 -> normal login
    try { const r = await fetch('/api/setup/admin'); if (r.ok) setup.needed = !!(await r.json()).needed; } catch { /* */ }
    return;
  }
  try {
    const i = await (await fetch('/api/desktop/login_info')).json();
    srv.value = i.server || ''; u.value = u.value || i.username || '';
    cloud.value = i.cloud || ''; cloudReady.value = !!i.cloud_ready;
  } catch { /* */ }
});
/** Desktop client: the local service logs in to the server (keeping the server token locally) and gives the web page a local session. */
async function goDesk() {
  if (!srv.value.trim()) { ElMessage.warning($t('login.enterTheServerUrlAsk')); return; }
  busy.value = true;
  try {
    const r = await post('/api/desktop/login', { server: srv.value, username: u.value, password: p.value });
    setDeskSession(r);
    if (r.offline) ElMessage.warning($t('login.theServerIsCurrentlyUnreachable'));
    await afterLogin(p.value, !!r.must_change_pw);
  } finally { busy.value = false; }
}
async function goAlone() {
  busy.value = true;
  try {
    setDeskSession(await post('/api/desktop/standalone', {}));
    await afterLogin('');
  } finally { busy.value = false; }
}
/** Post-login destination: return to next if redirected from a protected page; otherwise open the start page (Teaching / All Factories if "Show welcome page on startup" is off). */
const nextOr = (role: string) => { const n = (route.query.next as string) || ''; return n && n !== '/' ? n : homeFor(role); };
async function afterLogin(pw: string, must = false) {
  await loadSession();
  if (pw && (WEAK.includes(pw) || must)) await forceChange(pw, ['student', 'teacher'].includes(session.user?.role) || must);
  const role = session.user?.role;
  router.replace(nextOr(role));
}
async function createAdmin() {
  if (setup.pw.length < 8) { ElMessage.warning($t('login.setupShort')); return; }
  if (setup.pw !== setup.pw2) { ElMessage.warning($t('login.setupMismatch')); return; }
  busy.value = true;
  try {
    const r = await post('/api/setup/admin', { username: setup.username.trim(), password: setup.pw, name: setup.name.trim() || setup.username.trim() });
    session.token = r.token; localStorage.setItem('vf_token', r.token);
    await loadSession();
    router.replace(nextOr(session.user?.role));
  } finally { busy.value = false; }
}
async function go() {
  busy.value = true;
  try {
    const r = await post('/api/login', { username: u.value, password: p.value });
    session.token = r.token; localStorage.setItem('vf_token', r.token);
    await loadSession();
    // 5.0: admin-issued temporary passwords must also be changed first (teachers created by org admins, imported students, org admins created by operations)
    const tm = await get('/api/teach/me', true).catch(() => null);
    if (WEAK.includes(p.value) || tm?.must_change_password) await forceChange(p.value, ['student', 'teacher', 'orgadmin'].includes(session.user?.role) || !!tm?.must_change_password);
    const role = session.user?.role;
    router.replace(nextOr(role));
  } finally { busy.value = false; }
}
/** Initial-password login: students/teachers must change it; admins/engineers get one reminder and may choose "Later" (initial passwords are common in automated tests and demos).
 *  The dialog (components/PasswordDialog.vue) requires the new password twice and checks each rule: at least 6 characters, different from the old password, not an initial password. */
const pwOpen = ref(false), pwOld = ref(''), pwMust = ref(false);
let pwResolve: (() => void) | null = null;
function forceChange(old: string, must: boolean) {
  pwOld.value = old; pwMust.value = must; pwOpen.value = true;
  return new Promise<void>((res) => { pwResolve = res; });
}
function pwDone() { pwOpen.value = false; const r = pwResolve; pwResolve = null; r?.(); }
</script>

<style scoped>
/* 5.0.1: light theme (shared with HoneyMOM): fine light-gray grid canvas, white cards, cobalt-blue primary button; amber only for the logo and tagline */
.lang-pos { position: fixed; top: 14px; right: 16px; z-index: 5; }
.login { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; color: var(--hm-text); }
.lg-card { display: flex; align-items: center; justify-content: center; gap: 70px; flex-wrap: wrap; }
.intro { color: var(--hm-text); max-width: 420px; } .intro img { height: 72px; } .intro img.word { height: 48px; width: auto; } .intro h1 { font-size: 34px; margin: 12px 0 4px; letter-spacing: 3px; }
.intro p { color: var(--hm-amber-ink); margin: 0 0 18px; font-size: 15px; } .intro ul { padding-left: 18px; color: var(--hm-text-2); line-height: 2; font-size: 14px; }
.box { width: min(380px, 100%); background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); padding: 26px 28px 18px; box-shadow: var(--hm-e3); }
/* Illustrated layout: one card, illustration on the left (logo and intro above), form on the right */
.login.art .lg-card { gap: 0; flex-wrap: nowrap; width: min(1120px, 100%); height: min(720px, calc(100vh - 40px)); background: var(--hm-surface); border-radius: var(--hm-r-lg); overflow: hidden;
  box-shadow: var(--hm-e3); border: 1px solid var(--hm-border); }
.login.art .intro { align-self: stretch; flex: none; width: calc(min(720px, 100vh - 40px) * 0.818); max-width: 56%; background-size: cover; background-position: center bottom;
  background-color: var(--hm-surface-2); color: var(--hm-text); padding: 5% 7% 0; border-right: 1px solid var(--hm-border); }
.login.art .intro img.word { height: 40px; }
.login.art .intro p { color: var(--hm-amber-ink); margin: 10px 0 8px; letter-spacing: 2px; font-size: 13.5px; }
.login.art .intro ul { color: var(--hm-text-2); line-height: 1.6; font-size: 12.5px; padding-left: 16px; margin: 0; }
.login.art .box { flex: 1; box-shadow: none; border: 0; border-radius: 0; display: flex; flex-direction: column; justify-content: center; padding: 30px min(64px, 6vw); width: auto; max-width: none; }
.login.art .box > * { width: 100%; max-width: 360px; margin-left: auto; margin-right: auto; }
@media (max-width: 900px) { .login.art .intro { display: none; } .login.art .lg-card { height: auto; width: min(440px, 100%); } }
h2 { margin: 0 0 14px; font-size: var(--hm-fs-xl); font-weight: var(--hm-fw-semibold); color: var(--hm-text); }
.demo { margin-top: 14px; font-size: var(--hm-fs-xs); color: var(--hm-text-2); background: var(--hm-surface-2); border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); padding: 8px 10px; line-height: 1.6; }
.alone { margin-top: 10px; text-align: center; }
.srv-pick { display: flex; gap: 6px; margin-bottom: 10px; }
.srv-pick button { flex: 1; border: 1px solid var(--el-border-color); background: var(--hm-surface); border-radius: var(--hm-r-sm); padding: 7px 6px; font: inherit; font-size: var(--hm-fs-sm); cursor: pointer; color: var(--hm-text-2); }
.srv-pick button:hover:not(:disabled) { border-color: var(--el-color-primary-light-5); color: var(--hm-primary); }
.srv-pick button.on { border-color: var(--hm-primary); color: var(--hm-primary); background: var(--hm-primary-soft); font-weight: 600; }
.cloud-tip { font-size: var(--hm-fs-xs); color: var(--hm-idle-ink); margin: -4px 0 8px; line-height: 1.5; }
.foot { margin-top: 14px; text-align: center; font-size: var(--hm-fs-xs); color: var(--hm-text-3); }
</style>