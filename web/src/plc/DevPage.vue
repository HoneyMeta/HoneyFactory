<template>
  <!-- PLC module self-test page: mimic the Workbench .ed shell (light theme only), sidebar + main area. URL params: pid, view=workbench|side|hmi|ext|all -->
  <div class="ed devp">
    <div v-if="!ready" class="pad">{{ $t('devPage.signingInVfTokenMust') }}</div>
    <template v-else>
      <div class="dv-bar plc-root"><b>{{ $t('devPage.plcDevelopment') }}</b><span class="muted">{{ $t('devPage.factory0', [pid]) }}</span><span class="grow" />
        <button v-for="v in VIEWS" :key="v" class="plc-btn" :class="{ pri: view === v }" @click="view = v">{{ v }}</button></div>
      <div class="dv-main">
        <aside v-if="view === 'all' || view === 'side' || view === 'ext'" class="dv-side">
          <PlcSide v-if="view !== 'ext'" :pid="pid" />
          <ExternalPanel v-else :pid="pid" />
        </aside>
        <main class="dv-body">
          <PlcWorkbench v-if="view === 'all' || view === 'workbench' || view === 'side'" :pid="pid" />
          <HmiPanel v-else-if="view === 'hmi'" :pid="pid" />
          <PlcWorkbench v-else :pid="pid" />
        </main>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import './plc.css';
import { onMounted, ref } from 'vue';
import { loadSession } from '../api';
import { ed } from '../editor/store';
import ExternalPanel from './ExternalPanel.vue';
import HmiPanel from './HmiPanel.vue';
import PlcSide from './PlcSide.vue';
import PlcWorkbench from './PlcWorkbench.vue';

const q = new URLSearchParams(location.search);
const pid = q.get('pid') || 'foundry-housing';
const VIEWS = ['all', 'workbench', 'side', 'hmi', 'ext'];
const view = ref(q.get('view') || 'all');
ed.pid = pid;
const ready = ref(false);
onMounted(async () => { await loadSession(); ready.value = true; });
</script>

<style>
.devp { position: fixed; inset: 0; display: flex; flex-direction: column; }
.dv-bar { display: flex; align-items: center; gap: 10px; height: 38px; padding: 0 12px; background: var(--hm-glass-strong, #fff); border-bottom: 1px solid var(--ln); }
.dv-main { flex: 1; min-height: 0; display: flex; }
.dv-side { width: 340px; flex: none; border-right: 1px solid var(--ln); min-height: 0; }
.dv-body { flex: 1; min-width: 0; min-height: 0; }
.pad { padding: 20px; }
</style>
