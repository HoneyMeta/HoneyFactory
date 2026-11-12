<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('mesNav.systemStatus') }}</h2></div>
    <div class="grid g2">
      <div class="card"><h3>{{ $t('system.dataCollection') }}</h3>
        <p class="small">{{ $t('system.dataClock') }}<b class="mono">{{ c?.now }}</b></p>
        <el-table :data="ds" size="small"><el-table-column prop="code" :label="$t('system.dataSource')" /><el-table-column prop="name" :label="$t('common.name')" /><el-table-column prop="protocol" :label="$t('common.protocol')" />
          <el-table-column prop="endpoint" :label="$t('common.address')" /><el-table-column prop="status" :label="$t('common.status')" /></el-table>
        <p class="small muted">{{ $t('system.received0PartEventsAnd', [c?.stats.part_events || 0, c?.stats.events || 0]) }}</p></div>
      <div class="card"><h3>{{ $t('system.about') }}</h3>
        <p class="small"><b>{{ $t('common.teachingMes') }}</b>{{ $t('system.teachingMesIncludedWithHoneyfactory', [mes.st?.plant_name || mes.st?.pid || $t('mesStart.localFactories')]) }}</p>
        <p class="small muted">{{ $t('system.startedOnDemandByThe') }}</p>
        <p class="small muted">{{ $t('system.moduleOrganizationAndDataStructures') }}</p></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { get, mes } from '../api';

const c = ref<any>(null), ds = ref<any[]>([]);
onMounted(async () => { c.value = await get('/api/collector'); ds.value = (await get('/api/e/datasource')).items; });
</script>
