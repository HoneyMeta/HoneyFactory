<template>
  <!-- Local MES running: slim status bar atop MES pages (factory, data clock, idle auto-stop timeout) + return to factory / reimport / switch factory / stop -->
  <div class="mes-bar" data-k="mes-bar" data-tour="mes-bar">
    <span class="mb-brand"><el-icon><Tickets /></el-icon>{{ $t('common.teachingMes') }}</span>
    <el-tooltip :content="$t('mesBar.runningFor0', [dur(st.uptime_s)]) + (st.idle_s != null ? $t('mesBar.idleFor0', [dur(st.idle_s)]) : '') + (st.idle_min ? $t('mesBar.stopsAutomaticallyAfter0Min', [st.idle_min]) : $t('mesBar.noAutomaticStop'))">
      <span class="mb-st" data-k="mes-state"><i class="dot" />{{ $t('common.running2') }}</span>
    </el-tooltip>
    <span class="mb-plant" :title="st.pid">{{ st.plant_name }}</span>
    <el-tooltip :content="$t('mesBar.dataClockUsesTimestampsFrom')">
      <span class="mb-clock" data-k="mes-clock"><el-icon><Clock /></el-icon>{{ (mes.now || st.data_clock || '').slice(5, 19) || '—' }}</span>
    </el-tooltip>
    <span v-if="st.counts?.equipment !== undefined" class="mb-cnt">{{ $t('mesBar.equipment0WorkOrders1', [st.counts.equipment, st.counts.work_order, st.counts.report, st.counts.part]) }}</span>
    <span v-if="st.idle_min && st.idle_s != null" class="mb-idle" data-k="mes-idle">{{ $t('mesBar.idle01MinUntil', [dur(st.idle_s), st.idle_min]) }}</span>
    <span class="grow" />
    <el-button size="small" data-k="mes-back" data-tour="mes-back" @click="back"><el-icon><Back /></el-icon>{{ $t('mesBar.backToFactory') }}</el-button>
    <el-tooltip :content="$t('mesBar.reimportEquipmentAndTheTag')">
      <el-button size="small" :loading="busy" data-k="mes-reimport" @click="reimport"><el-icon><Refresh /></el-icon>{{ $t('mesBar.reimportEquipment') }}</el-button>
    </el-tooltip>
    <el-dropdown trigger="click" @command="onCmd">
      <el-button size="small" data-k="mes-more" data-tour="mes-more"><el-icon><MoreFilled /></el-icon></el-button>
      <template #dropdown>
        <el-dropdown-menu>
          <el-dropdown-item command="pick"><el-icon><Switch /></el-icon>{{ $t('mesBar.switchFactory') }}</el-dropdown-item>
          <el-dropdown-item command="info" disabled>{{ $t('mesBar.mesPort0Mqtt1', [st.port, st.ports?.mqtt, st.ports?.opcua]) }}</el-dropdown-item>
        </el-dropdown-menu>
      </template>
    </el-dropdown>
    <el-button size="small" type="danger" plain data-k="mes-stop" @click="emit('stop')">{{ $t('mesBar.stopMes') }}</el-button>
    <GuideButton area="mes" size="sm" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, ref } from 'vue';
import { useRouter } from 'vue-router';
import { post as vpost } from '../api';
import GuideButton from '../components/GuideButton.vue';
import { mes } from './api';

const emit = defineEmits(['pick', 'stop']);
const router = useRouter();
const st = computed(() => mes.st || {});
const busy = ref(false);
const dur = (s: number) => (s == null ? '—' : s < 60 ? $t('mesBar.n0S', [Math.round(s)]) : s < 3600 ? $t('mesBar.n0Min', [Math.floor(s / 60)]) : $t('mesBar.n0H1Min', [Math.floor(s / 3600), Math.floor((s % 3600) / 60)]));
function back() { router.push(`/p/${encodeURIComponent(st.value.pid)}/workbench`); }
async function reimport() {
  busy.value = true;
  try { const r = await vpost('/api/desktop/mes/reimport', {}); ElMessage.success(r.msg || $t('mesBar.reimportComplete')); } finally { busy.value = false; }
}
function onCmd(c: string) { if (c === 'pick') emit('pick'); }
</script>

<style scoped>
.mes-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 10px var(--hm-sp-5) 0; padding: 5px 8px 5px 12px; min-height: 38px;
  background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); box-shadow: var(--hm-e1); font-size: var(--hm-fs-xs); color: var(--hm-text-2); }
.mb-brand { display: inline-flex; align-items: center; gap: 5px; font-weight: 600; color: var(--hm-text); font-size: var(--hm-fs-sm); }
.mb-brand .el-icon { color: var(--hm-primary); font-size: 16px; }
.mb-st { display: inline-flex; align-items: center; gap: 5px; padding: 0 8px; line-height: 20px; border-radius: var(--hm-r-pill); background: var(--hm-run-soft); color: var(--hm-run-ink); font-weight: 600; }
.mb-st .dot { width: 6px; height: 6px; border-radius: 50%; background: var(--hm-run); }
.mb-plant { font-weight: 600; color: var(--hm-text); max-width: 240px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mb-clock { display: inline-flex; align-items: center; gap: 4px; font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; color: var(--hm-text-2);
  background: var(--hm-surface-2); border: 1px solid var(--hm-border); border-radius: var(--hm-r-sm); padding: 0 7px; line-height: 20px; }
.mb-cnt, .mb-idle { color: var(--hm-text-3); white-space: nowrap; font-variant-numeric: tabular-nums; }
.mes-bar .el-button + .el-button { margin-left: 0; }
.mes-bar :deep(.el-dropdown) { line-height: 1; }
@media (max-width: 1560px) { .mb-idle { display: none; } }
@media (max-width: 1400px) { .mb-cnt { display: none; } }
html.compact .mes-bar { margin: 6px 12px 0; min-height: 32px; padding: 3px 6px 3px 10px; gap: 8px; }
</style>
