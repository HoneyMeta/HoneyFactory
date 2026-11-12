<template>
  <!-- F1 context help: side drawer without leaving the page (Workbench simulation keeps running) -->
  <el-drawer v-model="ui.help.open" :size="size" direction="rtl" append-to-body :with-header="false" :modal="false" class="help-drawer" modal-class="help-drawer-modal">
    <div class="hd" :data-help-id="cur?.id || ''">
      <div class="hd-top">
        <el-icon class="hd-ic"><QuestionFilled /></el-icon><b>{{ $t('common.help') }}</b><small class="muted">F1</small><span class="grow" />
        <el-tooltip :content="$t('helpDrawer.openInHelpCenter')"><el-button text size="small" data-k="help-full" @click="full"><el-icon><FullScreen /></el-icon></el-button></el-tooltip>
        <el-button text size="small" :title="$t('helpDrawer.closeEsc')" @click="ui.help.open = false"><el-icon><Close /></el-icon></el-button>
      </div>
      <el-input v-model="q" size="small" clearable :placeholder="$t('helpDrawer.searchHelp')" class="hd-q" data-k="help-q"><template #prefix><el-icon><Search /></el-icon></template></el-input>
      <div v-if="q.trim()" class="hd-list">
        <div v-for="s in found" :key="s.id" class="hd-li" @click="pick(s.id)"><b>{{ s.title }}</b><span class="muted small">{{ snippet(s.text) }}</span></div>
        <EmptyState v-if="!found.length" kind="search" compact :title="$t('helpDrawer.noMatchingHelpFound')" :desc="$t('helpDrawer.tryDifferentWordsOrPress')" />
      </div>
      <template v-else-if="cur">
        <div class="hd-ttl"><h3>{{ cur.title }}</h3><span v-if="isCtx" class="hd-ctx">{{ $t('common.youAreHere') }}</span></div>
        <div class="hd-body md">{{ cur.text }}</div>
        <div v-if="guides.length" class="hd-rel hd-guides" data-k="help-guides">
          <div class="muted small">{{ $t('helpDrawer.guidedToursStepByStep') }}</div>
          <div class="hd-chips"><span v-for="g in guides" :key="g.key" class="hd-chip gd" :data-guide="g.key" @click="runGuide(g.key)">{{ g.task ? '▶ ' : '' }}{{ g.title }}</span></div>
        </div>
        <div class="hd-rel">
          <div class="muted small">{{ $t('helpDrawer.otherSections') }}</div>
          <div class="hd-chips"><span v-for="s in others" :key="s.id" class="hd-chip" @click="pick(s.id)">{{ s.title }}</span></div>
        </div>
      </template>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import EmptyState from '../components/EmptyState.vue';
import { ui } from '../start/ui';
import { contextHelpId } from './context';
import { sectionById, sectionsFor } from './sections';
import { guidesForHelp, startGuide } from '../panels/teach/tour/guides';

const router = useRouter();
const q = ref(''), ctxId = ref('');
const size = computed(() => (innerWidth < 900 ? '92%' : innerWidth > 2200 ? '560px' : '460px'));
const all = computed(() => sectionsFor());
const cur = computed(() => sectionById(ui.help.id) || all.value[0]);
const isCtx = computed(() => !!ctxId.value && ctxId.value === cur.value?.id);
const others = computed(() => all.value.filter((s) => s.id !== cur.value?.id));
const found = computed(() => { const k = q.value.trim().toLowerCase(); return all.value.filter((s) => (s.title + s.text).toLowerCase().includes(k)); });
function snippet(t: string) {
  const k = q.value.trim().toLowerCase(), i = t.toLowerCase().indexOf(k);
  return (i > 30 ? '…' : '') + t.slice(Math.max(0, i - 30), i + 60).replace(/\s+/g, ' ') + '…';
}
function pick(id: string) { ui.help.id = id; q.value = ''; }
// 4.7 Guided tours for this section: click to close the drawer and start the tour
const guides = computed(() => (cur.value ? guidesForHelp(cur.value.id) : []));
function runGuide(key: string) { ui.help.open = false; startGuide(key); }
function full() { const id = cur.value?.id; ui.help.open = false; router.push('/help' + (id ? '?s=' + id : '')); }
watch(() => ui.help.open, (v) => { if (v) { q.value = ''; if (!ui.help.id) ui.help.id = contextHelpId(); if (!ui.help.from) ctxId.value = ui.help.id; else ctxId.value = ''; } });

/** F1: toggle help for the current context. Esc closes it. */
function onKey(e: KeyboardEvent) {
  if (e.key === 'F1') {
    e.preventDefault(); e.stopPropagation();
    const id = contextHelpId();
    if (ui.help.open && ui.help.id === id) { ui.help.open = false; return; }
    ui.help.from = ''; ui.help.id = id; ctxId.value = id; ui.help.open = true;
  } else if (e.key === 'Escape' && ui.help.open && !document.querySelector('.cmdp-mask')) { ui.help.open = false; }
}
onMounted(() => addEventListener('keydown', onKey, true));
onUnmounted(() => { removeEventListener('keydown', onKey, true); ui.help.open = false; });
</script>

<style scoped>
.hd { height: 100%; display: flex; flex-direction: column; gap: 10px; }
.hd-top { display: flex; align-items: center; gap: 6px; } .hd-top b { font-size: 15px; } .hd-ic { color: var(--el-color-primary); font-size: 18px; }
.hd-ttl { display: flex; align-items: center; gap: 8px; } .hd-ttl h3 { margin: 4px 0 0; font-size: 16px; line-height: 1.4; }
.hd-ctx { flex: none; font-size: 11.5px; color: var(--hm-run-ink); background: var(--hm-run-soft); border-radius: 999px; padding: 1px 8px; }
.hd-body { font-size: 13.5px; line-height: 1.85; overflow: auto; flex: 1; min-height: 0; padding-right: 4px; color: var(--el-text-color-primary); }
.hd-rel { border-top: 1px solid var(--el-border-color-lighter); padding-top: 8px; }
.hd-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; max-height: 120px; overflow: auto; }
.hd-chip { font-size: 12px; border: 1px solid var(--el-border-color); border-radius: 999px; padding: 2px 10px; cursor: pointer; white-space: nowrap; }
.hd-chip:hover { border-color: var(--el-color-primary); color: var(--el-color-primary); }
.hd-chip.gd { border-color: var(--el-color-primary-light-5); color: var(--el-color-primary); }
.hd-guides { border-top: 0; padding-top: 0; }
.hd-list { overflow: auto; flex: 1; display: grid; align-content: start; gap: 4px; }
.hd-li { padding: 8px 10px; border-radius: 8px; cursor: pointer; display: grid; gap: 2px; } .hd-li:hover { background: var(--el-fill-color-light); }
</style>
<style>
/* Nonblocking drawer: no backdrop; the page remains interactive */
.help-drawer-modal { pointer-events: none; background: transparent !important; }
.help-drawer-modal .help-drawer { pointer-events: auto; box-shadow: var(--hm-e3); }
.help-drawer .el-drawer__body { padding: 14px 16px; }
</style>
