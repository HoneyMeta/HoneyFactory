// F1 context help: select a Help Center section for the current context and open it in a side drawer without navigating.
// Priority: data-help="<section>" on the hovered/focused element → hovered Workbench panel (floating window, sidebar, inspector) and current view → route.
// Other modules can specify a section via data-help="plc" on their root element (section IDs: help/sections.ts).
import { session } from '../api';
import { ed } from '../editor/store';
import { sectionById } from './sections';

/** Panel → section (panel IDs in editor/shell/panels.ts and panels/*\/index.ts). */
export const PANEL_HELP: Record<string, string> = {
  'plc-editor': 'plc', 'plc-editor-float': 'plc', 'plc-hmi': 'plc', 'plc-external': 'plc',
  'cell-editor': 'cell', 'cell-editor-float': 'cell', 'cell-console': 'cell', 'cell-inspector': 'cell',
  'teach-task': 'course', 'teach-metrics': 'course', 'teach-console': 'teach', 'teach-classes': 'teach', 'teach-courses': 'course', 'teach-publish': 'teach',
  'design-report': 'design', 'design-sop': 'design', 'debug-console': 'debug', 'debug-console-float': 'debug',
  outliner: 'edit', library: 'edit', model: 'edit', events: 'cockpit', parts: 'views', crew: 'plan', breakpoints: 'graph',
  analysis: 'analysis', scenarios: 'scenario', experiments: 'exp', plan: 'plan', reports: 'analysis', signals: 'signals', dataset: 'dataset', tables: 'tables',
};
const VIEW_HELP: Record<string, string> = { '3d': 'views', plan: 'layers', graph: 'edit', arch: 'layers' };
const ROUTE_HELP: [RegExp, string][] = [
  [/^\/welcome/, 'welcome'], [/^\/teach/, 'teach'], [/^\/mine/, 'client'], [/^\/settings/, 'client'], [/^\/help/, 'start'],
  [/^\/(tokens|users|audit)/, 'account'], [/^\/p\/[^/]+\/plan/, 'plan'], [/^\/p\/[^/]+\/scenarios/, 'scenario'], [/^\/p\/[^/]+\/experiments/, 'exp'],
  [/^\/p\/[^/]+\/reports/, 'analysis'], [/^\/p\/[^/]+\/signals/, 'signals'], [/^\/p\/[^/]+\/dataset/, 'dataset'], [/^\/p\/[^/]+\/tables/, 'tables'],
  [/^\/p\/[^/]+\/workbench/, 'cockpit'], [/^\/$/, 'start'],
];

let mx = -1, my = -1;
addEventListener('pointermove', (e) => { mx = e.clientX; my = e.clientY; }, { passive: true, capture: true });

const ok = (id: string | null | undefined) => (id && sectionById(id) ? id : '');
const forRole = (id: string) => {
  // Show "Five steps" first for students in teaching-related areas
  if (session.user?.role === 'student' && (id === 'teach' || id === 'course')) return 'stu';
  return id;
};

/** Hovered element, falling back to the focused element. */
function hereEl(): Element | null {
  const a = document.activeElement;
  const hov = mx >= 0 ? document.elementFromPoint(mx, my) : null;
  // Ignore the drawer and Command Palette when resolving context
  const skip = (el: Element | null) => !el || !!el.closest('.help-drawer, .cmdp-mask');
  if (hov && !skip(hov)) return hov;
  return a && a !== document.body && !skip(a) ? a : null;
}

function inWorkbench(el: Element | null): string {
  if (!/^\/p\/[^/]+\/workbench/.test(location.pathname) || !ed.model) return '';
  if (el) {
    const fw = el.closest('.fl-layer .fw');
    if (fw) {
      const all = [...document.querySelectorAll('.fl-layer .fw')];
      const w = ed.floats[all.indexOf(fw)];
      const id = w ? String(w.id).split(':')[0] : '';
      if (ok(PANEL_HELP[id])) return PANEL_HELP[id];
      if (id === 'chart') return 'cockpit';
    }
    if (el.closest('.ed-left') && ok(PANEL_HELP[ed.leftPanel])) return PANEL_HELP[ed.leftPanel];
    if (el.closest('.ed-right')) return ed.rightTab && ok(PANEL_HELP[ed.rightTab]) ? PANEL_HELP[ed.rightTab] : ed.rightTab === 'live' ? 'cockpit' : 'layers';
    if (el.closest('.ed-bottom, .ed-bar, .ed-menu, .ed-status')) return 'cockpit';
    if (el.closest('.vp-a')) return 'views';
    if (el.closest('.vp-b, .vp')) return VIEW_HELP[ed.view] || 'views';
    if (el.closest('.ed-act')) return 'cockpit';
  }
  // Pointer outside Workbench: use PLC if its editor is open, lesson context in the teaching workspace, otherwise the current view
  if (ed.floats.some((w: any) => String(w.id).startsWith('plc-editor')) || (ed.leftOpen && ed.leftPanel === 'plc-editor')) return 'plc';
  if (ed.workspace === 'teach') return 'teach';
  return VIEW_HELP[ed.split ? '3d' : ed.view] || 'cockpit';
}

/** Resolve the help section for the current context. */
export function contextHelpId(): string {
  const el = hereEl();
  const tagged = el?.closest('[data-help]')?.getAttribute('data-help');
  // Explicit data-help elements take priority, followed by Workbench panels / views
  const id = ok(tagged) || inWorkbench(el);
  if (id) return forRole(id);
  const r = ROUTE_HELP.find(([re]) => re.test(location.pathname));
  return forRole(ok(r?.[1]) || 'start');
}
