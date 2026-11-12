// Help Center content shared by pages/Help.vue and the F1 context help drawer help/HelpDrawer.vue. Section IDs are also data-help="<id>" values.
import { $t } from '../i18n';
import { session } from '../api';

export type HelpSection = { id: string; title: string; text: string };
// Show "Five lab steps" first for students, with only lab-related sections; teachers also see teaching and course sections
export const STUDENT: HelpSection = { id: 'stu', title: $t('sections.studentsCompleteALabLesson'), text: `${$t('sections.n1ReadTheTaskBrief')}"${$t('common.teaching')}"→"${$t('common.myCourses')}"${$t('sections.thenSelectALessonThe')}
${$t('sections.n2WriteTheProgramOn')}"PLC"→"${$t('common.program2')}"${$t('sections.openThePlcProgrammingWindow')}"${$t('common.compile')}"${$t('sections.toCheckForErrorsEach')}
${$t('sections.n3DownloadAndRunClick')}"${$t('common.download')}"${$t('sections.toPutThePlcIn')}"${$t('common.run')}"${$t('sections.toStartTheEquipment')}
${$t('sections.n4TestUseTheOperator')}"${$t('common.onlineMonitor')}"${$t('sections.toSeeWhetherEachContact')}
${$t('sections.n5SubmitInTheTask')}"${$t('common.submitForGrading')}"${$t('sections.theSystemRunsTestsAutomatically')}
${$t('sections.stuckCheckTheHintsIn')}"${$t('common.aiTutor')}"${$t('sections.itOffersGuidanceWithoutGiving')}` };
export const STU_IDS = ['stu', 'welcome', 'course', 'client', 'plc', 'cell', 'graph', 'teach', 'account'];
export const SECTIONS: HelpSection[] = [
  { id: 'start', title: $t('sections.quickStart'), text: `${$t('sections.honeyfactoryIsAnIndustrialDigital')}

${$t('sections.n1In')}"${$t('common.allFactories')}"${$t('sections.openAFactorySWorkbench')}
${$t('sections.n2In')}"${$t('common.scenario')}"${$t('sections.runABuiltInScenario')}"${$t('sections.nightShiftToolBreakage')}"${$t('sections.andObserveChangesInAlarms')}
${$t('sections.n3In')}"${$t('common.signals')}"${$t('sections.getTheProtocolEndpointsAnd')}
${$t('sections.n4In')}"${$t('common.experimentsOptimization')}"${$t('sections.evaluateTheEffectsOfAdding')}
${$t('sections.n5In')}"${$t('common.dataset')}"${$t('sections.exportDataWithGroundTruth')}` },
  { id: 'welcome', title: $t('sections.startPageCommandPaletteCtrl'), text: `${$t('sections.startPageThisIsWhere')}"${$t('sections.showWelcomePageAtStartup')}"${$t('sections.toGoStraightToThe')}"${$t('common.start')}"${$t('sections.inTheLeftMenu')}
${$t('sections.recentRecentlyOpenedFactoriesWith')}
${$t('sections.newCreateAFactoryFrom')}
${$t('sections.learnResumeYourLastLesson')}
${$t('sections.studentsAlsoSee')}"${$t('common.resumeLastLesson')}"${$t('sections.andAssignmentsDueSoonTeachers')}
${$t('sections.commandPalettePressCtrlK')}
${$t('sections.f1OpenHelpFor')}"${$t('common.youAreHere')}"${$t('sections.withoutLeavingThePageIn')}"${$t('common.teaching')}"${$t('sections.pageItOpensGuidanceOn')}` },
  { id: 'cockpit', title: $t('sections.workbenchOneCanvasThreeViews'), text: `${$t('sections.theWorkbenchIsTheMain')}
${$t('sections.workspacesAtTheTopGeneral')}
${$t('sections.leftActivityBarClickAn')}
${$t('sections.rightInspector')}"${$t('common.attribute')}"${$t('sections.toEditTheModel')}"${$t('common.live')}"${$t('sections.toViewTheSelectedEquipment')}"${$t('sections.pinned')}"${$t('sections.toTheCanvasAsFloating')}
${$t('sections.aSingleTimelineAtThe')}
${$t('sections.statesRunningPausedYellowBorder')}"${$t('sections.changesDuringARun')}"${$t('sections.ifYouMakeStructuralChanges')}
${$t('sections.runControlsResetRunPause')}` },
  { id: 'graph', title: $t('sections.workDirectlyInTheView'), text: `${$t('sections.youCanWorkDirectlyWith')}
${$t('sections.rightClickEquipmentCopyDelete')}"${$t('common.breakpoint')}"${$t('sections.whenItEntersDowntimeBlocked')}"${$t('contextMenu.watchValues')}"${$t('sections.selectTagsToDisplayTheir')}"${$t('common.injectFailure')}"${$t('sections.basedOnTheFailuresSupported')}
${$t('sections.equipmentWithBreakpointsHasA')}
${$t('sections.libraryDragAnAssetInto')}
${$t('sections.shortcutsDeleteBackspaceToDelete')}
${$t('sections.onlyTheLightThemeIs')}` },
  { id: 'layers', title: $t('sections.realFactoryLayersProductionEquipment'), text: `${$t('sections.aFactoryIncludesProductionEquipment')}
${$t('sections.selectAnyObjectCommonActions')}"${$t('objectPanel.connections')}"${$t('sections.upstreamAndDownstreamMaterialFlow')}
${$t('sections.addAPlcSelectEquipment')}"${$t('common.addPlc')}"${$t('sections.toPlaceAPlcBeside')}"${$t('sections.connectToAnExistingPlc')}"${$t('sections.orUseThePlcS')}"${$t('sections.controlEquipment')}"${$t('sections.equipmentWith')}"${$t('sections.runEnable')}"${$t('sections.connectedWillNotStartUntil')}"${$t('store.waitingForPlc')}"${$t('sections.k2241')}
${$t('sections.connectionsInTheGraphView')}"${$t('sections.nSignals')}"${$t('sections.dragBetweenPlcsGatewaysSwitches')}"+"${$t('sections.addsAndConnectsTheNext')}
${$t('sections.architectureTheFourthViewFour')}"${$t('archView.add')}"${$t('sections.addObjectsByLayer')}"${$t('archView.showOnlyEquipmentConnectedTo')}"${$t('sections.keepEvenLargeFactoriesEasy')}
${$t('sections.theFloorPlanReadsLike')}
${$t('sections.displayUseTheToolbarS')}"${$t('common.show')}"${$t('sections.toFilterByLayerAnd')}
${$t('sections.thePropertiesPanelDefaultsTo')}"${$t('sections.simpleMode')}"${$t('sections.whichListsOnlyCommonParameters')}"${$t('details.advanced')}"${$t('sections.toShowAllParametersAnd')}"?"${$t('sections.providesAnExplanation')}
${$t('sections.insideTheEquipmentSelectEquipment')}"${$t('common.equipmentInterior')}"${$t('sections.toSeeEveryInputAnd')}
${$t('sections.controlPanelStartStopAnd')}"${$t('common.operatorPanel')}"${$t('sections.toOpenItAgain')}
${$t('sections.n3dHoverOverEquipmentTo')}"${$t('common.equipmentInterior')}"${$t('sections.orDoubleClickAPlc')}
${$t('sections.theFloorPlanAndGraph')} = ${$t('sections.addAndConnectAUnit')}"+"${$t('sections.orTheTabKeyAlso')}` },
  { id: 'views', title: $t('sections.toolsFor3dFloorPlan'), text: `${$t('sections.n3dViewPresetsAnd')}"${$t('sections.bookmarks')}"${$t('sections.saveTheCurrentViewAnd')}
${$t('sections.floorPlanPositionEquipmentPrecisely')}
${$t('sections.graphConnectionsShowLiveFlow')}"${$t('dockLists.traceStepByStepIn')}"${$t('sections.toHighlightTheEquipmentAnd')}` },
  { id: 'edit', title: $t('sections.modelingGraphFloorPlanAnd'), text: `${$t('sections.buildModelsInTheWorkbench')}
${$t('sections.graphPrimaryEachEquipmentUnit')}"${$t('common.in')}"${$t('sections.andTheRightSideShowing')}"${$t('common.out')}"${$t('sections.inspectionEquipmentAlsoHasAn')}"${$t('common.out')}"${$t('sections.toAnotherCardS')}"${$t('common.in')}"${$t('sections.toConnectThemDragTo')}
${$t('sections.floorPlanPositionEquipmentPrecisely2')}"${$t('planView.calibrateBackgroundImage')}"${$t('sections.toClickTwoPointsA')}"${$t('common.measureDistance')}"${$t('sections.toMeasureTheDistanceBetween')}
${$t('sections.n3dEditingIsAlsoSupported')}
${$t('sections.leftPanel')}"${$t('common.object')}"${$t('sections.listsAllObjectsByZone')}"${$t('common.library')}"${$t('sections.letsYouDragBlocksInto')}"${$t('sections.details')}"${$t('sections.letsYouEditParametersBy')}
${$t('sections.customTagsAddTagsTo')}"${$t('details.parameterBinding')}"${$t('sections.letsFormulasDriveParametersFor')}
${$t('sections.groupingSelectSeveralBlocksAnd')}"${$t('common.saveAsTemplate')}"${$t('sections.toReuseTheEntireLine')}
${$t('sections.allChangesFirstGoInto')}"${$t('common.draft')}"${$t('sections.andAreSavedAutomaticallyUse')}"${$t('common.check')}"${$t('sections.listsErrorsAndWarnings')}"${$t('modelPanel.testRun')}"${$t('sections.fastForwardsTheCurrentConfiguration')}"${$t('sections.applyToFactory')}"${$t('sections.parameterAndPositionChangesAre')}"${$t('common.version')}"${$t('sections.youCanCompareAndLoad')}
${$t('sections.shortcutsCtrlKOpensThe')}` },
  { id: 'ai', title: $t('common.aiAssistant'), text: `${$t('sections.atTheBottomRightOf')}"${$t('common.aiAssistant')}"${$t('sections.whichAutomaticallyKnowsYourCurrent')}"${$t('livePanel.askAiToInvestigate')}"${$t('sections.onTheEquipmentLiveStatus')}"${$t('common.askAi')}"${$t('sections.k2241')}
${$t('sections.itChecksRunDataReports')}"${$t('sections.readingCnc3SLiveStatus')}"${$t('sections.k2241')}
${$t('sections.beforeChangingTheModelIt')}"${$t('assistantDock.applyToDraft')}"${$t('sections.toApplyTheChangeAs')}
${$t('sections.itCanAlsoSetBreakpoints')}
${$t('sections.itDoesNotModifyReal')}"${$t('assistantDock.chatHistory')}"${$t('sections.anOpenaiCompatibleLanguageModel')}` },
  { id: 'plan', title: $t('common.productionPlan'), text: `${$t('sections.shiftsOutsideScheduledShiftsEquipmen')}
${$t('sections.plannedDowntimeAtTheScheduled')}"${$t('common.plannedDowntime')}"${$t('sections.stateThisIsExcludedFrom')}
${$t('sections.productsAndOrdersOrdersRun')}
${$t('sections.applyAndSaveClickApply')}` },
  { id: 'scenario', title: $t('common.scenario'), text: `${$t('sections.aScenarioIsATimed')}
"${$t('sections.minuteN')}"${$t('sections.isMeasuredFromTheStart')}
${$t('sections.tenBuiltInScenariosAre')}` },
  { id: 'exp', title: $t('sections.experimentsOptimizationWhatIfFrom'), text: `${$t('sections.experimentComparisonDefineAlternativ')}"${$t('sections.parametersLevels')}"${$t('sections.toGenerateCombinationsAutomaticallyE')}"${$t('sections.startingSeed1000K')}"${$t('sections.allAlternativesUseTheSame')}"${$t('sections.significant')}"${$t('sections.indicatesThatTheConfidenceInterval')}
${$t('sections.parameterOptimizationChooseAdjustabl')}
${$t('sections.whatIfFromNowCreates')}"${$t('common.runWhatIfFromHere')}"${$t('sections.orAskAi')}"${$t('sections.whatWouldHappenIfWe')}"${$t('sections.experimentsDoNotAffectThe')}` },
  { id: 'analysis', title: $t('sections.analysisTimeBreakdownMaterialFlow'), text: `${$t('sections.timeBreakdownEachMachineS')} = ${$t('sections.availabilityPerformanceQualityPlanne')}
${$t('sections.materialFlowSankeyDiagramShows')}
${$t('sections.energyPowerByState15')}
${$t('sections.bottlenecksUsesTheActivePeriod')}"${$t('sections.busy')}"${$t('sections.atAnyGivenTimeDetermines')}"${$t('sections.tiedBottlenecks')}"${$t('sections.withAConfidenceRatingEquipment')}"${$t('common.bottleneckAnalysis')}"${$t('sections.toColorEquipmentByUtilization')}
${$t('sections.allStatisticsAcrossAnalysisReports')}
${$t('sections.theseAreAvailableAtThe')}"${$t('common.analyze')}"${$t('sections.tabClickABarOr')}"${$t('common.runReports')}"${$t('sections.youCanAlsoClick')}"${$t('common.askAiToInterpret')}"${$t('common.k266')}` },
  { id: 'tables', title: $t('sections.dataTablesSubmodelsAndDxf'), text: `${$t('sections.dataTablesImportCsvExcel')}"${$t('sections.releaseFromDataTable')}"${$t('sections.optionUsesTheTableS')}'${$t('sections.tableName')}'${$t('sections.key')} '${$t('sections.columnName')}'${$t('sections.toRetrieveValuesRoutingAnd')}
${$t('sections.submodelsPackageASectionOf')}"${$t('sections.parameterValues')}"${$t('sections.toOverrideInternalParametersBlocks')}
${$t('sections.dxfUnderlaysUploadACad')}
${$t('sections.newBlockParametersFailuresBased')}` },
  { id: 'signals', title: $t('sections.signalsAndProtocols'), text: `${$t('sections.opcUaOpcTcp')}<${$t('sections.host')}>${$t('sections.n4840VfactoryAnonymousAccessNo')}=2;s=<${$t('common.factory')}>/<${$t('common.equipment')}>/<${$t('common.tag')}>${$t('sections.eachValueIncludesSourceAnd')}"${$t('sections.allowOutOfRangeWrites')}"${$t('sections.forFaultDrillsSupportsHistorical')}
${$t('sections.externalTimestampsInSignalsEach')}"${$t('common.simTime')}"${$t('sections.or')}"${$t('common.wallClock')}"${$t('sections.toDetermineWhichClockProtocol')}
${$t('sections.modbusTcpOnePortPer')}
${$t('sections.mqttTopicVfactory')}<${$t('common.factory')}>/<${$t('common.area')}>/<${$t('common.equipment')}>/<${$t('common.tag')}>${$t('sections.payload')} {"value","unit","quality","ts","sim_ts","wall_ts"}${$t('sections.iso8601WithTimeZone')} {"value": x}${$t('sections.resultsAreReturnedOnSet')}<${$t('common.factory')}>${$t('sections.errorsAgvsPublishUsingVda')}
${$t('sections.communicationFaultsInjectFaultsBy')}
${$t('sections.connectionAddressesShowThisComputer')}
${$t('sections.exportTheTagListTo')}` },
  { id: 'delivery', title: $t('sections.deliveryPackagesRawSiteMode'), text: `${$t('sections.deliveryPackageInSignalsOr')}"${$t('sections.deliveryPackage')}"${$t('sections.toDownloadAZipContaining')}"${$t('deliveryExport.oneRowPerTagUsing')}"${$t('sections.or')}"${$t('deliveryExport.oneRowPerProtocol')}"${$t('sections.n3dOptionsIncludeTheModels')}
${$t('sections.rawSiteModeASwitch')}"${$t('sections.workOutWhatEachTag')}"${$t('sections.theSimulationIsNotReset')}
${$t('sections.actionSignalsMachiningCentersMolding')}"Actions"${$t('sections.solenoidValvesPositionSensorsSpindle')}"${$t('sections.actionSignal')}"${$t('sections.property')}
${$t('sections.actionFailuresTheEquipmentFailure')}"${$t('sections.cylinderLeakSlowerExtension')}""${$t('sections.fixtureJamSlowerRelease')}""${$t('sections.slowGuardDoor')}"${$t('sections.alsoAvailableInScenariosThe')}=clamp,extra_s=2,drift_s_per_day=${$t('sections.n05MeansTheClamp')}"${$t('common.clearFailure')}"${$t('sections.restoresNormalOperation')}` },
  { id: 'dataset', title: $t('common.dataset'), text: `${$t('sections.tagsCsvWideFormatTime')}
${$t('sections.theMostRecent24Hours')}` },
  { id: 'cell', title: $t('sections.controlUnitsEquipmentLevelSensors'), text: `${$t('sections.equipmentInTheFullPlant')}"${$t('sections.processLevel')}"${$t('sections.aMachineToolOrA')}"${$t('sections.equipmentLevel')}"${$t('sections.conveyorsSensorsActuatorsAndOperator')}"${$t('sections.controlUnit')}"${$t('sections.blockFromTheLibraryInto')}"${$t('sections.controlUnit')}"${$t('sections.inTheActivityBarTo')}
${$t('sections.components32TypesBeltRoller')}
${$t('sections.editingPlaceAndDragComponents')}"${$t('common.components')}"${$t('sections.tabOnTheRightTo')}
${$t('sections.runningClickOperatorPanelButtons')}
${$t('sections.n3dEveryComponentTypeHas')}
${$t('sections.tagsEachIOIs')}<${$t('common.name')}>${$t('sections.andOperatorPanelComponentsAs')}<${$t('common.no2')}>${$t('sections.allowingMesScadaToRead')}` },
  { id: 'plc', title: $t('sections.plcProgrammingBuiltInSoft'), text: `${$t('sections.aPlcIsAStandalone')}"${$t('common.program2')}"${$t('sections.orIn')}"${$t('common.teaching')}"${$t('sections.theLeftSideOfThe')}"PLC"${$t('sections.toStartProgrammingSelectingA')}"${$t('sections.thePlcBuiltIntoEach')}"${$t('sections.isAutomaticallyConvertedIntoA')}
${$t('sections.languagesLadderDiagramNoNc')}
${$t('sections.compilationErrorsAreReportedIn')}
${$t('sections.downloadAndRunDownloadingWhile')}
${$t('sections.onlineDebuggingHighlightPowerFlow')}
${$t('sections.importExportExchangeLadderDiagrams')}
${$t('sections.connectAPhysicalPlcIn')}"${$t('common.externalPlc')}"${$t('sections.settingsSelectAProtocolModbus')}
${$t('sections.hmiDragButtonsSwitchesIndicator')}
${$t('sections.iOTableEachTag')}
${$t('sections.timingChartPlotIO')}"${$t('sections.expectedTiming')}"${$t('sections.andMarkEachItemAs')}
${$t('sections.crossReferenceSeeWhichRungs')}"${$t('sections.duplicateCoils')}"${$t('sections.unusedInputsAndOutputsThat')}
${$t('sections.breakpointsWhenARungOr')}"${$t('sections.plcPausedAtLineN')}"${$t('sections.theLeftSide')}"${$t('common.breakpoint')}"${$t('sections.panelIsDividedInto')}"${$t('breakpoints.conditionalSimulationBreakpoints')}"${$t('sections.and')}"${$t('breakpoints.plcBreakpoints')}"${$t('sections.groups')}
${$t('sections.rightClickALadderElement')}
${$t('sections.aiAssistantAsk')}"${$t('sections.writeAConveyorSortingProgram')}"${$t('sections.toGetAProgramCard')}"${$t('assistantDock.downloadToPlcAndRun')}"${$t('common.k266')}` },
  { id: 'course', title: $t('sections.coursesFromBasicToAdvanced'), text: `${$t('sections.threeBuiltInCoursesEach')}"${$t('sections.openAll')}"${$t('sections.k2460')}
${$t('sections.plcControlFundamentals15Lessons')}
${$t('sections.productionLineSimulationOptimization')}
${$t('sections.foundryOperations6LessonsCooling')}
${$t('sections.lessonTypesPlcControlWrite')}
${$t('sections.teachersGoToTeachingCourse')}"${$t('common.publishToClass')}"${$t('common.k344')}"${$t('sections.courseOverview')}"${$t('sections.isAStudentByLesson')}"${$t('common.continue')}"${$t('common.k266')}
${$t('sections.demoAtServerStartupSet')}=${$t('sections.n1OrGoToThe')}"${$t('sections.createDemoClass')}"${$t('sections.whichCreatesTheDemoTeacher')}` },
  { id: 'teach', title: $t('sections.teachingLabTasksGradingAnd'), text: `${$t('sections.forPlcAndSmartManufacturing')}"${$t('common.usersRoles')}"${$t('sections.orByATeacherImporting')}
${$t('sections.teachersInTheLeftSide')}"${$t('common.teaching')}"${$t('sections.orTheWorkbenchS')}"${$t('common.teaching')}"${$t('sections.workspace')}
${$t('sections.classesAndRostersCreateClasses')}
${$t('sections.assignTasksChooseFrom15')}
${$t('sections.teacherConsoleViewClassProgress')}"${$t('sections.takeOver')}"${$t('sections.andNotifyTheStudentViewing')}
${$t('sections.students')}
${$t('sections.afterLoggingInGoDirectly')}"${$t('common.teaching')}"${$t('sections.thenUnder')}"${$t('sections.myLabTasks')}"${$t('sections.selectATaskAndEnter')}
${$t('sections.writePlcProgramsDownloadTo')}
${$t('sections.submissionsAreGradedAutomaticallyAga')}
${$t('sections.aiTutorTheAssistantIn')}"${$t('common.aiTutor')}"${$t('sections.itCanSeeYourProgram')}
${$t('sections.aSandboxSleepsAutomaticallyAfter')}"${$t('sections.labTasks')}"${$t('sections.andOpenItAgain')}` },
  { id: 'design', title: $t('sections.designDesignReportsAndSop'), text: `"${$t('panels.design')}"${$t('sections.theWorkspaceOpensTheFloor')}
${$t('sections.designReportsExportToWord')}
${$t('sections.sopWalkthroughsBreakAWork')}` },
  { id: 'debug', title: $t('sections.integrationTestTagListsMessages'), text: `"${$t('panels.integrationTest')}"${$t('sections.thisWorkspaceIsForMes')}
${$t('sections.tagListViewLiveValues')}
${$t('sections.connectionsAndCommunicationFailuresS')}
${$t('sections.messagesCaptureMqttMessagesAnd')}
${$t('sections.testScriptsDefineStepBy')}"${$t('sections.whatTheFactoryShouldDo')}"${$t('sections.waitInjectFailuresWriteTags')}
${$t('sections.commandLineForCiPython')}"${$t('common.skip')}"${$t('sections.warmUpResultsAreCached')}
${$t('sections.messagesTwoTimeColumnsLocal')}
${$t('sections.dockerTheProjectIncludesDockerfile')}` },
  { id: 'client', title: $t('sections.windowsDesktopClientAssignmentPackag'), text: `${$t('sections.theDesktopClientHasThe')}
${$t('sections.loginSignInToThe')}"${$t('common.usersRoles')}"${$t('sections.adminsManageAccountsInThe')}"${$t('common.local')}"${$t('sections.serverFactoriesCanBe')}"${$t('sections.downloadedToThisComputer')}"${$t('common.k266')}
${$t('sections.standaloneUseOnTheLogin')}"${$t('sections.useStandalone')}"${$t('sections.noAccountIsRequiredA')}
${$t('sections.offlineAccountsUsedToSign')}
${$t('sections.assignmentsAssignmentsPublishedByThe')}"${$t('common.myCourses')}"${$t('sections.click')}"${$t('sections.workLocally')}"${$t('sections.thenClick')}"${$t('sections.submitToTeacher')}"${$t('sections.whenFinishedTheServerGrades')}"${$t('sections.exportAssignmentPackage')}"${$t('sections.vfhwForTheTeacherTo')}
${$t('sections.teachersEachSubmissionShowsIts')}"${$t('sections.openAndRun')}"${$t('sections.toInspectTheStudentS')}
${$t('sections.protocolServicesOpcUaModbus')}` },
  { id: 'account', title: $t('sections.accountsTokensAudit'), text: `${$t('sections.rolesAdminAllFeaturesIncluding')}
${$t('sections.forIntegrationWithOtherSystems')}"${$t('common.apiTokens')}"${$t('sections.restrictScopesReadOnlyRead')}"${$t('common.recentlyUsed')}"${$t('sections.showsTheActualRequestTime')} <${$t('sections.token')}>${$t('sections.apiDocumentationDocsAvailableOffline')}
${$t('sections.allOperationsThatModifyData')}"${$t('common.auditLog')}"${$t('common.k266')}` },
  { id: 'deploy', title: $t('sections.deploymentOperations'), text: `${$t('sections.selfHostedDeploymentOneWindows')}
${$t('sections.dataPlantsStoresFactoryConfiguration')}
${$t('sections.openThePortsListedAbove')}` },
];

/** Role-based sections: students see lab-related sections only; teachers also see "Five steps for students". */
export function sectionsFor(role = session.user?.role): HelpSection[] {
  if (role === 'student') return [STUDENT, ...SECTIONS].filter((s) => STU_IDS.includes(s.id));
  return role === 'teacher' ? [STUDENT, ...SECTIONS] : SECTIONS;
}
export const sectionById = (id: string) => [STUDENT, ...SECTIONS].find((s) => s.id === id);
