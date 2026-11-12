// 4.7 Compact layout: supports 1280×720 minimum. Enabled automatically when height < 800 or width < 1366 (<html class="compact">),
// Override in settings with "Always Compact / Always Standard" (localStorage vf_compact = on / off; unset = auto).
// Compact mode: smaller spacing and fonts, overflow buttons in the Workbench's second row move to "More", collapsible right sidebar, hideable timeline (html.compact rules in style.css / editor.css).
import { $t } from './i18n';
import { reactive } from 'vue';

export type CompactPref = 'auto' | 'on' | 'off';
export const density = reactive({ pref: 'auto' as CompactPref, on: false, auto: false });
export const COMPACT_W = 1366, COMPACT_H = 800;
export const PREF_CN: Record<CompactPref, string> = { auto: $t('compact.autoCompactWhenWindowIs'), on: $t('common.alwaysCompact'), off: $t('common.alwaysStandard') };

function readPref(): CompactPref {
  try { const v = localStorage.getItem('vf_compact'); return v === 'on' || v === 'off' ? v : 'auto'; } catch { return 'auto'; }
}
export function applyCompact() {
  density.pref = readPref();
  density.auto = innerHeight < COMPACT_H || innerWidth < COMPACT_W;
  density.on = density.pref === 'on' || (density.pref === 'auto' && density.auto);
  document.documentElement.classList.toggle('compact', density.on);
}
export function setCompact(p: CompactPref) {
  try { if (p === 'auto') localStorage.removeItem('vf_compact'); else localStorage.setItem('vf_compact', p); } catch { /* Private browsing mode */ }
  applyCompact();
}
let t: any = 0;
addEventListener('resize', () => { clearTimeout(t); t = setTimeout(applyCompact, 120); });
addEventListener('storage', (e) => { if (e.key === 'vf_compact') applyCompact(); });     // Settings changed in another window
applyCompact();
(window as any).__vfDensity = density;   // For UI tests
