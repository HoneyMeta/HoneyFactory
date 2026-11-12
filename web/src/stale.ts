// 4.6.2 Pages left open after a release: the backend rebuilds web/dist, renaming files before old pages lazy-load panels (Outliner-xxx.js, Library-xxx.js …).
// The browser reports "Failed to fetch dynamically imported module", leaving panels blank. Catch these errors centrally, show "Updated to a new version. Refreshing…", and reload once.
// Prevent reload loops: record the reload time in sessionStorage. If it fails again within 1 min (e.g. offline or server down), prompt students to refresh manually instead.
// Sources: Vite's vite:preloadError (dependency preload/module load failure), lazy-loaded routes (router.onError), defineAsyncComponent panels (app.config.errorHandler),
// and uncaught await import(...) calls (unhandledrejection). The desktop client (Electron) uses the shell's reload (reopens the current page with a new single-use token).
import { $t } from './i18n';
import type { App } from 'vue';
import type { Router } from 'vue-router';

declare const __VF_BUILD_TAG__: string;           // Defined via vite.config.ts define (normally empty)
const KEY = 'vf_stale_reload';
const LOOP_MS = 60_000;
let pending = false;

/** Check for lazy-loaded file fetch errors (wording varies by browser). */
export function isChunkError(e: any): boolean {
  const m = String(e?.message || e || '');
  return /Failed to fetch dynamically imported module|error loading dynamically imported module|Importing a module script failed|Unable to preload CSS|Loading (CSS )?chunk .* failed|dynamically imported module/i.test(m);
}

function notice(text: string, bad = false) {
  try {
    let el = document.getElementById('vf-stale-note');
    if (!el) {
      el = document.createElement('div');
      el.id = 'vf-stale-note';
      el.setAttribute('role', 'status');
      el.dataset.k = 'stale-note';
      el.style.cssText = 'position:fixed;left:50%;top:14px;transform:translateX(-50%);z-index:5000;padding:8px 16px;border-radius:var(--hm-r-md, 8px);font-size:13px;'
        + 'box-shadow:var(--hm-e3);pointer-events:none;font-family:inherit;';
      document.body.appendChild(el);
    }
    el.style.background = bad ? 'var(--hm-fault-soft)' : 'var(--hm-primary-soft)';
    el.style.color = bad ? 'var(--hm-fault-ink)' : 'var(--hm-setup-ink)';
    el.style.border = '1px solid ' + (bad ? 'var(--hm-fault)' : 'var(--hm-primary-soft-2)');
    el.dataset.bad = bad ? '1' : '0';
    el.textContent = text;
  } catch { /* Page not ready yet */ }
}

/** Reload once (at most once per minute). Return whether a reload will actually occur. */
export function staleReload(reason?: any): boolean {
  if (pending) return true;
  let last = 0;
  try { last = Number(sessionStorage.getItem(KEY) || 0); } catch { /* Private browsing mode */ }
  if (Date.now() - last < LOOP_MS) {
    notice($t('stale.pageFilesFailedToLoad'), true);
    console.warn($t('stale.vfOnDemandLoadingFailed'), reason);
    return false;
  }
  pending = true;
  try { sessionStorage.setItem(KEY, String(Date.now())); } catch { /* */ }
  notice($t('stale.updatedToTheNewVersion'));
  console.info($t('stale.vfPageFilesHaveBeen'), reason);
  setTimeout(() => {
    const n = (window as any).vfNative;
    if (n?.reload) { try { n.reload(); return; } catch { /* Legacy shell */ } }
    location.reload();
  }, 900);
  return true;
}

export function installStaleGuard(app: App, router: Router) {
  // Do not call preventDefault: let errors propagate to the route/async component/unhandled Promise handlers below, avoiding confusing errors from lazy loads returning undefined
  window.addEventListener('vite:preloadError', (e: any) => { staleReload(e.payload); });
  window.addEventListener('unhandledrejection', (e) => { if (isChunkError(e.reason) && staleReload(e.reason)) e.preventDefault(); });
  router.onError((err) => { if (isChunkError(err)) staleReload(err); });
  const prev = app.config.errorHandler;
  app.config.errorHandler = (err, inst, info) => {
    if (isChunkError(err) && staleReload(err)) return;
    if (prev) prev(err, inst, info); else console.error(err);
  };
  (window as any).__vfStale = { staleReload, isChunkError, tag: typeof __VF_BUILD_TAG__ === 'string' ? __VF_BUILD_TAG__ : '' };     // For UI tests
}
