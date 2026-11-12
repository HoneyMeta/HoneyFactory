<template>
  <div class="vp task-panel" ref="root" :class="{ narrow, split: splitOn }">
    <div class="vp-head">
      <span class="ttl">{{ cur && !splitOn ? cur.assignment.title : $t('common.myCourses') }}</span>
      <el-button v-if="cur && !watching && !splitOn && !noMap" size="small" text @click="back"><el-icon><Back /></el-icon>{{ $t('taskPanel.courseMap') }}</el-button>
      <el-button size="small" text :loading="loading" @click="refresh" :title="$t('common.refresh')"><el-icon><Refresh /></el-icon></el-button>
    </div>

    <!-- Review sandbox (teacher opens a student submission / client opens an assignment package): run only, no answering questions -->
    <div v-if="review" class="vp-body">
      <div class="vp-card review-card">
        <b>{{ $t('taskPanel.reviewSandbox') }}</b>
        <div class="vp-small" style="margin-top: 4px">{{ review.label }}</div>
        <div class="vp-small vp-muted" style="margin-top: 6px">{{ $t('taskPanel.thisContainsTheStudentS', [review.what]) }}</div>
      </div>
    </div>
    <div v-else class="tp-main">
      <!-- Course map (always on the left on wide screens; alternates with the lesson in narrow panels) -->
      <div v-if="(!cur || splitOn) && !noMap" class="vp-body tp-map" data-k="course-map">
        <div v-if="focus" class="tp-back"><el-button size="small" text data-k="back-home" @click="emit('home')"><el-icon><Back /></el-icon>{{ $t('org.allCourses') }}</el-button></div>
        <template v-if="desk.on && !focus">
          <SchoolWork ref="swEl" @open="openLocal" />
          <div class="vp-row local-row">
            <input ref="pkgFile" type="file" accept=".vfhw,.vfplant" style="display: none" @change="pickPkg" />
            <el-button size="small" @click="pkgFile?.click()"><el-icon><FolderOpened /></el-icon>{{ $t('common.openAssignmentPackage') }}</el-button>
            <span class="vp-small vp-muted">{{ $t('taskPanel.theCoursesBelowAreBundled') }}</span>
          </div>
        </template>
        <div v-if="!map.courses.length && !map.tasks.length && !loading && !focus" class="vp-empty">
          <template v-if="isTeacher()">{{ $t('taskPanel.thisIsTheCourseMap') }}</template>
          <template v-else>{{ $t('taskPanel.yourTeacherHasNotPublished') }}</template>
        </div>
        <div v-for="c in shownCourses" :key="c.class_id + c.course" class="course vp-card" :class="{ folded: !courseOpen(c) }" :data-course="c.course">
          <div class="vp-row sp chead" @click="toggleCourse(c)" :title="courseOpen(c) ? $t('common.collapse') : $t('taskPanel.expandThisCourseSChapters')">
            <span class="cname"><el-icon class="fold-i"><ArrowDown v-if="courseOpen(c)" /><ArrowRight v-else /></el-icon>{{ c.name }}</span>
            <span class="vp-small vp-muted">{{ c.class_name }}</span>
          </div>
          <div class="vp-row" style="margin: 6px 0 2px">
            <el-progress class="vp-grow" :percentage="c.total ? Math.round((c.done / c.total) * 100) : 0" :stroke-width="6" :show-text="false" />
            <span class="vp-small">{{ $t('taskPanel.n01Lessons', [c.done, c.total]) }}</span>
            <el-button v-if="c.next" size="small" type="primary" @click="open(c.next)">{{ c.done ? $t('common.continue') : $t('common.start') }}</el-button>
          </div>
          <div v-for="ch in (courseOpen(c) ? c.chapters : [])" :key="ch.id" class="chapter">
            <div class="chtitle">{{ ch.title }}</div>
            <div v-for="l in ch.lessons" :key="l.aid" class="lesson" :class="[l.state, { cur: l.aid === c.next, sel: l.aid === cur?.assignment?.id }]" :data-aid="l.aid"
                 @click="l.state !== 'locked' && open(l.aid)" :title="l.state === 'locked' ? (l.prereq?.length ? $t('taskPanel.completePrerequisiteLesson0To', [l.prereq.join($t('common.k360'))]) : $t('taskPanel.completeThePreviousLessonWith')) : ''">
              <el-icon class="st"><Lock v-if="l.state === 'locked'" /><CircleCheckFilled v-else-if="l.state === 'done'" /><VideoPlay v-else /></el-icon>
              <span class="lt vp-grow">{{ l.title }}</span>
              <span class="kind" :class="l.kind">{{ KIND_CN[l.kind] || l.kind }}</span>
              <span class="sc" :class="scoreCls(l.best)">{{ l.best ?? '' }}</span>
            </div>
          </div>
        </div>
        <template v-if="map.tasks.length && (!focus || focus === 'tasks')">
          <div class="vp-sec" style="margin-top: 10px"><div class="lbl">{{ focus ? $t('common.schoolAssignments') : $t('taskPanel.standaloneTasksAssignments') }}</div></div>
          <div class="vp-list">
            <div v-for="a in map.tasks" :key="a.id" class="vp-item task-card" :class="{ sel: a.id === cur?.assignment?.id }" :data-aid="a.id" :data-kind="a.kind" @click="open(a.id)">
              <div class="vp-row sp"><span class="t"><span class="kind" :class="a.kind">{{ KIND_CN[a.kind] || 'PLC' }}</span> {{ a.title }}</span>
                <el-tag v-if="a.best !== null && a.best !== undefined" size="small" :type="a.best >= 99.5 ? 'success' : a.best >= 60 ? 'warning' : 'danger'">{{ $t('common.n0Min', [a.best]) }}</el-tag>
                <el-tag v-else size="small" type="info">{{ a.submissions ? $t('courseHome.awaitingGrading') : $t('courseHome.notSubmitted') }}</el-tag></div>
              <div class="vp-small vp-muted" style="margin-top: 4px">{{ a.class_name }}<template v-if="a.kind !== 'factory'"> · {{ a.scene_name }}</template>{{ a.due ? $t('schoolWork.due') + a.due : '' }}</div>
              <div class="vp-row" style="margin-top: 6px">
                <el-progress class="vp-grow" :percentage="Math.round(a.best || 0)" :stroke-width="5" :show-text="false" />
                <el-button size="small" type="primary" plain @click.stop="open(a.id)">{{ a.kind === 'factory' ? $t('courseHome.viewRequirements') : a.submissions ? $t('common.continue') : $t('common.start') }}</el-button>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- Lesson -->
      <div v-if="cur" class="tp-detail" data-k="lesson-detail">
        <div v-if="splitOn" class="vp-head dtl-head">
          <span class="kind big" :class="cur.kind">{{ KIND_CN[cur.kind] || cur.kind }}</span>
          <span class="ttl">{{ cur.assignment.title }}</span>
          <span v-if="cur.course" class="vp-small vp-muted">{{ cur.course.name }}</span>
        </div>
        <!-- First sandbox visit guide: cards in the left sidebar, without covering the canvas (console and 3D buttons remain clickable). Each step references buttons that are available and clickable at that point. -->
        <div v-if="tourOpen" class="vp-card tour-card" :data-tour-step="tourStep" :data-tour-kind="tourKind">
          <div class="vp-row sp"><b class="vp-small">{{ $t('taskPanel.yourFirstSandboxCompleteA') }}</b><span class="vp-small vp-muted">{{ tourStep + 1 }}/{{ TOUR.length }}</span></div>
          <div class="tour"><b>{{ TOUR[tourStep].t }}</b><p>{{ TOUR[tourStep].d }}</p></div>
          <div class="vp-row" style="justify-content: flex-end">
            <el-button v-if="TOUR[tourStep].go && inSandbox" size="small" type="primary" plain data-k="tour-go" @click="tourGo(TOUR[tourStep].go)">{{ TOUR[tourStep].goText }}</el-button>
            <span class="vp-grow" />
            <el-button size="small" text @click="endTour">{{ $t('common.skip') }}</el-button>
            <el-button v-if="tourStep" size="small" @click="tourStep--">{{ $t('common.back') }}</el-button>
            <el-button size="small" type="primary" data-k="tour-next" @click="tourStep < TOUR.length - 1 ? tourStep++ : endTour()">{{ tourStep < TOUR.length - 1 ? $t('common.next') : $t('common.gotIt') }}</el-button>
          </div>
        </div>
        <div v-if="watching" class="banner watch">{{ $t('taskPanel.observing') }} <b>{{ cur.username }}</b> {{ $t('taskPanel.sSandboxReadOnlyThis') }}</div>
        <div v-if="live.takeover && !watching" class="banner warn">{{ $t('taskPanel.n0HasBeenControllingYour', [live.takeover.name, live.takeover.since]) }}</div>
        <div v-if="cur.viewer === 'trial'" class="banner">{{ $t('taskPanel.teacherTrialSubmissionsShowYour') }}</div>

        <!-- Factory submission assignment: no sandbox; select a factory from "My Factories" to submit -->
        <div v-if="isFactory && !watching" class="vp-card fac-card" data-k="factory-submit">
          <template v-if="desk.on">
            <div class="vp-row sp"><b>{{ $t('taskPanel.selectAFactoryFromMy') }}</b>
              <el-button size="small" text type="primary" data-k="goto-mine" @click="goMine"><el-icon><OfficeBuilding /></el-icon>{{ $t('taskPanel.openMyFactories') }}</el-button></div>
            <div class="vp-row" style="margin-top: 6px">
              <el-select v-model="fac.plant" :placeholder="$t('taskPanel.chooseFromMyFactories')" size="small" class="fac-sel" data-k="factory-pick" :loading="fac.loading" :no-data-text="$t('common.noFactoriesYet')">
                <el-option v-for="p in fac.list" :key="p.id" :value="p.id" :label="p.name">
                  <span>{{ p.name }}</span><span class="vp-muted vp-small" style="float: right; margin-left: 12px">{{ $t('welcome.n0Objects1Plcs', [p.blocks, p.plcs]) }}</span></el-option>
              </el-select>
              <el-tooltip :content="$t('taskPanel.runTheTeacherSAutomated')" placement="bottom">
                <span><el-button size="small" :disabled="!fac.plant || !!facBlock" :loading="busy === 'submit'" data-k="factory-check" @click="submit">{{ $t('taskPanel.checkLocally') }}</el-button></span></el-tooltip>
              <el-tooltip :content="facBlock || (cur.desktop?.school ? $t('taskPanel.submitThisFactoryModelEach') : $t('taskPanel.localAssignmentsAreNotSubmitted'))" placement="bottom">
                <span><el-button v-if="cur.desktop?.school" size="small" type="primary" :disabled="!fac.plant || !!facBlock" :loading="busy === 'school'" data-k="factory-submit-btn" @click="submitSchool">
                  <el-icon><Promotion /></el-icon>{{ $t('sections.submitToTeacher') }}</el-button></span></el-tooltip>
              <el-button size="small" :disabled="!fac.plant" :loading="busy === 'export'" @click="exportPkg" :title="$t('taskPanel.exportAnAssignmentPackageVfhw')"><el-icon><Download /></el-icon>{{ $t('sections.exportAssignmentPackage') }}</el-button>
            </div>
            <div v-if="!fac.list.length && !fac.loading" class="vp-small" style="margin-top: 6px">{{ $t('taskPanel.youHaveNoFactoriesYet') }}</div>
            <div v-else class="vp-small vp-muted" style="margin-top: 6px">{{ $t('taskPanel.youSubmitTheFactoryAs') }}</div>
          </template>
          <template v-else>
            <b>{{ $t('taskPanel.thisFactoryDesignAssignmentRequires') }}</b>
            <div class="vp-small" style="margin-top: 4px">{{ $t('taskPanel.installTheHoneyfactoryDesktopClient') }}</div>
          </template>
        </div>

        <div v-if="!watching && !isFactory" class="vp-head acts">
          <el-tag v-if="noSandbox" size="small" effect="plain" data-k="quiz-tag">{{ cur.kind === 'mes' ? $t('taskPanel.completeTheStepsInMes') : $t('taskPanel.answerBelowNoSandboxNeeded') }}</el-tag>
          <el-button v-else-if="!inSandbox" type="primary" size="small" :loading="busy === 'enter'" data-k="enter-lesson" @click="enter()"><el-icon><Position /></el-icon>{{ cur.sandbox === 'none' ? $t('taskPanel.startLesson') : $t('taskPanel.continueLesson') }}</el-button>
          <el-tag v-else size="small" type="success" effect="plain">{{ $t('taskPanel.youAreWorkingOnThis') }}</el-tag>
          <el-dropdown v-if="!isPlant && !noSandbox" size="small" trigger="click" @command="reset">
            <el-button size="small" :loading="busy === 'reset'" :disabled="cur.sandbox === 'none'">{{ $t('taskPanel.startOver') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item command="keep">{{ $t('taskPanel.resetEquipmentToItsInitial') }}</el-dropdown-item>
              <el-dropdown-item command="clear">{{ $t('taskPanel.startOverClearTheProgram') }}</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
          <el-button v-else-if="!noSandbox" size="small" :loading="busy === 'reset'" :disabled="cur.sandbox === 'none'" @click="reset('clear')">{{ $t('taskPanel.resetFactory') }}</el-button>
          <el-tooltip :content="submitBlock || (cur.desktop ? $t('taskPanel.runAndGradeLocallyAgainst') : $t('taskPanel.automaticallyRunAndGradeAgainst'))" placement="bottom">
            <span><el-button size="small" type="success" :loading="busy === 'submit'" data-k="submit-score" @click="submit" :disabled="!!submitBlock"><el-icon><Upload /></el-icon>{{ cur.desktop ? $t('taskPanel.gradeLocally') : $t('common.submitForGrading') }}</el-button></span>
          </el-tooltip>
          <el-button v-if="isPreview && cur.viewer === 'trial' && !noSandbox" size="small" type="warning" plain :loading="busy === 'ref'" :disabled="cur.sandbox === 'none'"
                     data-k="save-reference" :title="$t('taskPanel.saveYourCurrentModelProgram')" @click="saveReference">
            <el-icon><Medal /></el-icon>{{ $t('taskPanel.saveAsReferenceSolution') }}</el-button>
          <template v-if="cur.desktop">
            <el-tooltip :content="cur.desktop.school ? (cur.desktop.school.connected ? $t('taskPanel.packageYourLocalAssignmentAnd') : $t('taskPanel.signInToTheSchool')) : $t('taskPanel.localSelfStudyLessonExport')" placement="bottom">
              <span><el-button v-if="cur.desktop.school" size="small" type="primary" :loading="busy === 'school'" :disabled="!!submitBlock || !cur.desktop.school.connected" @click="submitSchool">
                <el-icon><Promotion /></el-icon>{{ $t('sections.submitToTeacher') }}</el-button></span>
            </el-tooltip>
            <el-button size="small" :loading="busy === 'export'" :disabled="cur.sandbox === 'none' && !noSandbox" @click="exportPkg" :title="$t('taskPanel.exportAnAssignmentPackageVfhw')"><el-icon><Download /></el-icon>{{ $t('sections.exportAssignmentPackage') }}</el-button>
          </template>
          <el-button v-if="cur.tour && !guide.on && !watching" size="small" text type="primary" data-k="start-tour" :title="$t('taskPanel.followAStepByStep')" @click="restartTour">
            <el-icon><Guide /></el-icon>{{ $t('taskPanel.followTutorial') }}</el-button>
          <el-button v-if="cur.sandbox !== 'none' && !watching && !noSandbox" size="small" text data-k="hint-next" :loading="busy === 'hint'" :title="$t('taskPanel.getTheNextStepBased')" @click="hintNext">
            <el-icon><Opportunity /></el-icon>{{ $t('taskPanel.showNextStep') }}</el-button>
          <el-button v-if="cur.assignment.tutor" size="small" text @click="openTutor" :title="$t('taskPanel.openTheAiTutorIn')"><el-icon><ChatDotRound /></el-icon>{{ $t('taskPanel.askAiTutor') }}</el-button>
          <span class="vp-grow" />
          <span v-if="!noSandbox" class="vp-small vp-muted" data-k="lesson-status"><span class="vp-dot" :class="{ on: live.running }" /> {{ SANDBOX_CN[cur.sandbox] }}<template v-if="live.plc"> · <span data-k="plc-block" :title="plcTitle">{{ live.plc_block?.name || 'PLC' }}</span> {{ plcText }}</template></span>
        </div>
        <div v-if="busy === 'submit'" class="banner run">{{ $t('taskPanel.runningAgainst01S', [isFactory ? $t('taskPanel.teacherSAutomatedChecks') : $t('taskPanel.gradingCriteria'), elapsed, isFactory ? $t('taskPanel.runYourFactoryLocallyWith') : isPlant ? $t('taskPanel.theServerRunsYourFactory') : $t('taskPanel.testStartStopEStop')]) }}</div>
        <div v-if="busy === 'school'" class="banner run">{{ $t('taskPanel.submittingToTheTeacher0', [elapsed, isFactory ? $t('taskPanel.checkYourFactory') : $t('taskPanel.grading')]) }}</div>
        <div v-if="cur.course && !splitOn" class="crumb vp-small vp-muted">{{ cur.course.name }} · {{ cur.scene.kind_cn }}<template v-if="cur.best !== null && cur.best !== undefined"> {{ $t('taskPanel.best') }} <b>{{ cur.best }}</b> {{ $t('courseEditor.points') }}</template>
          <template v-if="cur.limits?.max_subs"> {{ $t('taskPanel.submissions01', [cur.limits.used, cur.limits.max_subs]) }}</template></div>
        <div v-else-if="splitOn && (cur.best !== null && cur.best !== undefined || cur.limits?.max_subs || cur.assignment.due)" class="crumb vp-small vp-muted">
          <template v-if="cur.best !== null && cur.best !== undefined">{{ $t('taskPanel.max') }} <b>{{ cur.best }}</b> {{ $t('courseEditor.points') }} </template>
          <template v-if="cur.limits?.max_subs"> {{ $t('taskPanel.submissions01', [cur.limits.used, cur.limits.max_subs]) }}</template>
          <template v-if="cur.assignment.due"> {{ $t('taskPanel.due0', [cur.assignment.due]) }}</template></div>

        <!-- Next steps: explain when the PLC has no program / is stopped; do not treat this as an alarm -->
        <div v-if="nextStep" class="vp-card next-step" data-k="next-step">
          <el-icon class="ns-i"><InfoFilled /></el-icon>
          <span class="vp-grow">{{ nextStep.text }}</span>
          <el-button v-if="nextStep.go && inSandbox" size="small" type="primary" plain @click="nextStep.go()">{{ nextStep.btn }}</el-button>
        </div>

        <!-- 4.5 "Suggest Next Step": use the checklist (PLC lessons) or targets (production line lessons) to suggest what to do next -->
        <div v-if="hintBox" class="vp-card next-step hint-box" data-k="hint-box">
          <el-icon class="ns-i"><Opportunity /></el-icon>
          <span class="vp-grow" v-html="hintBox" />
          <el-button size="small" text @click="hintBox = ''">{{ $t('common.gotIt') }}</el-button>
        </div>

        <!-- Troubleshooting: teacher-injected failure -->
        <div v-if="live.faults_active && !watching" class="vp-card fault-card">
          <div class="vp-row"><el-icon class="vp-fail"><WarningFilled /></el-icon><b>{{ $t('taskPanel.equipmentFailure') }}</b><span class="vp-small vp-muted">{{ $t('taskPanel.identifyTheComponentAndThe') }}</span></div>
          <div class="vp-row" style="margin-top: 6px">
            <el-select v-model="dg.comp" size="small" :placeholder="$t('taskPanel.component')" filterable style="width: 130px">
              <el-option v-for="c in live.diagnose?.comps || []" :key="c.id" :value="c.id" :label="c.label && c.label !== c.id ? `${c.id} ${c.label}` : c.id" />
            </el-select>
            <el-select v-model="dg.kind" size="small" :placeholder="$t('taskPanel.fault')" style="width: 140px">
              <el-option v-for="k in live.diagnose?.kinds || []" :key="k.kind" :value="k.kind" :label="k.label" />
            </el-select>
            <el-button size="small" type="danger" plain :disabled="!dg.comp || !dg.kind" :loading="busy === 'dg'" @click="diagnose">{{ $t('taskPanel.foundIt') }}</el-button>
          </div>
          <div v-if="dg.msg" class="vp-small" :class="dg.ok ? 'vp-pass' : 'vp-fail'" style="margin-top: 4px">{{ dg.msg }}</div>
        </div>

        <el-tabs v-model="tab" class="tp-tabs">
          <el-tab-pane :label="isFactory ? $t('publishWizard.requirements') : $t('common.assignmentBrief')" name="task">
            <div class="vp-body">
              <div class="vp-row sp" style="margin-bottom: 4px"><span /><el-button size="small" text @click="bookOpen = true"><el-icon><FullScreen /></el-icon>{{ $t('taskPanel.zoomIn') }}</el-button></div>
              <div v-if="cur.assignment.descr" class="vp-card vp-small" style="margin-bottom: 10px">{{ $t('taskPanel.teacherSNotes0', [cur.assignment.descr]) }}</div>
              <div class="vp-md book-md" v-html="md(cur.scene.brief_md || cur.scene.task_md || $t('taskPanel.noAssignmentBrief'))" />
              <el-collapse v-if="cur.scene.hints?.length" style="margin-top: 8px">
                <el-collapse-item v-for="(h, i) in cur.scene.hints" :key="i" :title="$t('taskPanel.hint0UseIfStuck', [i + 1])"><div class="vp-md" v-html="md(h)" /></el-collapse-item>
              </el-collapse>
            </div>
          </el-tab-pane>
          <el-tab-pane :label="isFactory ? $t('common.automatedChecks') : isQuiz ? $t('taskPanel.questionsAnswers') : cur.kind === 'mes' ? $t('publishWizard.check') : isPlant ? $t('taskPanel.objectivesAnswers') : liveCheck ? $t('taskPanel.gradingCriteriaChecklist') : $t('taskPanel.gradingCriteria')" name="goals">
            <div class="vp-body" data-tour="goal-list">
              <template v-if="liveCheck">
                <Checklist :key="cur.pid" :pid="cur.pid" show-submit @submit="submit" />
              </template>
              <template v-else>
              <div v-if="isFactory" class="vp-small vp-muted" style="margin-bottom: 8px">
                {{ rules.length ? $t('taskPanel.afterSubmissionTheServerRuns', [rules.length, cur.scene.hours]) : $t('taskPanel.thisAssignmentHasNoAutomated') }}</div>
              <div v-else-if="isPlant && cur.kind === 'point' && !rules.some((r: any) => r.kind !== 'answer')" class="vp-small vp-muted" style="margin-bottom: 8px" data-k="goals-intro">
                {{ $t('taskPanel.findAndClickTheRequired') }}</div>
              <div v-else-if="isPlant" class="vp-small vp-muted" style="margin-bottom: 8px" data-k="goals-intro">
                {{ $t('taskPanel.openTheSandboxToEdit', [cur.scene.time_h || 8]) }}
                <template v-if="progress.cost !== undefined && progress.cost !== null && rules.some((r: any) => r.kind === 'budget' || r.metric === 'cost')"> {{ $t('taskPanel.currentInvestment') }} <b>{{ progress.cost }}</b> {{ $t('taskPanel.cny10000') }}</template>
              </div>
              <div v-else-if="isQuiz" class="vp-small vp-muted" style="margin-bottom: 8px" data-k="goals-intro">{{ $t('taskPanel.yourAnswersAreSavedAutomatically', [cur.desktop ? $t('taskPanel.gradeLocally') : $t('common.submitForGrading'), cur.desktop ? $t('taskPanel.gradedImmediatelyOnThisComputer') : '']) }}</div>
              <div v-else-if="cur.kind === 'mes'" class="vp-small vp-muted" style="margin-bottom: 8px" data-k="goals-intro">{{ $t('taskPanel.completeTheFollowingStepsIn') }}</div>
              <div v-else-if="!isFactory" class="vp-small vp-muted" style="margin-bottom: 8px" data-k="goals-intro">{{ $t('taskPanel.afterSubmissionTheSystemTest') }}</div>
              <div v-if="isPlant && progress.locked?.length" class="vp-card locked-warn" data-k="locked-warn">
                <b>{{ $t('taskPanel.note') }}</b>{{ $t('taskPanel.n0TheLiveFiguresBelow', [progress.locked.join($t('common.k344'))]) }}</div>
              <div v-for="r in rules" :key="r.key" class="goal vp-card" :data-rule="r.key">
                <div class="vp-row sp">
                  <span class="gl" data-k="goal-title"><el-icon v-if="goalOk(r) === true" class="vp-pass"><CircleCheckFilled /></el-icon><el-icon v-else-if="goalOk(r) === false" class="vp-fail"><WarningFilled /></el-icon>{{ r.title || r.label }}</span>
                  <span class="vp-small vp-muted">{{ $t('common.n0Min', [fmtNum(r.weight)]) }}</span>
                </div>
                <template v-if="r.kind === 'answer'">
                  <div v-if="r.goal && r.goal !== (r.title || r.label)" class="vp-small vp-muted goal-q" data-k="goal-desc">{{ r.goal }}</div>
                  <el-checkbox-group v-if="r.qtype === 'multi'" :model-value="answers[r.key] || []" :disabled="watching" @change="(v: any) => saveAnswer(r.key, v)" class="choices" data-k="q-multi">
                    <el-checkbox v-for="(c, i) in r.choices" :key="i" :value="i" size="small">{{ c }}</el-checkbox>
                  </el-checkbox-group>
                  <el-radio-group v-else-if="r.qtype === 'tf'" :model-value="answers[r.key]" :disabled="watching" @change="(v: any) => saveAnswer(r.key, v)" class="choices tf" data-k="q-tf">
                    <el-radio :value="true" size="small">{{ $t('courseEditor.true') }}</el-radio><el-radio :value="false" size="small">{{ $t('courseEditor.false') }}</el-radio>
                  </el-radio-group>
                  <div v-else-if="r.qtype === 'number'" class="vp-row" style="margin-top: 4px" data-k="q-number">
                    <el-input-number :model-value="answers[r.key] ?? undefined" size="small" :disabled="watching" controls-position="right" :step="0.1" style="width: 160px"
                                     :placeholder="$t('taskPanel.enterANumber')" @change="(v: any) => saveAnswer(r.key, v ?? null)" />
                    <span v-if="r.unit" class="vp-small vp-muted">{{ r.unit }}</span>
                  </div>
                  <el-radio-group v-else-if="r.choices" :model-value="answers[r.key]" :disabled="watching" @change="(v: any) => saveAnswer(r.key, v)" class="choices">
                    <el-radio v-for="(c, i) in r.choices" :key="i" :value="i" size="small">{{ c }}</el-radio>
                  </el-radio-group>
                  <div v-else-if="r.pick" class="vp-row" style="margin-top: 4px">
                    <el-button v-if="!watching" size="small" :type="picking === r.key ? 'warning' : 'default'" @click="startPick(r)"><el-icon><Aim /></el-icon>{{ picking === r.key ? $t('taskPanel.clickEquipmentInTheGraph') : $t('taskPanel.selectInGraph') }}</el-button>
                    <span v-if="answers[r.key]" class="vp-small">{{ $t('taskPanel.selected') }}<b>{{ answers[r.key] }}</b></span>
                    <el-button v-if="answers[r.key] && !watching" size="small" text @click="saveAnswer(r.key, null)">{{ $t('taskPanel.clear') }}</el-button>
                  </div>
                </template>
                <div v-else-if="isPlant" class="vp-small goal-v" data-k="goal-desc">
                  <span v-if="r.goal && r.goal !== (r.title || r.label)" class="vp-muted">{{ $t('taskPanel.target0', [r.goal]) }}</span><span v-else-if="!r.goal" class="vp-muted">{{ $t('taskPanel.target0', [humanRule(r)]) }}</span>
                  <span v-if="live.progress">{{ $t('taskPanel.n0Current', [r.goal && r.goal !== (r.title || r.label) || !r.goal ? ' · ' : '']) }} <b>{{ liveRow(r)?.value_text ?? fmtNum(liveRow(r)?.value) }}</b>{{ liveRow(r)?.exact ? '' : (liveRow(r)?.note ? $t('common.k459') + liveRow(r).note + $t('common.k460') : $t('taskPanel.estimated')) }}</span>
                </div>
                <div v-else-if="!isFactory" class="vp-small vp-muted goal-v" data-k="goal-desc">{{ r.goal && r.goal !== (r.title || r.label) ? r.goal : humanRule(r) }}<template v-if="r.how"><br>{{ $t('taskPanel.howToTest0', [r.how]) }}</template></div>
              </div>
              </template>
            </div>
          </el-tab-pane>
          <el-tab-pane v-if="liveCheck" :label="$t('common.logs')" name="log">
            <div class="vp-body log-body"><RunLog :key="cur.pid" :pid="cur.pid" /></div>
          </el-tab-pane>
          <el-tab-pane v-if="!isPlant && !isFactory && !noSandbox" :label="$t('taskPanel.iOTable')" name="io">
            <div class="vp-body">
              <div v-if="narrow" class="io-cards">
                <div v-for="e in cur.scene.io" :key="e.name" class="io-card">
                  <div class="vp-row sp"><b class="mono">{{ e.name }}</b><span class="mono vp-muted">{{ e.addr }}</span>
                    <span><template v-if="live.io && e.name in live.io"><span v-if="(e.type || 'BOOL') === 'BOOL'" class="vp-dot" :class="{ on: !!live.io[e.name], out: e.dir === 'out' }" />
                      <span v-else class="mono">{{ fmtVal(live.io[e.name]) }}</span></template></span></div>
                  <div class="vp-small vp-muted">{{ e.dir === 'in' ? $t('common.input') : $t('common.output') }} · {{ e.type || 'BOOL' }}<template v-if="e.contact === 'NC'"> · <b class="ncell">{{ $t('taskPanel.nc1WhenNotActuated') }}</b></template><template v-if="e.desc || e.comment"> · {{ e.desc || e.comment }}</template></div>
                </div>
              </div>
              <table v-else class="vp-tbl io-tbl">
                <tr><th>{{ $t('common.name') }}</th><th>{{ $t('common.direction') }}</th><th>{{ $t('common.address') }}</th><th>{{ $t('common.type') }}</th><th :title="$t('taskPanel.nc1WhenNotPressed')">{{ $t('common.contact') }}</th><th :title="$t('taskPanel.valueWhenNotActuatedAnd')">{{ $t('taskPanel.notActuated') }}</th><th>{{ $t('commandsCore.current') }}</th><th>{{ $t('common.description') }}</th></tr>
                <tr v-for="e in cur.scene.io" :key="e.name">
                  <td class="mono">{{ e.name }}</td><td>{{ e.dir === 'in' ? $t('common.input') : $t('common.output') }}</td><td class="mono">{{ e.addr }}</td><td>{{ e.type || 'BOOL' }}</td>
                  <td :class="{ ncell: e.contact === 'NC' }" :title="e.contact === 'NC' ? $t('taskPanel.n0IsNc1When', [e.name]) : ''">{{ e.contact === 'NC' ? $t('common.nc') : e.contact === 'NO' ? $t('common.no3') : '—' }}</td>
                  <td class="mono">{{ e.dir === 'in' && 'idle' in e ? (e.idle ? 1 : 0) : '' }}</td>
                  <td><template v-if="live.io && e.name in live.io">
                    <span v-if="(e.type || 'BOOL') === 'BOOL'" class="vp-dot" :class="{ on: !!live.io[e.name], out: e.dir === 'out' }" />
                    <span v-else class="mono">{{ fmtVal(live.io[e.name]) }}</span></template><span v-else class="vp-muted">—</span></td>
                  <td class="vp-muted">{{ e.desc || e.comment || e.comp || '' }}</td>
                </tr>
              </table>
              <div class="vp-small vp-muted" style="margin-top: 6px">{{ $t('taskPanel.iODirectionIsRelative') }}</div>
              <div v-if="live.plc_block" class="vp-small vp-muted" style="margin-top: 4px" data-k="io-plc-note">
                {{ $t('taskPanel.theseIOAreConnected') }} <b>{{ live.plc_block.name }}</b>{{ $t('taskPanel.n0ThisIsThePlc', [live.plc_block.id, plcDevices]) }}</div>
            </div>
          </el-tab-pane>
          <el-tab-pane :label="$t('taskPanel.grades') + (cur.submissions.length ? $t('common.n0', [cur.submissions.length]) : '')" name="score">
            <div class="vp-body">
              <div v-if="schoolRes?.queued" class="vp-card school-res" data-k="school-queued">
                <div class="vp-row sp"><b>{{ $t('taskPanel.queuedSubmitsAutomaticallyWhenOnline') }}</b><span class="vp-small vp-muted">{{ schoolRes.created }}</span></div>
                <div class="vp-small vp-muted" style="margin-top: 4px">{{ schoolRes.msg || $t('taskPanel.cannotConnectToTheSchool') }}</div>
              </div>
              <div v-else-if="schoolRes" class="vp-card school-res" data-k="school-res">
                <div class="vp-row sp"><b>{{ schoolRes.status === 'submitted' ? $t('taskPanel.submittedToTeacher') : $t('taskPanel.schoolServerGrading') }}</b><span class="vp-small vp-muted">{{ schoolRes.created }} · {{ schoolRes.server }}</span></div>
                <div v-if="schoolRes.status === 'submitted'" class="vp-small" style="margin-top: 4px">{{ $t('taskPanel.yourTeacherHasReceivedYour') }}</div>
                <div v-else class="vp-row" style="margin-top: 4px"><span class="vp-score" :class="scoreCls(schoolRes.score)">{{ schoolRes.score ?? '—' }}<small> / 100</small></span>
                  <span class="vp-small vp-muted">{{ $t('taskPanel.theServerReranYour0', [isFactory ? $t('common.factory') : isPlant ? $t('taskPanel.modelAndAnswers') : $t('common.program'), isFactory ? $t('taskPanel.automaticallyCheckedTeacherReviewPen') : '', schoolRes.local_score ?? '—']) }}</span></div>
                <div v-if="schoolRes.error" class="vp-fail vp-small">{{ schoolRes.error }}</div>
              </div>
              <!-- School server submission: teacher's score and feedback (school assignments completed in the client) -->
              <div v-if="school.submissions.length" class="vp-sec" data-k="school-results">
                <div class="lbl">{{ $t('taskPanel.officialGradeSchoolServer') }}</div>
                <div v-for="s in school.submissions.slice(0, showAll ? 20 : 3)" :key="'r' + s.id" class="vp-card sub school-sub" :data-sid="s.id">
                  <div class="vp-row sp">
                    <span class="vp-score" :class="scoreCls(s.score)">{{ s.score ?? '—' }}<small> / 100</small></span>
                    <span class="vp-small vp-muted">{{ s.created }} · {{ s.status === 'reviewed' ? $t('taskPanel.gradedByTeacher') : s.status === 'submitted' ? $t('courseHome.awaitingGrading') : $t('taskPanel.automaticGrading') }}</span>
                  </div>
                  <div v-if="s.override_score !== null && s.override_score !== undefined" class="vp-small">{{ $t('taskPanel.teacherSScore') }}<b>{{ s.override_score }}</b>{{ s.auto_score !== null && s.auto_score !== undefined ? $t('taskPanel.automaticCheck0', [s.auto_score]) : '' }}</div>
                  <div v-if="s.comment" class="vp-small teacher-cmt">{{ $t('taskPanel.teacherSFeedback0', [s.comment]) }}</div>
                  <!-- 4.6.2 Correct answers and explanations supplied by the school server per teacher settings -->
                  <div v-if="s.reveal && s.reveal.state !== 'shown'" class="vp-small vp-muted reveal-note" data-k="reveal-note" :data-state="s.reveal.state">{{ revealNote(s.reveal) }}</div>
                  <template v-for="(d, j) in (s.details || []).filter((x: any) => x.kind === 'answer' && 'your' in x)" :key="'q' + j">
                    <div class="det" :class="d.ok === false ? 'bad' : 'good'" :data-rule="d.key">
                      <div class="vp-row sp"><span><el-icon><CircleCheckFilled v-if="d.ok !== false" /><CircleCloseFilled v-else /></el-icon> {{ d.label || d.key }}</span>
                        <span class="num">{{ fmtNum(d.points ?? d.score) }}<span class="vp-muted"> / {{ fmtNum(d.weight) }}</span></span></div>
                      <QuizReveal :d="d" />
                    </div>
                  </template>
                </div>
              </div>
              <div v-else-if="school.offline && cur.desktop?.school" class="vp-small vp-muted" style="margin-bottom: 6px">{{ $t('taskPanel.cannotConnectToTheSchool2') }}</div>
              <div v-if="cur.desktop && cur.submissions.length" class="vp-small vp-muted" style="margin-bottom: 6px">{{ $t('taskPanel.theScoreBelowIsA') }}</div>
              <div v-if="!cur.submissions.length && !school.submissions.length" class="vp-empty">{{ $t('taskPanel.notSubmittedYet0', [emptyScoreText]) }}</div>
              <div v-if="cur.submissions.length && cur.submissions[0].score >= 60 && cur.next" class="vp-card next-card">
                <span>{{ $t('taskPanel.lessonPassedNextLesson') }}<b>{{ cur.next.title }}</b></span>
                <el-button size="small" type="primary" @click="open(cur.next.id)">{{ $t('courseHome.nextLesson') }}</el-button>
              </div>
              <template v-for="(s, i) in cur.submissions" :key="s.id">
                <div class="vp-card sub" v-if="i === 0 || showAll" :data-sid="s.id">
                  <div class="vp-row sp">
                    <span v-if="s.status === 'submitted'" class="vp-score wait">{{ $t('courseHome.awaitingGrading') }}</span>
                    <span v-else class="vp-score" :class="s.score >= 60 ? 'vp-pass' : 'vp-fail'">{{ s.score ?? '—' }}<small> / {{ s.max || 100 }}</small></span>
                    <span class="vp-small vp-muted">{{ cur.desktop ? $t('taskPanel.localEstimatedScore') : $t('taskPanel.submittedOn') }}{{ s.created }}<template v-if="s.late"> {{ $t('taskPanel.late') }}</template><template v-if="s.trial"> {{ $t('taskPanel.practice') }}</template></span>
                  </div>
                  <div v-if="s.error" class="vp-fail vp-small">{{ s.error }}</div>
                  <div v-if="s.override_score !== null && s.override_score !== undefined" class="vp-small">{{ $t('taskPanel.teacher01', [s.auto_score === null || s.auto_score === undefined ? $t('taskPanel.grade') : $t('taskPanel.changeGrade'), s.override_score]) }}<template v-if="s.auto_score !== null && s.auto_score !== undefined">{{ $t('taskPanel.automatic0', [s.auto_score]) }}</template></div>
                  <div v-if="s.comment" class="vp-small teacher-cmt" style="margin: 4px 0">{{ $t('taskPanel.teacherSFeedback0', [s.comment]) }}</div>
                  <div v-if="s.hidden" class="vp-small vp-muted">{{ $t('taskPanel.yourTeacherHasHiddenThe') }}</div>
                  <div v-if="s.reveal && s.reveal.state !== 'shown'" class="vp-small vp-muted reveal-note" data-k="reveal-note" :data-state="s.reveal.state">{{ revealNote(s.reveal) }}</div>
                  <div v-for="(d, j) in s.details" :key="j" class="det" :class="d.ok === false || d.pass === false ? 'bad' : 'good'" :data-rule="d.key">
                    <div class="vp-row sp"><span><el-icon><CircleCheckFilled v-if="d.ok !== false && d.pass !== false" /><CircleCloseFilled v-else /></el-icon> {{ d.label || d.key }}</span>
                      <span class="num">{{ fmtNum(d.points ?? d.score) }}<span class="vp-muted"> / {{ fmtNum(d.weight) }}</span></span></div>
                    <QuizReveal v-if="d.kind === 'answer' && 'your' in d" :d="d" />
                    <div v-else class="vp-small vp-muted">{{ $t('taskPanel.requirement0Result1', [d.goal && d.goal !== (d.label || d.key) ? d.goal : humanRule(d), d.value_text && d.kind !== 'answer' ? d.value_text : humanValue(d)]) }}<template v-if="(d.ok === false || d.pass === false) && d.desc"> · {{ d.desc }}</template></div>
                    <div v-if="s.rule_comments?.[d.key]" class="vp-small rc">{{ $t('taskPanel.teacher0', [s.rule_comments[d.key]]) }}</div>
                  </div>
                </div>
              </template>
              <el-button v-if="cur.submissions.length > 1 || school.submissions.length > 3" size="small" text @click="showAll = !showAll">{{ showAll ? $t('taskPanel.showLatestOnly') : $t('taskPanel.showAllSubmissions') }}</el-button>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
      <div v-else-if="splitOn" class="tp-detail tp-pick" data-k="lesson-pick">
        <div class="vp-empty">
          <el-icon :size="34"><Reading /></el-icon>
          <div style="margin-top: 8px">{{ $t('taskPanel.selectALessonOnThe') }}</div>
          <div v-if="!desk.on && isStu" class="vp-small" style="margin-top: 10px">{{ $t('taskPanel.wantToBuildAFactory') }}</div>
        </div>
      </div>
    </div>

    <el-dialog v-model="bookOpen" :title="cur?.assignment.title" width="760px" append-to-body :modal="false" draggable class="book-dlg">
      <div v-if="cur" class="vp-md book" v-html="md(cur.scene.brief_md || cur.scene.task_md || '')" />
    </el-dialog>
    <PackageOpen ref="pkgEl" v-model="pkgDlg" @own="ownPkg" />
    <PasswordDialog v-model="pwOpen" :title="$t('teach.changeYourPasswordFirst')" :later-text="$t('common.maybeLater')" :intro="$t('teach.youAreUsingTheInitial')" @later="pwLater" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { desk, get, post, put, session } from '../../api';
import PasswordDialog from '../../components/PasswordDialog.vue';
import { md } from '../../editor/md';
import { ed, loadModel } from '../../editor/store';
import { fmtNum, fmtVal, humanRule, humanValue, isStudent, isTeacher, PLC_CN, poll, SANDBOX_CN, saveFile } from './util';
import PackageOpen from './PackageOpen.vue';
import Checklist from './Checklist.vue';
import RunLog from './RunLog.vue';
import { hasActiveTour, startTour, tour as guide } from './tour/tour';
import SchoolWork from './SchoolWork.vue';
import QuizReveal from './QuizReveal.vue';
import './panel.css';

/** split: wide teaching home layout—course map on the left, current lesson on the right; the narrow Workbench sidebar still shows one view at a time. */
/** 4.6 "Current Lesson" view on the course page: focus = show only this course's chapters ("<class ID>:<course>") or 'tasks' (school assignments); initialAid = lesson to open initially. */
const props = defineProps<{ pid?: string; split?: boolean; focus?: string; initialAid?: number; autoEnter?: boolean | 'start'; noMap?: boolean }>();
const emit = defineEmits<{ (e: 'open-plant', pid: string): void; (e: 'home'): void }>();
const KIND_CN: Record<string, string> = { cell: 'PLC', plant: $t('common.line'), diagnose: $t('common.troubleshooting'), factory: $t('common.factoryDesign'), quiz: $t('common.quiz'), point: $t('common.clickToSelect'), mes: 'MES' };
const shownCourses = computed(() => (props.focus && props.focus !== 'tasks' ? map.courses.filter((c: any) => `${c.class_id}:${c.course}` === props.focus) : props.focus === 'tasks' ? [] : map.courses));
// Avoid expanding all courses in long lists: expand the course containing the current lesson or the first unfinished course; click a course name to toggle.
const openCourses = reactive<Record<string, boolean>>({});
const ckey = (c: any) => `${c.class_id}:${c.course}`;
function courseOpen(c: any) {
  const k = ckey(c);
  if (k in openCourses) return openCourses[k];
  if (props.focus) return true;
  const curAid = cur.value?.assignment?.id;
  if (curAid) return (c.chapters || []).some((ch: any) => ch.lessons.some((l: any) => l.aid === curAid));
  if (c.total && c.done >= c.total) return map.courses.length === 1;           // Collapse completed courses.
  if (map.courses.length <= 3) return true;                                    // Expand all courses in short lists; otherwise expand only the first unfinished course.
  return map.courses.find((x: any) => x.done < x.total) === c;
}
function toggleCourse(c: any) { openCourses[ckey(c)] = !courseOpen(c); }
const isStu = computed(() => isStudent());
// 4.3: students program the PLC block (a separate device controlling the control unit via signal wires), not the unit itself.
const plcDevices = computed(() => (live.plc_block?.devices || []).map((d: any) => (d.name && d.name !== d.id ? $t('common.n012', [d.name, d.id]) : d.id)).join($t('common.k360')) || $t('taskPanel.labUnit'));
const plcTitle = computed(() => (live.plc_block ? $t('taskPanel.plcBlock01Controlling', [live.plc_block.name, live.plc_block.id, plcDevices.value]) : ''));
const plcText = computed(() => (live.plc === 'STOP' && !live.has_program ? $t('taskPanel.noProgramYet') : PLC_CN[live.plc] || live.plc));
// Five-step beginner guide: every referenced button is available and clickable at that step (verified by tests/guide_ui.js). go = "Take Me There": open the panel containing that button.
const plcId = computed(() => live.plc_block?.id || cur.value?.scene?.plc || 'PLC1');
const TOUR_CELL = computed(() => [
  { t: $t('taskPanel.n1ReadTheTaskBrief'), d: $t('taskPanel.theTaskBriefBelowExplains') },
  { t: $t('taskPanel.n2OpenPlcProgramming'), d: $t('taskPanel.clickPlcTheChipIcon', [plcId.value])
    + $t('taskPanel.thenClickProgrammingInThe'), go: 'editor', goText: $t('taskPanel.openProgrammingWindowDirectly') },
  { t: $t('taskPanel.n3WriteAndDownloadThe'), d: $t('taskPanel.writeLadderDiagramOrStructured'), go: 'editor', goText: $t('taskPanel.openProgrammingWindow') },
  { t: $t('taskPanel.n4UseTheControlPanel'), d: $t('taskPanel.theControlPanelFloatsAt'),
    go: 'console', goText: $t('workbench.openOperatorConsole') },
  { t: $t('taskPanel.n5SubmitForGrading'), d: $t('taskPanel.whenYouThinkItIs') },
]);
const TOUR_PLANT = [
  { t: $t('taskPanel.n1ReadTheTaskBrief'), d: $t('taskPanel.theTaskBriefBelowExplains2') },
  { t: $t('taskPanel.n2EditTheModel'), d: $t('taskPanel.clickAMachineOnThe') },
  { t: $t('taskPanel.n3RunAndCheckThe'), d: $t('taskPanel.clickRunInTheSecond') },
  { t: $t('taskPanel.n4AnswerTheQuestions'), d: $t('taskPanel.clickYourChoicesDirectlyIn') },
  { t: $t('taskPanel.n5SubmitForGrading'), d: $t('taskPanel.whenYouThinkYouHave') },
];
const tourKind = computed(() => (isPlant.value ? 'plant' : 'cell'));
const TOUR = computed<any[]>(() => (isPlant.value ? TOUR_PLANT : TOUR_CELL.value));
const map = reactive<any>({ courses: [], tasks: [] });
const cur = ref<any>(null);
const tab = ref('task');
const loading = ref(false);
const busy = ref('');
const showAll = ref(false);
const live = reactive<any>({ running: false, io: null, plc: null, plc_block: null, progress: null, has_program: false, takeover: null, faults_active: 0, diagnose: null, hint: '' });
const answers = reactive<Record<string, any>>({});
const picking = ref('');
const elapsed = ref(0);
const bookOpen = ref(false);
const tourOpen = ref(false);
const tourStep = ref(0);
const pwOpen = ref(false);
const dg = reactive<any>({ comp: '', kind: '', msg: '', ok: false });
const root = ref<HTMLElement | null>(null);
const narrow = ref(false);
const width = ref(0);
const fac = reactive<any>({ list: [], plant: '', loading: false });
const school = reactive<any>({ submissions: [], offline: false });
let stopLive: any = null, timer: any = null, ro: ResizeObserver | null = null;

const splitOn = computed(() => !!props.split && width.value >= 960);
const isPlant = computed(() => ['plant', 'diagnose', 'point'].includes(cur.value?.kind));
/** 4.6 Quiz lessons (quiz) / MES operation lessons (mes): no sandbox; answer and submit directly. */
const isQuiz = computed(() => cur.value?.kind === 'quiz');
const noSandbox = computed(() => ['quiz', 'mes'].includes(cur.value?.kind) || cur.value?.scene?.sandbox === false);
const isFactory = computed(() => cur.value?.kind === 'factory');
const isPreview = computed(() => String(cur.value?.assignment?.course || '').startsWith('_preview-'));     // "Preview as Student" while the teacher authors a course
const rules = computed(() => cur.value?.scene?.rules || []);
const progress = computed(() => live.progress || {});
/** Teacher observing a student's sandbox: show that student's tasks in a read-only panel. */
const watching = computed(() => cur.value?.viewer === 'teacher');
const inSandbox = computed(() => !!cur.value && props.pid === cur.value.pid);
const submitBlock = computed(() => {
  if (!cur.value) return '';
  if (cur.value.assignment.status !== 'published') return $t('taskPanel.thisTaskIsClosed');
  if (noSandbox.value) {
    const l = cur.value.limits;
    if (l?.max_subs && l.used >= l.max_subs && cur.value.viewer !== 'trial') return $t('taskPanel.noSubmissionsRemainingMaximum0', [l.max_subs]);
    return isQuiz.value && !rules.value.some((r: any) => answers[r.key] !== undefined) ? $t('taskPanel.answerTheQuestionsBeforeSubmitting') : '';
  }
  if (cur.value.sandbox === 'none') return $t('taskPanel.clickStartThisLessonFirst');
  if (!isPlant.value && !live.has_program) return $t('taskPanel.noProgramHasBeenDownloaded');
  const l = cur.value.limits;
  if (l?.max_subs && l.used >= l.max_subs && cur.value.viewer !== 'trial') return $t('taskPanel.noSubmissionsRemainingMaximum0', [l.max_subs]);
  return '';
});
const facBlock = computed(() => {
  if (!cur.value || !isFactory.value) return '';
  if (cur.value.assignment.status !== 'published') return $t('taskPanel.thisAssignmentIsClosed');
  const l = cur.value.limits;
  if (l?.max_subs && l.used >= l.max_subs && cur.value.viewer !== 'trial') return $t('taskPanel.noSubmissionsRemainingMaximum0', [l.max_subs]);
  return '';
});
const emptyScoreText = computed(() => (isFactory.value ? (desk.on ? $t('taskPanel.selectAFactoryFromMy2') : $t('taskPanel.selectAFactoryFromMy3'))
  : isPlant.value ? $t('taskPanel.afterEditingTheModelAnd') : $t('taskPanel.afterWritingYourProgramAnd')));
/** PLC lesson: sandbox is open but the PLC has no program / is stopped—a normal starting state. Tell students what to do next, not an alarm. */
const nextStep = computed<any>(() => {
  const c = cur.value;
  if (!c || watching.value || isPlant.value || isFactory.value || c.sandbox === 'none' || !live.plc_block) return null;
  if (!live.has_program) return { text: $t('taskPanel.nextProgramThePlcAnd'), btn: $t('taskPanel.openPlcPanel'), go: () => tourGo('plc') };
  if (live.plc && live.plc !== 'RUN') {
    if (live.plc === 'HALT') return { text: $t('taskPanel.thePlcIsPausedAt'), btn: $t('taskPanel.openPlcPanel'), go: () => tourGo('plc') };
    return { text: live.hint || $t('taskPanel.thePlcIsNotRunning'), btn: $t('taskPanel.openPlcPanel'), go: () => tourGo('plc') };
  }
  return null;
});
/** 4.5: in a PLC lesson sandbox, the grading criteria tab becomes a live checklist, with a separate "Log" tab. */
const liveCheck = computed(() => !!cur.value && !isPlant.value && !isFactory.value && cur.value.sandbox !== 'none' && !review.value);
const hintBox = ref('');
let hintN = 0;
const esc = (t: any) => String(t ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string));
/** "Suggest Next Step": use the first unchecked checklist item (how to test + latest diagnostic) for PLC lessons, or the first unmet target + hint for production line lessons. */
async function hintNext() {
  const c = cur.value;
  if (!c) return;
  busy.value = 'hint';
  try {
    if (!isPlant.value) {
      if (!live.has_program) { hintBox.value = $t('taskPanel.nextBWriteAndDownload'); return; }
      if (live.plc && live.plc !== 'RUN') { hintBox.value = $t('taskPanel.nextThePlcIsNot'); return; }
      const r = await get(`/api/p/${encodeURIComponent(c.pid)}/coach?since=999999999`, true);
      const items: any[] = r.checklist?.items || [];
      const bad = items.find((i) => i.state === 'fail') || items.find((i) => i.auto && !i.auto.ok) || items.find((i) => i.state !== 'ok');
      if (!bad) { hintBox.value = $t('taskPanel.allChecklistItemsAreB'); return; }
      let h = `${$t('taskPanel.next')}<b>${esc(bad.label)}</b>${$t('common.k266')}<br>${$t('checklist.howToTest')}${esc(bad.how)}`;
      if (bad.state === 'fail' && bad.msg) h += `<br><span class="vp-fail">${$t('checklist.notCompleted')}${esc(bad.msg)}</span>`;
      else if (bad.auto && !bad.auto.ok) h += `<br><span class="vp-fail">${$t('taskPanel.thisItemFailedTheAutomated')}${bad.auto.desc ? $t('common.k546') + esc(bad.auto.desc) : ''}</span>`;
      if (r.diag?.msg) h += `<br>${$t('taskPanel.latestDiagnostics')}${esc(r.diag.msg)}`;
      if (bad.trial) h += $t('taskPanel.brThisItemRequiresA');
      hintBox.value = h;
      tab.value = 'goals';
    } else {
      const rows: any[] = live.progress?.rules || [];
      const bad = rows.find((r) => r.kind === 'answer' ? !r.answered : r.ok === false) || rows.find((r) => r.ok !== true && r.kind !== 'answer');
      const hints: string[] = c.scene.hints || [];
      if (!bad) { hintBox.value = $t('taskPanel.allGoalsAppearToBe'); return; }
      let h = `${$t('taskPanel.next')}<b>${esc(bad.label)}</b>`;
      h += bad.kind === 'answer' ? $t('taskPanel.selectAnAnswerUnderGoals') : $t('taskPanel.target0Current1Click', [esc(bad.text || ''), esc(bad.value ?? '—')]);
      if (hints.length) h += `<br>${$t('taskPanel.hint')}${esc(hints[hintN++ % hints.length])}`;
      hintBox.value = h;
    }
  } catch { hintBox.value = $t('taskPanel.unableToLoadTheChecklist'); } finally { busy.value = ''; }
}
/** "Follow the Tutorial": enter the sandbox if needed, then start at step one. */
async function restartTour() {
  const c = cur.value;
  if (!c?.tour) return;
  if (c.sandbox === 'none' || !inSandbox.value) { await enter(true); return; }
  endTour();
  await startTour({ key: c.tour, aid: c.assignment.id, pid: c.pid, plc: live.plc_block?.id || c.scene?.plc || 'PLC1', kind: isPlant.value ? 'plant' : 'cell' });
}
function onTeachTab(e: any) { if (e.detail?.tab) tab.value = e.detail.tab; }
function onTeachEnter() { if (cur.value && !inSandbox.value) enter(false); }
window.addEventListener('vf:teach-tab', onTeachTab);
window.addEventListener('vf:teach-enter', onTeachEnter);
onBeforeUnmount(() => { window.removeEventListener('vf:teach-tab', onTeachTab); window.removeEventListener('vf:teach-enter', onTeachEnter); });
const scoreCls = (s: any) => (s === null || s === undefined ? '' : s >= 60 ? 'vp-pass' : 'vp-fail');
/** 4.6.2 Explain why correct answers are hidden (reveal.state from the server's with_reveal). */
function revealNote(r: any) {
  if (r.state === 'due') return r.due ? $t('taskPanel.yourTeacherHasSetCorrect', [r.due]) : $t('taskPanel.yourTeacherHasSetCorrect2');
  if (r.state === 'never') return $t('taskPanel.yourTeacherHasDisabledCorrect');
  if (r.state === 'local') return $t('taskPanel.thisIsALocalScore');
  return '';
}
/** Save the teacher's preview model / program as the lesson reference solution (used to verify the task is achievable). */
async function saveReference() {
  const c = cur.value;
  if (!c) return;
  busy.value = 'ref';
  try {
    const cid = String(c.assignment.course).slice('_preview-'.length);
    await post(`/api/teach/authoring/${encodeURIComponent(cid)}/reference`, { aid: c.assignment.id });
    ElMessage.success($t('taskPanel.savedAsAReferenceSolution'));
  } finally { busy.value = ''; }
}
const liveRow = (r: any) => (live.progress?.rules || []).find((x: any) => x.key === r.key);
function goalOk(r: any) {
  if (r.kind === 'answer') return undefined;
  return isPlant.value ? liveRow(r)?.ok : undefined;
}

async function load() {
  loading.value = true;
  try { Object.assign(map, await get('/api/teach/my/courses')); } finally { loading.value = false; }
}
async function refresh() {
  if (!cur.value || splitOn.value) await load();
  if (cur.value) await open(cur.value.assignment.id, watching.value ? cur.value.username : '');
  swEl.value?.load?.();
}
async function open(aid: number, username = '') {
  loading.value = true;
  try {
    const same = cur.value?.assignment?.id === aid;
    cur.value = await get(`/api/teach/assignments/${aid}/task${username ? '?username=' + encodeURIComponent(username) : ''}`);
    for (const k of Object.keys(answers)) delete answers[k];
    Object.assign(answers, cur.value.answers || {});
    if (!watching.value) try { localStorage.setItem('vf_teach_aid', String(aid)); } catch { /* */ }
    if (!same) { schoolRes.value = null; school.submissions = []; school.offline = false; }
    live.progress = null; live.io = null; live.plc = null; live.plc_block = null; live.faults_active = 0; live.hint = ''; dg.msg = '';
    if (!['task', 'goals', 'score', 'io'].includes(tab.value) || (tab.value === 'io' && (isPlant.value || isFactory.value)) || !same) tab.value = 'task';
    // The shell sets canvas editability by lesson type (read-only for PLC lessons, editable for line lessons)
    if (inSandbox.value) ed.teach = { ...(ed.teach || {}), assignment: aid, kind: cur.value.kind, pid: cur.value.pid, role: watching.value ? 'teacher' : session.user?.role };
    if (isFactory.value) { stopLive?.(); stopLive = null; loadMine(); } else if (noSandbox.value) { stopLive?.(); stopLive = null; if (!same) tab.value = 'goals'; } else startLive();
    loadSchool();
    if (inSandbox.value && !watching.value) maybeTour();
  } finally { loading.value = false; }
}
function back() { cur.value = null; stopLive?.(); stopLive = null; cancelPick(); try { localStorage.removeItem('vf_teach_aid'); } catch { /* */ } load(); }

function startLive() {
  stopLive?.();
  if (watching.value) return;
  stopLive = poll(async () => {
    if (!cur.value || isFactory.value) return;
    const r = await get(`/api/teach/assignments/${cur.value.assignment.id}/live`, true);
    const was = live.faults_active;
    Object.assign(live, { running: r.running, io: r.io || null, plc: r.plc || null, plc_block: r.plc_block || null, progress: r.progress || null, has_program: !!r.has_program,
      takeover: r.takeover || null, faults_active: r.faults_active || 0, diagnose: r.diagnose || null, hint: r.hint || '' });
    if (!was && live.faults_active && cur.value.viewer !== 'trial') ElNotification({ title: $t('taskPanel.equipmentFailure2'), message: $t('taskPanel.yourTeacherHasInjectedA'), type: 'warning' });
    cur.value.sandbox = r.sandbox;
  }, 2000);
}

/** Enter sandbox: ask the shell to switch to this factory (ed.teach.open); open the Workbench directly if unhandled. */
async function enter(guided: boolean | null = null) {
  const c0 = cur.value;
  if (guided === null && c0?.tour && c0.sandbox === 'none' && !watching.value && !isFactory.value) {
    // First lesson start: ask whether to follow the tutorial (4.5)
    const a = await ElMessageBox.confirm($t('taskPanel.isThisYourFirstTime'),
      $t('taskPanel.startLesson'), { confirmButtonText: $t('taskPanel.followTutorial'), cancelButtonText: $t('taskPanel.tryOnMyOwn'), distinguishCancelAndClose: true, type: 'info', customClass: 'tour-ask' })
      .then(() => 'yes').catch((x: string) => x);
    if (a === 'close') return;
    guided = a === 'yes';
  }
  busy.value = 'enter';
  try {
    const aid = cur.value.assignment.id;
    const r = await post(`/api/teach/assignments/${aid}/sandbox`);
    if (guided && cur.value.tour) {
      tourOpen.value = false;
      try { sessionStorage.setItem('vf_teach_tour_step', '0'); } catch { /* */ }
      await startTour({ key: cur.value.tour, aid, pid: r.pid, plc: r.plc_block?.id || cur.value.scene?.plc || 'PLC1', kind: isPlant.value ? 'plant' : 'cell' }).catch(() => undefined);
    }
    cur.value.sandbox = r.state;
    ed.teach = { ...(ed.teach || {}), assignment: aid, kind: cur.value.kind, pid: r.pid, bid: r.bid, role: 'student', readonly: false, open: { pid: r.pid, bid: r.bid, n: Date.now() } };
    emit('open-plant', r.pid);
    if (props.pid !== r.pid && !ed.teach.handled) {
      const { router } = await import('../../router');
      router.push(`/p/${encodeURIComponent(r.pid)}/workbench`);
    }
  } finally { busy.value = ''; }
}
async function reset(cmd: string) {
  const plant = isPlant.value;
  await ElMessageBox.confirm(plant ? $t('taskPanel.resetTheFactoryModelTo') : cmd === 'clear' ? $t('taskPanel.resetBothTheEquipmentAnd') : $t('taskPanel.resetTheEquipmentToThe'), $t('taskPanel.startOver'), { type: 'warning' });
  busy.value = 'reset';
  try {
    const r = await post(`/api/teach/assignments/${cur.value.assignment.id}/sandbox/reset`, { clear_program: cmd === 'clear' });
    ElMessage.success($t('taskPanel.resetToTheInitialState'));
    if (plant && ed.pid === r.pid) await loadModel(r.pid);       // Restore the starting model on the canvas too
  } finally { busy.value = ''; }
}
async function submit() {
  busy.value = 'submit';
  elapsed.value = 0;
  timer = setInterval(() => elapsed.value++, 1000);
  try {
    const body = isFactory.value ? { plant: fac.plant } : (isPlant.value || noSandbox.value) ? { answers: { ...answers } } : {};
    const r = await post(`/api/teach/assignments/${cur.value.assignment.id}/submit`, body);
    if (r.status === 'error') ElMessage.error($t('taskPanel.gradingDidNotFinish') + (r.error || ''));
    else if (r.status === 'submitted') ElMessage.success($t('taskPanel.recordedNoAutomaticChecksGraded'));
    else ElMessage.success(`${isFactory.value ? $t('taskPanel.checkLocally') : $t('taskPanel.score')} ${r.score}`);
    window.dispatchEvent(new CustomEvent('vf:teach-submitted', { detail: { aid: cur.value.assignment.id, score: r.score } }));
    await open(cur.value.assignment.id);
    tab.value = 'score';
  } finally { busy.value = ''; clearInterval(timer); }
}
// ---- Desktop client: school assignments, teacher submissions, assignment package export / open, My Factories ----
const swEl = ref<any>(null);
const pkgFile = ref<HTMLInputElement | null>(null);
const pkgDlg = ref(false);
const pkgEl = ref<any>(null);
const schoolRes = ref<any>(null);
let localReady = false;
async function ensureLocal() {
  if (!desk.on || localReady) return;
  localReady = true;
  await post('/api/client/local/ensure', {}).catch(() => { localReady = false; });
}
async function openLocal(aid: number) { await load(); await open(aid); }
/** Student opened their own assignment package: program/model is loaded into this assignment's sandbox; open the lesson and enter the sandbox. Factory files were imported into "My Factories". */
async function ownPkg(r: any) {
  if (r.myplant) { const { router } = await import('../../router'); router.push(`/p/${encodeURIComponent(r.pid)}/workbench`); return; }
  await load(); await open(r.aid); await enter();
}
async function loadMine() {
  if (!desk.on) return;
  fac.loading = true;
  try {
    const r = await get('/api/client/myplants', true);
    fac.list = r.plants || [];
    let last = '';
    try { last = localStorage.getItem('vf_fac_pick_' + cur.value?.assignment?.id) || ''; } catch { /* */ }
    if (!fac.list.some((p: any) => p.id === fac.plant)) fac.plant = fac.list.some((p: any) => p.id === last) ? last : fac.list[0]?.id || '';
  } catch { fac.list = []; } finally { fac.loading = false; }
}
watch(() => fac.plant, (v) => { if (v && cur.value) try { localStorage.setItem('vf_fac_pick_' + cur.value.assignment.id, v); } catch { /* */ } });
async function loadSchool() {
  if (!desk.on || !cur.value?.desktop?.school) { school.submissions = []; return; }
  const r = await get(`/api/client/school/results?aid=${cur.value.assignment.id}`, true).catch(() => null);
  school.submissions = r?.submissions || [];
  school.offline = !!r?.offline;
}
async function goMine() { const { router } = await import('../../router'); router.push('/mine'); }
async function submitSchool() {
  busy.value = 'school';
  elapsed.value = 0;
  timer = setInterval(() => elapsed.value++, 1000);
  try {
    const r = await post('/api/client/school/submit', { aid: cur.value.assignment.id, ...(isFactory.value ? { plant: fac.plant } : {}) });
    if (r.queued) {                                   // Offline: assignment queued locally for submission (202); submit automatically when online
      schoolRes.value = { queued: true, msg: r.msg, created: r.outbox?.queued || '', server: desk.server || '' };
      ElMessage.warning($t('taskPanel.queuedSubmitsAutomaticallyWhenOnline'));
      tab.value = 'score';
      return;
    }
    schoolRes.value = { ...r.remote, server: r.server };
    ElMessage.success(r.remote.status === 'submitted' ? $t('taskPanel.submittedToYourTeacherAwaiting') : $t('taskPanel.submittedToYourTeacherSchool', [r.remote.score ?? '—']));
    swEl.value?.load?.();
    loadSchool();
    tab.value = 'score';
  } finally { busy.value = ''; clearInterval(timer); }
}
async function exportPkg() {
  busy.value = 'export';
  try {
    const a = cur.value.assignment;
    await saveFile(`/api/teach/assignments/${a.id}/package${isFactory.value ? '?plant=' + encodeURIComponent(fac.plant) : ''}`, `${a.title || $t('common.working')}.vfhw`);
    ElMessage.success($t('taskPanel.assignmentPackageExportedSendThis'));
  } finally { busy.value = ''; }
}
function pickPkg(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = '';
  if (f) { pkgDlg.value = true; pkgEl.value?.openFile(f); }
}
watch(() => desk.openPath, (p) => {
  if (!p || !pkgEl.value) return;
  desk.openPath = '';
  pkgEl.value.openPath(p);
}, { flush: 'post' });
/** Review sandboxes: sb-review-<submission ID> (teacher opens a student submission), sb-review-p<package> (client opens an assignment package). */
const review = computed(() => {
  const m = (props.pid || '').match(/^sb-review-(p?)(\w+)$/);
  if (!m) return null;
  const what = ed.teach?.kind === 'cell' ? $t('common.program') : ed.teach?.kind === 'factory' ? $t('taskPanel.factoryModelAndPlcProgram') : $t('taskPanel.programModel');
  return m[1] ? { label: $t('taskPanel.assignmentPackageOpenedInDesktop'), what } : { label: $t('taskPanel.submission01', [m[2], ed.teach?.student ? $t('common.k459') + ed.teach.student + $t('common.k460') : '']), what };
});
async function diagnose() {
  busy.value = 'dg';
  try {
    const r = await post(`/api/teach/assignments/${cur.value.assignment.id}/diagnose`, { comp: dg.comp, kind: dg.kind });
    dg.msg = r.msg; dg.ok = r.ok;
    if (r.ok) { ElMessage.success(r.msg); dg.comp = ''; dg.kind = ''; }
  } finally { busy.value = ''; }
}
/** Students have one AI entry point: "AI Tutor" at bottom right (handled by the shell, with the current lesson's assignment ID). */
function openTutor() { window.dispatchEvent(new CustomEvent('vf:assistant-toggle', { detail: { open: true } })); }

// ---- Answers: multiple choice / graph picking (shell contract: ed.pick = {prompt, kinds, onPick}) ----
async function saveAnswer(key: string, v: any) {
  if (v === null || (Array.isArray(v) && !v.length)) delete answers[key]; else answers[key] = v;
  const r = await put(`/api/teach/assignments/${cur.value.assignment.id}/answers`, { answers: { [key]: v } });
  for (const k of Object.keys(answers)) if (!(k in r.answers)) delete answers[k];
  Object.assign(answers, r.answers);
}
function startPick(r: any) {
  if (picking.value === r.key) { cancelPick(); return; }
  picking.value = r.key;
  ed.pick = {
    prompt: $t('taskPanel.n0ClickAMachineIn', [r.label]), kinds: r.kinds,
    onPick: (id: string) => { picking.value = ''; saveAnswer(r.key, id); ElMessage.success($t('taskPanel.selected0', [id])); },
  };
  if (!ed.teach?.handled && !props.pid?.startsWith('sb-')) ElMessage.info($t('taskPanel.clickStartThisLessonTo'));
}
function cancelPick() { if (picking.value) { picking.value = ''; if (ed.pick) ed.pick = null; } }
watch(() => ed.pick, (v) => { if (!v && picking.value) picking.value = ''; });

// ---- Five-step onboarding, first-login password change ----
function maybeTour() {
  if (isFactory.value || hasActiveTour()) return;
  try { if (localStorage.getItem('vf_teach_tour')) return; } catch { return; }
  // Opening the "PLC" panel during the tour replaces the left sidebar; resume at the same step on returning to "My Courses"
  let s = 0;
  try { s = Number(sessionStorage.getItem('vf_teach_tour_step') || 0); } catch { /* */ }
  tourStep.value = Math.min(Math.max(0, s), TOUR.value.length - 1); tourOpen.value = true;
}
watch(tourStep, (s) => { if (tourOpen.value) try { sessionStorage.setItem('vf_teach_tour_step', String(s)); } catch { /* */ } });
/** "Take Me There": open the panel mentioned in the guide (which contains the button). */
async function tourGo(what: string) {
  if (what === 'plc') window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor' } }));
  else if (what === 'editor') {                  // Select this PLC first (the programming window follows the selected PLC), then open the programming window; keep the sidebar and guide
    ed.sel = [plcId.value];
    window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'plc-editor-float' } }));
  }
  else if (what === 'console') { const m = await import('../cell/state'); m.openConsole(true); }
}
function pwLater() { try { sessionStorage.setItem('vf_pw_later', '1'); } catch { /* */ } }
function endTour() { tourOpen.value = false; try { localStorage.setItem('vf_teach_tour', '1'); sessionStorage.removeItem('vf_teach_tour_step'); } catch { /* */ } }

onMounted(async () => {
  ro = new ResizeObserver((es) => { const w = es[0]?.contentRect.width || 999; width.value = w; narrow.value = w < 440; });
  if (root.value) { ro.observe(root.value); width.value = root.value.clientWidth; }
  if (review.value) return;
  await ensureLocal();
  if (desk.openPath && pkgEl.value) { const p = desk.openPath; desk.openPath = ''; pkgEl.value.openPath(p); }
  const m = (props.pid || '').match(/^sb-(.+)-(\d+)$/);
  const me = await get('/api/teach/me', true).catch(() => null);
  let later = false;
  try { later = !!sessionStorage.getItem('vf_pw_later'); } catch { /* */ }
  if (me?.must_change_password && !later) pwOpen.value = true;     // After "Later" is clicked, suppress the prompt for this login session (keep the sandbox canvas clear)
  if (m) {
    // In a sandbox, show its lesson directly (sandbox ID sb-<account>-<assignment ID>); teachers see that student's task
    const own = me && m[1] === me.safe;
    open(Number(m[2]), own || !isTeacher() ? '' : m[1]).catch(() => load());
    return;
  }
  await load();
  if (props.initialAid) {                                       // 4.6 Course page: open the clicked lesson
    await open(props.initialAid).catch(() => undefined);
    // autoEnter: true = enter sandbox directly; 'start' = same as "Start Lesson / Continue Lesson" (course card's "Start Learning / Continue Learning"; quizzes, MES, and factory design lessons only open the lesson)
    if (props.autoEnter === 'start') { if (cur.value && !watching.value && !isFactory.value && !noSandbox.value && !inSandbox.value) await enter(); }
    else if (props.autoEnter && cur.value) await enter(false);
    return;
  }
  let aid = 0;
  try { aid = Number(localStorage.getItem('vf_teach_aid') || 0); } catch { /* */ }
  // Wide layout (teaching home): always show a lesson on the right: the last viewed lesson, or the next lesson in the first course
  if (!aid && splitOn.value) aid = map.courses.find((c: any) => c.next)?.next || map.tasks[0]?.id || 0;
  if (aid) open(aid).catch(() => { try { localStorage.removeItem('vf_teach_aid'); } catch { /* */ } });
});
onBeforeUnmount(() => { stopLive?.(); cancelPick(); clearInterval(timer); ro?.disconnect(); });
</script>

<style scoped>
.task-panel :deep(.el-tabs__header) { margin: 0; padding: 0 10px; }
.tp-main { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.tp-detail { flex: 1; min-height: 0; min-width: 0; display: flex; flex-direction: column; }
.split .tp-main { flex-direction: row; }
.split .tp-map { flex: 0 0 clamp(360px, 30%, 480px); border-right: 1px solid var(--el-border-color-lighter); background: var(--el-fill-color-lighter); }
.split .tp-detail .vp-body { padding: 12px 18px; }
.split .book-md { max-width: 1200px; }
.dtl-head { gap: 10px; }
.dtl-head .ttl { font-size: 15px; margin-right: 0; }
.tp-pick { align-items: center; justify-content: center; }
.tp-tabs { flex: 1; min-height: 0; }
.local-row { margin: 0 0 10px; gap: 8px; }
.review-card { border-left: 3px solid var(--warn, var(--el-color-warning)); }
.school-res { border-left: 3px solid var(--el-color-primary); margin-bottom: 8px; }
.tp-tabs :deep(.el-tabs__content) { flex: 1; min-height: 0; overflow: auto; }
.tp-tabs :deep(.el-tab-pane) { height: 100%; }
/* Task brief I/O and grading tables in narrow sidebars: scroll the whole table horizontally; avoid one-character-per-line wrapping (S11) */
.narrow :deep(.vp-md table) { display: block; overflow-x: auto; max-width: 100%; }
.narrow :deep(.vp-md th), .narrow :deep(.vp-md td) { white-space: nowrap; }
.acts { gap: 6px; }
.crumb { padding: 4px 10px 0; }
.banner { margin: 6px 10px 0; padding: 6px 10px; border-radius: 5px; font-size: 12.5px; background: var(--el-color-primary-light-9); color: var(--el-text-color-primary); }
.banner.warn { background: var(--el-color-warning-light-9); border: 1px solid var(--el-color-warning-light-5); }
.banner.watch { background: var(--el-color-info-light-9); border: 1px solid var(--el-border-color); }
.banner.run { background: var(--el-color-success-light-9); }
.fault-card { margin: 6px 10px 0; border-color: var(--el-color-danger-light-5); background: var(--el-color-danger-light-9); padding: 8px 10px; }
.next-step { margin: 6px 10px 0; padding: 7px 10px; display: flex; align-items: center; gap: 4px 8px; flex-wrap: wrap; border-color: var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); font-size: 12.5px; line-height: 1.6; }
.next-step .vp-grow { min-width: 200px; }
.next-step .ns-i { color: var(--el-color-primary); flex: none; }
.fac-card { margin: 8px 10px 0; border-left: 3px solid var(--el-color-primary); }
.fac-sel { width: 260px; }
.sub { margin-bottom: 8px; }
.school-sub { border-left: 3px solid var(--el-color-success-light-5); }
.teacher-cmt { color: var(--el-color-primary); background: var(--el-color-primary-light-9); border-radius: 4px; padding: 3px 6px; }
.vp-score.wait { font-size: 15px; color: var(--el-color-warning); }
.det { border-top: 1px solid var(--el-border-color-extra-light); padding: 5px 0; }
.det.good .el-icon { color: var(--ok, var(--el-color-success)); }
.det.bad .el-icon { color: var(--bad, var(--el-color-danger)); }
.det .num { font-variant-numeric: tabular-nums; font-weight: 600; }
.det .rc { color: var(--el-color-primary); }
.course { margin-bottom: 12px; }
.course .chead { cursor: pointer; user-select: none; }
.course .fold-i { vertical-align: -2px; margin-right: 4px; color: var(--el-text-color-secondary); }
.course.folded { padding-bottom: 8px; }
.tp-back { margin: -4px 0 8px -6px; }
.choices.tf { flex-direction: row; gap: 14px; }
.cname { font-weight: 600; font-size: 14px; }
.chapter { margin-top: 8px; }
.chtitle { font-size: 12px; color: var(--el-text-color-secondary); margin: 4px 0; padding-bottom: 2px; border-bottom: 1px dashed var(--el-border-color-lighter); }
.lesson { display: flex; align-items: center; gap: 6px; padding: 5px 6px; border-radius: 5px; cursor: pointer; font-size: 13px; }
.lesson:hover { background: var(--el-fill-color-light); }
.lesson.locked { cursor: not-allowed; color: var(--el-text-color-placeholder); }
.lesson.cur { background: var(--el-color-primary-light-9); }
.lesson.sel, .task-card.sel { box-shadow: 0 0 0 2px var(--el-color-primary) inset; }
.lesson .st { flex: none; }
.lesson.done .st { color: var(--ok, var(--el-color-success)); }
.lesson.open .st { color: var(--el-color-primary); }
.lesson .lt { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kind { font-size: 11px; padding: 0 5px; border-radius: 3px; background: var(--el-fill-color); color: var(--el-text-color-secondary); flex: none; font-weight: normal; }
.kind.big { font-size: 12px; padding: 1px 7px; }
.kind.diagnose { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
.kind.plant { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.kind.factory { background: var(--el-color-success-light-9); color: var(--el-color-success); }
.lesson .sc { width: 28px; text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; flex: none; }
.goal { margin-bottom: 8px; padding: 8px 10px; }
.goal .gl { display: flex; align-items: center; gap: 4px; font-weight: 500; }
/* 4.6: Former .gv class collided with the Workbench graph's global .gv { position: absolute; inset: 0 }, pinning the "Target: … Current …" row to the tab top over the description */
.goal .goal-v { margin-top: 4px; }
.goal .goal-q { margin-top: 2px; }
.choices { display: flex; flex-direction: column; align-items: stretch; margin-top: 4px; gap: 2px; }
/* 4.6.2 Wrap long option text (previously clipped to one line, e.g. "Temporarily hold a few parts: the upstream machine has finished, down"); align radio buttons / checkboxes with the first line */
.choices :deep(.el-radio), .choices :deep(.el-checkbox) { height: auto; min-height: 24px; margin-right: 0; align-items: flex-start; white-space: normal; max-width: 100%; padding: 3px 0; }
.choices :deep(.el-radio__input), .choices :deep(.el-checkbox__input) { flex: none; margin-top: 2px; }
.choices :deep(.el-radio__label), .choices :deep(.el-checkbox__label) { white-space: normal; overflow-wrap: anywhere; line-height: 1.5; padding-left: 6px; }
.choices.tf { align-items: flex-start; }
.reveal-note { margin: 2px 0 4px; }
.next-card { display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 8px; border-color: var(--el-color-success-light-5); }
.io-cards { display: flex; flex-direction: column; gap: 6px; }
.io-card { border: 1px solid var(--el-border-color-lighter); border-radius: 5px; padding: 5px 8px; }
.book { max-height: 70vh; overflow: auto; font-size: 14px; }
.tour p { line-height: 1.7; margin: 6px 0 0; color: var(--el-text-color-regular); }
.tour-card { margin: 6px 10px; border-left: 3px solid var(--el-color-primary); }
.tour-card .tour { margin: 4px 0; font-size: 13px; }
.hint-box { border-color: var(--el-color-warning-light-5); background: var(--el-color-warning-light-9); }
.hint-box .ns-i { color: var(--el-color-warning); }
.log-body { height: 100%; box-sizing: border-box; display: flex; flex-direction: column; }
.locked-warn { margin-bottom: 8px; padding: 6px 10px; font-size: 12px; line-height: 1.6; border-color: var(--el-color-warning-light-5); background: var(--el-color-warning-light-9); }
.ncell { color: var(--hm-idle-ink); font-weight: 600; }
</style>
