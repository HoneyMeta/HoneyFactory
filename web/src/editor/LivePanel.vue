<template>
  <div class="lp">
    <template v-if="!id">
      <div class="dt-head"><el-icon class="dt-ic" style="background:#15a34a"><Monitor /></el-icon><div><b>{{ $t('livePanel.factoryLiveMonitor') }}</b><small>{{ $t('livePanel.selectEquipmentToViewIts') }}</small></div></div>
      <div v-if="st" class="lp-kv">
        <div v-for="k in KPIS" :key="k[0]" v-show="st.kpi[k[0]] !== undefined && st.kpi[k[0]] !== null"><small>{{ k[1] }}</small><b class="mono">{{ k[2] ? k[2](st.kpi[k[0]]) : fmt(st.kpi[k[0]]) }}</b></div>
      </div>
      <div class="sub-t">{{ $t('common.alarm') }} <small class="muted">{{ alarmed.length }}</small></div>
      <div v-for="s in alarmed" :key="s.id" class="lk click" @click="pick(s.id)"><span class="dot" :style="{ background: STATE_COLOR[s.state] }" /><b>{{ s.id }}</b> {{ s.alarm }}</div>
      <p v-if="!alarmed.length" class="ok small">{{ $t('livePanel.noActiveAlarms') }}</p>
      <div class="sub-t">{{ $t('common.equipment') }} <small class="muted">{{ $t('livePanel.oeeLowToHigh') }}</small></div>
      <div v-for="s in byOee" :key="s.id" class="lk click" @click="pick(s.id)"><span class="dot" :style="{ background: STATE_COLOR[s.state] || '#888' }" /><b>{{ s.id }}</b> {{ s.name }}
        <span class="grow" /><span class="mono small">{{ s.oee ? pct(s.oee.OEE, 0) : '' }}</span></div>
    </template>
    <template v-else-if="d">
      <div class="dt-head"><el-icon class="dt-ic" :style="{ background: STATE_COLOR[d.state] || '#888' }"><Monitor /></el-icon>
        <div><b>{{ d.name }}</b><small class="mono">{{ d.id }} · {{ STATE_CN[d.state] || d.state }}{{ d.alarm ? ' · ⚠ ' + d.alarm : '' }}</small></div></div>
      <div class="chips"><span class="chip">{{ $t('details.power0Kw', [d.power]) }}</span><span v-if="d.oee" class="chip">OEE {{ pct(d.oee.OEE, 0) }}</span>
        <span v-if="d.oee" class="chip">{{ $t('livePanel.availability0Performance1Quality', [pct(d.oee.A, 0), pct(d.oee.P, 0), pct(d.oee.Q, 0)]) }}</span></div>
      <div class="dt-actions"><el-button v-if="session.user?.role !== 'student'" size="small" type="primary" plain @click="askAI"><el-icon><ChatDotRound /></el-icon> {{ $t('livePanel.askAiToInvestigate') }}</el-button>
        <el-button size="small" @click="addBp"><el-icon><Flag /></el-icon> {{ $t('livePanel.pauseOnFailure') }}</el-button></div>
      <el-tabs v-model="tab" class="lp-tabs">
        <el-tab-pane :label="$t('livePanel.overview')" name="ov">
          <div v-if="tb" class="lp-tb">
            <div class="sub-t">{{ $t('livePanel.timeBreakdownLast8Hours') }} <small class="muted">OEE {{ tb.oee != null ? pct(tb.oee, 0) : '—' }}</small></div>
            <div class="lp-bar"><el-tooltip v-for="c in tbSegs" :key="c.key" :content="`${c.label} ${(c.v * 100).toFixed(1)}%`"><i :style="{ width: c.v * 100 + '%', background: c.color }" /></el-tooltip></div>
            <div class="lp-lg"><span v-for="c in tbSegs.filter((x) => x.v >= 0.02)" :key="c.key"><i :style="{ background: c.color }" />{{ c.label }} {{ (c.v * 100).toFixed(0) }}%</span></div>
          </div>
          <div class="lp-kv"><div v-for="t in keyTags" :key="t[0]"><small>{{ t[1].d || t[0] }}</small><b class="mono">{{ fmt(t[1].v) }}</b> <i>{{ t[1].u }}</i></div></div>
          <div class="sub-t">{{ $t('livePanel.faultInjectionOperation') }}</div>
          <div class="btns"><el-button v-for="(v, k) in d.faults" :key="k" size="small" type="warning" plain :disabled="!edit || !!ed.replay" @click="fault(String(k))">{{ v }}</el-button>
            <el-button size="small" :disabled="!edit || !!ed.replay" @click="fault('clear')">{{ $t('common.clearFailure') }}</el-button>
            <el-button size="small" :disabled="!edit || !!ed.replay" @click="enable(!d.enabled)">{{ d.enabled ? $t('livePanel.disableEquipment') : $t('livePanel.enableEquipment') }}</el-button></div>
        </el-tab-pane>
        <el-tab-pane :label="$t('livePanel.system')" name="par">
          <div v-for="[k, t] in writable" :key="k" class="ctl"><label>{{ t.d || k }} <small class="muted">{{ t.u }}{{ t.lo != null ? ` · ${t.lo}–${t.hi}` : '' }}</small></label>
            <div class="row"><el-switch v-if="typeof t.v === 'boolean'" v-model="wv[k]" /><el-input-number v-else v-model="wv[k]" size="small" :min="t.lo ?? undefined" :max="t.hi ?? undefined" :step="0.1" :controls="false" style="flex:1" />
              <el-button size="small" type="primary" :disabled="!edit" @click="write(k)">{{ $t('livePanel.system') }}</el-button></div></div>
          <p v-if="!writable.length" class="muted small">{{ $t('livePanel.noWritableTags') }}</p>
          <p class="small muted">{{ $t('livePanel.setpointsAreWrittenDirectlyTo') }}</p>
        </el-tab-pane>
        <el-tab-pane :label="$t('livePanel.trends')" name="tr">
          <div class="row"><el-select v-model="trKey" filterable size="small" style="flex:1" @change="loadTrend"><el-option v-for="[k, t] in numTags" :key="k" :label="$t('common.n012', [t.d || k, k])" :value="k" /></el-select>
            <el-select v-model="trH" size="small" style="width:86px" @change="loadTrend"><el-option v-for="h in [1, 4, 12, 24]" :key="h" :label="h + $t('common.hours2')" :value="h" /></el-select>
            <el-tooltip :content="$t('livePanel.pinToCanvasFloatingPanel')"><el-button size="small" :disabled="!trKey" @click="pin"><el-icon><Paperclip /></el-icon></el-button></el-tooltip></div>
          <Chart v-if="trend" :option="trendOpt" :height="220" />
        </el-tab-pane>
        <el-tab-pane :label="$t('common.tag')" name="pt">
          <table class="tags"><tr v-for="r in ptRows" :key="r.k"><td class="mono" :title="r.addr">{{ r.k }}</td><td class="mono">{{ fmt(r.v) }}</td><td class="muted">{{ r.u }}</td></tr></table>
          <p class="small muted">{{ $t('livePanel.hoverOverATagName') }}</p>
        </el-tab-pane>
        <el-tab-pane :label="$t('common.logs')" name="log"><div v-for="e in evs" :key="e.seq" class="ev" :class="e.kind"><time class="mono">{{ e.t.slice(5) }}</time> {{ e.msg }}</div>
          <p v-if="!evs.length" class="muted small">{{ $t('livePanel.noneYet') }}</p></el-tab-pane>
        <el-tab-pane :label="$t('livePanel.groundTruth')" name="truth"><p class="small muted">{{ $t('livePanel.theSimulationSActualInternal') }}</p><pre class="small lp-pre">{{ JSON.stringify(d.truth, null, 1) }}</pre></el-tab-pane>
      </el-tabs>
    </template>
    <p v-else-if="missing" class="muted small" style="padding:12px">{{ $t('livePanel.thisBlockIsNotYet') }}</p>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, markRaw, onUnmounted, reactive, ref, watch } from 'vue';
import { canEdit, fmt, get, P, pct, post, session } from '../api';
import { askAssistant } from '../assistant';
import Chart from '../components/Chart.vue';
import ChartFloat from './shell/ChartFloat.vue';
import { ed, openFloat, select, STATE_CN, STATE_COLOR, viewState } from './store';

const edit = canEdit();
const id = computed(() => (ed.sel.length === 1 ? ed.sel[0] : ''));
const st = viewState;
const d = ref<any>(null), missing = ref(false), tab = ref('ov'), wv = reactive<Record<string, any>>({});
const trKey = ref(''), trH = ref(4), trend = ref<any>(null), points = ref<Record<string, any>>({});
const KPIS: [string, string, ((v: any) => string)?][] = [['good', $t('common.acceptedQty')], ['castings', $t('breakpoints.castingsIncoming')], ['machined', $t('common.machining')], ['scrap_rate', $t('common.scrapRate'), (v) => pct(v, 2)],
  ['escape', $t('breakpoints.missedInspection')], ['energy_kwh', $t('livePanel.energyKwh'), (v) => String(Math.round(v))], ['kwh_per_t_melt', $t('livePanel.energyPerTonKwhT')]];
const stations = computed(() => (st.value?.stations || []).filter((s: any) => s.kind !== 'crew'));
const alarmed = computed(() => stations.value.filter((s: any) => s.alarm));
const byOee = computed(() => [...stations.value].filter((s: any) => s.oee).sort((a: any, b: any) => a.oee.OEE - b.oee.OEE).slice(0, 30));
const writable = computed(() => Object.entries(d.value?.tags || {}).filter(([, t]: any) => t.w) as [string, any][]);
const numTags = computed(() => Object.entries(d.value?.tags || {}).filter(([, t]: any) => typeof t.v === 'number') as [string, any][]);
const keyTags = computed(() => numTags.value.filter(([k]) => !k.startsWith('Setpoint') && !k.startsWith('Common/Energy')).slice(0, 10));
const evs = ref<any[]>([]);
// GET /points rows are keyed by the backend's column names (Chinese; English variants accepted)
const PT_COLS: Record<string, string[]> = { station: ['\u5de5\u4f4d', 'Station', 'Workstation'], tag: ['\u70b9\u4f4d', 'Tag'], mqtt: ['MQTT \u4e3b\u9898', 'MQTT Topic'] };
const col = (row: any, k: string) => { for (const c of PT_COLS[k]) if (row?.[c] !== undefined) return row[c]; return ''; };
const ptRows = computed(() => Object.entries(d.value?.tags || {}).map(([k, t]: any) => {
  const p = points.value[`${id.value}/${k}`];
  return { k, v: t.v, u: t.u, addr: p ? `OPC UA ${p['OPC UA NodeId']}\nMQTT ${col(p, 'mqtt')}${p.Modbus ? '\nModbus ' + p.Modbus : ''}` : '' };
}));
const trendOpt = computed(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 46, right: 10, top: 12, bottom: 24 }, xAxis: { type: 'category', data: trend.value.t },
  yAxis: { type: 'value', scale: true }, series: [{ type: 'line', showSymbol: false, data: trend.value.v, areaStyle: { opacity: 0.08 } }] }));

let poll: any = null;
async function load(first = false) {
  const sid = id.value; if (!sid || ed.replay) return;
  // Not yet in the running factory (new block or pending structural changes): skip requests to avoid repeated 404s.
  if (ed.runtime?.stations && !ed.runtime.stations.some((x: any) => x.id === sid)) { d.value = null; missing.value = true; return; }
  const r = await get(`${P(ed.pid)}/station/${encodeURIComponent(sid)}`, true).catch(() => null);
  if (sid !== id.value) return;
  if (!r) { d.value = null; missing.value = true; return; }
  d.value = r; missing.value = false;
  if (first) {
    for (const [k, t] of Object.entries(r.tags) as any) if (t.w) wv[k] = t.v;
    if (!trKey.value || !r.tags[trKey.value]) trKey.value = Object.keys(r.history || {})[0] || Object.keys(r.tags).find((k) => typeof r.tags[k].v === 'number' && !k.startsWith('Setpoint')) || '';
    trend.value = null; if (tab.value === 'tr') loadTrend();
    const all = await get(`${P(ed.pid)}/events?since=0&limit=500`, true).catch(() => []);
    evs.value = all.filter((e: any) => e.station === sid).reverse().slice(0, 80);
    if (!Object.keys(points.value).length) get(P(ed.pid) + '/points', true).then((rows) => { for (const x of rows) points.value[`${String(col(x, 'station')).split(' ')[0]}/${col(x, 'tag')}`] = x; }).catch(() => {});
  }
}
const tb = ref<any>(null), tbCls = ref<any[]>([]);
const tbSegs = computed(() => (tb.value ? tbCls.value.map((c: any) => ({ ...c, v: tb.value.share?.[c.key] || 0 })).filter((c: any) => c.v > 0) : []));
async function loadTb() {
  const sid = id.value; if (!sid) return;
  const r = await get(`${P(ed.pid)}/analysis/stats?hours=8&warmup=1`, true).catch(() => null);
  if (!r || sid !== id.value) return;
  tbCls.value = r.classes || []; tb.value = (r.objects || []).find((o: any) => o.id === sid) || null;
}
function pin() {
  openFloat({ id: 'chart', title: `${d.value?.name || id.value} · ${trKey.value}`, icon: 'TrendCharts', component: markRaw(ChartFloat), size: [480, 300] },
    { sid: id.value, tag: trKey.value, hours: trH.value }, `${id.value}/${trKey.value}`);
}
async function loadTrend() { if (trKey.value) trend.value = await get(`${P(ed.pid)}/signals/trend?key=${encodeURIComponent(id.value + '/' + trKey.value)}&hours=${trH.value}`).catch(() => null); }
async function fault(k: string) { await post(`${P(ed.pid)}/station/${id.value}/fault`, { kind: k }); ElMessage.success($t('livePanel.executed')); load(); }
async function enable(v: boolean) { await post(`${P(ed.pid)}/station/${id.value}/enable`, { enabled: v }); load(); }
async function write(k: string) { await post(`${P(ed.pid)}/station/${id.value}/write`, { tag: k, value: wv[k] }); ElMessage.success($t('livePanel.setTo0', [k])); }
async function addBp() {
  await post(P(ed.pid) + '/breakpoints', { cond: { kind: 'state', id: id.value, state: 'Stopped' } });
  ElMessage.success($t('livePanel.breakpointAddedSimulationWillPause')); window.dispatchEvent(new CustomEvent('vf:breakpoints-changed'));
}
function askAI() { askAssistant($t('livePanel.whatIsTheCurrentStatus', [d.value?.name || id.value, id.value])); }
function pick(sid: string) { select([sid]); }
watch(id, () => { d.value = null; tb.value = null; missing.value = false; clearInterval(poll); if (id.value) { load(true); loadTb(); poll = setInterval(() => load(), 2000); } }, { immediate: true });
watch(tab, (t) => { if (t === 'tr' && !trend.value) loadTrend(); });
// Context menu "View Tags and Protocol Addresses": switch to the tags tab
const onTab = (e: any) => { if (e.detail) tab.value = e.detail; };
addEventListener('vf:live-tab', onTab);
onUnmounted(() => { clearInterval(poll); removeEventListener('vf:live-tab', onTab); });
</script>
