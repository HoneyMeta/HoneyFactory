import { $t } from './i18n';
import { createRouter, createWebHistory, START_LOCATION } from 'vue-router';
import { desk, desktopBoot, loadSession, session } from './api';
import { installNative } from './native';
import { setTitle } from './brand';
import Layout from './layout/Layout.vue';
import { findMesNav } from './mes/nav';
import { homeFor, startPrefs } from './start/recent';

const P = (n: string) => () => import(`./pages/${n}.vue`);
/** Teaching MES pages (5.0.1: integrated into the HoneyFactory UI, web/src/mes/pages) */
const MP = (n: string) => () => import(`./mes/pages/${n}.vue`);

// Factory feature pages ("Current Factory" group in the left navigation)
export const PLANT_MENU: [string, string, string][] = [
  ['workbench', $t('common.home'), 'Monitor'], ['plan', $t('common.productionPlan'), 'Calendar'], ['scenarios', $t('common.scenario'), 'VideoPlay'], ['experiments', $t('common.experimentsOptimization'), 'DataAnalysis'],
  ['reports', $t('common.runReports'), 'Histogram'], ['signals', $t('common.signals'), 'Connection'], ['dataset', $t('common.dataset'), 'Files'],
  ['tables', $t('common.dataSubmodels'), 'Grid'],
];
export const SYS_MENU: [string, string, string, string?][] = [
  ['/tokens', $t('common.apiTokens'), 'Key'], ['/users', $t('common.usersRoles'), 'User', 'admin'], ['/audit', $t('common.auditLog'), 'Document', 'admin'], ['/help', $t('common.helpCenter'), 'QuestionFilled'],
];

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: P('Login'), meta: { public: true } },
    // 5.0 platform operations backend (SaaS): separate entry, accounts, and Cookie sessions + TOTP; bypasses organization login
    { path: '/ops', component: () => import('./ops/OpsApp.vue'), meta: { public: true } },
    // Workbench = former Cockpit + Model Editor (run and edit in one viewport; auto-pause when editing)
    { path: '/p/:pid/workbench', component: () => import('./editor/Workbench.vue'), props: true },
    ...['/p/:pid', '/p/:pid/cockpit', '/p/:pid/editor', '/p/:pid/check'].map((path) => ({ path, redirect: (to: any) => `/p/${to.params.pid}/workbench` })),
    {
      path: '/', component: Layout, children: [
        { path: '', component: P('Plants') },
        { path: 'welcome', component: P('Welcome') },            // Start page (4.5): first page after login / on launch (can be disabled on the page)
        { path: 'p/:pid/plan', component: P('Plan'), props: true },
        { path: 'p/:pid/scenarios', component: P('Scenarios'), props: true },
        { path: 'p/:pid/experiments', component: P('Experiments'), props: true },
        { path: 'p/:pid/reports', component: P('Reports'), props: true },
        { path: 'p/:pid/signals', component: P('Signals'), props: true },
        { path: 'p/:pid/dataset', component: P('Dataset'), props: true },
        { path: 'p/:pid/tables', component: P('Tables'), props: true },
        { path: 'tokens', component: P('Tokens') },
        { path: 'users', component: P('Users') },
        { path: 'audit', component: P('Audit') },
        { path: 'help', component: P('Help') },
        { path: 'teach', component: P('Teach') },
        { path: 'courses', component: P('Teach') },             // 4.6: Student "Courses"; teacher "Courses" (course creation, course library). /teach is the teacher's "Teaching" page; students see courses at /teach
        { path: 'mine', component: P('MyPlants') },              // Desktop client: "My Factories" (students' own local factories)
        // Teaching MES (connects to local factories in the desktop client; pages integrated into this UI since 5.0.1, menu in mes/nav.ts). MesShell: local MES status bar, on-demand startup, factory selection;
        // Browser / server / SaaS pages show instructions + "Open in Desktop Client"
        {
          path: 'mes', component: () => import('./mes/MesShell.vue'), children: [
            { path: '', component: MP('Home') },
            { path: 'screen', component: MP('Screen') },
            { path: 'm', component: MP('Mobile') },
            { path: 'e/:entity', component: MP('EntityPage'), props: true },
            { path: 'production/gantt', component: MP('Gantt') },
            { path: 'trace', component: MP('Trace') },
            { path: 'andon', component: MP('Andon') },
            { path: 'quality', component: MP('Quality') },
            { path: 'quality/spc', component: MP('Spc') },
            { path: 'equipment/monitor', component: MP('Monitor') },
            { path: 'equipment/oee', component: MP('Oee') },
            { path: 'equipment/maint', component: MP('Maint') },
            { path: 'warehouse', component: MP('Stock') },
            { path: 'energy', component: MP('Energy') },
            { path: 'foundry/heats', component: MP('Heats') },
            { path: 'machining/tools', component: MP('Tools') },
            { path: 'machining/defects', component: MP('MachDefects') },
            { path: 'system', component: MP('System') },
            { path: ':rest(.*)*', redirect: '/mes' },
          ],
        },
        { path: 'settings', component: P('Settings') },          // Settings page for desktop mode (desktop client)
        { path: 'org', component: P('Org') },                    // 5.0 organization management (org admins): teachers, students, seats, usage, data, licenses
        { path: 'progress', component: P('ClassProgress') },     // 5.0 class progress: progress and current step reported by desktop clients
      ],
    },
    { path: '/:rest(.*)', redirect: '/' },
  ],
});

/** 5.0: Browser is accessing the SaaS cloud service (not the desktop client). */
export const saasWeb = () => !desk.on && session.user?.deploy === 'saas';
export function saasHome(role = session.user?.role) {
  return role === 'orgadmin' ? '/org' : role === 'teacher' ? '/teach' : '/courses';
}

let openRouted = false;
router.beforeEach(async (to, from) => {
  await desktopBoot();                             // Desktop client: enter directly with remembered login (7 days) / standalone mode; otherwise go to login
  const home = () => homeFor(session.user?.role);
  if (desk.on && to.path === '/login' && session.token && (session.user || (await loadSession()))) return home();
  if (to.meta.public) return true;
  if (!session.user && !(await loadSession())) return '/login?next=' + encodeURIComponent(to.fullPath);
  if (!desk.on && to.path === '/settings') return '/';            // /mes/**: browsers show instructions + Open in Desktop Client (mes/MesClientOnly.vue), without redirecting
  // 5.0 SaaS web app: the server runs no factories, so no factory list, Workbench, or factory pages (modeling and simulation run in the desktop client).
  if (saasWeb() && (to.params.pid || /^\/(welcome|mine|tokens)?$/.test(to.path) || /^\/(welcome|mine|tokens)(\/|$)/.test(to.path))) return saasHome();
  if (desk.mode === 'standalone' && /^\/(tokens|users|audit)(\/|$)/.test(to.path)) return '/';   // Unavailable in standalone mode (online mode uses the same role-based access as the web app).
  // Double-click an assignment package (launcher passes ?open=<path>): go to "Teaching → My Courses", where PackageOpen opens it (redirect once only).
  // The teacher's course library used to be under "Teaching → Course Library": redirect old links to 4.6 "Courses".
  if (to.path === '/teach' && to.query.tab === 'courses' && ['teacher', 'admin'].includes(session.user?.role || '')) return { path: '/courses' };
  if (desk.openPath && !openRouted && to.path !== '/teach') { openRouted = true; return { path: '/teach', query: { open: desk.openPath } }; }
  if (to.path === '/teach' && desk.openPath) openRouted = true;
  // On startup (first navigation to Home): show the Start page if "Show welcome page at startup" is enabled; leave deep links to factories or pages unchanged.
  if (from === START_LOCATION && to.path === '/' && !Object.keys(to.query).length && startPrefs.showWelcome) return '/welcome';
  // Students can only access their own sandboxes: redirect other factory pages to Teaching Home (the desktop client also allows Settings, "My Factories", and their own local-… factories).
  const own = desk.on && String(to.params.pid || '').startsWith('local-');
  if (session.user?.role === 'student' && !/^\/(teach|courses|help|settings|mine|welcome|mes)(\/|$)/.test(to.path) && !String(to.params.pid || '').startsWith('sb-') && !own) return '/teach';
  if (!desk.on && to.path === '/mine') return '/teach';
  if (to.params.pid && !String(to.params.pid).startsWith('sb-')) localStorage.setItem('vf_last_plant', String(to.params.pid));
  return true;
});

// Page title: HoneyFactory · <page> (include the factory name for the Workbench).
const TITLES: Record<string, string> = { '/': $t('common.allFactories'), '/welcome': $t('common.start'), '/teach': $t('common.teaching'), '/courses': $t('common.courses'), '/mine': $t('common.myFactories'), '/help': $t('common.helpCenter'), '/settings': $t('common.settings'), '/login': $t('common.signIn'), '/mes': 'MES',
  '/org': $t('common.organizationManagement'), '/progress': $t('common.classProgress'), '/ops': $t('opsApp.platformOperations') };
router.afterEach((to) => {
  const pid = String(to.params.pid || '');
  if (pid) {
    const sub = to.path.split('/')[3] || 'workbench';
    const page = PLANT_MENU.find((m) => m[0] === sub)?.[1] || $t('common.home');
    const name = session.plants.find((p: any) => p.id === pid)?.name || (pid.startsWith('sb-') ? $t('common.labSandbox') : '');
    setTitle(name ? `${page} · ${name}` : page);
  } else if (to.path === '/teach' && session.user?.role === 'student') setTitle($t('common.courses'));
  else if (to.path.startsWith('/mes/')) setTitle(findMesNav(to.path)?.item[1] ? `${findMesNav(to.path)!.item[1]} · MES` : 'MES');
  else setTitle(TITLES[to.path] || SYS_MENU.find((m) => m[0] === to.path)?.[1] || '');
});

installNative(router);                             // Electron client: tray/jump list navigation, double-clicked files, and recent factories (no-op in the web app).
