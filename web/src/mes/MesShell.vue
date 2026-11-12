<template>
  <!-- 5.0.1 Teaching MES shell: parent route for /mes/** within the HoneyFactory UI (expand "MES" in the sidebar for the MES menu).
       Desktop client: local MES running → top status bar (MesBar) + page; otherwise → auto-start for the remembered/only local factory, or prompt to select one (MesStart).
       Browser / server web / SaaS web: no MES (MES connects to local factories only in the desktop client); show explanation + open in desktop client (MesClientOnly). -->
  <div class="mes-shell" data-k="mes-page">
    <MesClientOnly v-if="!desk.on" />
    <template v-else-if="ready">
      <MesBar @pick="mes.picking = true" @stop="stop" />
      <router-view v-slot="{ Component }">
        <component :is="Component" v-if="Component" />
      </router-view>
    </template>
    <MesStart v-else @start="start" @stop="stop" @reload="refresh" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, onUnmounted, watch } from 'vue';
import { useRoute } from 'vue-router';
import { desk, get as vget, post as vpost, refreshDesk } from '../api';
import { get, loadMesSession, mes, running } from './api';
import MesBar from './MesBar.vue';
import MesClientOnly from './MesClientOnly.vue';
import MesStart from './MesStart.vue';

const route = useRoute();
const ready = computed(() => running() && !mes.picking && !!mes.user && !!mes.meta && mes.sessionKey === `${mes.st?.pid}:${mes.st?.started}`);

async function refresh() {
  const r = await vget('/api/desktop/mes', true).catch(() => null);
  mes.loaded = true;
  mes.failed = !r;
  if (r) mes.st = r;
  if (running()) await loadMesSession();
  return r;
}

/** Factory for auto-start: URL ?pid=, last used, or the only MES-compatible local factory (foundry/machining); unresolved → '' (prompt to select) */
function autoPid() {
  const st = mes.st, plants = st?.plants || [], ids = plants.map((p: any) => p.id);
  const q = String(route.query.pid || '');
  if (q && ids.includes(q)) return q;
  if (st?.last_pid && ids.includes(st.last_pid)) return st.last_pid;
  const fit = plants.filter((p: any) => p.fit);
  return fit.length === 1 ? fit[0].id : '';
}

async function start(pid: string) {
  if (!pid || mes.starting) return;
  const st = mes.st;
  if (st?.state === 'running' && st.pid !== pid) {
    const name = st.plants?.find((p: any) => p.id === pid)?.name || pid;
    const go = await ElMessageBox.confirm($t('mesShell.onlyOneMesInstanceCan', [st.plant_name, name]), $t('mesShell.switchFactory'), { type: 'warning' })
      .then(() => true, () => false);
    if (!go) return;
  }
  mes.starting = pid; mes.manualStop = false;
  try {
    mes.st = { ...mes.st, ...(await vpost('/api/desktop/mes/start', { pid })) };
    await loadMesSession(true);
    mes.picking = false;
  } catch { /* Error already shown */ } finally {
    mes.starting = '';
    await refresh();
    refreshDesk();
  }
}

async function stop() {
  try {
    mes.st = { ...mes.st, ...(await vpost('/api/desktop/mes/stop', {})) };
    mes.manualStop = true; mes.picking = false;
    ElMessage.success($t('mesShell.mesStoppedAllDataIs'));
  } finally { await refresh(); refreshDesk(); }
}

async function maybeAutoStart() {
  const st = mes.st;
  if (!st || !st.available || mes.manualStop || mes.starting || mes.picking || st.state === 'running' || st.state === 'starting' || st.state === 'error') return;
  const pid = autoPid();
  if (pid) await start(pid);
}

let tSt: any, tClock: any, tPing: any;
async function tickClock() {
  if (!running() || document.visibilityState !== 'visible') return;
  try { mes.now = (await get('/api/clock', true)).now; } catch { /* */ }
}
onMounted(async () => {
  if (!desk.on) return;
  await refresh();
  await maybeAutoStart();
  tickClock();
  tSt = setInterval(refresh, 5000);
  tClock = setInterval(tickClock, 3000);
  // While the page is open and visible, tell the local service it is in use, not idle
  tPing = setInterval(() => { if (running() && document.visibilityState === 'visible') vpost('/api/desktop/mes/ping', {}).catch(() => {}); }, 60000);
});
onUnmounted(() => { clearInterval(tSt); clearInterval(tClock); clearInterval(tPing); });
// MES restarts after stopping (e.g. idle auto-stop, then started elsewhere): reload the session
watch(() => `${mes.st?.state}:${mes.st?.pid}:${mes.st?.started}`, () => { if (running()) loadMesSession(); });
// URL specifies another factory ("Open MES" in a lesson): ask for confirmation instead of switching automatically
watch(() => route.query.pid, (p) => { if (p && running() && p !== mes.st?.pid) mes.picking = true; }, { immediate: true });
</script>

<style scoped>
.mes-shell { min-height: 100%; display: flex; flex-direction: column; }
</style>
