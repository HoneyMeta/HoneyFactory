<template>
  <div class="vp task-metrics">
    <div class="vp-head"><span class="ttl">{{ $t('taskMetrics.taskMetrics') }}</span><span class="vp-small vp-muted">{{ data?.time ? $t('taskMetrics.simulation') + data.time.slice(11) : '' }}</span></div>
    <div class="vp-body" v-if="!aid"><div class="vp-empty">{{ $t('taskMetrics.metricsForTheCurrentTask') }}</div></div>
    <div class="vp-body" v-else-if="!data"><div class="vp-empty">{{ $t('common.loading') }}</div></div>
    <div class="vp-body" v-else>
      <!-- Production line lessons: live progress for each target -->
      <template v-if="data.progress">
        <div v-for="r in data.progress.rules.filter((x: any) => x.kind !== 'answer')" :key="r.key" class="m-row">
          <div class="vp-row sp"><span>{{ r.label }}</span>
            <el-icon v-if="r.ok === true" class="vp-pass"><CircleCheckFilled /></el-icon><el-icon v-else-if="r.ok === false" class="vp-fail"><WarningFilled /></el-icon></div>
          <div class="vp-row sp"><b class="big">{{ fmtNum(r.value) }}</b><span class="vp-small vp-muted">{{ $t('taskMetrics.target0', [humanRule(r)]) }}</span></div>
        </div>
        <div class="vp-small vp-muted">{{ $t('taskMetrics.metricsAreEstimatesBasedOn') }}</div>
      </template>
      <!-- PLC lessons: parts, PLC, I/O -->
      <template v-else>
        <div class="vp-kv" style="margin-bottom: 8px">
          <span :title="data.plc_block ? $t('taskMetrics.plcBlock') + data.plc_block.id : ''">{{ data.plc_block?.name || 'PLC' }}</span><span>{{ PLC_CN[data.plc] || data.plc || '—' }}</span>
          <template v-for="m in metricRows(data.stats, data.rule_keys || [])" :key="m.key"><span>{{ m.label }}</span><span>{{ m.text }}</span></template>
          <template v-if="data.alarm"><span>{{ $t('common.alarm') }}</span><span class="vp-fail">{{ data.alarm }}</span></template>
        </div>
        <div class="vp-sec"><div class="lbl">{{ $t('taskMetrics.inputOutput') }}</div>
          <div class="io">
            <span v-for="(v, k) in data.io" :key="k" class="io-i"><span class="vp-dot" :class="{ on: v === true || (typeof v === 'number' && v > 0) }" /> <span class="mono">{{ k }}</span>
              <span v-if="typeof v === 'number'" class="mono vp-muted">{{ fmtNum(v) }}</span></span>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
// "Task Metrics" in the lab sandbox's right sidebar (inspector panel, replacing factory-wide KPIs): live grading-target progress for production line lessons; part count, PLC status, and I/O for PLC lessons.
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { get } from '../../api';
import { fmtNum, humanRule, metricRows, PLC_CN, poll } from './util';
import './panel.css';

const props = defineProps<{ pid?: string }>();
const data = ref<any>(null);
const aid = computed(() => ((props.pid || '').startsWith('sb-review-') ? 0 : Number((props.pid || '').match(/^sb-.+-(\d+)$/)?.[1] || 0)));   // A review sandbox is not an assignment sandbox.
let stop: any = null;
const who = computed(() => (props.pid || '').match(/^sb-(.+)-\d+$/)?.[1] || '');
let me: any = null;
async function load() {
  if (!aid.value) return;
  me ||= await get('/api/teach/me', true).catch(() => ({}));
  const other = me.is_teacher && who.value && who.value !== me.safe;      // Teacher viewing a student's sandbox: show that student's data (read-only, without waking the sandbox).
  const lv = other ? await get(`/api/teach/assignments/${aid.value}/students/${encodeURIComponent(who.value)}/watch`, true)
    : await get(`/api/teach/assignments/${aid.value}/live`, true);
  const tk = data.value?.rule_keys ? null : await get(`/api/teach/assignments/${aid.value}/task`, true);
  data.value = { ...lv, rule_keys: data.value?.rule_keys || (tk?.scene?.rules || []).map((r: any) => r.key) };
}
watch(aid, () => { data.value = null; stop?.(); stop = aid.value ? poll(load, 2000) : null; }, { immediate: true });
onBeforeUnmount(() => stop?.());
</script>

<style scoped>
.m-row { border-bottom: 1px solid var(--el-border-color-extra-light); padding: 6px 0; }
.big { font-size: 20px; font-variant-numeric: tabular-nums; }
.io { display: flex; flex-wrap: wrap; gap: 4px 12px; }
.io-i { font-size: 12px; white-space: nowrap; }
</style>
