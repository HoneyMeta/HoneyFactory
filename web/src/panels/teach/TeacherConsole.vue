<template>
  <div class="vp teacher-console">
    <div class="vp-head" data-tour="tc-head">
      <span class="ttl">{{ $t('common.teacherConsole') }}</span>
      <el-select v-model="aid" size="small" :placeholder="$t('teacherConsole.selectLessonTask')" style="width: 300px" filterable data-tour="tc-pick" @change="onPickAssign">
        <el-option-group v-for="g in groups" :key="g.name" :label="g.name">
          <el-option v-for="a in g.items" :key="a.id" :value="a.id" :label="(a.seq ? a.seq + '. ' : '') + a.title + (a.status === 'closed' ? $t('teacherConsole.closed') : '')">
            <span>{{ a.seq ? a.seq + '. ' : '' }}{{ a.title }}</span><span class="vp-muted vp-small" style="float: right">{{ $t('teacherConsole.n01Submitted', [a.submitted, a.students]) }}</span>
          </el-option>
        </el-option-group>
      </el-select>
      <el-button v-if="curAssign?.course" size="small" :type="view === 'course' ? 'primary' : 'default'" plain @click="view = view === 'course' ? 'lesson' : 'course'">
        <el-icon><Grid /></el-icon>{{ view === 'course' ? $t('teacherConsole.viewLesson') : $t('sections.courseOverview') }}</el-button>
      <el-button size="small" type="primary" data-tour="tc-lesson" @click="lessonWiz = true"><el-icon><MagicStick /></el-icon>{{ $t('teacherConsole.startALesson') }}</el-button>
      <el-button size="small" data-tour="tc-publish" @click="coursePub = true"><el-icon><Collection /></el-icon>{{ $t('common.publishCourse') }}</el-button>
      <el-button size="small" @click="wizard = true"><el-icon><Plus /></el-icon>{{ $t('teach.individualAssignments') }}</el-button>
      <el-dropdown v-if="prog" size="small" trigger="click" @command="assignCmd">
        <el-button size="small">{{ $t('teacherConsole.task') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
        <template #dropdown><el-dropdown-menu>
          <el-dropdown-item command="edit">{{ $t('teacherConsole.editTaskNameInstructionsTime') }}</el-dropdown-item>
          <el-dropdown-item command="analytics">{{ $t('teacherConsole.learningAnalyticsScoreRateFor') }}</el-dropdown-item>
          <el-dropdown-item command="toggle" divided>{{ prog.assignment.status === 'published' ? $t('teacherConsole.closeTaskStudentsCanNo') : $t('teacherConsole.reopen') }}</el-dropdown-item>
          <el-dropdown-item command="tutor">{{ prog.assignment.tutor ? $t('teacherConsole.disableAiTutor') : $t('teacherConsole.enableAiTutor') }}</el-dropdown-item>
          <el-dropdown-item command="hints">{{ prog.assignment.hints ? $t('teacherConsole.hideHints') : $t('teacherConsole.showHints') }}</el-dropdown-item>
          <el-dropdown-item v-if="!isFactory && !saas" command="preview" divided>{{ $t('teacherConsole.tryItMyselfTeacherSandbox') }}</el-dropdown-item>
          <el-dropdown-item command="delete" divided>{{ $t('teacherConsole.deleteTask') }}</el-dropdown-item>
        </el-dropdown-menu></template>
      </el-dropdown>
      <el-button v-if="prog" size="small" :loading="!!aiJob?.running" data-k="ai-all" :title="$t('teacherConsole.aiReviewsEachStudentS')" @click="aiAll">
        <el-icon><MagicStick /></el-icon>{{ $t('teacherConsole.generateAiSuggestionsForClass') }}</el-button>
      <span class="vp-grow" />
      <template v-if="prog">
        <span v-for="(n, k) in stuCounts" :key="k" class="cnt"><span class="vp-dot" :style="{ background: STU_STATE_COLOR[k] }" /> {{ stuStateLabel(k) }} {{ n }}</span>
        <span v-if="saas" class="vp-small vp-muted" data-k="tc-saas-note">{{ $t('teacherConsole.averageScore0StudentsWork', [prog.avg ?? '—']) }}</span>
        <span v-else class="vp-small vp-muted">{{ $t('teacherConsole.averageScore0Sandboxes1', [prog.avg ?? '—', prog.pool.running, prog.pool.sleeping]) }}</span>
      </template>
      <el-button size="small" text :loading="loading" @click="refresh"><el-icon><Refresh /></el-icon></el-button>
      <GuideButton area="teach" size="sm" />
    </div>

    <!-- 4.6 Batch AI suggestion progress -->
    <div v-if="aiJob" class="ai-job" data-k="ai-job">
      <el-icon><MagicStick /></el-icon><b>{{ $t('teacherConsole.aiGradingSuggestions') }}</b>
      <el-progress class="vp-grow" :percentage="aiJob.total ? Math.round((aiJob.done / aiJob.total) * 100) : 100" :stroke-width="8" :status="aiJob.running ? undefined : aiJob.failed ? 'warning' : 'success'" />
      <span class="vp-small" data-k="ai-job-text">{{ aiJob.running ? $t('teacherConsole.reviewingSubmission01', [Math.min(aiJob.done + 1, aiJob.total), aiJob.total]) : $t('teacherConsole.completed012', [aiJob.done - aiJob.failed, aiJob.total, aiJob.failed ? $t('teacherConsole.n0Failed', [aiJob.failed]) : '']) }}{{ aiFake ? $t('teacherConsole.testModeNoLlmConnected') : '' }}</span>
      <span class="vp-small vp-muted">{{ $t('teacherConsole.suggestionsOnlyOpenEachStudent') }}</span>
      <el-button v-if="!aiJob.running" size="small" text @click="aiJob = null"><el-icon><Close /></el-icon></el-button>
    </div>
    <div class="vp-body" v-if="!assigns.length && !loading">
      <div class="vp-empty empty-start" data-tour="tc-empty">
        <div class="es-t">{{ $t('teacherConsole.noCoursesOrTasksPublished') }}</div>
        <div class="es-d">{{ $t('teacherConsole.followACourseChooseProduction') }}</div>
        <div class="vp-row" style="justify-content: center; margin-top: 12px">
          <el-button type="primary" @click="coursePub = true"><el-icon><Collection /></el-icon>{{ $t('common.publishCourse') }}</el-button>
          <el-button v-if="!saas" :loading="busy === 'demo'" @click="makeDemo"><el-icon><MagicStick /></el-icon>{{ $t('sections.createDemoClass') }}</el-button>
        </div>
        <div v-if="!saas" class="vp-small vp-muted" style="margin-top: 10px">{{ $t('teacherConsole.demoClass6DemoStudents') }}</div>
      </div>
    </div>
    <div class="vp-body" v-else-if="view === 'course' && curAssign?.course" data-tour="tc-body">
      <CourseProgress :course="curAssign.course" :class-id="curAssign.class_id" @lesson="gotoLesson" />
    </div>
    <div class="vp-body" v-else-if="!prog" data-tour="tc-body"><div class="vp-empty">{{ $t('teacherConsole.selectALessonOrTask') }}</div></div>

    <div class="vp-body tc-body" v-else>
      <!-- Factory assignment submissions: class-wide list, newest first; click a row to open the student's "Submissions & Review" -->
      <div v-if="isFactory" class="vp-card fac-subs" data-k="factory-subs">
        <div class="vp-row sp"><b>{{ $t('teacherConsole.factoryDesignAssignmentClassSubmissi') }}</b>
          <span class="vp-small vp-muted">{{ $t('teacherConsole.n0YourScoreAndComments', [prog.assignment.spec?.checks?.length ? $t('teacherConsole.automaticChecks0', [prog.assignment.spec.checks.length]) : $t('teacherConsole.noAutomaticChecksGradedBy')]) }}</span></div>
        <div v-if="!allSubs.length" class="vp-small vp-muted" style="margin-top: 6px">{{ $t('teacherConsole.noSubmissionsYetStudentsBuild') }}</div>
        <table v-else class="vp-tbl" style="margin-top: 6px">
          <tr><th>{{ $t('common.student') }}</th><th>{{ $t('teacherConsole.submittedAt') }}</th><th>{{ $t('common.factory') }}</th><th>{{ $t('common.automatedChecks') }}</th><th>{{ $t('teacherConsole.teacherScore') }}</th><th>{{ $t('common.status') }}</th><th></th></tr>
          <tr v-for="s in allSubs.slice(0, 30)" :key="s.id" :data-sid="s.id" class="fs-row" @click="pickSub(s)">
            <td>{{ nameOf(s.username) }} <span class="vp-muted">{{ s.username }}</span></td><td class="mono">{{ s.created }}</td>
            <td>{{ s.plant?.name || '—' }}<span v-if="s.plant" class="vp-muted vp-small"> {{ $t('teacherConsole.objects0', [s.plant.blocks]) }}</span></td>
            <td class="mono">{{ s.auto_score ?? '—' }}</td><td class="mono"><b>{{ s.override_score ?? '—' }}</b></td>
            <td><el-tag size="small" :type="s.status === 'reviewed' ? 'success' : s.status === 'error' ? 'danger' : 'warning'" effect="plain">{{ SUB_ST[s.status] || s.status }}</el-tag></td>
            <td><el-button size="small" text type="primary" @click.stop="pickSub(s)">{{ $t('teacherConsole.review') }}</el-button></td>
          </tr>
        </table>
      </div>
      <div class="vp-split">
        <div class="main grid-wrap">
          <div class="vp-row" style="margin-bottom: 8px">
            <el-input v-model="filter" size="small" :placeholder="$t('teacherConsole.searchStudents')" clearable style="width: 160px" />
            <el-radio-group v-model="stateFilter" size="small">
              <el-radio-button value="">{{ $t('common.all') }}</el-radio-button>
              <el-radio-button v-for="k in Object.keys(stuCounts)" :key="k" :value="k">{{ stuStateLabel(k) }}</el-radio-button>
            </el-radio-group>
          </div>
          <div class="grid" data-tour="tc-grid">
            <div v-for="r in rows" :key="r.username" class="stu" :class="{ on: sel === r.username }" :style="{ borderLeftColor: STU_STATE_COLOR[stuState(r)] }"
                 @click="pick(r.username)" :data-user="r.username">
              <div class="vp-row sp"><b>{{ r.name }}</b><span class="sc" :class="r.best >= 60 ? 'vp-pass' : r.best !== null ? 'vp-fail' : 'vp-muted'">{{ r.best ?? '—' }}</span></div>
              <div class="vp-small vp-muted">{{ r.username }}</div>
              <div class="vp-row vp-small" style="margin-top: 3px">
                <span :style="{ color: STU_STATE_COLOR[stuState(r)] }">{{ stuStateLabel(stuState(r)) }}</span>
                <span v-if="r.plc" class="vp-muted">PLC {{ PLC_CN[r.plc] || r.plc }}</span>
                <span v-if="r.submissions" class="vp-muted">{{ $t('teacherConsole.submissions0', [r.submissions]) }}</span>
                <span v-if="r.seen && !r.active" class="vp-muted">{{ $t('teacherConsole.lastVisited0', [r.seen]) }}</span>
              </div>
              <div v-if="r.reported" class="vp-small ell" data-k="tc-reported" :title="r.reported.step || ''">
                <span class="vp-dot" :style="{ background: r.reported.online ? 'var(--el-color-success)' : 'var(--el-text-color-placeholder)' }" />
                {{ r.reported.online ? $t('common.online') : $t('common.offline') }}<template v-if="r.reported.progress != null"> · {{ Math.round(r.reported.progress * 100) }}%</template>
                <template v-if="r.reported.step"> · {{ r.reported.step }}</template>
                <template v-else-if="r.reported.elsewhere"> {{ $t('teacherConsole.workingOn0', [r.reported.elsewhere.title]) }}</template></div>
              <div v-if="r.faults?.length" class="vp-small vp-fail ell" :title="r.faults.map((f: any) => f.label).join($t('common.k360'))">{{ $t('teacherConsole.activeFailure01Min', [r.faults[0].label, r.faults[0].since_min, r.faults[0].attempts]) }}</div>
              <div v-else-if="r.alarm && (r.state_code === 'stuck' || matches(r.state, 'common.stuck'))" class="vp-small vp-fail ell">{{ r.alarm }}</div>
              <div v-else-if="r.stats && r.stats.good_per_h === undefined && metricRows(r.stats, ruleKeys).length" class="vp-small vp-muted ell">{{ metricRows(r.stats, ruleKeys).filter((m) => m.key !== 'faults').slice(0, 3).map((m) => `${m.label} ${m.text}`).join(' · ') }}</div>
              <div v-else-if="r.stats && r.stats.good_per_h !== undefined" class="vp-small vp-muted ell">{{ $t('teacherConsole.throughput0Pcs1Pcs', [r.stats.good, r.stats.good_per_h, r.edited ? $t('teacherConsole.modelModified') : '']) }}</div>
            </div>
          </div>
        </div>

        <div class="side detail" v-if="sel">
          <div class="vp-row sp" style="margin-bottom: 6px">
            <b>{{ $t('common.n012', [selRow?.name, sel]) }}</b>
            <el-button size="small" text @click="sel = ''"><el-icon><Close /></el-icon></el-button>
          </div>
          <el-tabs v-model="dtab" stretch>
            <el-tab-pane v-if="saas && !isFactory" :label="$t('plan.progress')" name="live">
              <div class="vp-small vp-muted" style="margin-bottom: 8px">{{ $t('teacherConsole.studentsWorkInTheDesktop') }}</div>
              <div v-if="!selRow?.reported?.at && !selRow?.reported?.last_seen" class="vp-empty" data-k="tc-live-empty">{{ $t('teacherConsole.noReportsYetTheStudent') }}</div>
              <template v-else>
                <div class="vp-kv" data-k="tc-live">
                  <span>{{ $t('common.online') }}</span><span>{{ selRow.reported.online ? $t('common.online') : $t('common.offline') }}<span class="vp-muted">{{ $t('teacherConsole.last0', [selRow.reported.last_seen || '—']) }}</span></span>
                  <span>{{ $t('teacherConsole.currentStep') }}</span><span>{{ selRow.reported.step || '—' }}<span v-if="selRow.reported.step_min != null" class="vp-muted">{{ $t('teacherConsole.n0MinElapsed', [Math.round(selRow.reported.step_min)]) }}</span></span>
                  <span>{{ $t('plan.progress') }}</span><span>{{ selRow.reported.progress != null ? Math.round(selRow.reported.progress * 100) + '%' : '—' }}</span>
                  <span>{{ $t('teacherConsole.localScore') }}</span><span>{{ selRow.reported.score ?? '—' }}</span>
                  <span>{{ $t('teacherConsole.reportedAt') }}</span><span>{{ selRow.reported.at || '—' }}</span>
                </div>
                <div class="vp-sec" v-if="liveLog.length"><div class="lbl">{{ $t('teacherConsole.latestReport') }}</div>
                  <div v-for="(l, i) in liveLog" :key="i" class="vp-small"><span class="vp-muted">{{ (l.at || '').slice(11, 16) }}</span> {{ l.step || l.state }}
                    <span v-if="l.progress != null" class="vp-muted">· {{ Math.round(l.progress * 100) }}%</span></div></div>
              </template>
            </el-tab-pane>
            <el-tab-pane v-if="!isFactory && !saas" :label="$t('teacherConsole.observe')" name="watch">
              <div v-if="!watch" class="vp-muted vp-small">{{ $t('common.loading') }}</div>
              <div v-else-if="watch.exists === false" class="vp-empty">{{ $t('teacherConsole.n0', [watch.msg]) }}<br>{{ $t('teacherConsole.viewingAsATeacherDoes') }}</div>
              <template v-else>
                <div class="vp-kv" style="margin-bottom: 6px">
                  <span>{{ $t('teacherConsole.sandbox') }}</span><span class="vp-mono">{{ watch.pid }}</span>
                  <span :title="watch.plc_block ? $t('taskMetrics.plcBlock') + watch.plc_block.id : ''">{{ watch.plc_block?.name || 'PLC' }}</span><span>{{ PLC_CN[watch.plc] || watch.plc || '—' }}</span>
                  <span>{{ $t('teacherConsole.simTime') }}</span><span>{{ watch.time }}</span>
                  <span v-if="watch.alarm">{{ $t('common.alarm') }}</span><span v-if="watch.alarm" class="vp-fail">{{ watch.alarm }}</span>
                </div>
                <div class="vp-row" style="margin-bottom: 6px">
                  <el-button size="small" @click="openWatch"><el-icon><View /></el-icon>{{ $t('teacherConsole.observeInCanvasReadOnly') }}</el-button>
                  <el-button v-if="!takeover" size="small" type="warning" plain @click="setTakeover(true)" :title="$t('teacherConsole.takeControlToEditThe')">{{ $t('sections.takeOver') }}</el-button>
                  <el-button v-else size="small" type="warning" @click="setTakeover(false)">{{ $t('teacherConsole.endTakeover') }}</el-button>
                </div>
                <div v-if="takeover" class="vp-small" style="color: var(--el-color-warning); margin-bottom: 6px">{{ $t('teacherConsole.youHaveControlledThisSandbox', [takeover.since]) }}</div>
                <div class="vp-sec" v-if="watch.progress"><div class="lbl">{{ $t('teacherConsole.goalProgressEstimatedDuringSandbox', [watch.progress.cost ?? '—']) }}</div>
                  <table class="vp-tbl"><tr v-for="r in watch.progress.rules" :key="r.key"><td>{{ r.label }}</td>
                    <td class="num mono">{{ r.kind === 'answer' ? (r.answered ? $t('teacherConsole.answered') : $t('teacherConsole.unanswered')) : fmtVal(r.value) }}</td>
                    <td class="vp-muted mono">{{ r.text || '' }}</td></tr></table>
                  <div v-if="watch.answers && Object.keys(watch.answers).length" class="vp-small vp-muted" style="margin-top: 4px">{{ $t('teacherConsole.answer0', [JSON.stringify(watch.answers)]) }}</div>
                </div>
                <div class="vp-sec" v-if="watch.io_table?.length"><div class="lbl">I/O</div>
                  <table class="vp-tbl"><tr><th>{{ $t('common.name') }}</th><th>{{ $t('common.address') }}</th><th>{{ $t('common.value') }}</th></tr>
                    <tr v-for="e in watch.io_table" :key="e.name"><td class="mono">{{ e.name }}</td><td class="mono vp-muted">{{ e.addr }}</td>
                      <td><span v-if="(e.type || 'BOOL') === 'BOOL'" class="vp-dot" :class="{ on: !!watch.io[e.name], out: e.dir === 'out' }" /><span v-else class="mono">{{ fmtVal(watch.io[e.name]) }}</span></td></tr>
                  </table></div>
                <div class="vp-sec" v-if="watch.stats && Object.keys(watch.stats).length"><div class="lbl">{{ $t('cellEditor.statistics') }}</div>
                  <div class="vp-kv"><template v-for="m in metricRows(watch.stats, ruleKeys)" :key="m.key"><span>{{ m.label }}</span><span>{{ m.text }}</span></template></div></div>
                <div class="vp-sec"><div class="lbl">{{ $t('teacherConsole.recentEvents') }}</div>
                  <div v-for="e in watch.events.slice(-8).reverse()" :key="e.seq" class="vp-small"><span class="vp-muted">{{ e.t.slice(11) }}</span> {{ e.msg }}</div>
                  <div v-if="!watch.events.length" class="vp-small vp-muted">{{ $t('common.none') }}</div></div>
                <div class="vp-sec" v-if="watch.program"><div class="lbl">{{ $t('teacherConsole.studentProgram0', [watch.program.lang]) }}</div>
                  <pre class="prog">{{ progText(watch.program) }}</pre></div>
              </template>
            </el-tab-pane>
            <el-tab-pane v-if="!isFactory && !saas" :label="$t('common.injectFailure')" name="fault">
              <div class="vp-small vp-muted" style="margin-bottom: 8px">{{ $t('teacherConsole.onlyAffectsThisStudentS') }}</div>
              <div class="vp-list">
                <div v-for="(f, i) in faults" :key="i" class="vp-row sp vp-card fault">
                  <span>{{ faultLabel(f) }}</span>
                  <el-button size="small" type="danger" plain :loading="busy === 'f' + i" @click="inject(f, i)">{{ $t('common.inject') }}</el-button>
                </div>
              </div>
              <div v-if="!faults.length" class="vp-small vp-muted">{{ $t('teacherConsole.noInjectableFailuresConfiguredFor') }}</div>
              <el-button size="small" style="margin-top: 10px" @click="clearFaults">{{ $t('cellEditor.clearAllFaults') }}</el-button>
            </el-tab-pane>
            <el-tab-pane :label="$t('teacherConsole.submissionsReview')" name="subs">
              <div class="vp-row" style="margin-bottom: 8px">
                <input ref="pkgEl" type="file" accept=".vfhw" style="display: none" @change="importPkg" />
                <el-button size="small" :loading="busy === 'imp'" @click="pkgEl?.click()" :title="$t('teacherConsole.ifAStudentCannotSubmit')">
                  <el-icon><Upload /></el-icon>{{ $t('teacherConsole.importAssignmentPackage') }}</el-button>
                <span v-if="saas" class="vp-small vp-muted">{{ $t('teacherConsole.sourceDesktopClientSubmittedBy') }}</span>
                <span v-else class="vp-small vp-muted">{{ $t('teacherConsole.sourceSandboxCompletedOnThe') }}</span>
              </div>
              <div v-if="!subs.length" class="vp-small vp-muted">{{ $t('teacherConsole.noSubmissionsYet') }}</div>
              <div v-for="(s, i) in subs" :key="s.id" class="vp-card sub" :class="{ open: s._open }">
                <div class="vp-row sp" style="cursor: pointer" @click="s._open = !s._open">
                  <span><span class="vp-score" :class="s.score >= 60 ? 'vp-pass' : 'vp-fail'" style="font-size: 18px">{{ s.score ?? '—' }}</span>
                    <span class="vp-small vp-muted"> {{ $t('teacherConsole.iteration0', [subs.length - i]) }}</span>
                    <el-tag size="small" :type="SRC_TAG[s.source] || 'info'" effect="plain" style="margin-left: 6px" :title="SRC_TIP[s.source]">{{ SRC_CN[s.source] || $t('teacherConsole.sandbox') }}</el-tag></span>
                  <span class="vp-small vp-muted">{{ $t('teacherConsole.submittedAt01', [s.created, s.late ? $t('teacherConsole.late') : '']) }} <el-icon><ArrowDown v-if="!s._open" /><ArrowUp v-else /></el-icon></span>
                </div>
                <div class="vp-small vp-muted">{{ $t('teacherConsole.automatic0', [s.auto_score ?? '—']) }}<template v-if="s.override_score !== null && s.override_score !== undefined"> {{ $t('teacherConsole.changedTo01', [s.override_score, s.reviewed_by]) }}</template>
                  <template v-if="s.error"> · <span class="vp-fail">{{ s.error }}</span></template></div>
                <template v-if="s._open">
                  <div v-for="(d, j) in s.details" :key="j" class="det" :class="d.ok === false || d.pass === false ? 'bad' : 'good'">
                    <div class="vp-row sp"><span>{{ d.ok === false || d.pass === false ? '✗' : '✓' }} {{ d.label || d.key }}</span>
                      <span class="mono">{{ fmtNum(d.points ?? d.score) }}/{{ fmtNum(d.weight) }}</span></div>
                    <QuizReveal v-if="d.kind === 'answer' && 'your' in d" :d="d" />
                    <div v-else class="vp-small vp-muted">{{ $t('taskPanel.requirement0Result1', [humanRule(d), humanValue(d)]) }}</div>
                    <el-input v-model="s._rc[d.key]" size="small" :placeholder="$t('teacherConsole.commentsForThisCriterionOptional')" />
                  </div>
                  <div class="vp-sec" style="margin-top: 6px"><div class="lbl">{{ $t('teacherConsole.gradingReplayAutomaticTestRun') }}</div>
                    <div class="replay"><div v-for="(l, k) in (s.log || [])" :key="k" class="vp-small mono">{{ typeof l === 'string' ? l : (l.t !== undefined ? 't=' + l.t + 's ' : '') + (l.msg || JSON.stringify(l)) }}</div>
                      <div v-if="!(s.log || []).length" class="vp-small vp-muted">{{ $t('teacherConsole.noRecords') }}</div></div></div>
                  <div class="vp-sec"><div class="lbl">
                    <span>{{ $t('teacherConsole.n0AtSubmission', [s.program?.model ? $t('teacherConsole.factoryModelPlcProgram') : s.program?.blocks ? $t('dockLists.model') : $t('common.program')]) }}</span><span class="grow" />
                    <el-radio-group v-if="subs[i + 1]" v-model="s._view" size="small"><el-radio-button value="code">{{ $t('teacherConsole.snapshot') }}</el-radio-button><el-radio-button value="diff">{{ $t('teacherConsole.compareWithPrevious') }}</el-radio-button></el-radio-group>
                  </div>
                    <pre v-if="s._view !== 'diff'" class="prog">{{ programText(s.program) || $t('teacherConsole.noSnapshot') }}</pre>
                    <pre v-else class="prog diff"><span v-for="(x, k) in lineDiff(programText(subs[i + 1].program), programText(s.program))" :key="k" :class="'d' + (x.t === '+' ? 'a' : x.t === '-' ? 'r' : 'n')">{{ x.t }} {{ x.s }}
</span></pre>
                  </div>
                </template>
                <!-- 4.6 AI-assisted grading: teachers accept or edit suggested scores and comments per criterion; grades count only after saving the review -->
                <div class="ai-box" :class="{ on: s._ai }" data-k="ai-box">
                  <div class="vp-row sp">
                    <span class="ai-h"><el-icon><MagicStick /></el-icon>{{ $t('teacherConsole.aiSuggestion') }}<small>{{ $t('teacherConsole.forReferenceOnlyCountsToward') }}</small></span>
                    <el-button size="small" text type="primary" :loading="busy === 'ai' + s.id" data-k="ai-suggest" @click="aiOne(s)">{{ s._ai ? $t('teacherConsole.regenerate') : $t('teacherConsole.requestAiReview') }}</el-button>
                  </div>
                  <template v-if="s._ai">
                    <div v-if="s._ai.status === 'error'" class="vp-small vp-fail">{{ s._ai.error }}</div>
                    <template v-else>
                      <div v-for="c in s._ai.criteria" :key="c.key" class="ai-c" :data-key="c.key">
                        <div class="vp-row sp"><span class="ai-l">{{ c.label }}</span>
                          <span class="mono vp-small"><span class="vp-muted" :title="$t('common.automatedChecks')">{{ c.auto === null || c.auto === undefined ? '' : $t('teacherConsole.automatic') + fmtNum(c.auto) + ' · ' }}</span>{{ $t('teacherConsole.recommendation') }} <b>{{ fmtNum(c.score) }}</b>/{{ fmtNum(c.weight) }}</span></div>
                        <div v-if="c.comment" class="vp-row ai-cm"><span class="vp-grow vp-small">{{ c.comment }}</span>
                          <el-button size="small" link type="primary" :disabled="s._rc[c.key] === c.comment" @click="s._rc[c.key] = c.comment">{{ s._rc[c.key] === c.comment ? $t('teacherConsole.applied') : $t('teacherConsole.applyComments') }}</el-button></div>
                      </div>
                      <div class="vp-row sp ai-tot"><span class="vp-small">{{ $t('teacherConsole.suggestedTotalScore') }} <b class="mono" data-k="ai-score">{{ fmtNum(s._ai.score) }}</b>{{ s._ai.fake ? $t('teacherConsole.testMode') : '' }}</span>
                        <el-button size="small" type="primary" plain data-k="ai-accept" @click="aiAccept(s)">{{ $t('teacherConsole.applyScoreAndComments') }}</el-button></div>
                      <div v-if="s._ai.comment" class="vp-small ai-cm">{{ s._ai.comment }}</div>
                    </template>
                  </template>
                </div>
                <div class="vp-row" style="margin-top: 4px">
                  <el-input-number v-model="s._score" size="small" :min="0" :max="100" :precision="1" controls-position="right" style="width: 110px" :placeholder="s.auto_score === null || s.auto_score === undefined ? $t('taskPanel.grade') : $t('taskPanel.changeGrade')" data-k="review-score" />
                  <el-input v-model="s._comment" size="small" :placeholder="$t('teacherConsole.overallComments')" class="vp-grow" />
                </div>
                <div class="vp-row" style="margin-top: 4px">
                  <el-button size="small" type="primary" @click="review(s)">{{ $t('teacherConsole.saveReview') }}</el-button>
                  <el-button size="small" text @click="review(s, true)" v-if="s.override_score !== null && s.override_score !== undefined">{{ $t('teacherConsole.restoreAutoScore') }}</el-button>
                  <el-button v-if="!s._open" size="small" text @click="s._open = true">{{ $t('teacherConsole.viewProgramGradingReplay') }}</el-button>
                  <span class="vp-grow" />
                  <el-button v-if="!saas" size="small" text @click="openReviewSandbox(s)" :loading="busy === 'rv' + s.id" :title="$t('teacherConsole.createAReviewSandboxFrom')"><el-icon><VideoPlay /></el-icon>{{ $t('sections.openAndRun') }}</el-button>
                  <el-button size="small" text @click="downloadPkg(s)" :title="$t('teacherConsole.downloadTheAssignmentPackageVfhw')"><el-icon><Download /></el-icon>{{ $t('packageOpen.assignmentPackage') }}</el-button>
                </div>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
      </div>
    </div>

    <el-dialog v-model="editOpen" :title="$t('teacherConsole.editTask')" width="560px" append-to-body>
      <el-form v-if="editForm" label-width="110px" size="small">
        <el-form-item :label="$t('teacherConsole.taskName')"><el-input v-model="editForm.title" /></el-form-item>
        <el-form-item :label="$t('common.description')"><el-input v-model="editForm.descr" type="textarea" :rows="3" /></el-form-item>
        <el-form-item :label="$t('publishWizard.startTime')"><el-date-picker v-model="editForm.start_at" type="datetime" value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:mm" :placeholder="$t('publishWizard.startNow')" clearable /></el-form-item>
        <el-form-item :label="$t('common.deadline')"><el-date-picker v-model="editForm.due" type="datetime" value-format="YYYY-MM-DD HH:mm" format="YYYY-MM-DD HH:mm" :placeholder="$t('common.noTimeLimit')" clearable /></el-form-item>
        <el-form-item :label="$t('teacherConsole.lateSubmission')"><el-checkbox v-model="editForm.allow_late">{{ $t('publishWizard.allowSubmissionsAfterTheDeadline') }}</el-checkbox></el-form-item>
        <el-form-item :label="$t('publishWizard.submissionLimit')"><el-input-number v-model="editForm.max_subs" :min="0" :max="100" controls-position="right" /><span class="vp-small vp-muted" style="margin-left: 8px">{{ $t('publishWizard.n0Unlimited') }}</span></el-form-item>
        <el-form-item :label="$t('publishWizard.gradingRubric')"><el-checkbox v-model="editForm.show_details">{{ $t('teacherConsole.studentsCanSeeTheirScore') }}</el-checkbox></el-form-item>
        <el-form-item :label="$t('common.correctAnswer')">
          <el-select v-model="editForm.reveal" style="width: 150px" data-k="edit-reveal"><el-option v-for="o in REVEAL_OPTS" :key="o.v" :value="o.v" :label="o.l" /></el-select>
          <span class="vp-small vp-muted" style="margin-left: 8px">{{ revealHint(editForm.reveal, editForm.due) }}</span>
        </el-form-item>
      </el-form>
      <template #footer><el-button size="small" @click="editOpen = false">{{ $t('common.cancel') }}</el-button><el-button size="small" type="primary" @click="saveEdit">{{ $t('common.save') }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="anaOpen" :title="$t('teacherConsole.learningAnalytics0', [prog?.assignment?.title || ''])" width="720px" append-to-body>
      <div v-if="ana">
        <div class="vp-row" style="margin-bottom: 8px">
          <span class="vp-small">{{ $t('teacherConsole.submitted01Students', [ana.submitted, ana.students]) }}</span>
          <span v-for="(n, k) in ana.dist" :key="k" class="vp-small vp-muted">{{ $t('teacherConsole.n0Points1Students', [k, n]) }}</span>
        </div>
        <div v-if="!ana.rules.length" class="vp-empty">{{ $t('teacherConsole.noStudentsHaveSubmittedYet') }}</div>
        <div v-for="r in ana.rules" :key="r.key" class="ana-row">
          <div class="vp-row sp"><b>{{ r.label }}</b><span class="vp-small">{{ $t('teacherConsole.achieved01Students2', [r.pass, r.n, Math.round(r.rate * 100)]) }}</span></div>
          <div class="bar"><div :style="{ width: Math.round(r.rate * 100) + '%' }" :class="r.rate < 0.6 ? 'low' : ''" /></div>
          <div v-for="(e, k) in r.examples" :key="k" class="vp-small vp-muted">· {{ e }}</div>
        </div>
        <div v-if="ana.notsubmitted.length" class="vp-small vp-muted" style="margin-top: 8px">{{ $t('teacherConsole.notYetSubmitted0', [ana.notsubmitted.join($t('common.k360'))]) }}</div>
      </div>
    </el-dialog>
    <el-dialog v-model="lessonWiz" :title="$t('teacherConsole.startALesson')" width="860px" append-to-body destroy-on-close class="fit-dialog">
      <LessonWizard @done="onCoursePublished($event); lessonWiz = false" @cancel="lessonWiz = false" />
    </el-dialog>
    <el-dialog v-model="coursePub" :title="$t('common.publishCourse')" width="820px" append-to-body destroy-on-close class="fit-dialog">
      <CoursePublish @done="onCoursePublished" @cancel="coursePub = false" />
    </el-dialog>
    <el-dialog v-model="wizard" :title="$t('teacherConsole.publishSingleAssignment')" width="820px" append-to-body destroy-on-close class="fit-dialog">
      <PublishWizard @done="onPublished" @cancel="wizard = false" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t, matches } from '../../i18n';
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus';
import { computed, onBeforeUnmount, onMounted, ref, watch as vwatch } from 'vue';
import { del, desk, get, patch, post, saasServer, session } from '../../api';
import { ed } from '../../editor/store';
import CourseProgress from './CourseProgress.vue';
import LessonWizard from './LessonWizard.vue';
import CoursePublish from './CoursePublish.vue';
import QuizReveal from './QuizReveal.vue';
import GuideButton from '../../components/GuideButton.vue';
import PublishWizard from './PublishWizard.vue';
import { faultLabel, fmtNum, metricRows, fmtVal, humanRule, humanValue, lineDiff, PLC_CN, poll, programText, REVEAL_OPTS, revealHint, saveFile, STU_STATE_COLOR, stuState, stuStateLabel, teachBus } from './util';
import './panel.css';

defineProps<{ pid?: string }>();
const assigns = ref<any[]>([]);
const aid = ref<number | null>(null);
const prog = ref<any>(null);
const loading = ref(false);
const sel = ref('');
/** 5.0 SaaS: no server-side sandboxes; no observation, fault injection, or review sandboxes. Show client-reported progress. */
const saas = computed(() => saasServer());
const dtab = ref(saasServer() ? 'live' : 'watch');
const liveLog = ref<any[]>([]);
const watch = ref<any>(null);
const subs = ref<any[]>([]);
const busy = ref('');
const wizard = ref(false);
const coursePub = ref(false);
const lessonWiz = ref(false);
const editOpen = ref(false);
const editForm = ref<any>(null);
const anaOpen = ref(false);
const ana = ref<any>(null);
const takeover = ref<any>(null);
let noticeSince = -1;
const view = ref<'lesson' | 'course'>('lesson');
const filter = ref('');
const stateFilter = ref('');
// state counts: by code when the server sends counts_code, else by display text
const stuCounts = computed<Record<string, number>>(() => prog.value?.counts_code || prog.value?.counts || {});
let stopProg: any = null, stopWatch: any = null;

const groups = computed(() => {
  const m: Record<string, any[]> = {};
  for (const a of assigns.value) (m[`${a.class_name || $t('teacherConsole.noClassAssigned')} · ${a.course_name || $t('teacherConsole.singleTask')}`] ||= []).push(a);
  for (const items of Object.values(m)) items.sort((x: any, y: any) => (x.seq || 0) - (y.seq || 0) || y.id - x.id);
  return Object.entries(m).map(([name, items]) => ({ name, items }));
});
const curAssign = computed(() => assigns.value.find((a) => a.id === aid.value));
/** Factory assignment submissions: no sandbox (no observation or fault injection); view submissions, open runs, and grade. */
const isFactory = computed(() => (prog.value?.assignment?.kind || curAssign.value?.kind) === 'factory');
const allSubs = ref<any[]>([]);
const SUB_ST: Record<string, string> = { submitted: $t('teacherConsole.awaitingGrading'), scored: $t('teacherConsole.autoChecked'), reviewed: $t('teacherConsole.graded'), error: $t('teacherConsole.checkFailed'), scoring: $t('teacherConsole.checking') };
const nameOf = (u: string) => (prog.value?.rows || []).find((r: any) => r.username === u)?.name || u;
function pickSub(s: any) { pick(s.username); dtab.value = 'subs'; }
const rows = computed(() => (prog.value?.rows || []).filter((r: any) => (!stateFilter.value || (prog.value?.counts_code ? stuState(r) : r.state) === stateFilter.value)
  && (!filter.value || r.username.includes(filter.value) || (r.name || '').includes(filter.value))));
const selRow = computed(() => (prog.value?.rows || []).find((r: any) => r.username === sel.value));
const faults = computed(() => prog.value?.assignment?.faults || []);
/** Metrics follow the current lesson: control units use the scenario's stats.metrics (no sorting accuracy in motor start/stop lessons). */
const ruleKeys = computed<string[]>(() => prog.value?.rule_keys || []);

async function loadAssigns() {
  assigns.value = await get('/api/teach/assignments');
  if (!aid.value && assigns.value.length) {
    let last = 0;
    try { last = Number(localStorage.getItem('vf_teach_console_aid') || 0); } catch { /* */ }
    aid.value = assigns.value.some((a) => a.id === last) ? last : assigns.value[0].id;
  }
}
async function loadProgress() {
  if (!aid.value) return;
  try { localStorage.setItem('vf_teach_console_aid', String(aid.value)); } catch { /* */ }
  prog.value = await get(`/api/teach/assignments/${aid.value}/progress`, true);
  if (isFactory.value) {
    allSubs.value = await get(`/api/teach/assignments/${aid.value}/submissions`, true).catch(() => []);
    if (dtab.value === 'watch' || dtab.value === 'fault' || dtab.value === 'live') dtab.value = 'subs';
  } else allSubs.value = [];
}
/** Teacher notifications: fault resolved, control taken over, etc.; shown at the top right. */
async function loadNotices() {
  const r = await get(`/api/teach/notices?since=${Math.max(0, noticeSince)}`, true);
  const fresh = noticeSince < 0 ? [] : r.filter((n: any) => n.id > noticeSince);
  if (r.length) noticeSince = Math.max(noticeSince, ...r.map((n: any) => n.id));
  else if (noticeSince < 0) noticeSince = 0;
  for (const n of fresh.reverse()) ElNotification({ title: n.kind === 'fault_fixed' ? $t('teacherConsole.theStudentResolvedTheFault') : $t('teacherConsole.teachingNotifications'), message: n.msg, type: n.kind === 'fault_fixed' ? 'success' : 'info', duration: 8000 });
}
async function refresh() {
  loading.value = true;
  try { await loadAssigns(); await loadProgress(); } finally { loading.value = false; }
}
function pick(u: string) {
  sel.value = u;
  watch.value = null;
  takeover.value = null;
  loadSubs();
  if (saas.value) loadLive();
}
async function loadLive() {
  liveLog.value = [];
  if (!sel.value || !aid.value) return;
  const r = await get(`/api/teach/assignments/${aid.value}/reported`, true).catch(() => null);
  liveLog.value = (r?.students || []).find((s: any) => s.username === sel.value)?.log || [];
}
async function loadWatch() {
  if (!sel.value || !aid.value) return;
  watch.value = await get(`/api/teach/assignments/${aid.value}/students/${encodeURIComponent(sel.value)}/watch`, true);
}
const SRC_CN: Record<string, string> = { sandbox: $t('teacherConsole.sandbox'), client: $t('common.desktopClient'), import: $t('common.import') };
const SRC_TAG: Record<string, string> = { sandbox: 'info', client: 'success', import: 'warning' };
const SRC_TIP: Record<string, string> = { sandbox: $t('teacherConsole.completedInAServerSandbox'), client: $t('teacherConsole.completedInTheDesktopClient'), import: $t('teacherConsole.assignmentPackageImportedByThe') };
const pkgEl = ref<HTMLInputElement | null>(null);
async function downloadPkg(s: any) {
  await saveFile(`/api/teach/submissions/${s.id}/package`, `${s.username}-${aid.value}-${s.id}.vfhw`);
}
/** Open run: server creates review sandbox sb-review-<submission ID>; shell opens the Workbench (run and use controls, but no program or model edits). */
async function openReviewSandbox(s: any) {
  busy.value = 'rv' + s.id;
  try {
    const r = await post(`/api/teach/submissions/${s.id}/open`, {});
    ed.teach = { ...(ed.teach || {}), assignment: aid.value, pid: r.pid, role: 'teacher', readonly: false, student: s.username, review: s.id, kind: r.kind,
      open: { pid: r.pid, bid: r.bid, readonly: false, review: true, n: Date.now() } };
    if (!ed.teach.handled) {
      const { router } = await import('../../router');
      router.push(`/p/${encodeURIComponent(r.pid)}/workbench`);
    }
  } finally { busy.value = ''; }
}
async function importPkg(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = '';
  if (!f || !sel.value) return;
  await ElMessageBox.confirm($t('teacherConsole.importAssignmentPackage0As', [f.name, sel.value]), $t('teacherConsole.importAssignmentPackage'), { type: 'info' });
  busy.value = 'imp';
  try {
    const r = await fetch(`/api/teach/assignments/${aid.value}/students/${encodeURIComponent(sel.value)}/import_package`, {
      method: 'POST', headers: { Authorization: 'Bearer ' + session.token, 'Content-Type': 'application/octet-stream' }, body: await f.arrayBuffer() });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) { ElMessage.error(typeof j.detail === 'string' ? j.detail : $t('teacherConsole.importFailed')); return; }
    ElMessage.success($t('teacherConsole.importedServerScore0Points', [j.score ?? '—']));
    await loadSubs(); await loadProgress();
  } finally { busy.value = ''; }
}
async function setTakeover(on: boolean) {
  if (on) await ElMessageBox.confirm($t('teacherConsole.takeOver0SSandbox', [sel.value]), $t('sections.takeOver'), { type: 'warning' });
  const r = await post(`/api/teach/assignments/${aid.value}/students/${encodeURIComponent(sel.value)}/takeover`, { on });
  takeover.value = r.takeover;
  if (on && watch.value?.pid) {
    ed.teach = { ...(ed.teach || {}), assignment: aid.value, pid: watch.value.pid, role: 'teacher', readonly: false, student: sel.value,
      open: { pid: watch.value.pid, bid: watch.value.bid, readonly: false, n: Date.now() } };
  }
}
async function loadSubs() {
  if (!sel.value) return;
  const [r, ai] = await Promise.all([get(`/api/teach/assignments/${aid.value}/submissions?username=${encodeURIComponent(sel.value)}`),
    get(`/api/teach/assignments/${aid.value}/ai_suggestions`, true).catch(() => ({ items: [] }))]);
  const by: Record<number, any> = {};
  for (const x of ai.items || []) by[x.sub_id] = x;
  subs.value = r.map((s: any, i: number) => ({ ...s, _score: s.override_score ?? s.auto_score ?? undefined, _comment: s.comment || '', _rc: { ...(s.rule_comments || {}) },
    _open: i === 0, _view: 'code', _ai: by[s.id] && by[s.id].status !== 'running' ? by[s.id] : null, _aiTaken: false }));
}
// ---- 4.6 AI-assisted grading ----
const aiJob = ref<any>(null);
const aiFake = ref(false);
async function aiOne(s: any) {
  busy.value = 'ai' + s.id;
  try {
    const r = await post(`/api/teach/submissions/${s.id}/ai_suggest`, { force: !!s._ai });
    s._ai = r.suggestion; aiFake.value = !!r.fake;
  } finally { busy.value = ''; }
}
/** Accept: copy suggested scores and comments into the review fields below (not saved; grades count only after the teacher clicks "Save Review"). */
function aiAccept(s: any) {
  const a = s._ai;
  if (!a) return;
  s._score = a.score; s._comment = a.comment || s._comment;
  for (const c of a.criteria || []) if (c.comment) s._rc[c.key] = c.comment;
  s._aiTaken = true;
  ElMessage.info($t('teacherConsole.reviewFieldsFilledInCheck'));
}
let stopJob: any = null;
async function aiAll() {
  const n = prog.value?.rows?.filter((r: any) => r.submissions).length || 0;
  await ElMessageBox.confirm($t('teacherConsole.askAiToReviewEach', [n]), $t('teacherConsole.generateAiSuggestionsForClass'), { type: 'info', confirmButtonText: $t('common.start') });
  const r = await post(`/api/teach/assignments/${aid.value}/ai_suggest_all`, {});
  aiFake.value = !!r.fake;
  aiJob.value = { total: r.total, done: 0, failed: 0, running: r.total > 0, id: r.job };
  stopJob?.();
  stopJob = poll(async () => {
    const j = await get(`/api/teach/ai_jobs/${r.job}`, true);
    aiJob.value = { ...j };
    if (!j.running) { stopJob?.(); stopJob = null; if (sel.value) loadSubs(); }
  }, 1000);
}
vwatch([sel, dtab, aid], () => {
  stopWatch?.(); stopWatch = null;
  if (sel.value && dtab.value === 'watch' && !saas.value) stopWatch = poll(loadWatch, 2000);
});

async function inject(f: any, i: number) {
  busy.value = 'f' + i;
  try {
    await post(`/api/teach/assignments/${aid.value}/students/${encodeURIComponent(sel.value)}/faults`, { comp: f.comp, kind: f.kind });
    ElMessage.success($t('teacherConsole.injectedInto01', [sel.value, faultLabel(f)]));
  } finally { busy.value = ''; }
}
async function clearFaults() {
  await del(`/api/teach/assignments/${aid.value}/students/${encodeURIComponent(sel.value)}/faults`);
  ElMessage.success($t('teacherConsole.cleared'));
}
async function review(s: any, restore = false) {
  const body: any = { comment: s._comment, rule_comments: s._rc };
  if (s._ai && s._ai.status === 'ok' && !restore) {                         // Record how the teacher handled AI suggestions (accepted / edited)
    const same = s._aiTaken && Number(s._score) === Number(s._ai.score) && s._comment === s._ai.comment;
    post(`/api/teach/submissions/${s.id}/ai_decision`, { decision: s._aiTaken ? (same ? 'accepted' : 'edited') : 'dismissed' }).catch(() => undefined);
  }
  const has = (v: any) => v !== null && v !== undefined;
  if (restore) body.score = null;                                             // Restore automatic score
  else if (has(s._score) && s._score !== s.auto_score) body.score = s._score;   // Override score
  else if (has(s.override_score)) body.score = null;                           // Matching the automatic score cancels the override
  await post(`/api/teach/submissions/${s.id}/review`, body);
  ElMessage.success($t('common.saved'));
  await loadSubs();
  await loadProgress();
}
/** Observe: ask the shell to open the student's sandbox read-only (ed.teach.open.readonly = true). */
function openWatch() {
  if (!watch.value) return;
  ed.teach = { ...(ed.teach || {}), assignment: aid.value, pid: watch.value.pid, bid: watch.value.bid, role: 'teacher', readonly: true,
    student: sel.value, open: { pid: watch.value.pid, bid: watch.value.bid, readonly: true, n: Date.now() } };
}
async function assignCmd(cmd: string) {
  const a = prog.value.assignment;
  if (cmd === 'edit') {
    editForm.value = { title: a.title, descr: a.descr || '', due: a.due, start_at: a.start_at, allow_late: a.allow_late !== false, max_subs: a.max_subs || 0,
      show_details: a.show_details !== false, reveal: a.reveal || 'submit' };
    editOpen.value = true;
    return;
  }
  if (cmd === 'analytics') { ana.value = await get(`/api/teach/assignments/${a.id}/analytics`); anaOpen.value = true; return; }
  if (cmd === 'toggle') await patch(`/api/teach/assignments/${a.id}`, { status: a.status === 'published' ? 'closed' : 'published' });
  else if (cmd === 'tutor') await patch(`/api/teach/assignments/${a.id}`, { tutor: !a.tutor });
  else if (cmd === 'hints') await patch(`/api/teach/assignments/${a.id}`, { hints: !a.hints });
  else if (cmd === 'preview') {
    const r = await post(`/api/teach/assignments/${a.id}/sandbox`);
    ed.teach = { ...(ed.teach || {}), assignment: a.id, pid: r.pid, bid: r.bid, role: 'teacher', readonly: false, open: { pid: r.pid, bid: r.bid, n: Date.now() } };
    ElMessage.success($t('teacherConsole.teacherSandbox0IsReady', [r.pid]));
    return;
  } else if (cmd === 'delete') {
    await ElMessageBox.confirm($t('teacherConsole.deleteTask0AllStudent', [a.title]), $t('teacherConsole.deleteTask'), { type: 'warning' });
    await del(`/api/teach/assignments/${a.id}`);
    aid.value = null; prog.value = null; sel.value = '';
  }
  await refresh();
}
async function saveEdit() {
  await patch(`/api/teach/assignments/${aid.value}`, { ...editForm.value, max_subs: editForm.value.max_subs || null });
  editOpen.value = false;
  ElMessage.success($t('common.saved'));
  await refresh();
}
async function onPublished(id: number) {
  wizard.value = false;
  aid.value = id;
  await refresh();
}
async function onCoursePublished(v: { course: string; class_id: number }) {
  coursePub.value = false;
  await loadAssigns();
  const first = assigns.value.filter((a) => a.course === v.course && a.class_id === v.class_id).sort((x, y) => (x.seq || 0) - (y.seq || 0))[0];
  if (first) { aid.value = first.id; view.value = 'course'; }
  await loadProgress();
}
function onPickAssign() { view.value = 'lesson'; sel.value = ''; loadProgress(); }
function gotoLesson(a: number, username?: string) {
  aid.value = a; view.value = 'lesson';
  loadProgress().then(() => { if (username) pick(username); });
}
async function makeDemo() {
  busy.value = 'demo';
  try {
    const r = await post('/api/teach/demo');
    ElMessage.success($t('teacherConsole.created01StudentsPassword', [r.class_name, r.students.length, r.password, r.lessons]));
    aid.value = null;
    await refresh();
    const first = assigns.value.filter((a) => a.course === 'machining' && a.class_id === r.class_id).sort((x, y) => (x.seq || 0) - (y.seq || 0))[0];
    if (first) { aid.value = first.id; view.value = 'course'; await loadProgress(); }
  } finally { busy.value = ''; }
}
function progText(p: any) { return programText(p); }

let stopNotice: any = null;
// Click a gradebook score → open the review for this assignment and student
vwatch(() => teachBus.review?.n, async () => {
  const r = teachBus.review;
  if (!r) return;
  if (!assigns.value.some((a) => a.id === r.aid)) await loadAssigns();
  aid.value = r.aid; view.value = 'lesson';
  await loadProgress();
  if (r.username) { pick(r.username); dtab.value = 'subs'; }
});
vwatch(() => teachBus.classes, loadAssigns);
onMounted(async () => {
  await refresh();
  stopProg = poll(loadProgress, 4000);
  stopNotice = poll(loadNotices, 5000);
});
onBeforeUnmount(() => { stopProg?.(); stopWatch?.(); stopNotice?.(); stopJob?.(); });
</script>

<style scoped>
.tc-body { padding: 10px; }
.empty-start { max-width: 560px; margin: 40px auto; }
.empty-start .es-t { font-size: 16px; font-weight: 600; color: var(--el-text-color-primary); margin-bottom: 6px; }
.empty-start .es-d { font-size: 13px; line-height: 1.7; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px; }
.stu { border: 1px solid var(--el-border-color-lighter); border-left: 4px solid var(--el-border-color); border-radius: 6px; padding: 7px 9px; cursor: pointer; background: var(--el-fill-color-blank); min-width: 0; }
.stu:hover { border-color: var(--el-color-primary-light-5); }
.stu.on { box-shadow: 0 0 0 2px var(--el-color-primary) inset; }
.stu .sc { font-size: 18px; font-weight: 700; font-variant-numeric: tabular-nums; }
.ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cnt { font-size: 12px; margin-right: 6px; white-space: nowrap; }
.detail { width: 340px !important; border-left: 1px solid var(--el-border-color-lighter); padding-left: 12px; }
.det { border-top: 1px solid var(--el-border-color-extra-light); padding: 5px 0; }
.det.bad > .vp-row span:first-child { color: var(--bad, var(--el-color-danger)); }
.replay { max-height: 140px; overflow: auto; background: var(--el-fill-color-light); border-radius: 4px; padding: 4px 6px; }
.diff .da { color: var(--ok, var(--el-color-success)); background: var(--el-color-success-light-9); }
.diff .dr { color: var(--bad, var(--el-color-danger)); background: var(--el-color-danger-light-9); text-decoration: line-through; }
.ana-row { margin-bottom: 10px; }
.bar { height: 8px; background: var(--el-fill-color); border-radius: 4px; overflow: hidden; margin: 3px 0; }
.bar > div { height: 100%; background: var(--ok, var(--el-color-success)); }
.bar > div.low { background: var(--bad, var(--el-color-danger)); }
.prog { max-height: 220px; overflow: auto; background: var(--el-fill-color-light); padding: 6px 8px; border-radius: 4px; font-size: 11.5px; margin: 0; white-space: pre-wrap; }
.sub { margin-bottom: 8px; }
.fault { padding: 6px 10px; }
.fac-subs { margin-bottom: 10px; }
.fs-row { cursor: pointer; }
.ai-job { display: flex; align-items: center; gap: 10px; padding: 8px 12px; border-bottom: 1px solid var(--el-border-color-lighter); background: var(--el-color-primary-light-9); flex-wrap: wrap; }
.ai-box { margin: 6px 0 2px; border: 1px dashed var(--hm-ai-ring); border-radius: var(--hm-r-sm); padding: 5px 8px; background: var(--hm-ai-soft); }
.ai-box .ai-h { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; font-weight: 600; color: var(--hm-primary-press); }
.ai-box .ai-h small { font-weight: 400; color: var(--el-text-color-secondary); margin-left: 4px; }
.ai-c { border-top: 1px solid var(--el-border-color-extra-light); padding: 4px 0; }
.ai-l { font-size: 12px; }
.ai-cm { color: var(--el-text-color-regular); line-height: 1.5; }
.ai-tot { border-top: 1px solid var(--el-border-color-lighter); padding-top: 5px; margin-top: 2px; }
.fs-row:hover td { background: var(--el-fill-color-light); }
</style>
