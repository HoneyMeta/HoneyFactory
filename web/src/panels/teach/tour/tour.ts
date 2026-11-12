// 4.5 Guided tutorial engine: walk beginners through a lesson. Steps are data-driven (backend vfactory/teach/tours/<lesson>.json, GET /api/teach/tours/<lesson>),
// Each step: title, action, rationale, spotlight target, completion condition (live checks), hint after N seconds, and mistake detection. UI: TourOverlay.vue (mounted on body, allows interaction).
//
// Step format (see the end of docs/audit/4.5-novice-walkthrough.md):
//   { id, title, do, why, target, goto, done, hints: [{after, text}], wrong: [{when, msg}], manual?, delay? }
//   target: {sel: CSS} | {tour: name} → [data-tour=name] | {panel_btn: panel} → left vertical toolbar icon | {ld: {var, t?}} → ladder element | array = first visible target
//   goto ("Take me there"): {panel, select, console, plc_tab, teach_tab, enter}
//   Conditions for done / wrong.when:
//     {route:'workbench'} in this lesson's sandbox Workbench   {panel:'plc-editor-float'} panel/floating panel is open
//     {ld:{var,t}} element exists in the ladder diagram   {ld_par:[a,b]} a and b are on separate parallel branches   {ld_coil:'X'}   {st:'regex'}
//     {downloaded:true} editor program downloaded to PLC   {plc:'RUN'}   {pressed:'START'} pressed since this step began   {io_seq:{name,seq:[1,0]}} input goes 1 then 0
//     {io:{name,eq}} current output   {check:'key'} checklist item checked   {check_fail:'key'}   {checks_all:true}   {diag:'reason'} matching diagnostic appears
//     {submitted:true}   {answered:'q'}   {param:{block,key,ne|eq}}   {running:true}   {sim_s:600}   {goal:'key'} production line lesson goal reached
//     {all:[…]} {any:[…]} {not:…}
// 4.7 Guided tours (guides.ts, local definitions, no grading or /api/teach calls) also use this engine: tour.guide = true; steps are usually manual. Extra tour conditions:
//     {view:'plan'} current view   {added:'processor'} equipment of this type added since step start   {linked:true} connection added since step start   {sel_type:'plc'} selected equipment type
//     {selected:'process'} equipment in this layer selected   {seen: target} target is visible; {running:true} uses the Workbench's own run state in tours; {added, n} at least n units added
//   Tour goto also supports: {select:'$process'|'$plc'} (select the first matching unit only if the selection has another type), {click: CSS} (click a page tab)
import { $t, i18n, variants } from '../../../i18n';
import { createApp, reactive, watch } from 'vue';
import { get } from '../../../api';
import { ed, setRightOpen, typeOf } from '../../../editor/store';
import { useSession } from '../../../plc/session';
import { coachOf } from '../coach';
import { guideAt, guideDef, setGuideAt } from './guides';

const KEY = 'vf_tour';
export const tour = reactive<any>({
  on: false, def: null as any, key: '', aid: 0, pid: '', plc: 'PLC1', kind: 'cell', i: 0, stepAt: 0, stepSeq: 0, done: false, ok: false, okAt: 0,
  hint: '', wrong: '', finished: false, min: false, live: null as any, answers: {} as any, submitted: 0, err: '', taken: [] as number[],
  hold: false,   // UI testing: disable automatic step advancement and automatic "Take me there".
  guide: false,  // 4.7: Guided tours (locally defined, not tied to a lesson)
  snap: null as any,   // Tours: equipment and connection counts at step start (baseline for {added} and {linked})
});
let timer: any = null;
let coachRel: (() => void) | null = null;
let liveT = 0;

function save() {
  try {
    if (!tour.on) { sessionStorage.removeItem(KEY); return; }
    sessionStorage.setItem(KEY, JSON.stringify({ key: tour.key, aid: tour.aid, pid: tour.pid, plc: tour.plc, kind: tour.kind, i: tour.i, min: tour.min, stepAt: tour.stepAt,
      stepSeq: tour.stepSeq, submitted: tour.submitted, guide: tour.guide }));
  } catch { /* Private browsing mode */ }
}

export function hasActiveTour() { return tour.on; }

/** 4.7 Start a locally defined tour (no backend request). def: {title, steps, outro?}. */
export function startLocal(def: any, ctx: { key: string; pid?: string; plc?: string }, at = 0) {
  if (tour.on && !tour.guide) { clearTimeout(timer); coachRel?.(); coachRel = null; }
  Object.assign(tour, { on: true, guide: true, def, key: ctx.key, aid: 0, pid: ctx.pid || '', plc: ctx.plc || '', kind: 'guide', finished: false, min: false,
    submitted: 0, taken: [], live: null, answers: {} });
  ensureOverlay();
  go(at);
  loop();
}
/** Tour's "current PLC": selected PLC → selected equipment's PLC; if unavailable, use the model's first PLC. Return '' if none (PLC window uses the practice PLC). */
function guidePlc(): string {
  const bs: any[] = ed.model?.blocks || [];
  const isPlc = (id: string) => bs.some((b) => b.id === id && b.type === 'plc');
  if (ed.sel?.length === 1 && isPlc(ed.sel[0])) return ed.sel[0];
  if (tour.plc && isPlc(tour.plc)) return tour.plc;
  return bs.find((b) => b.type === 'plc')?.id || '';
}
function snapModel() {
  const counts: Record<string, number> = {};
  for (const b of ed.model?.blocks || []) counts[b.type] = (counts[b.type] || 0) + 1;
  return { counts, links: (ed.model?.links || []).length };
}

/** Start a lesson tutorial. ctx: {key: lesson ID (scenario ID or course/lesson), aid, pid: sandbox, plc: PLC block programmed by the student, kind}. */
export async function startTour(ctx: { key: string; aid: number; pid: string; plc?: string; kind?: string }, at = 0) {
  const def = await get(`/api/teach/tours/${encodeURIComponent(ctx.key)}`, true);
  Object.assign(tour, { on: true, guide: false, def, key: ctx.key, aid: ctx.aid, pid: ctx.pid, plc: ctx.plc || 'PLC1', kind: ctx.kind || def.kind || 'cell', finished: false, min: false,
    submitted: 0, taken: [] });
  ensureOverlay();
  go(at);
  loop();
}

export function stopTour() {
  tour.on = false; tour.def = null; tour.finished = false;
  clearTimeout(timer); timer = null;
  coachRel?.(); coachRel = null;
  save();
}

export function go(i: number) {
  const n = tour.def?.steps?.length || 0;
  if (i >= n) { tour.finished = true; tour.i = n; if (tour.guide) setGuideAt(tour.key, null); save(); return; }
  tour.i = Math.max(0, i); tour.finished = false;
  tour.stepAt = Date.now(); tour.ok = false; tour.okAt = 0; tour.hint = ''; tour.wrong = '';
  tour.stepSeq = tour.guide || !tour.pid ? 0 : coachOf(tour.pid).s.seq;
  tour.snap = tour.guide ? snapModel() : null;
  save();
  autoGoto(tour.i);
}
/** 4.6: If a step's click target is hidden, run "Take Me There" once (open panel, switch tab, scroll into view) so students need not find it.
 *  4.6.2: Run only once on step entry; if the student has already scrolled, open the panel and tab without scrolling.
 *  4.7: Run each tour step's goto on entry (switch view, open panel), whether the target is visible or not. */
function autoGoto(i: number) {
  setTimeout(async () => {
    const s = step();
    if (!tour.on || tour.hold || tour.i !== i || tour.finished || tour.min || !s?.target || (!(tour.guide && s.goto) && resolveTarget(s.target))) return;
    const auto = { auto: true, since: tour.stepAt };
    if (s.goto && !s.goto.enter) await goto(s.goto, s.target, auto); else revealTarget(s.target, auto);
  }, 700);
}
// 4.6.2 Track student scrolling (wheel, touch drag, page keys, scrollbar drag). Auto-scroll only before the student scrolls; never fight for scroll position.
let userScrollAt = 0;
const SCROLL_KEYS = new Set(['PageUp', 'PageDown', 'Home', 'End', 'ArrowUp', 'ArrowDown', ' ']);
const markScroll = () => { userScrollAt = Date.now(); };
window.addEventListener('wheel', markScroll, { capture: true, passive: true });
window.addEventListener('touchmove', markScroll, { capture: true, passive: true });
window.addEventListener('keydown', (e) => { if (SCROLL_KEYS.has(e.key)) markScroll(); }, { capture: true, passive: true });
window.addEventListener('pointerdown', (e) => {
  const el = e.target as HTMLElement | null;                 // Scrollbar press: the pointer is outside the element's content area
  if (el && el instanceof HTMLElement && (el.scrollHeight > el.clientHeight || el.scrollWidth > el.clientWidth)) {
    const r = el.getBoundingClientRect();
    if (e.clientX > r.left + el.clientLeft + el.clientWidth || e.clientY > r.top + el.clientTop + el.clientHeight) markScroll();
  }
}, { capture: true, passive: true });
export const userScrolledSince = (t: number) => userScrollAt > t;
export const next = () => go(tour.i + 1);
export const prev = () => go(tour.i - 1);
export function step() { return tour.def?.steps?.[tour.i] || null; }

// ---------------- Facts ----------------
function sess() {
  try { return useSession(ctxPid(), ctxPlc()); } catch { return null; }
}
function ldEls(): any[] {
  const p = sess()?.s.program;
  if (!p || p.lang !== 'LD') return [];
  const out: any[] = [];
  const walk = (x: any, br: any) => {
    if (Array.isArray(x)) x.forEach((y) => walk(y, br));
    else if (x?.par) x.par.forEach((b: any, i: number) => walk(b, { node: x, i }));
    else if (x?.ser) walk(x.ser, br);
    else if (x) out.push({ el: x, br });
  };
  for (const r of p.source?.rungs || []) walk(r.elements || [], null);
  return out;
}
const up = (s: any) => String(s || '').trim().toUpperCase();
function entriesSince() { return coachOf(tour.pid).s.entries.filter((e) => e.seq > tour.stepSeq); }

/** 4.7 Tour-specific conditions (no coach data); return undefined for non-tour conditions. */
function guideCond(c: any): boolean | undefined {
  if (c.view) return ed.view === c.view;
  if (c.seen) return !!resolveTarget(c.seen);
  if (c.added) { const now = snapModel(), was = tour.snap || { counts: {} }; return (now.counts[c.added] || 0) - (was.counts[c.added] || 0) >= (c.n || 1); }
  if (c.linked) return snapModel().links > (tour.snap?.links ?? Infinity);
  const one = ed.sel?.length === 1 ? (ed.model?.blocks || []).find((b: any) => b.id === ed.sel[0]) : null;
  if (c.sel_type) return !!one && one.type === c.sel_type;
  if (c.selected) return !!one && (typeOf(one).layer || 'process') === c.selected;
  if (c.running && tour.guide) return !!ed.runtime && !ed.replay && (ed.runtime.ctl?.mode || 'running') === 'running';
  return undefined;
}

export function cond(c: any): boolean {
  if (!c) return false;
  if (c.all) return c.all.every(cond);
  if (c.any) return c.any.some(cond);
  if (c.not) return !cond(c.not);
  const gc = guideCond(c);
  if (gc !== undefined) return gc;
  const co = coachOf(tour.pid).s;
  if (c.route) return location.pathname.includes(`/p/${encodeURIComponent(tour.pid)}/`) || location.pathname.includes(`/p/${tour.pid}/`);
  if (c.panel) return (ed.floats || []).some((w: any) => String(w.id).split(':')[0] === c.panel) || (ed.leftOpen && ed.leftPanel === c.panel);
  if (c.ld) return ldEls().some((o) => up(o.el.var) === up(c.ld.var) && (!c.ld.t || o.el.t === c.ld.t));
  if (c.ld_coil) return ldEls().some((o) => up(o.el.var) === up(c.ld_coil) && ['COIL', 'SET'].includes(o.el.t));
  if (c.ld_par) {
    const [a, b] = c.ld_par.map(up);
    const els = ldEls();
    return els.some((x) => x.br && up(x.el.var) === a && els.some((y) => y.br && y.br.node === x.br.node && y.br.i !== x.br.i && up(y.el.var) === b));
  }
  if (c.st) { const p = sess()?.s.program; return !!p && p.lang === 'ST' && new RegExp(c.st, 'i').test(String(p.source || '')); }
  if (c.downloaded) {
    const s = sess();
    if (s && s.s.loaded) return !s.dirty && !!s.s.onlineHash && s.s.onlineHash === s.s.projectHash;
    return co.entries.some((e) => e.k === 'plc' && (e.code === 'download' || variants('tour.downloadToPlc').some((t) => String(e.msg).startsWith(t))));
  }
  if (c.plc) return (co.state?.plc || sess()?.s.online?.state) === c.plc;
  if (c.pressed) return entriesSince().some((e) => e.k === 'act' && e.comp === c.pressed && (e.code === 'press' || /\u6309\u4e0b|\u62cd\u4e0b|press/i.test(e.msg)));
  if (c.io_seq) {
    const seq: any[] = c.io_seq.seq.map((v: any) => !!v);
    let k = 0;
    for (const e of entriesSince()) if (e.k === 'in' && e.name === c.io_seq.name && !!e.v === seq[k]) { k++; if (k >= seq.length) return true; }
    return false;
  }
  if (c.io) return (co.state?.on || []).includes(c.io.name) === !!c.io.eq;
  if (c.check) return (co.checklist?.items || []).some((i: any) => i.key === c.check && i.state === 'ok');
  if (c.check_fail) return (co.checklist?.items || []).some((i: any) => i.key === c.check_fail && i.state === 'fail');
  if (c.checks_all) return !!co.checklist?.all_ok || !!co.checklist?.auto_full;
  if (c.diag) return entriesSince().some((e) => e.k === 'diag' && (c.diag === true || e.cause === c.diag));
  if (c.submitted) return tour.submitted > tour.stepAt;
  if (c.answered) return tour.answers?.[c.answered] !== undefined && tour.answers?.[c.answered] !== null;
  if (c.param) {
    const b = (ed.model?.blocks || []).find((x: any) => x.id === c.param.block);
    const v = b?.params?.[c.param.key];
    if (v === undefined) return false;
    if ('ne' in c.param) return String(v) !== String(c.param.ne);
    return String(v) === String(c.param.eq);
  }
  if (c.running) return !!tour.live && tour.live.paused === false && (tour.live.sim_s || 0) > 0;
  if (c.sim_s) return (tour.live?.sim_s || 0) >= c.sim_s;
  if (c.goal) return (tour.live?.progress?.rules || []).some((r: any) => r.key === c.goal && r.ok);
  return false;
}

// ---------------- Targets ----------------
// 4.6: Spotlight only targets actually visible on screen; clipped by a scrollable parent, offscreen, or covered by another window counts as hidden (previously drew a circle over empty space).
//   Also supports {block: equipmentId}, resolved in the current view: card in Floor Plan / Flow / Architecture, projected equipment bounds in 3D. Used by the AI Tutor's "Look Here".
export type Hit = { el: Element | null; rect: DOMRect };
const CLIPS = /(auto|scroll|hidden|clip)/;
/** Visible portion of an element, excluding parent overflow clipping and offscreen areas; return null if fully hidden. */
export function shownRect(el: Element): DOMRect | null {
  const r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return null;
  let x0 = Math.max(0, r.left), y0 = Math.max(0, r.top), x1 = Math.min(innerWidth, r.right), y1 = Math.min(innerHeight, r.bottom);
  for (let p = el.parentElement; p && p !== document.body && p !== document.documentElement; p = p.parentElement) {
    const cs = getComputedStyle(p);
    if (cs.display === 'none' || cs.visibility === 'hidden') return null;
    if (CLIPS.test(cs.overflowX + ' ' + cs.overflowY)) {
      const q = p.getBoundingClientRect();
      x0 = Math.max(x0, q.left); y0 = Math.max(y0, q.top); x1 = Math.min(x1, q.right); y1 = Math.min(y1, q.bottom);
    }
    if (cs.position === 'fixed') break;            // Fixed-position windows (floating windows, sidebars) are not clipped by outer ancestors
  }
  if (x1 - x0 < 2 || y1 - y0 < 2) return null;
  return new DOMRect(x0, y0, x1 - x0, y1 - y0);
}
/** Check visibility: small elements must be mostly visible; large containers (task panel, right sidebar) only need a substantial visible area. */
function enough(full: DOMRect, s: DOMRect) {
  const fa = full.width * full.height, sa = s.width * s.height;
  return sa >= fa * 0.6 || (fa > 40000 && s.width >= 60 && s.height >= 30);
}
/** Check if the target is topmost at its center (ignore tutorial overlays and the bottom-right assistant, but not other floating windows). */
function onTop(el: Element, s: DOMRect) {
  const pts = [[s.x + s.width / 2, s.y + s.height / 2], [s.x + Math.min(8, s.width / 3), s.y + Math.min(8, s.height / 3)]];
  return pts.some(([x, y]) => {
    const top = document.elementsFromPoint(x, y).find((e) => !e.closest('#vf-tour-host, .aid-root'));
    return !!top && (el.contains(top) || top.contains(el));
  });
}
function vis(e: Element | null): Hit | null {
  if (!e || !e.getClientRects().length) return null;
  if (!(e instanceof SVGElement) && (e as HTMLElement).offsetParent === null && getComputedStyle(e).position !== 'fixed') return null;
  const s = shownRect(e);
  if (!s || !enough(e.getBoundingClientRect(), s) || !onTop(e, s)) return null;
  return { el: e, rect: s };
}
const esc = (s: string) => (window.CSS?.escape ? CSS.escape(s) : String(s).replace(/"/g, '\\"'));
/** All candidate elements for this target on the page, regardless of visibility. */
function candidates(t: any): Element[] {
  if (t.sel) return Array.from(document.querySelectorAll(t.sel));
  if (t.tour) return Array.from(document.querySelectorAll(`[data-tour="${t.tour}"]`));
  if (t.panel_btn) return Array.from(document.querySelectorAll(`.ed-act button[data-panel="${t.panel_btn}"]`));
  if (t.ld) {
    const o = ldEls().find((x) => up(x.el.var) === up(t.ld.var) && (!t.ld.t || x.el.t === t.ld.t));
    return o ? Array.from(document.querySelectorAll(`.lde g.el[data-id="${esc(o.el.id)}"]`)) : [];
  }
  if (t.block) {
    const id = esc(t.block);
    return Array.from(document.querySelectorAll(`.vue-flow__node[data-id="${id}"], .pv-svg [data-id="${id}"], .av-svg [data-id="${id}"]`));
  }
  return [];
}
/** Resolve the first visible target (arrays are searched in order). */
export function resolveTarget(t: any): Hit | null {
  if (!t) return null;
  if (Array.isArray(t)) { for (const x of t) { const h = resolveTarget(x); if (h) return h; } return null; }
  for (const e of candidates(t)) { const h = vis(e); if (h) return h; }
  if (t.block && (ed.view === '3d' || ed.split)) {           // No DOM in 3D: use screen-projected equipment bounding boxes (provided by View3D)
    const r: DOMRect | null = (window as any).__vf3dRect?.(t.block) || null;
    const host = document.querySelector('.scene-host');
    const hr = host ? shownRect(host) : null;
    if (r && hr) {
      const x0 = Math.max(r.left, hr.left), y0 = Math.max(r.top, hr.top), x1 = Math.min(r.right, hr.right), y1 = Math.min(r.bottom, hr.bottom);
      if (x1 - x0 > 6 && y1 - y0 > 6) return { el: null, rect: new DOMRect(x0, y0, x1 - x0, y1 - y0) };
    }
  }
  return null;
}
export function targetEl(t: any): HTMLElement | null { return (resolveTarget(t)?.el as HTMLElement) || null; }
/** Nearest scrollable ancestor (none = window). */
function scrollBox(el: Element): HTMLElement | null {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const cs = getComputedStyle(p);
    if (/(auto|scroll)/.test(cs.overflowY) && p.scrollHeight > p.clientHeight + 1) return p;
  }
  return null;
}
/** Tall targets (full question list or task panel) exceed 60% of their scroll area's height. Spotlight the visible portion without scrolling. */
function tall(el: Element) {
  const h = el.getBoundingClientRect().height, box = scrollBox(el);
  return h > (box ? box.clientHeight : innerHeight) * 0.6;
}
/** Target exists but is scrolled out of view: scroll it into view (task panel checklist, long ladder diagram).
 *  4.6.2: Call only on step entry (automatic, before the student scrolls) or "Take Me There", not on every refresh;
 *  Leave partially visible tall targets (question lists) in place; if fully hidden, reveal only the top (block: start), preserving the student's scroll position. */
export function revealTarget(t: any, opt: { auto?: boolean; since?: number } = {}): boolean {
  if (!t) return false;
  if (opt.auto && userScrolledSince(opt.since ?? 0)) return !!resolveTarget(t);
  const list = Array.isArray(t) ? t : [t];
  // In order: scroll earlier, more specific targets (e.g. the checklist's "Demo" button) into view if present; do not settle for a later visible target (the whole checklist)
  for (const x of list) {
    if (resolveTarget(x)) return true;
    for (const e of candidates(x)) {
      if (!e.getClientRects().length) continue;
      const big = tall(e);
      if (big && shownRect(e)) return true;                  // Tall container is partially visible: spotlight that portion without scrolling
      try { e.scrollIntoView({ block: big ? 'start' : 'center', inline: 'nearest' }); } catch { /* */ }
      if (resolveTarget(x) || (big && shownRect(e))) return true;
    }
  }
  return false;
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
export async function until(f: () => any, ms: number) { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (f()) return true; await sleep(80); } return !!f(); }
/** Check for candidate elements on the page, regardless of visibility. Used to wait for the page before opening the tour. */
export const hasCandidate = (t: any) => (Array.isArray(t) ? t : [t]).some((x) => !!x && candidates(x).length > 0);
/** Sandbox and PLC block for the current tutorial/pointer (use the pointer's own when no tutorial is open). Tour: selected PLC or first PLC in the model ('' if none). */
const ctxPid = () => (tour.on ? tour.pid : point.pid) || ed.pid;
const ctxPlc = () => (tour.on && tour.guide ? guidePlc() : (tour.on ? tour.plc : point.plc) || 'PLC1');
/** Tour {select:'$process'|'$plc'}: keep the current selection if its type matches; otherwise select the first match. */
function pickFor(kind: string): string {
  const bs: any[] = ed.model?.blocks || [];
  const match = (b: any) => (kind === 'plc' ? b.type === 'plc' : (typeOf(b).layer || 'process') === kind);
  const cur = ed.sel?.length === 1 ? bs.find((b) => b.id === ed.sel[0]) : null;
  if (cur && match(cur)) return '';
  return bs.find(match)?.id || '';
}

/** "Take Me There": open the step's panel and tab (containing the button), wait for it to appear, then scroll the target into view.
 *  opt.auto: automatic call on step entry (skip scrolling if the student has scrolled meanwhile); omit for "Take Me There" clicks to scroll normally. */
export async function goto(g: any, target?: any, opt: { auto?: boolean; since?: number } = {}) {
  if (!g) { if (target) revealTarget(target, opt); return; }
  if (g.enter) window.dispatchEvent(new CustomEvent('vf:teach-enter', { detail: { aid: tour.aid } }));
  if (g.view && ['3d', 'plan', 'graph', 'arch'].includes(g.view)) ed.view = g.view;
  if (g.click) (document.querySelector(g.click) as HTMLElement | null)?.click();   // Tour: switch to a page tab (e.g. "Teacher Console" on the teaching page)
  if (g.select) {
    const id = tour.on && tour.guide && /^\$(process|plc)$/.test(g.select) ? pickFor(g.select.slice(1)) : g.select === '$plc' ? ctxPlc() : g.select;
    if (id) {
      ed.sel = [id]; ed.selLink = '';
      if (g.focus !== false) { const { focusOn } = await import('../../../editor/store'); setTimeout(() => focusOn(id), 120); }
    }
  }
  if (g.right) { ed.rightTab = g.right; if (ed.rightOpen === false) setRightOpen(true); }   // 4.7: The right sidebar can collapse (ed.rightOpen); expand it before showing its contents
  if (g.panel) {
    if (g.panel === 'plc-editor-float' || g.panel === 'plc-editor') { const id = ctxPlc(); if (id) ed.sel = [id]; }
    // Tour: skip requests for already-open panels (reopening left panels is harmless; floating windows come to front). Avoid unnecessary disruption.
    const open = (ed.floats || []).some((w: any) => String(w.id).split(':')[0] === g.panel) || (ed.leftOpen && ed.leftPanel === g.panel);
    if (!(tour.on && tour.guide && open)) window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: g.panel } }));
  }
  if (g.console || g.console_tab) { const m = await import('../../cell/state'); m.openConsole(true); }
  if (g.plc_tab) {
    await until(() => document.querySelector('.pw'), 4000);
    window.dispatchEvent(new CustomEvent('vf:plc-tab', { detail: { pid: ctxPid(), tab: g.plc_tab } }));
  }
  if (g.console_tab) {
    await until(() => document.querySelector('.cco'), 3000);
    window.dispatchEvent(new CustomEvent('vf:console-tab', { detail: { tab: g.console_tab } }));
  }
  if (g.teach_tab) {
    if (!(ed.leftOpen && ed.leftPanel === 'teach-task')) window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'teach-task' } }));
    await until(() => document.querySelector('.task-panel .tp-tabs'), 6000);
    // A newly opened task panel may still be loading the lesson (then reset to "Task Brief"); verify the tab switch persists and retry if needed
    const on = () => !!document.querySelector(`.task-panel .el-tabs__item.is-active#tab-${g.teach_tab}`);
    for (let k = 0; k < 12 && !on(); k++) {
      window.dispatchEvent(new CustomEvent('vf:teach-tab', { detail: { tab: g.teach_tab } }));
      await sleep(350);
    }
  }
  if (target) {
    await until(() => candidates(Array.isArray(target) ? target[0] : target).length || resolveTarget(target), 2500);
    await sleep(250);                                   // Tab-switch and floating-window opening animations
    if (!revealTarget(target, opt)) { unblock(target); revealTarget(target, opt); }
  }
}
/** Target exists and is visible within its container but covered by a floating window (console, programming window): move the covering window aside. */
function unblock(t: any) {
  const list = Array.isArray(t) ? t : [t];
  for (const x of list) {
    for (const e of candidates(x)) {
      const s = shownRect(e);
      if (!s || e.closest('.fw')) continue;
      let moved = false;
      document.querySelectorAll<HTMLElement>('.fl-layer > .fw[data-float]').forEach((fe) => {
        const r = fe.getBoundingClientRect();
        if (r.right <= s.left || r.left >= s.right || r.bottom <= s.top || r.top >= s.bottom) return;
        const w = (ed.floats || []).find((f: any) => f.id === fe.dataset.float);
        if (!w || w.max) return;
        const box = (e.closest('.ed-left, .ed-right, .ed-bar') as HTMLElement | null)?.getBoundingClientRect() || s;
        if (box.right + 12 + w.w <= innerWidth) w.x = Math.round(box.right + 12);
        else if (box.left - 12 - w.w >= 48) w.x = Math.round(box.left - 12 - w.w);
        else { w.x = Math.round(box.right + 12); w.w = Math.max(320, innerWidth - w.x - 8); }
        moved = true;
      });
      if (moved) return;
    }
  }
}

// ---------------- Pointer (4.6): AI Tutor's "Look Here", a single-step tutorial using the same spotlight overlay ----------------
export const point = reactive<any>({ on: false, label: '', text: '', target: null as any, goto: null as any, pid: '', plc: '', at: 0, tried: false });
/** Spotlight a target: {label, text?, target, goto?}. Run "Take Me There" first (open panel, switch tab, select equipment), then spotlight; explain missing targets on the card. */
export async function pointAt(p: { label?: string; text?: string; target: any; goto?: any; pid?: string; plc?: string }) {
  Object.assign(point, { on: true, label: p.label || '', text: p.text || '', target: p.target, goto: p.goto || null, pid: p.pid || ed.pid, plc: p.plc || '', at: Date.now(), tried: false });
  ensureOverlay();
  await goto(p.goto, p.target);
  point.tried = true;
  return !!resolveTarget(p.target);
}
export function stopPoint() { point.on = false; point.target = null; }
(window as any).__vfTour = Object.assign((window as any).__vfTour || {}, { tour, point, go, goto, resolveTarget, pointAt, stopPoint, userScrolledSince, cond, guideAt, startLocal });   // For UI tests (tour guides / startGuide are added by guides.ts)

// ---------------- Loop ----------------
async function refreshLive() {
  if (tour.kind === 'cell' || !tour.aid || Date.now() - liveT < 1500) return;
  liveT = Date.now();
  try {
    tour.live = await get(`/api/teach/assignments/${tour.aid}/live`, true);
    const a = await get(`/api/teach/assignments/${tour.aid}/answers`, true);
    tour.answers = a.answers || {};
  } catch { /* */ }
}
function loop() {
  clearTimeout(timer);
  if (!coachRel && tour.pid && !tour.guide) coachRel = coachOf(tour.pid).use();   // Tours do not use coach data (no grading), so no polling
  const tick = async () => {
    if (!tour.on) return;
    await refreshLive();
    const s = step();
    if (s && !tour.finished) {
      const el = (Date.now() - tour.stepAt) / 1000;
      if (!tour.ok && s.done && cond(s.done)) { tour.ok = true; tour.okAt = Date.now(); tour.wrong = ''; }
      if (!tour.ok) {
        const w = (s.wrong || []).find((x: any) => (!x.after || el >= x.after) && cond(x.when));
        tour.wrong = w ? w.msg : '';
        const h = (s.hints || []).filter((x: any) => el >= (x.after || 0)).pop();
        tour.hint = h ? h.text : '';
      }
      if (tour.ok && !s.manual && !tour.hold && Date.now() - tour.okAt > (s.delay ?? 1400)) next();
    }
    timer = setTimeout(tick, 400);
  };
  tick();
}

// ---------------- Attach to body ----------------
let mounted = false;
export function ensureOverlay() {
  if (mounted) return;
  mounted = true;
  import('./TourOverlay.vue').then((m) => {
    const host = document.createElement('div');
    host.id = 'vf-tour-host';
    document.body.appendChild(host);
    createApp(m.default).use(i18n).mount(host);   // separate app: needs the i18n plugin for $t in templates
  });
}

window.addEventListener('vf:teach-submitted', () => { tour.submitted = Date.now(); save(); });
watch(() => [tour.min], save);

// Resume the last step on page refresh or when entering the Workbench from the teaching page
(function resume() {
  let st: any = null;
  try { st = JSON.parse(sessionStorage.getItem(KEY) || 'null'); } catch { /* */ }
  if (!st?.key) return;
  if (st.guide) {                                    // 4.7 Usage tours: defined locally (guides.ts), no backend requests
    const def = guideDef(st.key);
    if (!def) { try { sessionStorage.removeItem(KEY); } catch { /* */ } return; }
    Object.assign(tour, { on: true, guide: true, def, key: st.key, aid: 0, pid: st.pid || '', plc: st.plc || '', kind: 'guide', i: st.i || 0, min: !!st.min,
      stepAt: st.stepAt || Date.now(), stepSeq: 0, submitted: 0, finished: (st.i || 0) >= def.steps.length, snap: snapModel() });
    ensureOverlay();
    loop();
    return;
  }
  get(`/api/teach/tours/${encodeURIComponent(st.key)}`, true).then((def: any) => {
    Object.assign(tour, { on: true, def, key: st.key, aid: st.aid, pid: st.pid, plc: st.plc, kind: st.kind, i: st.i || 0, min: !!st.min, stepAt: st.stepAt || Date.now(),
      stepSeq: st.stepSeq || 0, submitted: st.submitted || 0, finished: (st.i || 0) >= (def.steps || []).length });
    ensureOverlay();
    loop();
  }).catch(() => { try { sessionStorage.removeItem(KEY); } catch { /* */ } });
})();
