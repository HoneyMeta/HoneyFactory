<template>
  <div class="tl">
    <div class="tl-h">
      <template v-if="ed.replay">
        <span class="tl-badge">{{ $t('common.replay') }}</span><b class="mono">{{ ed.replay.time }}</b>
        <el-button size="small" text @click="stepBy(-1)"><el-icon><ArrowLeft /></el-icon></el-button>
        <el-button size="small" text @click="stepBy(1)"><el-icon><ArrowRight /></el-icon></el-button>
        <el-button size="small" type="primary" @click="live">{{ $t('timeline.returnToLive') }}</el-button>
      </template>
      <template v-else><span class="muted small">{{ $t('timeline.dragOrClickTheTimeline') }}</span></template>
      <span class="grow" />
      <span v-for="(c, k) in TLC" :key="k" class="tl-lg"><i :style="{ background: c[1] }" />{{ c[0] }}</span>
    </div>
    <div class="tl-track" ref="track">
      <el-tooltip v-for="e in marks" :key="e.seq" :content="`${e.t.slice(5)} ${e.station} ${e.msg}`" placement="top" :show-after="150">
        <i class="tl-mk" :style="{ left: e.x * 100 + '%', background: (TLC[e.kind] || TLC.info)[1] }" @click="jump(e)" />
      </el-tooltip>
      <el-slider v-if="range" :model-value="cur" :min="range[0]" :max="range[1]" :step="60" :show-tooltip="false" @input="onScrub" @change="onScrub" />
    </div>
    <div class="tl-f muted small mono"><span>{{ idx.points[0]?.[1] }}</span><span class="grow" /><span>{{ $t('timeline.n0Now', [idx.points[idx.points.length - 1]?.[1]]) }}</span></div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { get, P } from '../api';
import { ed, select } from './store';

const TLC: Record<string, [string, string]> = { fault: [$t('common.fault'), '#dc2b2b'], alarm: [$t('common.alarm'), '#c25e12'], tool: [$t('common.toolChange'), '#1463d6'], scenario: [$t('common.scenario'), '#6d4fe0'],
  plan: [$t('common.plan'), '#0ba5c4'], inject: [$t('common.inject'), '#c7a12a'], repair: [$t('common.repair'), '#15a34a'], info: [$t('common.other'), '#94a3b8'] };
const idx = reactive<any>({ points: [] }), tl = ref<any>(null), track = ref<HTMLElement>();
const range = computed(() => (idx.points.length > 1 ? [idx.points[0][0], idx.points[idx.points.length - 1][0]] : null));
const cur = computed(() => ed.replay?.t ?? range.value?.[1] ?? 0);
const marks = computed(() => {
  if (!tl.value || !range.value || !ed.runtime) return [];
  const span = 24 * 3600, now = ed.runtime.t, [a, b] = range.value;
  return tl.value.events.map((e: any) => ({ ...e, ts: now - (1 - e.x) * span })).filter((e: any) => e.ts >= a && e.ts <= b)
    .map((e: any) => ({ ...e, x: (e.ts - a) / Math.max(1, b - a) }));
});
let timer: any = null, pend: any = null;
async function load() {
  Object.assign(idx, await get(P(ed.pid) + '/replay/index', true).catch(() => ({ points: [] })));
  tl.value = await get(P(ed.pid) + '/timeline?hours=24', true).catch(() => null);
}
async function goTo(t: number) {
  const s = await get(`${P(ed.pid)}/replay/at?t=${t}`, true).catch(() => null);
  if (s) ed.replay = { t: s.t ?? t, time: s.time, data: s };
}
function onScrub(v: any) {
  const t = Number(v);
  if (range.value && t >= range.value[1] - 30) { live(); return; }
  clearTimeout(pend); pend = setTimeout(() => goTo(t), 120);
}
function stepBy(n: number) { if (ed.replay && range.value) goTo(Math.max(range.value[0], Math.min(range.value[1], ed.replay.t + n * 60))); }
function jump(e: any) { goTo(e.ts); if (e.station) select([e.station]); }
function live() { ed.replay = null; }
/** Jump to the nearest snapshot for a timestamp string (YYYY-MM-DD HH:MM). */
async function goToTime(str: string) {
  if (!idx.points.length) await load();
  const p = idx.points.find((x: any) => x[1] >= str) || idx.points[idx.points.length - 1];
  if (p) goTo(p[0]);
}
/** Click a chart time (HH:MM) → jump to the nearest snapshot. */
function onReplayTo(e: any) {
  const label = String(e.detail?.label || ''); if (!label) return;
  const hit = [...idx.points].reverse().find((x: any) => x[1].slice(11, 16) === label.slice(-5));
  if (hit) goTo(hit[0]);
}
onMounted(() => { load(); timer = setInterval(load, 15000); addEventListener('vf:replay-to', onReplayTo); });
onUnmounted(() => { clearInterval(timer); removeEventListener('vf:replay-to', onReplayTo); });
defineExpose({ goTo, goToTime, load, stepBy });
</script>
