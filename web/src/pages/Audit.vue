<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('common.auditLog') }}</h2><span class="sub">{{ $t('audit.allActionsThatModifyData') }}</span><span class="grow" />
      <el-input v-model="q" :placeholder="$t('audit.searchUsersOrPaths')" clearable style="width:220px" @change="load" /></div>
    <div class="card"><el-table :data="rows" size="small" height="calc(100vh - 170px)">
      <el-table-column prop="t" :label="$t('common.time')" width="160" /><el-table-column prop="username" :label="$t('audit.users')" width="180" />
      <el-table-column :label="$t('common.actions')" min-width="160"><template #default="{ row }">{{ desc(row) }}</template></el-table-column>
      <el-table-column prop="method" :label="$t('audit.method')" width="80" /><el-table-column prop="path" :label="$t('audit.path')" min-width="240" show-overflow-tooltip />
      <el-table-column :label="$t('entityPage.result')" width="80"><template #default="{ row }"><span :class="row.status < 400 ? 'ok' : 'bad'">{{ row.status }}</span></template></el-table-column>
      <el-table-column prop="ip" :label="$t('audit.source')" width="120" /></el-table></div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { onMounted, ref } from 'vue';
import { get } from '../api';

const rows = ref<any[]>([]), q = ref('');
const MAP: [RegExp, string][] = [[/login$/, $t('common.signIn')], [/\/sim$/, $t('audit.simulationControl')], [/\/advance$/, $t('audit.fastForward')], [/\/restart$/, $t('audit.resetRestart')], [/\/save$/, $t('audit.saveLayout')], [/\/fault$/, $t('common.injectFailure')],
  [/\/write$/, $t('common.writeSetpoint')], [/\/enable$/, $t('audit.startStopEquipment')], [/scenarios\/run$/, $t('audit.runScenario')], [/scenarios\/stop$/, $t('audit.stopScenario')], [/scenarios/, $t('audit.editScenario')], [/experiments/, $t('assistantDock.experiment')],
  [/\/plan$/, $t('audit.modifyPlan')], [/signals\/comm$/, $t('audit.communicationFailure')], [/signals\/record$/, $t('audit.recording')], [/signals\/replay$/, $t('common.replay')], [/\/station/, $t('audit.editEquipment')], [/\/plant$/, $t('audit.modifyFactory')],
  [/tokens/, $t('common.apiTokens')], [/users/, $t('audit.userManagement')], [/\/api\/plants/, $t('audit.createDeleteFactory')]];
const desc = (r: any) => MAP.find(([re]) => re.test(r.path))?.[1] || '';
async function load() { rows.value = await get('/api/admin/audit?q=' + encodeURIComponent(q.value)); }
onMounted(load);
</script>
