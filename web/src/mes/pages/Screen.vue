<template>
  <!-- Workshop dashboard (light theme, same design as HoneyMOM): embedded in the HoneyFactory UI; "Fullscreen" fills the screen with this panel for workshop TV displays -->
  <div ref="root" class="scr hm-grid-bg" :class="{ fs }" data-k="mes-screen">
    <header>
      <img src="/brand/logo-mark-64.png" :alt="$t('common.honey')" />
      <div class="ttl"><h1>{{ company }}</h1><small>{{ $t('screen.teachingMesProductionControlDisplay') }}</small></div>
      <span class="grow" />
      <div class="clk"><b>{{ (d?.now || '').slice(11, 19) || '—' }}</b><small>{{ $t('screen.n0DataTime', [(d?.now || '').slice(0, 10)]) }}</small></div>
      <el-button @click="toggleFs"><el-icon><FullScreen /></el-icon>&nbsp;{{ fs ? $t('screen.exitFullScreen') : $t('view3D.fullScreen') }}</el-button>
      <el-button @click="router.push('/mes')"><el-icon><Back /></el-icon>{{ $t('screen.home') }}</el-button>
    </header>
    <template v-if="d">
      <div class="kpis">
        <div class="k"><small>{{ $t('home.pouredReceivedToday') }}</small><b>{{ d.kpi.production.castings }}</b><i>{{ $t('common.pcs') }}</i></div>
        <div class="k"><small>{{ $t('home.machinedToday') }}</small><b>{{ d.kpi.production.machined }}</b><i>{{ $t('common.pcs') }}</i></div>
        <div class="k ok"><small>{{ $t('home.storedToday') }}</small><b>{{ d.kpi.production.stored }}</b><i>{{ $t('common.pcs') }}</i></div>
        <div class="k" :class="d.kpi.quality.scrap_rate > .03 ? 'bad' : 'ok'"><small>{{ $t('common.scrapRate') }}</small><b>{{ pct(d.kpi.quality.scrap_rate, 2) }}</b></div>
        <div class="k" :class="avg == null ? '' : avg < .6 ? 'bad' : avg < .8 ? 'warn' : 'ok'"><small>{{ $t('common.avgOee') }}</small><b>{{ pct(avg) }}</b></div>
        <div class="k"><small>{{ $t('home.powerToday') }}</small><b>{{ Math.round(d.kpi.energy.kwh) }}</b><i>kWh</i></div>
        <div class="k"><small>{{ $t('energy.furnaceKwhT') }}</small><b>{{ d.kpi.energy.kwh_per_t || '—' }}</b><i>kWh/t</i></div>
      </div>
      <div class="body">
        <div class="panel" style="grid-column: span 2"><h3>{{ $t('home.outputLast24H') }} <small>{{ $t('home.hourly') }}</small></h3><Chart :option="hourOpt" :height="250" /></div>
        <div class="panel"><h3>{{ $t('screen.machineOee') }}</h3><Chart :option="oeeOpt" :height="250" /></div>
        <div class="panel"><h3>{{ $t('home.equipmentStatus') }}</h3>
          <div class="eqs"><div v-for="e in mon" :key="e.id" class="e" :class="'s-' + (e.status || 'offline')" :title="e.name"><b>{{ e.code }}</b><span>{{ ST[e.status] || $t('common.offline') }}</span></div></div></div>
        <div class="panel"><h3>{{ $t('home.todaySTopDefects') }}</h3><Chart :option="parOpt" :height="230" /></div>
        <div class="panel"><h3>{{ $t('screen.liveAlarms') }}</h3>
          <div v-for="a in d.alarms" :key="a.id" class="al"><i class="dot" />{{ a.equipment__label }} · {{ a.msg }} <em>{{ (a.start || '').slice(11, 16) }}</em></div>
          <p v-if="!d.alarms.length" class="ok small">{{ $t('screen.allEquipmentOperatingNormally') }}</p>
          <h3 style="margin-top:12px">{{ $t('screen.workOrderProgress') }}</h3>
          <div v-for="o in d.orders.slice(0, 4)" :key="o.id" class="wo"><span>{{ o.code }} {{ o.customer }}</span>
            <div class="pb"><div :style="{ width: Math.min(100, (o.qty_done || 0) / o.qty * 100) + '%' }" /></div><em>{{ o.qty_done || 0 }}/{{ o.qty }}</em></div>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import Chart from '../../components/Chart.vue';
import { CH } from '../../design/chart';
import { get, mes, pct } from '../api';

const router = useRouter(), d = ref<any>(null), mon = ref<any[]>([]), root = ref<HTMLElement>(), fs = ref(false);
const company = computed(() => mes.user?.company || mes.st?.plant_name || $t('screen.teachingPlant'));
const ST: Record<string, string> = { running: $t('common.running'), idle: $t('common.idle'), setup: $t('common.changeover'), down: $t('common.down') };
let t: any;
async function load() { d.value = await get('/api/dash/home', true); mon.value = (await get('/api/equipment/monitor', true)).items.filter((e: any) => !['crew', 'agv'].includes(e.etype)); }
function toggleFs() { if (document.fullscreenElement) document.exitFullscreen(); else root.value?.requestFullscreen?.(); }
const onFs = () => { fs.value = document.fullscreenElement === root.value; };
onMounted(() => { load(); t = setInterval(load, 8000); document.addEventListener('fullscreenchange', onFs); });
onUnmounted(() => { clearInterval(t); document.removeEventListener('fullscreenchange', onFs); if (document.fullscreenElement === root.value) document.exitFullscreen(); });
const avg = computed(() => { const o = d.value.kpi.equipment.oee.filter((x: any) => x.OEE != null); return o.length ? o.reduce((a: number, x: any) => a + x.OEE, 0) / o.length : null; });
const hourOpt = computed(() => { const hs = d.value.hours, H = d.value.hourly; const s = (k: string) => hs.map((h: string) => H[h]?.[k] || 0);
  return { tooltip: { trigger: 'axis' }, legend: { top: 0, right: 0 }, grid: { left: 40, right: 10, top: 30, bottom: 24 }, xAxis: { type: 'category', data: hs.map((h: string) => h.slice(11, 13)) },
    yAxis: { type: 'value' }, series: [{ name: $t('home.pouring'), type: 'bar', data: s('poured') }, { name: $t('common.machining'), type: 'bar', data: s('machined') },
      { name: $t('common.goodsReceipt'), type: 'line', smooth: true, data: s('stored'), itemStyle: { color: CH.ok } }] }; });
const oeeOpt = computed(() => { const o = d.value.kpi.equipment.oee.filter((x: any) => x.OEE != null);
  return { grid: { left: 70, right: 52, top: 6, bottom: 6 }, xAxis: { type: 'value', max: 1, show: false }, yAxis: { type: 'category', inverse: true, data: o.map((x: any) => x.code) },
    series: [{ type: 'bar', data: o.map((x: any) => ({ value: x.OEE, itemStyle: { color: x.OEE < .6 ? CH.bad : x.OEE < .8 ? CH.warn : CH.ok } })), label: { show: true, position: 'right', formatter: (p: any) => (p.value * 100).toFixed(0) + '%' } }] }; });
const parOpt = computed(() => ({ tooltip: {}, series: [{ type: 'pie', radius: ['40%', '60%'], data: d.value.kpi.quality.pareto.slice(0, 6).map((x: any) => ({ name: x.name, value: x.n })) }] }));
</script>

<style scoped>
.scr { padding: 6px var(--hm-sp-5) var(--hm-sp-6); min-height: 100%; color: var(--hm-text); }
.scr.fs { overflow: auto; padding: 16px 24px; }
header { display: flex; align-items: center; gap: 12px; padding: 8px 0 12px; border-bottom: 1px solid var(--hm-border); margin-bottom: 14px; }
header img { height: 40px; width: 40px; }
.ttl h1 { font-size: var(--hm-fs-2xl); margin: 0; letter-spacing: 1px; font-weight: 700; color: var(--hm-text); line-height: 1.2; }
.ttl small { color: var(--hm-text-3); font-size: var(--hm-fs-xs); letter-spacing: 2px; }
.grow { flex: 1; }
.clk { text-align: right; margin-right: 8px; } .clk b { display: block; font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; font-size: 28px; line-height: 1.1; color: var(--hm-text); }
.clk small { color: var(--hm-text-3); font-size: var(--hm-fs-xs); }
.kpis { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); gap: 12px; margin-bottom: 12px; }
.k { background: var(--hm-surface); border: 1px solid var(--hm-border); border-top: 3px solid var(--hm-primary); border-radius: var(--hm-r-lg); box-shadow: var(--hm-e1); padding: 10px 14px; }
.k.ok { border-top-color: var(--hm-run); } .k.warn { border-top-color: var(--hm-idle); } .k.bad { border-top-color: var(--hm-fault); }
.k small { color: var(--hm-text-3); font-size: var(--hm-fs-xs); display: block; }
.k b { font-size: 30px; font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; font-weight: 700; color: var(--hm-text); line-height: 1.25; }
.k.ok b { color: var(--hm-run-ink); } .k.warn b { color: var(--hm-idle-ink); } .k.bad b { color: var(--hm-fault-ink); }
.k i { font-style: normal; color: var(--hm-text-3); font-size: var(--hm-fs-xs); margin-left: 4px; }
.body { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.panel { background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); box-shadow: var(--hm-e1); padding: 10px 14px; min-width: 0; }
.panel h3 { margin: 0 0 8px; font-size: var(--hm-fs-md); font-weight: 600; color: var(--hm-text); display: flex; align-items: center; gap: 8px; }
.panel h3::before { content: ''; width: 3px; height: 14px; border-radius: 2px; background: var(--hm-primary); }
.panel h3 small { color: var(--hm-text-3); font-weight: 400; font-size: var(--hm-fs-xs); }
.eqs { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
.e { border-radius: var(--hm-r-md); padding: 6px; text-align: center; font-size: var(--hm-fs-xs); background: var(--hm-offline-soft); color: var(--hm-offline-ink); }
.e b { display: block; font-size: var(--hm-fs-sm); font-family: var(--hm-font-num); }
.s-running { background: var(--hm-run-soft); color: var(--hm-run-ink); } .s-idle { background: var(--hm-idle-soft); color: var(--hm-idle-ink); }
.s-down { background: var(--hm-fault-soft); color: var(--hm-fault-ink); } .s-setup { background: var(--hm-setup-soft); color: var(--hm-setup-ink); }
.al { font-size: var(--hm-fs-sm); padding: 3px 0; display: flex; align-items: center; gap: 6px; } .al em { color: var(--hm-text-3); font-style: normal; margin-left: auto; }
.al .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--hm-fault); flex: none; }
.wo { display: grid; grid-template-columns: 1fr 120px 70px; gap: 8px; align-items: center; font-size: var(--hm-fs-xs); margin: 5px 0; }
.wo em { color: var(--hm-text-3); font-style: normal; text-align: right; font-family: var(--hm-font-num); }
.pb { height: 8px; background: var(--hm-surface-3); border-radius: 4px; overflow: hidden; } .pb div { height: 100%; background: var(--hm-primary); }
@media (max-width: 1400px) { .kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (max-width: 1100px) { .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); } .body { grid-template-columns: minmax(0, 1fr); } .panel { grid-column: auto !important; } }
</style>
