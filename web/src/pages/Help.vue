<template>
  <div class="page help" data-help="start">
    <div class="page-head"><h2>{{ $t('common.helpCenter') }}</h2><span class="grow" /><el-input v-model="q" :placeholder="$t('help.searchHelp')" clearable style="width:220px" /></div>
    <div class="grid" style="grid-template-columns: 200px 1fr">
      <div class="card toc"><div v-for="s in shown" :key="s.id" class="click" :class="{ on: cur === s.id }" @click="go(s.id)">{{ s.title }}</div></div>
      <div class="card body">
        <EmptyState v-if="!shown.length" kind="search" :title="$t('helpDrawer.noMatchingHelpFound')" :desc="$t('helpDrawer.tryDifferentWordsOrPress')" />
        <section v-for="s in shown" :key="s.id" :id="'h-' + s.id"><h3>{{ s.title }}</h3><div class="md">{{ s.text }}</div></section>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute } from 'vue-router';
import { session } from '../api';
import { sectionsFor } from '../help/sections';
import EmptyState from '../components/EmptyState.vue';

// Content lives in help/sections.ts (also used by the F1 context help drawer); ?s=<section> jumps to that section
const route = useRoute();
const q = ref(''), cur = ref(String(route.query.s || '') || (session.user?.role === 'student' ? 'stu' : 'start'));
const ALL = computed(() => sectionsFor());
const shown = computed(() => (q.value ? ALL.value.filter((s) => (s.title + s.text).toLowerCase().includes(q.value.trim().toLowerCase())) : ALL.value));
function go(id: string) { cur.value = id; document.getElementById('h-' + id)?.scrollIntoView({ behavior: 'smooth' }); }
onMounted(() => { if (route.query.s) setTimeout(() => go(String(route.query.s)), 60); });
</script>

<style scoped>
.toc { position: sticky; top: 10px; align-self: start; } .toc div { padding: 6px 8px; border-radius: 6px; } .toc div.on { background: var(--hm-primary-soft); color: var(--hm-setup-ink); box-shadow: inset 3px 0 0 var(--hm-primary); }
.body section { margin-bottom: 20px; } .body .md { font-size: 13.5px; }
@media (max-width: 800px) { .grid { grid-template-columns: 1fr !important; } }
</style>
