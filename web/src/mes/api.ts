// Data APIs for Teaching MES pages (integrated into the HoneyFactory UI in 5.0.1, under /mes/...).
// Pages keep MES API paths ('/api/e/work_order'); rewrite them here to the local service proxy '/api/mes/e/work_order'
// (mes_proxy in vfactory/mes/sidecar.py forwards the local student's MES session to local MES). The browser uses only the HoneyFactory login token, with no access to MES keys or sessions.
import { $t, lang } from '../i18n';
import { ElMessage } from 'element-plus';
import { reactive } from 'vue';
import { session as vf } from '../api';

/** Local MES status (/api/desktop/mes) + local student info in MES (/api/mes/me, /api/mes/meta). Shared across all MES pages. */
export const mes = reactive<{
  st: any; loaded: boolean; failed: boolean; starting: string; manualStop: boolean; picking: boolean;
  user: any; meta: any; sessionKey: string; now: string;
}>({ st: null, loaded: false, failed: false, starting: '', manualStop: false, picking: false, user: null, meta: null, sessionKey: '', now: '' });

export const running = () => mes.st?.state === 'running';
/** MES API path → local service proxy path */
export const M = (p: string) => (p.startsWith('/api/mes/') ? p : p.startsWith('/api/') ? '/api/mes/' + p.slice(5) : p);

export async function call(method: string, path: string, body?: any, quiet = false) {
  const r = await fetch(M(path), {
    method, headers: { 'Content-Type': 'application/json', 'X-Lang': lang, ...(vf.token ? { Authorization: 'Bearer ' + vf.token } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) {                          // HoneyFactory login expired (the local service does not pass through MES 401 responses)
    vf.token = ''; try { localStorage.removeItem('vf_token'); } catch { /* */ }
    if (!location.pathname.startsWith('/login')) location.href = '/login?next=' + encodeURIComponent(location.pathname);
    throw new Error($t('rootApi.pleaseSignInFirst'));
  }
  if (r.status === 503 && j.mes_state) {
    // MES stopped (idle timeout, Stop clicked, or stopped elsewhere): show "Stopped" in the shell and unmount the page. Leave this request pending (no error toast or unhandled rejection).
    if (mes.st && mes.st.state === 'running') mes.st = { ...mes.st, state: j.mes_state === 'running' ? 'stopped' : j.mes_state };
    return new Promise<any>(() => { /* Never resolves */ });
  }
  if (!r.ok) {
    const msg = typeof j.detail === 'string' ? j.detail
      : r.status >= 500 ? $t('mesApi.operationFailedMesError0', [r.status]) : r.status === 404 ? $t('rootApi.theRequestedObjectWasNot') : $t('common.operationFailed0', [r.status]);
    if (!quiet) ElMessage.error(msg);
    throw new Error(msg);
  }
  return j;
}
export const get = (p: string, quiet = false) => call('GET', p, undefined, quiet);
export const post = (p: string, b: any = {}) => call('POST', p, b);
export const put = (p: string, b: any) => call('PUT', p, b);
export const del = (p: string) => call('DELETE', p);
/** Download / print (new window): pass the HoneyFactory login token in ?token= (as with other HoneyFactory downloads); strip it when proxying through the local service. */
export function openFile(path: string) {
  const u = M(path);
  window.open(u + (u.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(vf.token) + '&lang=' + lang);
}

/** Local student info and entity metadata in MES (refetch after MES starts or the factory changes). */
export async function loadMesSession(force = false) {
  const key = `${mes.st?.pid}:${mes.st?.started}`;
  if (!force && mes.user && mes.meta && mes.sessionKey === key) return true;
  try {
    // Requests stay pending if MES just stopped (see call's 503 handling); wait at most 20 seconds here
    const late = new Promise<never>((_r, rej) => setTimeout(() => rej(new Error('timeout')), 20000));
    const [u, m] = await Promise.race([Promise.all([get('/api/me', true), get('/api/meta', true)]), late]);
    Object.assign(mes, { user: u, meta: m, sessionKey: key });
    return true;
  } catch { return false; }
}

export function ent(name: string) { return mes.meta?.entities.find((e: any) => e.name === name); }
export function canWrite(module: string) { return !!mes.user?.writable?.includes(module); }
export const fmt = (v: any, d = 1) => (v === null || v === undefined || v === '' ? '—' : typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(d)) : String(v));
export const pct = (v: any, d = 1) => (v === null || v === undefined ? '—' : (v * 100).toFixed(d) + '%');
