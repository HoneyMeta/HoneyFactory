// Guided tutorials under "Learn" on the start page. Two defaults (first PLC lesson and first line lesson); teaching modules can register their own step-by-step guides:
//   import { registerTutorial } from '../../start/tutorials'
//   registerTutorial({ id: 'guided-plc-1', title: 'Follow Along: Motor Start/Stop Seal-In', desc: '…', icon: 'Cpu', roles: ['student'], run: () => … })
// Without run, open the course/lesson (students: the lesson published to their class; teachers: course library; others: course description in Help).
import { $t } from '../i18n';
import { reactive } from 'vue';

export type Tutorial = { id: string; title: string; desc?: string; icon?: string; course?: string; lesson?: string; help?: string; roles?: string[]; badge?: string; run?: () => any; order?: number };

export const tutorials = reactive<Tutorial[]>([
  { id: 'plc-first', order: 10, title: $t('tutorials.plcLesson1MotorStart'), desc: $t('tutorials.writeYourFirstLadderDiagram'), icon: 'Cpu', course: 'plc_basics', lesson: 's01', help: 'plc', badge: $t('tutorials.plcControlBasics') },
  { id: 'plc-next', order: 11, title: $t('tutorials.plcForwardReverseInterlockAnd'), desc: $t('tutorials.buildOnTheFirstLesson'), icon: 'Switch', course: 'plc_basics', lesson: 's02', help: 'plc', badge: $t('tutorials.plcControlBasics') },
  { id: 'line-first', order: 20, title: $t('tutorials.productionLineLessonSingleMachine'), desc: $t('tutorials.startWithOneMachineTool'), icon: 'DataLine', course: 'machining', lesson: 'm01', help: 'course', badge: $t('tutorials.productionLineSimulationOptimization') },
]);

export function registerTutorial(t: Tutorial) {
  const i = tutorials.findIndex((x) => x.id === t.id);
  if (i >= 0) tutorials.splice(i, 1, t); else tutorials.push(t);
  tutorials.sort((a, b) => (a.order ?? 50) - (b.order ?? 50));
  return () => { const j = tutorials.findIndex((x) => x === t); if (j >= 0) tutorials.splice(j, 1); };
}
