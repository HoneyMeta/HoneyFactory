<template>
  <!-- 5.0 SaaS: this action requires the desktop client (the factory runs on your computer). Provide a button to open the relevant client page + guidance if not installed. Avoid a "403, use the client" dead end. -->
  <div class="client-link" data-k="client-link">
    <div class="cl-head"><el-icon :size="20"><Monitor /></el-icon><b>{{ title }}</b></div>
    <p class="cl-why">{{ why }}</p>
    <div class="cl-row">
      <a class="el-button el-button--primary" :href="href" data-k="client-link-open" @click="opened = true"><el-icon><TopRight /></el-icon><span>{{ $t('clientLink.openInDesktopClient') }}</span></a>
      <el-button v-if="copyable" @click="copy">{{ $t('clientLink.copyLink') }}</el-button>
    </div>
    <ol class="cl-steps">
      <li>{{ $t('clientLink.desktopClientNotInstalledAsk') }}</li>
      <li>{{ $t('clientLink.onTheLoginPageSelect') }}<code>{{ origin }}</code>{{ $t('clientLink.andSignInWithThis') }}</li>
      <li>{{ steps }}</li>
    </ol>
    <p v-if="opened" class="cl-tip">{{ $t('clientLink.nothingHappenedTheDesktopClient') }}</p>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, ref } from 'vue';
import { clientLink } from '../api';

const props = withDefaults(defineProps<{ path: string; title?: string; why?: string; steps?: string; copyable?: boolean }>(), {
  title: $t('clientLink.completeThisStepInThe'), why: $t('clientLink.honeyCloudDoesNotRun'),
  steps: $t('clientLink.goToTheCorrespondingPage'), copyable: true,
});
const href = computed(() => clientLink(props.path));
const origin = location.origin;
const opened = ref(false);
async function copy() {
  try { await navigator.clipboard.writeText(href.value); ElMessage.success($t('common.copied')); } catch { ElMessage.info(href.value); }
}
</script>

<style scoped>
.client-link { border: 1px solid var(--el-color-primary-light-5); background: var(--el-color-primary-light-9); border-radius: 10px; padding: 14px 18px; max-width: 640px; }
.cl-head { display: flex; align-items: center; gap: 8px; font-size: 15px; color: var(--el-text-color-primary); }
.cl-why { margin: 6px 0 10px; font-size: 13px; line-height: 1.7; color: var(--el-text-color-regular); }
.cl-row { display: flex; gap: 8px; align-items: center; } .cl-row a { text-decoration: none; }
.cl-steps { margin: 10px 0 0; padding-left: 18px; font-size: 12.5px; line-height: 1.9; color: var(--el-text-color-secondary); }
.cl-steps code { background: var(--el-fill-color); padding: 0 4px; border-radius: 3px; }
.cl-tip { font-size: 12px; color: var(--hm-idle-ink); margin: 8px 0 0; }
</style>
