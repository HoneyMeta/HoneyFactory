<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('monitor.equipmentLiveMonitor') }}</h2><span class="sub">{{ $t('monitor.dataTime0RefreshesEvery', [d?.now]) }}</span><span class="grow" />
      <el-radio-group v-model="filter"><el-radio-button value="">{{ $t('common.all') }}</el-radio-button><el-radio-button value="down">{{ $t('common.down') }}</el-radio-button><el-radio-button value="alarm">{{ $t('monitor.alarmActive') }}</el-radio-button></el-radio-group></div>
    <div class="grid g4" v-if="d">
      <div v-for="e in shown" :key="e.id" class="card eq click" :class="'b-' + e.status" @click="open(e)">
        <div class="top"><b>{{ e.code }}</b> <span>{{ e.name }}</span><span class="grow" /><span class="tag-st" :class="'st-' + (e.status || 'offline')">{{ ST[e.status] || $t('common.offline') }}</span></div>
        <div class="muted small">{{ ET[e.etype] }} · {{ e.line__label || '' }}</div>
        <div class="vals">
          <div v-if="e.power != null"><small>{{ $t('common.power2') }}</small><b>{{ fmt(e.power) }}</b> kW</div>
          <div v-if="e.oee8h != null"><small>8h OEE</small><b>{{ pct(e.oee8h, 0) }}</b></div>
          <div v-for="(v, k) in e.tags" :key="k"><small>{{ short(String(k)) }}</small><b>{{ fmt(v, 2) }}</b></div>
        </div>
        <div v-if="e.alarm" class="alarm">⚠ {{ e.alarm }}</div>
      </div>
    </div>
    <el-drawer v-model="dr" :title="cur ? `${cur.code} ${cur.name}` : ''" size="min(720px, 100%)">
      <template v-if="cur">
        <div style="display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap">
          <el-button @click="router.push('/mes/equipment/oee?eid=' + cur.id)">{{ $t('monitor.oeeDowntimeTimeline') }}</el-button>
          <el-button @click="router.push('/mes/e/repair_order')">{{ $t('mobile.requestRepair') }}</el-button>
        </div>
        <el-table :data="tags" size="small" max-height="560"><el-table-column prop="name" :label="$t('common.tag')" /><el-table-column prop="value" :label="$t('common.value')" /><el-table-column prop="ts" :label="$t('common.time')" width="160" /></el-table>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { fmt, get, pct } from '../api';

const router = useRouter();
const d = ref<any>(null), filter = ref(''), dr = ref(false), cur = ref<any>(null), tags = ref<any[]>([]);
const ST: Record<string, string> = { running: $t('common.running'), idle: $t('common.idle'), setup: $t('common.changeover'), down: $t('common.down'), offline: $t('common.offline') };
const ET: Record<string, string> = { furnace: $t('energy.inductionFurnace'), treatment: $t('monitor.nodularizationStation'), sand: $t('energy.sandPreparation'), molding: $t('monitor.moldingLine'), cooling: $t('monitor.coolingLine'), shotblast: $t('monitor.shotBlaster'), cnc: $t('monitor.machiningCenter'), deburr: $t('energy.deburring'),
  inspection: $t('monitor.testStation'), warehouse: $t('monitor.asRs'), agv: 'AGV', crew: $t('common.teams'), receiving: $t('monitor.receivingDock') };
const short = (k: string) => k.split('/').slice(-2).join('/');
const shown = computed(() => (d.value?.items || []).filter((e: any) => (filter.value === 'down' ? e.status === 'down' : filter.value === 'alarm' ? e.alarm : true)));
let t: any;
async function load() { d.value = await get('/api/equipment/monitor', true); }
async function open(e: any) { cur.value = e; dr.value = true; tags.value = await get('/api/equipment/tags/' + e.id); }
onMounted(() => { load(); t = setInterval(load, 3000); });
onUnmounted(() => clearInterval(t));
</script>

<style scoped>
.eq { padding: 10px 12px; overflow: hidden; } .eq::before { content: ''; position: absolute; left: 0; right: 0; top: 0; height: 3px; background: var(--hm-offline); }
.b-running::before { background: var(--hm-run) !important; } .b-idle::before { background: var(--hm-idle) !important; } .b-down::before { background: var(--hm-fault) !important; } .b-setup::before { background: var(--hm-setup) !important; }
.eq:hover { box-shadow: var(--hm-e2); border-color: var(--hm-border-strong); }
.top { display: flex; gap: 6px; align-items: center; color: var(--hm-text); } .grow { flex: 1; } .top span:nth-child(2) { font-size: var(--hm-fs-sm); color: var(--hm-text-2); }
.vals { display: grid; grid-template-columns: 1fr 1fr; gap: 4px 10px; margin-top: 8px; } .vals small { color: var(--hm-text-3); font-size: var(--hm-fs-2xs); display: block; }
.vals b { font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; color: var(--hm-text); }
.alarm { margin-top: 6px; color: var(--hm-fault-ink); font-size: var(--hm-fs-xs); }
</style>
