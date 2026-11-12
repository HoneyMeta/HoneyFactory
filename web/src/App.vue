<template>
  <!-- Rebuild the page when switching factories (Workbench loads the model and connects WebSocket by pid) -->
  <router-view :key="String(route.params.pid || '')" />
  <!-- /mes/**: Teaching MES pages (no AI); do not overlay the HoneyFactory Modeling Assistant -->
  <!-- 5.0 SaaS web has no factories; use the Modeling Assistant in the desktop client (LLM via the server AI proxy) -->
  <AssistantDock v-if="session.user && !route.meta.public && !/^\/mes(\/|$)/.test(route.path) && session.user.deploy !== 'saas'" />
  <!-- All pages (including Workbench): Ctrl+K Command Palette, F1 help drawer, What's New after upgrades, keyboard shortcuts -->
  <template v-if="session.user && !route.meta.public">
    <CommandPalette />
    <HelpDrawer />
    <WhatsNew />
    <ShortcutsDialog />
    <MesChip />
  </template>
</template>

<script setup lang="ts">
import { watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { session } from './api';
import { loadBrand } from './brand';
import AssistantDock from './components/AssistantDock.vue';
import ShortcutsDialog from './components/ShortcutsDialog.vue';
import MesChip from './components/MesChip.vue';
import WhatsNew from './components/WhatsNew.vue';
import CommandPalette from './commands/CommandPalette.vue';
import { installCommandLoaders } from './commands';
import HelpDrawer from './help/HelpDrawer.vue';
import { installRecent } from './start/recent';
import { checkWhatsNew } from './start/ui';

const route = useRoute(), router = useRouter();
loadBrand();
installRecent(router);
installCommandLoaders(router);
// After login: show What's New if the version has changed
watch(() => !!session.user && !route.meta.public, (v) => { if (v) setTimeout(checkWhatsNew, 600); }, { immediate: true });
</script>
