<template>
  <div class="school-server">
    <div v-if="st.connected" class="vp-card ok-card">
      <div class="vp-row sp">
        <span><el-icon class="vp-pass"><CircleCheckFilled /></el-icon> {{ $t('common.connected') }} <b class="mono">{{ st.url }}</b></span>
        <span class="vp-small vp-muted">{{ st.at ? st.at.slice(0, 16) + $t('schoolServer.logIn') : '' }}</span>
      </div>
      <div class="vp-small" style="margin-top: 4px">{{ $t('schoolServer.studentAccount01Assignments', [st.name, st.username]) }}</div>
      <div class="vp-row" style="margin-top: 8px">
        <el-button size="small" :loading="busy === 'test'" @click="test()">{{ $t('schoolServer.testConnection') }}</el-button>
        <el-button size="small" type="danger" plain @click="logout">{{ $t('layout.signOut') }}</el-button>
        <span v-if="msg" class="vp-small" :class="msgOk ? 'vp-pass' : 'vp-fail'">{{ msg }}</span>
      </div>
    </div>
    <el-form v-else label-width="92px" size="small" class="ss-form" @submit.prevent>
      <div class="vp-small vp-muted" style="margin-bottom: 8px">{{ $t('schoolServer.enterTheSchoolServerAddress') }}</div>
      <el-form-item :label="$t('login.serverUrl')"><el-input v-model="form.url" :placeholder="$t('login.exampleHttp1921681')" data-k="url" /></el-form-item>
      <el-form-item :label="$t('schoolServer.studentAccount')"><el-input v-model="form.username" :placeholder="$t('classManager.studentId')" data-k="user" /></el-form-item>
      <el-form-item :label="$t('common.password')"><el-input v-model="form.password" type="password" show-password data-k="pw" @keyup.enter="login" /></el-form-item>
      <el-form-item>
        <el-button size="small" :loading="busy === 'test'" :disabled="!form.url" @click="test(form.url)">{{ $t('schoolServer.testConnection') }}</el-button>
        <el-button size="small" type="primary" :loading="busy === 'login'" :disabled="!form.url || !form.username || !form.password" @click="login">{{ $t('common.signIn') }}</el-button>
      </el-form-item>
      <div v-if="msg" class="vp-small" :class="msgOk ? 'vp-pass' : 'vp-fail'">{{ msg }}</div>
    </el-form>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// "School Server" in client settings: address + student credentials → local backend logs in to the school server and stores the token (never exposed to the web page).
// Desktop only (/api/client/*); embed in the shell settings page or the connection dialog in "My Courses".
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, reactive, ref } from 'vue';
import { get, post } from '../../api';
import './panel.css';

const emit = defineEmits<{ (e: 'changed', v: any): void }>();
const st = reactive<any>({ url: '', username: '', name: '', connected: false, at: '' });
const form = reactive({ url: '', username: '', password: '' });
const busy = ref('');
const msg = ref('');
const msgOk = ref(false);

async function load() {
  const r = await get('/api/client/status', true).catch(() => null);
  if (r?.school) { Object.assign(st, r.school); form.url ||= r.school.url; form.username ||= r.school.username; }
}
async function test(url?: string) {
  busy.value = 'test'; msg.value = '';
  try {
    const r = await post('/api/client/school/test', url ? { url } : {});
    msgOk.value = !r.login || r.login.ok;
    msg.value = $t('schoolServer.serverReachable0', [r.server?.version ? $t('schoolServer.version') + r.server.version + $t('common.k460') : '']) + (r.login ? (r.login.ok ? $t('schoolServer.loginValid') : $t('schoolServer.but') + r.login.msg) : '');
  } catch (e: any) { msgOk.value = false; msg.value = e.message; } finally { busy.value = ''; }
}
async function login() {
  busy.value = 'login'; msg.value = '';
  try {
    const r = await post('/api/client/school/login', { ...form });
    Object.assign(st, r); form.password = '';
    ElMessage.success($t('schoolServer.connectedToSchoolServer0', [r.name]));
    emit('changed', r);
  } catch (e: any) { msgOk.value = false; msg.value = e.message; } finally { busy.value = ''; }
}
async function logout() {
  await ElMessageBox.confirm($t('schoolServer.logOutOfTheSchool'), $t('layout.signOut'), { type: 'warning' });
  const r = await post('/api/client/school/logout', {});
  Object.assign(st, r); msg.value = '';
  emit('changed', r);
}
onMounted(load);
defineExpose({ load });
</script>

<style scoped>
.ss-form { max-width: 460px; }
.ok-card { border-left: 3px solid var(--ok, var(--el-color-success)); }
</style>
