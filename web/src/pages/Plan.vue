<template>
  <div class="page plan-page" v-if="v">
    <div class="page-head"><h2>{{ $t('common.productionPlan') }}</h2><span class="sub">{{ $t('plan.shiftCalendarBreaksPlannedDowntime') }}</span><span class="grow" />
      <!-- 4.7: make unapplied changes visible (previously discarded silently on navigation) -->
      <span v-if="edit && dirty" class="pl-dirty" data-k="plan-dirty"><i />{{ $t('plan.youHaveUnappliedChanges') }}</span>
      <el-button v-if="edit && dirty" size="small" data-k="plan-discard" @click="discard">{{ $t('plan.discardChanges') }}</el-button>
      <el-button v-if="edit" type="primary" :loading="busy" :disabled="!dirty" data-k="plan-apply" @click="save()">{{ $t('plan.applyPlan') }}</el-button></div>
    <!-- After applying: changes affect the running factory but are not saved to its config file (restart/reset restores the old plan) -->
    <div v-if="edit && !v.saved" class="pl-note" data-k="plan-unsaved">
      <el-icon><Warning /></el-icon><span>{{ $t('plan.appliedToTheRunningFactory') }}<b>{{ $t('plan.notYetSavedToThe') }}</b>{{ $t('plan.resettingOrRestartingTheFactory') }}</span><span class="grow" />
      <el-button size="small" type="primary" plain :loading="saving" :disabled="dirty" :title="dirty ? $t('plan.applyOrDiscardTheChanges') : ''" data-k="plan-save" @click="saveCfg">{{ $t('plan.saveToFactoryConfiguration') }}</el-button></div>
    <div v-else-if="edit && justSaved" class="pl-note ok" data-k="plan-saved"><el-icon><CircleCheck /></el-icon><span>{{ $t('plan.thePlanHasBeenSaved') }}</span></div>
    <div class="grid g4">
      <div class="kpi"><small>{{ $t('plan.currentShift') }}</small><b style="font-size:18px">{{ v.off || v.shift }}</b><i>{{ v.break ? $t('plan.onBreak') + v.break : '' }}</i></div>
      <div class="kpi"><small>{{ $t('plan.currentProduct') }}</small><b style="font-size:18px">{{ v.product.code }}</b><i>{{ $t('plan.cycleTimeFactor0', [v.product.cycle_factor]) }}</i></div>
      <div class="kpi"><small>{{ $t('plan.currentOrder') }}</small><b style="font-size:18px">{{ v.order || $t('common.none') }}</b></div>
      <div class="kpi"><small>{{ $t('plan.throughputOverLast4Hours') }}</small><b>{{ v.rate_per_h }}</b><i>{{ $t('plan.pcsHourUsedToPredict') }}</i></div>
    </div>
    <div class="card" style="margin-top:14px"><h3>{{ $t('common.order') }} <small>{{ $t('plan.ordersRunInSequenceProduction') }}</small><span class="grow" />
      <el-button v-if="edit" size="small" @click="c.orders.push({ code: 'SO-' + (c.orders.length + 1).toString().padStart(3, '0'), product: c.products[0].code, qty: 300, due: '', customer: '' })">{{ $t('plan.order') }}</el-button></h3>
      <el-table :data="c.orders" size="small">
        <el-table-column :label="$t('plan.orderNo')" width="120"><template #default="{ row }"><el-input v-model="row.code" size="small" /></template></el-table-column>
        <el-table-column :label="$t('common.product')" width="140"><template #default="{ row }"><el-select v-model="row.product" size="small"><el-option v-for="p in c.products" :key="p.code" :label="p.code" :value="p.code" /></el-select></template></el-table-column>
        <el-table-column :label="$t('plan.quantity')" width="100"><template #default="{ row }"><el-input-number v-model="row.qty" size="small" :min="1" :controls="false" style="width:80px" /></template></el-table-column>
        <el-table-column :label="$t('ganttChart.dueDate')" width="200"><template #default="{ row }"><el-date-picker v-model="row.due" type="datetime" size="small" value-format="YYYY-MM-DD HH:mm" style="width:180px" /></template></el-table-column>
        <el-table-column :label="$t('plan.customer')"><template #default="{ row }"><el-input v-model="row.customer" size="small" /></template></el-table-column>
        <el-table-column :label="$t('plan.progress')" width="180"><template #default="{ row }"><el-progress :percentage="Math.min(100, Math.round((st(row.code).done || 0) / row.qty * 100))" :format="() => `${st(row.code).done || 0}/${row.qty}`" /></template></el-table-column>
        <el-table-column :label="$t('plan.estCompletion')" width="150"><template #default="{ row }"><span :class="st(row.code).late ? 'bad' : ''">{{ st(row.code).eta || '—' }}</span></template></el-table-column>
        <el-table-column width="50"><template #default="{ $index }"><el-button v-if="edit" link type="danger" @click="c.orders.splice($index, 1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
      </el-table></div>
    <div class="grid g2" style="margin-top:14px">
      <div class="card"><h3>{{ $t('common.product') }} <span class="grow" /><el-button v-if="edit" size="small" @click="c.products.push({ code: 'NEW', name: $t('plan.newProduct'), cycle_factor: 1, changeover_min: 30 })">{{ $t('plan.product') }}</el-button></h3>
        <el-table :data="c.products" size="small">
          <el-table-column :label="$t('opsApp.code')"><template #default="{ row }"><el-input v-model="row.code" size="small" /></template></el-table-column>
          <el-table-column :label="$t('common.name')"><template #default="{ row }"><el-input v-model="row.name" size="small" /></template></el-table-column>
          <el-table-column :label="$t('plan.machiningCycleTimeFactor')" width="110"><template #default="{ row }"><el-input-number v-model="row.cycle_factor" size="small" :step="0.05" :controls="false" style="width:80px" /></template></el-table-column>
          <el-table-column :label="$t('plan.changeoverMin')" width="90"><template #default="{ row }"><el-input-number v-model="row.changeover_min" size="small" :controls="false" style="width:70px" /></template></el-table-column>
        </el-table></div>
      <div class="card"><h3>{{ $t('plan.shiftsWorkingDays') }} <span class="grow" /><el-button v-if="edit" size="small" @click="c.shifts.push({ name: $t('plan.newShift'), start: '08:00', end: '16:00' })">{{ $t('plan.shift') }}</el-button></h3>
        <p class="small muted">{{ $t('plan.noShifts247Production') }}</p>
        <div v-for="(s, i) in c.shifts" :key="i" class="r"><el-input v-model="s.name" size="small" style="width:90px" />
          <el-time-select v-model="s.start" start="00:00" step="00:30" end="23:30" size="small" style="width:110px" />–<el-time-select v-model="s.end" start="00:00" step="00:30" end="23:30" size="small" style="width:110px" />
          <el-button link type="danger" @click="c.shifts.splice(i, 1)"><el-icon><Delete /></el-icon></el-button></div>
        <div style="margin-top:8px"><el-checkbox-group v-model="c.workdays"><el-checkbox v-for="(n, i) in [$t('planView.n1'), $t('planView.n2'), $t('planView.n3'), $t('planView.n4'), $t('planView.n5'), $t('plan.sat'), $t('plan.sun')]" :key="i" :value="i + 1">{{ $t('plan.day0', [n]) }}</el-checkbox></el-checkbox-group></div>
        <h3 style="margin-top:14px">{{ $t('view3DHover.resting') }} <span class="grow" /><el-button v-if="edit" size="small" @click="c.breaks.push({ name: $t('view3DHover.resting'), start: '11:30', end: '12:00' })">{{ $t('plan.break') }}</el-button></h3>
        <p class="small muted">{{ $t('plan.operatorsLeaveTheirStationsDuring') }}</p>
        <div v-for="(s, i) in c.breaks" :key="i" class="r"><el-input v-model="s.name" size="small" style="width:90px" />
          <el-time-select v-model="s.start" start="00:00" step="00:15" end="23:45" size="small" style="width:110px" />–<el-time-select v-model="s.end" start="00:00" step="00:15" end="23:45" size="small" style="width:110px" />
          <el-button link type="danger" @click="c.breaks.splice(i, 1)"><el-icon><Delete /></el-icon></el-button></div>
      </div>
    </div>
    <div class="card" style="margin-top:14px"><h3>{{ $t('common.plannedDowntime') }} <small>{{ $t('plan.forMaintenanceOverhaulsEtcEquipment') }}</small><span class="grow" />
      <el-button v-if="edit" size="small" @click="c.downtime.push({ station: stations[0]?.id, start: '', hours: 2, reason: $t('plan.plannedMaintenance') })">{{ $t('plan.plannedDowntime') }}</el-button></h3>
      <el-table :data="c.downtime" size="small">
        <el-table-column :label="$t('common.equipment')" width="200"><template #default="{ row }"><el-select v-model="row.station" size="small" filterable><el-option v-for="s in stations" :key="s.id" :label="`${s.id} ${s.name}`" :value="s.id" /></el-select></template></el-table-column>
        <el-table-column :label="$t('common.start')" width="210"><template #default="{ row }"><el-date-picker v-model="row.start" type="datetime" size="small" value-format="YYYY-MM-DD HH:mm" style="width:190px" /></template></el-table-column>
        <el-table-column :label="$t('plan.durationH')" width="100"><template #default="{ row }"><el-input-number v-model="row.hours" size="small" :min="0.25" :step="0.5" :controls="false" style="width:70px" /></template></el-table-column>
        <el-table-column :label="$t('common.reason')"><template #default="{ row }"><el-input v-model="row.reason" size="small" /></template></el-table-column>
        <el-table-column :label="$t('common.status')" width="90"><template #default="{ row }"><span v-if="v.station_off[row.station]" class="tag-st st-Planned">{{ $t('common.inProgress') }}</span></template></el-table-column>
        <el-table-column width="50"><template #default="{ $index }"><el-button v-if="edit" link type="danger" @click="c.downtime.splice($index, 1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
      </el-table>
      <p class="small muted">{{ $t('plan.afterEditingClickApplyPlan') }}</p></div>

    <!-- 4.7: unapplied changes on navigation, floating panel close, or workspace switch -->
    <el-dialog v-model="ask.open" :title="$t('plan.productionPlanNotYetApplied')" width="440px" append-to-body :close-on-click-modal="false" data-k="plan-leave" @closed="answer('stay')">
      <p style="margin:0">{{ $t('plan.youChangedThePlanBut') }}</p>
      <template #footer>
        <el-button data-k="plan-leave-stay" @click="answer('stay')">{{ $t('plan.continueEditing') }}</el-button>
        <el-button type="danger" plain data-k="plan-leave-discard" @click="answer('discard')">{{ $t('plan.discardChanges') }}</el-button>
        <el-button type="primary" :loading="busy" data-k="plan-leave-apply" @click="answer('apply')">{{ $t('plan.applyPlan') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router';
import { canEdit, get, P, post, put } from '../api';
import { floatGuards } from '../editor/store';

const props = defineProps<{ pid: string }>();
const api = P(props.pid), edit = canEdit();
const v = ref<any>(null), c = ref<any>(null), busy = ref(false), saving = ref(false), justSaved = ref(false), stations = ref<any[]>([]);
const st = (code: string) => v.value.orders.find((o: any) => o.code === code) || {};
const KEYS = ['shifts', 'workdays', 'breaks', 'downtime', 'products', 'orders'];
/** Compare editable content only (order progress and null representations do not count as changes). */
function norm(x: any) {
  if (!x) return '';
  const drop = new Set(['done', 'born', 'left', 'eta', 'late']);
  return JSON.stringify(KEYS.map((k) => x[k] ?? []), (key, val) => (drop.has(key) ? undefined : val === null || val === undefined ? '' : val));
}
const base = ref('');
const dirty = computed(() => !!c.value && edit && norm(c.value) !== base.value);
function adopt(r: any) { v.value = r; c.value = JSON.parse(JSON.stringify(r.cfg)); base.value = norm(c.value); }
async function load() { adopt(await get(api + '/plan')); }
async function save(quiet = false) {
  busy.value = true;
  try { adopt(await put(api + '/plan', c.value)); justSaved.value = false; if (!quiet) ElMessage.success(v.value.saved ? $t('plan.planIsNowActive') : $t('plan.thePlanHasBeenApplied')); return true; }
  catch { return false; } finally { busy.value = false; }
}
function discard() { c.value = JSON.parse(JSON.stringify(v.value.cfg)); base.value = norm(c.value); }
async function saveCfg() {
  saving.value = true;
  try { adopt(await post(api + '/plan/save', {})); justSaved.value = true; ElMessage.success($t('plan.planSavedToTheFactory')); } finally { saving.value = false; }
}

// ---------- Leave confirmation: routing (page/factory switch), floating panel close, workspace switch, reload/window close ----------
const ask = reactive<{ open: boolean; done: ((a: string) => void) | null }>({ open: false, done: null });
function answer(a: string) { const d = ask.done; ask.done = null; ask.open = false; d?.(a); }
/** Prompt for unapplied changes: Apply / Discard / Keep Editing. Returns true if leaving is allowed. */
async function confirmLeave(): Promise<boolean> {
  if (!dirty.value) return true;
  const a = await new Promise<string>((res) => { ask.done = res; ask.open = true; });
  if (a === 'apply') return save(true);
  if (a === 'discard') { discard(); return true; }
  return false;
}
onBeforeRouteLeave(() => confirmLeave());
onBeforeRouteUpdate((to, from) => (to.params.pid !== from.params.pid ? confirmLeave() : true));
function onUnload(e: BeforeUnloadEvent) { if (dirty.value) { e.preventDefault(); e.returnValue = ''; } }
const FLOAT_ID = 'plan';                  // Workbench "Production Plan" floating panel (editor/shell/panels.ts)
onMounted(async () => {
  addEventListener('beforeunload', onUnload);
  floatGuards.set(FLOAT_ID, confirmLeave);
  load(); stations.value = (await get(api + '/meta')).stations.filter((s: any) => !['crew', 'agv'].includes(s.kind));
});
onBeforeUnmount(() => { removeEventListener('beforeunload', onUnload); if (floatGuards.get(FLOAT_ID) === confirmLeave) floatGuards.delete(FLOAT_ID); });
(window as any).__vfPlan = { dirty: () => dirty.value };   // For UI tests
</script>

<style scoped>
.r { display: flex; gap: 6px; align-items: center; margin-bottom: 6px; }
.pl-dirty { display: inline-flex; align-items: center; gap: 6px; color: var(--warn); font-weight: 600; font-size: 12.5px; }
.pl-dirty i { width: 8px; height: 8px; border-radius: 50%; background: var(--warn); box-shadow: 0 0 0 3px var(--hm-idle-soft); }
.pl-note { display: flex; align-items: center; gap: 8px; margin: -2px 0 12px; padding: 8px 12px; border-radius: 8px; font-size: 12.5px;
  background: var(--hm-idle-soft); color: var(--hm-idle-ink); border: 1px solid rgba(217, 154, 22, .35); flex-wrap: wrap; }
.pl-note.ok { background: var(--hm-run-soft); color: var(--hm-run-ink); border-color: rgba(21, 163, 74, .3); }
</style>
