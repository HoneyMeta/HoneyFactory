// 4.7 Guided tours in the command palette (Ctrl+K): one "Guided Tour: <name>" command per tour. Availability depends on role and client (guideAvailable in guides.ts).
import { $t } from '../i18n';
import { GUIDES, guideAvailable, startGuide } from '../panels/teach/tour/guides';
import { registerCommands, type Command } from './registry';

registerCommands(GUIDES.map((g): Command => ({
  id: 'guide.' + g.key,
  title: $t('guides.guidedTour0', [g.title]),
  hint: $t('guides.n0Steps', [g.steps.length]),
  keywords: $t('guides.tourTutorialBeginnerGuideHow', [g.desc, g.kw || '']),
  group: $t('guides.guidedTour'),
  icon: g.task ? 'Flag' : 'Guide',
  when: () => guideAvailable(g),
  run: () => startGuide(g.key),
})));
