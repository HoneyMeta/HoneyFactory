// Global commands: navigation, factories, courses, help sections, resources (What's New, shortcuts, API docs). Workbench actions are in ./workbench.ts.
import { $t } from '../i18n';
import { reactive } from 'vue';
import { desk, get, session } from '../api';
import { density, PREF_CN, setCompact, type CompactPref } from '../compact';
import { sectionsFor } from '../help/sections';
import { router, PLANT_MENU } from '../router';
import { openHelp, openShortcuts, openWhatsNew } from '../start/ui';
import { registerCommands, registerProvider, type Command } from './registry';

const role = () => session.user?.role || '';
const stu = () => role() === 'student';
const authed = () => !!session.user;
const notStu = () => authed() && !stu();
const go = (p: string) => () => router.push(p);
const curPid = () => decodeURIComponent(location.pathname.match(/^\/p\/([^/]+)/)?.[1] || '') || (() => { try { return localStorage.getItem('vf_last_plant') || ''; } catch { return ''; } })();

registerCommands([
  { id: 'nav.welcome', title: $t('common.startPage'), keywords: $t('commandsCore.welcomeHomeStartRecent'), group: $t('commandsCore.page'), icon: 'HomeFilled', when: authed, run: go('/welcome') },
  { id: 'nav.plants', title: $t('common.allFactories'), keywords: $t('commandsCore.factoriesListPlantsNewFactory'), group: $t('commandsCore.page'), icon: 'Grid', when: notStu, run: go('/') },
  { id: 'nav.newplant', title: $t('commandsCore.newFactory'), keywords: $t('commandsCore.templateNewPlantCreate'), group: $t('commandsCore.page'), icon: 'Plus', when: () => notStu() && ['admin', 'engineer'].includes(role()), run: go('/?new=1') },
  // 4.6: Students only see "Courses"; teachers see "Courses" (authoring, publishing) and "Teaching" (classes, assignments, grading)
  { id: 'nav.courses', title: $t('common.courses'), keywords: $t('commandsCore.coursesLabLearningCourseLesson'), group: $t('commandsCore.page'), icon: 'Reading', when: () => ['student', 'teacher', 'admin'].includes(role()) || desk.mode === 'standalone', run: go('/courses') },
  { id: 'nav.teach', title: $t('common.teaching'), keywords: $t('commandsCore.classesAssignmentsGradingReviewTeach'), group: $t('commandsCore.page'), icon: 'School', when: () => ['teacher', 'admin'].includes(role()), run: go('/teach') },
  { id: 'nav.mine', title: $t('common.myFactories'), keywords: $t('commandsCore.localMyMine'), group: $t('commandsCore.page'), icon: 'OfficeBuilding', when: () => stu() && desk.on, run: go('/mine') },
  { id: 'nav.help', title: $t('common.helpCenter'), keywords: $t('commandsCore.helpDocumentationInstructions'), group: $t('commandsCore.page'), icon: 'QuestionFilled', when: authed, run: go('/help') },
  { id: 'nav.mes', title: $t('commandsCore.mesTeachingMes'), keywords: $t('commandsCore.mesWorkOrdersProductionReporting'), group: $t('commandsCore.page'), icon: 'Tickets', when: () => authed(), run: go('/mes') },
  { id: 'nav.settings', title: $t('common.settings'), keywords: $t('commandsCore.clientServerProtocol3dQuality'), group: $t('commandsCore.page'), icon: 'Setting', when: () => authed() && desk.on, run: go('/settings') },
  { id: 'nav.tokens', title: $t('common.apiTokens'), keywords: $t('commandsCore.tokenApiInterface'), group: $t('commandsCore.page'), icon: 'Key', when: () => notStu() && desk.mode !== 'standalone', run: go('/tokens') },
  { id: 'nav.users', title: $t('common.usersRoles'), keywords: $t('commandsCore.accountsUsersPermissions'), group: $t('commandsCore.page'), icon: 'User', when: () => role() === 'admin' && desk.mode !== 'standalone', run: go('/users') },
  { id: 'nav.audit', title: $t('common.auditLog'), keywords: $t('commandsCore.auditLogsRecords'), group: $t('commandsCore.page'), icon: 'Document', when: () => role() === 'admin' && desk.mode !== 'standalone', run: go('/audit') },
  { id: 'nav.docs', title: $t('common.apiDocumentation'), keywords: 'api docs openapi swagger', group: $t('commandsCore.resources'), icon: 'Reading', when: notStu, run: () => window.open('/docs') },
  { id: 'res.whatsnew', title: $t('common.whatSNew'), keywords: $t('commandsCore.updatesVersionsWhatSNew'), group: $t('commandsCore.resources'), icon: 'MagicStick', when: authed, run: openWhatsNew },
  { id: 'res.shortcuts', title: $t('commandsCore.keyboardShortcuts'), keywords: $t('commandsCore.keyboardShortcutHotkey'), group: $t('commandsCore.resources'), icon: 'Postcard', shortcut: 'Ctrl+/', when: () => authed() && !/\/workbench/.test(location.pathname), run: openShortcuts },
  { id: 'res.help-here', title: $t('commandsCore.helpForThisPage'), keywords: $t('commandsCore.f1Help'), group: $t('commandsCore.resources'), icon: 'QuestionFilled', shortcut: 'F1', when: authed, run: () => openHelp('') },
]);

// 4.7 UI layout: Compact (1280×720 minimum) / Standard / Auto
registerProvider('density', () => (authed() ? (['auto', 'on', 'off'] as CompactPref[]).map((p): Command => ({
  id: 'ui.compact.' + p, title: $t('commandsCore.uiLayout0', [PREF_CN[p]]), keywords: $t('commandsCore.compactDensitySmallScreenLaptop'), group: $t('common.settings'), icon: p === 'on' ? 'Fold' : p === 'off' ? 'Expand' : 'Monitor',
  hint: density.pref === p ? $t('commandsCore.current') : '', run: () => setCompact(p),
})) : []));

// Feature pages within the current factory
registerProvider('plant-pages', () => {
  if (!notStu()) return [];
  const pid = curPid(); const p = session.plants.find((x: any) => x.id === pid);
  if (!p) return [];
  return PLANT_MENU.filter((m) => m[0] !== 'workbench').map((m): Command => ({ id: 'plant.' + m[0], title: `${m[1]}`, hint: p.name, keywords: m[0], group: $t('commandsCore.currentFactory'), icon: m[2], run: go(`/p/${pid}/${m[0]}`) }));
});

// Factory: open the Workbench
registerProvider('plants', (q) => {
  if (!authed()) return [];
  const list = session.plants.filter((p: any) => !stu() || String(p.id).startsWith('local-'));
  if (!q.trim() && list.length > 8) return [];
  return list.slice(0, 80).map((p: any): Command => ({ id: 'plant.open.' + p.id, title: $t('commandsCore.openFactory0', [p.name]), hint: p.id, keywords: $t('commandsCore.n01Workbench', [p.id, p.product || '']), group: $t('common.factory'), icon: 'OfficeBuilding', run: go(`/p/${p.id}/workbench`) }));
});

// Courses: students → their lessons (click to open directly); teachers → course library
export const learn = reactive<{ loaded: boolean; courses: any[]; tasks: any[]; library: any[] }>({ loaded: false, courses: [], tasks: [], library: [] });
let lt = 0;
export async function loadLearn(force = false) {
  if (!authed() || (!force && Date.now() - lt < 30000)) return learn;
  lt = Date.now();
  try {
    if (stu() || desk.mode === 'standalone') { const r = await get('/api/teach/my/courses', true); learn.courses = r.courses || []; learn.tasks = r.tasks || []; }
    else if (['teacher', 'admin'].includes(role())) learn.library = await get('/api/teach/courses', true).catch(() => []);
  } catch { /* Teaching module unavailable or access denied */ }
  learn.loaded = true;
  return learn;
}
/** Open a specific lesson: TaskPanel reads vf_teach_aid (last viewed lesson) when opened. */
export function openLesson(aid: number) {
  try { localStorage.setItem('vf_teach_aid', String(aid)); } catch { /* */ }
  router.push({ path: '/teach', query: { l: String(aid) } });
}
registerProvider('lessons', (q) => {
  if (!authed() || !q.trim()) return [];
  const out: Command[] = [];
  for (const c of learn.courses) for (const ch of c.chapters || []) for (const l of ch.lessons || []) {
    if (l.locked) continue;
    out.push({ id: 'lesson.' + l.aid, title: $t('commandsCore.lesson0', [l.title]), hint: c.name, keywords: $t('commandsCore.n01CourseLab', [c.name, ch.title]), group: $t('common.courses'), icon: l.kind === 'cell' ? 'Cpu' : 'Reading', run: () => openLesson(l.aid) });
  }
  for (const t of learn.tasks) out.push({ id: 'lesson.' + t.id, title: $t('commandsCore.assignment0', [t.title]), hint: t.class_name, keywords: $t('commandsCore.assignmentTask'), group: $t('common.courses'), icon: 'Notebook', run: () => openLesson(t.id) });
  for (const c of learn.library) out.push({ id: 'course.' + c.id, title: $t('commandsCore.course0', [c.name]), hint: $t('common.courseLibrary'), keywords: $t('commandsCore.n0CourseLibraryPublish', [c.desc || '']), group: $t('common.courses'), icon: 'Reading', run: () => router.push({ path: '/teach', query: { tab: 'courses' } }) });
  return out;
});

// Help sections: open in the F1 drawer
registerProvider('help', (q) => {
  if (!authed() || !q.trim()) return [];
  return sectionsFor().map((s): Command => ({ id: 'help.' + s.id, title: $t('commandsCore.help0', [s.title]), keywords: s.text.slice(0, 400), group: $t('common.help'), icon: 'QuestionFilled', run: () => openHelp(s.id, 'palette') }));
});
