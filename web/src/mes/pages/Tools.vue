<template>
  <div class="page" v-if="d">
    <div class="page-head"><h2>{{ $t('mesNav.toolLife') }}</h2><span class="sub">{{ $t('tools.toolLifeIsTrackedBy') }}</span></div>
    <div class="grid g4">
      <div class="kpi"><small>{{ $t('tools.tools') }}</small><b>{{ d.tools.length }}</b></div>
      <div class="kpi warn"><small>{{ $t('hmStatus.warning') }}</small><b>{{ d.tools.filter((t: any) => t.status === 'warn').length }}</b></div>
      <div class="kpi bad"><small>{{ $t('tools.dueForChange') }}</small><b>{{ d.tools.filter((t: any) => t.status === 'change').length }}</b></div>
      <div class="kpi"><small>{{ $t('tools.breakagesLast7Days') }}</small><b>{{ d.changes.filter((c: any) => c.reason === 'broken').reduce((a: number, c: any) => a + c.n, 0) }}</b></div>
    </div>
    <div class="card" style="margin-top:14px">
      <el-table :data="d.tools" size="small" max-height="440">
        <el-table-column prop="equipment__label" :label="$t('common.machineTool')" width="130" /><el-table-column prop="code" :label="$t('tools.toolPos')" width="60" /><el-table-column prop="name" :label="$t('tools.tool')" />
        <el-table-column :label="$t('tools.lifeCount')" width="220"><template #default="{ row }"><el-progress :percentage="Math.min(100, Math.round(row.life_pct || 0))"
          :status="row.status === 'change' ? 'exception' : row.status === 'warn' ? 'warning' : 'success'" :format="() => `${row.used || 0}/${row.life_limit || '—'}`" /></template></el-table-column>
        <el-table-column :label="$t('common.status')" width="80"><template #default="{ row }"><span class="tag-st" :class="'st-' + row.status">{{ ST[row.status] }}</span></template></el-table-column>
        <el-table-column prop="changes" :label="$t('common.toolChange')" width="60" />
        <el-table-column prop="last_change" :label="$t('tools.lastToolChange')" width="150" />
      </el-table>
    </div>
    <div class="card" style="margin-top:14px"><h3>{{ $t('tools.toolChangesInLast7') }} <small>{{ $t('tools.byMachineToolPositionReason') }}</small></h3>
      <el-table :data="d.changes" size="small" max-height="300">
        <el-table-column prop="equipment__label" :label="$t('common.machineTool')" width="130" /><el-table-column prop="tool" :label="$t('tools.toolPos')" width="70" />
        <el-table-column :label="$t('common.reason')" width="90"><template #default="{ row }">{{ R[row.reason] || row.reason }}</template></el-table-column>
        <el-table-column prop="n" :label="$t('tools.count')" width="70" /><el-table-column :label="$t('tools.averagePartsProcessed')"><template #default="{ row }">{{ fmt(row.avg_used, 0) }}</template></el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { onMounted, ref } from 'vue';
import { fmt, get } from '../api';

const d = ref<any>(null);
const ST: Record<string, string> = { ok: $t('common.normal'), warn: $t('hmStatus.warning'), change: $t('tools.dueForChange') };
const R: Record<string, string> = { life: $t('entityPage.endOfLife'), broken: $t('entityPage.toolBreakage'), manual: $t('entityPage.manual') };
onMounted(async () => { d.value = await get('/api/machining/tools'); });
</script>
