<template>
  <!-- Empty lists: use the supplied empty-<kind>.png illustration if available; otherwise use an icon + existing text -->
  <div class="es" :class="[{ compact, plain, art: !!img.src && !plain }]" :data-k="'empty-' + kind">
    <img v-if="img.src && !plain" :src="img.src" :srcset="img.srcset || undefined" alt="" class="es-img" @error="bad = true" />
    <el-icon v-else-if="!plain" :size="compact ? 28 : 40" class="es-i"><component :is="icon || ICONS[kind] || 'Box'" /></el-icon>
    <div class="es-t">{{ title }}</div>
    <div v-if="desc" class="es-d">{{ desc }}</div>
    <div v-if="$slots.default" class="es-a"><slot /></div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { brand, loadBrand, themed } from '../brand';

/** plain: text only (use an illustration for the main empty area on a page; use plain for the rest) */
const props = withDefaults(defineProps<{ kind: string; title: string; desc?: string; icon?: string; compact?: boolean; plain?: boolean }>(), { desc: '', icon: '', compact: false, plain: false });
const ICONS: Record<string, string> = { plants: 'OfficeBuilding', mine: 'OfficeBuilding', homework: 'Notebook', submissions: 'Tickets', search: 'Search', recent: 'Clock' };
// Supplied illustrations: empty-factories / homework / submissions / search / offline (each has @2x; light variants only since 5.0.1)
const ART: Record<string, string> = { plants: 'empty-factories', mine: 'empty-factories', recent: 'empty-factories', factories: 'empty-factories',
  homework: 'empty-homework', submissions: 'empty-submissions', search: 'empty-search', offline: 'empty-offline' };
const bad = ref(false);
loadBrand();
const img = computed(() => (bad.value || !brand.loaded ? { src: '', srcset: '' } : themed(ART[props.kind] || 'empty-' + props.kind)));
</script>

<style scoped>
.es { display: flex; flex-direction: column; align-items: center; text-align: center; padding: 28px 16px; color: var(--hm-text-3); }
.es.plain { padding: 16px 10px; }
.es.compact { padding: 14px 10px; }
.es-img { width: min(240px, 70%); height: auto; margin-bottom: 8px; user-select: none; pointer-events: none; }
.es.compact .es-img { width: min(168px, 60%); }
.es-i { color: var(--hm-text-3); margin-bottom: 8px; }
.es-t { font-size: var(--hm-fs-md); font-weight: 600; color: var(--hm-text-2); }
.es.compact .es-t { font-size: var(--hm-fs-sm); }
.es-d { font-size: var(--hm-fs-xs); margin-top: 4px; max-width: 420px; line-height: 1.6; }
.es-a { margin-top: 12px; display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
</style>
