<template>
  <div v-if="(tour.on && tour.def) || point.on" class="vt-root" data-k="tour-overlay" :data-guide="tour.on && tour.guide ? tour.key : ''" :data-step="tour.i" :data-step-id="point.on ? 'point' : cur?.id || 'end'"
       :data-ok="tour.ok ? 1 : 0" :data-found="rect ? 1 : 0">
    <!-- Spotlight: highlight the target and dim the rest; the overlay passes mouse events through -->
    <div v-if="rect && showSpot" class="vt-spot" :class="{ ok: !point.on && tour.ok }" :style="spotStyle" data-k="tour-spot" />
    <div v-if="rect && showSpot && arrow" class="vt-arrow" :style="arrow.style">{{ arrow.ch }}</div>

    <!-- 4.6 Pointing (AI Tutor's "Look here"): a single-step tutorial with a smaller card -->
    <div v-if="point.on" ref="card" class="vt-card" :style="cardStyle" data-k="point-card">
      <div class="vt-top" :title="$t('tourOverlay.holdHereToDragThe')" @pointerdown="startDrag">
        <span class="vt-n">{{ $t('tourOverlay.lookHere') }}</span><span class="vt-t">{{ $t('common.aiTutor') }}</span>
        <button class="vt-x" :title="$t('common.close')" data-k="point-close" @click="stopPoint()">×</button>
      </div>
      <div class="vt-body">
        <h4 data-k="point-title">{{ point.label || $t('tourOverlay.here') }}</h4>
        <div v-if="point.text" class="vt-do" v-html="rich(point.text)" />
        <div v-if="!rect && point.tried" class="vt-miss" data-k="point-miss">{{ point.goto ? $t('tourOverlay.couldNotFindTheTarget') : $t('tourOverlay.theTargetIsNotCurrently') }}</div>
      </div>
      <div class="vt-btns">
        <button v-if="point.goto" class="vt-b" data-k="point-goto" @click="regoto">{{ $t('tourOverlay.takeMeThere') }}</button>
        <span class="grow" />
        <button class="vt-b pri" data-k="point-ok" @click="stopPoint()">{{ $t('common.gotIt') }}</button>
      </div>
    </div>

    <!-- Show only a compact bar when collapsed -->
    <template v-else-if="tour.on && tour.def">
      <button v-if="tour.min" class="vt-pill" data-k="tour-pill" @click="tour.min = false">{{ tour.guide ? $t('tourOverlay.tour') : $t('tourOverlay.tutorial') }} {{ Math.min(tour.i + 1, n) }}/{{ n }} · {{ cur?.title || $t('common.done') }}</button>
      <div v-else ref="card" class="vt-card" :style="cardStyle" data-k="tour-card">
        <div class="vt-prog"><i :style="{ width: Math.round((Math.min(tour.i + (tour.ok ? 1 : 0), n) / n) * 100) + '%' }" /></div>
        <div class="vt-top" :title="$t('tourOverlay.holdHereToDragThe')" @pointerdown="startDrag">
          <span class="vt-n">{{ tour.finished ? $t('common.done') : $t('tourOverlay.step01', [tour.i + 1, n]) }}</span>
          <span class="vt-t">{{ tour.def.title }}</span>
          <button class="vt-x" :title="tour.guide ? $t('tourOverlay.collapseTheTourStaysExpand') : $t('tourOverlay.collapseReopenTheTutorialAnytime')" data-k="tour-min" @click="tour.min = true">—</button>
        </div>
        <template v-if="tour.finished">
          <div class="vt-body">
            <h4>{{ tour.guide ? $t('tourOverlay.tourComplete') : $t('tourOverlay.tutorialComplete') }}</h4>
            <p class="vt-do">{{ tour.def.outro || $t('tourOverlay.youVeCompletedEveryStep') }}</p>
          </div>
          <div class="vt-btns"><span class="grow" /><button class="vt-b pri" data-k="tour-close" @click="stopTour()">{{ tour.guide ? $t('common.close') : $t('tourOverlay.closeTutorial') }}</button></div>
        </template>
        <template v-else-if="cur">
          <!-- Scrollable body (expanded "Why" can be long); keep the title and buttons visible -->
          <div ref="body" class="vt-body" data-k="tour-body">
            <h4 data-k="tour-title">{{ cur.title }}</h4>
            <div class="vt-do" data-k="tour-do"><b v-if="!tour.guide">{{ $t('tourOverlay.whatToDo') }}</b><span v-html="rich(cur.do)" /></div>
            <details v-if="cur.why" class="vt-why" :open="whyOpen" @toggle="onWhy"><summary>{{ tour.guide ? $t('tourOverlay.learnMore') : $t('tourOverlay.whyDoThis') }}</summary><div v-html="rich(cur.why)" /></details>
            <div v-if="tour.ok" class="vt-ok" data-k="tour-ok">{{ $t('tourOverlay.done0', [cur.manual ? '' : $t('tourOverlay.movingToTheNextStep')]) }}</div>
            <div v-else-if="tour.wrong" class="vt-wrong" data-k="tour-wrong">⚠ {{ tour.wrong }}</div>
            <div v-else-if="diagMsg" class="vt-wrong" data-k="tour-diag">{{ $t('tourOverlay.systemDiagnostics0', [diagMsg]) }}</div>
            <div v-if="!tour.ok && tour.hint" class="vt-hint" data-k="tour-hint">{{ $t('tourOverlay.tip0', [tour.hint]) }}</div>
          </div>
          <!-- Target is not visible: show instructions instead of an empty ring -->
          <div v-if="!rect && cur.target && !tour.ok" class="vt-miss" data-k="tour-miss">{{ cur.goto ? $t('tourOverlay.theClickTargetIsnT') : $t('tourOverlay.theClickTargetIsnT2') }}</div>
          <div class="vt-btns">
            <button v-if="cur.goto" class="vt-b" :class="{ hot: !rect && cur.target && !tour.ok }" data-k="tour-goto" @click="goto(cur.goto, cur.target)">{{ $t('tourOverlay.takeMeThere') }}</button>
            <button v-if="fixable" class="vt-b warn" data-k="tour-fix" :title="$t('tourOverlay.collapseTheTutorialOpenThe')" @click="fix">{{ $t('tourOverlay.editProgram') }}</button>
            <span class="grow" />
            <button class="vt-b" :disabled="!tour.i" data-k="tour-prev" @click="prev()">{{ $t('common.back') }}</button>
            <button class="vt-b" :title="$t('tourOverlay.skipThisStepNoCheck')" data-k="tour-skip" @click="next()">{{ $t('common.skip') }}</button>
            <button v-if="!cur.done || tour.ok" class="vt-b pri" data-k="tour-next" @click="next()">{{ tour.i < n - 1 ? $t('common.next') : $t('common.done') }}</button>
            <button class="vt-b q" :title="tour.guide ? $t('tourOverlay.exitTheTourClickOr') : $t('tourOverlay.exitTheTutorialYouCan')" data-k="tour-exit" @click="exitTour">{{ $t('common.exit') }}</button>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../../i18n';
// Guided tutorial UI: target spotlight + arrow + step card (Previous / Skip / Exit / progress). Reposition every frame as the target window moves; pointer-events: none on the overlay, with only the card clickable.
// 4.6: Limit card height to the viewport and scroll the body; reposition when "Why" expands or content grows to keep the entire card on screen.
//      Spotlight only visible targets (resolveTarget); otherwise prompt "Click 'Take Me There'" on the card. The AI Tutor's "Look here" (point) uses this overlay too.
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { coachOf } from '../coach';
import { setGuideAt } from './guides';
import { goto, next, point, prev, resolveTarget, stopPoint, stopTour, tour } from './tour';

const card = ref<HTMLElement | null>(null);
const body = ref<HTMLElement | null>(null);
const rect = ref<DOMRect | null>(null);
const area = ref<DOMRect | null>(null);
const whyOpen = ref(false);
const n = computed(() => tour.def?.steps?.length || 1);
const cur = computed<any>(() => tour.def?.steps?.[tour.i] || null);
const showSpot = computed(() => (point.on ? true : !tour.min && !tour.finished));
const diagMsg = computed(() => {
  const d = tour.guide ? null : coachOf(tour.pid).s.diag;
  return d && d.seq > tour.stepSeq && cur.value?.show_diag !== false ? d.msg : '';
});
watch(() => tour.i, () => { whyOpen.value = !!cur.value?.why_open; });
const target = () => (point.on ? point.target : cur.value && !tour.finished ? cur.value.target : null);
let raf = 0;
function frame() {
  const t = target();
  const hit = t ? resolveTarget(t) : null;
  const r = hit ? hit.rect : null;
  // Place the card outside the target's entire window/panel to avoid covering nearby buttons, e.g. "Stop" beside "Start"
  const box = hit?.el ? (hit.el.closest('.fw, .ed-left, .ed-right, .ed-bar, .ed-act') as HTMLElement | null) : null;
  const br = box ? box.getBoundingClientRect() : r;
  const ob = area.value;
  if (!br) area.value = null;
  else if (!ob || Math.abs(ob.x - br.x) > 0.5 || Math.abs(ob.y - br.y) > 0.5 || Math.abs(ob.width - br.width) > 0.5 || Math.abs(ob.height - br.height) > 0.5) area.value = br;
  const o = rect.value;
  if (!r || r.width === 0) { if (o) rect.value = null; }
  else if (!o || Math.abs(o.x - r.x) > 0.5 || Math.abs(o.y - r.y) > 0.5 || Math.abs(o.width - r.width) > 0.5 || Math.abs(o.height - r.height) > 0.5) rect.value = r;
  // Reposition when card height changes (expanded "Why" or new hints)
  const h = card.value?.offsetHeight || 0;
  if (h && Math.abs(h - ch.value) > 1) ch.value = h;
  vw.value = innerWidth; vh.value = innerHeight;
  raf = requestAnimationFrame(frame);
}
raf = requestAnimationFrame(frame);
onBeforeUnmount(() => cancelAnimationFrame(raf));
const ch = ref(260), vw = ref(innerWidth), vh = ref(innerHeight);
const PAD = 6;
const spotStyle = computed(() => {
  const r = rect.value!;
  return { left: r.x - PAD + 'px', top: r.y - PAD + 'px', width: r.width + PAD * 2 + 'px', height: r.height + PAD * 2 + 'px' };
});
const CW = 360, M = 10;
/** Place the card beside the target (right → left → below → above), falling back to the bottom-left corner. */
const place = computed(() => {
  const t = rect.value, W = vw.value, H = vh.value, hh = Math.min(ch.value, H - 2 * M);
  if (!t) return { x: 16, y: H - hh - 16, side: '' };
  const a = area.value;
  // If the target's window fills most of the screen, avoid only the target itself
  const r = a && a.width * a.height < W * H * 0.55 && (a.right + 24 + CW < W || a.left - 24 - CW > 0) ? a : t;
  const cy = Math.min(Math.max(70, t.y + t.height / 2 - hh / 2), H - hh - M);
  if (r.right + 24 + CW < W) return { x: r.right + 24, y: cy, side: 'right' };
  if (r.left - 24 - CW > 0) return { x: r.left - 24 - CW, y: cy, side: 'left' };
  const cx = Math.min(Math.max(M, r.x + r.width / 2 - CW / 2), W - CW - M);
  if (r.bottom + 24 + hh < H) return { x: cx, y: r.bottom + 24, side: 'below' };
  if (r.top - 24 - hh > 0) return { x: cx, y: r.top - 24 - hh, side: 'above' };
  // If no side fits, find a corner clear of the target and its window; otherwise choose the least overlap
  const hit = (x: number, y: number, b: DOMRect) => Math.max(0, Math.min(x + CW, b.right + 8) - Math.max(x, b.left - 8)) * Math.max(0, Math.min(y + hh, b.bottom + 8) - Math.max(y, b.top - 8));
  const corners = [[16, H - hh - 16], [W - CW - 16, H - hh - 16], [W - CW - 16, 70], [16, 70]];
  let best = corners[0], bestCost = Infinity;
  for (const [x, y] of corners) {
    const cost = hit(x, y, t) * 100 + (a ? hit(x, y, a) : 0);
    if (cost < bestCost) { bestCost = cost; best = [x, y]; }
  }
  return { x: best[0], y: best[1], side: '' };
});
/** Drag the title row to uncover the target (for this step only; auto-position again on the next step). */
const moved = ref<{ x: number; y: number } | null>(null);
watch(() => [tour.i, point.at], () => { moved.value = null; });
function startDrag(e: PointerEvent) {
  if ((e.target as HTMLElement).closest('button')) return;
  const sx = e.clientX, sy = e.clientY, ox = moved.value?.x ?? place.value.x, oy = moved.value?.y ?? place.value.y;
  const mv = (ev: PointerEvent) => { moved.value = { x: Math.max(0, Math.min(innerWidth - 80, ox + ev.clientX - sx)), y: Math.max(0, Math.min(innerHeight - 40, oy + ev.clientY - sy)) }; };
  const upf = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', upf); };
  addEventListener('pointermove', mv); addEventListener('pointerup', upf);
}
/** Clamp the card to the viewport; move a dragged card up if expanding "Why" makes it taller. */
const cardStyle = computed(() => {
  const H = vh.value, W = vw.value, hh = Math.min(ch.value, H - 2 * M);
  const x = Math.max(M, Math.min(W - CW - M, moved.value?.x ?? place.value.x));
  const y = Math.max(M, Math.min(H - hh - M, moved.value?.y ?? place.value.y));
  return { left: x + 'px', top: y + 'px', width: CW + 'px', maxHeight: H - 2 * M + 'px' };
});
const arrow = computed(() => {
  const r = rect.value, p = place.value;
  if (!r || !p.side || moved.value) return null;
  if ((p.side === 'right' && p.x < r.right) || (p.side === 'left' && p.x + CW > r.left)) return null;
  const mid = r.y + r.height / 2, cx = r.x + r.width / 2;
  if (p.side === 'right') return { ch: '◀', style: { left: r.right + 4 + 'px', top: mid - 10 + 'px' } };
  if (p.side === 'left') return { ch: '▶', style: { left: r.left - 22 + 'px', top: mid - 10 + 'px' } };
  if (p.side === 'below') return { ch: '▲', style: { left: cx - 8 + 'px', top: r.bottom + 4 + 'px' } };
  return { ch: '▼', style: { left: cx - 8 + 'px', top: r.top - 22 + 'px' } };
});
/** Expand "Why": after the card grows (repositioned next frame), scroll the expanded content into view in the body. */
function onWhy(e: Event) {
  const d = e.target as HTMLDetailsElement;
  whyOpen.value = d.open;
  if (d.open) nextTick(() => requestAnimationFrame(() => requestAnimationFrame(() => d.scrollIntoView({ block: 'nearest' }))));
}
/** Step text supports **bold** and `code`. */
function rich(t: string) {
  const esc = String(t || '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string));
  return esc.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`(.+?)`/g, '<code>$1</code>').replace(/\n/g, '<br>');
}
async function regoto() { point.tried = false; await goto(point.goto, point.target); point.tried = true; }
/** If this step reports a diagnostic (button has no effect), offer "Edit Program": collapse the card, open the PLC editor, and jump to the red-highlighted rung. */
const lastDiag = computed(() => { const d = tour.guide ? null : coachOf(tour.pid).s.diag; return d && d.seq > tour.stepSeq && (d.rung !== undefined || d.line) ? d : null; });
const fixable = computed(() => !tour.ok && !!lastDiag.value);
async function fix() {
  const d = lastDiag.value; if (!d) return;
  tour.min = true;
  await goto({ panel: 'plc-editor-float', plc_tab: 'prog' });
  setTimeout(() => window.dispatchEvent(new CustomEvent('vf:plc-goto', { detail: { pid: tour.pid, plc: d.plc, rung: d.rung, line: d.line, elems: d.elems } })), 600);
}
function exitTour() {
  // 4.7 Guided tours: save the current step and offer "Resume from Step N / Start Over" next time
  if (tour.guide) {
    if (!confirm($t('tourOverlay.exitThisGuidedTourYou'))) return;
    setGuideAt(tour.key, tour.i);
    stopTour();
    return;
  }
  if (confirm($t('tourOverlay.exitTheGuidedTutorialYou'))) stopTour();
}
</script>

<style scoped>
.vt-root { position: fixed; inset: 0; z-index: 3000; pointer-events: none; font-size: 13px;
  --vt-bg: var(--hm-surface); --vt-tx: var(--hm-text); --vt-mu: var(--hm-text-2); --vt-ln: var(--hm-border); --vt-acc: var(--hm-primary); --vt-acc2: var(--hm-primary-hover); --vt-ok: var(--hm-run-ink); --vt-bad: var(--hm-fault-ink); --vt-hint: var(--hm-idle-soft); --vt-why: var(--hm-surface-2); --vt-hov: var(--hm-primary-soft); }
.vt-spot { position: fixed; border-radius: 8px; border: 2px solid var(--vt-acc); box-shadow: 0 0 0 9999px rgba(15, 23, 42, .26), 0 0 14px 2px var(--vt-acc);
  transition: left .15s, top .15s, width .15s, height .15s; animation: vt-pulse 1.6s ease-in-out infinite; }
.vt-spot.ok { border-color: var(--vt-ok); box-shadow: 0 0 0 9999px rgba(15, 23, 42, .18), 0 0 14px 2px var(--vt-ok); }
@keyframes vt-pulse { 50% { box-shadow: 0 0 0 9999px rgba(15, 23, 42, .26), 0 0 22px 6px var(--vt-acc); } }
.vt-arrow { position: fixed; color: var(--vt-acc); font-size: 18px; line-height: 20px; text-shadow: 0 0 4px rgba(0, 0, 0, .25); animation: vt-bob 1s ease-in-out infinite; }
@keyframes vt-bob { 50% { transform: scale(1.25); } }
/* Card: three stacked sections (progress + title / scrollable body / buttons), capped at viewport height */
.vt-card { position: fixed; pointer-events: auto; background: var(--vt-bg); color: var(--vt-tx); border: 1px solid var(--vt-ln); border-radius: var(--hm-r-lg); display: flex; flex-direction: column;
  box-shadow: var(--hm-e3); padding: 0 14px 12px; box-sizing: border-box; transition: left .2s, top .2s; overflow: hidden; }
.vt-prog { height: 4px; margin: 0 -14px 8px; background: var(--vt-ln); border-radius: 10px 10px 0 0; overflow: hidden; flex: none; }
.vt-prog i { display: block; height: 100%; background: var(--vt-acc); transition: width .3s; }
.vt-top { display: flex; align-items: center; gap: 8px; font-size: 11.5px; color: var(--vt-mu); cursor: move; user-select: none; flex: none; }
[data-k="point-card"] .vt-top { padding-top: 8px; }
.vt-body { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; margin: 0 -6px; padding: 0 6px; }
.vt-n { font-weight: 600; color: var(--vt-acc); }
.vt-t { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vt-x { border: 0; background: none; color: var(--vt-mu); cursor: pointer; font-size: 14px; padding: 0 4px; }
.vt-x:hover { color: var(--vt-tx); }
h4 { margin: 6px 0 6px; font-size: 15px; }
.vt-do { line-height: 1.7; }
.vt-do :deep(code), .vt-why :deep(code) { background: var(--vt-why); padding: 0 4px; border-radius: 3px; font-family: var(--hm-font-mono); font-size: 12px; }
.vt-why { margin-top: 6px; background: var(--vt-why); border-radius: 6px; padding: 4px 8px; line-height: 1.65; color: var(--vt-mu); font-size: 12.5px; }
.vt-why summary { cursor: pointer; color: var(--vt-acc); font-size: 12px; }
.vt-ok { margin-top: 8px; color: var(--vt-ok); font-weight: 600; }
.vt-wrong { margin-top: 8px; color: var(--vt-bad); line-height: 1.6; font-size: 12.5px; }
.vt-hint { margin-top: 6px; background: var(--vt-hint); border-radius: 6px; padding: 4px 8px; line-height: 1.6; font-size: 12.5px; }
.vt-miss { margin-top: 8px; font-size: 12.5px; color: var(--vt-tx); background: var(--vt-hint); border-radius: 6px; padding: 4px 8px; flex: none; }
.vt-btns { display: flex; align-items: center; gap: 6px; margin-top: 10px; flex-wrap: wrap; flex: none; }
.vt-b { border: 1px solid var(--vt-ln); background: var(--vt-bg); color: var(--vt-tx); border-radius: 5px; height: 26px; padding: 0 10px; cursor: pointer; font-size: 12.5px; }
/* Hover: regular buttons get a light background and primary-color text; primary buttons only darken their background and keep white text (previously text turned blue and disappeared against the background) */
.vt-b:hover:not(:disabled) { border-color: var(--vt-acc); color: var(--vt-acc); background: var(--vt-hov); }
.vt-b:disabled { opacity: .45; cursor: default; }
.vt-b.pri, .vt-b.pri:hover:not(:disabled) { background: var(--vt-acc); border-color: var(--vt-acc); color: #fff; }
.vt-b.pri:hover:not(:disabled) { background: var(--vt-acc2); border-color: var(--vt-acc2); }
.vt-b.hot { border-color: var(--vt-acc); color: var(--vt-acc); font-weight: 600; animation: vt-hot 1.4s ease-in-out infinite; }
@keyframes vt-hot { 50% { box-shadow: 0 0 0 3px rgba(20, 99, 214, .25); } }
.vt-b.q { color: var(--vt-mu); }
.vt-b.warn, .vt-b.warn:hover:not(:disabled) { border-color: var(--vt-bad); color: var(--vt-bad); }
.vt-pill { position: fixed; left: 16px; bottom: 16px; pointer-events: auto; border: 1px solid var(--vt-acc); background: var(--vt-bg); color: var(--vt-acc); border-radius: 16px;
  padding: 5px 12px; cursor: pointer; box-shadow: var(--hm-e2); font-size: 12.5px; }
.vt-pill:hover { background: var(--vt-hov); }
.grow { flex: 1; }
</style>
