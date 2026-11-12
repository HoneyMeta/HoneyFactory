import { $t } from './i18n';
// User-facing What's New content, without implementation details. Shown on first launch after an upgrade: if the /api/health version is newer than the locally stored "last seen version",
// list entries for all intervening versions (components/WhatsNew.vue). Also accessible anytime from "Resources" on the start page and the Help menu.
// Add a version: prepend { version: '4.6', date, title, items }; each item is one sentence, optionally with help (Help Center section id).
export type WhatsNewItem = { text: string; help?: string; tag?: string };
export type WhatsNewEntry = { version: string; date: string; title: string; items: WhatsNewItem[] };

export const WHATS_NEW: WhatsNewEntry[] = [
  {
    version: '4.5', date: '2026-11', title: $t('whatsnew.anImprovedStartPageCommand'),
    items: [
      { tag: $t('common.startPage'), text: $t('whatsnew.afterSigningInYouLl'), help: 'welcome' },
      { tag: $t('common.startPage'), text: $t('whatsnew.studentsCanSeeResumeLast'), help: 'welcome' },
      { tag: $t('common.commandPalette'), text: $t('whatsnew.pressCtrlKOnAny'), help: 'welcome' },
      { tag: $t('common.help'), text: $t('whatsnew.pressF1ToOpenHelp'), help: 'welcome' },
      { tag: $t('whatsnew.appearance'), text: $t('whatsnew.newBrandLogoIllustrationsAnd') },
      { tag: $t('common.desktopClient'), text: $t('whatsnew.theDesktopClientNowRuns'), help: 'client' },
      { tag: $t('common.courses'), text: $t('whatsnew.introductoryPlcAndProductionLine'), help: 'course' },
    ],
  },
  {
    version: '4.4', date: '2026-11', title: $t('whatsnew.myFactoriesAndDarkMode'),
    items: [
      { tag: $t('common.desktopClient'), text: $t('whatsnew.studentsNowHaveMyFactories'), help: 'client' },
      { tag: $t('common.working'), text: $t('whatsnew.teachersCanAssignSubmitA'), help: 'teach' },
      { tag: $t('whatsnew.appearance'), text: $t('whatsnew.theTeachingAndMyFactories') },
      { tag: $t('common.username'), text: $t('whatsnew.youMustChangeYourInitial'), help: 'account' },
    ],
  },
  {
    version: '4.3', date: '2026-11', title: $t('whatsnew.realWorldFactoryLayersPlcs'),
    items: [
      { tag: $t('whatsnew.modeling'), text: $t('whatsnew.plcsAreNowStandaloneDevices'), help: 'plc' },
      { tag: $t('whatsnew.modeling'), text: $t('whatsnew.industrialGatewaysSwitchesScadaAnd'), help: 'layers' },
      { tag: $t('searchDialog.find'), text: $t('whatsnew.pressCtrlFToFind'), help: 'layers' },
      { tag: $t('common.attribute'), text: $t('whatsnew.thePropertiesPanelDefaultsTo'), help: 'layers' },
    ],
  },
];

const parts = (v: string) => String(v || '').replace(/^v/i, '').split(/[.\-+]/).map((x) => parseInt(x, 10) || 0);
/** Return a negative value if a < b. Compare only the first two segments (4.5.1 and 4.5 share What's New entries). */
export function cmpVer(a: string, b: string, n = 2) {
  const x = parts(a), y = parts(b);
  for (let i = 0; i < n; i++) { const d = (x[i] || 0) - (y[i] || 0); if (d) return d; }
  return 0;
}
/** New entries after seen, up to and including current (empty seen = fresh install: do not show). */
export function entriesBetween(seen: string, current: string) {
  return WHATS_NEW.filter((e) => cmpVer(e.version, current) <= 0 && (!seen || cmpVer(e.version, seen) > 0));
}
