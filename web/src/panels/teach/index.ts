// Teaching panel registration (auto-loaded by the shell at web/src/editor/shell/panels.ts).
// roles: suggested visibility filter for the shell (omitted = everyone); components also explain access restrictions without throwing errors.
import { $t } from '../../i18n';
import { defineAsyncComponent } from 'vue';
import './tour/tour';            // 4.5 Guided tutorials: resume the last step after refresh or entering the Workbench
import { registerTutorial } from '../../start/tutorials';

// 4.5: List lessons with guided tutorials under "Learn" on the start page (steps in vfactory/teach/tours/). Open a lesson, then click "Start This Lesson" → "Follow the Tutorial".
const GUIDE = $t('teachIndex.stepByStepGuidanceOpen');
registerTutorial({ id: 'plc-first', order: 10, title: $t('teachIndex.guidedLabMotorStartStop'), icon: 'Cpu', course: 'plc_basics', lesson: 's01', help: 'plc', badge: $t('teachIndex.followTheTutorial'),
  desc: $t('teachIndex.writeYourFirstLadderProgram') + GUIDE });
registerTutorial({ id: 'plc-next', order: 11, title: $t('teachIndex.guidedLabMotorForwardReverse'), icon: 'Switch', course: 'plc_basics', lesson: 's02', help: 'plc', badge: $t('teachIndex.followTheTutorial'),
  desc: $t('teachIndex.addStartStopAndSeal') + GUIDE });
registerTutorial({ id: 'plc-estop', order: 12, title: $t('teachIndex.guidedLabConveyorStartStop'), icon: 'Warning', course: 'plc_basics', lesson: 's03', help: 'plc', badge: $t('teachIndex.followTheTutorial'),
  desc: $t('teachIndex.stopImmediatelyWhenEStop') + GUIDE });
registerTutorial({ id: 'line-first', order: 20, title: $t('teachIndex.guidedLabSingleMachineCycle'), icon: 'DataLine', course: 'machining', lesson: 'm01', help: 'course', badge: $t('teachIndex.followTheTutorial'),
  desc: $t('teachIndex.runTheModelToObserve') + GUIDE });

const A = (f: () => Promise<any>) => defineAsyncComponent(f);

export const panels = [
  { id: 'teach-task', title: $t('common.myCourses'), icon: 'Reading', component: A(() => import('./TaskPanel.vue')), workspaces: ['teach'], place: 'left', order: 60,
    roles: ['student', 'teacher', 'admin'] },
  { id: 'teach-metrics', title: $t('taskMetrics.taskMetrics'), icon: 'Odometer', component: A(() => import('./TaskMetrics.vue')), workspaces: ['teach'], place: 'inspector',
    order: 59, roles: ['student', 'teacher', 'admin'] },
  { id: 'teach-console', title: $t('common.teacherConsole'), icon: 'DataBoard', component: A(() => import('./TeacherConsole.vue')), workspaces: ['teach'], place: 'float',
    size: [1240, 760], order: 61, roles: ['teacher', 'admin'] },
  { id: 'teach-classes', title: $t('common.classesRosters'), icon: 'School', component: A(() => import('./ClassManager.vue')), workspaces: ['teach'], place: 'float',
    size: [980, 640], order: 62, roles: ['teacher', 'admin'] },
  { id: 'teach-courses', title: $t('common.courseLibrary'), icon: 'Collection', component: A(() => import('./CoursePublish.vue')), workspaces: ['teach'], place: 'float',
    size: [860, 620], order: 62.5, roles: ['teacher', 'admin'] },
  { id: 'teach-publish', title: $t('teacherConsole.singleTask'), icon: 'Promotion', component: A(() => import('./PublishWizard.vue')), workspaces: ['teach'], place: 'float',
    size: [780, 600], order: 63, roles: ['teacher', 'admin'] },
];
