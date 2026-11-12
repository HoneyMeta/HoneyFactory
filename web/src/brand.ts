// Brand assets (delivered to web/public/brand/* and listed in web/public/brand/manifest.json).
// Pages use only files listed in the manifest; use neutral placeholders (gradients / icons / existing text) for missing assets, keeping paths and usage unchanged.
import { $t } from './i18n';
import { reactive } from 'vue';

// Light theme only since 5.0.1: use light assets only (-dark variants are no longer used)
export const brand = reactive<{ loaded: boolean; files: Set<string> }>({ loaded: false, files: new Set() });

/** Collect all .png/.svg/.jpg/.webp filenames from the manifest (supports ["a.png"], {files:[…]}, {"a.png":{…}}, [{file:"a.png"}], etc.). */
function collect(x: any, out: Set<string>) {
  if (typeof x === 'string') { const m = x.match(/^\/brand\/([\w.@-]+\.(?:png|svg|jpe?g|webp|ico))$/i) || x.match(/^([\w.@-]+\.(?:png|svg|jpe?g|webp|ico))$/i); if (m) out.add(m[1].toLowerCase()); return; }
  if (Array.isArray(x)) { x.forEach((v) => collect(v, out)); return; }
  if (x && typeof x === 'object') for (const [k, v] of Object.entries(x)) { collect(k, out); collect(v, out); }
}
let loading: Promise<void> | null = null;
export function loadBrand() {
  loading ||= fetch('/brand/manifest.json', { cache: 'no-cache' })
    .then((r) => (r.ok && /json/.test(r.headers.get('content-type') || '') ? r.json() : null))
    .then((j) => { const s = new Set<string>(); if (j) collect(j, s); brand.files = s; })
    .catch(() => { /* No manifest: use placeholders throughout */ })
    .finally(() => { brand.loaded = true; applyFavicon(); });
  return loading;
}
/** Asset URL if delivered, otherwise ''. name excludes directories, e.g. 'welcome-hero.png'. */
export const brandUrl = (name: string) => (brand.files.has(name.toLowerCase()) ? '/brand/' + name : '');
/** First available asset: e.g. fall back to empty-generic.png if empty-plants.png is missing. */
export const firstBrand = (...names: string[]) => names.map(brandUrl).find(Boolean) || '';

/** Illustration (light variant): base has no extension (e.g. 'empty-search'); provide srcset if @2x (.webp or .png) exists. */
export function themed(base: string): { src: string; srcset: string } {
  const src = firstBrand(base + '.png', base + '.webp', base + '.jpg');
  if (!src) return { src: '', srcset: '' };
  const x2 = firstBrand(base + '@2x.webp', base + '@2x.png');
  return { src, srcset: x2 ? `${src} 1x, ${x2} 2x` : '' };
}

/** Logo for light backgrounds (logo-light); fall back to the original /logo.png. */
export const logoFor = () => firstBrand('logo-light.png', 'logo-dark.png') || '/logo.png';
export const markUrl = () => firstBrand('logo-mark-64.png', 'logo-mark-128.png', 'logo-mark.png', 'logo-mark-32.png') || '/logo.png';

/** index.html already references /brand/favicon.ico + favicon.png; fall back to /logo.png only if they are absent from the manifest. */
function applyFavicon() {
  if (firstBrand('favicon.png', 'favicon.ico')) return;
  const l = document.querySelector<HTMLLinkElement>('link[rel="icon"][type="image/png"]') || document.querySelector<HTMLLinkElement>('link[rel="icon"]');
  if (l) l.href = '/logo.png';
}

/** Page title: HoneyFactory · <page>. */
export function setTitle(page = '') { document.title = page ? $t('brand.honeyfactory0', [page]) : $t('common.honeyfactory'); }
