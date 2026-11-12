// 4.7 Guided tours: ungraded step-by-step module explanations (purpose, when to use, what to do next), plus two complete task walkthroughs.
// Use the guided tutorial engine (tour.ts / TourOverlay.vue), but define steps here (no /api/teach requests); most are manual (user clicks "Next").
// Open via the page's "?" (components/GuideButton.vue), Ctrl+K search for "Guided Tours" (commands/guides.ts), or "Guided Tours" in the F1 help drawer.
//
// Guide format: { key, title, desc, areas: [where it appears in "?" menus], where: page to use, help?: help section, task?: complete task, roles?, steps }
//   where: workbench (a factory's Workbench) | experiments | signals (factory page; opens the matching floating panel in the Workbench) | courses (student courses page) | teach (teacher teaching page) | mes (desktop client)
//   Step: { id, title, do, why?, target, goto?, done?, manual? }; target uses {tour:'name'} → [data-tour=name] (array = first visible target). See the start of tour.ts.
// No static import of tour.ts here (the Command Palette loads this file on every page); load the engine only when starting a tour.
import { $t } from '../../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { desk, session } from '../../../api';

export type GuideStep = { id: string; title: string; do: string; why?: string; target: any; goto?: any; done?: any; manual?: boolean; delay?: number };
export type Guide = { key: string; title: string; desc: string; areas: string[]; where: string; help?: string | string[]; task?: boolean; roles?: string[]; kw?: string; steps: GuideStep[]; outro?: string };

const T = (n: string) => ({ tour: n });
const M = (s: Omit<GuideStep, 'manual'>): GuideStep => ({ manual: true, ...s });

export const GUIDES: Guide[] = [
  // ---------------- Workbench: four views ----------------
  {
    key: 'wb-3d', title: $t('guides.n3dView'), desc: $t('guides.watchTheFactoryInMotion'), areas: ['workbench'], where: 'workbench', help: 'views', kw: $t('guides.n3dThreeDimensionalViewPerspective'),
    steps: [
      M({ id: 'view', title: $t('guides.n3dWatchTheFactoryIn'), target: T('wb-view-3d'), goto: { view: '3d' }, do: $t('guides.switchBetweenFourViewsHere') }),
      M({ id: 'bar', title: $t('guides.viewpointsAndLayers'), target: T('v3-bar'), goto: { view: '3d' }, do: $t('guides.useViewpointToSwitchTo') }),
      M({ id: 'bn', title: $t('guides.spotBottlenecksAtAGlance'), target: T('v3-bottleneck'), goto: { view: '3d' }, do: $t('guides.clickBottleneckAnalysisEquipmentIs') }),
      M({ id: 'track', title: $t('guides.followAPart'), target: T('v3-track'), goto: { view: '3d' }, do: $t('guides.clickFollowAPartTo') }),
      M({ id: 'run', title: $t('guides.runAndFastForward'), target: T('wb-run-ctl'), do: $t('guides.the3dViewShowsSimulation') }),
      M({ id: 'next', title: $t('common.next'), target: T('wb-views'), do: $t('guides.toChangeTheLayoutGo') }),
    ],
  },
  {
    key: 'wb-plan', title: $t('guides.floorPlanView'), desc: $t('guides.placeEquipmentAndDrawThe'), areas: ['workbench', 'plan'], where: 'workbench', help: 'layers', kw: $t('guides.planFloorLayout2d'),
    steps: [
      M({ id: 'view', title: $t('guides.floorPlanLayoutInMeters'), target: T('wb-view-plan'), goto: { view: 'plan' }, do: $t('guides.theFloorPlanIsDrawn') }),
      M({ id: 'tools', title: $t('guides.drawingTools'), target: T('pv-tools'), goto: { view: 'plan' }, do: $t('guides.thisToolbarIncludesSelectWall') }),
      M({ id: 'canvas', title: $t('guides.moveAndConnectEquipment'), target: T('pv-canvas'), goto: { view: 'plan' }, do: $t('guides.dragEquipmentToRepositionIt') }),
      M({ id: 'layers', title: $t('planView.layers'), target: T('pv-layers'), goto: { view: 'plan' }, do: $t('guides.ifThePlanGetsCluttered') }),
      M({ id: 'foot', title: $t('guides.coordinatesAndToolTips'), target: T('pv-foot'), goto: { view: 'plan' }, do: $t('guides.theBottomBarShowsThe') }),
      M({ id: 'props', title: $t('guides.editDimensionsAndParameters'), target: T('wb-right'), goto: { right: 'props' }, do: $t('guides.selectAnyItemEquipmentWall') }),
    ],
  },
  {
    key: 'plan-draw', title: $t('guides.floorPlanDrawing'), desc: $t('guides.drawWallsAreasAislesAnd'), areas: ['workbench', 'plan'], where: 'workbench', help: 'layers', kw: $t('guides.wallAreaAislePathNetwork'),
    steps: [
      M({ id: 'rwall', title: $t('guides.drawExteriorWallsFirst'), target: T('pv-tool-rwall'), goto: { view: 'plan' }, do: $t('guides.selectRectangularWallAndClick') }),
      M({ id: 'walls', title: $t('guides.drawInteriorWalls'), target: T('pv-tool-walls'), goto: { view: 'plan' }, do: $t('guides.withWallClickEachPoint') }),
      M({ id: 'zones', title: $t('guides.defineAreas'), target: [T('pv-tool-rzone'), T('pv-tool-zones')], goto: { view: 'plan' }, do: $t('guides.useAreaOrRectangularArea') }),
      M({ id: 'aisles', title: $t('guides.drawAisles'), target: T('pv-tool-aisles'), goto: { view: 'plan' }, do: $t('guides.aisleDefinesRoutesForPeople') }),
      M({ id: 'paths', title: $t('guides.drawAnAgvNetwork'), target: T('pv-tool-paths'), goto: { view: 'plan' }, do: $t('guides.withNetworkSelectedClickTo'),
        why: $t('guides.networkNodesCanBeStops') }),
      M({ id: 'dims', title: $t('guides.dimensionsAndMeasurements'), target: T('pv-tool-dims'), goto: { view: 'plan' }, do: $t('guides.dimensionAddsDimensionLinesThat') }),
      M({ id: 'underlay', title: $t('guides.traceACadDrawing'), target: T('pv-underlay'), goto: { view: 'plan' }, do: $t('guides.haveACadScreenshotOr') }),
    ],
  },
  {
    key: 'wb-graph', title: $t('guides.graphView'), desc: $t('guides.buildAProcessFlowWith'), areas: ['workbench'], where: 'workbench', help: 'edit', kw: $t('guides.graphFlowCardsConnectionsProcess'),
    steps: [
      M({ id: 'view', title: $t('guides.graphProcessSequenceAtA'), target: T('wb-view-graph'), goto: { view: 'graph' }, do: $t('guides.theGraphShowsEachMachine') }),
      M({ id: 'canvas', title: $t('guides.connectAndAdd'), target: T('gv-canvas'), goto: { view: 'graph' }, do: $t('guides.dragFromOutOnThe') }),
      M({ id: 'tools', title: $t('guides.layoutAndFlowCounts'), target: T('gv-tools'), goto: { view: 'graph' }, do: $t('guides.autoLayoutRearrangesCardsBy') }),
      M({ id: 'lib', title: $t('common.library'), target: [{ panel_btn: 'library' }, T('wb-act')], do: $t('guides.theLibraryOnTheLeft') }),
      M({ id: 'props', title: $t('guides.parametersAndLiveStatus'), target: T('wb-right'), goto: { right: 'props' }, do: $t('guides.selectACardAndUse') }),
    ],
  },
  {
    key: 'wb-arch', title: $t('guides.architectureView'), desc: $t('guides.seeHowPlcsNetworksAnd'), areas: ['workbench'], where: 'workbench', help: 'layers', kw: $t('guides.archArchitectureNetworkPlcMes'),
    steps: [
      M({ id: 'view', title: $t('guides.architectureControlAndNetworkLayers'), target: T('wb-view-arch'), goto: { view: 'arch' }, do: $t('guides.theArchitectureDiagramIsLayered') }),
      M({ id: 'canvas', title: $t('guides.networkCablesAndSignalWires'), target: T('av-canvas'), goto: { view: 'arch' }, do: $t('guides.purpleLinesAreNetworkCables') }),
      M({ id: 'only', title: $t('guides.focusOnControl'), target: T('av-only'), goto: { view: 'arch' }, do: $t('guides.toFocusOnControlSelect') }),
      M({ id: 'auto', title: $t('guides.arrange'), target: T('av-auto'), goto: { view: 'arch' }, do: $t('guides.autoArrangeClearsManualPositions') }),
      M({ id: 'next', title: $t('common.next'), target: T('wb-views'), do: $t('guides.toAddAPlcTo') }),
    ],
  },
  // ---------------- Workbench blocks ----------------
  {
    key: 'plc', title: $t('common.plcProgramming'), desc: $t('guides.ladderDiagramsDownloadsOnlineMonitor'), areas: ['workbench', 'plc'], where: 'workbench', help: 'plc', kw: $t('guides.plcLadderDiagramLdSt'),
    steps: [
      M({ id: 'bar', title: $t('guides.plcProgrammingWindow'), target: T('plc-bar'), goto: { panel: 'plc-editor-float' }, do: $t('guides.thisIsThePlcProgramming') }),
      M({ id: 'tools', title: $t('guides.commandLanguage'), target: [T('ld-tools'), T('plc-pane')], goto: { panel: 'plc-editor-float' }, do: $t('guides.ladderInstructionsIncludeNoContacts') }),
      M({ id: 'compile', title: $t('common.compile'), target: T('plc-compile'), goto: { panel: 'plc-editor-float' }, do: $t('guides.compileChecksTheProgramWithout') }),
      M({ id: 'download', title: $t('common.download'), target: T('plc-download'), goto: { panel: 'plc-editor-float' }, do: $t('guides.downloadToPlcSendsThe') }),
      M({ id: 'monitor', title: $t('common.onlineMonitor'), target: T('plc-monitor'), goto: { panel: 'plc-editor-float' }, do: $t('guides.turnOnOnlineMonitorEnergized') }),
      M({ id: 'io', title: $t('guides.iOMonitoringAndForcing'), target: T('plc-tab-io'), goto: { panel: 'plc-editor-float' }, do: $t('guides.viewInputsAndOutputsOn') }),
    ],
  },
  {
    key: 'analysis', title: $t('common.analyze'), desc: $t('guides.bottlenecksTimeBreakdownMaterialFlow'), areas: ['workbench', 'analysis'], where: 'workbench', help: 'analysis', kw: $t('guides.analysisBottleneckTimeBreakdownSanke'),
    steps: [
      M({ id: 'tabs', title: $t('guides.analysisWindow'), target: T('an-tabs'), goto: { panel: 'analysis' }, do: $t('guides.theAnalysisWindowHelpsIdentify') }),
      M({ id: 'range', title: $t('guides.analysisTimeRange'), target: T('an-range'), goto: { panel: 'analysis' }, do: $t('guides.chooseHowManyRecentHours') }),
      M({ id: 'body', title: $t('guides.findEquipmentFromAChart'), target: T('an-body'), goto: { panel: 'analysis' }, do: $t('guides.clickEquipmentInAChart') }),
      M({ id: 'ai', title: $t('common.askAiToInterpret'), target: T('an-ai'), goto: { panel: 'analysis' }, do: $t('guides.askAiToInterpretSends') }),
      M({ id: 'report', title: $t('guides.enlargeAndExport'), target: T('an-report'), goto: { panel: 'analysis' }, do: $t('guides.toViewALargerChart') }),
      M({ id: 'next', title: $t('guides.nextTestImprovements'), target: [{ panel_btn: 'experiments' }, T('wb-act')], do: $t('guides.onceYouFindTheBottleneck') }),
    ],
  },
  // ---------------- Factory pages ----------------
  {
    key: 'experiments', title: $t('common.experimentsOptimization'), desc: $t('guides.compareScenariosOptimizeParametersPr'), areas: ['experiments', 'analysis'], where: 'experiments', help: 'exp', kw: $t('guides.experimentComparisonScenarioOptimiza'),
    steps: [
      M({ id: 'head', title: $t('guides.whatIsExperimentsOptimization'), target: T('exp-head'), do: $t('guides.compareScenariosAddAMachine') }),
      M({ id: 'new', title: $t('experiments.newExperiment2'), target: [T('exp-new'), T('exp-head')], do: $t('guides.newExperimentChooseParametersTo') }),
      M({ id: 'opt', title: $t('experiments.parameterOptimization2'), target: [T('exp-opt'), T('exp-head')], do: $t('guides.parameterOptimizationAutomaticallySe') }),
      M({ id: 'list', title: $t('guides.viewConclusions'), target: T('exp-list'), do: $t('guides.clickAnExperimentInThe') }),
      M({ id: 'sample', title: $t('guides.startWithAnExample'), target: [T('exp-samples'), T('exp-list')], do: $t('guides.firstTimeHereLoadExamples') }),
      M({ id: 'fork', title: $t('common.runWhatIfFromHere'), target: { sel: '[data-tour="exp-tabs"] #tab-fork' }, do: $t('guides.projectFromNowCopiesThe') }),
    ],
  },
  {
    key: 'signals', title: $t('common.signals'), desc: $t('guides.opcUaModbusMqttTags'), areas: ['signals'], where: 'signals', help: 'signals', kw: $t('guides.signalsTagsOpcUaModbus'),
    steps: [
      M({ id: 'head', title: $t('guides.whatIsSignals'), target: T('sig-head'), do: $t('guides.forIntegrationTestingWithMes') }),
      M({ id: 'ep', title: $t('guides.connectionAddresses'), target: [T('sig-endpoints'), T('sig-sandbox'), T('sig-head')], do: $t('guides.useTheCopyButtonsFor') }),
      M({ id: 'tree', title: $t('guides.browseTags'), target: T('sig-tree'), do: $t('guides.tagsAreListedByEquipment') }),
      M({ id: 'fault', title: $t('signals.communicationFaultInjection'), target: T('sig-fault'), do: $t('guides.simulateDisconnectionsLatencyPacketL') }),
      M({ id: 'export', title: $t('guides.exportTagList'), target: T('sig-export'), do: $t('guides.exportAnExcelCsvJson') }),
      M({ id: 'time', title: $t('guides.timestamps'), target: [T('sig-time'), T('sig-head')], do: $t('guides.chooseWhetherExternalTimestampsUse') }),
    ],
  },
  // ---------------- Teaching ----------------
  {
    key: 'courses', title: $t('guides.coursesPage'), desc: $t('guides.findCoursesResumeLearningAnd'), areas: ['courses'], where: 'courses', help: ['course', 'stu'], kw: $t('guides.coursesLearningAssignmentsLabs'), roles: ['learner'],
    steps: [
      M({ id: 'hero', title: $t('common.myCourses'), target: T('ch-hero'), do: $t('guides.eachCourseHasACard') }),
      M({ id: 'resume', title: $t('guides.resumeLearning'), target: [T('ch-resume'), T('ch-hero')], do: $t('guides.resumeLastLessonTakesYou') }),
      M({ id: 'filter', title: $t('guides.filterAndSearch'), target: T('ch-filter'), do: $t('guides.filterByInProgressOr') }),
      M({ id: 'grid', title: $t('guides.openACourse'), target: [T('ch-grid'), T('ch-empty')], do: $t('guides.clickACardToSee') }),
      M({ id: 'hw', title: $t('common.schoolAssignments'), target: T('ch-homework'), do: $t('guides.standaloneAssignmentsFromYourTeacher') }),
      M({ id: 'help', title: $t('guides.needHelp'), target: T('guide-btn'), do: $t('guides.followTheTaskInstructionsIn') }),
    ],
  },
  {
    key: 'teacher', title: $t('common.teacherConsole'), desc: $t('guides.trackClassProgressPublishCourses'), areas: ['teach'], where: 'teach', help: 'teach', kw: $t('guides.teacherClassAssignmentPublishReview'), roles: ['teacher', 'admin'],
    steps: [
      M({ id: 'head', title: $t('common.teacherConsole'), target: T('tc-head'), goto: { click: '.teach-page #tab-console' }, do: $t('guides.seeEachStudentSProgress') }),
      M({ id: 'pick', title: $t('guides.selectALesson'), target: T('tc-pick'), goto: { click: '.teach-page #tab-console' }, do: $t('guides.selectALessonOrTask') }),
      M({ id: 'lesson', title: $t('teacherConsole.startALesson'), target: T('tc-lesson'), goto: { click: '.teach-page #tab-console' }, do: $t('guides.startALessonGuidesYou') }),
      M({ id: 'publish', title: $t('guides.publishAFullCourse'), target: T('tc-publish'), goto: { click: '.teach-page #tab-console' }, do: $t('guides.publishCourseAssignsTheEntire') }),
      M({ id: 'grid', title: $t('guides.classOverview'), target: [T('tc-grid'), T('tc-empty'), T('tc-body')], goto: { click: '.teach-page #tab-console' }, do: $t('guides.studentCardsAreColorCoded') }),
      M({ id: 'classes', title: $t('common.classesRosters'), target: { sel: '.teach-page #tab-classes' }, do: $t('guides.noClassYetGoTo') }),
    ],
  },
  {
    key: 'mes', title: $t('guides.mesLocal'), desc: $t('guides.connectToALocalFactory'), areas: ['mes'], where: 'mes', help: 'client', kw: $t('guides.mesWorkOrderProductionReport'),
    steps: [
      M({ id: 'head', title: $t('guides.localMes'), target: [T('mes-bar'), T('mes-head')], do: $t('guides.teachingMesWorkOrdersProduction') }),
      M({ id: 'steps', title: $t('guides.getStartedInThreeSteps'), target: [T('mes-steps'), T('mes-bar'), T('mes-head')], do: $t('guides.clickMesOnTheLeft') }),
      M({ id: 'plants', title: $t('guides.selectALocalFactory'), target: [T('mes-plants'), T('mes-empty'), T('mes-more'), T('mes-bar'), T('mes-head')], do: $t('guides.selectALocalFactoryTo') }),
      M({ id: 'open', title: $t('guides.startMes'), target: [T('mes-open'), T('mes-new'), T('mes-bar'), T('mes-head')], do: $t('guides.clickStartAndOpenMes') }),
      M({ id: 'back', title: $t('mesBar.backToFactory'), target: [T('mes-back'), T('mes-head')], do: $t('guides.whileMesIsOpenClick') }),
    ],
  },
  // ---------------- Complete tasks ----------------
  {
    key: 'task-line', title: $t('guides.buildALineAndFind'), desc: $t('guides.incomingProcessExitRunThe'), areas: ['workbench'], where: 'workbench', task: true, help: 'edit',
    kw: $t('guides.beginnerGettingStartedBuildLine'), outro: $t('guides.doneYouBuiltALine'),
    steps: [
      { id: 'source', title: $t('guides.addAnIncomingBlock'), target: T('lib-source'), goto: { view: 'graph', panel: 'library' }, done: { added: 'source' },
        do: $t('guides.theFlowViewIsThe'), why: $t('guides.practiceInAnEmptyFactory') },
      { id: 'proc', title: $t('guides.addTwoProcessBlocks'), target: T('lib-processor'), goto: { panel: 'library' }, done: { added: 'processor', n: 2 },
        do: $t('guides.keepTheIncomingBlockSelected') },
      { id: 'sink', title: $t('guides.addAnExit'), target: T('lib-sink'), goto: { panel: 'library' }, done: { added: 'sink' },
        do: $t('guides.selectTheLastProcessBlock') },
      M({ id: 'check', title: $t('guides.checkTheConnections'), target: T('gv-canvas'), goto: { view: 'graph' },
        do: $t('guides.theFlowDiagramShouldForm') }),
      M({ id: 'slow', title: $t('guides.slowDownOneMachine'), target: T('wb-right'), goto: { right: 'props' },
        do: $t('guides.selectTheSecondProcessBlock') }),
      { id: 'apply', title: $t('guides.applyChangesAndRun'), target: [T('wb-apply'), T('wb-play')], done: { running: true },
        do: $t('guides.afterAddingOrRemovingEquipment') },
      M({ id: 'speed', title: $t('audit.fastForward'), target: [T('wb-speed'), T('wb-run-ctl')],
        do: $t('guides.setTheSpeedTo300') }),
      { id: 'open', title: $t('workbench.openAnalysis'), target: [{ panel_btn: 'analysis' }, T('wb-act')], done: { panel: 'analysis' },
        do: $t('guides.clickAnalyticsInTheVertical') },
      M({ id: 'bn', title: $t('guides.viewTheBottleneck'), target: T('an-body'), goto: { panel: 'analysis' },
        do: $t('guides.theTopRankedMachineOn') }),
      M({ id: 'next', title: $t('common.next'), target: [{ panel_btn: 'experiments' }, T('wb-act')],
        do: $t('guides.wantToKnowWhetherAdding') }),
    ],
  },
  {
    key: 'task-plc', title: $t('guides.addAPlcAndTest'), desc: $t('guides.addAPlcWriteLadder'), areas: ['workbench', 'plc'], where: 'workbench', task: true, help: 'plc',
    kw: $t('guides.plcIntegrationTestControlLadder'), outro: $t('guides.doneTheEquipmentNowHas'),
    steps: [
      { id: 'pick', title: $t('guides.selectAMachine'), target: [T('gv-canvas'), T('wb-viewport')], goto: { view: 'graph' }, done: { selected: 'process' },
        do: $t('guides.clickAProcessingMachineSuch') },
      { id: 'add', title: $t('common.addPlc'), target: [T('sel-addplc'), T('sel-prog')], goto: { select: '$process' }, done: { added: 'plc' },
        do: $t('guides.clickAddPlcInThe') },
      M({ id: 'apply', title: $t('guides.applyChanges'), target: [T('wb-apply'), T('wb-play')],
        do: $t('guides.addingAPlcIsA') }),
      { id: 'prog', title: $t('guides.openProgramming'), target: [T('sel-prog'), T('wb-viewport')], goto: { select: '$plc' }, done: { panel: 'plc-editor-float' },
        do: $t('guides.selectThePlcAndClick') },
      M({ id: 'rung', title: $t('guides.writeARung'), target: [T('ld-tools'), T('plc-pane')], goto: { panel: 'plc-editor-float' },
        do: $t('guides.addANoContactInput'),
        why: $t('guides.forExampleConnectTheEquipment') }),
      M({ id: 'compile', title: $t('common.compile'), target: T('plc-compile'), goto: { panel: 'plc-editor-float' }, do: $t('guides.clickCompileToCheckThe') }),
      M({ id: 'download', title: $t('common.download'), target: T('plc-download'), goto: { panel: 'plc-editor-float' }, do: $t('guides.clickDownloadToSendThe') }),
      M({ id: 'monitor', title: $t('common.onlineMonitor'), target: T('plc-monitor'), goto: { panel: 'plc-editor-float' }, do: $t('guides.turnOnOnlineMonitorEnergized2') }),
      M({ id: 'io', title: $t('guides.checkIO'), target: T('plc-tab-io'), goto: { panel: 'plc-editor-float' }, do: $t('guides.switchToIOMonitor') }),
      M({ id: 'run', title: $t('guides.runTogether'), target: T('wb-play'), do: $t('guides.clickRunInTheWorkbench') }),
    ],
  },
];

export const guideByKey = (k: string) => GUIDES.find((g) => g.key === k);
/** Definitions for the engine (tour.def). */
export function guideDef(key: string) {
  const g = guideByKey(key);
  return g ? { title: g.title, steps: g.steps, outro: g.outro || $t('guides.the0TourIsComplete', [g.title]), kind: 'guide' } : null;
}

// ---------------- Remember the step on exit (ask "Resume / Start over" when reopened) ----------------
const GKEY = 'vf_guide_at';
function memo(): Record<string, number> { try { const v = JSON.parse(localStorage.getItem(GKEY) || '{}'); return v && typeof v === 'object' ? v : {}; } catch { return {}; } }
export function guideAt(key: string): number { const v = memo()[key]; return typeof v === 'number' && v > 0 ? v : 0; }
export function setGuideAt(key: string, i: number | null) {
  try { const m = memo(); if (i && i > 0) m[key] = i; else delete m[key]; localStorage.setItem(GKEY, JSON.stringify(m)); } catch { /* Private browsing mode */ }
}

// ---------------- Access and location ----------------
const role = () => session.user?.role || '';
const learner = () => role() === 'student' || desk.mode === 'standalone';
const inWb = () => /^\/p\/[^/]+\/workbench/.test(location.pathname);
const urlPid = () => decodeURIComponent(location.pathname.match(/^\/p\/([^/]+)/)?.[1] || '');
function curPid() {
  const u = urlPid();
  if (u) return u;
  let last = '';
  try { last = localStorage.getItem('vf_last_plant') || ''; } catch { /* */ }
  return last || session.plants?.[0]?.id || '';
}
/** Whether this user can start this tour now (role, desktop client). */
export function guideAvailable(g: Guide): boolean {
  if (!session.user) return false;
  if (g.roles?.length) {
    const ok = g.roles.some((r) => (r === 'learner' ? learner() : r === role()));
    if (!ok) return false;
  }
  if (g.where === 'mes') return desk.on;
  // Students can only access their own sandboxes: offer factory tours only in sandbox Workbenches.
  if (role() === 'student' && ['workbench', 'experiments', 'signals'].includes(g.where)) return inWb() && (g.where !== 'signals');
  if (g.where === 'teach') return ['teacher', 'admin'].includes(role()) && desk.mode !== 'standalone';
  return true;
}
/** Tours listed under "?": tours for this location + complete tasks (tasks last). */
export function guidesFor(area: string) {
  const all = GUIDES.filter(guideAvailable);
  return { here: all.filter((g) => !g.task && g.areas.includes(area)), tasks: all.filter((g) => g.task) };
}
/** Help drawer: tours relevant to this section. */
export const guidesForHelp = (sectionId: string) => GUIDES.filter((g) => ([] as string[]).concat(g.help || []).includes(sectionId) && guideAvailable(g));

const READY: Record<string, string> = { workbench: '.ed-bar', experiments: '[data-tour="exp-head"]', signals: '[data-tour="sig-head"]', courses: '[data-tour="ch-hero"]', teach: '.teach-page', mes: '[data-k="mes-page"]' };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function waitFor(sel: string, ms: number) { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (document.querySelector(sel)) return true; await sleep(100); } return !!document.querySelector(sel); }
async function nav(to: string) { const { router } = await import('../../../router'); await router.push(to); }

/** Navigate to the tour's page (stay if already there). Return false with a reason if navigation fails. */
async function arrive(g: Guide): Promise<boolean> {
  const path = location.pathname, pid = curPid();
  const stu = role() === 'student';
  const needPlant = () => { ElMessage.info(stu ? $t('guides.enterALessonSLab') : $t('guides.openAFactoryBeforeOpening')); return false; };
  if (g.where === 'workbench') {
    if (!inWb()) { if (stu || !pid) return needPlant(); await nav(`/p/${encodeURIComponent(pid)}/workbench`); }
  } else if (g.where === 'experiments' || g.where === 'signals') {
    if (inWb()) {                                    // In the Workbench: open the matching floating panel (same content as the page).
      const { ed } = await import('../../../editor/store');
      if (!(ed.floats || []).some((w: any) => String(w.id).split(':')[0] === g.where)) window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: g.where } }));
    } else if (!new RegExp(`^/p/[^/]+/${g.where}`).test(path)) { if (stu || !pid) return needPlant(); await nav(`/p/${encodeURIComponent(pid)}/${g.where}`); }
  } else if (g.where === 'courses') {
    if (!/^\/(courses|teach)(\/|$)/.test(path) || (path.startsWith('/teach') && !learner())) await nav('/courses');
  } else if (g.where === 'teach') {
    if (!/^\/teach(\/|$)/.test(path)) await nav('/teach');
  } else if (g.where === 'mes') {
    if (!/^\/mes(\/|$)/.test(path)) await nav('/mes');
  }
  const ok = await waitFor(READY[g.where] || 'body', 20000);
  if (!ok) ElMessage.warning($t('guides.thePageIsStillLoading'));
  return ok;
}

/** Open a tour. If at is omitted and prior progress exists, ask "Resume from step N / Start over". Return whether it started. */
export async function startGuide(key: string, at?: number): Promise<boolean> {
  const g = guideByKey(key);
  if (!g) return false;
  const T0 = await import('./tour');
  if (T0.tour.on && !T0.tour.guide) {
    try {
      await ElMessageBox.confirm($t('guides.youAreFollowingThisLesson'), $t('guides.openGuidedTour'), { confirmButtonText: $t('guides.openTour'), cancelButtonText: $t('common.cancel'), type: 'info' });
    } catch { return false; }
  }
  if (at === undefined) {
    const m = guideAt(key);
    if (m > 0 && m < g.steps.length) {
      try {
        await ElMessageBox.confirm($t('guides.youLastExitedAtStep', [m + 1, g.steps[m].title]), $t('guides.guidedTour0', [g.title]),
          { confirmButtonText: $t('guides.continueFromStep0', [m + 1]), cancelButtonText: $t('guides.startOver'), distinguishCancelAndClose: true, type: 'info', customClass: 'vf-guide-resume' });
        at = m;
      } catch (a) { if (a === 'cancel') at = 0; else return false; }
    } else at = 0;
  }
  if (!(await arrive(g))) return false;
  T0.startLocal(guideDef(key), { key, pid: inWb() || /^\/p\//.test(location.pathname) ? urlPid() : '' }, Math.max(0, Math.min(at || 0, g.steps.length - 1)));
  return true;
}

(window as any).__vfTour = Object.assign((window as any).__vfTour || {}, { guides: GUIDES, startGuide, guidesFor, guideAt, setGuideAt });   // For UI tests
// Tour still open after page refresh: load the engine (it resumes the last step from sessionStorage).
try { if (JSON.parse(sessionStorage.getItem('vf_tour') || 'null')?.guide) import('./tour'); } catch { /* */ }
