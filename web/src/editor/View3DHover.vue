<template>
  <div v-show="visible && info" ref="card" class="v3-hc" :data-id="hit?.id || ''">
    <template v-if="info">
      <div class="hc-h">
        <b class="hc-n">{{ info.name }}</b>
        <span class="hc-l" :style="{ background: info.layer.color }" :title="info.layer.label">{{ info.layer.short }}</span>
      </div>
      <div class="hc-t">{{ info.type }}</div>
      <div class="hc-s"><i class="hc-dot" :style="{ background: info.color }" /><b>{{ info.state }}</b><span v-if="info.sub" class="hc-sub">· {{ info.sub }}</span></div>
      <div v-if="info.alarm" class="hc-al">⚠ {{ info.alarm }}</div>
      <div v-if="info.figs.length" class="hc-k">
        <div v-for="f in info.figs" :key="f[0]"><small>{{ f[0] }}</small><b :class="f[2] || ''">{{ f[1] }}</b></div>
      </div>
      <div v-if="info.bar !== null" class="hc-bar"><i :style="{ width: Math.round(info.bar * 100) + '%', background: barColor(info.bar, info.barHigh) }" /></div>
      <div v-if="info.plc" class="hc-plc">{{ $t('view3DHover.controlledBy0', [info.plc]) }}</div>
      <div class="hc-hint">{{ info.hint }}</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
// 3D hover card (4.4): name, type, layer, status, one or two key metrics, and action hints. Appears after 150 ms and follows the pointer; hides during dragging/scrolling.
// Set position via style directly (non-reactive) so mouse movement does not re-render the 3D view.
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { layerOf, relationsOf } from './shell/relations';
import { blocksById, ed, rtById, STATE_CN, STATE_COLOR, typeOf } from './store';

const props = defineProps<{ hit: any; busy: boolean; suppress: string }>();
const card = ref<HTMLElement>();
const show = ref(false);
let tm: any = null;
watch(() => props.hit, (h) => {
  clearTimeout(tm);
  if (!h) { show.value = false; return; }
  if (show.value) return;                        // Already visible: switch to another object immediately, without delay.
  tm = setTimeout(() => { show.value = true; nextPos(); }, 150);
});
const visible = computed(() => show.value && !!props.hit && !props.busy && props.suppress !== props.hit.id);

const AGV_CN: Record<string, string> = { Idle: $t('common.idle2'), Moving: $t('view3DHover.traveling'), Charging: $t('view3DHover.charging'), Blocked: $t('view3DHover.blocked'), Loading: $t('view3DHover.loadingUnloading'), Unloading: $t('view3DHover.loadingUnloading'), ToCharger: $t('view3DHover.headingToCharger') };
const AGV_COLOR: Record<string, string> = { Idle: 'var(--hm-idle)', Moving: 'var(--hm-run)', Charging: 'var(--hm-primary)', Blocked: 'var(--hm-fault)' };
const WK_CN: Record<string, string> = { idle: $t('common.idle2'), walk: $t('dockLists.walking'), carry: $t('common.transport'), work: $t('common.working'), break: $t('view3DHover.resting') };
const WK_COLOR: Record<string, string> = { idle: 'var(--hm-idle)', walk: 'var(--hm-primary)', carry: 'var(--hm-primary)', work: 'var(--hm-run)', break: '#7d7aa8' };
/** Progress bar colors: higher fill warns for occupancy (buffers, furnace charge); lower fill warns for battery and sand levels (barHigh). */
const barColor = (v: number, high: boolean) => (high ? (v < 0.25 ? 'var(--hm-fault)' : v < 0.5 ? 'var(--hm-idle)' : 'var(--hm-run)') : (v > 0.9 ? 'var(--hm-fault)' : v > 0.7 ? 'var(--hm-idle)' : 'var(--hm-run)'));
const pct = (v: number) => `${Math.round(v * 100)}%`;
const nm = (id: string) => blocksById.value[id]?.name || id;

const info = computed(() => {
  const h = props.hit; if (!h) return null;
  const b = blocksById.value[h.id], st: any = rtById.value[h.id] || {};
  const t = typeOf(b), lay = layerOf(h.id), L0 = ed.cat?.layers?.[lay] || { label: lay, color: 'var(--hm-offline)' };
  const L = { ...L0, short: String(L0.label || lay).split(/\s*[\uff08(]/)[0] };      // Show only "Control" and "Communication" on the card; use tooltips for full names.
  const out = {
    name: b?.name || st.name || h.id, type: `${t.label || b?.type || st.kind || ''} · ${h.id}`, layer: L,
    state: STATE_CN[st.state] || st.state || '—', color: STATE_COLOR[st.state] || 'var(--hm-offline)', sub: '' as string, alarm: st.alarm || '',
    figs: [] as [string, string, string?][], bar: null as number | null, barHigh: false, plc: '', hint: $t('view3DHover.clickToSelectDoubleClick'),
  };
  const kind = st.kind || b?.type;
  const rel = b ? relationsOf(h.id) : null;
  if (h.agv) {                                   // Single AGV
    const a = (st.agvs || []).find((x: any) => x.id === h.agv) || {};
    Object.assign(out, { name: h.agv, type: `AGV · ${b?.name || h.id}`, state: AGV_CN[a.state] || a.state || '—', color: AGV_COLOR[a.state] || 'var(--hm-offline)' });
    if (a.soc !== undefined) { out.figs.push([$t('view3DHover.energy'), `${a.soc}%`, a.soc <= 25 ? 'bad' : '']); out.bar = a.soc / 100; out.barHigh = true; }
    out.figs.push([$t('view3DHover.loaded'), a.load ? $t('view3DHover.n0Pcs', [a.load]) : $t('view3DHover.empty')]);
    out.hint = $t('view3DHover.clickToSelectFleetDouble');
    return out;
  }
  if (h.worker) {                                // Single worker
    const w = (st.workers || []).find((x: any) => x.id === h.worker) || {};
    Object.assign(out, { name: w.role || h.worker, type: `${h.worker} · ${b?.name || $t('common.teams')}`, state: WK_CN[w.state] || w.state || '—', color: WK_COLOR[w.state] || 'var(--hm-offline)' });
    if (w.serving) out.sub = $t('view3DHover.at') + nm(w.serving);
    out.hint = $t('view3DHover.clickToSelectTeamDouble');
    return out;
  }
  out.sub = st.phase || st.step || '';
  if (st.enabled === false) { out.state = $t('common.disabled2'); out.color = 'var(--hm-offline)'; }
  const oee = st.oee?.OEE;
  if (kind === 'furnace') {
    if (st.temp !== undefined) out.figs.push([$t('view3DHover.temperature'), `${Math.round(st.temp)} °C`]);
    if (st.fill !== undefined) { out.figs.push([$t('view3DHover.chargeMaterial'), pct(st.fill)]); out.bar = st.fill; }
  } else if (kind === 'buffer') {
    const n = st.count ?? 0, cap = st.cap || b?.params?.cap || 0;
    out.figs.push([$t('view3DHover.inStock'), cap ? `${n} / ${cap}` : String(n)]);
    if (cap) { out.figs.push([$t('view3DHover.occupied'), pct(n / cap)]); out.bar = Math.min(1, n / cap); }
  } else if (kind === 'plc') {
    const p = st.plc || {}, s = p.state || (st.state === 'Executing' ? 'RUN' : 'STOP');
    out.figs.push([$t('common.program'), s, s === 'RUN' ? 'ok' : s === 'HALT' ? 'bad' : 'mu']);
    out.figs.push([$t('view3DHover.controlledEquipment'), $t('view3DHover.n0Units', [(p.devices || rel?.devices || []).length])]);
    if (p.halt) out.alarm = out.alarm || String(p.halt.reason || p.halt.msg || p.halt);
    out.hint = $t('view3DHover.clickToSelectDoubleClick2');
  } else if (['gateway', 'switch', 'mes', 'scada', 'hmi'].includes(kind)) {
    if (st.online !== undefined) { out.state = st.online ? $t('common.online') : $t('common.offline'); out.color = st.online ? 'var(--hm-run)' : 'var(--hm-fault)'; }
    out.figs.push([$t('common.connection'), $t('common.n02', [st.clients ?? rel?.network.length ?? 0])]);
    if (kind === 'hmi' && rel?.plcs.length) out.figs.push(['PLC', nm(rel.plcs[0])]);
    out.hint = $t('view3DHover.clickToSelectDoubleClick3');
  } else if (kind === 'sand') {
    if (st.level !== undefined) { out.figs.push([$t('view3DHover.sandLevel'), `${Math.round(st.level)}%`]); out.bar = st.level / 100; out.barHigh = true; }
    if (st.moist !== undefined) out.figs.push([$t('view3DHover.moisture'), `${(+st.moist).toFixed(1)}%`]);
  } else if (kind === 'cell') {
    let ok = 0, bad = 0;
    for (const c of Object.values(st.cell?.comps || {}) as any[]) { ok += c.ok || 0; bad += c.bad || 0; }
    out.figs.push([$t('common.good'), String(ok)]); if (bad || ok) out.figs.push([$t('view3DHover.ng'), String(bad), bad ? 'bad' : '']);
  } else {
    if (oee !== undefined) out.figs.push(['OEE', pct(oee), oee < 0.5 ? 'warn' : '']);
    const n = st.count ?? st.molds ?? st.stock;
    if (typeof n === 'number') out.figs.push([st.count !== undefined ? $t('view3DHover.parts') : st.molds !== undefined ? $t('view3DHover.molded') : $t('common.stock'), String(n)]);
    else if (st.last) out.figs.push([$t('view3DHover.previousPart'), st.last, st.last === 'OK' ? 'ok' : 'bad']);
    if (out.figs.length < 2 && st.power) out.figs.push([$t('common.power2'), `${+(+st.power).toFixed(1)} kW`]);
  }
  if (rel?.plcs.length && kind !== 'plc') out.plc = rel.plcs.map(nm).join($t('common.k360'));
  if (lay !== 'process' && kind !== 'plc' && kind !== 'cell') out.hint = $t('view3DHover.clickToSelectDoubleClick3');
  if (['agv', 'crew'].includes(kind)) out.hint = $t('view3DHover.clickToSelectDoubleClick3');
  return out;
});

// ---------- Position: follow the mouse; flip sides near the right or bottom edge ----------
let mx = 0, my = 0, raf = 0;
function nextPos() {
  if (raf) return;
  raf = requestAnimationFrame(() => {
    raf = 0;
    const el = card.value, box = el?.parentElement; if (!el || !box) return;
    const r = box.getBoundingClientRect(), w = el.offsetWidth || 240, h = el.offsetHeight || 140;
    let x = mx - r.left + 18, y = my - r.top + 20;
    if (x + w > r.width - 8) x = mx - r.left - w - 14;
    if (y + h > r.height - 8) y = my - r.top - h - 12;
    el.style.transform = `translate(${Math.max(4, Math.round(x))}px, ${Math.max(4, Math.round(y))}px)`;
  });
}
const onMove = (e: PointerEvent) => { mx = e.clientX; my = e.clientY; if (show.value) nextPos(); };
onMounted(() => card.value?.parentElement?.addEventListener('pointermove', onMove));
onUnmounted(() => { clearTimeout(tm); cancelAnimationFrame(raf); card.value?.parentElement?.removeEventListener('pointermove', onMove); });
</script>

<style>
.v3-hc { position: absolute; left: 0; top: 0; z-index: 7; width: 236px; pointer-events: none; padding: 9px 11px 8px; border-radius: var(--hm-r-md);
  background: var(--hm-glass-strong); backdrop-filter: var(--hm-glass-blur); color: var(--tx); border: 1px solid var(--hm-border); box-shadow: var(--hm-e3); font-size: 12px; line-height: 1.45; }
.v3-hc .hc-h { display: flex; align-items: flex-start; gap: 8px; }
.v3-hc .hc-n { flex: 1; min-width: 0; font-size: 13.5px; font-weight: 700; line-height: 1.35; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; word-break: break-all; }
.v3-hc .hc-l { flex: none; color: #fff; font-size: 10.5px; line-height: 17px; padding: 0 7px; border-radius: 9px; margin-top: 1px; }
.v3-hc .hc-t { color: var(--mu); font-size: 11px; margin-top: 1px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.v3-hc .hc-s { display: flex; align-items: center; gap: 6px; margin-top: 6px; white-space: nowrap; overflow: hidden; }
.v3-hc .hc-s b { font-weight: 600; } .v3-hc .hc-sub { color: var(--mu); overflow: hidden; text-overflow: ellipsis; }
.v3-hc .hc-dot { flex: none; width: 9px; height: 9px; border-radius: 50%; box-shadow: 0 0 0 2px rgba(15, 32, 60, .08); }
.v3-hc .hc-al { margin-top: 4px; color: var(--bad); font-weight: 600; }
.v3-hc .hc-k { display: flex; gap: 14px; margin-top: 7px; padding-top: 6px; border-top: 1px solid var(--ln); }
.v3-hc .hc-k div { display: grid; min-width: 0; } .v3-hc .hc-k small { color: var(--mu); font-size: 10.5px; }
.v3-hc .hc-k b { font: 600 14px/1.25 var(--hm-font-num); font-variant-numeric: tabular-nums; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.v3-hc .hc-k b.ok { color: var(--ok); } .v3-hc .hc-k b.bad { color: var(--bad); } .v3-hc .hc-k b.warn { color: var(--warn); } .v3-hc .hc-k b.mu { color: var(--mu); }
.v3-hc .hc-bar { height: 4px; border-radius: 2px; background: var(--bg3); margin-top: 6px; overflow: hidden; } .v3-hc .hc-bar i { display: block; height: 100%; border-radius: 2px; }
.v3-hc .hc-plc { margin-top: 5px; font-size: 11px; color: var(--mu); }
.v3-hc .hc-hint { margin-top: 7px; padding-top: 5px; border-top: 1px dashed var(--ln); font-size: 10.5px; color: var(--mu); letter-spacing: .2px; }
</style>
