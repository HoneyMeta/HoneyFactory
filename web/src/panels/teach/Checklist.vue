<template>
  <div class="ckl" :class="{ compact }" data-tour="checklist">
    <div v-if="!cl" class="ck-empty">{{ c.s.err ? $t('checklist.unableToLoadTheChecklist') : $t('checklist.loadingChecklist') }}</div>
    <div v-else-if="cl.preparing" class="ck-empty">{{ $t('checklist.preparingChecklistRunningTheTest') }}</div>
    <template v-else>
      <!-- All checks passed: explain the next step -->
      <div v-if="success" class="ck-ok" data-k="checklist-success">
        <b>{{ $t('checklist.allItemsCompleted') }}</b>
        <span>{{ $t('checklist.n0ClickSubmitForGrading', [cl.auto_full ? $t('checklist.theAutomatedPrecheckAlsoEarned') : '']) }}</span>
        <button v-if="showSubmit" class="ck-btn pri" data-act="checklist-submit" @click="emit('submit')">{{ $t('common.submitForGrading') }}</button>
      </div>
      <div v-else-if="!compact" class="ck-head">
        <span>{{ $t('checklist.checkOffItemsAsYou', [cl.done, cl.total]) }}</span>
        <span class="grow" />
        <button class="ck-btn" :disabled="c.s.autoBusy" data-act="autotest" :title="$t('checklist.runTheCurrentPlcProgram')" @click="autotest">
          {{ c.s.autoBusy ? $t('checklist.testing') : $t('checklist.automatedPrecheck') }}</button>
        <button v-if="trialAll" class="ck-btn" data-act="trial-all" :title="$t('checklist.automaticallyRunsTheGradingTest')" @click="trial()">{{ $t('checklist.demoAll') }}</button>
      </div>
      <div v-if="cl.trial" class="ck-trial">{{ $t('checklist.demonstrating0', [cl.trial.key ? $t('checklist.k4568') + label(cl.trial.key) + $t('archView.k772') : $t('checklist.allTests')]) }} <a @click="c.stopTrial()">{{ $t('common.stop') }}</a></div>
      <div v-for="it in items" :key="it.key" class="ck-i" :class="it.state" :data-key="it.key" :data-state="it.state">
        <div class="ck-row">
          <span class="ck-ic">{{ ICON[it.state] || '○' }}</span>
          <span class="ck-l">{{ it.label }}</span>
          <span v-if="!compact" class="ck-w">{{ $t('common.n0Min', [fmt(it.weight)]) }}</span>
          <span v-if="it.auto && !compact" class="ck-a" :class="it.auto.ok ? 'ok' : 'bad'" :title="it.auto.ok ? $t('checklist.automatedPrecheckPassed') : $t('checklist.automatedPrecheckFailed') + (it.auto.desc ? '——' + it.auto.desc : '')">{{ $t('checklist.test0', [it.auto.ok ? '✓' : '✗']) }}</span>
          <button v-if="it.trial && !compact" class="ck-btn sm" :data-act="'trial-' + it.key" :title="$t('checklist.thisItemRequiresASimulated')" @click="trial(it.key)">{{ $t('checklist.demo') }}</button>
        </div>
        <div v-if="!compact || it.state === 'fail'" class="ck-how">
          <template v-if="it.state === 'fail' && it.msg"><b class="bad">{{ $t('checklist.notCompleted') }}</b>{{ it.msg }}<br v-if="!compact" /></template>
          <template v-if="!compact"><span class="muted">{{ $t('checklist.howToTest') }}</span>{{ it.how }}</template>
          <template v-if="it.kind === 'stat' && it.msg && !compact"> · {{ it.msg }}</template>
        </div>
        <div v-if="!compact && it.means" class="ck-means muted">{{ it.means }}</div>
      </div>
      <div v-if="!compact && autoMismatch.length" class="ck-warn">
        {{ $t('checklist.theAutomatedPrecheckAndYour', [autoMismatch.join($t('common.k360'))]) }}
      </div>
      <div v-if="!compact" class="ck-foot muted">{{ $t('checklist.triedAndSucceededInThe') }}</div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Live checklist: check off each grading criterion as the user works (backend uses the same conditions as grading; see vfactory/control/live.py).
import { ElMessage } from 'element-plus';
import { computed } from 'vue';
import { useCoach } from './coach';

const props = defineProps<{ pid: string; compact?: boolean; showSubmit?: boolean }>();
const emit = defineEmits<{ (e: 'submit'): void }>();
const c = useCoach(props.pid);
const ICON: Record<string, string> = { ok: '✓', fail: '✗', partial: '◐', todo: '○' };
const cl = computed<any>(() => c.s.checklist);
const items = computed<any[]>(() => cl.value?.items || []);
const success = computed(() => !!cl.value?.all_ok || !!cl.value?.auto_full);
const trialAll = computed(() => items.value.some((i) => i.kind === 'check'));
const autoMismatch = computed(() => items.value.filter((i) => i.auto && ((i.state === 'ok' && !i.auto.ok) || (i.state === 'fail' && i.auto.ok))).map((i) => i.label));
const label = (k: string) => items.value.find((i) => i.key === k)?.label || k;
const fmt = (v: any) => (Number.isInteger(v) ? String(v) : Number(v).toFixed(1));
async function trial(key?: string) {
  try { const r = await c.trial(key); ElMessage.info($t('checklist.startTheDemoAbout0', [Math.round(r.seconds)])); } catch { /* Already notified */ }
}
async function autotest() {
  try { const r: any = await c.autotest(); ElMessage.success($t('checklist.automatedPrecheck0PointsNot', [r?.score ?? '—'])); } catch { /* Already notified */ }
}
</script>

<style scoped>
.ckl { font-size: 12.5px; color: var(--el-text-color-primary); }
.ck-empty { color: var(--el-text-color-secondary); padding: 6px 0; }
.ck-head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; font-size: 12px; color: var(--el-text-color-secondary); flex-wrap: wrap; }
.ck-ok { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 8px 10px; border-radius: 6px; margin-bottom: 8px; line-height: 1.5;
  background: var(--el-color-success-light-9); border: 1px solid var(--el-color-success-light-5); color: var(--el-text-color-primary); }
.ck-ok b { color: var(--el-color-success); font-size: 13.5px; }
.ck-trial { padding: 4px 8px; background: var(--el-color-primary-light-9); border-radius: 4px; margin-bottom: 6px; font-size: 12px; }
.ck-trial a { cursor: pointer; color: var(--el-color-primary); }
.ck-i { padding: 6px 8px; border: 1px solid var(--el-border-color-lighter); border-radius: 5px; margin-bottom: 5px; background: var(--el-bg-color); }
.ck-i.ok { border-color: var(--el-color-success-light-5); }
.ck-i.fail { border-color: var(--el-color-danger-light-5); background: var(--el-color-danger-light-9); }
.ck-row { display: flex; align-items: center; gap: 6px; }
.ck-ic { width: 16px; text-align: center; font-weight: 700; color: var(--el-text-color-placeholder); flex: none; }
.ok .ck-ic { color: var(--el-color-success); } .fail .ck-ic { color: var(--el-color-danger); } .partial .ck-ic { color: var(--el-color-warning); }
.ck-l { flex: 1; min-width: 0; font-weight: 500; }
.ck-w { font-size: 11px; color: var(--el-text-color-secondary); flex: none; }
.ck-a { font-size: 10.5px; padding: 0 4px; border-radius: 3px; flex: none; }
.ck-a.ok { background: var(--el-color-success-light-9); color: var(--el-color-success); } .ck-a.bad { background: var(--el-color-danger-light-9); color: var(--el-color-danger); }
.ck-how { margin: 3px 0 0 22px; font-size: 11.5px; line-height: 1.55; color: var(--el-text-color-regular); }
.ck-means { margin: 2px 0 0 22px; font-size: 11px; line-height: 1.5; }
.ck-warn { margin-top: 6px; padding: 5px 8px; border-radius: 4px; background: var(--el-color-warning-light-9); font-size: 11.5px; line-height: 1.5; }
.ck-foot { margin-top: 6px; font-size: 11px; line-height: 1.5; }
.ck-btn { border: 1px solid var(--el-border-color); background: var(--el-bg-color); color: var(--el-text-color-regular); border-radius: 4px; padding: 0 8px; height: 22px;
  font-size: 11.5px; cursor: pointer; flex: none; }
.ck-btn:hover:not(:disabled) { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.ck-btn.sm { height: 19px; padding: 0 6px; font-size: 11px; }
.ck-btn.pri, .ck-btn.pri:hover:not(:disabled) { background: var(--el-color-success); border-color: var(--el-color-success); color: #fff; }
.ck-btn.pri:hover:not(:disabled) { filter: brightness(1.08); }   /* 4.6: no primary text color on hover (hard to read on a green background) */
.bad { color: var(--el-color-danger); } .muted { color: var(--el-text-color-secondary); } .grow { flex: 1; }
.compact .ck-i { padding: 2px 6px; margin-bottom: 2px; border: 0; background: none; }
.compact .ck-i.fail { background: var(--el-color-danger-light-9); }
.compact .ck-how { margin-left: 22px; font-size: 11px; }
</style>
