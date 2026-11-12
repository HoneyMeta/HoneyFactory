<template>
  <div class="rlog" :class="{ compact }" data-tour="run-log">
    <div class="rl-bar">
      <button v-for="f in FILTERS" :key="f.k" class="rl-f" :class="{ on: filter === f.k }" :data-filter="f.k" @click="filter = f.k">{{ f.label }}</button>
      <span class="grow" />
      <label class="rl-auto" :title="$t('runLog.automaticallyScrollToTheBottom')"><input v-model="follow" type="checkbox" />{{ $t('runLog.follow') }}</label>
      <button class="rl-f" :title="$t('runLog.clearTheLogAlsoCleared')" data-act="clear-log" @click="c.clear()">{{ $t('debugConsole.clear') }}</button>
    </div>
    <div ref="box" class="rl-body" @scroll="onScroll">
      <div v-if="!shown.length" class="rl-empty">{{ c.s.err ? $t('runLog.cannotReadTheRunLog') + c.s.err : $t('runLog.noEntriesYetPressButtons') }}</div>
      <div v-for="e in shown" :key="e.seq" class="rl-e" :class="['k-' + e.k, e.ok === false ? 'bad' : e.ok === true ? 'good' : '']" :data-k="e.k">
        <span class="rl-t mono" :title="$t('runLog.cellSimTime0Computer', [fmtSimT(e.t), fmtWall(e.wall)])">{{ e.t !== null && e.t !== undefined ? fmtSimT(e.t) : '' }}<small>{{ fmtWall(e.wall) }}</small></span>
        <span class="rl-k">{{ KIND_CN[e.k] || e.k }}</span>
        <span class="rl-m">{{ e.msg }}<a v-if="e.k === 'diag' && e.plc && (e.rung !== undefined || e.line)" class="rl-go" @click="goto(e)">{{ $t('runLog.viewInProgram') }}</a></span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// Run log: actions, input/output changes, PLC, checklist, diagnostics, and alarms. Show unit sim time (from 0 after restart/reset) and computer time.
import { computed, nextTick, ref, watch } from 'vue';
import { FILTERS, fmtSimT, fmtWall, KIND_CN, useCoach } from './coach';

const props = defineProps<{ pid: string; compact?: boolean; max?: number; initial?: string }>();
const c = useCoach(props.pid);
const filter = ref(props.initial || 'all');
const follow = ref(true);
const box = ref<HTMLElement | null>(null);
const shown = computed(() => {
  const f = FILTERS.find((x) => x.k === filter.value);
  let l = c.s.entries;
  if (f && f.kinds.length) l = l.filter((e) => f.kinds.includes(e.k));
  return props.max ? l.slice(-props.max) : l;
});
function onScroll() {
  const b = box.value; if (!b) return;
  follow.value = b.scrollHeight - b.scrollTop - b.clientHeight < 30;
}
watch(() => [shown.value.length, shown.value[shown.value.length - 1]?.seq], () => {
  if (!follow.value) return;
  nextTick(() => { const b = box.value; if (b) b.scrollTop = b.scrollHeight; });
}, { immediate: true });
/** Diagnostic entry: open the programming window at the relevant rung / line. */
function goto(e: any) {
  window.dispatchEvent(new CustomEvent('vf:plc-goto', { detail: { pid: props.pid, plc: e.plc, rung: e.rung, line: e.line, elems: e.elems } }));
}
</script>

<style scoped>
.rlog { display: flex; flex-direction: column; min-height: 0; height: 100%; font-size: 12px; color: var(--el-text-color-primary); }
.rl-bar { display: flex; align-items: center; gap: 3px; flex-wrap: wrap; padding: 3px 0 4px; }
.rl-f { border: 1px solid var(--el-border-color); background: var(--el-bg-color); color: var(--el-text-color-regular); border-radius: 10px; padding: 0 8px; height: 20px;
  font-size: 11px; cursor: pointer; }
.rl-f.on { background: var(--el-color-primary-light-9); border-color: var(--el-color-primary); color: var(--el-color-primary); }
.rl-auto { display: inline-flex; align-items: center; gap: 2px; font-size: 11px; color: var(--el-text-color-secondary); margin-right: 4px; }
.rl-body { flex: 1; min-height: 60px; overflow: auto; border: 1px solid var(--el-border-color-lighter); border-radius: 4px; background: var(--el-fill-color-lighter); }
.rl-empty { padding: 10px; color: var(--el-text-color-secondary); line-height: 1.6; }
.rl-e { display: flex; gap: 6px; padding: 2px 6px; border-bottom: 1px solid var(--el-border-color-extra-light); line-height: 1.5; align-items: baseline; }
.rl-t { flex: none; width: 52px; color: var(--el-text-color-secondary); font-size: 11px; display: flex; flex-direction: column; line-height: 1.2; }
.rl-t small { font-size: 9.5px; opacity: .75; }
.compact .rl-t small { display: none; }
.rl-k { flex: none; width: 30px; font-size: 10.5px; color: var(--el-text-color-secondary); }
.rl-m { flex: 1; min-width: 0; word-break: break-all; }
.k-act .rl-k { color: var(--el-color-primary); }
.k-in .rl-m, .k-out .rl-m { font-family: Consolas, monospace; font-size: 11.5px; }
.k-out .rl-k { color: var(--hm-run-ink); }
.k-plc .rl-k { color: var(--el-color-primary); font-weight: 600; }
.k-diag { background: var(--el-color-danger-light-9); }
.k-diag .rl-k, .k-diag .rl-m { color: var(--el-color-danger); }
.k-alarm .rl-k, .k-alarm .rl-m { color: var(--hm-idle-ink); }
.k-check.good .rl-m { color: var(--el-color-success); }
.k-check.bad .rl-m { color: var(--el-color-danger); }
.k-trial .rl-m { color: var(--el-color-primary); }
.rl-go { margin-left: 6px; cursor: pointer; color: var(--el-color-primary); white-space: nowrap; }
.grow { flex: 1; } .mono { font-family: Consolas, monospace; }
.compact .rl-e { padding: 1px 5px; }
</style>
