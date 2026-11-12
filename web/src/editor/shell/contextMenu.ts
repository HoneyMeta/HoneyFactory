// Shared context menu for all three views (Graph / Floor Plan / 3D). Views only select the object, calculate the click position, and call openBlockMenu / openLinkMenu / openPaneMenu,
// passing view-specific editing actions (e.g. "Move into Group" in Graph) via extra. Actions are grouped into "Edit / Run & Debug / Analysis & Integration Testing".
import { $t } from '../../i18n';
import { markRaw, reactive } from 'vue';
import { canEdit } from '../../api';
import { askAssistant } from '../../assistant';
import { blocksById, copySel, duplicateSel, ed, focusOn, openFloat, paste, removeSelected, typeOf } from '../store';
import {
  addBp, bpsOf, injectFault, isWatched, loadStation, numericTags, promptBp, removeBp, stationInfo, tagBp, toggleBp, toggleWatch,
} from './graphdebug';

export type MenuItem = { label: string; kbd?: string; danger?: boolean; disabled?: boolean; checked?: boolean; hint?: string; children?: MenuItem[] | (() => MenuItem[]); run?: () => any };
export type MenuGroup = { title?: string; items: MenuItem[] };
export const ctx = reactive<{ show: boolean; x: number; y: number; groups: MenuGroup[] }>({ show: false, x: 0, y: 0, groups: [] });
/** Active temporary tool (4.6): views register a cancel handler when measuring distance (keyed by '3d' / 'plan'); right-clicking that view shows "Cancel Measurement" first. */
export const ctxTools = reactive<{ measure: Record<string, (() => void) | null> }>({ measure: {} });
const VIEW_ROOT: Record<string, string> = { '3d': '.v3', plan: '.pv' };

// 4.6: suppress menus on right-drag (3D orbit/pan, Floor Plan and Graph pan); movement over 5 pixels between press and release counts as a drag.
// Track during window capture so neither 3D OrbitControls nor Floor Plan mousedown handlers can block it; supports menus triggered on release (Windows) or press.
const DRAG_PX = 5;
let rdown: { x: number; y: number; max: number } | null = null;
addEventListener('pointerdown', (e) => { if (e.button === 2) rdown = { x: e.clientX, y: e.clientY, max: 0 }; }, true);
addEventListener('pointermove', (e) => {
  if (!rdown || !(e.buttons & 2)) return;
  rdown.max = Math.max(rdown.max, Math.hypot(e.clientX - rdown.x, e.clientY - rdown.y));
  if (rdown.max > DRAG_PX && ctx.show) ctx.show = false;          // Systems that open menus on press: dismiss as soon as dragging starts
}, true);
/** Whether this right-click was a drag (orbit / pan). */
export function wasRightDrag(e?: MouseEvent) {
  if (!rdown) return false;
  const d = e ? Math.hypot(e.clientX - rdown.x, e.clientY - rdown.y) : 0;
  return Math.max(rdown.max, d) > DRAG_PX;
}

export function openCtx(e: MouseEvent, groups: MenuGroup[]) {
  e.preventDefault(); e.stopPropagation();
  if (wasRightDrag(e)) { rdown = null; return; }
  rdown = null;
  const tgt = e.target as Element | null;
  const mv = Object.keys(ctxTools.measure).find((v) => ctxTools.measure[v] && tgt?.closest?.(VIEW_ROOT[v]));
  const cancel = mv ? ctxTools.measure[mv] : null;
  const lead: MenuGroup[] = cancel ? [{ items: [{ label: $t('contextMenu.cancelMeasurement'), kbd: 'Esc', run: () => cancel() }] }] : [];
  Object.assign(ctx, { show: true, x: e.clientX, y: e.clientY, groups: [...lead, ...groups].filter((g) => g.items.length) });
}
export function closeCtx() { ctx.show = false; }

const VIEW_CN: Record<string, string> = { '3d': $t('workbench.n3d'), plan: $t('planView.floorPlan'), graph: $t('contextMenu.graph') };
function locate(id: string, view: string): MenuItem {
  return { label: $t('contextMenu.locate'), children: Object.keys(VIEW_CN).filter((v) => v !== view).map((v) => ({ label: VIEW_CN[v], run: () => { ed.view = v; setTimeout(() => focusOn(id), 300); } })) };
}
const STATE_BP: [string, string][] = [['Stopped', $t('contextMenu.downtimeFailure')], ['Blocked', $t('common.blocked')], ['Starved', $t('common.materialShortage')], ['Setup', $t('common.changeover')], ['Idle', $t('common.idle')]];

/** Equipment (block) context menu. extra: view-specific editing actions. */
export function openBlockMenu(e: MouseEvent, id: string, view: string, extra: MenuItem[] = []) {
  const b = blocksById.value[id]; if (!b) return;
  const edit = canEdit(), multi = ed.sel.length > 1, rt = ed.runtime?.stations?.find((s: any) => s.id === id);
  if (!stationInfo[id] || Date.now() - stationInfo[id].at > 5000) loadStation(id);
  const isBuf = b.type === 'buffer';
  const bpItems = (): MenuItem[] => {
    const have = bpsOf(id);
    const add: MenuItem[] = isBuf
      ? [{ label: $t('contextMenu.partCountReachesCapacity0', [b.params?.capacity ?? '?']), run: () => addBp({ kind: 'buffer', id, op: '>=', value: b.params?.capacity || 10 }) },
        { label: $t('contextMenu.partCountReaches'), run: () => promptBp('buffer', id) }, { label: $t('contextMenu.partCountIs0Empty'), run: () => addBp({ kind: 'buffer', id, op: '<=', value: 0 }) }]
      : [...STATE_BP.map(([s, n]) => ({ label: $t('contextMenu.enter0', [n]), kbd: s === 'Stopped' ? 'F9' : undefined, run: () => addBp({ kind: 'state', id, state: s }) })),
        { label: $t('contextMenu.downtimeExceedsMin'), run: () => promptBp('state_for', id) }, { label: $t('breakpoints.alarmOccurs'), run: () => addBp({ kind: 'alarm', id }) },
        { label: $t('contextMenu.tagValueExceeds'), children: () => numericTags(id).slice(0, 24).map((t) => ({ label: t, run: () => tagBp(id, t) })) }];
    return [...add, ...have.flatMap((x: any) => [
      { label: $t('common.n01', [x.enabled ? $t('contextMenu.disable') : $t('common.enable'), x.name || x.desc]), run: () => toggleBp(x) },
      { label: $t('contextMenu.delete0', [x.name || x.desc]), danger: true, run: () => removeBp(x) }])];
  };
  const faults = (): MenuItem[] => {
    const f = stationInfo[id]?.faults || {};
    const l: MenuItem[] = Object.entries(f).map(([k, v]) => ({ label: String(v), run: () => injectFault(id, k) }));
    return [...(l.length ? l : [{ label: stationInfo[id] ? $t('contextMenu.noFaultsCanBeInjected') : $t('common.loading'), disabled: true }]), { label: $t('common.clearFailure'), run: () => injectFault(id, 'clear') }];
  };
  const watch = (): MenuItem[] => {
    const tags = numericTags(id);
    if (!tags.length) return [{ label: stationInfo[id] ? $t('contextMenu.noNumericTags') : $t('common.loading'), disabled: true }];
    return tags.slice(0, 30).map((t) => ({ label: t, checked: isWatched(id, t), run: () => toggleWatch(id, t) }));
  };
  const trend = (): MenuItem[] => numericTags(id).slice(0, 30).map((t) => ({ label: t, run: () => openTrend(id, t) }));
  const name = multi ? $t('contextMenu.these0Machines', [ed.sel.length]) : $t('contextMenu.n0', [b.name]);
  openCtx(e, [
    { title: multi ? $t('contextMenu.selected0', [ed.sel.length]) : `${b.name} · ${typeOf(b).label}`, items: [
      ...(edit ? extra : []),
      ...(edit ? [{ label: $t('common.duplicate'), kbd: 'Ctrl+D', run: duplicateSel }, { label: $t('common.copy'), kbd: 'Ctrl+C', run: copySel }] : []),
      ...(multi ? [] : [locate(id, view)]),
      ...(edit ? [{ label: $t('common.delete'), kbd: 'Del', danger: true, run: removeSelected }] : []),
    ] },
    { title: $t('contextMenu.runDebug'), items: multi ? [] : [
      { label: $t('common.breakpoint'), hint: bpsOf(id).length ? $t('common.n02', [bpsOf(id).length]) : '', children: bpItems },
      { label: $t('contextMenu.watchValues'), hint: (ed.watches[id] || []).length ? $t('common.n02', [ed.watches[id].length]) : '', children: watch },
      ...(edit ? [{ label: $t('common.injectFailure'), children: faults }] : []),
      { label: $t('contextMenu.viewLiveData'), run: () => { ed.rightTab = 'live'; } },
      { label: $t('contextMenu.viewTrends'), children: trend },
      ...(rt?.alarm ? [{ label: $t('contextMenu.currentAlarm0', [rt.alarm]), disabled: true }] : []),
    ] },
    { title: $t('contextMenu.analysisIntegrationTesting'), items: [
      { label: $t('contextMenu.askAiAbout0', [name]), run: () => askAssistant($t('contextMenu.n0HowIsItRunning', [multi ? ed.sel.map((x: string) => blocksById.value[x]?.name).join($t('common.k360')) : $t('common.n012', [b.name, id])])) },
      ...(multi ? [] : [{ label: $t('contextMenu.viewTagsProtocolAddresses'), run: () => { ed.rightTab = 'live'; window.dispatchEvent(new CustomEvent('vf:live-tab', { detail: 'pt' })); } }]),
    ] },
  ]);
}

export function openLinkMenu(e: MouseEvent, id: string, extra: MenuItem[] = []) {
  const l = (ed.model?.links || []).find((x: any) => x.id === id); if (!l) return;
  const nm = (x: string) => blocksById.value[x]?.name || x;
  const trs = (ed.model?.blocks || []).filter((b: any) => b.type === 'transporter');
  openCtx(e, [
    { title: $t('contextMenu.connection01', [nm(l.from), nm(l.to)]), items: [
      ...(canEdit() ? extra : []),
      ...(canEdit() && trs.length ? [{ label: $t('contextMenu.transportMethod'), children: [{ label: $t('details.directTransferNoVehicle'), checked: !l.via, run: () => setVia(l, '') },
        ...trs.map((t: any) => ({ label: $t('contextMenu.transportedBy0', [t.name]), checked: l.via === t.id, run: () => setVia(l, t.id) }))] }] : []),
      ...(canEdit() ? [{ label: $t('contextMenu.deleteConnection'), kbd: 'Del', danger: true, run: removeSelected }] : []),
    ] },
    { title: $t('common.analyze'), items: [{ label: $t('contextMenu.askAiAboutThisConnection'), run: () => askAssistant($t('contextMenu.howIsMaterialFlowFrom', [nm(l.from), nm(l.to)])) }] },
  ]);
}
async function setVia(l: any, via: string) {
  const { exec } = await import('../store');
  exec([{ op: 'update_link', id: l.id, set: { via: via || null } }], via ? $t('contextMenu.switchToFleetTransport') : $t('contextMenu.switchToDirectTransfer'));
}

/** Empty canvas area. at: model coordinates at the click (Graph node or Floor Plan pos). */
export function openPaneMenu(e: MouseEvent, extra: MenuItem[] = [], at?: { node?: number[]; pos?: number[] }) {
  const clip = !!(ed.clipboard || localStorage.getItem('vf_ed_clip'));
  openCtx(e, [
    { items: [
      ...(canEdit() ? extra : []),
      ...(canEdit() ? [{ label: $t('contextMenu.paste'), kbd: 'Ctrl+V', disabled: !clip, run: () => paste(at) }] : []),
      { label: $t('common.selectAll'), kbd: 'Ctrl+A', run: () => { ed.sel = (ed.model?.blocks || []).map((b: any) => b.id); } },
      { label: $t('commandsCore.keyboardShortcuts'), kbd: 'Ctrl+/', run: () => window.dispatchEvent(new CustomEvent('vf:shortcuts')) },
    ] },
  ]);
}

function openTrend(id: string, tag: string) {
  import('./ChartFloat.vue').then((m) => openFloat({ id: 'chart', title: `${blocksById.value[id]?.name || id} · ${tag}`, icon: 'TrendCharts', component: markRaw(m.default), size: [480, 300] },
    { sid: id, tag, hours: 2 }, `${id}/${tag}`));
}
