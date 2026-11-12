<template>
  <!-- 4.7 "?" guided tours: list tours for this area + two complete tasks; click to start (interrupted tours show "Resume at Step N") -->
  <el-popover v-model:visible="open" placement="bottom-end" :width="300" trigger="click" popper-class="gb-pop" :teleported="true">
    <template #reference>
      <button type="button" class="gb-btn" :class="size" data-tour="guide-btn" data-k="guide-btn" :data-area="area" :title="$t('guideButton.guidedTourHowToUse')" @click.stop>
        <span aria-hidden="true">?</span>
      </button>
    </template>
    <div class="gb" data-k="guide-menu" :data-area="area">
      <div class="gb-h"><b>{{ $t('guides.guidedTour') }}</b><small>{{ $t('guideButton.followTheStepsExitAt') }}</small></div>
      <button v-for="g in list.here" :key="g.key" type="button" class="gb-it" data-k="guide-item" :data-guide="g.key" @click="run(g.key)">
        <span class="gb-t">{{ g.title }}<em v-if="at(g)">{{ $t('guideButton.resumeAtStep0', [at(g) + 1]) }}</em></span><small>{{ $t('assistantDock.n01Steps', [g.desc, g.steps.length]) }}</small>
      </button>
      <div v-if="!list.here.length" class="gb-none">{{ $t('guideButton.thereIsNoDedicatedTour') }}</div>
      <template v-if="list.tasks.length">
        <div class="gb-sec">{{ $t('guideButton.fullTaskGuidedWalkthrough') }}</div>
        <button v-for="g in list.tasks" :key="g.key" type="button" class="gb-it task" data-k="guide-item" :data-guide="g.key" @click="run(g.key)">
          <span class="gb-t">{{ g.title }}<em v-if="at(g)">{{ $t('guideButton.resumeAtStep0', [at(g) + 1]) }}</em></span><small>{{ $t('assistantDock.n01Steps', [g.desc, g.steps.length]) }}</small>
        </button>
      </template>
      <div class="gb-f">{{ $t('guideButton.allToursPress') }} <kbd>Ctrl K</kbd> {{ $t('guideButton.searchForGuidedTours') }}</div>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
// Shared "?" button across modules (Workbench top bar, Floor Plan toolbar, PLC editor, analysis window, experiments, Signals, course page, Teacher Console, MES).
// area: current location (areas on each tour in guides.ts).
import { computed, ref } from 'vue';
import { guideAt, guidesFor, startGuide, type Guide } from '../panels/teach/tour/guides';

const props = withDefaults(defineProps<{ area: string; size?: 'sm' | 'md' }>(), { size: 'md' });
const open = ref(false);
const tick = ref(0);
const list = computed(() => { void tick.value; void open.value; return guidesFor(props.area); });
const at = (g: Guide) => { void tick.value; const i = guideAt(g.key); return i > 0 && i < g.steps.length ? i : 0; };
function run(key: string) { open.value = false; tick.value++; startGuide(key); }
</script>

<style scoped>
.gb-btn { flex: none; display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; padding: 0; border-radius: 50%; cursor: pointer;
  border: 1px solid var(--hm-border-strong); background: var(--hm-surface); color: var(--hm-text-2);
  font: 600 13px/1 system-ui, -apple-system, 'Segoe UI', sans-serif; }
.gb-btn.sm { width: 20px; height: 20px; font-size: 12px; }
.gb-btn:hover, .gb-btn:focus-visible { border-color: var(--el-color-primary); color: var(--el-color-primary); outline: none; }
</style>
<style>
/* Append the popup to body to isolate it from panel styles */
.gb-pop.el-popover { padding: 8px; }
.gb { display: flex; flex-direction: column; gap: 2px; font-size: 13px; color: var(--el-text-color-primary); }
.gb-h { display: flex; align-items: baseline; gap: 8px; padding: 2px 6px 6px; }
.gb-h small, .gb-it small, .gb-f, .gb-none { color: var(--el-text-color-secondary); font-size: 12px; }
.gb-it { display: flex; flex-direction: column; align-items: flex-start; gap: 1px; text-align: left; width: 100%; padding: 6px 8px; border: 0; border-radius: 6px;
  background: transparent; color: inherit; font: inherit; cursor: pointer; }
.gb-it:hover, .gb-it:focus-visible { background: var(--el-fill-color-light); outline: none; }
.gb-t { font-weight: 500; display: flex; align-items: center; gap: 6px; }
.gb-t em { font-style: normal; font-size: 11px; font-weight: 400; color: var(--el-color-primary); border: 1px solid var(--el-color-primary-light-5); border-radius: 999px; padding: 0 6px; }
.gb-it.task .gb-t::before { content: '▶'; font-size: 9px; color: var(--el-color-success); }
.gb-sec { margin: 6px 6px 2px; padding-top: 6px; border-top: 1px solid var(--el-border-color-lighter); font-size: 12px; color: var(--el-text-color-secondary); }
.gb-none { padding: 4px 8px; }
.gb-f { padding: 6px 6px 2px; border-top: 1px solid var(--el-border-color-lighter); margin-top: 4px; }
.gb-f kbd { font-family: var(--hm-font-mono); font-size: 10.5px; border: 1px solid var(--el-border-color); border-radius: 4px; padding: 0 4px; }
</style>
