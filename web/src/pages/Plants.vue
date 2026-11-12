<template>
  <div class="page" data-help="start">
    <div class="page-head"><h2>{{ $t('common.allFactories') }}</h2><span class="sub">{{ subTitle }}</span><span class="grow" />
      <el-button v-if="canEdit()" type="primary" @click="openNew"><el-icon><Plus /></el-icon>{{ $t('plants.newFactory') }}</el-button></div>
    <div v-if="loaded && !plants.length" class="card"><EmptyState kind="plants" :title="$t('plants.noFactoriesYet')" :desc="canEdit() ? $t('plants.createOneFromATemplate') : $t('plants.factoriesCreatedByAnAdmin')">
      <el-button v-if="canEdit()" type="primary" @click="openNew"><el-icon><Plus /></el-icon>{{ $t('plants.newFactory') }}</el-button></EmptyState></div>
    <div class="grid g3">
      <div v-for="p in plants" :key="p.id" class="card plant">
        <div class="ph" @click="router.push(`/p/${p.id}/workbench`)">
          <div><b class="click">{{ p.name }}</b><span v-if="p.local && desk.mode === 'server'" class="here" :title="$t('plants.thisFactoryRunsOnThis')">{{ $t('common.local') }}</span><div class="muted small">{{ $t('plants.id0Product12', [p.id, p.product, p.shift ? ' · ' + p.shift : '']) }}</div></div>
          <span class="tag-st" :class="p.paused ? 'st-Idle' : p.off ? 'st-Planned' : 'st-Executing'">{{ p.paused ? $t('common.paused') : p.off ? p.off : $t('common.runningAt0', [p.speed]) }}</span>
        </div>
        <div class="stats">
          <div><small>{{ $t('common.simTime') }}</small><b class="mono">{{ p.time.slice(5, 16) }}</b></div>
          <div><small>{{ $t('common.equipment') }}</small><b>{{ p.running }}/{{ p.stations }}</b><i>{{ $t('common.running') }}</i></div>
          <div><small>{{ $t('common.alarm') }}</small><b :class="p.alarms ? 'bad' : 'ok'">{{ p.alarms }}</b></div>
          <div><small>{{ $t('experiments.hourlyOutput') }}</small><b>{{ p.rate }}</b><i>{{ $t('plants.pcsH') }}</i></div>
          <div><small>{{ $t('plants.totalGoodParts') }}</small><b>{{ p.good }}</b></div>
          <div><small>{{ $t('common.scrapRate') }}</small><b>{{ pct(p.scrap_rate, 2) }}</b></div>
        </div>
        <div class="tags">
          <template v-if="!desk.on || (p.local ? desk.protocols : desk.mode === 'server')"><span class="tag-st">Modbus :{{ p.modbus_port }}</span><span class="tag-st">{{ $t('plants.connectedClients0', [p.clients]) }}</span></template>
          <span v-if="p.scenario" class="tag-st st-running">{{ $t('plants.scenario0', [p.scenario]) }}</span><span v-if="p.recording" class="tag-st st-Stopped">{{ $t('plants.recording') }}</span>
          <span v-if="p.dirty" class="tag-st st-Idle">{{ $t('plants.unsavedChanges') }}</span>
        </div>
        <div class="acts">
          <el-button type="primary" size="small" @click="router.push(`/p/${p.id}/workbench`)">{{ $t('plants.openWorkbench') }}</el-button>
          <el-button size="small" :disabled="!canEdit()" @click="toggle(p)">{{ p.paused ? $t('common.continue') : $t('common.pause') }}</el-button>
          <el-dropdown v-if="canEdit()" @command="(c: string) => more(p, c)">
            <el-button size="small">{{ $t('workbench.more') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item command="copy">{{ $t('plants.copyAsNewFactory') }}</el-dropdown-item>
              <el-dropdown-item v-if="desk.mode === 'server' && !p.local" command="download">{{ $t('plants.downloadToThisComputerRun') }}</el-dropdown-item>
              <el-dropdown-item command="reset">{{ $t('plants.resetSimulation') }}</el-dropdown-item>
              <el-dropdown-item command="del" divided>{{ $t('common.delete') }}</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
        </div>
      </div>
    </div>
    <div class="grid g3" style="margin-top:14px">
      <div v-if="!desk.on || desk.mode === 'server' || desk.protocols" class="card"><h3>{{ $t('plants.connectionAddresses') }}</h3>
        <div class="small ln">{{ $t('plants.opcUa') }}<code>opc.tcp://{{ host }}:{{ ports.opcua }}/vfactory/</code>{{ $t('plants.sharedByAllFactoriesOrganized') }}</div>
        <div class="small ln">{{ $t('plants.mqtt') }}<code>{{ host }}:{{ ports.mqtt }}</code>{{ $t('plants.topic') }} <code>{{ $t('plants.vfactoryFactory') }}</code></div>
        <div class="small ln">{{ $t('plants.modbusTcpOnePortPer') }}</div>
        <div class="small ln">{{ $t('plants.httpApi') }}<code>http://{{ hostPort }}/api</code>{{ $t('common.k521') }}<a href="/docs" target="_blank">{{ $t('common.apiDocumentation') }}</a></div></div>
      <div class="card"><h3>{{ $t('sections.quickStart') }}</h3>
        <ol class="small" style="padding-left:18px;line-height:1.9;margin:0">
          <li>{{ $t('plants.openTheWorkbenchToView') }}</li><li>{{ $t('plants.runAFailureScenarioIn') }}</li>
          <li>{{ $t('plants.connectUsingClientsSuchAs') }}</li><li>{{ $t('plants.evaluateTheEffectsOfAdding') }}</li></ol>
        <el-button link type="primary" @click="router.push('/help')">{{ $t('plants.viewHelpCenter') }}</el-button></div>
      <div v-if="!desk.on" class="card"><h3>{{ $t('common.username') }}</h3><p class="small">{{ $t('plants.current01', [session.user?.name, session.user?.role_name]) }}</p>
        <p class="small muted">{{ $t('plants.adminsCanAddAccountsIn') }}</p></div>
    </div>
    <el-dialog v-model="newOpen" :title="$t('common.newFactory')" width="min(760px, 96vw)" :close-on-click-modal="!busy" :show-close="!busy">
      <div v-if="busy" class="np-busy">
        <el-icon class="is-loading"><Loading /></el-icon>
        <div><b>{{ $t('plants.creatingFactory') }}</b><div class="muted small">{{ $t('plants.loadTemplateCreateEquipmentAnd') }}</div></div>
      </div>
      <template v-else>
        <div v-if="desk.mode === 'server'" class="np-row np-where"><span>{{ $t('plants.runOn') }}</span>
          <el-radio-group v-model="nf.local"><el-radio-button :value="false">{{ $t('common.server') }}</el-radio-button><el-radio-button :value="true">{{ $t('plants.localThisComputer') }}</el-radio-button></el-radio-group>
          <small class="muted">{{ nf.local ? $t('plants.onlyAvailableToYouOn') : $t('plants.runsOnTheServerAnd') }}</small></div>
        <div class="np-row"><span>{{ $t('common.name') }}</span><el-input v-model="nf.name" :placeholder="$t('plants.eGMachiningWorkshop2')" style="flex:1" />
          <span>{{ $t('common.no2') }}</span><el-input v-model="nf.id" :placeholder="$t('plants.automaticEGMachining1')" style="width:190px" /></div>
        <div class="muted small np-tip">{{ $t('plants.theIdAppearsInUrls') }}<b>{{ $t('common.no2') }}</b>{{ $t('plants.equipmentTagMqttVfactory') }}<b>{{ $t('common.no2') }}</b>{{ $t('plants.useOnlyLowercaseLettersDigits') }}</div>
        <div v-for="g in groups" :key="g.name" class="np-g">
          <div class="np-gh">{{ g.name }}</div>
          <div class="np-cards">
            <div v-for="t in g.items" :key="t.key" class="np-card" :class="{ on: nf.src === 't:' + t.key }" @click="nf.src = 't:' + t.key">
              <b>{{ t.name }}</b><p>{{ t.desc }}</p><small class="muted">{{ t.blocks ? t.blocks + $t('plants.machines') : $t('plants.startFromScratch') }}</small>
            </div>
          </div>
        </div>
        <div v-if="plants.length" class="np-g"><div class="np-gh">{{ $t('plants.copyExistingFactory') }}</div>
          <el-select :model-value="nf.src.startsWith('c:') ? nf.src : ''" :placeholder="$t('plants.selectAFactoryToCopy')" style="width:100%" @change="(v: string) => (nf.src = v)">
            <el-option v-for="p in copyable" :key="p.id" :value="'c:' + p.id" :label="(p.local && desk.mode === 'server' ? $t('layout.local') : '') + p.name" />
          </el-select></div>
      </template>
      <template #footer><el-button :disabled="busy" @click="newOpen = false">{{ $t('common.cancel') }}</el-button><el-button type="primary" :loading="busy" @click="create">{{ $t('plants.createAndOpen') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { canEdit, del, desk, get, P, pct, post, session } from '../api';
import EmptyState from '../components/EmptyState.vue';

const router = useRouter(), route = useRoute();
const plants = computed(() => session.plants), ports = ref<any>({});
// When the desktop client is online, use the server's connectivity address (the window URL uses local 127.0.0.1)
const srvUrl = computed(() => { try { return new URL(desk.mode === 'server' ? desk.server : location.href); } catch { return new URL(location.href); } });
const host = computed(() => srvUrl.value.hostname), hostPort = computed(() => srvUrl.value.host);
const newOpen = ref(false), busy = ref(false), templates = ref<any>({}), tinfo = ref<any>({}), nf = reactive({ name: '', id: '', src: 't:showcase', local: false });
const subTitle = computed(() => desk.mode === 'server' ? $t('plants.serverFactoriesRunOnThe')
  : desk.on && !desk.protocols ? $t('plants.eachFactoryRunsItsOwn') : $t('plants.eachFactoryRunsItsOwn2'));
// Copy: server factories can be copied to the server or locally (local = download); local factories can only be copied locally
const copyable = computed(() => plants.value.filter((p: any) => !(p.local && desk.mode === 'server' && !nf.local)));
const groups = computed(() => {
  const m = new Map<string, any[]>();
  for (const [key, v] of Object.entries(tinfo.value) as any) { const g = v.group || $t('plants.entireFactory'); if (!m.has(g)) m.set(g, []); m.get(g)!.push({ key, ...v }); }
  return [...m.entries()].map(([name, items]) => ({ name, items }));
});
let t: any;
const loaded = ref(false);
async function load() { const r = await get('/api/overview', true); session.plants = r.plants; ports.value = r.ports; loaded.value = true; }
onMounted(() => { load(); t = setInterval(load, 3000); if (route.query.new && canEdit()) openNew(); });
onUnmounted(() => clearInterval(t));
async function toggle(p: any) { await post(P(p.id) + '/sim', { paused: !p.paused }); load(); }
async function openNew() { const r = await get('/api/plants'); templates.value = r.templates; tinfo.value = r.template_info || Object.fromEntries(Object.entries(r.templates).map(([k, v]) => [k, { name: v }])); newOpen.value = true; }
async function create() {
  busy.value = true;
  try {
    const b: any = { name: nf.name || $t('plants.newFactory2') };
    if (nf.id.trim()) b.id = nf.id.trim();
    if (nf.src.startsWith('t:')) b.template = nf.src.slice(2); else b.copy_from = nf.src.slice(2);
    if (desk.mode === 'server' && nf.local) b.local = true;
    const src = plants.value.find((p: any) => p.id === b.copy_from);
    const r = b.local && src && !src.local ? await post('/api/desktop/plants/download', { pid: src.id, name: b.name }) : await post('/api/plants', b);
    newOpen.value = false; nf.id = ''; await load(); router.push(`/p/${r.id}/workbench`);
  } finally { busy.value = false; }
}
async function more(p: any, c: string) {
  if (c === 'copy') { nf.name = p.name + $t('plants.copy'); nf.src = 'c:' + p.id; nf.local = !!p.local && desk.mode === 'server'; await openNew(); }
  if (c === 'download') {
    await ElMessageBox.confirm($t('plants.copyTheModelAndPlc', [p.name]), $t('sections.downloadedToThisComputer'));
    const r = await post('/api/desktop/plants/download', { pid: p.id, name: p.name + $t('plants.local') });
    ElMessage.success($t('plants.downloadedToThisComputer0', [r.name]) + (r.plc_programs ? $t('plants.including0PlcPrograms', [r.plc_programs]) : '')); await load();
  }
  if (c === 'reset') { await ElMessageBox.confirm($t('plants.rebuildTheFactoryFromIts'), $t('plants.resetSimulation')); await post(P(p.id) + '/restart'); ElMessage.success($t('plants.resetComplete')); load(); }
  if (c === 'del') { await ElMessageBox.confirm($t('plants.delete0ItsConfigurationFile', [p.name]), $t('plants.deleteFactory'), { type: 'warning' }); await del('/api/plants/' + p.id); load(); }
}
</script>

<style scoped>
.np-row { display: flex; align-items: center; gap: 8px; } .np-where { margin-bottom: 10px; }
.here { margin-left: 6px; font-size: 11.5px; color: var(--hm-run-ink); background: var(--hm-run-soft); border-radius: 999px; padding: 1px 8px; vertical-align: 2px; } .np-tip { margin: 6px 0 10px; line-height: 1.6; }
.np-g { margin-top: 10px; } .np-gh { font-weight: 600; margin-bottom: 6px; font-size: 13px; }
.np-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 8px; }
.np-card { border: 1px solid var(--el-border-color); border-radius: 8px; padding: 8px 10px; cursor: pointer; display: grid; gap: 3px; }
.np-card:hover { border-color: var(--el-color-primary-light-5); } .np-card.on { border-color: var(--el-color-primary); box-shadow: 0 0 0 1px var(--el-color-primary); background: var(--el-color-primary-light-9); }
.np-card p { margin: 0; font-size: 12px; color: var(--el-text-color-regular); line-height: 1.5; } .np-card b { font-size: 13.5px; }
.np-busy { display: flex; gap: 12px; align-items: center; padding: 18px 6px; } .np-busy .el-icon { font-size: 26px; color: var(--el-color-primary); }
.plant { display: grid; gap: 10px; } .ph { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; } .ph b { font-size: 15.5px; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px 10px; background: var(--hm-surface-2); border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); padding: 8px 10px; }
.stats small { color: var(--mu); font-size: 11.5px; display: block; } .stats b { font-size: 16px; font-family: Consolas, monospace; } .stats i { font-style: normal; color: var(--mu); font-size: 11px; margin-left: 3px; }
.tags { display: flex; flex-wrap: wrap; gap: 5px; } .acts { display: flex; gap: 6px; } .ln { padding: 3px 0; } code { background: var(--hm-surface-2); padding: 0 4px; border-radius: var(--hm-r-xs); font-size: 12px; font-family: var(--hm-font-mono); }
</style>
