import { $t, lang } from './i18n';
import { ElMessage } from 'element-plus';
import { reactive } from 'vue';

export const session = reactive<{ token: string; user: any; plants: any[]; readonlyPid: string }>({ token: localStorage.getItem('vf_token') || '', user: null, plants: [], readonlyPid: '' });

export async function call(method: string, path: string, body?: any, quiet = false) {
  const r = await fetch(path, {
    method, headers: { 'Content-Type': 'application/json', 'X-Lang': lang, ...(session.token ? { Authorization: 'Bearer ' + session.token } : {}),
      // Desktop client (online mode): the local service routes requests locally or to the server based on the current page's factory (vfactory/desktop_proxy.py)
      ...(desk.on && curPid() ? { 'X-VF-Plant': curPid() } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401 && path !== '/api/login') {
    session.token = ''; localStorage.removeItem('vf_token');
    if (!location.pathname.startsWith('/login')) location.href = '/login?next=' + encodeURIComponent(location.pathname);
    throw new Error($t('rootApi.pleaseSignInFirst'));
  }
  if (!r.ok) {
    // Prefer the server's message (localized by X-Lang); otherwise (500, etc.) show a readable message instead of a bare status code
    const msg = typeof j.detail === 'string' ? j.detail
      : r.status >= 500 ? $t('rootApi.operationFailedServerError0', [r.status])
      : r.status === 404 ? $t('rootApi.theRequestedObjectWasNot') : r.status === 403 ? $t('rootApi.yourAccountDoesNotHave') : $t('common.operationFailed0', [r.status]);
    if (!quiet) ElMessage.error(msg);
    throw new Error(msg);
  }
  return j;
}
export const get = (p: string, quiet = false) => call('GET', p, undefined, quiet);
export const post = (p: string, b: any = {}) => call('POST', p, b);
export const put = (p: string, b: any) => call('PUT', p, b);
export const patch = (p: string, b: any) => call('PATCH', p, b);
export const del = (p: string) => call('DELETE', p);
export const P = (pid: string) => `/api/p/${encodeURIComponent(pid)}`;
/** Token for URLs the browser opens itself (`?token=${tok()}`); also carries the UI language (`&lang=`) since such requests can't send X-Lang. */
export const tok = () => encodeURIComponent(session.token) + '&lang=' + lang;
/** Current page's factory ID (Workbench and factory pages use /p/<pid>/...). */
const curPid = () => decodeURIComponent(location.pathname.match(/^\/p\/([^/]+)/)?.[1] || '');
/** Model editing and run control: admins/engineers; students and teachers can only edit sandboxes; teachers viewing student sandboxes are read-only.
 *  Students can freely edit their own "My Factories" in the desktop client (local factories local-…); the server rechecks ownership. */
export const canEdit = () => {
  const r = session.user?.role, pid = curPid();
  if (session.readonlyPid && pid === session.readonlyPid) return false;
  return ['admin', 'engineer'].includes(r) || (['student', 'teacher'].includes(r) && (pid.startsWith('sb-') || ownLocalPlant(pid)));
};
/** The user's local factories in the desktop client ("My Factories"): IDs start with local-. */
export const ownLocalPlant = (pid = curPid()) => desk.on && pid.startsWith('local-');
export const isAdmin = () => session.user?.role === 'admin';
export function download(path: string) {
  window.open(path + (path.includes('?') ? '&' : '?') + 'token=' + tok() + (desk.on && curPid() ? '&vfp=' + encodeURIComponent(curPid()) : ''));
}

/** Desktop client (desktop mode): /api/health returns desktop=true. on=false means a regular server web session; behavior is unchanged.
 *  mode: server = server account login (server factories proxied through the local service; local factories run locally); standalone = standalone (local admin); '' = not logged in. */
export const desk = reactive<{ checked: boolean; on: boolean; mode: string; server: string; online: boolean | null; version: string; protocols: boolean;
  quality: string; openPath: string; error: string; mustChangePw: boolean; native: boolean; mes: { state: string; pid: string; plant_name: string } | null;
  serverDeploy: string }>({
  checked: false, on: false, mode: '', server: '', online: null, version: '', protocols: false, quality: '', openPath: '', error: '', mustChangePw: false,
  serverDeploy: '',
  // Electron client (desktop/): provides window.vfNative (system dialogs, notifications, tray; see native.ts); unavailable in the old C# launcher + Edge window
  native: !!(window as any).vfNative?.isNative,
  mes: null,
});
const lsSet = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* */ } };
// Launcher one-time token (#dt=…): remove from the URL as soon as this module loads, before router initialization can write the token URL back
const pendingTicket = (() => {
  const m = location.hash.match(/(?:^#|&)dt=([^&]+)/);
  if (m) history.replaceState(history.state, '', location.pathname + location.search);
  return m ? decodeURIComponent(m[1]) : '';
})();
/** Local factories (factories running locally in the desktop client and local lesson sandboxes): local=true in the factory list. */
const whereCache = reactive<Record<string, boolean>>({});
export function isLocalPlant(pid: string) {
  if (!desk.on || !pid) return false;
  if (desk.mode === 'standalone') return true;
  const p = session.plants.find((x: any) => x.id === pid);
  if (p) return !!p.local;
  if (!(pid in whereCache)) {                      // For sandboxes and others not in the factory list: query the local service once
    whereCache[pid] = false;
    get(`/api/desktop/where/${encodeURIComponent(pid)}`, true).then((r) => { whereCache[pid] = !!r.local; }).catch(() => {});
  }
  return whereCache[pid];
}
/** 5.0: connected to SaaS cloud (no factories run on the server), either directly in a browser or through a logged-in desktop client. */
export function saasServer() {
  return desk.on ? desk.mode === 'server' && desk.serverDeploy === 'saas' : session.user?.deploy === 'saas';
}
/** 5.0: link to open a page in the desktop client (vfactory:// is handled by the installed client). */
export const clientLink = (path: string) => `vfactory://open?path=${encodeURIComponent(path)}`;
export function applyHealth(h: any) {
  Object.assign(desk, { mode: h.mode || '', server: h.server || '', online: h.online ?? null, version: h.version || desk.version,
    protocols: !!h.protocols, quality: h.quality || 'low', mes: h.mes || null, serverDeploy: h.server_deploy || '' });
  lsSet('vf_quality', desk.quality);                // 3D quality: read by scene.ts when creating the renderer
}
export async function refreshDesk() {
  try { applyHealth(await (await fetch('/api/health')).json()); } catch { /* */ }
}
/** Successful login (server account / standalone): local session issued by the local service. */
export function setDeskSession(j: any) {
  session.token = j.token; lsSet('vf_token', j.token); session.user = null;
  applyHealth(j); desk.mustChangePw = !!j.must_change_pw;
}

/** Call once on page load: check /api/health for desktop mode; if enabled, exchange the launcher's one-time token (#dt=…) for a session; enter directly if standalone mode or a remembered login (7 days)
 *  is still valid; otherwise go to login (desktop Login.vue: server address + account, or "Use standalone without a server").
 *  Launcher URL: http://127.0.0.1:<port>/[?open=<assignment-package-path>]#dt=<one-time-token>. Keep open in desk.openPath for the teaching module (.vfhw opened by double-click). */
export async function desktopBoot() {
  if (desk.checked) return desk.on;
  desk.checked = true;
  let h: any = {};
  try { h = await (await fetch('/api/health')).json(); } catch { return false; }
  if (!h.desktop) return false;
  desk.on = true;
  applyHealth(h);
  const qs = new URLSearchParams(location.search);
  if (qs.get('open')) desk.openPath = qs.get('open') || '';
  if (pendingTicket) {
    try {
      const r = await fetch('/api/desktop/session', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Lang': lang }, body: JSON.stringify({ token: pendingTicket }) });
      const j = await r.json().catch(() => ({}));
      if (r.ok && j.token) setDeskSession(j);
      else if (r.ok && j.need_login) { session.token = ''; localStorage.removeItem('vf_token'); }
      else if (!session.token) desk.error = j.detail || $t('rootApi.couldNotEstablishALocal');
    } catch { /* Use the previous session from local storage */ }
  } else if (!h.mode) { session.token = ''; localStorage.removeItem('vf_token'); }   // After logout: discard the previous session
  return true;
}

export async function loadSession() {
  if (!session.token) return false;
  try {
    session.user = await get('/api/me', true);
    session.plants = (await get('/api/overview', true)).plants;
    return true;
  } catch { return false; }
}

export function connect(pid: string, onState: (s: any) => void) {
  let ws: WebSocket | null = null, closed = false;
  const open = () => {
    ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/${encodeURIComponent(pid)}?token=${tok()}`);
    ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.type === 'state') onState(m.data); };
    ws.onclose = () => { if (!closed) setTimeout(open, 1500); };
  };
  open();
  return () => { closed = true; ws?.close(); };
}

export const fmt = (v: any, d = 2) => (v === null || v === undefined || v === '' ? '—' : typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 1 ? 4 : d)) : typeof v === 'boolean' ? (v ? $t('common.yes') : $t('common.no')) : String(v));
export const pct = (v: any, d = 1) => (v === null || v === undefined ? '—' : (v * 100).toFixed(d) + '%');
export function toast(m: string) { ElMessage.success(m); }
