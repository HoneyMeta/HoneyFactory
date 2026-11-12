// Workbench commands (only available at /p/<factory>/workbench). No changes to Workbench.vue:
//   · View, theme, undo/redo, selection, add equipment → use state and functions from editor/store.ts directly;
//   · Open panel → 'vf:open-panel' event (handled by Workbench's openPanel);
//   · Run / Pause / Step / Save Version / Keyboard Shortcuts → dispatch Workbench shortcuts (F5 / F6 / F10 / Ctrl+S / Ctrl+/), reusing its checks and confirmations;
//   · Reset, save, versions, projection, run to, switch workspace → click the corresponding toolbar button (same confirmation flow).
import { $t } from '../i18n';
import { canEdit, P, post } from '../api';
import { isStudent } from '../editor/shell/teach';
import { panelsFor, PANELS, WORKSPACES, type Panel } from '../editor/shell/panels';
import { ctl, ed, exec, flash, focusOn, makeBlock, mode, newId, redo, removeSelected, select, selBlocks, typeOf, undo } from '../editor/store';
import { registerCommands, registerProvider, type Command } from './registry';

const inWb = () => /^\/p\/[^/]+\/workbench/.test(location.pathname) && !!ed.model;
const editable = () => inWb() && canEdit();
const running = () => mode.value === 'running';
/** Dispatch a Workbench shortcut (target body, bubbling to the window listener). */
function key(k: string, mods: { ctrl?: boolean; shift?: boolean; alt?: boolean } = {}) {
  (document.activeElement as HTMLElement | null)?.blur?.();
  document.body.dispatchEvent(new KeyboardEvent('keydown', { key: k, ctrlKey: !!mods.ctrl, shiftKey: !!mods.shift, altKey: !!mods.alt, bubbles: true, cancelable: true }));
}
/** Click a toolbar button by its text. */
function click(sel: string, text?: string) {
  const els = [...document.querySelectorAll<HTMLElement>(sel)];
  const el = text ? els.find((e) => (e.innerText || '').replace(/\s+/g, '').includes(text)) : els[0];
  el?.click();
  return !!el;
}
const openPanel = (id: string) => window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id } }));
const setView = (v: string) => () => { ed.view = v; if (ed.split && v !== '3d' && v !== 'graph') ed.split = false; };

const VIEWS: [string, string, string, string, string][] = [
  ['3d', $t('workbench.switchTo3d'), 'Box', 'Alt+1', $t('workbench.n3dViewPerspective')], ['graph', $t('workbench.switchToGraph'), 'Share', 'Alt+2', $t('workbench.graphFlowCardsConnections')],
  ['plan', $t('workbench.switchToFloorPlan'), 'Grid', 'Alt+3', $t('workbench.planFloorLayoutDrawing2d')], ['arch', $t('workbench.switchToArchitecture'), 'Connection', 'Alt+4', $t('workbench.archArchitectureLayersNetworkPlc')],
];

registerCommands([
  ...VIEWS.map(([v, t, icon, sc, kw]): Command => ({ id: 'wb.view.' + v, title: t, keywords: kw, icon, shortcut: sc, group: $t('workbench.view'), when: () => inWb() && ed.view !== v, run: setView(v) })),
  { id: 'wb.split', title: $t('workbench.n3dAndGraphSideBy'), keywords: $t('workbench.splitScreenSideBySide'), icon: 'Operation', group: $t('workbench.view'), when: inWb, run: () => { ed.split = !ed.split; } },
  { id: 'wb.fit', title: $t('common.fitAll'), keywords: $t('workbench.fitAllZoom'), icon: 'FullScreen', shortcut: 'Home', group: $t('workbench.view'), when: inWb, run: () => focusOn('') },
  { id: 'wb.focus', title: $t('common.focusOnSelectedEquipment'), keywords: $t('workbench.focusLocate'), icon: 'Aim', shortcut: 'F', group: $t('workbench.view'), when: () => inWb() && !!ed.sel.length, run: () => focusOn(ed.sel[0]) },
  { id: 'wb.find', title: $t('common.findEquipmentPlcChannelsOr'), keywords: $t('workbench.findSearchIpI00'), icon: 'Search', shortcut: 'Ctrl+F', group: $t('workbench.view'), when: inWb, run: () => { ed.searchOpen = true; } },
  { id: 'wb.status', title: $t('workbench.overlayLiveStatus'), keywords: $t('workbench.overlayStatus'), icon: 'DataLine', group: $t('workbench.view'), when: inWb, run: () => { ed.overlay = !ed.overlay; } },

  { id: 'wb.run', title: $t('common.run'), keywords: $t('workbench.runPlayStartResume'), icon: 'VideoPlay', shortcut: $t('workbench.f5Space'), group: $t('common.run'), when: () => editable() && !running(), run: () => key('F5') },
  { id: 'wb.pause', title: $t('common.pause'), keywords: $t('workbench.pauseStop'), icon: 'VideoPause', shortcut: $t('workbench.f6Space'), group: $t('common.run'), when: () => editable() && running(), run: () => key('F6') },
  { id: 'wb.step', title: $t('workbench.stepToNextEvent'), keywords: $t('workbench.stepNext'), icon: 'DArrowRight', shortcut: 'F10', group: $t('common.run'), when: editable, run: () => key('F10') },
  ...[[60, $t('workbench.advance1Min')], [600, $t('workbench.advance10Min')], [3600, $t('workbench.advance1Hour')]].map(([s, t]): Command => ({ id: 'wb.step' + s, title: String(t), keywords: $t('workbench.stepFastForward'), icon: 'DArrowRight', group: $t('common.run'), when: editable,
    run: () => { ed.replay = null; return ctl('step', { seconds: s }); } })),
  { id: 'wb.reset', title: $t('workbench.resetToStart'), keywords: $t('workbench.resetRestartBeginning'), icon: 'RefreshLeft', group: $t('common.run'), when: editable, run: () => click('.ed-bar .rb button', $t('workbench.reset')) },
  { id: 'wb.runto', title: $t('workbench.runTo'), keywords: $t('workbench.runToConditionHour'), icon: 'Promotion', group: $t('common.run'), when: editable, run: () => click('.ed-bar .rb button', $t('workbench.runTo2')) },
  ...[1, 10, 60, 300, 1200, 3600].map((v): Command => ({ id: 'wb.speed' + v, title: $t('workbench.speed0', [v]), keywords: $t('workbench.speedMultiplier'), icon: 'Odometer', group: $t('common.run'), when: () => editable() && ed.runtime?.speed !== v,
    run: () => post(P(ed.pid) + '/sim', { speed: v }) })),
  { id: 'wb.fork', title: $t('common.runWhatIfFromHere'), keywords: $t('workbench.forkWhatIfSimulateCompare'), icon: 'Connection', group: $t('common.run'), when: editable, run: () => click('.ed-bar button', $t('workbench.whatIf')) },

  { id: 'wb.undo', title: $t('workbench.undo'), keywords: 'undo', icon: 'RefreshLeft', shortcut: 'Ctrl+Z', group: $t('common.edit'), when: () => inWb() && !!ed.undo.length, run: undo },
  { id: 'wb.redo', title: $t('workbench.redo'), keywords: 'redo', icon: 'RefreshRight', shortcut: 'Ctrl+Y', group: $t('common.edit'), when: () => inWb() && !!ed.redo.length, run: redo },
  { id: 'wb.delete', title: $t('common.deleteSelected'), keywords: $t('workbench.deleteRemove'), icon: 'Delete', shortcut: 'Del', group: $t('common.edit'), when: () => editable() && (!!ed.sel.length || !!ed.selLink), run: removeSelected },
  { id: 'wb.selall', title: $t('common.selectAll'), keywords: 'select all', icon: 'Select', shortcut: 'Ctrl+A', group: $t('common.edit'), when: inWb, run: () => select((ed.model.blocks || []).map((b: any) => b.id)) },
  { id: 'wb.add', title: $t('workbench.addEquipment'), keywords: $t('workbench.addDeviceEquipmentLibrary'), icon: 'CirclePlus', group: $t('common.edit'), when: editable, run: () => openPanel('library') },
  { id: 'wb.check', title: $t('workbench.validateModel'), keywords: $t('workbench.checkValidateErrorsWarnings'), icon: 'CircleCheck', group: $t('common.edit'), when: inWb, run: () => { ed.modelTab = 'check'; openPanel('model'); } },
  { id: 'wb.save', title: $t('workbench.saveToModel'), keywords: $t('workbench.saveApply'), icon: 'Upload', group: $t('common.edit'), when: () => editable() && !!ed.changes.length, run: () => click('.ed-menu button', $t('common.save')) },
  { id: 'wb.version', title: $t('common.saveVersion'), keywords: $t('workbench.versionSnapshot'), icon: 'Clock', shortcut: 'Ctrl+S', group: $t('common.edit'), when: editable, run: () => key('s', { ctrl: true }) },
  { id: 'wb.versions', title: $t('workbench.versionHistory'), keywords: $t('workbench.versionsHistory'), icon: 'Clock', group: $t('common.edit'), when: inWb, run: () => click('.ed-menu button', $t('common.version')) },
  { id: 'wb.keys', title: $t('workbench.workbenchShortcuts'), keywords: $t('workbench.shortcutKeyboard'), icon: 'Postcard', shortcut: 'Ctrl+/', group: $t('common.help'), when: inWb, run: () => key('/', { ctrl: true }) },
]);

/** Panel labels: PLC → "PLC Programming", cell-console → "Operator Console"… Include synonyms for search. */
const PANEL_TITLE: Record<string, [string, string]> = {
  'plc-editor': [$t('workbench.openPlcProgramming'), $t('workbench.plcLadderDiagramStProgramming')], 'plc-editor-float': [$t('workbench.openPlcProgrammingLargeWindow'), $t('workbench.plcLadderDiagramStProgramming2')],
  'cell-console': [$t('workbench.openOperatorConsole'), $t('workbench.buttonStartStopEmergencyIndicator')], analysis: [$t('workbench.openAnalysis'), $t('workbench.timeBreakdownSankeyGanttEnergy')],
  signals: [$t('workbench.openSignals'), $t('workbench.opcUaModbusMqttProtocol')], experiments: [$t('workbench.openExperimentsOptimization'), $t('workbench.experimentCompareOptimizationConfide')],
  breakpoints: [$t('workbench.openBreakpoints'), $t('workbench.breakpointConditionPause')], 'cell-editor': [$t('workbench.openEquipmentInternals'), $t('workbench.controlUnitSensorActuatorI')],
};
const allowedPanels = (): Panel[] => {
  if (!inWb()) return [];
  if (isStudent()) {            // Students: only include items in the activity bar (already filtered by lesson type in the Workbench)
    const ids = new Set([...document.querySelectorAll('.ed-act button[data-panel]')].map((b) => b.getAttribute('data-panel')));
    return PANELS.filter((p) => ids.has(p.id));
  }
  const m = new Map<string, Panel>();
  for (const p of [...panelsFor('all'), ...panelsFor(ed.workspace)]) if (p.place !== 'inspector' && (!p.hidden || p.id === 'plc-editor-float')) m.set(p.id, p);
  return [...m.values()];
};
registerProvider('wb-panels', () => allowedPanels().map((p): Command => {
  const [t, kw] = PANEL_TITLE[p.id] || [$t('common.open') + p.title, ''];
  return { id: 'wb.panel.' + p.id, title: t, keywords: `${p.title} ${kw} ${p.id}`, icon: p.icon, hint: p.place === 'float' ? $t('workbench.floatingWindow') : $t('workbench.sidebar'), group: $t('workbench.panel'), run: () => openPanel(p.id) };
}));
registerProvider('wb-workspaces', () => (inWb() && !isStudent() ? Object.entries(WORKSPACES).filter(([k]) => k !== ed.workspace).map(([k, w]): Command => ({
  id: 'wb.ws.' + k, title: $t('workbench.switchTo0Workspace', [w.label]), keywords: $t('workbench.workspace0', [w.desc]), icon: w.icon, hint: w.desc, group: $t('workbench.workspace'), run: () => click('.ed-ws button', w.label),
})) : []));

// Equipment: enter an ID or name → select and locate
registerProvider('wb-blocks', (q) => {
  if (!inWb() || !q.trim()) return [];
  const k = q.trim().toLowerCase();
  return (ed.model.blocks || []).filter((b: any) => String(b.id).toLowerCase().includes(k) || String(b.name || '').toLowerCase().includes(k)).slice(0, 12)
    .map((b: any): Command => ({ id: 'wb.goto.' + b.id, title: $t('workbench.locate01', [b.name || b.id, b.name && !String(b.name).includes(b.id) ? $t('common.n0', [b.id]) : '']), hint: typeOf(b).label || b.type, keywords: `${b.id} ${b.type}`, icon: typeOf(b).icon || 'Aim', group: $t('common.equipment'),
      run: () => { select([b.id]); focusOn(b.id); flash([b.id], 1500); } }));
});

// Add equipment after the selected equipment (same as double-clicking in the library), or at the far right if none is selected
function addType(type: string) {
  const t = ed.cat.types[type], src = selBlocks.value.length === 1 ? selBlocks.value[0] : null;
  const bs = ed.model.blocks || [];
  const node = src ? [src.node[0] + 280, src.node[1]] : [bs.length ? Math.max(...bs.map((b: any) => b.node?.[0] || 0)) + 280 : 100, bs.length ? Math.min(...bs.map((b: any) => b.node?.[1] || 0)) : 100];
  const pos = src ? [src.pos[0] + src.size[0] / 2 + t.size[0] / 2 + 2, src.pos[1]] : [bs.length ? Math.max(...bs.map((b: any) => b.pos[0] + b.size[0] / 2)) + t.size[0] / 2 + 3 : 10, 10];
  const b = makeBlock(type, pos, node);
  const ops: any[] = [{ op: 'add_block', block: b }];
  const so = src ? typeOf(src).out : [];
  if (src && so.length && t.in.length) ops.push({ op: 'add_link', link: { id: newId('L'), kind: 'material', from: src.id, from_port: so[0], to: b.id, to_port: t.in[0] } });
  exec(ops, ops.length > 1 ? $t('workbench.add1After0', [src.name, t.label]) : $t('common.add0', [t.label]));
  select([b.id]); flash([b.id], 1500); focusOn(b.id, true);
}
registerProvider('wb-types', (q) => {
  if (!editable() || !q.trim() || !ed.cat?.types || ed.modelLocked) return [];
  const k = q.trim().toLowerCase().replace(/^(\u6dfb\u52a0|\u52a0|\u65b0\u589e|add)\s*/, '');
  if (!k) return [];
  return Object.entries(ed.cat.types).filter(([id, t]: any) => !t.hidden && (String(t.label).toLowerCase().includes(k) || id.includes(k))).slice(0, 8)
    .map(([id, t]: any): Command => ({ id: 'wb.addtype.' + id, title: $t('workbench.add0', [t.label]), hint: t.cat || '', keywords: $t('workbench.addCreateNew0', [id]), icon: t.icon || 'CirclePlus', group: $t('workbench.addEquipment2'), run: () => addType(id) }));
});

