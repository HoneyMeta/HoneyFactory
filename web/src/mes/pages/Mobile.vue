<template>
  <div class="page mob-page">
    <div class="page-head"><h2>{{ $t('mobile.mobile') }}</h2><span class="sub">{{ $t('mobile.scanToReportProductionView') }}</span></div>
  <div class="mob" data-k="mes-mobile">
    <header><img src="/brand/logo-mark-64.png" :alt="$t('common.honey')" /><b>{{ $t('common.teachingMes') }}</b><span class="grow" /><span class="small">{{ mes.user?.name }}</span>
      <el-button text size="small" @click="router.push('/mes')">{{ $t('mobile.desktop') }}</el-button></header>
    <el-tabs v-model="tab" stretch>
      <el-tab-pane :label="$t('mobile.scanToReport')" name="scan">
        <div class="box">
          <el-input v-model="sn" :placeholder="$t('mobile.scanPartCodeEnterManually')" size="large" clearable @keyup.enter="lookup"><template #append><el-button @click="lookup">{{ $t('mobile.search') }}</el-button></template></el-input>
          <div v-if="part" class="pc"><b>{{ part.part.sn }}</b> · {{ part.part.station }} · {{ part.part.status }}<br><span class="small muted">{{ $t('mobile.workOrder0Heat1', [part.part.work_order__label || '—', part.part.heat || '—']) }}</span></div>
          <el-form label-position="top" style="margin-top:10px">
            <el-form-item :label="$t('mesNav.operation')"><el-select v-model="rp.process" style="width:100%"><el-option v-for="p in procs" :key="p.id" :label="p.name" :value="p.id" /></el-select></el-form-item>
            <div class="row2"><el-form-item :label="$t('common.good')"><el-input-number v-model="rp.qty_good" :min="0" /></el-form-item><el-form-item :label="$t('mobile.defective')"><el-input-number v-model="rp.qty_ng" :min="0" /></el-form-item></div>
            <el-form-item v-if="rp.qty_ng" :label="$t('mobile.defect')"><el-select v-model="rp.defect" style="width:100%"><el-option v-for="x in defects" :key="x.id" :label="x.name" :value="x.id" /></el-select></el-form-item>
          </el-form>
          <el-button type="primary" size="large" style="width:100%" :disabled="!sn" @click="report">{{ $t('mobile.report') }}</el-button>
        </div>
      </el-tab-pane>
      <el-tab-pane :label="$t('mobile.myTasks')" name="task">
        <div v-for="o in tasks" :key="o.id" class="task">
          <div><b>{{ o.work_order__label }}</b> · {{ o.process_name }} <span class="tag-st" :class="'st-' + o.status">{{ OS[o.status] }}</span></div>
          <div class="small muted">{{ o.station_group }} · {{ o.qty_good || 0 }}/{{ o.qty_plan }} · {{ o.mode === 'auto' ? $t('mobile.machineAutoReporting') : $t('mobile.manualReporting') }}</div>
          <div v-if="o.mode !== 'auto'" style="margin-top:6px"><el-input-number v-model="o._n" :min="1" size="small" /> <el-button size="small" type="primary" @click="reportOp(o)">{{ $t('mobile.reportGood') }}</el-button></div>
        </div>
        <p v-if="!tasks.length" class="muted box">{{ $t('mobile.noPendingTasks') }}</p>
      </el-tab-pane>
      <el-tab-pane :label="$t('mobile.requestRepair')" name="rep">
        <div class="box"><el-form label-position="top">
          <el-form-item :label="$t('common.equipment')"><el-select v-model="rep.equipment" filterable style="width:100%"><el-option v-for="e in eqs" :key="e.id" :label="`${e.code} ${e.name}`" :value="e.id" /></el-select></el-form-item>
          <el-form-item :label="$t('mobile.faultDescription')"><el-input v-model="rep.fault" type="textarea" :rows="3" /></el-form-item>
          <el-form-item :label="$t('mobile.urgency')"><el-radio-group v-model="rep.level"><el-radio-button value="normal">{{ $t('mobile.marginal') }}</el-radio-button><el-radio-button value="urgent">{{ $t('mobile.urgent') }}</el-radio-button></el-radio-group></el-form-item>
        </el-form><el-button type="danger" size="large" style="width:100%" @click="repair">{{ $t('mobile.submitRepairRequest') }}</el-button></div>
      </el-tab-pane>
      <el-tab-pane :label="$t('mobile.checks')" name="spot">
        <div v-for="m in due" :key="m.id" class="task"><b>{{ m.name }}</b><div class="small muted">{{ m.items }}</div>
          <div style="margin-top:6px"><el-button size="small" type="primary" @click="spot(m, 'ok')">{{ $t('common.normal') }}</el-button><el-button size="small" type="danger" plain @click="spot(m, 'abnormal')">{{ $t('common.abnormal') }}</el-button></div></div>
        <p v-if="!due.length" class="box ok">{{ $t('mobile.allOfTodaySChecks') }}</p>
      </el-tab-pane>
    </el-tabs>
  </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, mes, post } from '../api';

const router = useRouter(), tab = ref('scan');
const sn = ref(''), part = ref<any>(null), procs = ref<any[]>([]), defects = ref<any[]>([]), tasks = ref<any[]>([]), eqs = ref<any[]>([]), due = ref<any[]>([]);
const rp = reactive<any>({ process: null, qty_good: 1, qty_ng: 0, defect: null }), rep = reactive<any>({ equipment: null, fault: '', level: 'normal' });
const OS: Record<string, string> = { waiting: $t('mobile.waitingToStart'), ready: $t('mobile.readyToStart'), running: $t('common.inProgress'), done: $t('common.done') };
async function lookup() { try { part.value = await get('/api/trace/part/' + encodeURIComponent(sn.value.trim())); } catch { part.value = null; } }
async function report() {
  await post('/api/production/report', { sn: sn.value.trim(), process: rp.process, qty_good: rp.qty_good, qty_ng: rp.qty_ng, defect: rp.defect, mobile: true });
  ElMessage.success($t('mobile.reported')); sn.value = ''; part.value = null;
}
async function reportOp(o: any) { await post('/api/production/report', { wo_op: o.id, qty_good: o._n || 1, mobile: true }); ElMessage.success($t('mobile.reported')); loadTasks(); }
async function repair() {
  if (!rep.equipment || !rep.fault) { ElMessage.warning($t('mobile.selectAMachineAndDescribe')); return; }
  await post('/api/e/repair_order', { ...rep, reported_by: mes.user?.name, reported_at: null }); ElMessage.success($t('mobile.repairRequestedTheMaintenanceTechnic')); rep.fault = '';
}
async function spot(m: any, result: string) {
  const notes = result === 'abnormal' ? (await ElMessageBox.prompt($t('mobile.abnormalityDescription'), m.name)).value : '';
  const r = await post(`/api/e/maint_plan/${m.id}/do/execute`, { result, notes }); ElMessage.success(r.msg || $t('maint.recorded')); due.value = await get('/api/equipment/maint_due');
}
async function loadTasks() { tasks.value = (await get('/api/production/my_tasks')).map((o: any) => ({ ...o, _n: 1 })); }
onMounted(async () => {
  procs.value = (await get('/api/e/process?size=50&sort=code')).items; defects.value = (await get('/api/e/defect_code?size=50&sort=code')).items;
  eqs.value = (await get('/api/e/equipment?size=100&sort=code')).items; due.value = await get('/api/equipment/maint_due'); loadTasks();
});
</script>

<style scoped>
.mob { max-width: 440px; background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: 18px; box-shadow: var(--hm-e2); overflow: hidden; min-height: 640px; }
header { display: flex; align-items: center; gap: 8px; background: var(--hm-surface); color: var(--hm-text); padding: 10px 12px; border-bottom: 1px solid var(--hm-border); }
header img { height: 26px; } header b { font-size: var(--hm-fs-md); } .grow { flex: 1; }
.mob :deep(.el-tabs__header) { margin: 0; padding: 0 8px; }
.box { padding: 12px; } .pc { margin-top: 8px; background: var(--hm-primary-soft); color: var(--hm-text); border-radius: var(--hm-r-md); padding: 8px 10px; font-size: var(--hm-fs-sm); }
.row2 { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; } .task { padding: 10px 12px; border-bottom: 1px solid var(--hm-border); color: var(--hm-text); }
</style>
