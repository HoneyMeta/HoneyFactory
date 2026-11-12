<template>
  <!-- Class progress (5.0): students work locally in the desktop client, which reports progress, current step, and local scores; sends an online heartbeat every minute while open.
       Shows who is online, who is stuck on which step and for how long, who has not started, and progress and scores per lesson. -->
  <div class="page" data-k="progress-page">
    <div class="page-head"><h2>{{ $t('common.classProgress') }}</h2><span class="sub">{{ $t('classProgress.progressIsReportedAutomaticallyWhile') }}</span><span class="grow" />
      <el-select v-model="cid" :placeholder="$t('common.selectClass')" style="width:220px" data-k="progress-class" @change="load">
        <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" /></el-select>
      <el-button :disabled="!cid" :loading="busy" @click="load">{{ $t('common.refresh') }}</el-button></div>

    <template v-if="data">
      <div class="sum" data-k="progress-summary">
        <button v-for="f in FILTERS" :key="f.k" class="chip" :class="[f.k, { on: filter === f.k }]" :data-k="'pf-' + f.k" @click="filter = f.k">
          <b>{{ f.k === 'all' ? data.summary.students : data.summary[f.k] ?? 0 }}</b><span>{{ f.label }}</span></button>
        <span class="grow" />
        <span class="muted">{{ $t('classProgress.onlineTheClientHasReported', [Math.round(data.online_s / 60), data.stuck_min]) }}</span>
      </div>
      <div class="card">
        <el-table :data="shown" size="small" data-k="progress-table" max-height="calc(100vh - 260px)" :row-class-name="rowClass" :default-sort="{ prop: 'order', order: 'ascending' }">
          <el-table-column :label="$t('common.student')" fixed width="170" prop="order" sortable :sort-method="byOrder">
            <template #default="{ row }">
              <div class="who"><span class="dot" :class="{ on: row.online }" :data-k="'pc-online-' + row.username" :title="row.online ? $t('classProgress.clientOpen') : $t('common.offline')" />
                <div><b>{{ row.name }}</b><br><small class="muted">{{ row.username }} · {{ seen(row) }}</small></div></div>
            </template>
          </el-table-column>
          <el-table-column :label="$t('classProgress.currentlyWorkingOn')" min-width="240">
            <template #default="{ row }">
              <div v-if="row.current" class="cur">
                <el-tag v-if="row.stuck" type="danger" size="small" effect="dark" :data-k="'pc-stuck-' + row.username">{{ $t('classProgress.stuckFor0Min', [mins(row.current.step_min)]) }}</el-tag>
                <b>{{ row.current.title }}</b>
                <div class="pc-step">{{ row.current.step || STATE[row.current.state] || '' }}<span v-if="!row.stuck && row.current.step_min != null" class="muted">{{ $t('classProgress.n0Min', [mins(row.current.step_min)]) }}</span></div>
              </div>
              <span v-else class="muted">{{ $t('classProgress.theAssignmentHasNotBeen') }}</span>
            </template>
          </el-table-column>
          <el-table-column v-for="a in data.assignments" :key="a.id" :label="a.title" min-width="150">
            <template #default="{ row }">
              <div v-if="cell(row, a.id)" class="cell" :data-k="`pc-${row.username}-${a.id}`">
                <el-progress :percentage="Math.round((cell(row, a.id).progress ?? 0) * 100)" :stroke-width="7" :show-text="false"
                             :status="cell(row, a.id).state === 'submitted' || cell(row, a.id).state === 'done' ? 'success' : cell(row, a.id).step_min >= data.stuck_min ? 'exception' : undefined" />
                <div class="pc-step">{{ cell(row, a.id).step || STATE[cell(row, a.id).state] || '' }}</div>
                <div class="muted">{{ STATE[cell(row, a.id).state] || '' }}<template v-if="cell(row, a.id).score != null"> {{ $t('classProgress.local0', [cell(row, a.id).score]) }}</template>
                  <template v-if="cell(row, a.id).best != null"> {{ $t('classProgress.score') }} <b>{{ cell(row, a.id).best }}</b></template></div>
              </div>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>
        <p class="muted">{{ $t('classProgress.progressTheProportionAlreadyAchieved') }}</p>
      </div>
    </template>
    <div v-else-if="!classes.length" class="card muted">{{ $t('classProgress.noClassesYetCreateA') }}</div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { get } from '../api';

const classes = ref<any[]>([]), cid = ref<any>(null), data = ref<any>(null), busy = ref(false);
const STATE: Record<string, string> = { not_started: $t('classProgress.notStarted'), working: $t('classProgress.inProgress'), done: $t('classProgress.metLocally'), submitted: $t('classProgress.submitted') };
const FILTERS = [{ k: 'all', label: $t('classProgress.allStudents') }, { k: 'online', label: $t('common.online') }, { k: 'stuck', label: $t('common.stuck') }, { k: 'working', label: $t('classProgress.inProgress') },
  { k: 'not_started', label: $t('classProgress.notStarted') }, { k: 'submitted', label: $t('classProgress.allSubmitted') }];
const filter = ref('all');
const mins = (m: number) => (m < 1 ? $t('classProgress.lessThan1') : String(Math.round(m)));
const cell = (row: any, aid: number) => row.items?.[aid] || row.items?.[String(aid)];
const order = (r: any) => (r.stuck ? 0 : r.online ? 1 : r.state === 'not_started' ? 3 : 2);
const byOrder = (a: any, b: any) => order(a) - order(b) || String(a.username).localeCompare(String(b.username));
const shown = computed(() => (data.value?.students || []).filter((r: any) => filter.value === 'all' || (filter.value === 'online' ? r.online
  : filter.value === 'stuck' ? r.stuck : r.state === filter.value)).slice().sort(byOrder));
const rowClass = ({ row }: any) => (row.stuck ? 'stuck-row' : '');
function ago(t: string) {
  const s = (Date.now() - new Date(t.replace(' ', 'T')).getTime()) / 1000;
  return s < 90 ? $t('common.justNow') : s < 3600 ? $t('common.n0MinAgo', [Math.round(s / 60)]) : s < 86400 ? $t('common.n0HoursAgo', [Math.round(s / 3600)]) : t.slice(0, 16);
}
const seen = (r: any) => (r.online ? $t('common.online') : r.last_seen ? $t('classProgress.n0Online', [ago(r.last_seen)]) : r.last ? $t('classProgress.n0Reported', [ago(r.last)]) : $t('classProgress.clientNeverOpened'));
async function load() {
  if (!cid.value) return;
  busy.value = true;
  try { data.value = await get(`/api/teach/classes/${cid.value}/reported`); } finally { busy.value = false; }
}
let timer: any;
onMounted(async () => {
  classes.value = await get('/api/teach/classes');
  if (classes.value.length) { cid.value = classes.value[0].id; load(); }
  timer = setInterval(() => load().catch(() => null), 15000);
});
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
.sum { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 10px; }
.chip { display: flex; align-items: baseline; gap: 6px; border: 1px solid var(--el-border-color); background: var(--el-bg-color); border-radius: 8px; padding: 6px 12px; cursor: pointer; color: var(--el-text-color-regular); }
.chip b { font-size: 18px; } .chip.on { border-color: var(--el-color-primary); background: var(--el-color-primary-light-9); }
.chip.stuck b { color: var(--el-color-danger); } .chip.online b { color: var(--el-color-success); }
.who { display: flex; gap: 8px; align-items: center; } .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--el-text-color-placeholder); flex: none; }
.dot.on { background: var(--hm-run); box-shadow: 0 0 0 3px var(--hm-run-soft); }
.cur { line-height: 1.5; } .cur .el-tag { margin-right: 6px; } .cell { line-height: 1.5; } .pc-step { font-size: 12px; color: var(--el-text-color-regular); }
.muted { color: var(--hm-text-3); font-size: 12px; } .grow { flex: 1; }
:deep(.stuck-row) { background: var(--hm-fault-soft); }
</style>
