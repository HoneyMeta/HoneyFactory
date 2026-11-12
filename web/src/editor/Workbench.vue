<template>
  <div class="ed" :class="'ws-' + ed.workspace" v-if="ed.model">
    <!-- Row 1: brand, factory, workspace, save -->
    <header class="ed-menu">
      <div class="ed-brand click" :title="isTeachRole() ? $t('common.teaching') : $t('common.allFactories')" @click="router.push(isTeachRole() ? '/teach' : '/')"><img src="/logo.png" alt="" /><b>{{ $t('common.honeyfactory') }}</b></div>
      <!-- Lab sandbox: show "owner's sandbox · lesson name", not internal IDs -->
      <span v-if="pid.startsWith('sb-')" class="ed-sbname" :title="pid">{{ watchOnly ? (ed.teach?.student || $t('common.student')) + $t('workbench.labSandbox') : $t('workbench.myLabSandbox') }} · {{ ed.model.plant?.name }}</span>
      <el-select v-else :model-value="pid" size="small" class="ed-plant" @change="(v: string) => router.push(`/p/${v}/workbench`)">
        <el-option v-for="p in session.plants" :key="p.id" :label="p.name" :value="p.id" />
      </el-select>
      <div class="ed-ws" data-tour="wb-ws">
        <el-tooltip v-for="(w, k) in wsList" :key="k" :content="w.desc" placement="bottom">
          <button :class="{ on: ed.workspace === k }" @click="setWorkspace(k as string)"><el-icon><component :is="w.icon" /></el-icon>{{ w.label }}</button>
        </el-tooltip>
      </div>
      <span class="grow" />
      <el-tooltip v-if="desk.on && (desk.mode === 'standalone' || isLocalPlant(pid))" :content="$t('workbench.thisFactoryRunsOnThis')"><span class="ed-chip local" @click="router.push('/settings')">{{ $t('common.local') }}</span></el-tooltip>
      <el-tooltip v-else-if="desk.on" :content="$t('workbench.thisFactoryRunsOnServer', [desk.server])"><span class="ed-chip server" @click="router.push('/settings')">{{ $t('common.server') }}</span></el-tooltip>
      <span v-if="watchOnly" class="ed-chip warn" :title="$t('workbench.teacherViewOfAStudent')">{{ $t('workbench.viewing0ReadOnly', [ed.teach?.student || '']) }}</span>
      <span v-else-if="pid.startsWith('sb-')" class="ed-chip" :title="$t('workbench.labSandboxVisibleOnlyTo')">{{ $t('common.labSandbox') }}</span>
      <span v-if="ed.live.length" class="ed-chip warn" :title="$t('workbench.parameterAndPositionChangesMade')" @click="openModel('changes')">{{ $t('workbench.runtimeChanges0Unsaved', [ed.live.length]) }}</span>
      <el-tooltip v-if="ed.structural" :content="$t('workbench.equipmentOrConnectionsHaveChanged')">
        <el-button size="small" type="warning" :disabled="!canEdit() || busyCtl" data-tour="wb-apply" @click="play()"><el-icon><VideoPlay /></el-icon>{{ $t('workbench.applyChangesAndRun') }}</el-button></el-tooltip>
      <span class="ed-draft small">{{ ed.saving ? $t('workbench.savingDraft') : ed.changes.length ? $t('workbench.draft0', [ed.savedAt]) : $t('workbench.matchesSavedVersion') }}</span>
      <el-button size="small" :type="vErr ? 'danger' : ''" plain @click="openModel('check')">
        <el-icon><component :is="vErr ? 'CircleClose' : vWarn ? 'Warning' : 'CircleCheck'" /></el-icon>{{ vErr ? $t('workbench.errors0', [vErr]) : vWarn ? $t('workbench.n0Warnings', [vWarn]) : $t('workbench.validationPassed') }}</el-button>
      <el-button size="small" @click="openVersions"><el-icon><Clock /></el-icon> {{ $t('common.version') }}</el-button>
      <el-button size="small" type="primary" :disabled="!ed.changes.length || !!vErr || !canEdit()" @click="applyOpen = true"><el-icon><Upload /></el-icon> {{ $t('common.save') }}</el-button>
      <GuideButton area="workbench" size="sm" />
      <LangSwitch compact class="ed-lang" />
      <el-tooltip :content="$t('workbench.commandPaletteCtrlK')"><el-button size="small" text @click="openPalette"><el-icon><Search /></el-icon></el-button></el-tooltip>
    </header>

    <!-- Row 2: run controls + views -->
    <header class="ed-bar">
      <span class="ed-mode" :class="mode">{{ MODE_CN[mode] }}</span>
      <el-button-group size="small" class="rb" data-tour="wb-run-ctl">
        <el-tooltip :content="$t('workbench.resetRebuildTheFactoryFrom')"><el-button :disabled="!canEdit() || busyCtl" @click="reset"><el-icon><RefreshLeft /></el-icon>{{ $t('workbench.reset2') }}</el-button></el-tooltip>
        <el-tooltip :content="running ? $t('workbench.pauseSpaceF6') : $t('workbench.runSpaceF5')">
          <el-button :type="running ? '' : 'success'" :disabled="!canEdit() || busyCtl" data-tour="wb-play" @click="running ? pause() : play()"><el-icon><component :is="running ? 'VideoPause' : 'VideoPlay'" /></el-icon>&nbsp;{{ running ? $t('common.pause') : $t('common.run') }}</el-button></el-tooltip>
        <el-dropdown size="small" :disabled="!canEdit() || busyCtl" @command="step"><el-button :disabled="!canEdit() || busyCtl" :title="$t('workbench.stepF10NextEvent')"><el-icon><DArrowRight /></el-icon>{{ $t('workbench.step') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
          <template #dropdown><el-dropdown-menu><el-dropdown-item command="event">{{ $t('workbench.toNextEvent') }}</el-dropdown-item><el-dropdown-item command="60">{{ $t('workbench.advance1Min') }}</el-dropdown-item>
            <el-dropdown-item command="600">{{ $t('workbench.advance10Min') }}</el-dropdown-item><el-dropdown-item command="3600">{{ $t('workbench.advance1Hour') }}</el-dropdown-item></el-dropdown-menu></template></el-dropdown>
        <el-popover placement="bottom-start" :width="300" trigger="click">
          <template #reference><el-button :disabled="!canEdit() || busyCtl" :title="$t('workbench.runTo')"><el-icon><Promotion /></el-icon>{{ $t('workbench.runTo3') }}</el-button></template>
          <div class="rt-pop">
            <div class="row"><span>{{ $t('common.run') }}</span><el-input-number v-model="rt.hours" size="small" :min="0.1" :max="72" :step="1" :controls="false" style="width:70px" /><span>{{ $t('common.hours') }}</span>
              <el-button size="small" type="primary" @click="runTo({ hours: rt.hours })">{{ $t('common.start') }}</el-button></div>
            <div class="row"><span>{{ $t('workbench.to') }}</span><el-input v-model="rt.at" size="small" placeholder="YYYY-MM-DD HH:MM" style="width:150px" />
              <el-button size="small" type="primary" @click="runTo({ cond: { kind: 'time', at: rt.at } })">{{ $t('common.start') }}</el-button></div>
            <div class="row"><span>{{ $t('workbench.until') }}</span><el-select v-model="rt.id" size="small" filterable :placeholder="$t('common.equipment')" style="width:120px"><el-option v-for="b in ed.model.blocks" :key="b.id" :value="b.id" :label="b.id" /></el-select>
              <el-select v-model="rt.state" size="small" style="width:76px"><el-option v-for="(v, k) in STATE_CN" :key="k" :value="k" :label="v" /></el-select>
              <el-button size="small" type="primary" :disabled="!rt.id" @click="runTo({ cond: { kind: 'state', id: rt.id, state: rt.state }, hours: 24 })">{{ $t('common.start') }}</el-button></div>
            <p class="muted small">{{ $t('workbench.moreConditionsBufferCountsMetrics') }}</p>
          </div>
        </el-popover>
      </el-button-group>
      <el-select v-model="speed" size="small" class="ed-speed" data-tour="wb-speed" :disabled="!canEdit()" @change="setSpeed">
        <el-option v-for="v in SPEEDS" :key="v" :value="v" :label="v === 3600 ? $t('workbench.max3600') : v + '×'" />
      </el-select>
      <el-tooltip v-if="running && actual && actual < speed * 0.8" :content="$t('workbench.largeModelsOrSlowerComputers')">
        <span class="ed-actual">{{ $t('workbench.actual0', [actual >= 10 ? Math.round(actual) : actual.toFixed(1)]) }}</span></el-tooltip>
      <div class="ed-clock" :title="$t('workbench.simulationTimeNotTheCurrent')"><b class="mono"><small class="ed-simlbl">{{ ed.replay ? $t('common.replay') : $t('workbench.simulation') }}</small>{{ ed.replay?.time || ed.runtime?.time || '--' }}</b>
        <span v-if="ed.runtime" class="small muted">{{ ed.runtime.off || ed.runtime.shift }} · {{ ed.runtime.product }}{{ ed.runtime.order ? ' · ' + ed.runtime.order : '' }}</span></div>
      <div v-if="busy" class="ed-busy"><el-progress :percentage="Math.round(busy.progress * 100)" :stroke-width="6" style="width:110px" /><span class="small">{{ $t('workbench.runTo0', [busy.goal]) }}</span>
        <el-button size="small" text @click="ctl('cancel')">{{ $t('common.cancel') }}</el-button></div>
      <span class="grow" />
      <el-radio-group v-model="ed.view" size="small" class="ed-views" data-tour="wb-views">
        <el-radio-button value="3d" data-tour="wb-view-3d"><el-icon><Box /></el-icon> {{ $t('workbench.n3d') }}</el-radio-button>
        <el-radio-button value="plan" data-tour="wb-view-plan"><el-icon><Grid /></el-icon> {{ $t('workbench.floorPlan') }}</el-radio-button>
        <el-radio-button value="graph" data-tour="wb-view-graph"><el-icon><Share /></el-icon> {{ $t('workbench.flow') }}</el-radio-button>
        <el-radio-button value="arch" data-tour="wb-view-arch"><el-icon><Connection /></el-icon> {{ $t('archView.architecture') }}</el-radio-button>
      </el-radio-group>
      <FilterBar />
      <template v-if="!density.on">
        <el-tooltip :content="$t('workbench.findEquipmentPlcChannelsAnd')"><el-button size="small" @click="ed.searchOpen = true"><el-icon><Search /></el-icon></el-button></el-tooltip>
        <el-tooltip :content="$t('workbench.sideBySide3dOn')"><el-button size="small" class="split-btn" :type="ed.split ? 'primary' : ''" @click="ed.split = !ed.split"><el-icon><Operation /></el-icon></el-button></el-tooltip>
      </template>
      <el-button-group size="small">
        <el-tooltip :content="ed.undo.length ? $t('workbench.undo0CtrlZ', [ed.undo[ed.undo.length - 1].label]) : $t('workbench.nothingToUndo')"><el-button :disabled="!ed.undo.length" @click="undo"><el-icon><RefreshLeft /></el-icon></el-button></el-tooltip>
        <el-tooltip :content="$t('workbench.redoCtrlY')"><el-button :disabled="!ed.redo.length" @click="redo"><el-icon><RefreshRight /></el-icon></el-button></el-tooltip>
      </el-button-group>
      <DeliveryExport ref="deliveryRef" :pid="pid" size="small" :button="!density.on" />
      <template v-if="!density.on">
        <el-tooltip :content="$t('workbench.exploreFromNowCopyThe')">
          <el-button size="small" :disabled="!canEdit()" @click="forkOpen = true"><el-icon><Connection /></el-icon>{{ $t('workbench.explore') }}</el-button></el-tooltip>
        <el-tooltip :content="$t('workbench.overlayLiveStatusOnCards')"><el-switch v-model="ed.overlay" size="small" :active-text="$t('common.status')" /></el-tooltip>
      </template>
      <!-- 4.7 compact layout: move row 2 overflow into "More" -->
      <el-dropdown v-else trigger="click" size="small" popper-class="bar-more-pop" @command="onMore">
        <el-button size="small" data-k="bar-more" :title="$t('workbench.more')"><el-icon><MoreFilled /></el-icon></el-button>
        <template #dropdown><el-dropdown-menu>
          <el-dropdown-item command="search"><el-icon><Search /></el-icon>{{ $t('workbench.findEquipmentAislesAndSignals') }}</el-dropdown-item>
          <el-dropdown-item command="split"><el-icon><Operation /></el-icon>{{ $t('workbench.n3dAndGraphSideBy2', [ed.split ? ' ✓' : '']) }}</el-dropdown-item>
          <el-dropdown-item command="fork" :disabled="!canEdit()"><el-icon><Connection /></el-icon>{{ $t('workbench.exploreFromNow') }}</el-dropdown-item>
          <el-dropdown-item command="overlay"><el-icon><View /></el-icon>{{ $t('workbench.overlayLiveStatus0', [ed.overlay ? ' ✓' : '']) }}</el-dropdown-item>
          <el-dropdown-item command="delivery"><el-icon><Files /></el-icon>{{ $t('workbench.deliveryPackageTagListFloor') }}</el-dropdown-item>
          <el-dropdown-item command="timeline" divided><el-icon><Clock /></el-icon>{{ ed.tlOpen ? $t('workbench.hideTimeline') : $t('workbench.showTimeline') }}</el-dropdown-item>
        </el-dropdown-menu></template>
      </el-dropdown>
      <el-tooltip :content="ed.rightOpen ? $t('workbench.collapseTheRightPanelProperties') : $t('workbench.expandTheRightPanelProperties')">
        <el-button size="small" data-k="right-toggle" :type="ed.rightOpen ? '' : 'primary'" plain @click="setRightOpen(!ed.rightOpen)"><el-icon><component :is="ed.rightOpen ? 'DArrowRight' : 'DArrowLeft'" /></el-icon></el-button></el-tooltip>
    </header>

    <div class="ed-body">
      <!-- Activity bar: click to open a sidebar or floating window -->
      <nav class="ed-act" data-tour="wb-act">
        <template v-for="(p, i) in actPanels" :key="p.id">
        <span v-if="i === ownCount && ownCount" class="ed-act-sep" :title="$t('workbench.featuresInThe0Workspace', [WORKSPACES[ed.workspace]?.label])" />
        <el-tooltip :content="p.title" placement="right" :show-after="250" :hide-after="0">
          <button :class="{ on: isOn(p), float: p.place === 'float' }" :data-panel="p.id" @click="activate(p)"><el-icon><component :is="p.icon" /></el-icon></button>
        </el-tooltip>
        </template>
        <span class="grow" />
        <el-tooltip :content="$t('common.aiAssistant')" placement="right"><button @click="toggleAI"><el-icon><MagicStick /></el-icon></button></el-tooltip>
        <el-tooltip :content="$t('common.help')" placement="right"><button @click="router.push('/help')"><el-icon><QuestionFilled /></el-icon></button></el-tooltip>
        <el-tooltip v-if="desk.on" :content="$t('common.settings')" placement="right"><button @click="router.push('/settings')"><el-icon><Setting /></el-icon></button></el-tooltip>
      </nav>
      <Splitpanes class="ed-main" @resized="saveSizes('main', $event)">
        <Pane v-if="leftP" :size="sizes.main[0]" :min-size="12" class="ed-left">
          <div class="sp-h"><b>{{ leftP.title }}</b><span class="grow" />
            <button v-if="leftP.popout" class="fw-b" :title="$t('workbench.openInLargerWindow')" @click="openPanel(leftP.popout)"><el-icon><FullScreen /></el-icon></button>
            <button class="fw-b" :title="$t('common.collapse')" @click="ed.leftOpen = false"><el-icon><DArrowLeft /></el-icon></button></div>
          <div class="sp-body"><component :is="leftP.component" :pid="pid" @add="addFromLibrary" @template="saveTemplate" /></div>
        </Pane>
        <Pane :size="(leftP ? sizes.main[1] : sizes.main[0] + sizes.main[1]) + (ed.rightOpen ? 0 : sizes.main[2])" :min-size="30">
          <Splitpanes horizontal @resized="saveSizes('center', $event)">
            <Pane :size="ed.tlOpen ? sizes.center[0] : 100" :min-size="40" class="ed-view" :class="'mode-' + mode">
              <div class="vp" :class="{ split: ed.split }" data-tour="wb-viewport">
                <div v-if="showGuide" class="ed-guide">
                  <b>{{ $t('workbench.startBuildingAFactoryHere') }}</b>
                  <ol>
                    <li><a @click="guideStep(1)">{{ $t('workbench.drawTheLayout') }}</a>{{ $t('workbench.useWallAreaAndAisle') }}</li>
                    <li><a @click="guideStep(2)">{{ $t('workbench.placeEquipment') }}</a>{{ $t('workbench.dragSourcesMachinesBuffersSinks') }}</li>
                    <li><a @click="guideStep(3)">{{ $t('workbench.connectTheFlow') }}</a>{{ $t('workbench.inTheGraphDragFrom') }}</li>
                    <li><a @click="guideStep(4)">{{ $t('workbench.addControlsAndNetworking') }}</a>{{ $t('workbench.selectEquipmentAndClickAdd') }}</li>
                  </ol>
                  <div class="ed-guide-f"><el-button size="small" @click="router.push('/?new=1')">{{ $t('workbench.createAFactoryFromA') }}</el-button><span class="grow" /><el-button size="small" text @click="hideGuide">{{ $t('workbench.donTShowAgain') }}</el-button></div>
                </div>
                <div v-if="ed.placing || ed.pick" class="ed-modebar" :class="{ pick: !!ed.pick }">
                  <template v-if="ed.pick"><el-icon><Aim /></el-icon><b>{{ ed.pick.prompt }}</b><span class="muted">{{ $t('workbench.clickAMachineInThe') }}</span></template>
                  <template v-else><el-icon><Pointer /></el-icon><b>{{ $t('workbench.place0', [ed.placing.label]) }}</b><span class="muted">{{ $t('workbench.clickTheCanvasToPlace') }}</span></template>
                  <el-button size="small" text @click="ed.placing = null; ed.pick = null">{{ $t('workbench.cancelEsc') }}</el-button>
                </div>
                <SelectionBar />
                <div v-show="ed.view === '3d' || ed.split" class="vp-a"><View3D ref="v3" /></div>
                <div v-if="ed.split || ed.view !== '3d'" class="vp-b">
                  <GraphView v-if="ed.split || ed.view === 'graph'" ref="graph" @template="saveTemplate" />
                  <component :is="ArchView" v-else-if="ed.view === 'arch' && ArchView" />
                  <div v-else-if="ed.view === 'arch'" class="muted" style="padding:40px;text-align:center">{{ $t('workbench.architectureViewIsUnderConstruction') }}</div>
                  <PlanView v-else ref="plan" />
                </div>
              </div>
              <div class="vp-kpi" v-if="vs" :class="{ fold: kpiFold }">
                <button class="vp-kpi-t" :title="kpiFold ? $t('workbench.expandMetrics') : $t('workbench.collapseMetrics')" @click="kpiFold = !kpiFold; saveKpiFold()"><el-icon><component :is="kpiFold ? 'DataLine' : 'ArrowRight'" /></el-icon></button>
                <template v-if="!kpiFold">
                <div><small>{{ $t('common.acceptedQty') }}</small><b>{{ vs.kpi.good }}</b></div>
                <div v-if="vs.kpi.castings"><small>{{ isFoundry ? $t('workbench.castings') : $t('workbench.feedMaterial') }}</small><b>{{ vs.kpi.castings }}</b></div>
                <div><small>{{ $t('common.scrapRate') }}</small><b>{{ pct(vs.kpi.scrap_rate, 2) }}</b></div>
                <div><small>{{ $t('livePanel.energyKwh') }}</small><b>{{ Math.round(vs.kpi.energy_kwh) }}</b></div>
                <div v-if="alarms"><small>{{ $t('common.alarm') }}</small><b class="bad">{{ alarms }}</b></div>
                </template>
              </div>
            </Pane>
            <Pane v-if="ed.tlOpen" :size="sizes.center[1]" :min-size="6" class="ed-bottom"><Timeline ref="timeline" /></Pane>
          </Splitpanes>
        </Pane>
        <Pane v-if="ed.rightOpen" :size="sizes.main[2]" :min-size="16" class="ed-right">
          <el-tabs v-model="ed.rightTab" class="ed-tabs" data-tour="wb-right">
            <el-tab-pane :label="$t('common.attribute')" name="props"><el-scrollbar><Details @template="saveTemplate" /></el-scrollbar></el-tab-pane>
            <el-tab-pane :label="$t('common.live')" name="live"><el-scrollbar><LivePanel /></el-scrollbar></el-tab-pane>
            <el-tab-pane v-for="p in inspectorPanels" :key="p.id" :label="p.title" :name="p.id"><el-scrollbar><component :is="p.component" :pid="pid" /></el-scrollbar></el-tab-pane>
          </el-tabs>
        </Pane>
      </Splitpanes>
    </div>

    <footer class="ed-status mono">
      <span>{{ $t('workbench.n0Workspace', [WORKSPACES[ed.workspace]?.label]) }}</span>
      <span>{{ $t('workbench.n0Blocks1Connections', [(ed.model.blocks || []).length, (ed.model.links || []).length]) }}</span>
      <span v-if="ed.sel.length">{{ $t('workbench.selected0', [ed.sel.length]) }}</span><span v-if="ed.selLink">{{ $t('details.connection0', [ed.selLink]) }}</span>
      <span v-if="ed.runtime?.ctl?.hit" class="warn">{{ $t('workbench.lastBreakpoint01', [ed.runtime.ctl.hit.time.slice(5, 16), ed.runtime.ctl.hit.name]) }}</span>
      <span class="click" data-k="timeline-toggle" :title="ed.tlOpen ? $t('workbench.hideTheBottomTimelineTo') : $t('workbench.showTheTimelineToReplay')" @click="setTimelineOpen(!ed.tlOpen)">{{ ed.tlOpen ? $t('workbench.hideTimeline') : $t('workbench.showTimeline') }}</span>
      <span class="grow" />
      <span class="muted click" @click="shortcuts = true">{{ $t('workbench.spaceRunPauseRightClick') }}</span>
    </footer>
    <FloatLayer />
    <ContextMenu />
    <SearchDialog />
    <!-- Banner when the PLC pauses at a breakpoint (visible even with the editor closed) -->
    <PlcHaltBar :pid="pid" />
    <el-dialog v-model="shortcuts" :title="$t('common.keyboardShortcuts')" width="620px" append-to-body>
      <table class="kb-table"><tr v-for="k in SHORTCUTS" :key="k[0]"><td><kbd>{{ k[0] }}</kbd></td><td>{{ k[1] }}</td></tr></table>
    </el-dialog>

    <el-dialog v-model="applyOpen" :title="$t('workbench.saveToModel')" width="560px" append-to-body>
      <p class="small">{{ $t('workbench.save0ChangesToThe', [ed.changes.length, ed.structural ? $t('workbench.structuralChangesAreIncludedThe') : $t('workbench.onlyParametersAndPositionsHave')]) }}</p>
      <div class="apply-list"><ChangeList :items="ed.changes" /></div>
      <el-input v-model="applyNote" :placeholder="$t('workbench.versionNotesOptionalEG')" size="small" />
      <template #footer><el-button @click="applyOpen = false">{{ $t('common.cancel') }}</el-button><el-button type="primary" :loading="applying" @click="doApply()">{{ $t('common.save') }}</el-button></template>
    </el-dialog>

    <el-drawer v-model="forkOpen" :title="$t('common.runWhatIfFromHere')" size="560px" append-to-body>
      <ForkPanel v-if="forkOpen" :pid="pid" :hours="4" />
    </el-drawer>
    <el-drawer v-model="verOpen" :title="$t('workbench.versionHistory')" size="440px" append-to-body>
      <div class="vers">
        <el-button size="small" @click="saveVersion">{{ $t('workbench.saveTheCurrentDraftAs') }}</el-button>
        <div v-for="v in versions" :key="v.n" class="ver">
          <div><b>#{{ v.n }}</b> {{ v.note }}<small class="muted"> · {{ v.user }} · {{ v.t }}</small></div>
          <div class="muted small">{{ $t('workbench.n0Blocks1Connections', [v.blocks, v.links]) }}</div>
          <div><el-button size="small" text @click="verDiff(v.n)">{{ $t('workbench.compareWithDraft') }}</el-button><el-button size="small" text type="primary" @click="loadVersion(v.n)">{{ $t('workbench.loadIntoDraft') }}</el-button></div>
          <div v-if="vdiff.n === v.n" class="vdiff"><ChangeList :items="vdiff.items" /><div v-if="!vdiff.items.length" class="muted small">{{ $t('workbench.noDifferences') }}</div></div>
        </div>
        <div v-if="!versions.length" class="muted small">{{ $t('workbench.noVersionsYetAVersion') }}</div>
      </div>
    </el-drawer>
  </div>
  <div v-else class="ed-loading">{{ $t('workbench.loading') }}</div>
</template>

<script setup lang="ts">
import { $t, matches } from '../i18n';
import '@vue-flow/core/dist/style.css';
import '@vue-flow/core/dist/theme-default.css';
import '@vue-flow/controls/dist/style.css';
import '@vue-flow/minimap/dist/style.css';
import 'splitpanes/dist/splitpanes.css';

import './editor.css';
import { ElMessage, ElMessageBox, ElNotification } from 'element-plus';
import { Pane, Splitpanes } from 'splitpanes';
import { computed, defineAsyncComponent, nextTick, onMounted, onUnmounted, reactive, ref, watch, watchEffect } from 'vue';
import { useRouter } from 'vue-router';
import { handleTeachOpen, isStudent, isTeachRole } from './shell/teach';
import { canEdit, connect, del, desk, get, isLocalPlant, P, pct, post, session } from '../api';
import { aiCtx } from '../assistant';
import DeliveryExport from '../components/DeliveryExport.vue';
import ForkPanel from '../components/ForkPanel.vue';
import GuideButton from '../components/GuideButton.vue';
import LangSwitch from '../components/LangSwitch.vue';
import ChangeList from './ChangeList.vue';
import Details from './Details.vue';
import GraphView from './GraphView.vue';
import LivePanel from './LivePanel.vue';
import PlanView from './PlanView.vue';
import ContextMenu from './shell/ContextMenu.vue';
import FilterBar from './shell/FilterBar.vue';
import SearchDialog from './shell/SearchDialog.vue';
import SelectionBar from './shell/SelectionBar.vue';
import { goBack, goFwd } from './shell/relations';
// Architecture (fourth view, ArchView.vue): load if the file exists.
const archMods = import.meta.glob('./ArchView.vue');
const ArchView = archMods['./ArchView.vue'] ? defineAsyncComponent(archMods['./ArchView.vue'] as any) : null;
import PlcHaltBar from '../plc/PlcHaltBar.vue';
import FloatLayer from './shell/FloatLayer.vue';
import { showHit, startGraphDebug, toggleDefaultBp } from './shell/graphdebug';
import { isCommon, panelById, panelsFor, WORKSPACES, type Panel } from './shell/panels';
import {
  blocksById, copySel, ctl, duplicateSel, ed, exec, flash, focusOn, groupSel, loadModel, makeBlock, mode, newId, paste, redo, reloadTemplates, removeSelected,
  saveDraft, select, selBlocks, STATE_CN, typeOf, undo, viewState, openFloat, closeFloat, floatGuards, guardFloats,
  setRightOpen, setTimelineOpen,
} from './store';
import { density } from '../compact';
import Timeline from './Timeline.vue';
import { openCommandPalette } from '../commands/registry';
import View3D from './View3D.vue';

const props = defineProps<{ pid: string }>();
const pid = computed(() => props.pid);
const router = useRouter();
const graph = ref<any>(), plan = ref<any>(), timeline = ref<any>(), v3 = ref<any>();
const vErr = computed(() => ed.validation?.summary?.error || 0), vWarn = computed(() => ed.validation?.summary?.warn || 0);
const MODE_CN: Record<string, string> = { running: $t('common.running2'), paused: $t('common.paused'), edit: $t('workbench.editReset'), replay: $t('common.replay') };
const SPEEDS = [1, 10, 60, 300, 1200, 3600];
const running = computed(() => mode.value === 'running');
const busy = computed(() => ed.runtime?.ctl?.busy);
const vs = viewState;
const alarms = computed(() => (vs.value?.stations || []).filter((s: any) => s.alarm).length);
const speed = ref(10), busyCtl = ref(false), forkOpen = ref(false), deliveryRef = ref<any>(null);
const rt = reactive({ hours: 4, at: '', id: '', state: 'Stopped' });

// ---------- Shell: workspaces, activity bar, sidebars, floating windows ----------
// Activity bar: shared panels stay at the top in fixed positions across workspaces; workspace-specific panels go below the divider. Floating copies have no separate icon (use "Pop Out" in the sidebar header).
// Students only have the "Teaching" workspace; show only panels needed for the lab (fewer for PLC lessons than production line lessons).
const wsList = computed(() => (isStudent() ? { teach: WORKSPACES.teach } : WORKSPACES));
const STU_CELL = ['teach-task', 'teach-courses', 'plc-editor', 'plc-hmi', 'cell-editor', 'breakpoints', 'events'];
const STU_PLANT = [...STU_CELL, 'outliner', 'library', 'model', 'parts', 'analysis', 'experiments', 'plan', 'design-sop'];
const actPanels = computed(() => {
  let list = panelsFor(ed.workspace).filter((p) => p.place !== 'inspector' && !p.hidden);
  if (isStudent()) { const allow = ed.teach?.kind === 'cell' ? STU_CELL : STU_PLANT; list = list.filter((p) => allow.includes(p.id)); }
  return [...list.filter(isCommon), ...list.filter((p) => !isCommon(p))];
});
const ownCount = computed(() => { const n = actPanels.value.filter(isCommon).length; return n < actPanels.value.length ? n : 0; });
const inspectorPanels = computed(() => panelsFor(ed.workspace).filter((p) => p.place === 'inspector'));
const leftP = computed(() => { const p = ed.leftOpen ? panelById(ed.leftPanel) : null; return p && p.place === 'left' ? p : null; });
const FLOAT_PROPS: Record<string, any> = { analysis: { height: 360 } };
function isOn(p: Panel) { return p.place === 'float' ? ed.floats.some((w: any) => w.id === p.id) : ed.leftOpen && ed.leftPanel === p.id; }
function activate(p: Panel) {
  if (p.place === 'float') { if (ed.floats.some((w: any) => w.id === p.id)) closeFloat(p.id); else openFloat(p, FLOAT_PROPS[p.id] || {}); return; }
  if (ed.leftOpen && ed.leftPanel === p.id) ed.leftOpen = false; else { ed.leftPanel = p.id; ed.leftOpen = true; }
}
function openPanel(id: string) { const p = panelById(id); if (p) { if (p.place === 'float') openFloat(p, FLOAT_PROPS[id] || {}); else { ed.leftPanel = id; ed.leftOpen = true; } } }
function openModel(tab: string) { ed.modelTab = tab; openPanel('model'); }
function setWorkspace(k: string, apply = true, asked = false) {
  if (apply) {
    // Close floating windows outside the new workspace (keep pinned trend charts); 4.7: prompt for unapplied changes (production plan); "Continue Editing" cancels the switch.
    const keep = new Set(panelsFor(k).map((p) => p.id));
    const drop = ed.floats.filter((f: any) => { const base = String(f.id).split(':')[0]; return base !== 'chart' && !keep.has(base); }).map((f: any) => f.id);
    if (!asked && drop.some((id: string) => floatGuards.has(id))) {
      guardFloats(drop).then((can) => { if (can.length === drop.length) setWorkspace(k, apply, true); });
      return;
    }
    ed.floats = ed.floats.filter((f: any) => !drop.includes(f.id));
  }
  ed.workspace = k; try { localStorage.setItem('vf_ws', k); } catch { /* */ }
  if (!apply) return;
  const w = WORKSPACES[k];
  ed.view = w.view; ed.rightTab = w.right;
  const first = w.left.find((id) => panelById(id)) || 'outliner';
  ed.leftPanel = first; ed.leftOpen = true;
}
function onOpenPanel(e: any) { if (e.detail?.id) openPanel(e.detail.id); }
const onShortcuts = () => { shortcuts.value = true; };   // Context menu "Keyboard Shortcuts" and Command Palette
// 4.6: selecting an object in 3D / Floor Plan / Graph / Architecture (new, non-empty selection) switches the right sidebar to "Properties" for its core details.
// Run synchronously: explicit tab changes immediately after selection take precedence ("Live" on breakpoint hit, context menu "View Live Data").
const selKey = () => (ed.sel || []).join(',') + (ed.selLink ? '|' + ed.selLink : '');
watch(selKey, (k, old) => { if (k && k !== old) ed.rightTab = 'props'; }, { flush: 'sync' });
function toggleAI() { window.dispatchEvent(new CustomEvent('vf:assistant-toggle')); }
/** "More" menu for the 4.7 compact layout. */
function onMore(c: string) {
  if (c === 'search') ed.searchOpen = true;
  else if (c === 'split') ed.split = !ed.split;
  else if (c === 'fork') forkOpen.value = true;
  else if (c === 'overlay') ed.overlay = !ed.overlay;
  else if (c === 'timeline') setTimelineOpen(!ed.tlOpen);
  else if (c === 'delivery') deliveryRef.value?.open();
}

const defSizes = innerWidth < 1500 ? { main: [19, 64, 17], center: [89, 11] } : { main: [18, 60, 22], center: [86, 14] };   // Leave more canvas space on 1366-wide laptops.
const sizes = reactive<any>((() => { try { return { ...defSizes, ...JSON.parse(localStorage.getItem('vf_wb2_sizes') || '{}') }; } catch { return defSizes; } })());
function saveSizes(k: string, e: any) {
  const arr = (Array.isArray(e) ? e : e?.panes || []).map((p: any) => p.size);
  if (arr.length === sizes[k].length) { sizes[k] = arr; try { localStorage.setItem('vf_wb2_sizes', JSON.stringify(sizes)); } catch { /* */ } }
}

// ---------- Run controls ----------
async function guarded(fn: () => Promise<any>) { busyCtl.value = true; try { return await fn(); } finally { busyCtl.value = false; } }
async function play() {
  if (ed.replay) ed.replay = null;
  if (vErr.value) { ElMessage.warning($t('workbench.theModelHasErrorsResolve')); openModel('check'); return; }
  // Warn about unconnected equipment first; otherwise the run will only show "Starved/Blocked".
  const esc = (t: string) => String(t).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] as string));
  const loose = (ed.validation?.issues || []).filter((i: any) => (i.cat_code === 'wiring' || matches(i.cat, 'common.connections')) && i.level === 'warn');
  if (loose.length && ed.structural) {
    const go = await ElMessageBox.confirm(`<div>${loose.slice(0, 6).map((i: any) => '· ' + esc(i.msg)).join('<br>')}${loose.length > 6 ? `<br>${$t('workbench.andMore')} ${loose.length} ${$t('workbench.issues')}` : ''}</div><p style="margin-top:8px">${$t('workbench.thisEquipmentWillRemainStarved')}</p>`,
      $t('workbench.connectionIssues0', [loose.length]), { dangerouslyUseHTMLString: true, confirmButtonText: $t('workbench.runAnyway'), cancelButtonText: $t('workbench.openCheck'), type: 'warning', distinguishCancelAndClose: true }).then(() => true).catch((a: string) => { if (a === 'cancel') openModel('check'); return false; });
    if (!go) return;
  }
  await guarded(async () => {
    await saveDraft();
    if (ed.structural) {
      await ElMessageBox.confirm($t('workbench.thereAreStructuralChangesEquipment'), $t('workbench.restartRun'), { confirmButtonText: $t('workbench.saveAndRestartRun'), cancelButtonText: $t('common.cancel'), type: 'warning' });
      const r = await post(P(pid.value) + '/model/apply', { note: $t('workbench.saveBeforeRunning') });
      ElMessage.success(r.msg);
      await reload();
    }
    await ctl('play', { speed: speed.value });
  });
}
async function pause() { await ctl('pause'); }
async function step(c: string) { if (ed.replay) ed.replay = null; await guarded(() => (c === 'event' ? ctl('step', { event: true }) : ctl('step', { seconds: Number(c) }))); }
async function runTo(b: any) { if (ed.replay) ed.replay = null; const r = await ctl('run_to', b); ElMessage.info($t('breakpoints.runInBackgroundUntil') + r.goal); }
async function setSpeed(v: number) { await post(P(pid.value) + '/sim', { speed: v }); }
async function reset() {
  let keep = false;
  if (ed.changes.length) {
    try {
      await ElMessageBox.confirm($t('workbench.thereAre0UnsavedChanges', [ed.changes.length, ed.live.length]), $t('workbench.reset'),
        { distinguishCancelAndClose: true, confirmButtonText: $t('workbench.keepAndSave'), cancelButtonText: $t('workbench.discardChanges'), type: 'warning' });
      keep = true;
    } catch (a) { if (a === 'close') return; }
  }
  const note = ElMessage({ message: $t('workbench.resettingRebuildingTheFactoryFrom'), type: 'info', duration: 0 });
  await guarded(async () => {
    if (keep) { await saveDraft(); await post(P(pid.value) + '/model/apply', { note: $t('workbench.saveBeforeReset'), rebuild: true }); } else await del(P(pid.value) + '/model/draft');
    await post(P(pid.value) + '/ctl/reset');
    ed.replay = null;
    await reload();
    ElMessage.success($t('workbench.resetCompleteTheModelIs'));
  }).finally(() => note.close());
}
async function reload() { const keep = { sel: ed.sel, view: ed.view, rightTab: ed.rightTab }; await loadModel(pid.value); Object.assign(ed, keep); ed.rebuild3d = (ed.rebuild3d || 0) + 1; }

// ---------- Trial run / Save / Versions ----------
const applyOpen = ref(false), applyNote = ref(''), applying = ref(false);
async function doApply() {
  applying.value = true;
  try {
    await saveDraft();
    const r = await post(P(pid.value) + '/model/apply', { note: applyNote.value });
    ElMessage.success((r.mode === 'rebuild' ? $t('workbench.savedRebuildingFromTheNew') : r.mode === 'hot' ? $t('workbench.savedSimulationContinuesUninterrupte') : r.msg) + (r.version ? $t('workbench.version0', [r.version]) : ''));
    applyOpen.value = false; applyNote.value = '';
    await reload();
  } finally { applying.value = false; }
}
async function discard() {
  await ElMessageBox.confirm($t('workbench.discardAllUnsavedChangesParameter'), $t('workbench.discardChanges2'), { type: 'warning' });
  await del(P(pid.value) + '/model/draft'); await reload(); ElMessage.success($t('workbench.draftDiscarded'));
}
const verOpen = ref(false), versions = ref<any[]>([]), vdiff = reactive<any>({ n: 0, items: [] });
async function openVersions() { versions.value = await get(P(pid.value) + '/versions'); verOpen.value = true; vdiff.n = 0; }
async function saveVersion() {
  await saveDraft();
  const { value } = await ElMessageBox.prompt($t('workbench.versionNotes'), $t('common.saveVersion'), { inputValue: $t('workbench.saveManually') }).catch(() => ({ value: null as any }));
  if (value === null) return;
  const m = await post(P(pid.value) + '/versions', { note: value }); ElMessage.success($t('workbench.savedVersion0', [m.n]));
  if (verOpen.value) versions.value = await get(P(pid.value) + '/versions');
}
async function verDiff(n: number) { await saveDraft(); vdiff.items = await get(P(pid.value) + `/versions/${n}/diff?against=draft`); vdiff.n = n; }
async function loadVersion(n: number) {
  const v = await get(P(pid.value) + `/versions/${n}`);
  exec([{ op: 'replace_model', model: v.model }], $t('workbench.loadVersion0', [n])); verOpen.value = false;
  ElMessage.success($t('workbench.version0LoadedAsA', [n]));
}

// ---------- Add / Templates ----------
function addFromLibrary(type: string) {
  const t = ed.cat.types[type], src = selBlocks.value.length === 1 ? selBlocks.value[0] : null;
  const bs = ed.model.blocks || [];
  const node = src ? [src.node[0] + 280, src.node[1]] : [bs.length ? Math.max(...bs.map((b: any) => b.node?.[0] || 0)) + 280 : 100, bs.length ? Math.min(...bs.map((b: any) => b.node?.[1] || 0)) : 100];
  const pos = src ? [src.pos[0] + src.size[0] / 2 + t.size[0] / 2 + 2, src.pos[1]] : [bs.length ? Math.max(...bs.map((b: any) => b.pos[0] + b.size[0] / 2)) + t.size[0] / 2 + 3 : 10, 10];
  const b = makeBlock(type, pos, node);
  const ops: any[] = [{ op: 'add_block', block: b }];
  const so = src ? typeOf(src).out : [];
  if (src && so.length && t.in.length) ops.push({ op: 'add_link', link: { id: newId('L'), kind: 'material', from: src.id, from_port: so[0], to: b.id, to_port: t.in[0] } });
  exec(ops, ops.length > 1 ? $t('workbench.add1After0', [src.name, t.label]) : $t('common.add0', [t.label]));
  select([b.id]); flash([b.id], 1500); focusOn(b.id, true);
}
async function saveTemplate() {
  const bs = selBlocks.value; if (!bs.length) return;
  const { value } = await ElMessageBox.prompt($t('workbench.saveThe0SelectedBlocks', [bs.length]), $t('common.saveAsTemplate'), { inputValue: bs.length === 1 ? bs[0].name : '' }).catch(() => ({ value: null as any }));
  if (!value) return;
  const ids = new Set(bs.map((b: any) => b.id));
  await post('/api/templates', { name: value, blocks: bs, links: (ed.model.links || []).filter((l: any) => ids.has(l.from) && ids.has(l.to)) });
  await reloadTemplates(); ElMessage.success($t('workbench.savedAsATemplateUnder')); ed.leftPanel = 'library'; ed.leftOpen = true;
}
function pickIssue(id: string) {
  if (blocksById.value[id] || (ed.model.groups || []).some((g: any) => g.id === id)) { select([id]); focusOn(id); }
  else if ((ed.model.links || []).some((l: any) => l.id === id)) { ed.sel = []; ed.selLink = id; }
}

// ---------- Command Palette ----------
function openPalette() { openCommandPalette(); }   // 4.5: global Command Palette (commands/); Workbench commands live in commands/workbench.ts.

// ---------- Keyboard shortcuts ----------
/** Arrow-key nudging: move graph cards (10 / Shift 50 px) or 3D equipment (0.5 / Shift 2 m). Floor Plan handles its own input. */
function nudgeSel(k: string, big: boolean) {
  const d: Record<string, number[]> = { arrowleft: [-1, 0], arrowright: [1, 0], arrowup: [0, -1], arrowdown: [0, 1] };
  const [dx, dy] = d[k] || [0, 0], graphV = ed.view === 'graph', st = graphV ? (big ? 50 : 10) : big ? 2 : 0.5;
  const field = graphV ? 'node' : 'pos';
  exec(selBlocks.value.map((b: any) => ({ op: 'update_block', id: b.id, set: { [field]: [+((b[field]?.[0] || 0) + dx * st).toFixed(2), +((b[field]?.[1] || 0) + dy * st).toFixed(2)] } })), $t('planView.nudgePosition'));
}
const shortcuts = ref(false);
// Three-step guide for an empty factory
const guideOff = ref((() => { try { return localStorage.getItem('vf_guide_off') === '1'; } catch { return false; } })());
const showGuide = computed(() => !guideOff.value && canEdit() && !!ed.model && !(ed.model.blocks || []).length);
function hideGuide() { guideOff.value = true; try { localStorage.setItem('vf_guide_off', '1'); } catch { /* */ } }
function guideStep(n: number) {
  if (n === 1) { ed.view = 'plan'; }
  else if (n === 2) { ed.leftPanel = 'library'; ed.leftOpen = true; if (ed.view === '3d') ed.view = 'plan'; }
  else if (n === 4) { ed.view = 'arch'; }
  else { ed.view = 'graph'; }
}
// Canvas metrics bar: collapsible (persisted); use "Castings" for foundries and "Material Input" for other factories.
const kpiFold = ref((() => { try { return localStorage.getItem('vf_kpi_fold') === '1'; } catch { return false; } })());
function saveKpiFold() { try { localStorage.setItem('vf_kpi_fold', kpiFold.value ? '1' : '0'); } catch { /* */ } }
const isFoundry = computed(() => (ed.model?.blocks || []).some((b: any) => ['molding_line', 'induction_furnace', 'cooling_line'].includes(b.type)));
// Actual speed: sim time / wall-clock time over the last 4 seconds.
const actual = ref(0);
let samples: number[][] = [];
watch(() => ed.runtime?.t, (t) => {
  if (t === undefined || t === null) return;
  const now = performance.now() / 1000; samples.push([now, t]); samples = samples.filter((x) => now - x[0] < 4);
  if (samples.length > 3) { const a = samples[0], b = samples[samples.length - 1]; actual.value = Math.max(0, (b[1] - a[1]) / Math.max(0.5, b[0] - a[0])); }
});
const SHORTCUTS: [string, string][] = [
  [$t('shortcutsDialog.space'), $t('shortcutsDialog.runPause')], ['F5 / F6 / F10', $t('workbench.runPauseStepToThe')], [$t('workbench.rightClick'), $t('workbench.contextMenusForEquipmentLinks')],
  [$t('workbench.clickALibraryItem'), $t('workbench.enterPlacementModeThenClick')], [$t('workbench.dragALibraryItem'), $t('workbench.dragIntoThe3dView')],
  ['Delete / Backspace', $t('common.deleteSelected')], ['Ctrl+C / Ctrl+V', $t('workbench.copyPaste')], ['Ctrl+D', $t('common.duplicate')], ['Ctrl+A', $t('common.selectAll')], ['Ctrl+G', $t('common.group')],
  ['Ctrl+Z / Ctrl+Y', $t('shortcutsDialog.undoRedo')], [$t('workbench.arrowKeys'), $t('workbench.nudgePositionHoldShiftFor')], ['R', $t('workbench.rotate90InTheFloor')], ['F', $t('common.focusOnSelectedEquipment')], ['Home', $t('common.fitAll')],
  ['F9', $t('workbench.addOrRemoveABreakpoint')], ['Tab', $t('workbench.searchForAndAddBlocks')], ['Esc', $t('workbench.cancelPlacementOrPickingAnd')],
  [$t('workbench.floorPlanTypeWhileDrawing'), $t('workbench.n125ThenEnter12')],
  [$t('workbench.floorPlanShiftAlt'), $t('workbench.whileDrawingShiftLocksHorizontal')],
  [$t('workbench.floorPlanCtrlDDouble'), $t('workbench.wallsAreasAndPathsAlso')],
  [$t('workbench.floorPlanTabDragConnection'), $t('workbench.tabAddEquipmentHoverOver')],
  [$t('workbench.floorPlanVWP'), $t('workbench.selectWallPathNetworkAnnotation')],
  [$t('workbench.n3dHoverDoubleClick'), $t('workbench.hoverToShowAnOutline')],
  ['Ctrl+F', $t('common.findEquipmentPlcChannelsOr')], ['Alt+← / Alt+→', $t('workbench.backForwardAfterNavigatingBetween')],
  ['Alt+1 / 2 / 3 / 4', $t('workbench.switchBetween3dGraphFloor')], ['Ctrl+K', $t('common.commandPalette')], ['Ctrl+S', $t('common.saveVersion')], ['Ctrl+/', $t('workbench.thisTable')],
];
function onKey(e: KeyboardEvent) {
  const k = e.key.toLowerCase(), mod = e.ctrlKey || e.metaKey;
  if (mod && k === 'k') { e.preventDefault(); openPalette(); return; }
  if ((e.target as HTMLElement).closest('input:not([type=radio]):not([type=checkbox]),textarea,[contenteditable],.el-select,.el-dialog,.aid-panel')) return;
  if (mod && k === 'z' && !e.shiftKey) { e.preventDefault(); undo(); }
  else if (mod && (k === 'y' || (k === 'z' && e.shiftKey))) { e.preventDefault(); redo(); }
  else if (mod && k === 'c') copySel();
  else if (mod && k === 'v') paste();
  else if (mod && k === 'd') { e.preventDefault(); duplicateSel(); }
  else if (mod && k === 'a') { e.preventDefault(); select((ed.model.blocks || []).map((b: any) => b.id)); }
  else if (mod && k === 'g') { e.preventDefault(); groupSel(); }
  else if (mod && k === 's') { e.preventDefault(); saveVersion(); }
  else if (k === ' ' && ed.view !== 'plan' && canEdit()) { e.preventDefault(); running.value ? pause() : play(); }
  else if (k === 'delete' || k === 'backspace') removeSelected();
  else if (k === 'f5' && canEdit()) { e.preventDefault(); if (!running.value) play(); }
  else if (k === 'f6' && canEdit()) { e.preventDefault(); if (running.value) pause(); }
  else if (k === 'f10' && canEdit()) { e.preventDefault(); step('event'); }
  else if (k === 'f9') { e.preventDefault(); if (ed.sel.length && canEdit()) toggleDefaultBp(ed.sel); }
  else if (mod && k === '/') { e.preventDefault(); shortcuts.value = true; }
  else if (mod && k === 'f') { e.preventDefault(); ed.searchOpen = true; }
  else if (e.altKey && k === 'arrowleft') { e.preventDefault(); goBack(); }
  else if (e.altKey && k === 'arrowright') { e.preventDefault(); goFwd(); }
  else if (ed.replay && (k === 'arrowleft' || k === 'arrowright')) { e.preventDefault(); timeline.value?.stepBy(k === 'arrowleft' ? -1 : 1); }
  else if (k.startsWith('arrow') && ed.sel.length && ed.view !== 'plan' && canEdit()) { e.preventDefault(); nudgeSel(k, e.shiftKey); }
  else if (k === 'f' && !mod) focusOn(ed.sel[0] || '');
  else if (k === 'home') focusOn('');
  else if (k === 'tab' && ed.view === 'graph') { e.preventDefault(); graph.value?.openAdd(); }
  else if (k === 'escape') {
    if (ed.placing || ed.pick) { ed.placing = null; ed.pick = null; }
    else if (ed.floats.length) { const top = ed.floats.reduce((a: any, b: any) => (b.z > a.z ? b : a)); closeFloat(top.id); }   // Esc closes the topmost floating window.
    else { ed.sel = []; ed.selLink = ''; }
  }
  else if (e.altKey && ['1', '2', '3', '4'].includes(k)) { e.preventDefault(); ed.view = ['3d', 'graph', 'plan', 'arch'][+k - 1]; }
}

// ---------- Breakpoint hit: notify + locate ----------
watch(() => ed.runtime?.ctl?.hit, (h) => {
  if (!h || h.t === ed.lastHit || ed.lastHit === 0) return;
  ed.lastHit = h.t;
  ElNotification({ title: $t('common.paused'), message: h.msg || h.name, type: 'warning', duration: 6000 });
  if (h.station && blocksById.value[h.station]) { showHit(h.station); ed.rightTab = 'live'; }
});
watch(() => ed.runtime?.speed, (v) => { if (v) speed.value = v; });

// ---------- Context for the bottom-right AI Assistant ----------
function syncAi() {
  aiCtx.plant = pid.value; aiCtx.page = `/p/${pid.value}/workbench`; aiCtx.view = ed.view;
  aiCtx.selection = [...ed.sel, ...(ed.selLink ? [ed.selLink] : [])];
  aiCtx.names = [...ed.sel.map((id: string) => blocksById.value[id]?.name || id), ...(ed.selLink ? [$t('workbench.connect') + ed.selLink] : [])];
  aiCtx.replayTime = ed.replay?.time || '';
}
watch(() => [ed.sel, ed.selLink, ed.view, ed.replay], syncAi, { deep: true });

let stopWs: any = null, stopDbg: any = null;
onMounted(async () => {
  ed.model = null; ed.tryrun = null; ed.replay = null; ed.lastHit = 0;
  if (session.readonlyPid && session.readonlyPid !== props.pid) session.readonlyPid = '';
  try { await loadModel(props.pid); } catch {
    // After a service restart, re-enter the sandbox from "Lab Tasks" (the backend reloads it on entry).
    if (props.pid.startsWith('sb-')) { ElMessage.warning($t('workbench.theSandboxIsAsleepReopen')); router.replace(isTeachRole() ? '/teach' : '/'); }
    return;
  }
  // Empty factory: open the Design workspace (Floor Plan + resource library) with a three-step canvas guide.
  if (!(ed.model.blocks || []).length && canEdit() && !props.pid.startsWith('sb-')) { setWorkspace('design'); ed.leftPanel = 'library'; }
  else
  // Students / teachers entering a sandbox: default to the Teaching workspace and Lab Tasks panel.
  if (props.pid.startsWith('sb-') && (isTeachRole() || desk.on)) {   // Local accounts are admins in the desktop client, but sandboxes still open in lab mode
    setWorkspace('teach'); if (panelById('teach-task')) ed.leftPanel = 'teach-task';
    if (panelById('teach-metrics')) ed.rightTab = 'teach-metrics';   // Show this task's metrics in the right panel, not factory-wide KPIs
    if (!localStorage.getItem('vf_wb2_sizes')) sizes.center = [94, 6];   // The timeline is rarely used in labs: collapse it by default (drag the divider to expand)
  }
  else if (!ed.leftPanel || !panelById(ed.leftPanel)) setWorkspace(ed.workspace);
  stopDbg = startGraphDebug();
  stopWs = connect(props.pid, (s) => { if (ed.lastHit === 0) ed.lastHit = s.ctl?.hit?.t ?? -1; ed.runtime = s; });   // Ignore old hits from before opening
  addEventListener('keydown', onKey);
  Object.assign(aiCtx, {
    getModel: () => ed.model,
    apply: (ops: any[], label: string) => { exec(ops, label); flash([...new Set(ops.flatMap((o: any) => [o.block?.id, o.link?.id, o.id]).filter(Boolean))] as string[], 6000); },
    highlight: (ids: string[]) => flash(ids, 6000),
    navigate: (nav: any) => {
      if (nav.view) ed.view = nav.view;
      if (nav.select?.length) { select(nav.select.filter((i: string) => blocksById.value[i])); nextTick(() => focusOn(nav.select[0])); }
      if (nav.time) timeline.value?.goToTime(nav.time);
    },
  });
  addEventListener('vf:open-panel', onOpenPanel);
  addEventListener('vf:shortcuts', onShortcuts);
  (window as any).__vfUndoDepth = () => ed.undo.length;
  (window as any).__vfUndo = undo;
  syncAi();
  if (watchOnly.value) ElMessage.info($t('workbench.spectatorModeViewOnly'));
  else if (!canEdit()) ElMessage.info($t('workbench.yourAccountHasViewOnly'));
});
const stopTeach = handleTeachOpen(() => props.pid);
// Switch to 3D for SOP playback (Floor Plan and Graph views have no movable camera)
watch(() => ed.sop?.n, (n) => { if (n && ed.view !== '3d' && !ed.split) ed.view = '3d'; });
const watchOnly = computed(() => !!session.readonlyPid && session.readonlyPid === props.pid);
// PLC lessons (control unit lessons): students edit only the program; lock the model (line lessons require model edits, so leave it unlocked). The backend enforces this too.
watchEffect(() => { ed.modelLocked = isStudent() && ed.teach?.kind === 'cell'; });
onUnmounted(() => {
  stopTeach(); stopDbg?.(); ed.placing = null; ed.pick = null;
  removeEventListener('vf:open-panel', onOpenPanel);
  removeEventListener('vf:shortcuts', onShortcuts);
  stopWs?.(); removeEventListener('keydown', onKey); ed.runtime = null; ed.replay = null;
  Object.assign(aiCtx, { getModel: null, apply: null, highlight: null, navigate: null, selection: [], names: [], replayTime: '', view: '' });
});
</script>
