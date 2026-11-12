// window.vfNative from the Electron client's preload script (desktop/): system dialogs, notifications, tray/jump list navigation, and file double-clicks.
// Unavailable in the web app and legacy C# launcher; these functions are no-ops there, preserving existing behavior.
import type { Router } from 'vue-router';
import { call, desk, session } from './api';

export interface VfNative {
  isNative: true;
  getAppInfo(): Promise<any>;
  openFileDialog(o?: { title?: string; filters?: { name: string; extensions: string[] }[]; multi?: boolean }): Promise<string[]>;
  saveFileDialog(o: { defaultName: string; filters?: { name: string; extensions: string[] }[]; data?: Uint8Array | ArrayBuffer }): Promise<string | null>;
  notify(title: string, body: string): Promise<boolean>;
  closeBehaviour: { get(): Promise<string>; set(v: 'ask' | 'tray' | 'quit'): Promise<string> };
  openLogFolder(): Promise<string>;
  checkForUpdates(): Promise<{ status: string; version?: string; message: string }>;
  setBadge(n: number): Promise<boolean>;
  refresh(): void;
  /** 4.6.2: reopen the current page with a fresh one-time token; unavailable in the legacy shell */
  reload?(): void;
  onDeepLink(cb: (l: { action: string; file?: string; plant?: string; path?: string; url: string }) => void): () => void;
  onOpenFile(cb: (path: string) => void): () => void;
  onNavigate(cb: (path: string) => void): () => void;
}

export const native: VfNative | null = (typeof window !== 'undefined' && (window as any).vfNative?.isNative) ? (window as any).vfNative : null;

/** Open files (double-click .vfhw / .vfplant, drop onto the icon, vfactory://open?file=): reuse ?open=<path> handling via PackageOpen on the Teaching page. */
function openPath(router: Router, p: string) {
  desk.openPath = p;
  router.push({ path: '/teach', query: { open: p } });
}

let installed = false;
export function installNative(router: Router) {
  if (!native || installed) return;
  installed = true;
  native.onOpenFile((p) => openPath(router, p));
  native.onNavigate((p) => { if (typeof p === 'string' && p.startsWith('/')) router.push(p); });
  native.onDeepLink((l) => {
    if (l.file) openPath(router, l.file);
    else if (l.plant) router.push(`/p/${encodeURIComponent(l.plant)}/workbench`);
    else if (l.path && l.path.startsWith('/')) router.push(l.path);
  });
  // On entering a factory, add it to recent factories (tray menu, taskbar jump list)
  let last = '';
  router.afterEach((to) => {
    const pid = String(to.params.pid || '');
    if (!desk.on || !session.token || !pid || pid.startsWith('sb-') || pid === last) return;
    last = pid;
    const name = session.plants.find((x: any) => x.id === pid)?.name || pid;
    call('POST', '/api/desktop/recent', { pid, name }, true).then(() => native.refresh()).catch(() => {});
  });
}
