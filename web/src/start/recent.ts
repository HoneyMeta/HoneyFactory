// Local start-page data: recent factories (with thumbnails), "Show welcome page on startup", and viewed versions. Stored in this computer's browser (localStorage).
// Thumbnails: capture the 3D view on leaving the Workbench, saving a draft, or closing the window (WebGL canvas uses preserveDrawingBuffer); save a floor-plan sketch if 3D is hidden.
import { reactive, watch } from 'vue';
import type { Router } from 'vue-router';
import { session } from '../api';
import { ed } from '../editor/store';
import { sketchFromModel, type Sketch } from './sketch';

const ls = {
  get(k: string) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k: string, v: string) { try { localStorage.setItem(k, v); return true; } catch { return false; } },
  del(k: string) { try { localStorage.removeItem(k); } catch { /* */ } },
};

// ---------- Show welcome page on startup ----------
export const startPrefs = reactive({ showWelcome: ls.get('vf_welcome_on_start') !== '0' });
watch(() => startPrefs.showWelcome, (v) => ls.set('vf_welcome_on_start', v ? '1' : '0'));
/** Destination after login/on launch: start page if "Show welcome page on startup" is enabled; otherwise use the default (students/teachers → Teaching, others → All Factories). */
export function homeFor(role = session.user?.role) {
  if (role === 'orgadmin') return '/org';                     // 5.0 Org admin: organization management page
  if (startPrefs.showWelcome) return '/welcome';
  return ['student', 'teacher'].includes(role) ? '/teach' : '/';
}

// ---------- Recent files ----------
export type RecentItem = { pid: string; name: string; t: number; view?: string; blocks?: number; sketch?: Sketch | null; thumb?: boolean };
const RKEY = 'vf_recent', TKEY = (pid: string) => 'vf_thumb:' + pid;
function read(): RecentItem[] { try { const v = JSON.parse(ls.get(RKEY) || '[]'); return Array.isArray(v) ? v.filter((x) => x && x.pid) : []; } catch { return []; } }
export const recent = reactive<{ items: RecentItem[]; tick: number }>({ items: read(), tick: 0 });
function save() {
  recent.items = recent.items.slice(0, 12);
  if (!ls.set(RKEY, JSON.stringify(recent.items))) {               // Storage full: remove the oldest thumbnail and retry
    const last = recent.items.pop(); if (last) ls.del(TKEY(last.pid));
    ls.set(RKEY, JSON.stringify(recent.items));
  }
  recent.tick++;
}
/** Exclude sandboxes (sb-…) from "Recently Opened": resume lessons via "Continue Last Lesson"; opening a dormant sandbox directly fails. */
const keepable = (pid: string) => !!pid && !pid.startsWith('sb-');
export function touchRecent(pid: string, patch: Partial<RecentItem> = {}) {
  if (!keepable(pid)) return;
  const old = recent.items.find((x) => x.pid === pid);
  const name = patch.name || session.plants.find((p: any) => p.id === pid)?.name || old?.name || pid;
  recent.items = [{ ...(old || {}), ...patch, pid, name, t: Date.now() } as RecentItem, ...recent.items.filter((x) => x.pid !== pid)];
  save();
}
export function forgetRecent(pid: string) { recent.items = recent.items.filter((x) => x.pid !== pid); ls.del(TKEY(pid)); save(); }
export const thumbOf = (pid: string) => { void recent.tick; return ls.get(TKEY(pid)) || ''; };

/** Capture a Workbench thumbnail (3D if visible; otherwise save only a floor-plan sketch). */
export function captureThumb(pid = ed.pid) {
  if (!keepable(pid) || ed.pid !== pid || !ed.model) return;
  const sketch = sketchFromModel(ed.model);
  let thumb = false;
  try {
    const cv = document.querySelector<HTMLCanvasElement>('.vp-a canvas');
    const shown = cv && cv.offsetWidth > 40 && cv.offsetHeight > 40 && (ed.view === '3d' || ed.split);
    if (cv && shown && cv.width > 0) {
      const W = 360, H = 202, c = document.createElement('canvas');
      c.width = W; c.height = H;
      const g = c.getContext('2d')!;
      const r = Math.max(W / cv.width, H / cv.height), sw = W / r, sh = H / r;      // Center-crop to 16:9
      g.drawImage(cv, (cv.width - sw) / 2, (cv.height - sh) / 2, sw, sh, 0, 0, W, H);
      const px = g.getImageData(W / 2 - 20, H / 2 - 20, 40, 40).data;               // Discard fully black/transparent captures (not rendered yet)
      let lit = 0; for (let i = 0; i < px.length; i += 16) if (px[i + 3] > 0 && px[i] + px[i + 1] + px[i + 2] > 30) lit++;
      if (lit > 10) { thumb = ls.set(TKEY(pid), c.toDataURL('image/jpeg', 0.72)); }
    }
  } catch { /* Cross-origin/context lost: save only the sketch */ }
  touchRecent(pid, { name: ed.model.plant?.name, view: ed.view, blocks: (ed.model.blocks || []).length, sketch, ...(thumb ? { thumb: true } : {}) });
}

let installed = false;
/** Install once in App.vue: record "Recently Opened" on entering the Workbench; capture thumbnails on leaving, after saving, and on window close. */
export function installRecent(router: Router) {
  if (installed) return; installed = true;
  const isWb = (p: string) => /^\/p\/[^/]+\/workbench/.test(p);
  router.beforeEach((to, from) => { if (isWb(from.path) && from.params.pid) captureThumb(String(from.params.pid)); return true; });
  router.afterEach((to) => { if (isWb(to.path) && to.params.pid) touchRecent(String(to.params.pid)); });
  let t: any;
  watch(() => ed.savedAt, (v) => { if (v && ed.pid) { clearTimeout(t); t = setTimeout(() => captureThumb(ed.pid), 1200); } });
  // Also capture after the initial 3D render so newly opened factories get a thumbnail immediately
  watch(() => !!ed.runtime && !!ed.model, (v) => { if (v) { clearTimeout(t); const pid = ed.pid; t = setTimeout(() => captureThumb(pid), 6000); } });
  addEventListener('beforeunload', () => { if (isWb(location.pathname) && ed.pid) captureThumb(ed.pid); });
  addEventListener('pagehide', () => { if (isWb(location.pathname) && ed.pid) captureThumb(ed.pid); });
}

// ---------- Viewed versions ("What's New") ----------
export const seenVersion = { get: () => ls.get('vf_seen_version') || '', set: (v: string) => ls.set('vf_seen_version', v) };
