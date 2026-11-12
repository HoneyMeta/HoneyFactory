<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('common.stock') }}</h2><span class="sub">{{ $t('stock.theSystemAutomaticallyPostsCharge') }}</span><span class="grow" />
      <el-button @click="router.push('/mes/e/stock_txn')">{{ $t('mesNav.inventoryTransactions') }}</el-button><el-button type="primary" @click="countOpen = true">{{ $t('stock.cycleCount') }}</el-button></div>
    <div class="card">
      <el-table :data="rows" size="small">
        <el-table-column prop="warehouse__label" :label="$t('stock.warehouse')" /><el-table-column prop="material__label" :label="$t('common.material')" />
        <el-table-column :label="$t('common.stock')" align="right"><template #default="{ row }"><b class="mono" :class="row.low ? 'bad' : ''">{{ fmt(row.qty, 2) }}</b> {{ row.unit }}</template></el-table-column>
        <el-table-column :label="$t('stock.safetyStock')" align="right"><template #default="{ row }">{{ row.safety ?? '—' }}</template></el-table-column>
        <el-table-column label="" width="90"><template #default="{ row }"><span v-if="row.low" class="tag-st st-NG">{{ $t('stock.belowSafetyStock') }}</span></template></el-table-column>
      </el-table>
    </div>
    <el-dialog v-model="countOpen" :title="$t('stock.cycleCount')" width="min(560px,96vw)">
      <el-form label-width="80px"><el-form-item :label="$t('stock.warehouse')"><RefSelect v-model="cnt.warehouse" entity="warehouse" /></el-form-item></el-form>
      <el-table :data="cntRows" size="small">
        <el-table-column prop="material__label" :label="$t('common.material')" /><el-table-column :label="$t('stock.book')"><template #default="{ row }">{{ fmt(row.qty, 2) }}</template></el-table-column>
        <el-table-column :label="$t('stock.counted')"><template #default="{ row }"><el-input-number v-model="row.actual" :controls="false" style="width:110px" /></template></el-table-column>
      </el-table>
      <template #footer><el-button type="primary" @click="doCount">{{ $t('stock.postCountAdjustment') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { fmt, get, post } from '../api';
import RefSelect from '../components/RefSelect.vue';

const router = useRouter(), rows = ref<any[]>([]), countOpen = ref(false), cnt = reactive<any>({ warehouse: null });
const cntRows = ref<any[]>([]);
watch(() => cnt.warehouse, (w) => { cntRows.value = rows.value.filter((r) => r.warehouse === w).map((r) => ({ ...r, actual: +(r.qty || 0).toFixed(3) })); });
async function load() { rows.value = await get('/api/warehouse/overview'); }
async function doCount() {
  const r = await post('/api/warehouse/count', { warehouse: cnt.warehouse, lines: cntRows.value.map((x) => ({ material: x.material, actual: x.actual })) });
  ElMessage.success($t('stock.n0ItemsAdjusted', [r.adjusted])); countOpen.value = false; load();
}
onMounted(load);
</script>
