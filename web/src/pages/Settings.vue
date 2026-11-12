<template>
  <!-- Desktop client settings: account and server, pending assignments, version and data directory, local factory protocol services, 3D quality -->
  <div class="page">
    <div class="page-head"><h2>{{ $t('common.settings') }}</h2><span class="sub">{{ $t('settings.theHoneyfactoryDesktopClientOn') }}</span></div>
    <div v-if="info" class="grid g2">
      <div class="card">
        <h3>{{ $t('settings.accountServer') }}</h3>
        <template v-if="info.mode === 'server'">
          <div class="row"><span>{{ $t('common.server') }}</span><code class="path">{{ info.server }}</code>
            <span class="st" :class="info.online === false ? 'off' : 'on'">{{ info.online === false ? $t('common.cannotConnect') : $t('common.connected') }}</span></div>
          <div class="row"><span>{{ $t('common.username') }}</span><b>{{ info.account?.name }}</b><small class="muted">{{ info.account?.username }} · {{ roleName }}</small></div>
          <div class="row"><span>{{ $t('settings.signedInAt') }}</span><small>{{ $t('settings.n0RememberedFor7Days', [info.login_at]) }}</small></div>
          <p v-if="info.online === false" class="small warn">{{ info.offline_why }}</p>
          <p class="muted small">{{ $t('settings.manageAccountsAndRolesUnder') }}</p>
          <el-button size="small" @click="logout">{{ $t('settings.signOutSwitchServer') }}</el-button>
        </template>
        <template v-else>
          <div class="row"><span>{{ $t('settings.method') }}</span><b>{{ $t('settings.standaloneUse') }}</b></div>
          <p class="muted small">{{ $t('settings.notConnectedToAServer') }}</p>
          <el-button size="small" type="primary" @click="logout">{{ $t('settings.signInToServer') }}</el-button>
        </template>
      </div>
      <div v-if="info.mode === 'server'" class="card">
        <h3>{{ $t('settings.pendingSubmissions') }} <small>{{ $t('settings.pendingSubmissions0', [waiting]) }}</small></h3>
        <p class="muted small">{{ $t('settings.assignmentsSubmittedWhileTheServer') }}</p>
        <div v-for="x in info.outbox" :key="x.id" class="row ob">
          <span class="st" :class="x.state === 'sent' ? 'on' : x.state === 'failed' ? 'off' : 'wait'">{{ { waiting: $t('settings.pending'), sent: $t('settings.submitted'), failed: $t('settings.rejected') }[x.state as string] }}</span>
          <b>{{ x.title || ($t('settings.assignment') + x.remote_aid) }}</b><small class="muted">{{ x.queued }}{{ x.msg && x.state !== 'waiting' ? ' · ' + x.msg : '' }}</small>
        </div>
        <p v-if="!info.outbox.length" class="muted small">{{ $t('settings.noPendingSubmissions') }}</p>
        <el-button size="small" :disabled="!waiting" :loading="busy" @click="flush">{{ $t('settings.submitNow') }}</el-button>
      </div>
      <div class="card">
        <h3>{{ $t('system.about') }}</h3>
        <div class="row"><span>{{ $t('common.version') }}</span><b>{{ info.version }}</b></div>
        <div class="row"><span>{{ $t('settings.dataDirectory') }}</span><code class="path">{{ info.home }}</code>
          <el-button size="small" @click="openFolder('home')">{{ $t('common.open') }}</el-button></div>
        <div class="row"><span>{{ $t('common.logs') }}</span><code class="path">{{ info.home }}\logs</code>
          <el-button size="small" @click="openFolder('logs')">{{ $t('common.open') }}</el-button></div>
        <p class="muted small">{{ $t('settings.localFactoriesDraftsPlcPrograms') }}</p>
      </div>
      <div v-if="app" class="card" data-k="native-card">
        <h3>{{ $t('settings.windowUpdates') }}</h3>
        <div class="row"><span>{{ $t('settings.closeWindow') }}</span>
          <el-radio-group v-model="closeB" size="small" data-k="close-behaviour" @change="(v: any) => native?.closeBehaviour.set(v)">
            <el-radio-button value="ask">{{ $t('settings.askEveryTime') }}</el-radio-button>
            <el-radio-button value="tray">{{ $t('settings.minimizeToTray') }}</el-radio-button>
            <el-radio-button value="quit">{{ $t('common.exit') }}</el-radio-button>
          </el-radio-group></div>
        <div class="row"><span>{{ $t('common.desktopClient') }}</span><b>{{ app.version }}</b><small class="muted">Electron {{ app.electron }}{{ app.packaged ? '' : $t('settings.developmentBuild') }}</small></div>
        <div class="row"><span>{{ $t('settings.update') }}</span>
          <el-button size="small" :loading="upBusy" data-k="check-update" @click="checkUpdate">{{ $t('settings.checkForUpdates') }}</el-button>
          <small class="muted">{{ upMsg || (info.mode === 'server' ? $t('settings.updateAutomaticallyFromTheServer') : $t('settings.standaloneUseCheckOnlyWhen')) }}</small></div>
        <div class="row"><span>{{ $t('settings.shellLogs') }}</span><code class="path">{{ app.logs }}</code><el-button size="small" @click="native?.openLogFolder()">{{ $t('common.open') }}</el-button></div>
      </div>
      <div v-if="session.user?.role !== 'student'" class="card">
        <h3>{{ $t('settings.localFactoryProtocolServices') }}</h3>
        <div class="row"><el-switch :model-value="info.protocols" :loading="busy" :active-text="$t('settings.exposeSignalsViaOpcUa')" @change="(v: any) => save({ protocols: v })" /></div>
        <p class="muted small">{{ $t('settings.appliesOnlyToFactoriesRunning') }}</p>
        <p v-if="info.protocols" class="small">{{ $t('settings.portsOpcUa0Mqtt', [info.ports.opcua, info.ports.mqtt ?? $t('settings.off'), info.ports.modbus]) }}</p>
      </div>
      <div class="card" data-k="density-card">
        <h3>{{ $t('settings.interfaceLayout') }}</h3>
        <el-radio-group :model-value="density.pref" size="small" data-k="density" @change="(v: any) => setCompact(v)">
          <el-radio-button value="auto">{{ $t('settings.auto') }}</el-radio-button>
          <el-radio-button value="on">{{ $t('common.alwaysCompact') }}</el-radio-button>
          <el-radio-button value="off">{{ $t('common.alwaysStandard') }}</el-radio-button>
        </el-radio-group>
        <p class="muted small">{{ $t('settings.compactLayoutSmallerMarginsAnd', [density.on ? $t('settings.compact') : $t('entityPage.standard')]) }}</p>
      </div>
      <div class="card">
        <h3>{{ $t('settings.n3dDisplay') }}</h3>
        <el-radio-group :model-value="info.quality" :disabled="busy" @change="(v: any) => save({ quality: v })">
          <el-radio-button value="low">{{ $t('settings.performanceLow') }}</el-radio-button>
          <el-radio-button value="high">{{ $t('settings.qualityHigh') }}</el-radio-button>
        </el-radio-group>
        <p class="muted small">{{ $t('settings.performanceDisablesShadowsAndAnti') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { applyHealth, desk, get, post, put, session } from '../api';
import { native } from '../native';
import { density, setCompact } from '../compact';

const router = useRouter();
const info = ref<any>(null), busy = ref(false);
const roleName = computed(() => session.user?.role_name || info.value?.account?.role || '');
const waiting = computed(() => (info.value?.outbox || []).filter((x: any) => x.state === 'waiting').length);

// Electron desktop client (window.vfNative available): close-button behavior, update checks, shell logs
const app = ref<any>(null), closeB = ref('ask'), upBusy = ref(false), upMsg = ref('');
async function checkUpdate() {
  upBusy.value = true;
  try { const r = await native!.checkForUpdates(); upMsg.value = r.message; } finally { upBusy.value = false; }
}
onMounted(async () => {
  if (native) { native.getAppInfo().then((a) => { app.value = a; closeB.value = a.closeBehaviour; }).catch(() => {}); }
  info.value = await get('/api/desktop/settings');
});
async function save(b: any) {
  busy.value = true;
  try {
    info.value = await put('/api/desktop/settings', b);
    applyHealth({ ...info.value, version: info.value.version });
    if ('protocols' in b) ElMessage.success(b.protocols ? $t('settings.protocolServicesEnabled') : $t('settings.protocolServicesDisabled'));
    else ElMessage.success($t('common.saved'));
  } catch {
    info.value = await get('/api/desktop/settings');
  } finally { busy.value = false; }
}
async function flush() {
  busy.value = true;
  try {
    const r = await post('/api/desktop/outbox/flush', {});
    info.value = r;
    ElMessage[r.sent ? 'success' : 'warning'](r.sent ? $t('settings.submitted0', [r.sent]) : r.online === false ? $t('settings.stillUnableToConnectTo') : $t('settings.submissionFailedSeeTheList'));
  } finally { busy.value = false; }
}
async function logout() {
  await post('/api/desktop/logout', {});
  session.token = ''; session.user = null; localStorage.removeItem('vf_token'); desk.mode = '';
  router.push('/login');
}
async function openFolder(which: string) { await post('/api/desktop/open_folder', { which }); }
</script>

<style scoped>
.row { display: flex; align-items: center; gap: 10px; margin: 6px 0; font-size: 13px; }
.row > span:first-child { color: var(--hm-text-3); width: 64px; flex: none; }
.row.ob > span:first-child { width: auto; }
.path { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; background: var(--hm-surface-2); border: 1px solid var(--hm-border); border-radius: var(--hm-r-xs); padding: 2px 6px; font-size: 12px; font-family: var(--hm-font-mono); }
.st { font-size: 12px; border-radius: 999px; padding: 1px 8px; } .st.on { background: var(--hm-run-soft); color: var(--hm-run-ink); } .st.off { background: var(--hm-fault-soft); color: var(--hm-fault-ink); }
.st.wait { background: var(--hm-idle-soft); color: var(--hm-idle-ink); }
h3 { margin: 0 0 10px; }
</style>
