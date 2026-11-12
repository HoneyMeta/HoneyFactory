<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('mesNav.checksPm') }}</h2><span class="sub">{{ $t('maint.dueAndOverdueInspectionRounds') }}</span><span class="grow" />
      <el-button @click="router.push('/mes/e/maint_plan')">{{ $t('maint.plannedMaintenance') }}</el-button><el-button @click="router.push('/mes/e/maint_record')">{{ $t('maint.executionRecords') }}</el-button></div>
    <div class="card">
      <el-table :data="rows" size="small">
        <el-table-column prop="code" :label="$t('common.plan')" width="160" /><el-table-column prop="name" :label="$t('common.name')" />
        <el-table-column prop="equipment__label" :label="$t('common.equipment')" /><el-table-column :label="$t('common.type')" width="90"><template #default="{ row }">{{ MT[row.mtype] }}</template></el-table-column>
        <el-table-column prop="items" :label="$t('common.content')" min-width="220" show-overflow-tooltip />
        <el-table-column :label="$t('maint.expires')" width="110"><template #default="{ row }"><span :class="row.overdue_days > 0 ? 'bad' : ''">{{ row.next_due || $t('maint.unscheduled') }}{{ row.overdue_days > 0 ? $t('maint.overdueBy0Days', [row.overdue_days]) : '' }}</span></template></el-table-column>
        <el-table-column label="" width="150"><template #default="{ row }">
          <el-button size="small" type="primary" @click="exec(row, 'ok')">{{ $t('common.normal') }}</el-button><el-button size="small" type="danger" plain @click="exec(row, 'abnormal')">{{ $t('common.abnormal') }}</el-button></template></el-table-column>
      </el-table>
      <p v-if="!rows.length" class="ok">{{ $t('maint.noInspectionRoundsOrPm') }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { get, post } from '../api';

const router = useRouter(), rows = ref<any[]>([]);
const MT: Record<string, string> = { spot: $t('maint.dailyInspectionRounds'), maint: $t('maint.periodicPm'), lube: $t('maint.lubrication') };
async function load() { rows.value = await get('/api/equipment/maint_due'); }
async function exec(r: any, result: string) {
  let notes = '';
  if (result === 'abnormal') notes = (await ElMessageBox.prompt($t('maint.abnormalityDetails'), r.name)).value;
  const res = await post(`/api/e/maint_plan/${r.id}/do/execute`, { result, notes });
  ElMessage.success(res.msg || $t('maint.recorded')); load();
}
onMounted(load);
</script>
