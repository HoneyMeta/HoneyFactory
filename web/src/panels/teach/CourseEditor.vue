<template>
  <div class="ce" data-k="course-editor">
    <header class="ce-top">
      <el-button size="small" text @click="emit('back')"><el-icon><Back /></el-icon>{{ $t('common.courses') }}</el-button>
      <b class="ce-name">{{ c.name || $t('teach.newCourse') }}</b>
      <el-tag size="small" :type="st.version ? (st.dirty ? 'warning' : 'success') : 'info'" effect="plain" data-k="ce-status">
        {{ st.version ? (st.dirty ? $t('courseEditor.publishedV0UnpublishedChanges', [st.version]) : $t('courseEditor.publishedV0', [st.version])) : $t('common.draft') }}</el-tag>
      <span v-if="saveMsg" class="vp-small vp-muted">{{ saveMsg }}</span>
      <span class="grow" />
      <el-badge :value="errors" :hidden="!errors" type="danger"><el-button size="small" :type="issuesOpen ? 'primary' : 'default'" plain data-k="ce-checks-btn" @click="issuesOpen = !issuesOpen">
        <el-icon v-if="job.running" class="is-loading"><Loading /></el-icon><el-icon v-else><WarningFilled /></el-icon>{{ $t('courseEditor.assignmentCheck01Warnings', [errors ? $t('courseEditor.errors0', [errors]) : '', warns]) }}</el-button></el-badge>
      <el-button size="small" :loading="busy === 'save'" data-k="ce-save" @click="save()"><el-icon><DocumentChecked /></el-icon>{{ $t('common.save') }}</el-button>
      <el-button size="small" :loading="busy === 'preview'" :disabled="!!blockingPreview" data-k="ce-preview" @click="preview"><el-icon><View /></el-icon>{{ $t('courseEditor.previewAsStudent') }}</el-button>
      <el-button size="small" type="primary" :loading="busy === 'publish'" :disabled="!!errors" data-k="ce-publish" @click="publish"><el-icon><Promotion /></el-icon>{{ st.version ? $t('courseEditor.publishNewVersion') : $t('courseEditor.publish') }}</el-button>
    </header>
    <!-- 4.6.1 Authoring checks: errors (block publishing) / warnings / notes + trial results per lesson (score with no student changes, whether the reference solution passes) -->
    <div v-if="issuesOpen" class="ce-checks" data-k="ce-checks">
      <div class="ck-head">
        <b>{{ $t('courseEditor.assignmentCheck') }}</b>
        <span class="ck-count"><span class="ck-e">{{ $t('courseEditor.errors02', [errors]) }}</span><span class="ck-w">{{ $t('courseEditor.warnings0', [warns]) }}</span></span>
        <span v-if="job.running" class="ck-run" data-k="ck-running"><el-icon class="is-loading"><Loading /></el-icon>{{ $t('courseEditor.testRunningStartingModel0', [job.done, job.total]) }}
          <el-progress :percentage="job.total ? Math.round(((job.done || 0) + 0.35) / job.total * 100) : 0" :stroke-width="6" :show-text="false" class="ck-prog" :indeterminate="!job.done" /></span>
        <span class="grow" />
        <el-button size="small" text :disabled="!!job.running" data-k="ck-rerun" @click="runChecks(true)"><el-icon><Refresh /></el-icon>{{ $t('courseEditor.rerunTest') }}</el-button>
        <el-button link :title="$t('common.collapse')" @click="issuesOpen = false"><el-icon><Close /></el-icon></el-button>
      </div>
      <div class="vp-small vp-muted ck-note">{{ $t('courseEditor.fixAllErrorsBeforePublishing') }}</div>
      <div v-if="!issues.length" class="vp-small vp-pass" data-k="ck-clean">{{ $t('courseEditor.noIssuesFoundReadyTo') }}</div>
      <div v-for="g in issueGroups" :key="g.key" class="ck-group" :data-lesson="g.lesson || ''">
        <div class="ck-where" :class="{ link: !!g.lesson }" @click="g.lesson && gotoLesson(g.lesson)">{{ g.where }}</div>
        <div v-for="(i, k) in g.items" :key="k" class="ck-item" :class="'lv-' + i.level" :data-code="i.code">
          <span class="ck-sev">{{ SEV[i.level] || i.level }}</span>
          <span class="ck-msg">{{ i.msg }}</span>
          <span class="ck-acts">
            <el-button v-if="i.fix?.kind === 'weights'" size="small" type="primary" plain data-k="fix-weights" @click="applyFix(i)">{{ $t('courseEditor.scaleTo100') }}</el-button>
            <el-button v-else-if="i.fix?.kind === 'label'" size="small" plain data-k="fix-label" @click="applyFix(i)">{{ $t('courseEditor.useAsName') }}</el-button>
            <el-button v-if="i.lesson && !['no_reference', 'baseline_pending'].includes(i.code)" size="small" text @click="gotoIssue(i)">{{ $t('courseEditor.edit') }}</el-button>
          </span>
        </div>
        <div v-if="g.lesson && baseline[g.lesson]?.start" class="ck-base" data-k="ck-baseline">
          <table>
            <tr><th>{{ $t('courseEditor.criterion') }}</th><th>{{ kindOf(g.lesson) === 'cell' ? $t('courseEditor.startingStateNoCode') : $t('courseEditor.startingModelUnchanged') }}</th><th v-if="baseline[g.lesson].ref">{{ REF_CN[baseline[g.lesson].ref_source] || $t('courseEditor.referenceSolution') }}</th></tr>
            <tr v-for="d in baseline[g.lesson].start.details" :key="d.key">
              <td>{{ d.label }}</td><td :class="d.ok ? 'ok' : 'no'">{{ d.ok ? '✓' : '✗' }} {{ d.value_text }}</td>
              <td v-if="baseline[g.lesson].ref" :class="refRow(g.lesson, d.key)?.ok ? 'ok' : 'no'">{{ refRow(g.lesson, d.key)?.ok ? '✓' : '✗' }} {{ refRow(g.lesson, d.key)?.value_text }}</td>
            </tr>
            <tr class="tot"><td>{{ $t('courseEditor.scoreOutOf100Pass', [baseline[g.lesson].pass]) }}</td>
              <td :class="baseline[g.lesson].start.pct >= baseline[g.lesson].pass ? 'no' : 'ok'" data-k="ck-start-score">{{ $t('common.n0Min', [baseline[g.lesson].start.pct]) }}</td>
              <td v-if="baseline[g.lesson].ref" :class="baseline[g.lesson].ref.pct >= baseline[g.lesson].pass ? 'ok' : 'no'" data-k="ck-ref-score">{{ $t('common.n0Min', [baseline[g.lesson].ref.pct]) }}</td></tr>
          </table>
        </div>
        <div v-if="g.lesson && refs[g.lesson]" class="vp-small ck-ref" data-k="ck-ref">{{ $t('courseEditor.referenceSolutionSavedBy0', [String(refs[g.lesson].created || '').slice(5, 16), (refs[g.lesson].summary || []).join($t('common.k344'))]) }}
          <el-button link type="danger" size="small" @click="delRef(g.lesson)">{{ $t('common.delete') }}</el-button></div>
      </div>
    </div>
    <div class="ce-main">
      <!-- Left: outline (course → chapter → lesson), with move up/down controls -->
      <aside class="ce-tree">
        <div class="tn meta" :class="{ on: sel.t === 'course' }" @click="sel = { t: 'course' }"><el-icon><Notebook /></el-icon>{{ $t('courseEditor.courseInformation') }}</div>
        <div v-for="(ch, ci) in c.chapters" :key="ch._k" class="tch">
          <div class="tn ch" :class="{ on: sel.t === 'ch' && sel.ci === ci }" @click="sel = { t: 'ch', ci }">
            <span class="num">{{ ci + 1 }}</span><span class="tt">{{ ch.title || $t('courseEditor.untitledChapter') }}</span>
            <span class="ops" @click.stop><el-button link size="small" :disabled="!ci" :title="$t('courseEditor.moveUp')" @click="moveCh(ci, -1)"><el-icon><Top /></el-icon></el-button>
              <el-button link size="small" :disabled="ci === c.chapters.length - 1" :title="$t('courseEditor.moveDown')" @click="moveCh(ci, 1)"><el-icon><Bottom /></el-icon></el-button></span>
          </div>
          <div v-for="(l, li) in ch.lessons" :key="l._k" class="tn ls" :class="{ on: sel.t === 'l' && sel.ci === ci && sel.li === li, bad: lessonBad(l) }" :data-lesson="l.id" @click="sel = { t: 'l', ci, li }">
            <el-icon><component :is="KIND_ICON[l.kind] || 'Reading'" /></el-icon><span class="tt">{{ l.title || $t('courseEditor.untitledLesson') }}</span>
            <span class="ops" @click.stop><el-button link size="small" :title="$t('courseEditor.moveUp')" @click="moveL(ci, li, -1)"><el-icon><Top /></el-icon></el-button>
              <el-button link size="small" :title="$t('courseEditor.moveDown')" @click="moveL(ci, li, 1)"><el-icon><Bottom /></el-icon></el-button></span>
          </div>
          <el-dropdown trigger="click" @command="(t: string) => addLesson(ci, t)">
            <el-button size="small" text type="primary" class="add-l" :data-k="'add-lesson-' + ci"><el-icon><Plus /></el-icon>{{ $t('courseEditor.addLesson') }}</el-button>
            <template #dropdown><el-dropdown-menu>
              <el-dropdown-item v-for="t in meta.templates" :key="t.id" :command="t.id" :data-tpl="t.id"><el-icon><component :is="t.icon" /></el-icon>{{ t.name }}</el-dropdown-item>
            </el-dropdown-menu></template>
          </el-dropdown>
        </div>
        <el-button size="small" class="add-ch" data-k="add-chapter" @click="addChapter"><el-icon><Plus /></el-icon>{{ $t('courseEditor.addChapter') }}</el-button>
      </aside>

      <!-- Right: selected item -->
      <section class="ce-form">
        <!-- Course info -->
        <template v-if="sel.t === 'course'">
          <h3>{{ $t('courseEditor.courseInformation') }}</h3>
          <el-form label-width="96px" size="small">
            <el-form-item :label="$t('courseEditor.courseName')"><el-input v-model="c.name" maxlength="60" show-word-limit data-k="ce-course-name" /></el-form-item>
            <el-form-item :label="$t('courseEditor.description')"><el-input v-model="c.desc" type="textarea" :rows="3" maxlength="400" show-word-limit :placeholder="$t('courseEditor.aTwoLineDescriptionShown')" /></el-form-item>
            <el-form-item :label="$t('courseEditor.difficulty')"><el-rate v-model="c.level" :max="5" /></el-form-item>
            <el-form-item :label="$t('courseEditor.tags')"><el-select v-model="c.tags" multiple filterable allow-create default-first-option :placeholder="$t('courseEditor.eGPlcProductionLine')" style="width: 100%" /></el-form-item>
            <el-form-item :label="$t('courseEditor.cover')">
              <div class="covers">
                <div v-for="u in meta.covers" :key="u" class="cv" :class="{ on: c.cover === u }" @click="c.cover = u"><img :src="u" alt="" /></div>
                <div v-if="String(c.cover || '').startsWith('assets/')" class="cv on"><img :src="coverUrl" alt="" /></div>
                <label class="cv up"><input type="file" accept=".png,.jpg,.jpeg,.webp" @change="upload" /><el-icon :size="20"><Upload /></el-icon><span>{{ $t('reportExport.upload') }}</span></label>
              </div>
            </el-form-item>
            <el-form-item :label="$t('courseEditor.share')"><el-switch v-model="shared" :active-text="$t('courseEditor.oncePublishedOtherTeachersCan')" /></el-form-item>
          </el-form>
        </template>

        <!-- Chapter -->
        <template v-else-if="sel.t === 'ch' && curCh">
          <h3>{{ $t('courseEditor.chapter0', [sel.ci! + 1]) }}</h3>
          <el-form label-width="96px" size="small">
            <el-form-item :label="$t('courseEditor.chapterTitle')"><el-input v-model="curCh.title" maxlength="40" data-k="ce-ch-title" /></el-form-item>
            <el-form-item :label="$t('common.no2')"><el-input v-model="curCh.id" style="width: 160px" /></el-form-item>
            <el-form-item><el-button type="danger" plain :disabled="c.chapters.length <= 1" @click="delChapter(sel.ci!)">{{ $t('courseEditor.deleteThisChapterAndIts') }}</el-button></el-form-item>
          </el-form>
        </template>

        <!-- Lesson -->
        <template v-else-if="sel.t === 'l' && curL">
          <div class="lh"><span class="kchip" :class="curL.kind"><el-icon><component :is="KIND_ICON[curL.kind]" /></el-icon>{{ tplName(curL) }}</span>
            <h3>{{ curL.title || $t('courseEditor.untitledLesson') }}</h3><span class="grow" />
            <el-button size="small" text type="danger" @click="delLesson(sel.ci!, sel.li!)"><el-icon><Delete /></el-icon>{{ $t('courseEditor.deleteThisLesson') }}</el-button></div>
          <el-tabs v-model="ltab" class="ltabs">
            <el-tab-pane :label="$t('cellInspector.basic')" name="base">
              <el-form label-width="96px" size="small">
                <el-form-item :label="$t('courseEditor.lessonName')"><el-input v-model="curL.title" maxlength="60" data-k="ce-l-title" /></el-form-item>
                <el-form-item :label="$t('common.no2')"><el-input v-model="curL.id" style="width: 160px" /><span class="vp-small vp-muted" style="margin-left: 8px">{{ $t('courseEditor.lettersAndNumbersOnlyDo') }}</span></el-form-item>
                <el-form-item :label="$t('courseEditor.unlock')">
                  <el-radio-group v-model="unlockMode">
                    <el-radio value="prev">{{ $t('courseEditor.unlockAfterPassingPreviousLesson') }}</el-radio><el-radio value="after">{{ $t('courseEditor.specifyPrerequisites') }}</el-radio><el-radio value="free">{{ $t('courseEditor.alwaysUnlocked') }}</el-radio>
                  </el-radio-group>
                </el-form-item>
                <el-form-item v-if="unlockMode === 'after'" :label="$t('courseEditor.prerequisites')">
                  <el-select v-model="curL.unlock.after" multiple style="width: 100%" :placeholder="$t('courseEditor.selectLessonsThatComeBefore')">
                    <el-option v-for="o in earlier" :key="o.id" :value="o.id" :label="o.title" /></el-select></el-form-item>
                <el-form-item :label="$t('courseEditor.passingScore')"><el-input-number :model-value="curL.unlock?.min ?? 60" :min="0" :max="100" controls-position="right" @change="(v: any) => setUnlockMin(v)" />
                  <span class="vp-small vp-muted" style="margin-left: 8px">{{ $t('courseEditor.studentsMustReachThisScore') }}</span></el-form-item>
                <el-form-item :label="$t('common.assignmentBrief')"><el-input v-model="curL.brief_md" type="textarea" :rows="8" :placeholder="$t('courseEditor.assignmentBriefShownToStudents')" data-k="ce-brief" /></el-form-item>
                <el-form-item :label="$t('common.hint')"><div class="hints">
                  <div v-for="(h, i) in curL.hints" :key="i" class="vp-row"><el-input v-model="curL.hints[i]" class="vp-grow" :placeholder="$t('courseEditor.hintsForStudentsWhoGet')" /><el-button link @click="curL.hints.splice(i, 1)"><el-icon><Delete /></el-icon></el-button></div>
                  <el-button size="small" text type="primary" @click="curL.hints.push('')"><el-icon><Plus /></el-icon>{{ $t('courseEditor.addHint') }}</el-button></div></el-form-item>
              </el-form>
            </el-tab-pane>

            <!-- PLC lab -->
            <el-tab-pane v-if="curL.kind === 'cell'" :label="$t('courseEditor.scenarioGrading')" name="spec">
              <el-form label-width="96px" size="small">
                <el-form-item :label="$t('courseEditor.labScenario')">
                  <el-select v-model="curL.scene" filterable style="width: 100%" data-k="ce-scene" @change="onScene">
                    <el-option v-for="s in meta.scenes" :key="s.id" :value="s.id" :label="`${s.id} ${s.name}`" /></el-select></el-form-item>
                <el-form-item :label="$t('courseEditor.lockModel')"><el-switch :model-value="curL.lock_model !== false" :active-text="$t('courseEditor.studentsCanOnlyWriteCode')" @change="(v: any) => (curL.lock_model = v ? undefined : false)" /></el-form-item>
                <el-form-item v-if="scene" :label="$t('courseEditor.criterion')">
                  <div class="rubric">
                    <el-checkbox-group :model-value="rubric" @change="(v: any) => (curL.rubric = v)">
                      <div v-for="r in scene.rules" :key="r.key" class="rb"><el-checkbox :value="r.key">{{ r.label || r.key }}</el-checkbox><span class="vp-muted vp-small">{{ $t('common.n0Min', [r.weight]) }}</span></div>
                    </el-checkbox-group>
                    <div class="vp-small vp-muted">{{ $t('courseEditor.uncheckedCriteriaAreExcludedFrom') }}</div>
                  </div>
                </el-form-item>
                <el-form-item v-if="scene" :label="$t('courseEditor.customChecks')">
                  <div class="xt">
                    <div class="vp-small vp-muted" style="margin-bottom: 6px">{{ $t('courseEditor.examplePressStartAtT') }}</div>
                    <div v-for="(x, i) in custom" :key="i" class="xt-row" :data-custom="i">
                      <span>t</span><el-input-number v-model="x.t" :min="0" :step="0.5" size="small" controls-position="right" style="width: 86px" />
                      <span>{{ $t('courseEditor.sPress') }}</span><el-select v-model="x.press" size="small" style="width: 110px" :placeholder="$t('common.button')"><el-option v-for="e in ioIn" :key="e.name" :value="e.name" :label="e.name" /></el-select>
                      <span>{{ $t('common.k521') }}</span><el-input-number v-model="x.within" :min="0" :step="0.5" size="small" controls-position="right" style="width: 80px" /><span>{{ $t('courseEditor.sWithin') }}</span>
                      <el-select v-model="x.out" size="small" style="width: 110px" :placeholder="$t('common.output')"><el-option v-for="e in ioOut" :key="e.name" :value="e.name" :label="e.name" /></el-select>
                      <span>=</span><el-select v-model="x.eq" size="small" style="width: 60px"><el-option :value="1" label="1" /><el-option :value="0" label="0" /></el-select>
                      <el-input-number v-model="x.weight" :min="0" :max="100" size="small" controls-position="right" style="width: 80px" /><span>{{ $t('courseEditor.points') }}</span>
                      <el-button link @click="custom.splice(i, 1); syncCustom()"><el-icon><Delete /></el-icon></el-button>
                    </div>
                    <el-button size="small" text type="primary" data-k="ce-add-check" @click="custom.push({ t: 1, press: ioIn[0]?.name || '', within: 1, out: ioOut[0]?.name || '', eq: 1, weight: 10 }); syncCustom()"><el-icon><Plus /></el-icon>{{ $t('courseEditor.addCheck') }}</el-button>
                  </div>
                </el-form-item>
              </el-form>
            </el-tab-pane>

            <!-- Line task / Object selection -->
            <el-tab-pane v-if="['plant', 'point', 'diagnose'].includes(curL.kind)" :label="$t('common.factory')" name="plant">
              <el-form label-width="96px" size="small">
                <el-form-item :label="$t('courseEditor.factoryTemplate')">
                  <el-select v-model="curL.plant" filterable style="width: 100%" data-k="ce-plant" @change="() => { curL.params = []; delete curL.model; }">
                    <el-option v-for="p in meta.plants" :key="p.id" :value="p.id" :label="$t('common.n012', [p.name, p.id])" /></el-select></el-form-item>
                <template v-if="plant">
                  <el-form-item :label="$t('courseEditor.presetParameters')">
                    <div class="ptab">
                      <div v-for="(e, i) in curL.params" :key="i" class="vp-row">
                        <el-select v-model="e.block" size="small" style="width: 160px" :placeholder="$t('common.equipment')"><el-option v-for="b in plant.blocks" :key="b.id" :value="b.id" :label="`${b.id} ${b.name}`" /></el-select>
                        <el-select v-model="e.param" size="small" style="width: 140px" :placeholder="$t('common.parameters')" allow-create filterable><el-option v-for="(v, k) in blockOf(e.block)?.params || {}" :key="k" :value="k" :label="String(k)" /></el-select>
                        <el-input v-model="e.value" size="small" style="width: 140px" :placeholder="String(blockOf(e.block)?.params?.[e.param] ?? $t('common.value'))" @change="numify(e)" />
                        <el-button link @click="curL.params.splice(i, 1)"><el-icon><Delete /></el-icon></el-button>
                      </div>
                      <el-button size="small" text type="primary" @click="curL.params.push({ block: plant.blocks[0]?.id, param: '', value: '' })"><el-icon><Plus /></el-icon>{{ $t('courseEditor.editParameter') }}</el-button>
                    </div></el-form-item>
                  <el-form-item :label="$t('courseEditor.studentEditable')">
                    <el-select v-model="editable" multiple filterable style="width: 100%" :placeholder="$t('courseEditor.noneSelectedUnrestrictedCourseDefaul')" data-k="ce-editable">
                      <el-option v-for="o in paramOptions" :key="o" :value="o" :label="o" /></el-select></el-form-item>
                  <el-form-item :label="$t('courseEditor.structure')"><el-switch :model-value="!!curL.lock?.structure" :active-text="$t('courseEditor.equipmentAndConnectionsCannotBe')" @change="(v: any) => setLock('structure', v || undefined)" /></el-form-item>
                  <el-form-item v-if="curL.kind !== 'point'" :label="$t('workbench.simulation')">
                    <span class="vp-small">{{ $t('courseEditor.run') }}</span><el-input-number v-model="curL.time_h" :min="0.5" :max="168" :step="1" size="small" controls-position="right" style="width: 100px" />
                    <span class="vp-small">{{ $t('courseEditor.hoursRandomSeed') }}</span><el-input-number v-model="curL.seed" :min="1" :max="99999" size="small" controls-position="right" style="width: 100px" />
                    <span class="vp-small">{{ $t('common.warmUp') }}</span><el-input-number v-model="curL.warmup_h" :min="0" :max="24" size="small" controls-position="right" style="width: 90px" /><span class="vp-small">{{ $t('common.hours') }}</span></el-form-item>
                </template>
              </el-form>
            </el-tab-pane>

            <!-- Criteria / Questions -->
            <el-tab-pane v-if="curL.kind !== 'cell'" :label="curL.kind === 'quiz' ? $t('courseEditor.question') : curL.kind === 'mes' ? $t('courseEditor.mesChecks') : $t('courseEditor.objectivesQuestions')" name="rules">
              <div v-if="curL.kind === 'mes'" class="vp-card vp-small mes-note">{{ $t('courseEditor.mesLabStudentsCompleteTasks') }} <code>work_orders.released</code>{{ $t('courseEditor.ifMesIsNotConnected') }}</div>
              <div v-for="(r, i) in curL.rules" :key="i" class="rl vp-card" :data-rule="r.key">
                <div class="vp-row">
                  <el-select :model-value="ruleType(r)" size="small" style="width: 128px" @change="(v: string) => setRuleType(r, v)">
                    <el-option v-for="o in ruleTypes" :key="o.v" :value="o.v" :label="o.l" /></el-select>
                  <el-input v-model="r.label" size="small" class="vp-grow" :placeholder="r.kind === 'answer' ? $t('courseEditor.question') : $t('courseEditor.nameOptionalAutoGenerated')" data-k="rule-label" />
                  <el-input-number v-model="r.weight" :min="0" :max="100" size="small" controls-position="right" style="width: 90px" /><span class="vp-small">{{ $t('courseEditor.points') }}</span>
                  <el-button link @click="curL.rules.splice(i, 1)"><el-icon><Delete /></el-icon></el-button>
                </div>
                <div v-if="goalOf(r)" class="vp-small vp-muted rl-goal" data-k="rule-goal">{{ $t('courseEditor.studentsSee') }}<b>{{ goalOf(r).title }}</b><template v-if="goalOf(r).title !== goalOf(r).goal"> · {{ goalOf(r).goal }}</template><template v-if="goalOf(r).answer"> {{ $t('courseEditor.correct0', [goalOf(r).answer]) }}</template></div>
                <!-- Metrics -->
                <div v-if="['kpi', 'limit', 'budget'].includes(r.kind)" class="vp-row rl2">
                  <template v-if="r.kind !== 'budget'">
                    <el-select :model-value="metricBase(r)" size="small" style="width: 180px" filterable @change="(v: string) => setMetric(r, v, metricBlock(r))">
                      <el-option v-for="(n, k) in metricChoices(r)" :key="k" :value="k" :label="n" /></el-select>
                    <el-select v-if="blockMetric(r)" :model-value="metricBlock(r)" size="small" style="width: 150px" @change="(v: string) => setMetric(r, metricBase(r), v)">
                      <el-option v-for="b in plant?.blocks || []" :key="b.id" :value="b.id" :label="`${b.id} ${b.name}`" /></el-select>
                  </template>
                  <span v-else class="vp-small">{{ $t('courseEditor.totalInvestmentCny10000') }}</span>
                  <el-select v-model="r.op" size="small" style="width: 70px"><el-option v-for="(n, k) in meta.ops" :key="k" :value="k" :label="n" /></el-select>
                  <el-input-number v-model="r.value" size="small" controls-position="right" style="width: 120px" :step="0.1" />
                </div>
                <!-- MES -->
                <div v-else-if="r.kind === 'mes'" class="vp-row rl2">
                  <el-input v-model="r.query" size="small" style="width: 220px" :placeholder="$t('courseEditor.queryEGWorkOrders')" />
                  <el-select v-model="r.op" size="small" style="width: 70px"><el-option v-for="(n, k) in meta.ops" :key="k" :value="k" :label="n" /></el-select>
                  <el-input v-model="r.value" size="small" style="width: 120px" :placeholder="$t('courseEditor.targetValue')" @change="numify(r, 'value')" />
                  <el-input :model-value="r.where ? JSON.stringify(r.where) : ''" size="small" class="vp-grow" :placeholder="$t('courseEditor.whereFilterJsonEG')"
                            @change="(v: string) => setWhere(r, v)" />
                  <el-select v-model="r.answer_key" size="small" clearable style="width: 150px" :placeholder="$t('courseEditor.questionToCheck')">
                    <el-option v-for="q in (curL.rules || []).filter((x: any) => x.kind === 'answer')" :key="q.key" :value="q.key" :label="q.label || q.key" /></el-select>
                </div>
                <!-- Written-response questions -->
                <template v-else-if="r.kind === 'answer'">
                  <div v-if="r.pick" class="vp-row rl2">
                    <span class="vp-small">{{ $t('courseEditor.correctAnswerSelectOne') }}</span>
                    <el-select v-model="r.answer" multiple size="small" style="width: 280px" data-k="pick-answer"><el-option v-for="b in plant?.blocks || []" :key="b.id" :value="b.id" :label="`${b.id} ${b.name}`" /></el-select>
                  </div>
                  <div v-else-if="r.qtype === 'tf'" class="vp-row rl2"><span class="vp-small">{{ $t('common.correctAnswer') }}</span>
                    <el-radio-group v-model="r.answer" size="small"><el-radio-button :value="true">{{ $t('courseEditor.true') }}</el-radio-button><el-radio-button :value="false">{{ $t('courseEditor.false') }}</el-radio-button></el-radio-group></div>
                  <div v-else-if="r.qtype === 'number'" class="vp-row rl2"><span class="vp-small">{{ $t('courseEditor.answer') }}</span>
                    <el-input-number v-model="r.answer" size="small" controls-position="right" :step="0.1" style="width: 130px" data-k="num-answer" /><span class="vp-small">{{ $t('courseEditor.tolerance') }}</span>
                    <el-input-number v-model="r.tol" :min="0" size="small" controls-position="right" :step="0.1" style="width: 110px" /><el-input v-model="r.unit" size="small" style="width: 80px" :placeholder="$t('common.unit')" /></div>
                  <div v-else class="choices-ed">
                    <div v-for="(ch, j) in r.choices" :key="j" class="vp-row">
                      <el-checkbox v-if="r.qtype === 'multi'" :model-value="(r.answer || []).includes(j)" @change="(v: any) => toggleMulti(r, j, v)" />
                      <el-radio v-else :model-value="r.answer" :value="j" @change="r.answer = j" />
                      <el-input v-model="r.choices[j]" size="small" class="vp-grow" :placeholder="$t('courseEditor.option') + 'ABCDEFGH'[j]" :data-k="'choice-' + j" />
                      <el-button link :disabled="r.choices.length <= 2" @click="delChoice(r, j)"><el-icon><Delete /></el-icon></el-button>
                    </div>
                    <el-button size="small" text type="primary" @click="r.choices.push('')"><el-icon><Plus /></el-icon>{{ $t('courseEditor.addOption') }}</el-button>
                    <span class="vp-small vp-muted">{{ r.qtype === 'multi' ? $t('courseEditor.selectAllCorrectOptionsAll') : $t('courseEditor.clickTheCircleToMark') }}</span>
                  </div>
                  <!-- 4.6.2 Explanation: shown with correct answers after grading (visibility set when publishing to a class: after submission / after deadline / hidden) -->
                  <div class="vp-row rl2 rl-explain">
                    <span class="vp-small">{{ $t('courseEditor.explanation') }}</span>
                    <el-input v-model="r.explain" type="textarea" :autosize="{ minRows: 1, maxRows: 5 }" size="small" class="vp-grow" maxlength="1000"
                              :placeholder="$t('courseEditor.optionalExplainTheAnswerIn')" data-k="rule-explain" />
                  </div>
                </template>
              </div>
              <el-dropdown trigger="click" @command="addRule">
                <el-button size="small" type="primary" plain data-k="ce-add-rule"><el-icon><Plus /></el-icon>{{ curL.kind === 'quiz' ? $t('courseEditor.addQuestion') : $t('courseEditor.addItem') }}</el-button>
                <template #dropdown><el-dropdown-menu>
                  <el-dropdown-item v-for="o in ruleTypes" :key="o.v" :command="o.v" :data-rt="o.v">{{ o.l }}</el-dropdown-item>
                </el-dropdown-menu></template>
              </el-dropdown>
              <span class="vp-small vp-muted" style="margin-left: 10px" data-k="ce-total">{{ $t('courseEditor.total0PointsScaledTo', [totalWeight]) }}</span>
              <el-button v-if="totalWeight > 0 && totalWeight !== 100" size="small" text type="primary" data-k="ce-normalize" @click="normalize(curL)">{{ $t('courseEditor.scaleTo100') }}</el-button>
            </el-tab-pane>
          </el-tabs>
        </template>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t, variants } from '../../i18n';
// 4.6 Course editor: course info, chapters, lessons (templates: PLC lab / line task / quiz / equipment selection / MES operation), order, prerequisites, unlocks, and grading rules (all data-driven).
// Saves in course file format (vfactory/courses/__init__.py), validated by the server; preview = student walkthrough; publish = frozen, signed course package.
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { del, get, post, put, session } from '../../api';
import { KIND_ICON } from './courses';
import './panel.css';

const props = defineProps<{ id: string }>();
const emit = defineEmits<{ (e: 'back'): void; (e: 'preview', v: any): void; (e: 'published', v: any): void }>();
const meta = reactive<any>({ templates: [], scenes: [], plants: [], metrics: {}, block_metrics: {}, ops: {}, covers: [] });
const c = reactive<any>({ name: '', desc: '', level: 1, tags: [], cover: '', chapters: [] });
const st = reactive<any>({ version: 0, dirty: false });
const issues = ref<any[]>([]);
const errors = computed(() => issues.value.filter((i) => i.level === 'error').length);
const warns = computed(() => issues.value.filter((i) => i.level === 'warn').length);
const blockingPreview = computed(() => issues.value.filter((i) => i.level === 'error' && !i.check).length);   // Authoring check issues do not block preview (reference solutions must be saved in preview).
const issuesOpen = ref(false);
// 4.6.1 Authoring checks: trial run results, background progress, reference solutions, and student-facing instructions for each objective (server-generated).
const baseline = ref<Record<string, any>>({});
const pending = ref<string[]>([]);
const job = ref<any>({});
const refs = ref<Record<string, any>>({});
const goals = ref<Record<string, any>>({});
const SEV: Record<string, string> = { error: $t('common.error'), warn: $t('courseEditor.warning'), info: $t('opsApp.notes') };
const REF_CN: Record<string, string> = { teacher: $t('courseEditor.referenceSolution'), scene: $t('courseEditor.scenarioReferenceProgram'), lesson: $t('courseEditor.lessonReferenceSolution') };
const shared = ref(false);
const busy = ref('');
const saveMsg = ref('');
const sel = ref<{ t: 'course' | 'ch' | 'l'; ci?: number; li?: number }>({ t: 'course' });
const ltab = ref('base');
let kseq = 1;
const key = () => 'k' + kseq++;

const curCh = computed(() => (sel.value.t !== 'course' ? c.chapters[sel.value.ci!] : null));
const curL = computed<any>(() => (sel.value.t === 'l' ? c.chapters[sel.value.ci!]?.lessons[sel.value.li!] : null));
watch(() => sel.value.t === 'l' && curL.value?._k, () => { if (!['base', 'spec', 'plant', 'rules'].includes(ltab.value) || sel.value.t === 'l') ltab.value = 'base'; loadCustom(); });
const scene = computed(() => meta.scenes.find((s: any) => s.id === curL.value?.scene));
const plant = computed(() => meta.plants.find((p: any) => p.id === curL.value?.plant));
const ioIn = computed(() => (scene.value?.io || []).filter((e: any) => e.dir === 'in'));
const ioOut = computed(() => (scene.value?.io || []).filter((e: any) => e.dir === 'out'));
const rubric = computed(() => curL.value?.rubric ?? (scene.value?.rules || []).map((r: any) => r.key));
const blockOf = (id: string) => plant.value?.blocks.find((b: any) => b.id === id);
const tplName = (l: any) => ({ cell: $t('common.plcLab'), plant: $t('courseEditor.lineTask'), quiz: $t('common.quiz'), point: $t('courseEditor.selectEquipmentOnTheDiagram'), mes: $t('courseEditor.mesTask'), diagnose: $t('common.troubleshooting') } as any)[l.kind] || l.kind;
const coverUrl = computed(() => `/api/teach/courses/${encodeURIComponent(props.id)}/assets/${encodeURIComponent(String(c.cover).slice(7))}?token=${encodeURIComponent(session.token || '')}`);
const lessonBad = (l: any) => issues.value.some((i: any) => i.level === 'error' && (i.lesson ? i.lesson === l.id : variants('courseEditor.lesson0').some((t) => i.where === t.replace('{0}', l.title || l.id))));
const earlier = computed(() => {
  const out: any[] = [];
  for (const ch of c.chapters) for (const l of ch.lessons) { if (l === curL.value) return out; out.push(l); }
  return out;
});
const unlockMode = computed({
  get: () => (curL.value?.unlock?.free ? 'free' : curL.value?.unlock?.after ? 'after' : 'prev'),
  set: (v: string) => {
    const u = { ...(curL.value.unlock || {}) };
    delete u.free; delete u.after;
    if (v === 'free') u.free = true; else if (v === 'after') u.after = [];
    curL.value.unlock = Object.keys(u).length ? u : undefined;
  },
});
function setUnlockMin(v: number) { curL.value.unlock = { ...(curL.value.unlock || {}), min: v }; }
const totalWeight = computed(() => (curL.value?.rules || []).reduce((n: number, r: any) => n + (Number(r.weight) || 0), 0));
const allLessons = () => c.chapters.flatMap((ch: any, ci: number) => ch.lessons.map((l: any, li: number) => ({ l, ci, li })));
const kindOf = (lid: string) => allLessons().find((x: any) => x.l.id === lid)?.l.kind;
const goalOf = (r: any) => (curL.value && r?.key ? goals.value[curL.value.id]?.[r.key] : null);
const refRow = (lid: string, key: string) => (baseline.value[lid]?.ref?.details || []).find((d: any) => d.key === key);
// Group issues by "course / chapter / lesson" (lessons in outline order; include lessons with trial run results but no issues), with errors first in each group.
const issueGroups = computed(() => {
  const order: Record<string, number> = { error: 0, warn: 1, info: 2 };
  const sort = (xs: any[]) => xs.sort((a: any, b: any) => (order[a.level] ?? 3) - (order[b.level] ?? 3));
  const gs: any[] = [];
  for (const i of issues.value.filter((x) => !x.lesson)) {
    let g = gs.find((x) => x.key === 'w:' + i.where);
    if (!g) { g = { key: 'w:' + i.where, where: i.where, lesson: '', items: [] }; gs.push(g); }
    g.items.push(i);
  }
  const seen = new Set<string>();
  for (const { l } of allLessons()) {
    if (seen.has(l.id)) continue;
    seen.add(l.id);
    const items = issues.value.filter((x) => x.lesson === l.id);
    if (items.length || baseline.value[l.id] || refs.value[l.id]) gs.push({ key: 'l:' + l.id, where: items[0]?.where || $t('courseEditor.lesson0', [l.title || l.id]), lesson: l.id, items: sort(items) });
  }
  for (const i of issues.value.filter((x) => x.lesson && !seen.has(x.lesson))) {      // Recently deleted lessons (pending next save).
    let g = gs.find((x) => x.key === 'l:' + i.lesson);
    if (!g) { g = { key: 'l:' + i.lesson, where: i.where, lesson: i.lesson, items: [] }; gs.push(g); }
    g.items.push(i);
  }
  return gs;
});
/** Scale weights to total 100 (round, then apply the difference to the largest weight; matches server rules.normalize_weights). */
function normalize(l: any) {
  const rs = l?.rules || [];
  const ws = rs.map((r: any) => Math.max(0, Number(r.weight) || 0));
  const tot = ws.reduce((a: number, b: number) => a + b, 0);
  if (!rs.length || tot <= 0) return;
  const out = ws.map((w: number) => Math.floor((w * 100) / tot + 0.5));
  let big = 0;
  ws.forEach((w: number, i: number) => { if (w > ws[big]) big = i; });
  out[big] += 100 - out.reduce((a: number, b: number) => a + b, 0);
  rs.forEach((r: any, i: number) => { r.weight = out[i]; });
}
function gotoLesson(lid: string, tab = 'base') {
  const x = allLessons().find((y: any) => y.l.id === lid);
  if (!x) return;
  sel.value = { t: 'l', ci: x.ci, li: x.li };
  setTimeout(() => { ltab.value = tab; }, 0);
}
function gotoIssue(i: any) {
  const kind = kindOf(i.lesson);
  const tab = ['brief'].includes(i.code) ? 'base' : i.code === 'unconstrained' ? 'plant' : kind === 'cell' ? 'spec'
    : ['weights', 'label', 'answer', 'choices', 'tol', 'mes_query', 'pct', 'baseline', 'reference'].includes(i.code) || /\u8bc4\u5206\u9879|\u9898|\u76ee\u6807|criteri|question|goal|target/i.test(i.msg) ? 'rules' : 'base';
  gotoLesson(i.lesson, tab);
}
async function applyFix(i: any) {
  const x = allLessons().find((y: any) => y.l.id === i.lesson);
  if (!x) return;
  if (i.fix?.kind === 'weights') {
    for (const r of x.l.rules || []) if (i.fix.weights && r.key in i.fix.weights) r.weight = i.fix.weights[r.key];
  } else if (i.fix?.kind === 'label') {
    const r = (x.l.rules || []).find((y: any) => y.key === i.fix.rule);
    if (r) r.label = i.fix.value;
  }
  await save(true).catch(() => undefined);
}
let pollT: any = null;
let kicks = 0;
function takeChecks(v: any) {
  issues.value = v.issues || [];
  baseline.value = v.baseline || {};
  pending.value = v.pending || [];
  job.value = v.job || {};
  refs.value = v.refs || {};
  goals.value = v.goals || {};
  clearTimeout(pollT);
  if (job.value.running) pollT = setTimeout(pollChecks, 1200);
  else if (pending.value.length && kicks < 3) { kicks++; pollT = setTimeout(() => runChecks(false), 300); }
  else if (!pending.value.length) kicks = 0;
}
async function pollChecks() { try { takeChecks(await get(`/api/teach/authoring/${props.id}/checks`, true)); } catch { /* Recheck on next save */ } }
async function runChecks(force: boolean) {
  if (force) kicks = 0;
  try { takeChecks(await post(`/api/teach/authoring/${props.id}/checks`, { force })); } catch { /* Already notified */ }
}
async function delRef(lid: string) {
  await ElMessageBox.confirm($t('courseEditor.deleteTheReferenceSolutionFor'), $t('courseEditor.referenceSolution'), { type: 'warning' });
  takeChecks(await del(`/api/teach/authoring/${props.id}/reference/${encodeURIComponent(lid)}`));
}

// ---- Line: editable parameters (lock.editable = [[block, parameter]…])
const paramOptions = computed(() => (plant.value?.blocks || []).flatMap((b: any) => Object.keys(b.params || {}).map((k) => `${b.id}.${k}`)));
const editable = computed({
  get: () => ((curL.value?.lock?.editable || []) as any[]).map((e) => `${e[0]}.${e[1]}`),
  set: (v: string[]) => setLock('editable', v.length ? v.map((x) => { const i = x.indexOf('.'); return [x.slice(0, i), x.slice(i + 1)]; }) : undefined),
});
function setLock(k: string, v: any) {
  const l = { ...(curL.value.lock || {}) };
  if (v === undefined) delete l[k]; else l[k] = v;
  curL.value.lock = Object.keys(l).length ? l : undefined;
}
function setWhere(r: any, v: string) {
  if (!String(v || '').trim()) { delete r.where; return; }
  try { const x = JSON.parse(v); if (x && typeof x === 'object' && !Array.isArray(x)) r.where = x; else ElMessage.warning($t('courseEditor.whereMustBeAJson')); } catch { ElMessage.warning($t('courseEditor.whereIsNotValidJson')); }
}
function numify(o: any, k = 'value') { const v = o[k]; if (typeof v === 'string' && v.trim() !== '' && !isNaN(Number(v))) o[k] = Number(v); }

// ---- Criterion types
const ruleTypes = computed(() => {
  const k = curL.value?.kind;
  const q = [{ v: 'single', l: $t('courseEditor.singleChoice') }, { v: 'multi', l: $t('courseEditor.multipleChoice') }, { v: 'tf', l: $t('courseEditor.trueFalse') }, { v: 'number', l: $t('courseEditor.numericAnswer') }];
  if (k === 'quiz') return q;
  if (k === 'mes') return [{ v: 'mes', l: $t('courseEditor.mesChecks') }, ...q];
  if (k === 'point') return [{ v: 'pick', l: $t('courseEditor.selectEquipmentOnTheDiagram') }, ...q];
  return [{ v: 'kpi', l: $t('courseEditor.simulationMetric') }, { v: 'budget', l: $t('courseEditor.investmentBudget') }, { v: 'limit', l: $t('courseEditor.countLayout') }, { v: 'pick', l: $t('courseEditor.selectEquipmentOnTheDiagram') }, ...q];
});
const ruleType = (r: any) => (r.kind === 'answer' ? (r.pick ? 'pick' : r.qtype || 'single') : r.kind || 'kpi');
function freshRule(t: string): any {
  const k = 'r' + Math.random().toString(36).slice(2, 6);
  if (t === 'kpi') return { key: k, kind: 'kpi', metric: 'good', op: '>=', value: 100, weight: 20 };
  if (t === 'budget') return { key: k, kind: 'budget', op: '<=', value: 100, weight: 20 };
  if (t === 'limit') return { key: k, kind: 'limit', metric: 'count_all', op: '<=', value: 10, weight: 10 };
  if (t === 'mes') return { key: k, kind: 'mes', query: '', op: '>=', value: 1, weight: 20, label: '' };
  if (t === 'pick') return { key: k, kind: 'answer', pick: true, label: '', answer: [], weight: 20 };
  if (t === 'tf') return { key: k, kind: 'answer', qtype: 'tf', label: '', answer: true, weight: 10 };
  if (t === 'number') return { key: k, kind: 'answer', qtype: 'number', label: '', answer: 0, tol: 0, weight: 10 };
  if (t === 'multi') return { key: k, kind: 'answer', qtype: 'multi', label: '', choices: ['', '', ''], answer: [], weight: 10 };
  return { key: k, kind: 'answer', qtype: 'single', label: '', choices: ['', '', ''], answer: 0, weight: 10 };
}
function setRuleType(r: any, t: string) { const n = freshRule(t); for (const x of Object.keys(r)) if (!['key', 'label', 'weight'].includes(x)) delete r[x]; Object.assign(r, { ...n, key: r.key, label: r.label, weight: r.weight }); }
function addRule(t: string) { curL.value.rules.push(freshRule(t)); }
function toggleMulti(r: any, j: number, on: boolean) { const s = new Set<number>(r.answer || []); if (on) s.add(j); else s.delete(j); r.answer = [...s].sort(); }
function delChoice(r: any, j: number) {
  r.choices.splice(j, 1);
  if (r.qtype === 'multi') r.answer = (r.answer || []).filter((x: number) => x !== j).map((x: number) => (x > j ? x - 1 : x));
  else if (r.answer === j) r.answer = 0; else if (r.answer > j) r.answer--;
}
const BLOCK_M = computed(() => meta.block_metrics || {});
function metricChoices(r: any) {
  if (r.kind === 'limit') return { count_all: $t('courseEditor.totalEquipmentCount'), buffer_total: $t('courseEditor.totalBufferCapacity'), operators: $t('courseEditor.operatorCount'), vehicles: $t('courseEditor.transportVehicleCount'), overlap: $t('courseEditor.overlappingEquipmentPairs'), outside: $t('courseEditor.equipmentOutsideTheBuilding') };
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(meta.metrics || {})) if (!['cost', 'count_all', 'buffer_total', 'operators', 'vehicles', 'overlap', 'outside'].includes(k)) out[k] = String(v);
  for (const [k, v] of Object.entries(BLOCK_M.value)) out[k + '.'] = $t('courseEditor.n0SpecificEquipment', [v]);
  return out;
}
const metricBase = (r: any) => { const m = String(r.metric || ''); const i = m.indexOf('.'); return i > 0 && BLOCK_M.value[m.slice(0, i)] ? m.slice(0, i + 1) : m; };
const metricBlock = (r: any) => { const m = String(r.metric || ''); const i = m.indexOf('.'); return i > 0 && BLOCK_M.value[m.slice(0, i)] ? m.slice(i + 1) : ''; };
const blockMetric = (r: any) => metricBase(r).endsWith('.');
function setMetric(r: any, base: string, blk: string) { r.metric = base.endsWith('.') ? base + (blk || plant.value?.blocks.find((b: any) => b.type === 'processor')?.id || '') : base; }

// ---- PLC: custom checks (press button → output = value within a few seconds) → tests + extra_rules (declarative test steps)
const custom = ref<any[]>([]);
function loadCustom() {
  const l = curL.value;
  custom.value = [];
  if (!l || l.kind !== 'cell') return;
  const steps = l.tests || [];
  for (const r of l.extra_rules || []) {
    const ck = steps.find((s: any) => s.key === r.key && s.check);
    const pr = steps.find((s: any) => s._for === r.key && s.press);
    if (ck) custom.value.push({ t: pr?.t ?? ck.t, press: pr?.press || '', within: ck.within ?? 0, out: ck.check.out, eq: ck.check.eq ? 1 : 0, weight: r.weight, key: r.key });
  }
}
function syncCustom() {
  const l = curL.value;
  const off = Number(scene.value?.duration || 120) + 2;   // Append custom checks after scenario tests, scheduling them from the scenario end time.
  const tests: any[] = [], rules: any[] = [];
  custom.value.forEach((x, i) => {
    const k = x.key || `chk${i + 1}`;
    x.key = k;
    const t0 = off + i * 10 + Number(x.t || 0);
    if (x.press) tests.push({ t: t0, press: x.press, _for: k });
    tests.push({ t: t0 + 0.05, key: k, check: { out: x.out, eq: !!x.eq }, within: Number(x.within) || 0.5 });
    rules.push({ key: k, label: $t('courseEditor.n23Within1S', [x.press, x.within, x.out, x.eq]), op: '>=', value: 1, weight: Number(x.weight) || 0 });
  });
  l.tests = tests.length ? tests : undefined;
  l.extra_rules = rules.length ? rules : undefined;
}
watch(custom, () => { if (curL.value?.kind === 'cell') syncCustom(); }, { deep: true });
function onScene() { curL.value.rubric = undefined; custom.value = []; syncCustom(); }

// ---- Outline
function blankLesson(t: string): any {
  const tpl = meta.templates.find((x: any) => x.id === t);
  const kind = tpl?.kind || t;
  const n = c.chapters.reduce((a: number, ch: any) => a + ch.lessons.length, 0) + 1;
  const l: any = { _k: key(), id: `l${n}${Math.random().toString(36).slice(2, 4)}`, title: `${tpl?.name || $t('courseEditor.newLesson')} ${n}`, kind, brief_md: '', hints: [], rules: [] };
  if (kind === 'cell') l.scene = meta.scenes[0]?.id;
  if (kind === 'plant') Object.assign(l, { plant: meta.plants.find((p: any) => p.id === 'mc02_serial')?.id || meta.plants[0]?.id, time_h: 8, seed: 7, params: [], rules: [{ ...freshRule('kpi'), weight: 100 }] });
  if (kind === 'point') Object.assign(l, { plant: meta.plants.find((p: any) => p.id === 'mc03_bottleneck')?.id || meta.plants[0]?.id, params: [], rules: [{ ...freshRule('pick'), weight: 100 }], lock: { structure: true } });
  if (kind === 'quiz') l.rules = [freshRule('single')];
  if (kind === 'mes') l.rules = [{ ...freshRule('mes'), weight: 100 }];
  return l;
}
function addChapter() { c.chapters.push({ _k: key(), id: 'c' + (c.chapters.length + 1) + Math.random().toString(36).slice(2, 4), title: $t('courseEditor.chapter0', [c.chapters.length + 1]), lessons: [] }); sel.value = { t: 'ch', ci: c.chapters.length - 1 }; }
function addLesson(ci: number, t: string) { c.chapters[ci].lessons.push(blankLesson(t)); sel.value = { t: 'l', ci, li: c.chapters[ci].lessons.length - 1 }; ltab.value = 'base'; }
function moveCh(ci: number, d: number) { const a = c.chapters; [a[ci], a[ci + d]] = [a[ci + d], a[ci]]; sel.value = { t: 'ch', ci: ci + d }; }
function moveL(ci: number, li: number, d: number) {
  const ls = c.chapters[ci].lessons;
  if (li + d < 0) { if (ci > 0) { const [l] = ls.splice(li, 1); c.chapters[ci - 1].lessons.push(l); sel.value = { t: 'l', ci: ci - 1, li: c.chapters[ci - 1].lessons.length - 1 }; } return; }
  if (li + d >= ls.length) { if (ci < c.chapters.length - 1) { const [l] = ls.splice(li, 1); c.chapters[ci + 1].lessons.unshift(l); sel.value = { t: 'l', ci: ci + 1, li: 0 }; } return; }
  [ls[li], ls[li + d]] = [ls[li + d], ls[li]]; sel.value = { t: 'l', ci, li: li + d };
}
async function delChapter(ci: number) { await ElMessageBox.confirm($t('courseEditor.deleteThisChapterAndAll'), $t('common.delete'), { type: 'warning' }); c.chapters.splice(ci, 1); sel.value = { t: 'course' }; }
async function delLesson(ci: number, li: number) { await ElMessageBox.confirm($t('courseEditor.deleteThisLesson2'), $t('common.delete'), { type: 'warning' }); c.chapters[ci].lessons.splice(li, 1); sel.value = { t: 'ch', ci }; }

// ---- Load, save, preview, publish
function plain() {
  const strip = (o: any): any => (Array.isArray(o) ? o.map(strip) : o && typeof o === 'object'
    ? Object.fromEntries(Object.entries(o).filter(([k, v]) => k !== '_k' && v !== undefined).map(([k, v]) => [k, strip(v)])) : o);
  return strip({ ...c });
}
function take(v: any) {
  const x = v.course || {};
  Object.assign(c, { name: x.name || '', desc: x.desc || '', level: x.level || 1, tags: x.tags || [], cover: x.cover || '' });
  c.chapters = (x.chapters || []).map((ch: any) => ({ ...ch, _k: key(), lessons: (ch.lessons || []).map((l: any) => ({ hints: [], rules: [], brief_md: '', ...l, _k: key() })) }));
  for (const k of Object.keys(x)) if (!(k in c) && !['id', 'owner', 'version', 'origin'].includes(k)) c[k] = x[k];
  Object.assign(st, { version: v.version, dirty: v.dirty, published_at: v.published_at, classes: v.classes });
  shared.value = !!v.shared;
  takeChecks(v);
  if (issues.value.some((i) => i.level !== 'info')) issuesOpen.value = true;
}
async function save(quiet = false) {
  busy.value = quiet ? busy.value : 'save';
  try {
    const body = plain();
    const v = await put(`/api/teach/authoring/${props.id}`, { course: body, shared: shared.value });
    lastSaved = JSON.stringify(body);
    takeChecks(v); Object.assign(st, { version: v.version, dirty: v.dirty });
    saveMsg.value = $t('signals.saved') + new Date().toTimeString().slice(0, 5);
    if (!quiet) { if (errors.value) { issuesOpen.value = true; ElMessage.warning($t('courseEditor.saved0IssuesMustBe', [errors.value])); } else ElMessage.success($t('common.saved')); }
    return v;
  } finally { if (!quiet) busy.value = ''; }
}
async function preview() {
  busy.value = 'preview';
  try { await save(true); const r = await post(`/api/teach/authoring/${props.id}/preview`, {}); emit('preview', r); } finally { busy.value = ''; }
}
async function publish() {
  busy.value = 'publish';
  try {
    await save(true);
    if (job.value.running || pending.value.length) {         // Trial run still in progress: wait for completion before checking errors (a reference solution failing to pass is an error).
      takeChecks(await post(`/api/teach/authoring/${props.id}/checks`, { wait: true }));
    }
    if (errors.value) { issuesOpen.value = true; ElMessage.warning($t('courseEditor.n0ErrorsMustBeFixed', [errors.value])); return; }
    await ElMessageBox.confirm(st.version ? $t('courseEditor.publishNewVersionV0', [st.version + 1]) : $t('courseEditor.publishThisCourseOncePublished'),
      $t('common.publishCourse'), { type: 'info', confirmButtonText: $t('courseEditor.publish') });
    const r = await post(`/api/teach/authoring/${props.id}/publish`, {}).catch(async (e: any) => { await pollChecks(); issuesOpen.value = true; throw e; });
    Object.assign(st, { version: r.version, dirty: false });
    takeChecks(r);
    if (r.uploaded) ElMessage.success({ message: $t('courseEditor.publishedV0TheSigned', [r.uploaded.version]), duration: 6000 });
    else ElMessage.success($t('courseEditor.publishedV0CoursePackage', [r.version, Math.round(r.package.bytes / 1024)]));
    emit('published', r);
  } finally { busy.value = ''; }
}
async function upload(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = '';
  if (!f) return;
  const data = await new Promise<string>((res) => { const r = new FileReader(); r.onload = () => res(String(r.result)); r.readAsDataURL(f); });
  const r = await post(`/api/teach/authoring/${props.id}/assets`, { name: f.name, data });
  c.cover = r.cover;
}
let tSave: any = null;
let lastSaved = '';
watch(c, () => {
  const now = JSON.stringify(plain());
  if (!lastSaved || now === lastSaved) return;            // Just loaded / no actual changes: skip autosave (otherwise "Published" becomes "Unpublished changes").
  saveMsg.value = $t('courseEditor.unsavedChanges'); clearTimeout(tSave);
  tSave = setTimeout(() => { if (!busy.value) save(true).catch(() => undefined); }, 4000);
}, { deep: true });
onMounted(async () => {
  const [m, v] = await Promise.all([get('/api/teach/authoring/meta'), get(`/api/teach/authoring/${props.id}`)]);
  Object.assign(meta, m);
  take(v);
  setTimeout(() => { saveMsg.value = ''; lastSaved = JSON.stringify(plain()); }, 0);
});
onBeforeUnmount(() => { clearTimeout(pollT); clearTimeout(tSave); });
defineExpose({ save, c });
</script>

<style scoped>
.ce { color: var(--el-text-color-primary); display: flex; flex-direction: column; height: 100%; min-height: 560px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-lighter); border-radius: 12px; overflow: hidden; }
.ce-top { display: flex; align-items: center; gap: 10px; padding: 10px 14px; border-bottom: 1px solid var(--el-border-color-lighter); flex-wrap: wrap; }
.ce-name { font-size: 15px; }
.grow { flex: 1; }
.ce-checks { padding: 8px 16px 10px; border-bottom: 1px solid var(--el-border-color-lighter); background: var(--el-fill-color-lighter); max-height: 40vh; overflow: auto; font-size: 13px; }
.ck-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; position: sticky; top: -8px; background: var(--el-fill-color-lighter); padding: 4px 0; z-index: 1; }
.ck-count { display: inline-flex; gap: 8px; font-size: 12px; } .ck-e { color: var(--el-color-danger); } .ck-w { color: var(--ck-warn); }
.ck-run { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; color: var(--el-color-primary); } .ck-prog { width: 120px; }
.ck-note { margin: 2px 0 6px; }
.ck-group { margin-top: 8px; padding: 6px 10px 8px; border-radius: 8px; background: var(--el-bg-color); border: 1px solid var(--el-border-color-lighter); }
.ck-where { font-weight: 600; font-size: 12.5px; margin-bottom: 4px; } .ck-where.link { cursor: pointer; } .ck-where.link:hover { color: var(--el-color-primary); }
.ck-item { display: flex; align-items: flex-start; gap: 8px; padding: 3px 0; line-height: 1.6; }
.ck-sev { flex: none; font-size: 11.5px; padding: 0 7px; border-radius: 5px; line-height: 20px; margin-top: 1px; font-weight: 600; }
.ck-item.lv-error .ck-sev { background: var(--ck-err-bg); color: var(--el-color-danger); }
.ck-item.lv-warn .ck-sev { background: var(--ck-warn-bg); color: var(--ck-warn); }
.ck-item.lv-info .ck-sev { background: var(--el-fill-color); color: var(--el-text-color-secondary); }
.ck-item.lv-info .ck-msg { color: var(--el-text-color-secondary); }
.ck-msg { flex: 1; min-width: 0; } .ck-acts { flex: none; display: inline-flex; gap: 2px; }
.ck-base table { border-collapse: collapse; margin: 6px 0 2px; font-size: 12px; }
.ck-base th, .ck-base td { border: 1px solid var(--el-border-color-lighter); padding: 3px 9px; text-align: left; }
.ck-base th { background: var(--el-fill-color-light); font-weight: 600; color: var(--el-text-color-regular); }
.ck-base td.ok { color: var(--el-color-success); } .ck-base td.no { color: var(--el-color-danger); }
.ck-base tr.tot td { font-weight: 600; }
.ck-ref { margin-top: 4px; color: var(--el-text-color-regular); }
.rl-goal { margin-top: 6px; padding-left: 4px; }
.ce { --ck-warn: var(--hm-idle-ink); --ck-warn-bg: var(--hm-idle-soft); --ck-err-bg: var(--hm-fault-soft); }
.ce-main { flex: 1; min-height: 0; display: flex; }
.ce-tree { width: 290px; flex: none; border-right: 1px solid var(--el-border-color-lighter); overflow: auto; padding: 10px 8px; background: var(--el-fill-color-lighter); }
.tn { display: flex; align-items: center; gap: 7px; padding: 6px 8px; border-radius: 7px; cursor: pointer; font-size: 13px; }
.tn:hover { background: var(--el-fill-color); }
.tn.on { background: var(--el-color-primary-light-9); color: var(--el-color-primary); }
.tn.bad .tt { color: var(--el-color-danger); }
.tn .tt { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tn .ops { display: none; } .tn:hover .ops, .tn.on .ops { display: inline-flex; }
.tn.meta { font-weight: 600; margin-bottom: 6px; }
.tn.ch { font-weight: 600; margin-top: 6px; }
.tn.ch .num { width: 20px; height: 20px; border-radius: 50%; background: var(--hm-primary-soft); color: var(--hm-setup-ink); display: grid; place-items: center; font-size: 11px; }
.tn.ls { padding-left: 26px; }
.add-l { margin-left: 22px; }
.add-ch { margin: 10px 8px; }
.ce-form { flex: 1; min-width: 0; overflow: auto; padding: 14px 22px 30px; }
.ce-form h3 { margin: 0 0 12px; font-size: 16px; }
.lh { display: flex; align-items: center; gap: 10px; } .lh h3 { margin: 0; }
.ltabs { margin-top: 6px; }
.covers { display: flex; flex-wrap: wrap; gap: 8px; }
.cv { width: 128px; aspect-ratio: 16 / 9; border-radius: 8px; overflow: hidden; border: 2px solid transparent; cursor: pointer; background: var(--hm-surface-2); }
.cv img { width: 100%; height: 100%; object-fit: cover; }
.cv.on { border-color: var(--el-color-primary); }
.cv.up { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 2px; border: 2px dashed var(--el-border-color); color: var(--el-text-color-secondary); font-size: 12px; background: transparent; }
.cv.up input { display: none; }
.hints, .ptab, .xt, .rubric { width: 100%; display: flex; flex-direction: column; gap: 6px; }
.rb { display: flex; justify-content: space-between; align-items: center; min-width: 320px; max-width: 560px; }
.xt-row { display: flex; align-items: center; gap: 5px; flex-wrap: wrap; font-size: 12.5px; }
.rl { margin-bottom: 10px; padding: 10px 12px; }
.rl2 { margin-top: 8px; padding-left: 4px; }
.rl-explain { align-items: flex-start; }
.rl-explain > .vp-small { padding-top: 4px; flex: none; }
.choices-ed { margin-top: 8px; display: flex; flex-direction: column; gap: 5px; }
.mes-note { margin-bottom: 10px; background: var(--el-fill-color-lighter); line-height: 1.7; }
.kchip { font-size: 11.5px; padding: 2px 8px; border-radius: 6px; background: var(--el-fill-color); color: var(--el-text-color-secondary); display: inline-flex; align-items: center; gap: 4px; }
.kchip.cell { background: var(--hm-setup-soft); color: var(--hm-setup-ink); } .kchip.plant, .kchip.point { background: var(--hm-amber-soft); color: var(--hm-amber-ink); } .kchip.quiz, .kchip.factory { background: var(--hm-run-soft); color: var(--hm-run-ink); } .kchip.diagnose { background: var(--hm-fault-soft); color: var(--hm-fault-ink); } .kchip.mes { background: var(--hm-cyan-soft); color: var(--hm-cyan-ink); }
</style>
