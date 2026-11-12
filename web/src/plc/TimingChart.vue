<template>
  <!-- I/O timing chart (logic analyzer): waveforms for each I/O over the last N seconds; click to place a cursor and inspect values, Shift+click to place a second cursor and measure the time difference; supports replay;
       overlay "expected timing" for control units from lab scenarios (button press times and expected output values in automated scenario tests). -->
  <div class="tc" data-timing>
    <div class="tc-bar">
      <b>{{ $t('plcWorkbench.timingChart') }}</b>
      <el-radio-group v-model="win" size="small">
        <el-radio-button v-for="w in [5, 10, 30, 60]" :key="w" :value="w">{{ $t('mesBar.n0S', [w]) }}</el-radio-button>
      </el-radio-group>
      <button class="plc-btn" :class="{ pri: !live }" data-act="tc-pause" :title="live ? $t('timingChart.freezeTheDisplayRecordingContinues') : $t('timeline.returnToLive')" @click="toggleLive">
        <el-icon><component :is="live ? 'VideoPause' : 'VideoPlay'" /></el-icon>{{ live ? $t('common.held') : $t('common.live') }}</button>
      <button class="plc-btn" data-act="tc-replay" :title="$t('timingChart.replayFromLeftToRight')" @click="replay"><el-icon><RefreshRight /></el-icon>{{ playing ? $t('signals.stopReplay') : $t('common.replay') }}</button>
      <template v-if="spec?.scene">
        <i class="plc-sep" />
        <el-checkbox v-model="showSpec" size="small" data-act="tc-spec">{{ $t('timingChart.overlayExpectedTiming0', [spec.name]) }}</el-checkbox>
        <span v-if="showSpec && verdict" class="plc-chip" :class="verdict.bad ? 'ERROR' : 'RUN'">{{ verdict.text }}<i /></span>
      </template>
      <span class="grow" />
      <span v-if="cur.a !== null" class="mono small">A {{ rel(cur.a) }}<template v-if="cur.b !== null"> · B {{ rel(cur.b) }} · Δt = {{ ((cur.b - cur.a) / 1000).toFixed(3) }} s</template></span>
      <button v-if="cur.a !== null" class="plc-btn" @click="cur.a = cur.b = null">{{ $t('timingChart.clearCursor') }}</button>
    </div>
    <div class="tc-sig">
      <span class="muted small">{{ $t('timingChart.signals') }}</span>
      <button v-for="s in sigs" :key="s.name" class="chip" :class="[{ on: shown.has(s.name) }, s.dir]" :title="s.comment" @click="toggleSig(s.name)">{{ s.name }}</button>
    </div>
    <div ref="host" class="tc-body" @mousedown="onDown">
      <div v-if="!data.events.length" class="muted pad">{{ $t('timingChart.noRecordingsYetOnceThe') }}</div>
      <svg v-else :width="W" :height="H" class="tc-svg">
        <!-- Time scale -->
        <g v-for="t in ticks" :key="'t' + t">
          <line :x1="x(t)" :x2="x(t)" y1="0" :y2="H - 18" class="grid" />
          <text :x="x(t)" :y="H - 4" text-anchor="middle" class="tick">{{ rel(t) }}</text>
        </g>
        <g v-for="(s, i) in lanes" :key="s.name" :transform="`translate(0, ${laneY(i)})`">
          <rect x="0" y="0" :width="W" :height="laneH(s)" :class="['lane', i % 2 ? 'odd' : '']" />
          <text x="8" :y="laneH(s) / 2 + 4" class="tc-lbl" :class="s.dir">{{ s.name }}</text>
          <text :x="LW - 8" :y="laneH(s) / 2 + 4" text-anchor="end" class="tc-val" :class="{ on: valAt(s, cur.a ?? data.now_ms) === true }">{{ fmt(s, valAt(s, cur.a ?? data.now_ms)) }}</text>
          <!-- Expected -->
          <template v-if="showSpec">
            <rect v-for="(p, k) in specPress(s.name)" :key="'p' + k" :x="x(p.t0)" :y="2" :width="Math.max(2, x(p.t1) - x(p.t0))" :height="laneH(s) - 4" class="spec-press">
              <title>{{ $t('timingChart.expectedPress1At0', [p.t, s.name]) }}</title>
            </rect>
            <rect v-for="(c, k) in specCheck(s.name)" :key="'c' + k" :x="x(c.t0)" :y="1" :width="Math.max(3, x(c.t1) - x(c.t0))" :height="laneH(s) - 2"
              :class="['spec-check', c.ok === true ? 'ok' : c.ok === false ? 'bad' : '']">
              <title>{{ $t('timingChart.expected123From', [c.t, s.name, c.eq ? 1 : 0, c.desc ? $t('timingChart.ifNotMet') + c.desc + $t('common.k460') : '', c.ok === true ? $t('timingChart.match') : c.ok === false ? $t('timingChart.mismatch') : $t('timingChart.noRecords')]) }}</title>
            </rect>
          </template>
          <path :d="wave(s)" :class="['wave', s.dir, isBool(s) ? 'b' : 'n']" />
        </g>
        <line v-if="cur.a !== null" :x1="x(cur.a)" :x2="x(cur.a)" y1="0" :y2="H - 18" class="cur a" />
        <line v-if="cur.b !== null" :x1="x(cur.b)" :x2="x(cur.b)" y1="0" :y2="H - 18" class="cur b" />
        <rect :x="LW" y="0" width="1" :height="H - 18" class="sep" />
      </svg>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { get } from '../api';
import { C } from './plcApi';
import type { Sess } from './session';

const props = defineProps<{ sess: Sess }>();
const S = props.sess.s;
const LW = 170;
const win = ref(10);
const live = ref(true);
const playing = ref(false);
const host = ref<HTMLElement>();
const W = ref(900);
const data = reactive<any>({ signals: [], names: [], events: [], now_ms: 0, start_ms: 0 });
const cur = reactive<{ a: number | null; b: number | null }>({ a: null, b: null });
const shown = ref(new Set<string>());
const spec = ref<any>(null);
const showSpec = ref(false);
let timer: any = null, raf = 0, ro: ResizeObserver | null = null;

const sigs = computed(() => data.signals as any[]);
const lanes = computed(() => sigs.value.filter((s: any) => shown.value.has(s.name)));
const isBool = (s: any) => (s.type || 'BOOL') === 'BOOL';
const laneH = (s: any) => (isBool(s) ? 30 : 46);
const laneY = (i: number) => lanes.value.slice(0, i).reduce((a: number, s: any) => a + laneH(s), 0);
const H = computed(() => lanes.value.reduce((a: number, s: any) => a + laneH(s), 0) + 22);
const t0 = computed(() => data.now_ms - win.value * 1000);
const x = (t: number) => LW + ((t - t0.value) / (win.value * 1000)) * (W.value - LW - 10);
const tOf = (px: number) => t0.value + ((px - LW) / (W.value - LW - 10)) * win.value * 1000;
const rel = (t: number) => { const d = (t - data.now_ms) / 1000; return d === 0 ? $t('common.current') : `${d.toFixed(win.value <= 10 ? 1 : 0)} s`; };
const ticks = computed(() => {
  const step = win.value <= 5 ? 1000 : win.value <= 10 ? 2000 : win.value <= 30 ? 5000 : 10000;
  const out: number[] = [];
  for (let t = data.now_ms; t >= t0.value; t -= step) out.push(t);
  return out;
});
const idx = computed(() => new Map(data.names.map((n: string, i: number) => [n, i])));

function valAt(s: any, t: number) {
  const i = idx.value.get(s.name) as number;
  let v: any = null;
  for (const [et, vals] of data.events) { if (et > t) break; v = vals[i]; }
  return v;
}
function fmt(s: any, v: any) { if (v === null || v === undefined) return '—'; if (typeof v === 'boolean') return v ? '1' : '0'; return String(Math.round(Number(v) * 100) / 100); }
function wave(s: any) {
  const i = idx.value.get(s.name) as number;
  const h = laneH(s);
  const ev = data.events;
  if (!ev.length) return '';
  if (isBool(s)) {
    const yv = (v: any) => (v ? 5 : h - 5);
    let d = '', last: any = null;
    for (const [t, vals] of ev) {
      const v = !!vals[i];
      const xx = Math.max(LW, x(t));
      if (last === null) d += `M${xx},${yv(v)}`;
      else if (v !== last) d += `H${xx}V${yv(v)}`;
      last = v;
    }
    return d + `H${x(data.now_ms)}`;
  }
  let lo = Infinity, hi = -Infinity;
  for (const [, vals] of ev) { const v = Number(vals[i] || 0); lo = Math.min(lo, v); hi = Math.max(hi, v); }
  if (hi === lo) { hi += 1; lo -= 1; }
  const yv = (v: any) => h - 5 - ((Number(v || 0) - lo) / (hi - lo)) * (h - 10);
  let d = '', last: any = null;
  for (const [t, vals] of ev) {
    const v = Number(vals[i] || 0), xx = Math.max(LW, x(t));
    d += last === null ? `M${xx},${yv(v)}` : `H${xx}V${yv(v)}`;
    last = v;
  }
  return d + `H${x(data.now_ms)}`;
}

async function load() {
  if (!S.pid) return;
  try {
    const r = await get(`${C(S.pid, S.bid)}/trace?seconds=${Math.max(win.value, 60)}`, true);
    Object.assign(data, r);
    if (!shown.value.size && r.signals?.length) shown.value = new Set(r.signals.filter((s: any) => isBool(s)).map((s: any) => s.name));
  } catch { /* Retry next time */ }
}
function schedule() { clearTimeout(timer); timer = setTimeout(async () => { if (live.value && !document.hidden) await load(); schedule(); }, 300); }
function toggleLive() { live.value = !live.value; if (live.value) { cur.a = cur.b = null; stopPlay(); } }
function toggleSig(n: string) { const s = new Set(shown.value); if (s.has(n)) s.delete(n); else s.add(n); shown.value = s; }
function onDown(e: MouseEvent) {
  const r = host.value!.getBoundingClientRect();
  const px = e.clientX - r.left + host.value!.scrollLeft;
  if (px < LW || !data.events.length) return;
  const t = Math.min(data.now_ms, Math.max(t0.value, tOf(px)));
  live.value = false;
  if (e.shiftKey && cur.a !== null) cur.b = t; else { cur.a = t; cur.b = null; }
}
function stopPlay() { playing.value = false; cancelAnimationFrame(raf); }
function replay() {
  if (playing.value) { stopPlay(); return; }
  live.value = false; playing.value = true;
  const start = performance.now(), from = t0.value, span = win.value * 1000;
  const step = () => {
    if (!playing.value) return;
    const k = (performance.now() - start) / span;
    if (k >= 1) { cur.a = data.now_ms; stopPlay(); return; }
    cur.a = from + k * span;
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
}

// ---- Expected timing: align to the first press of the first button in the scenario test
const origin = computed(() => {
  const sp = spec.value;
  if (!sp?.presses?.length) return null;
  const first = sp.presses[0];
  const i = idx.value.get(first.sig) as number;
  if (i === undefined) return null;
  const sig = sigs.value.find((s: any) => s.name === first.sig);
  const active = sig?.contact === 'NC' ? false : true;
  let prev: any = null;
  for (const [t, vals] of data.events) {
    const v = !!vals[i];
    if (prev !== null && v === active && prev !== active) return t - first.t * 1000;
    prev = v;
  }
  return null;
});
function specPress(n: string) {
  const o = origin.value; const sp = spec.value;
  if (o === null || !sp) return [];
  return sp.presses.filter((p: any) => p.sig === n).map((p: any) => ({ ...p, t0: Math.max(t0.value, o + p.t * 1000), t1: o + (p.t + p.hold) * 1000 }))
    .filter((p: any) => p.t1 >= t0.value);
}
function specCheck(n: string) {
  const o = origin.value; const sp = spec.value;
  if (o === null || !sp) return [];
  const s = sigs.value.find((x: any) => x.name === n);
  return sp.checks.filter((c: any) => c.sig === n).map((c: any) => {
    const a = o + c.t * 1000, b = o + (c.t + Math.max(c.hold, 0.15)) * 1000;
    let ok: boolean | null = null;
    if (s && b <= data.now_ms && a >= (data.events[0]?.[0] ?? Infinity)) {
      ok = true;
      for (let t = a; t <= b; t += 20) if (!!valAt(s, t) !== !!c.eq) { ok = false; break; }
    }
    return { ...c, t0: Math.max(t0.value, a), t1: b, ok };
  }).filter((c: any) => c.t1 >= t0.value);
}
const verdict = computed(() => {
  if (!spec.value || origin.value === null) return spec.value ? { text: $t('timingChart.waitingForTheFirstButton'), bad: false } : null;
  let n = 0, good = 0;
  for (const s of sigs.value) for (const c of specCheck(s.name)) if (c.ok !== null) { n++; if (c.ok) good++; }
  return n ? { text: $t('timingChart.expectedTimingChecks01', [good, n]), bad: good < n } : { text: $t('timingChart.alignedWaitingForTheCheck'), bad: false };
});

onMounted(async () => {
  await load();
  schedule();
  ro = new ResizeObserver(() => { if (host.value) W.value = Math.max(500, host.value.clientWidth - 4); });
  if (host.value) { ro.observe(host.value); W.value = Math.max(500, host.value.clientWidth - 4); }
  try { spec.value = await get(`${C(S.pid, S.bid)}/timing_spec`, true); } catch { spec.value = null; }
});
onBeforeUnmount(() => { clearTimeout(timer); stopPlay(); ro?.disconnect(); });
watch(win, () => load());
</script>

<style scoped>
.tc { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ld-card); color: var(--ld-tx); }
.tc-bar { display: flex; align-items: center; gap: 8px; padding: 6px 10px; border-bottom: 1px solid var(--ld-ln); flex-wrap: wrap; }
.tc-sig { display: flex; gap: 4px; flex-wrap: wrap; align-items: center; padding: 5px 10px; border-bottom: 1px solid var(--ld-ln); }
.chip { height: 22px; padding: 0 8px; border-radius: 11px; border: 1px solid var(--ld-ln); background: var(--ld-bg); color: var(--ld-mu); cursor: pointer; font: 11.5px Consolas, monospace; }
.chip.on.in { background: var(--ld-in-bg); color: var(--ld-tx); border-color: var(--ld-in); }
.chip.on.out { background: var(--ld-pow-bg); color: var(--ld-tx); border-color: var(--ld-pow); }
.tc-body { flex: 1; min-height: 0; overflow: auto; cursor: crosshair; user-select: none; }
.tc-svg { display: block; }
.lane { fill: transparent; } .lane.odd { fill: var(--ld-bg); }
.grid { stroke: var(--ld-ln); stroke-width: 1; }
.sep { fill: var(--ld-ln2); }
.tick { fill: var(--ld-mu); font: 10.5px Consolas, monospace; }
.tc-lbl { font: 600 12px Consolas, monospace; fill: var(--ld-tx); } .tc-lbl.in { fill: var(--ld-in); } .tc-lbl.out { fill: var(--ld-pow); }
.tc-val { font: 600 12px Consolas, monospace; fill: var(--ld-mu); } .tc-val.on { fill: var(--ld-pow); }
.wave { fill: none; stroke-width: 1.8; }
.wave.in { stroke: var(--ld-in); } .wave.out { stroke: var(--ld-pow); } .wave.n { stroke: var(--ld-acc); }
.cur { stroke-width: 1.5; } .cur.a { stroke: var(--ld-halt); } .cur.b { stroke: var(--ld-sel); stroke-dasharray: 4 3; }
.spec-press { fill: none; stroke: var(--ld-mu); stroke-dasharray: 3 2; }
.spec-check { fill: var(--ld-bar); opacity: .8; } .spec-check.ok { fill: var(--ld-pow-bg); } .spec-check.bad { fill: var(--ld-bad-bg); stroke: var(--ld-bad); }
.small { font-size: 11.5px; } .pad { padding: 16px; } .grow { flex: 1; } .muted { color: var(--ld-mu); }
</style>
