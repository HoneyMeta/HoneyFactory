// 5.0.1: Light theme only (same design system as HoneyMOM; see design/README.md). Dark theme, toggle buttons, and commands removed.
// Silently migrate saved theme preferences (localStorage vf_theme = dark and embedded MES mes_theme) to light: delete stored values and remove <html class="dark">.
const OLD_KEYS = ['vf_theme', 'mes_theme'];
try { for (const k of OLD_KEYS) if (localStorage.getItem(k) !== null) localStorage.removeItem(k); } catch { /* Private browsing mode */ }
if (typeof document !== 'undefined') document.documentElement.classList.remove('dark');
export const LIGHT_ONLY = true;
