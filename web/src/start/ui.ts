// Global dialog/drawer toggles (mounted once in App.vue, accessible from any page or the Command Palette): What's New, keyboard shortcuts, F1 Help drawer.
import { reactive } from 'vue';
import { entriesBetween, WHATS_NEW, type WhatsNewEntry } from '../whatsnew';
import { seenVersion } from './recent';

export const ui = reactive({
  whatsNew: false, whatsNewEntries: [] as WhatsNewEntry[], whatsNewAuto: false,
  shortcuts: false,
  help: { open: false, id: '', from: '' },
  version: '',
});

export function openWhatsNew() { ui.whatsNewEntries = WHATS_NEW; ui.whatsNewAuto = false; ui.whatsNew = true; }
export function openShortcuts() { ui.shortcuts = true; }
export function openHelp(id = '', from = '') { ui.help.id = id; ui.help.from = from; ui.help.open = true; }

/** Read the server version (/api/health); show What's New if newer than the locally stored "last seen version". On first use (no stored version), store it without showing. */
let checked = false;
export async function checkWhatsNew() {
  if (checked) return; checked = true;
  try { ui.version = (await (await fetch('/api/health')).json()).version || ''; } catch { return; }
  if (!ui.version) return;
  const seen = seenVersion.get();
  if (!seen) { seenVersion.set(ui.version); return; }
  const list = entriesBetween(seen, ui.version);
  if (list.length) { ui.whatsNewEntries = list; ui.whatsNewAuto = true; ui.whatsNew = true; }
  else seenVersion.set(ui.version);
}
export function closeWhatsNew() { ui.whatsNew = false; if (ui.version) seenVersion.set(ui.version); }
