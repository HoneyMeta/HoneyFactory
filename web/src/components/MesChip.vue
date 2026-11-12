<template>
  <!-- Desktop client: when local MES is running, show a small badge at bottom left on pages without a sidebar (Workbench); click to return to MES Home (4.6, vfactory/mes/sidecar.py; 5.0.1 MES pages use /mes/...) -->
  <div v-if="show" class="mes-chip" data-k="mes-chip" :title="$t('mesChip.localMesIsRunning0', [mes?.plant_name])" @click="router.push('/mes')">
    <i class="pd" /><el-icon><Tickets /></el-icon><span>MES · {{ mes?.plant_name }}</span>
    <el-icon class="x" :title="$t('mesChip.hideForNow')" @click.stop="hidden = true"><Close /></el-icon>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { desk, refreshDesk } from '../api';

const route = useRoute(), router = useRouter();
const hidden = ref(false);
const mes = computed(() => desk.mes);
// Hide on pages with a sidebar (Layout top bar already has a badge) and MES pages; show only on full-page views such as the Workbench
const show = computed(() => desk.on && !hidden.value && mes.value?.state === 'running' && /^\/p\/[^/]+\/workbench/.test(route.path));
let t: any;
onMounted(() => { t = setInterval(() => { if (desk.on && /^\/p\/[^/]+\/workbench/.test(route.path)) refreshDesk(); }, 8000); });
onUnmounted(() => clearInterval(t));
</script>

<style scoped>
.mes-chip { position: fixed; left: 12px; bottom: 40px; z-index: 1900; display: inline-flex; align-items: center; gap: 5px; font-size: var(--hm-fs-xs); cursor: pointer; max-width: 260px;
  color: var(--hm-setup-ink); background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-pill); padding: 3px 8px 3px 10px; box-shadow: var(--hm-e2);
  transition: border-color var(--hm-dur-2) var(--hm-ease); }
.mes-chip:hover { border-color: var(--hm-primary); }
.mes-chip .pd { width: 7px; height: 7px; border-radius: 50%; background: var(--hm-run); flex: none; }
.mes-chip .el-icon { color: var(--hm-primary); }
.mes-chip span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-weight: 600; }
.mes-chip .x { color: var(--hm-text-3); } .mes-chip .x:hover { color: var(--hm-text); }
</style>
