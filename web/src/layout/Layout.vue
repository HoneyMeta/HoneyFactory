<template>
  <!-- 5.0.1 Shell: same light theme as HoneyMOM (glass sidebar + top command bar + main-area breadcrumbs; see design/README.md). Light theme only. -->
  <el-container class="shell">
    <el-aside :width="sideW" class="side" :class="{ collapsed }">
      <div class="brand" data-k="brand" @click="router.push(startPrefs.showWelcome || stu ? '/welcome' : '/')">
        <img :src="markUrl()" :alt="$t('common.honey')" />
        <div v-if="!collapsed" class="bt"><b>{{ $t('common.honeyfactory') }}</b><small>{{ $t('layout.industrialDigitalTwinSimulationPlatf') }}</small></div>
      </div>
      <el-scrollbar class="scroll">
        <el-menu :default-active="active" :collapse="collapsed" :collapse-transition="false" :default-openeds="openeds" @select="go" @open="onOpen">
          <el-menu-item v-if="!saas" index="/welcome" data-k="menu-welcome"><el-icon><HomeFilled /></el-icon><template #title>{{ $t('common.start') }}</template></el-menu-item>
          <el-menu-item v-if="!stu && !saas" index="/"><el-icon><Grid /></el-icon><template #title>{{ $t('common.allFactories') }}</template></el-menu-item>
          <!-- 5.0: Organization management for org admins; class progress for teachers (reported by desktop clients) -->
          <el-menu-item v-if="!desk.on && ['orgadmin', 'admin'].includes(session.user?.role)" index="/org" data-k="menu-org"><el-icon><OfficeBuilding /></el-icon><template #title>{{ $t('common.organizationManagement') }}</template></el-menu-item>
          <!-- 4.6: Students only have "Courses" (course cards + school assignments); teachers have "Courses" (course creation, library) and "Teaching" (classes, assignments, submissions and grading) -->
          <el-menu-item v-if="stu || (desk.mode === 'standalone' && ['teacher', 'admin', 'student'].includes(session.user?.role))" index="/courses" data-k="menu-courses"><el-icon><Reading /></el-icon><template #title>{{ $t('common.courses') }}</template></el-menu-item>
          <template v-else-if="teacherRole">
            <el-menu-item index="/courses" data-k="menu-courses"><el-icon><Collection /></el-icon><template #title>{{ $t('common.courses') }}</template></el-menu-item>
            <el-menu-item index="/teach" data-k="menu-teach"><el-icon><School /></el-icon><template #title>{{ $t('common.teaching') }}</template></el-menu-item>
            <el-menu-item v-if="!desk.on || saasSrv" index="/progress" data-k="menu-progress"><el-icon><TrendCharts /></el-icon><template #title>{{ $t('common.classProgress') }}</template></el-menu-item>
          </template>
          <!-- Students in the desktop client: unlimited local factories, stored only on this computer; unavailable on the web -->
          <el-menu-item v-if="(stu || (teacherRole && saasSrv)) && desk.on" index="/mine" data-k="menu-mine"><el-icon><OfficeBuilding /></el-icon><template #title>{{ $t('common.myFactories') }}</template></el-menu-item>
          <!-- 5.0.1 Teaching MES: expands into MES groups in the desktop client (pages use this UI, no embedded web page); the web has one entry explaining "Use in the desktop client" -->
          <el-sub-menu v-if="desk.on" index="mes" class="mes-sub" data-k="menu-mes" popper-class="vf-side-pop">
            <template #title><el-icon><Tickets /></el-icon><span>MES</span><i v-if="mesRunning" class="mes-dot" :title="$t('layout.localMesIsRunning')" /></template>
            <el-sub-menu v-for="g in MES_NAV" :key="g.group" :index="'mes:' + g.group" class="mes-grp" popper-class="vf-side-pop">
              <template #title><el-icon><component :is="g.icon" /></el-icon><span>{{ g.group }}</span></template>
              <el-menu-item v-for="it in g.items" :key="it[0]" :index="it[0]">{{ it[1] }}</el-menu-item>
            </el-sub-menu>
          </el-sub-menu>
          <el-menu-item v-else index="/mes" data-k="menu-mes"><el-icon><Tickets /></el-icon><template #title>MES<small class="cli">{{ $t('common.desktopClient') }}</small></template></el-menu-item>
          <div v-if="pid && !collapsed && !stu && !saas" class="grp">
            <span>{{ $t('commandsCore.currentFactory') }}</span>
            <el-select :model-value="pid" size="small" class="psel" @change="(v: string) => router.push(`/p/${v}/${sub || 'workbench'}`)">
              <el-option v-for="p in session.plants" :key="p.id" :label="(p.local && desk.mode === 'server' ? $t('layout.local') : '') + p.name" :value="p.id" />
            </el-select>
          </div>
          <template v-if="pid && !stu && !saas">
            <el-menu-item v-for="m in PLANT_MENU" :key="m[0]" :index="`/p/${pid}/${m[0]}`"><el-icon><component :is="m[2]" /></el-icon><template #title>{{ m[1] }}</template></el-menu-item>
          </template>
          <div v-if="!collapsed" class="grp"><span>{{ $t('layout.system') }}</span></div>
          <template v-for="m in SYS_MENU" :key="m[0]">
            <el-menu-item v-if="(!m[3] || session.user?.role === m[3] || (m[3] === 'admin' && session.user?.role === 'orgadmin')) && (!stu || m[0] === '/help') && (desk.mode !== 'standalone' || !SERVER_ONLY.includes(m[0])) && !(saasSrv && m[0] === '/tokens')" :index="m[0]"><el-icon><component :is="m[2]" /></el-icon><template #title>{{ m[1] }}</template></el-menu-item>
          </template>
          <el-menu-item v-if="desk.on" index="/settings"><el-icon><Setting /></el-icon><template #title>{{ $t('common.settings') }}</template></el-menu-item>
          <el-menu-item v-if="!stu" index="docs"><el-icon><Document /></el-icon><template #title>{{ $t('common.apiDocumentation') }}</template></el-menu-item>
        </el-menu>
      </el-scrollbar>
      <button class="fold" data-k="nav-fold" :title="collapsed ? $t('layout.expandMenu') : $t('layout.collapseMenu')" @click="collapsed = !collapsed">
        <el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon><span v-if="!collapsed">{{ $t('layout.collapseMenu') }}</span>
      </button>
      <div v-if="!collapsed" class="foot">{{ $t('layout.honeyTechnologyZhengzhouCoLtd') }}<br>HoneyMeta · {{ desk.on ? 'v' + desk.version + $t('layout.desktopClient') : ui.version ? 'v' + ui.version : '' }}</div>
    </el-aside>
    <el-container class="col">
      <el-header class="top" :height="density.on ? '44px' : '52px'">
        <button class="cmd" data-k="hdr-palette" :aria-label="$t('layout.searchPagesFactoriesEquipmentCommand')" @click="openCommandPalette()">
          <el-icon class="ci"><Search /></el-icon><span class="ph">{{ $t('layout.searchPagesFactoriesEquipmentCommand2') }}</span><kbd>Ctrl</kbd><kbd>K</kbd>
        </button>
        <span class="grow" />
        <template v-if="plant">
          <span class="chip" :class="plant.paused ? 'p' : 'r'"><i class="pd" :class="{ 'hm-pulse': !plant.paused }" />{{ plant.paused ? $t('common.paused') : $t('common.runningAt0', [plant.speed]) }}</span>
          <span class="clock hm-num">{{ plant.time }}</span>
        </template>
        <!-- Desktop client: local MES running (outside MES pages) → click to return to MES -->
        <el-tooltip v-if="desk.on && mesRunning && !onMes" :content="$t('layout.localMesIsRunningStops')">
          <span class="local-badge mesb" data-k="hdr-mes" @click="router.push('/mes')"><i class="pd" />MES · {{ desk.mes?.plant_name }}</span></el-tooltip>
        <!-- Desktop client: connected server and online/offline status; show "Standalone" in standalone mode -->
        <el-tooltip v-if="desk.on" :content="deskTip">
          <span class="local-badge" :class="{ off: desk.mode === 'server' && desk.online === false }" @click="router.push('/settings')">
            <el-icon><component :is="desk.mode === 'standalone' ? 'Monitor' : 'Connection'" /></el-icon>{{ deskLabel }}</span></el-tooltip>
        <LangSwitch compact />
        <el-dropdown trigger="click" @command="onHelp">
          <button class="ib" data-k="hdr-help" :title="$t('common.help')" :aria-label="$t('common.help')"><el-icon><QuestionFilled /></el-icon></button>
          <template #dropdown><el-dropdown-menu>
            <el-dropdown-item command="here"><span class="dm">{{ $t('commandsCore.helpForThisPage') }}<kbd>F1</kbd></span></el-dropdown-item>
            <el-dropdown-item command="center">{{ $t('common.helpCenter') }}</el-dropdown-item>
            <el-dropdown-item command="keys"><span class="dm">{{ $t('common.keyboardShortcuts') }}<kbd>Ctrl /</kbd></span></el-dropdown-item>
            <el-dropdown-item command="new" data-k="hdr-whatsnew" divided>{{ $t('layout.whatSNew0', [ui.version ? $t('common.k459') + ui.version + $t('common.k460') : '']) }}</el-dropdown-item>
            <el-dropdown-item command="welcome">{{ $t('common.startPage') }}</el-dropdown-item>
          </el-dropdown-menu></template>
        </el-dropdown>
        <el-dropdown trigger="click" @command="onCmd">
          <button class="user"><span class="av">{{ (session.user?.name || '?').slice(0, 1) }}</span>
            <span class="uname">{{ session.user?.name }} <small>{{ session.user?.role_name }}</small></span><el-icon class="dd"><ArrowDown /></el-icon></button>
          <template #dropdown>
            <el-dropdown-menu v-if="desk.on">
              <el-dropdown-item v-if="desk.mode === 'server'" command="pw"><el-icon><Key /></el-icon>{{ $t('passwordDialog.changePassword') }}</el-dropdown-item>
              <el-dropdown-item command="settings"><el-icon><Setting /></el-icon>{{ $t('common.settings') }}</el-dropdown-item>
              <el-dropdown-item command="help"><el-icon><QuestionFilled /></el-icon>{{ $t('common.helpCenter') }}</el-dropdown-item>
              <el-dropdown-item command="deskout" divided><el-icon><SwitchButton /></el-icon>{{ desk.mode === 'standalone' ? $t('layout.exitStandaloneMode') : $t('layout.signOut') }}</el-dropdown-item>
            </el-dropdown-menu>
            <el-dropdown-menu v-else>
              <el-dropdown-item command="pw"><el-icon><Key /></el-icon>{{ $t('passwordDialog.changePassword') }}</el-dropdown-item>
              <el-dropdown-item v-if="!saasSrv" command="tokens"><el-icon><Ticket /></el-icon>{{ $t('common.apiTokens') }}</el-dropdown-item>
              <el-dropdown-item command="help"><el-icon><QuestionFilled /></el-icon>{{ $t('common.helpCenter') }}</el-dropdown-item>
              <!-- 4.7 No settings page on the web: change layout here (under "Settings" in the desktop client) -->
              <el-dropdown-item v-for="p in (['auto', 'on', 'off'] as const)" :key="p" :command="'density:' + p" :divided="p === 'auto'" :data-k="'density-' + p">
                <span class="dm">{{ $t('layout.layout0', [p === 'auto' ? $t('layout.autoCompact') : p === 'on' ? $t('common.alwaysCompact') : $t('common.alwaysStandard')]) }}<el-icon v-if="density.pref === p"><Check /></el-icon></span></el-dropdown-item>
              <el-dropdown-item command="out" divided><el-icon><SwitchButton /></el-icon>{{ $t('layout.signOut') }}</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main :class="['main', 'hm-grid-bg', { full: route.meta.full }]">
        <div v-if="!route.meta.full" class="crumbs" :aria-label="$t('common.youAreHere')" data-k="crumbs">
          <template v-for="(c, i) in crumbs" :key="i">
            <span v-if="i" class="sl" aria-hidden="true">/</span>
            <a v-if="c.to && i < crumbs.length - 1" :href="c.to" @click.prevent="router.push(c.to)">{{ c.label }}</a>
            <span v-else :class="{ last: i === crumbs.length - 1 }">{{ c.label }}</span>
          </template>
        </div>
        <router-view :key="route.fullPath" />
      </el-main>
    </el-container>
    <PasswordDialog v-model="pwOpen" />
  </el-container>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { desk, post, refreshDesk, saasServer, session, get } from '../api';
import { PLANT_MENU, SYS_MENU, saasWeb } from '../router';
import PasswordDialog from '../components/PasswordDialog.vue';
import LangSwitch from '../components/LangSwitch.vue';
import { markUrl } from '../brand';
import { openCommandPalette } from '../commands/registry';
import { startPrefs } from '../start/recent';
import { openHelp, openShortcuts, openWhatsNew, ui } from '../start/ui';
import { density, setCompact, type CompactPref } from '../compact';
import { MES_NAV, mesCrumbs } from '../mes/nav';

const route = useRoute(), router = useRouter();
const collapsed = ref(innerWidth < 1000);
const sideW = computed(() => (collapsed.value ? '60px' : density.on ? '204px' : '232px'));   // 4.7 Compact layout: narrower sidebar
const pid = computed(() => (route.params.pid as string) || localStorage.getItem('vf_last_plant') || session.plants[0]?.id);
const sub = computed(() => route.path.split('/')[3] || '');
const onMes = computed(() => route.path === '/mes' || route.path.startsWith('/mes/'));
const active = computed(() => (stu.value && route.path === '/teach' ? '/courses' : route.path));
const plant = computed(() => (route.params.pid ? session.plants.find((p) => p.id === route.params.pid) : null));
const mesRunning = computed(() => desk.mes?.state === 'running');
// Students: only "Teaching" and "Help" in the sidebar; no factory selector or factory pages
const stu = computed(() => session.user?.role === 'student');
const teacherRole = computed(() => ['teacher', 'admin', 'orgadmin'].includes(session.user?.role));
const saas = computed(() => saasWeb());                                             // 5.0 SaaS web: no factories (they run in the desktop client)
const saasSrv = computed(() => saasServer());                                       // Web or desktop client connected to SaaS: no API tokens (factory APIs are all local)
const SERVER_ONLY = ['/tokens', '/users', '/audit'];                               // Not available in standalone mode (same as the web when online)
const host = (u: string) => u.replace(/^https?:\/\//, '');
const deskLabel = computed(() => desk.mode === 'standalone' ? $t('layout.standalone') : desk.online === false ? $t('common.offline') : host(desk.server));
const deskTip = computed(() => desk.mode === 'standalone' ? $t('layout.standaloneModeAllFactoriesAnd')
  : desk.online === false ? $t('layout.cannotConnectToServer0', [desk.server])
    : $t('layout.connectedToServer0Server', [desk.server]));
// On MES pages: expand MES and the current group in the menu
const openeds = computed(() => {
  if (!onMes.value || !desk.on) return [];
  const g = MES_NAV.find((x) => x.items.some((i) => i[0] === route.path || (i[0] !== '/mes' && route.path.startsWith(i[0] + '/'))));
  return ['mes', 'mes:' + (g?.group || MES_NAV[0].group)];
});
function onOpen(i: string) { if (i === 'mes' && !onMes.value && !collapsed.value) router.push('/mes'); }   // Click "MES": expand and open MES Home (start local MES on demand)
function onHelp(c: string) {
  if (c === 'here') openHelp(''); else if (c === 'center') router.push('/help'); else if (c === 'keys') openShortcuts();
  else if (c === 'new') openWhatsNew(); else if (c === 'welcome') router.push('/welcome');
}
const pageName = computed(() => PLANT_MENU.find((m) => m[0] === sub.value)?.[1] || SYS_MENU.find((m) => m[0] === route.path)?.[1] || (route.path === '/settings' ? $t('common.settings') : route.path === '/welcome' ? $t('common.start')
  : route.path === '/progress' ? $t('common.classProgress') : ''));
// Breadcrumbs (top row of the main area, as in HoneyMOM)
const crumbs = computed(() => {
  const p = route.path;
  if (onMes.value) return mesCrumbs(p);
  const out: { label: string; to?: string }[] = [];
  if (p === '/welcome') return [{ label: $t('common.start') }];
  if (p === '/mine') out.push({ label: $t('common.myFactories'), to: '/mine' });
  else if (p === '/courses' || (stu.value && p === '/teach')) out.push({ label: $t('common.courses'), to: '/courses' });
  else if (p === '/teach' || p === '/progress') out.push({ label: $t('common.teaching'), to: '/teach' });
  else if (p === '/org') out.push({ label: $t('common.organizationManagement') });
  else if (stu.value) out.push({ label: $t('common.courses'), to: '/courses' });
  else out.push({ label: $t('common.factory'), to: '/' });
  if (p === '/' && !stu.value) out[0] = { label: $t('common.allFactories') };
  if (plant.value) out.push({ label: plant.value.name, to: `/p/${plant.value.id}/workbench` });
  if (pageName.value) out.push({ label: pageName.value });
  return out;
});
function go(i: string) { if (i === 'docs') window.open('/docs'); else if (!i.startsWith('mes:') && i !== 'mes') router.push(i); }
let t: any;
async function refresh() {
  try { session.plants = (await get('/api/overview', true)).plants; } catch { /* */ }
  if (desk.on) refreshDesk();                     // Desktop client: online/offline and local MES status
}
onMounted(() => { t = setInterval(refresh, 5000); });
onUnmounted(() => clearInterval(t));
async function onCmd(c: string) {
  if (c === 'out') {
    await post('/api/me/logout', {}).catch(() => null);      // 5.0: Revoke the server session too (token expires immediately)
    session.token = ''; session.user = null; localStorage.removeItem('vf_token'); router.push('/login');
  }
  if (c === 'deskout') {
    await post('/api/desktop/logout', {});
    session.token = ''; session.user = null; localStorage.removeItem('vf_token'); desk.mode = '';
    router.push('/login');
  }
  if (c === 'tokens') router.push('/tokens');
  if (c === 'settings') router.push('/settings');
  if (c === 'help') router.push('/help');
  if (c === 'pw') pwOpen.value = true;       // Current password + new password twice (online desktop changes the server account; local offline login updates too)
  if (c.startsWith('density:')) setCompact(c.slice(8) as CompactPref);
}
const pwOpen = ref(false);
</script>

<style scoped>
.shell { height: 100vh; background: var(--hm-canvas); }
.col { min-width: 0; }
/* ---- Left menu: translucent white background and thin border, matching the HoneyMOM sidebar ---- */
.side { background: var(--hm-glass-strong); backdrop-filter: var(--hm-glass-blur); border-right: 1px solid var(--hm-border); display: flex; flex-direction: column;
  transition: width var(--hm-dur-3) var(--hm-ease); overflow: hidden; position: relative; z-index: 21; }
.brand { display: flex; align-items: center; gap: 10px; height: 52px; flex: none; padding: 0 14px; cursor: pointer; border-bottom: 1px solid var(--hm-border); }
.brand img { width: 28px; height: 28px; flex: none; }
.bt { display: flex; flex-direction: column; line-height: 1.15; white-space: nowrap; min-width: 0; }
.bt b { font-size: 15px; letter-spacing: .04em; font-weight: 700; color: var(--hm-text); } .bt small { font-size: 10.5px; color: var(--hm-text-3); letter-spacing: .12em; }
.collapsed .brand { justify-content: center; padding: 0; }
.scroll { flex: 1; min-height: 0; }
.scroll :deep(.el-scrollbar__view) { padding: 8px 8px 10px; }
.collapsed .scroll :deep(.el-scrollbar__view) { padding: 8px 0; }
.side :deep(.el-menu) { border-right: 0; background: transparent; --el-menu-bg-color: transparent; --el-menu-hover-bg-color: var(--hm-surface-3); --el-menu-text-color: var(--hm-text-2);
  --el-menu-active-color: var(--hm-primary-press); --el-menu-item-height: 36px; --el-menu-sub-item-height: 32px; --el-menu-base-level-padding: 10px; --el-menu-level-padding: 14px;
  --el-menu-item-font-size: var(--hm-fs-sm); --el-menu-icon-width: 20px; }
.side :deep(.el-menu-item), .side :deep(.el-sub-menu__title) { border-radius: var(--hm-r-md); margin: 1px 0; position: relative; line-height: 36px; }
.side :deep(.el-menu-item:hover), .side :deep(.el-sub-menu__title:hover) { color: var(--hm-text); }
.side :deep(.el-menu-item .el-icon), .side :deep(.el-sub-menu__title .el-icon) { color: var(--hm-text-3); font-size: 16px; }
.side :deep(.el-menu-item.is-active) { background: var(--hm-primary-soft); color: var(--hm-primary-press); font-weight: 600; }
.side :deep(.el-menu-item.is-active .el-icon) { color: var(--hm-primary); }
.side :deep(.el-menu-item.is-active)::before { content: ''; position: absolute; left: 0; top: 8px; bottom: 8px; width: 3px; border-radius: 2px; background: var(--hm-primary); }
.side :deep(.el-sub-menu.is-active > .el-sub-menu__title) { color: var(--hm-text); font-weight: 600; }
.side :deep(.el-sub-menu.is-active > .el-sub-menu__title .el-icon) { color: var(--hm-primary); }
/* MES groups: indentation + thin left border (matching the HoneyMOM menu) */
.side :deep(.mes-sub .el-menu--inline) { background: transparent; }
.side :deep(.mes-grp > .el-sub-menu__title) { height: 32px; line-height: 32px; font-size: var(--hm-fs-sm); }
.side :deep(.mes-grp .el-menu-item) { height: 30px; line-height: 30px; font-size: var(--hm-fs-sm); }
.side :deep(.mes-grp > .el-menu--inline) { position: relative; }
.side :deep(.mes-grp > .el-menu--inline)::before { content: ''; position: absolute; left: 33px; top: 2px; bottom: 4px; width: 1px; background: var(--hm-border); }
.mes-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--hm-run); margin-left: 6px; display: inline-block; }
.cli { font-size: 10.5px; color: var(--hm-text-3); border: 1px solid var(--hm-border); border-radius: var(--hm-r-pill); padding: 0 6px; line-height: 16px; margin-left: 6px; }
.grp { padding: 12px 10px 4px; color: var(--hm-text-3); font-size: var(--hm-fs-2xs); letter-spacing: .08em; display: grid; gap: 6px; }
.psel :deep(.el-select__wrapper) { background: var(--hm-surface-2); }
.fold { display: flex; align-items: center; gap: 8px; margin: 4px 8px 4px; padding: 6px 10px; border: 0; background: transparent; border-radius: var(--hm-r-md); color: var(--hm-text-3);
  cursor: pointer; font: inherit; font-size: var(--hm-fs-xs); flex: none; }
.fold:hover { background: var(--hm-surface-3); color: var(--hm-text); }
.collapsed .fold { justify-content: center; margin: 4px auto 8px; width: 40px; padding: 6px 0; }
.foot { color: var(--hm-text-3); font-size: 10.5px; padding: 8px 16px 10px; border-top: 1px solid var(--hm-border); line-height: 1.5; flex: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

/* ---- Top bar ---- */
.top { display: flex; align-items: center; gap: 8px; padding: 0 12px 0 16px; background: var(--hm-glass-strong); backdrop-filter: var(--hm-glass-blur); border-bottom: 1px solid var(--hm-border);
  position: relative; z-index: 20; }
.top::after { content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 1px; pointer-events: none;
  background: linear-gradient(90deg, transparent, rgba(11, 165, 196, .35) 30%, rgba(20, 99, 214, .35) 60%, transparent); }
.cmd { flex: 1 1 auto; max-width: 520px; height: 34px; display: flex; align-items: center; gap: 8px; padding: 0 8px 0 12px; border: 1px solid var(--hm-border); border-radius: var(--hm-r-md);
  background: var(--hm-surface-2); cursor: text; font: inherit; color: var(--hm-text-3); transition: border-color var(--hm-dur-1), background var(--hm-dur-1); min-width: 0; }
.cmd:hover { border-color: var(--hm-border-strong); background: #fff; }
.ci { font-size: 15px; } .ph { flex: 1; text-align: left; font-size: var(--hm-fs-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
kbd { font-family: var(--hm-font-mono); font-size: 10.5px; border: 1px solid var(--hm-border-strong); border-bottom-width: 2px; border-radius: 4px; padding: 0 5px; background: #fff; color: var(--hm-text-2); line-height: 16px; }
.dm { display: inline-flex; gap: 14px; justify-content: space-between; min-width: 150px; align-items: center; }
.ib { display: inline-flex; align-items: center; justify-content: center; height: 32px; min-width: 32px; padding: 0 8px; border: 0; border-radius: var(--hm-r-md); background: transparent;
  color: var(--hm-text-2); cursor: pointer; font: inherit; }
.ib:hover { background: var(--hm-surface-3); color: var(--hm-text); } .ib .el-icon { font-size: 17px; }
.pd { width: 7px; height: 7px; border-radius: 50%; background: currentColor; display: inline-block; flex: none; }
.clock { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: var(--hm-r-md); background: var(--hm-surface-2); border: 1px solid var(--hm-border);
  font-size: 14px; font-weight: 600; color: var(--hm-text); letter-spacing: .02em; }
.chip { display: inline-flex; align-items: center; gap: 6px; font-size: var(--hm-fs-xs); border-radius: var(--hm-r-pill); padding: 3px 10px; border: 1px solid transparent; }
.chip.r { background: var(--hm-run-soft); color: var(--hm-run-ink); } .chip.p { background: var(--hm-idle-soft); color: var(--hm-idle-ink); }
.local-badge { display: inline-flex; align-items: center; gap: 5px; font-size: var(--hm-fs-xs); color: var(--hm-text-2); background: #fff; border: 1px solid var(--hm-border);
  border-radius: var(--hm-r-pill); padding: 3px 10px; cursor: pointer; white-space: nowrap; }
.local-badge:hover { border-color: var(--hm-border-strong); color: var(--hm-text); }
.local-badge .el-icon { color: var(--hm-run); }
.local-badge.off { color: var(--hm-idle-ink); background: var(--hm-idle-soft); border-color: transparent; } .local-badge.off .el-icon { color: var(--hm-idle-ink); }
.local-badge.mesb { color: var(--hm-setup-ink); background: var(--hm-primary-soft); border-color: transparent; max-width: 220px; overflow: hidden; text-overflow: ellipsis; }
.local-badge.mesb .pd { color: var(--hm-run); }
.user { display: inline-flex; align-items: center; gap: 7px; height: 34px; padding: 0 6px 0 4px; margin-left: 2px; border: 0; border-radius: var(--hm-r-pill); background: transparent;
  cursor: pointer; font: inherit; color: var(--hm-text); }
.user:hover { background: var(--hm-surface-3); }
.av { width: 28px; height: 28px; border-radius: 50%; display: grid; place-items: center; font-size: 13px; font-weight: 700; color: #fff; background: linear-gradient(135deg, #e09a45, var(--hm-amber)); flex: none; }
.uname { font-size: var(--hm-fs-sm); white-space: nowrap; } .uname small { color: var(--hm-text-3); font-size: var(--hm-fs-xs); } .dd { font-size: 11px; color: var(--hm-text-3); }

/* ---- Main area ---- */
.main { padding: 0; overflow: auto; position: relative; } .main.full { overflow: hidden; }
.crumbs { display: flex; align-items: center; gap: 6px; height: 34px; padding: 0 20px; font-size: var(--hm-fs-xs); color: var(--hm-text-3); position: sticky; top: 0; z-index: 5;
  background: linear-gradient(var(--hm-canvas) 70%, rgba(243, 246, 250, 0)); }
.crumbs a { color: var(--hm-text-3); } .crumbs a:hover { color: var(--hm-primary); text-decoration: none; }
.crumbs .last { color: var(--hm-text-2); font-weight: 600; } .crumbs .sl { color: var(--hm-border-strong); }
.main :deep(.page) { padding-top: 2px; }
@media (max-width: 1279px) { .uname small, .ph { display: none; } .cmd { flex: 0 0 auto; width: 92px; } }
@media (max-width: 800px) { .uname, .clock, .cmd kbd { display: none; } .cmd { width: 40px; padding: 0 10px; } }
</style>
<style>
/* Collapsed menu: hover popup groups (MES) */
.vf-side-pop.el-popper { border-radius: 10px !important; }
.vf-side-pop .el-menu { padding: 4px; --el-menu-item-height: 32px; --el-menu-sub-item-height: 30px; --el-menu-active-color: var(--hm-primary-press); }
.vf-side-pop .el-menu-item, .vf-side-pop .el-sub-menu__title { border-radius: 5px; font-size: 13px; }
.vf-side-pop .el-menu-item.is-active { background: var(--hm-primary-soft); font-weight: 600; }
/* 4.7 Compact layout (1280×720 and up): no scoped; all selectors start with .shell */
html.compact .shell .top { gap: 6px; padding: 0 10px 0 12px; }
html.compact .shell .top .cmd { height: 30px; }
html.compact .shell .top .uname small { display: none; }
html.compact .shell > .side .brand { height: 44px; } html.compact .shell > .side .brand img { width: 24px; height: 24px; }
html.compact .shell > .side .el-menu { --el-menu-item-height: 32px; --el-menu-sub-item-height: 28px; }
html.compact .shell > .side .el-menu-item, html.compact .shell > .side .el-sub-menu__title { line-height: 32px; }
html.compact .shell > .side .grp { padding: 8px 10px 3px; }
html.compact .shell > .side .foot { padding: 5px 14px; font-size: 10px; }
html.compact .shell .main .crumbs { height: 28px; padding: 0 12px; }
</style>
