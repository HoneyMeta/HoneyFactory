<template>
  <div class="dl">
    <template v-if="kind === 'events'">
      <div class="dl-bar"><el-select v-model="ek" size="small" clearable :placeholder="$t('dockLists.allTypes')" style="width:110px"><el-option v-for="(v, k) in EK" :key="k" :value="k" :label="v" /></el-select>
        <el-input v-model="q" size="small" clearable :placeholder="$t('dockLists.equipmentOrContent')" style="width:160px" /><span class="muted small">{{ $t('common.n03', [shown.length]) }}</span></div>
      <div v-for="e in shown" :key="e.seq" class="ev click" :class="e.kind" @click="e.station && select([e.station])">
        <time class="mono">{{ e.t.slice(5) }}</time> <b>{{ e.station }}</b> {{ e.msg }}</div>
    </template>
    <template v-else-if="kind === 'parts'">
      <div class="dl-bar"><el-select v-model="pst" size="small" style="width:100px" @change="loadParts"><el-option v-for="(v, k) in PS" :key="k" :label="v" :value="k" /></el-select>
        <el-input v-model="pq" size="small" :placeholder="$t('dockLists.partIdPressEnterTo')" clearable style="width:180px" @keyup.enter="openPart(pq)" />
        <el-button size="small" @click="ed.trackReq = { id: '', n: Date.now() }; ed.view = '3d'">{{ $t('dockLists.followAPart') }}</el-button></div>
      <div v-for="p in parts" :key="p.id" class="ev click" @click="openPart(p.id)"><b class="mono">{{ p.id }}</b> <span class="chip">{{ PS[p.status] || p.status }}</span>
        <span class="muted">{{ p.type }} {{ p.heat || '' }} {{ p.scrap_cause || '' }}</span></div>
    </template>
    <template v-else>
      <div v-if="crew"><div class="small muted dl-bar">{{ $t('dockLists.onDuty0Working1', [crew.workers.length, crew.workers.filter((w: any) => w.state === 'work').length]) }}</div>
        <div v-for="w in crew.workers" :key="w.id" class="ev"><b>{{ w.id }}</b> {{ w.role }} <span :class="w.state === 'work' ? 'ok' : 'muted'">{{ WS[w.state] || w.state }}</span> <span class="small">{{ w.serving }}</span></div></div>
      <div v-for="o in pools" :key="o.id" class="ev click" @click="select([o.id])"><b>{{ o.id }}</b> {{ o.name }} <span class="muted">{{ STATE_CN[o.state] || o.state }}</span></div>
      <div v-if="!crew && !pools.length" class="muted small">{{ $t('dockLists.thisFactoryHasNoTeams') }}
        <div style="margin-top:6px"><el-button size="small" :disabled="!canEdit()" @click="addPool">{{ $t('dockLists.addWorkerPool') }}</el-button></div></div>
    </template>

    <el-dialog v-model="partOpen" :title="$t('dockLists.partRecord') + (part?.id || '')" width="min(720px, 96vw)" append-to-body>
      <template v-if="part">
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item :label="$t('common.status')">{{ PS[part.status] || part.status }}</el-descriptions-item><el-descriptions-item :label="$t('common.product')">{{ part.type }}</el-descriptions-item>
          <el-descriptions-item :label="$t('common.order')">{{ part.order || '—' }}</el-descriptions-item>
          <el-descriptions-item v-for="k in EXTRA.filter((k) => part[k[0]] !== undefined)" :key="k[0]" :label="k[1]">{{ part[k[0]] }}</el-descriptions-item>
          <el-descriptions-item :label="$t('common.scrapReason')">{{ part.scrap_cause || '—' }}</el-descriptions-item></el-descriptions>
        <p class="small"><b>{{ $t('dockLists.actualDefectsSimulationGroundTruth') }}</b>{{ $t('dockLists.n0', [JSON.stringify(part.defects)]) }}&emsp;<b>{{ $t('dockLists.inspectionResult') }}</b>{{ part.inspection ? part.inspection.result + ' ' + (part.inspection.found || []).join($t('common.k360')) : '—' }}</p>
        <el-timeline><el-timeline-item v-for="(h, i) in part.history" :key="i" :timestamp="h.t">{{ h.station }} · {{ h.event }}
          <span class="small muted">{{ Object.entries(h).filter(([k]) => !['t', 'station', 'event'].includes(k)).map(([k, v]) => `${k}=${v}`).join(' ') }}</span></el-timeline-item></el-timeline>
      </template>
      <template #footer>
        <el-button @click="traceInGraph">{{ $t('dockLists.traceStepByStepIn') }}</el-button>
        <el-button type="primary" @click="partOpen = false; ed.view = '3d'; ed.trackReq = { id: part.id, n: Date.now() }">{{ $t('dockLists.followIn3d') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { canEdit, get, P } from '../api';
import { placeBlock } from './shell/place';
import { ed, select, STATE_CN, viewState } from './store';

const props = defineProps<{ kind: 'events' | 'parts' | 'crew' }>();
const EK: Record<string, string> = { fault: $t('common.fault'), alarm: $t('common.alarm'), repair: $t('common.repair'), tool: $t('common.toolChange'), plan: $t('common.plan'), scenario: $t('common.scenario'), inject: $t('common.inject'), breakpoint: $t('common.breakpoint'), info: $t('dockLists.info'), layout: $t('dockLists.model') };
const PS: Record<string, string> = { all: $t('common.all'), WIP: $t('common.wip'), GOOD: $t('common.good'), FG: $t('common.goodsReceipt'), SHIPPED: $t('dockLists.shipped'), SCRAP: $t('common.scrapped'), RAW_STORE: $t('common.rawCastingStore') };
const WS: Record<string, string> = { idle: $t('common.idle2'), walk: $t('dockLists.walking'), carry: $t('common.transport'), work: $t('common.working'), absent: $t('dockLists.absent') };
const EXTRA: [string, string][] = [['heat', $t('common.heat')], ['ladle', $t('common.ladle')], ['pour_temp', $t('dockLists.pouringTemp')], ['mg', $t('dockLists.residualMg')], ['sand_moisture', $t('dockLists.sandMoisture')], ['lot', $t('dockLists.lot')]];
const events = ref<any[]>([]), ek = ref(''), q = ref('');
const parts = ref<any[]>([]), pst = ref('all'), pq = ref(''), part = ref<any>(null), partOpen = ref(false);
const shown = computed(() => events.value.filter((e) => (!ek.value || e.kind === ek.value) && (!q.value || `${e.station} ${e.msg}`.includes(q.value))).slice(0, 300));
const crew = computed(() => viewState.value?.stations?.find((s: any) => s.kind === 'crew'));
const pools = computed(() => (viewState.value?.stations || []).filter((s: any) => s.kind === 'operators'));
let lastSeq = 0, timer: any = null;
async function poll() {
  if (props.kind === 'events') {
    const ev = await get(`${P(ed.pid)}/events?since=${lastSeq}&limit=300`, true).catch(() => []);
    if (ev.length) { lastSeq = ev[ev.length - 1].seq; events.value = [...ev.reverse(), ...events.value].slice(0, 800); }
  } else if (props.kind === 'parts') loadParts();
}
async function loadParts() { parts.value = await get(`${P(ed.pid)}/parts?limit=80&status=${pst.value === 'all' ? '' : pst.value}`, true).catch(() => []); }
async function openPart(id: string) { if (!id) return; part.value = await get(`${P(ed.pid)}/part/${encodeURIComponent(id.trim())}`); partOpen.value = true; }
watch(() => ed.partReq, (r) => { if (r?.id) openPart(r.id); });
function traceInGraph() {
  const steps = (part.value?.history || []).filter((h: any) => (ed.model?.blocks || []).some((b: any) => b.id === h.station));
  if (!steps.length) return;
  ed.partTrace = { id: part.value.id, steps, i: 0 };
  partOpen.value = false; ed.view = 'graph';
}
onMounted(() => { poll(); timer = setInterval(poll, props.kind === 'events' ? 2000 : 5000); });
onUnmounted(() => clearInterval(timer));
function addPool() { const b = placeBlock('operators', { node: [100, 60] }); if (b) ed.rightTab = 'props'; }
</script>
