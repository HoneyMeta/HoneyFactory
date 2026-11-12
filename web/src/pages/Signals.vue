<template>
  <div class="page sig">
    <div class="page-head" data-tour="sig-head"><h2>{{ $t('common.signals') }}</h2><span class="sub">{{ $t('signals.integrationTestingWithMesScada') }}</span><span class="grow" />
      <el-button @click="openDocs"><el-icon><Reading /></el-icon>{{ $t('signals.apiDocumentation') }}</el-button>
      <el-dropdown @command="exp"><el-button data-tour="sig-export"><el-icon><Download /></el-icon>{{ $t('signals.exportTagList') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
        <template #dropdown><el-dropdown-menu><el-dropdown-item command="xlsx">{{ $t('signals.excelTagList') }}</el-dropdown-item><el-dropdown-item command="csv">{{ $t('signals.csvTagList') }}</el-dropdown-item>
          <el-dropdown-item command="json">{{ $t('signals.jsonTagListStructuredEnglish') }}</el-dropdown-item>
          <el-dropdown-item command="nodeset">{{ $t('signals.opcUaNodeset2Xml') }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
      <DeliveryExport :pid="pid" />
      <GuideButton area="signals" /></div>

    <div v-if="s && !s.endpoints.sandbox" class="timebar" :class="settings.time" data-tour="sig-time">
      <el-icon><Clock /></el-icon>
      <span>{{ $t('signals.externalTime') }}<b>{{ settings.time === 'wall' ? $t('signals.wallClockCurrentServerTime') : $t('common.simTime') }}</b></span>
      <span class="muted small">{{ settings.time === 'wall' ? $t('signals.opcUaSourcetimestampAndMqtt') :
        $t('signals.opcUaSourcetimestampAndMqtt2', [speed, speed > 1 ? $t('signals.timestampsAdvanceFasterThanThe') : '']) }}</span>
      <span class="grow" />
      <el-radio-group v-model="settings.time" size="small" :disabled="!edit" @change="saveSettings({ time: settings.time })">
        <el-radio-button value="sim">{{ $t('common.simTime') }}</el-radio-button><el-radio-button value="wall">{{ $t('common.wallClock') }}</el-radio-button></el-radio-group>
    </div>

    <div class="grid g4" v-if="s" data-tour="sig-endpoints">
      <div class="card ep"><small>OPC UA</small>
        <div class="addr"><code>{{ s.endpoints.opcua || '—' }}</code><el-button v-if="s.endpoints.opcua" link size="small" @click="copy(s.endpoints.opcua)"><el-icon><CopyDocument /></el-icon></el-button></div>
        <span class="muted small">{{ $t('signals.securityPolicyNoneAnonymousLogin', [s.endpoints.opcua_prefix]) }}</span>
        <span v-if="others('opcua').length" class="muted small more">{{ $t('signals.otherNetworkAdapters') }}<a v-for="a in others('opcua')" :key="a" @click="copy(a)">{{ hostOf(a) }}</a></span></div>
      <div class="card ep"><small>Modbus TCP</small>
        <div class="addr"><code>{{ s.endpoints.modbus || '—' }}</code><el-button v-if="s.endpoints.modbus" link size="small" @click="copy(s.endpoints.modbus)"><el-icon><CopyDocument /></el-icon></el-button></div>
        <span class="muted small">{{ $t('signals.oneUnitPerDeviceNumeric', [settings.modbus?.fmt, settings.modbus?.order, settings.modbus?.base]) }}</span>
        <span v-if="others('modbus').length" class="muted small more">{{ $t('signals.otherNetworkAdapters') }}<a v-for="a in others('modbus')" :key="a" @click="copy(a)">{{ hostOf(a) }}</a></span></div>
      <div class="card ep"><small>MQTT</small>
        <div class="addr"><code>{{ s.endpoints.mqtt || $t('signals.disabled') }}</code><el-button v-if="s.endpoints.mqtt" link size="small" @click="copy(s.endpoints.mqtt)"><el-icon><CopyDocument /></el-icon></el-button></div>
        <span class="muted small">{{ $t('signals.topics0SendWritesTo', [s.endpoints.mqtt_prefix, ANON[s.mqtt_auth?.anonymous] || '—']) }}</span>
        <span v-if="others('mqtt').length" class="muted small more">{{ $t('signals.otherNetworkAdapters') }}<a v-for="a in others('mqtt')" :key="a" @click="copy(a)">{{ hostOf(a) }}</a></span></div>
      <div class="card ep"><small>{{ $t('signals.connectedClients') }}</small><b>{{ s.clients.length }}</b><span class="muted small">{{ s.clients.map((c: any) => c.protocol).join($t('common.k360')) || $t('signals.noExternalConnections') }}</span>
        <span v-if="s.endpoints.hostname" class="muted small">{{ $t('signals.hostname0', [s.endpoints.hostname]) }}</span></div>
    </div>
    <el-alert v-else-if="s?.endpoints?.sandbox" type="info" :closable="false" :title="$t('signals.sandboxFactoriesDoNotExpose')" data-tour="sig-sandbox" />

    <div class="grid main" style="margin-top:14px">
      <div class="card tree" data-tour="sig-tree">
        <el-input v-model="q" :placeholder="$t('signals.searchTagsDescriptionsAddresses')" clearable size="small" style="margin-bottom:8px" />
        <el-tree :data="treeData" :props="{ label: 'label', children: 'children' }" node-key="key" :filter-node-method="filt" ref="treeRef" highlight-current
          :expand-on-click-node="true" @node-click="onNode" class="sig-tree">
          <template #default="{ data }"><span class="tn"><span :class="data.leaf ? '' : 'grp'">{{ data.label }}</span><span v-if="data.leaf" class="mono small muted">{{ fmt(data.value) }} {{ data.unit }}</span></span></template>
        </el-tree>
      </div>
      <div class="card" v-if="tag">
        <h3>{{ tag.desc }} <small class="mono">{{ tag.key }}</small><span class="grow" /><el-select v-model="hours" size="small" style="width:100px" @change="loadTrend"><el-option v-for="h in [1, 4, 12, 24]" :key="h" :label="h + $t('common.hours2')" :value="h" /></el-select></h3>
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item :label="$t('signals.currentValue')"><b class="mono">{{ fmt(liveVal) }}</b> {{ tag.unit }}</el-descriptions-item><el-descriptions-item :label="$t('common.type')">{{ tag.dtype }}{{ tag.writable ? $t('signals.writable') : $t('signals.readOnly') }}{{ tag.lo != null ? $t('signals.n01', [tag.lo, tag.hi]) : '' }}</el-descriptions-item>
          <el-descriptions-item label="OPC UA" :span="2"><code>{{ tag.opcua || '—' }}</code><el-button v-if="tag.opcua" link size="small" @click="copy(tag.opcua)"><el-icon><CopyDocument /></el-icon></el-button></el-descriptions-item>
          <el-descriptions-item label="MQTT" :span="2"><code>{{ tag.mqtt || '—' }}</code><el-button v-if="tag.mqtt" link size="small" @click="copy(tag.mqtt)"><el-icon><CopyDocument /></el-icon></el-button></el-descriptions-item>
          <el-descriptions-item label="Modbus" :span="2"><code>{{ tag.modbus || $t('signals.notMappedToModbus') }}</code></el-descriptions-item>
        </el-descriptions>
        <div v-if="tag.writable && edit" class="wr"><span>{{ $t('signals.write') }}</span><el-switch v-if="tag.dtype === 'bool'" v-model="wval" />
          <el-input-number v-else v-model="wval" :min="tag.lo ?? undefined" :max="tag.hi ?? undefined" :controls="false" size="small" />
          <el-button size="small" type="primary" @click="write">{{ $t('signals.write') }}</el-button><span class="small muted">{{ tag.lo != null ? $t('signals.range01', [tag.lo, tag.hi]) : '' }}</span></div>
        <div v-if="edit && s && !s.endpoints.sandbox" class="wr"><el-button size="small" @click="faultHere">{{ $t('signals.injectACommunicationFaultInto') }}</el-button></div>
        <Chart v-if="trend && trend.v.length" :option="trendOpt" :height="260" style="margin-top:10px" />
        <p v-else-if="tag.dtype === 'str'" class="muted small">{{ $t('signals.textTagsHaveNoTrend') }}</p>
      </div>
      <div class="card" v-else><p class="muted">{{ $t('signals.selectATagOnThe') }}</p></div>
      <div class="side">
        <div class="card"><h3>{{ $t('signals.connectedClients') }}</h3>
          <div v-for="(c, i) in s?.clients || []" :key="i" class="small row"><span class="tag-st">{{ c.protocol }}</span> <span class="mono">{{ c.peer }}</span> <span class="muted">{{ c.detail }}</span></div>
          <p v-if="!s?.clients.length" class="muted small">{{ $t('signals.noExternalClientsConnectedExcludes') }}</p></div>

        <div class="card" ref="faultCard" data-tour="sig-fault"><h3>{{ $t('signals.communicationFaultInjection') }}<span class="grow" /><el-button v-if="s?.rules?.length" size="small" link type="danger" :disabled="!edit" @click="clearAll">{{ $t('signals.restoreAll') }}</el-button></h3>
          <div class="frm">
            <label>{{ $t('common.object') }}</label><el-select v-model="ff.protocol" size="small" @change="fixMode"><el-option v-for="(n, k) in PN" :key="k" :label="n" :value="k" />
              <el-option v-if="netLinks.length" :label="$t('signals.networkCablesSignalWires4')" value="link" /></el-select>
            <label>{{ $t('common.scope') }}</label>
            <el-select v-if="ff.protocol === 'link'" v-model="ff.link" size="small" filterable :placeholder="$t('signals.selectACableOrWire')">
              <el-option v-for="l in netLinks" :key="l.id" :label="$t('signals.n0123', [l.id, l.from, l.to, l.protocol || l.kind])" :value="l.id" /></el-select>
            <div v-else class="row2"><el-select v-model="ff.station" size="small" clearable filterable :placeholder="$t('signals.entireProtocol')" style="flex:1" @change="ff.tag = ''">
                <el-option v-for="st in tree" :key="st.id" :label="`${st.id} ${st.name}`" :value="st.id" /></el-select>
              <el-select v-model="ff.tag" size="small" clearable filterable :placeholder="$t('signals.entireDevice')" :disabled="!ff.station" style="flex:1">
                <el-option v-for="t in tagsOf(ff.station)" :key="t" :label="t" :value="t" /></el-select></div>
            <label>{{ $t('common.fault') }}</label><el-select v-model="ff.mode" size="small"><el-option v-for="m in modesFor(ff.protocol)" :key="m" :label="linkModes[m] || s.modes[m]" :value="m" /></el-select>
            <template v-if="ff.mode === 'latency' || ff.mode === 'jitter'"><label>{{ ff.mode === 'jitter' ? $t('signals.maximumDelay') : $t('signals.postpone') }}</label><el-input-number v-model="ff.latency" size="small" :min="0.1" :max="120" :step="1" controls-position="right" /></template>
            <template v-if="ff.mode === 'drop'"><label>{{ $t('signals.packetLoss') }}</label><el-input-number v-model="ff.drop_pct" size="small" :min="1" :max="100" controls-position="right" /></template>
            <template v-if="ff.mode === 'stuck'"><label>{{ $t('signals.freezeAt') }}</label><el-input v-model="ff.value" size="small" :placeholder="$t('signals.blankValueAtFaultOnset')" /></template>
            <template v-if="ff.mode === 'drift'"><label>{{ $t('signals.perMinute') }}</label><el-input-number v-model="ff.rate" size="small" :step="0.5" controls-position="right" /></template>
            <label>{{ $t('signals.lasting') }}</label><div class="row2"><el-input-number v-model="ff.minutes" size="small" :min="0" :controls="false" style="width:70px" /><span class="small muted">{{ $t('signals.minSimTime0Until') }}</span></div>
            <template v-if="ff.protocol === 'mqtt' && !ff.station"><label></label><el-checkbox v-model="ff.include_mes" size="small">{{ $t('signals.alsoAffectMesGatewayMessages') }}</el-checkbox></template>
          </div>
          <p class="small muted" style="margin:6px 0">{{ ff.protocol === 'link' ? $t('signals.affectsDataPassingThroughThis') : s?.help?.[ff.mode] }}</p>
          <el-button size="small" type="danger" plain :disabled="!edit || !ff.mode" @click="inject">{{ $t('common.inject') }}</el-button>
          <div v-if="s?.rules?.length" class="rules">
            <div v-for="r in s.rules" :key="r.id" class="rule small"><span class="tag-st st-Stopped">{{ r.desc }}</span>
              <span class="muted">{{ r.left_min != null ? $t('signals.n0MinRemaining', [r.left_min]) : $t('signals.keepIndefinitely') }}</span><span class="grow" />
              <el-button size="small" link :disabled="!edit" @click="clearRule(r)">{{ $t('common.restore') }}</el-button></div></div>
          <p v-else class="small muted">{{ $t('signals.noActiveCommunicationFaultsFault') }}</p></div>

        <div class="card"><h3>{{ $t('signals.protocolSettings') }}</h3>
          <div class="frm">
            <label>{{ $t('signals.lenientTyping') }}</label><div class="row2"><el-switch v-model="settings.lenient_types" size="small" :disabled="!edit" @change="saveSettings({ lenient_types: settings.lenient_types })" />
              <span class="small muted">{{ $t('signals.convertValuesToTheTag') }}</span></div>
            <label>{{ $t('signals.outOfRangeWrites') }}</label><div class="row2"><el-switch v-model="settings.allow_out_of_range" size="small" :disabled="!edit" @change="saveSettings({ allow_out_of_range: settings.allow_out_of_range })" />
              <span class="small muted">{{ settings.allow_out_of_range ? $t('signals.allowFaultDrillsPassOut') : $t('signals.rejectOpcUaBadoutofrangeModbus') }}</span></div>
            <label>Modbus</label><div class="row2">
              <el-select v-model="mb.fmt" size="small" style="width:100px" :disabled="!edit"><el-option v-for="f in FMTS" :key="f" :label="f" :value="f" /></el-select>
              <el-select v-model="mb.order" size="small" style="width:90px" :disabled="!edit"><el-option v-for="o in ORDERS" :key="o" :label="o" :value="o" /></el-select></div>
            <label>{{ $t('signals.startAddress') }}</label><div class="row2"><el-input-number v-model="mb.base" size="small" :min="0" :max="60000" :controls="false" style="width:90px" :disabled="!edit" />
              <el-select v-model="mb.missing_unit" size="small" style="flex:1" :disabled="!edit"><el-option :label="$t('signals.unknownSlaveReturn0b')" value="exception" /><el-option :label="$t('signals.unknownSlaveNoResponse')" value="silent" /></el-select></div>
            <label></label><el-button size="small" :disabled="!edit" @click="saveSettings({ modbus: { ...mb } })">{{ $t('signals.applyModbusSettings') }}</el-button>
            <label>{{ $t('signals.heartbeat') }}</label><div class="row2"><el-input-number v-model="hb" size="small" :min="0" :max="3600" :controls="false" style="width:70px" :disabled="!edit" />
              <span class="small muted">{{ $t('signals.sStatusResendInterval0') }}</span><el-button size="small" link :disabled="!edit" @click="saveSettings({ mqtt: { heartbeat_s: hb } })">{{ $t('common.apply') }}</el-button></div>
            <template v-if="s?.mqtt_auth"><label>{{ $t('signals.anonymousMqttAccess') }}</label><el-select v-model="anon" size="small" :disabled="!admin" @change="saveAnon">
              <el-option :label="$t('signals.anonymousReadWrite')" value="rw" /><el-option :label="$t('signals.anonymousReadOnlyTokenRequired')" value="ro" /><el-option :label="$t('signals.noAnonymousAccessUseApi')" value="none" /></el-select></template>
          </div>
          <p class="small muted" style="margin-top:6px">{{ $t('signals.modbusDataTypesAndWord') }}</p></div>

        <div class="card"><h3>{{ $t('signals.recordingReplay') }}</h3>
          <div v-if="s?.recording" class="small"><span class="bad">{{ $t('plants.recording') }}</span> {{ $t('signals.n01Min2Changes', [s.recording.file, s.recording.minutes, s.recording.changes]) }}
            <el-button size="small" @click="rec('stop')">{{ $t('common.stop') }}</el-button></div>
          <el-button v-else size="small" :disabled="!edit" @click="rec('start')">{{ $t('signals.startRecording') }}</el-button>
          <div v-if="s?.replay" class="small" style="margin-top:6px"><span class="ok">{{ $t('signals.replaying') }}</span> {{ s.replay.file }} {{ s.replay.pos }}/{{ s.replay.frames }} {{ s.replay.sim_time }}
            <el-button size="small" @click="post(api + '/signals/replay', { action: 'stop' })">{{ $t('signals.stopReplay') }}</el-button></div>
          <div v-for="f in s?.recordings || []" :key="f.file" class="small row"><span class="mono">{{ f.file }}</span><span class="muted">{{ f.kb }} KB</span><span class="grow" />
            <el-button size="small" link type="primary" :disabled="!edit || !!s?.replay" @click="play(f.file)">{{ $t('common.replay') }}</el-button></div>
          <p class="small muted">{{ $t('signals.recordingSavesChangedTagValues') }}</p></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { canEdit, del, download, fmt, get, isAdmin, P, post, put } from '../api';
import Chart from '../components/Chart.vue';
import DeliveryExport from '../components/DeliveryExport.vue';
import GuideButton from '../components/GuideButton.vue';

const props = defineProps<{ pid: string }>();
const api = P(props.pid), edit = canEdit(), admin = isAdmin();
const tree = ref<any[]>([]), s = ref<any>(null), q = ref(''), treeRef = ref<any>(), tag = ref<any>(null), trend = ref<any>(null), hours = ref(4), wval = ref<any>(null);
const faultCard = ref<HTMLElement>();
const PN: Record<string, string> = { opcua: 'OPC UA', modbus: 'Modbus', mqtt: 'MQTT' };
const ANON: Record<string, string> = { rw: $t('signals.readWrite'), ro: $t('signals.readOnly2'), none: $t('signals.disabledSignInWithAn') };
const FMTS = ['int16', 'uint16', 'int32', 'uint32', 'float32', 'float64'], ORDERS = ['ABCD', 'CDAB', 'BADC', 'DCBA'];
const ff = reactive<any>({ protocol: 'mqtt', link: '', station: '', tag: '', mode: 'freeze', latency: 3, drop_pct: 30, value: '', rate: 1, minutes: 10, include_mes: true });
const settings = reactive<any>({ time: 'sim', lenient_types: true, allow_out_of_range: false, modbus: {}, mqtt: {} });
const mb = reactive<any>({ fmt: 'float32', order: 'ABCD', base: 1000, missing_unit: 'exception' });
const hb = ref(10), anon = ref('rw'), speed = ref(1);
let settingsLoaded = false;

const others = (p: string) => (s.value?.endpoints?.all?.[p] || []).slice(1);
const hostOf = (a: string) => a.replace(/^opc\.tcp:\/\//, '').replace(/\/vfactory\/$/, '');
function copy(t: string) { navigator.clipboard?.writeText(t).then(() => ElMessage.success($t('signals.copied') + t), () => ElMessage.info(t)); }
const openDocs = () => window.open('/docs');
const treeData = computed(() => tree.value.map((st: any) => {
  const groups: Record<string, any[]> = {};
  for (const t of st.tags) { const g = t.name.includes('/') ? t.name.split('/')[0] : $t('common.other'); (groups[g] ||= []).push({ ...t, label: t.name.split('/').slice(1).join('/') || t.name, leaf: true }); }
  return { key: st.id, label: `${st.id} ${st.name}`, children: Object.entries(groups).map(([g, ts]) => ({ key: st.id + '/' + g, label: g, children: ts })) };
}));
const tagsOf = (sid: string) => { const st = tree.value.find((x: any) => x.id === sid); return st ? st.tags.map((t: any) => t.name) : []; };
const liveVal = computed(() => { if (!tag.value) return null; const st = tree.value.find((x: any) => tag.value.key.startsWith(x.id + '/')); return st?.tags.find((t: any) => t.key === tag.value.key)?.value; });
const trendOpt = computed(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 55, right: 12, top: 14, bottom: 26 }, xAxis: { type: 'category', data: trend.value.t },
  yAxis: { type: 'value', scale: true }, series: [{ type: 'line', showSymbol: false, data: trend.value.v, areaStyle: { opacity: 0.08 } }] }));
function filt(v: string, data: any) { if (!v) return true; const t = (data.key + ' ' + (data.desc || '') + ' ' + data.label + ' ' + (data.opcua || '') + ' ' + (data.mqtt || '') + ' ' + (data.modbus || '')).toLowerCase(); return t.includes(v.toLowerCase()); }
watch(q, (v) => treeRef.value?.filter(v));
async function onNode(n: any) { if (!n.leaf) return; tag.value = n; wval.value = n.value; loadTrend(); }
async function loadTrend() { if (tag.value && tag.value.dtype !== 'str') trend.value = await get(`${api}/signals/trend?key=${encodeURIComponent(tag.value.key)}&hours=${hours.value}`); else trend.value = null; }
async function write() { const [sid, ...k] = tag.value.key.split('/'); await post(`${api}/station/${sid}/write`, { tag: k.join('/'), value: wval.value }); ElMessage.success($t('signals.written')); loadTree(); }
const netLinks = ref<any[]>([]), linkModes = ref<Record<string, string>>({});
const modesFor = (pr: string) => (pr === 'link' ? Object.keys(linkModes.value) : s.value?.supported?.[pr] || []);
function fixMode() { const sup = modesFor(ff.protocol); if (!sup.includes(ff.mode)) ff.mode = sup[0] || ''; }
async function loadArch() { try { const a = await get(api + '/architecture', true); netLinks.value = a.links || []; linkModes.value = a.link_modes || {}; } catch { netLinks.value = []; } }
function faultHere() { const [sid, ...k] = tag.value.key.split('/'); ff.station = sid; ff.tag = k.join('/'); if (!['freeze', 'bad', 'stuck', 'drift', 'drop'].includes(ff.mode)) ff.mode = 'stuck'; nextTick(() => faultCard.value?.scrollIntoView({ behavior: 'smooth', block: 'center' })); }
async function inject() {
  if (ff.protocol === 'link') {
    if (!ff.link) return ElMessage.warning($t('signals.selectACableOrWire2'));
    await post(api + '/signals/comm', { link: ff.link, mode: ff.mode, minutes: ff.minutes || 0, latency: ff.latency, drop_pct: ff.drop_pct });
    ElMessage.success($t('signals.injected01', [ff.link, linkModes.value[ff.mode]]));
    return loadStatus();
  }
  const b: any = { protocol: ff.protocol, mode: ff.mode, minutes: ff.minutes || 0, station: ff.station || undefined, tag: ff.tag || undefined };
  if (ff.mode === 'latency' || ff.mode === 'jitter') b.latency = ff.latency;
  if (ff.mode === 'drop') b.drop_pct = ff.drop_pct;
  if (ff.mode === 'stuck' && ff.value !== '') b.value = isNaN(Number(ff.value)) ? ff.value : Number(ff.value);
  if (ff.mode === 'drift') b.rate = ff.rate;
  if (ff.protocol === 'mqtt' && !ff.station) b.include_mes = ff.include_mes;
  const r = await post(api + '/signals/comm', b);
  ElMessage.success($t('signals.injected') + (r.rule ? `${PN[r.rule.protocol]} ${r.rule.station || ''}${r.rule.tag ? '/' + r.rule.tag : ''} ${s.value.modes[r.rule.mode]}` : ''));
  loadStatus();
}
async function clearRule(r: any) { await del(`${api}/signals/comm/${r.id}`); ElMessage.success($t('common.restored')); loadStatus(); }
async function clearAll() { await del(api + '/signals/comm'); ElMessage.success($t('signals.restoreAll')); loadStatus(); }
async function saveSettings(body: any) {
  const r = await put(api + '/protocol/settings', body);
  applySettings(r.settings);
  ElMessage.success($t('signals.protocolSettingsApplied'));
  loadTree();
}
async function saveAnon() { await put('/api/settings/mqtt', { anonymous: anon.value }); ElMessage.success($t('signals.anonymousMqttAccessUpdated')); loadStatus(); }
function applySettings(x: any) {
  Object.assign(settings, x);
  Object.assign(mb, x.modbus || {});
  hb.value = x.mqtt?.heartbeat_s ?? 10;
}
async function rec(a: string) { const r = await post(api + '/signals/record', { action: a }); ElMessage.success(a === 'start' ? $t('signals.recordingStarted') + r.file : $t('signals.saved') + r.file); loadStatus(); }
async function play(f: string) { await post(api + '/signals/replay', { file: f, speed: 10 }); ElMessage.success($t('signals.replayStarted10Speed')); loadStatus(); }
function exp(c: string) {
  if (c === 'json') return download(`${api}/points/v2`);
  download(c === 'xlsx' ? `${api}/points.xlsx` : c === 'csv' ? `${api}/points.csv` : `${api}/nodeset.xml`);
}
async function loadTree() { tree.value = await get(api + '/signals/tree', true); }
async function loadStatus() {
  s.value = await get(api + '/signals/status', true);
  if (!settingsLoaded && s.value?.settings) { applySettings(s.value.settings); settingsLoaded = true; } else if (s.value?.settings) settings.time = s.value.settings.time;
  if (s.value?.mqtt_auth) anon.value = s.value.mqtt_auth.anonymous;
  fixMode();
  try { speed.value = (await get(api + '/state', true))?.speed || 1; } catch { /* Ignore */ }
}
let t: any;
onMounted(() => { loadTree(); loadStatus(); loadArch(); t = setInterval(() => { loadTree(); loadStatus(); }, 3000); });
onUnmounted(() => clearInterval(t));
</script>

<style scoped>
.main { grid-template-columns: 300px 1fr 380px; align-items: start; } .side { display: grid; gap: 14px; }
@media (max-width: 1300px) { .main { grid-template-columns: 300px 1fr; } .side { grid-column: 1 / -1; grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 800px) { .main, .side { grid-template-columns: 1fr; } }
.ep { display: grid; gap: 4px; align-content: start; } .ep small { color: var(--mu); } .ep b { font-size: 20px; }
.addr { display: flex; align-items: center; gap: 4px; min-width: 0; }
.sig code { background: var(--hm-surface-2); color: var(--hm-text); border: 1px solid var(--hm-border); font-family: var(--hm-font-mono); padding: 2px 6px; border-radius: 4px; font-size: 12px;
  font-family: Consolas, 'Cascadia Mono', monospace; word-break: break-all; }
.more a { margin-right: 8px; cursor: pointer; font-family: Consolas, monospace; }
.timebar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 8px 12px; margin-bottom: 12px; border-radius: 8px;
  border: 1px solid var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); color: var(--tx, inherit); }
.timebar.wall { border-color: var(--hm-primary); }
.sig-tree { max-height: calc(100vh - 360px); min-height: 300px; overflow: auto; background: transparent; --el-tree-node-hover-bg-color: var(--hm-surface-3); color: var(--hm-text); font-size: 12.5px; }
.tn { display: flex; justify-content: space-between; width: 100%; padding-right: 6px; gap: 8px; font-size: 12.5px; font-weight: 400; } .tn .grp { color: var(--mu); }
.wr { display: flex; gap: 8px; align-items: center; margin-top: 10px; } .row { display: flex; gap: 6px; align-items: center; padding: 3px 0; }
.frm { display: grid; grid-template-columns: 64px 1fr; gap: 6px 8px; align-items: center; } .frm > label { font-size: 12px; color: var(--mu); }
.row2 { display: flex; gap: 6px; align-items: center; min-width: 0; flex-wrap: wrap; }
.rules { margin-top: 8px; display: grid; gap: 4px; } .rule { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
</style>
