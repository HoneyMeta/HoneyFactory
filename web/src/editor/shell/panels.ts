// Workbench sidebar/floating-window registry: built-in panels + panels registered by each module (web/src/panels/<module>/index.ts).
// Panel contract: { id, title, icon, component, workspaces: ['teach'|'design'|'debug'|'all'], place: 'left'|'float'|'inspector', size?: [w,h] }
import { $t } from '../../i18n';
import { session } from '../../api';
import { defineAsyncComponent, markRaw } from 'vue';

export type Panel = { id: string; title: string; icon: string; component: any; workspaces: string[]; place: 'left' | 'float' | 'inspector'; size?: number[]; order?: number; roles?: string[]; popout?: string; hidden?: boolean; dock?: string };

const A = (f: () => Promise<any>) => markRaw(defineAsyncComponent(f));
const BUILTIN: Panel[] = [
  { id: 'outliner', title: $t('common.object'), icon: 'List', component: A(() => import('../Outliner.vue')), workspaces: ['all'], place: 'left', order: 10 },
  { id: 'library', title: $t('common.library'), icon: 'Box', component: A(() => import('../Library.vue')), workspaces: ['all'], place: 'left', order: 11 },
  { id: 'model', title: $t('panels.checksChanges'), icon: 'CircleCheck', component: A(() => import('./ModelPanel.vue')), workspaces: ['all'], place: 'left', order: 12 },
  { id: 'events', title: $t('panels.eventsAlarms'), icon: 'Bell', component: A(() => import('./EventsPanel.vue')), workspaces: ['all'], place: 'left', order: 20 },
  { id: 'parts', title: $t('panels.part'), icon: 'Goods', component: A(() => import('./PartsPanel.vue')), workspaces: ['all'], place: 'left', order: 21 },
  { id: 'crew', title: $t('view3D.people'), icon: 'User', component: A(() => import('./CrewPanel.vue')), workspaces: ['design', 'all'], place: 'left', order: 22 },
  { id: 'breakpoints', title: $t('common.breakpoint'), icon: 'Flag', component: A(() => import('../Breakpoints.vue')), workspaces: ['all'], place: 'left', order: 23 },
  { id: 'analysis', title: $t('common.analyze'), icon: 'Histogram', component: A(() => import('../AnalysisDock.vue')), workspaces: ['design', 'debug', 'all'], place: 'float', size: [900, 420], order: 30 },
  { id: 'scenarios', title: $t('common.scenario'), icon: 'VideoPlay', component: A(() => import('../../pages/Scenarios.vue')), workspaces: ['debug', 'design', 'all'], place: 'float', size: [1000, 640], order: 40 },
  { id: 'experiments', title: $t('common.experimentsOptimization'), icon: 'DataAnalysis', component: A(() => import('../../pages/Experiments.vue')), workspaces: ['design', 'all'], place: 'float', size: [1100, 700], order: 41 },
  { id: 'plan', title: $t('common.productionPlan'), icon: 'Calendar', component: A(() => import('../../pages/Plan.vue')), workspaces: ['design', 'all'], place: 'float', size: [1000, 640], order: 42 },
  { id: 'reports', title: $t('common.runReports'), icon: 'Document', component: A(() => import('../../pages/Reports.vue')), workspaces: ['design', 'all'], place: 'float', size: [1100, 720], order: 43 },
  { id: 'signals', title: $t('common.signals'), icon: 'Connection', component: A(() => import('../../pages/Signals.vue')), workspaces: ['debug', 'all'], place: 'float', size: [1100, 680], order: 44 },
  { id: 'dataset', title: $t('common.dataset'), icon: 'Files', component: A(() => import('../../pages/Dataset.vue')), workspaces: ['debug', 'all'], place: 'float', size: [900, 560], order: 45 },
  { id: 'tables', title: $t('common.dataSubmodels'), icon: 'Grid', component: A(() => import('../../pages/Tables.vue')), workspaces: ['design', 'debug', 'all'], place: 'float', size: [1100, 680], order: 46 },
];

/** Load module registration files (teaching, PLC, control units, design, integration testing, …) if present; skip otherwise. */
const mods = import.meta.glob('../../panels/*/index.ts', { eager: true }) as Record<string, any>;
const EXTRA: Panel[] = Object.values(mods).flatMap((m: any) => (m.panels || []).map((p: any, i: number) => ({ order: 100 + i, ...p, component: markRaw(p.component) })));

export const PANELS: Panel[] = [...BUILTIN, ...EXTRA].sort((a, b) => (a.order ?? 50) - (b.order ?? 50));
export const panelById = (id: string) => PANELS.find((p) => p.id === id);
// PLC programming window defaults to the right half, leaving 3D on the left to view equipment motion while coding
for (const id of ['plc-editor-float']) { const p = PANELS.find((q) => q.id === id); if (p && !p.dock) p.dock = 'right'; }
// Sidebar X and floating window X-float provide the same feature: only the sidebar appears in the activity bar; its title bar has an "Open in Large Window" button
for (const p of PANELS) {
  const tw = PANELS.find((q) => q.id === p.id + '-float');
  if (tw && p.place === 'left') { p.popout = tw.id; tw.hidden = true; }
}

/** 3D extensions (web/src/scene_ext/*.ts export register(scene)). */
const exts = import.meta.glob('../../scene_ext/*.ts', { eager: true }) as Record<string, any>;
export function registerSceneExtensions(scene: any) {
  for (const m of Object.values(exts)) try { m.register?.(scene); } catch (e) { console.warn($t('panels.failedToLoadThe3d'), e); }
}

export const WORKSPACES: Record<string, { label: string; icon: string; view: string; left: string[]; right: string; desc: string }> = {
  all: { label: $t('panels.general'), icon: 'Monitor', view: '3d', left: ['outliner'], right: 'props', desc: $t('panels.allFeatures') },
  teach: { label: $t('common.teaching'), icon: 'Reading', view: '3d', left: ['teach-task', 'plc-editor', 'outliner'], right: 'live', desc: $t('panels.labTasksPlcProgrammingTroubleshootin') },
  design: { label: $t('panels.design'), icon: 'EditPen', view: 'plan', left: ['library', 'outliner'], right: 'props', desc: $t('panels.layoutScenarioComparisonReportsTrain') },
  debug: { label: $t('panels.integrationTest'), icon: 'Connection', view: 'graph', left: ['debug-console', 'events'], right: 'live', desc: $t('panels.tagListsProtocolsFaultScripts') },
};
/** Omitted roles = visible to everyone; otherwise restricted to those roles (admin always has access). */
const roleOk = (p: any) => !p.roles || p.roles.includes(session.user?.role) || session.user?.role === 'admin';
/** Teaching-only panels (classes, publishing assignments, …) are also hidden in "General". */
const teachOnly = (p: Panel) => p.workspaces.length > 0 && p.workspaces.every((w) => w === 'teach');
export const panelsFor = (ws: string) => PANELS.filter((p) => roleOk(p) && (p.workspaces.includes('all') || p.workspaces.includes(ws) || (ws === 'all' && !teachOnly(p))));
/** Common panels (available in every workspace at fixed positions). */
export const isCommon = (p: Panel) => p.workspaces.includes('all');
