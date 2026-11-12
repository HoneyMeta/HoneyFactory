<template>
  <div class="page" v-if="d">
    <div class="page-head"><h2>{{ $t('mesNav.machiningDefectStats') }}</h2><span class="sub">{{ $t('machDefects.scrapAndReworkByMachine') }}</span><span class="grow" />
      <el-select v-model="days" style="width:120px" @change="load"><el-option v-for="x in [1, 7, 30]" :key="x" :label="$t('common.last0Days', [x])" :value="x" /></el-select>
      <el-button @click="cmmOpen = true">{{ $t('machDefects.importCmmFirstArticleData') }}</el-button></div>
    <div class="grid g2">
      <div class="card"><h3>{{ $t('machDefects.scrapAndReworkRateBy') }}</h3><Chart :option="opt" :height="300" /></div>
      <div class="card"><h3>{{ $t('machDefects.details') }}</h3>
        <el-table :data="d.machines" size="small">
          <el-table-column prop="machine" :label="$t('common.machineTool')" /><el-table-column prop="total" :label="$t('machDefects.machinedParts')" /><el-table-column prop="scrap" :label="$t('common.scrapped')" />
          <el-table-column :label="$t('heats.scrapRate')"><template #default="{ row }">{{ pct(row.scrap_rate, 2) }}</template></el-table-column>
          <el-table-column :label="$t('machDefects.reworkRate')"><template #default="{ row }">{{ pct(row.rework_rate, 1) }}</template></el-table-column>
          <el-table-column :label="$t('common.scrapReason')"><template #default="{ row }"><span class="small">{{ Object.entries(row.causes).map(([k, v]) => `${k}×${v}`).join($t('common.k360')) || '—' }}</span></template></el-table-column>
        </el-table></div>
    </div>
    <el-dialog v-model="cmmOpen" :title="$t('machDefects.importCmmFirstArticleInspection')" width="min(560px,96vw)">
      <p class="small muted">{{ $t('machDefects.eachCsvRowPartCode') }}</p>
      <el-input v-model="csv" type="textarea" :rows="8" placeholder="SH261030000123,BORE_DIA,40.012,CMM-01" />
      <template #footer><el-button type="primary" @click="importCmm">{{ $t('common.import') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { get, pct, post } from '../api';
import Chart from '../../components/Chart.vue';

const d = ref<any>(null), days = ref(7), cmmOpen = ref(false), csv = ref('');
async function load() { d.value = await get('/api/machining/defects?days=' + days.value); }
async function importCmm() { const r = await post('/api/machining/cmm_import', { csv: csv.value }); ElMessage.success($t('machDefects.imported0Parts1Values', [r.records, r.values])); cmmOpen.value = false; }
onMounted(load);
const opt = computed(() => ({ tooltip: { trigger: 'axis' }, legend: { top: 0 }, grid: { left: 50, right: 10, top: 30, bottom: 26 }, xAxis: { type: 'category', data: d.value.machines.map((m: any) => m.machine) },
  yAxis: { type: 'value', axisLabel: { formatter: (v: number) => (v * 100).toFixed(0) + '%' } },
  series: [{ name: $t('heats.scrapRate'), type: 'bar', data: d.value.machines.map((m: any) => m.scrap_rate) }, { name: $t('machDefects.reworkRate'), type: 'bar', data: d.value.machines.map((m: any) => m.rework_rate) }] }));
</script>
