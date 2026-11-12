// UI language (vue-i18n). Same setup as HoneyMOM (web/src/i18n/index.ts there):
// - Default: a stored choice (localStorage vf_lang, or ?lang=en|zh-CN on any page URL, which is stored), else the browser language
//   (zh* -> zh-CN, otherwise English).
// - Messages live in ../locales/{en,zh-CN}.json, namespaced per page/component ("workbench.runToHere").
// - Placeholders are positional: "{0} pcs" -> $t(key, [n]). Named templates such as ECharts' "{b}: {c}" pass through untouched.
// - Switching language stores the choice and reloads the page, so module-level labels (menus, enums, command lists) are rebuilt.
// - Every same-origin request carries the UI language: fetch() gets an X-Lang header (installed here, once), URLs the browser
//   opens itself (downloads, window.open, WebSocket, <img src>) get &lang= through withLang() / tok() in ../api.ts.
import { createI18n } from 'vue-i18n';
import elEn from 'element-plus/es/locale/lang/en';
import elZhCn from 'element-plus/es/locale/lang/zh-cn';
import en from '../locales/en.json';
import zhCN from '../locales/zh-CN.json';

export type Lang = 'en' | 'zh-CN';
export const LANG_KEY = 'vf_lang';
/** Language names are shown in their own language. */
export const LANGS: { code: Lang; label: string; short: string }[] = [
  { code: 'en', label: 'English', short: 'EN' },
  { code: 'zh-CN', label: '\u4e2d\u6587', short: '\u4e2d' },
];

function norm(v: string | null | undefined): Lang | '' {
  if (!v) return '';
  if (v === 'en' || v.toLowerCase().startsWith('en')) return 'en';
  if (v.toLowerCase().startsWith('zh')) return 'zh-CN';
  return '';
}

function initial(): Lang {
  try {
    const q = norm(new URLSearchParams(location.search).get('lang'));
    if (q) localStorage.setItem(LANG_KEY, q);
    const v = q || norm(localStorage.getItem(LANG_KEY));
    if (v) return v;
  } catch { /* storage blocked */ }
  // No stored choice: follow the browser language (Chinese browsers get zh-CN), else English.
  try {
    const nav = (navigator.languages && navigator.languages[0]) || navigator.language || '';
    if (nav.toLowerCase().startsWith('zh')) return 'zh-CN';
  } catch { /* no navigator */ }
  return 'en';
}

export const lang: Lang = initial();
export const isZh = lang === 'zh-CN';
/** BCP-47 tag for Intl / toLocaleString. */
export const intlLocale = isZh ? 'zh-CN' : 'en-US';
/** Element Plus locale for app.use(ElementPlus, { locale: elLocale }). */
export const elLocale = isZh ? elZhCn : elEn;

// Minimal message format: {0} / {name} are replaced when a value is given, everything else is literal
// (so "@", "|", "{b}" and HTML need no escaping in the locale files).
function compile(msg: any) {
  const s = typeof msg === 'string' ? msg : String(msg ?? '');
  return (ctx: any) => s.replace(/\{(\w+)\}/g, (m: string, k: string) => {
    const v = /^\d+$/.test(k) ? ctx.list(Number(k)) : ctx.named(k);
    return v === undefined || v === null ? m : String(v);
  });
}

export const i18n = createI18n({
  legacy: false,
  globalInjection: true,
  locale: lang,
  fallbackLocale: 'en',
  messages: { en, 'zh-CN': zhCN } as any,
  messageCompiler: compile as any,
  missingWarn: false,
  fallbackWarn: false,
  warnHtmlMessage: false,
});

const gt = i18n.global.t as any;
/** Translate in scripts (templates use the global $t). */
export function $t(key: string, list?: unknown[]): string {
  return list ? gt(key, list) : gt(key);
}

/** Pick the text for the UI language: tr('Run', '\u8fd0\u884c'). For the rare case where a catalogue key is overkill. */
export const tr = (enText: string, zhText: string) => (isZh ? zhText : enText);

/** Text of a catalogue key in a given language (no fallback). */
export function textIn(l: Lang, key: string): string {
  const i = key.indexOf('.');
  const cat: any = l === 'en' ? en : zhCN;
  return cat?.[key.slice(0, i)]?.[key.slice(i + 1)] ?? '';
}
/** Both language texts of a catalogue key: for backend texts that may arrive in either language (status words, categories). */
export const variants = (key: string): string[] => [...new Set([textIn('en', key), textIn('zh-CN', key)].filter(Boolean))];
/** Does a backend text equal the key's text in either language? */
export const matches = (v: unknown, key: string) => v !== undefined && v !== null && variants(key).includes(String(v));
/** Show a backend enum text in the UI language when it is one of the known keys' texts (either language); otherwise unchanged. */
export function localize(v: unknown, keys: string[]): string {
  const s = String(v ?? '');
  for (const k of keys) if (matches(s, k)) return $t(k);
  return s;
}

/** Store the choice and reload (module-level labels are built at import time). Drops ?lang= from the URL so it doesn't override. */
export function setLang(l: Lang) {
  try { localStorage.setItem(LANG_KEY, l); } catch { /* ignore */ }
  const u = new URL(location.href);
  if (u.searchParams.has('lang')) { u.searchParams.delete('lang'); location.replace(u.toString()); } else location.reload();
}

/** Append lang=<ui language> to a same-origin URL the browser opens itself (download, window.open, WebSocket, img src). */
export function withLang(url: string): string {
  if (/[?&]lang=/.test(url)) return url;
  const i = url.indexOf('#');
  const base = i < 0 ? url : url.slice(0, i), hash = i < 0 ? '' : url.slice(i);
  return base + (base.includes('?') ? '&' : '?') + 'lang=' + encodeURIComponent(lang) + hash;
}

/** True when the text contains CJK characters (by char code; no CJK literals in code). */
export function hasCjk(s: string): boolean {
  for (let i = 0; i < s.length; i++) {
    const c = s.charCodeAt(i);
    if ((c >= 0x3000 && c <= 0x303f) || (c >= 0x3400 && c <= 0x4dbf) || (c >= 0x4e00 && c <= 0x9fff) || (c >= 0xf900 && c <= 0xfaff) || (c >= 0xff00 && c <= 0xffef)) return true;
  }
  return false;
}

// Every same-origin fetch carries X-Lang (the backend picks the language of messages, labels, exports and AI answers from it).
// Done once here so no call site can forget it (api.ts, mes/api.ts, panels, raw fetches for exports / packages / SSE streams).
function sameOrigin(u: string): boolean {
  if (/^(blob|data):/i.test(u)) return false;
  try { return new URL(u, location.href).origin === location.origin; } catch { return false; }
}
try {
  const w = window as any;
  if (!w.__vfLangFetch && typeof w.fetch === 'function') {
    const orig = w.fetch.bind(w);
    w.__vfLangFetch = true;
    w.fetch = (input: any, init?: RequestInit) => {
      try {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input?.url || '';
        if (sameOrigin(url)) {
          if (typeof Request !== 'undefined' && input instanceof Request && !init) {
            if (!input.headers.has('X-Lang')) { const h = new Headers(input.headers); h.set('X-Lang', lang); return orig(new Request(input, { headers: h })); }
          } else {
            const h = new Headers(init?.headers || (input instanceof Request ? input.headers : undefined));
            if (!h.has('X-Lang')) h.set('X-Lang', lang);
            return orig(input, { ...(init || {}), headers: h });
          }
        }
      } catch { /* fall through */ }
      return orig(input, init);
    };
  }
} catch { /* no window (tests) */ }

try { document.documentElement.lang = lang; } catch { /* ssr / tests */ }
