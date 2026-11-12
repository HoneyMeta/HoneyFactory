<template>
  <!-- Command Palette (Ctrl+K): pages, factories, lessons, help, and Workbench actions; fuzzy search, shortcuts on the right, recent items first -->
  <div v-if="palette.open" class="cmdp-mask" @mousedown.self="close">
    <div class="cmdp" role="dialog" :aria-label="$t('common.commandPalette')" data-k="cmdp">
      <div class="cmdp-in">
        <el-icon class="cmdp-si"><Search /></el-icon>
        <input ref="inp" v-model="palette.q" class="cmdp-q" data-k="cmdp-q" :placeholder="$t('commandPalette.searchCommandsPagesFactoriesCourses')" spellcheck="false" autocomplete="off" @keydown="onKey" />
        <kbd class="cmdp-esc">Esc</kbd>
      </div>
      <div ref="list" class="cmdp-list">
        <template v-for="(c, i) in hits" :key="c.id">
          <div v-if="headOf(i)" class="cmdp-g">{{ headOf(i) }}</div>
          <div :class="['cmdp-i', { on: i === sel }]" :data-cmd="c.id" @mousemove="sel = i" @click="run(c)">
            <el-icon class="cmdp-ic"><component :is="c.icon || 'Promotion'" /></el-icon>
            <span class="cmdp-t">{{ c.title }}</span>
            <small v-if="c.hint" class="cmdp-h">{{ c.hint }}</small>
            <span class="grow" />
            <span v-if="c.shortcut" class="cmdp-k"><kbd v-for="k in keys(c.shortcut)" :key="k">{{ k }}</kbd></span>
          </div>
        </template>
        <EmptyState v-if="!hits.length" kind="search" compact :title="$t('commandPalette.noMatchingCommands')" :desc="$t('commandPalette.tryDifferentWordingOrSearch', [palette.q])">
          <el-button size="small" @click="searchHelp">{{ $t('commandPalette.searchHelp') }}</el-button>
        </EmptyState>
      </div>
      <div class="cmdp-foot"><span><kbd>↑</kbd><kbd>↓</kbd> {{ $t('common.select') }}</span><span><kbd>Enter</kbd> {{ $t('commandPalette.execute') }}</span><span><kbd>Esc</kbd> {{ $t('common.close') }}</span><span class="grow" /><span>{{ $t('commandPalette.f1HelpForThisPage') }}</span></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import EmptyState from '../components/EmptyState.vue';
import { openHelp } from '../start/ui';
import { closeCommandPalette, openCommandPalette, palette, recent, runCommand, search, type Hit } from './registry';

const inp = ref<HTMLInputElement | null>(null), list = ref<HTMLElement | null>(null), sel = ref(0);
const hits = computed<Hit[]>(() => { void recent.ids.length; return search(palette.q, 60); });
/** Group headings: show "Recent" then groups when empty; with a query, sort by score without grouping. */
function headOf(i: number) {
  const c = hits.value[i], p = hits.value[i - 1];
  if (palette.q.trim()) return i === 0 ? '' : '';
  const g = (x: Hit) => (x.recentRank >= 0 ? $t('common.recentlyUsed') : x.group || $t('common.other'));
  return !p || g(p) !== g(c) ? g(c) : '';
}
const keys = (s: string) => s.split(' / ')[0].split('+');   // For 'F5 / Space', show only the first option; the / in 'Ctrl+/' is a key
watch(() => palette.q, () => { sel.value = 0; });
watch(() => palette.open, (v) => { if (v) { sel.value = 0; nextTick(() => inp.value?.focus()); } });
function close() { closeCommandPalette(); }
function run(c: Hit) { runCommand(c); }
function move(d: number) {
  const n = hits.value.length; if (!n) return;
  sel.value = (sel.value + d + n) % n;
  nextTick(() => list.value?.querySelector('.cmdp-i.on')?.scrollIntoView({ block: 'nearest' }));
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowDown') { e.preventDefault(); move(1); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
  else if (e.key === 'Enter') { e.preventDefault(); const c = hits.value[sel.value]; if (c) run(c); }
  else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); }
  else if (e.key === 'Tab') e.preventDefault();
}
function searchHelp() { const q = palette.q; close(); openHelp('', 'palette'); setTimeout(() => { const el = document.querySelector<HTMLInputElement>('.help-drawer input'); if (el) { el.value = q; el.dispatchEvent(new Event('input')); } }, 80); }

// Capture Ctrl+K (⌘K on Mac) to prevent the Workbench's legacy command palette from opening
function onGlobalKey(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'k') {
    e.preventDefault(); e.stopImmediatePropagation();
    if (palette.open) close(); else openCommandPalette();
  }
}
onMounted(() => addEventListener('keydown', onGlobalKey, true));
onUnmounted(() => { removeEventListener('keydown', onGlobalKey, true); close(); });
</script>

<style scoped>
.cmdp-mask { position: fixed; inset: 0; z-index: 3000; background: rgba(15, 27, 45, .28); display: flex; justify-content: center; align-items: flex-start; padding-top: min(14vh, 140px); }
.cmdp { width: min(680px, 94vw); max-height: min(70vh, 640px); display: flex; flex-direction: column; background: var(--hm-surface); color: var(--hm-text);
  border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); box-shadow: var(--hm-e3); overflow: hidden; }
.cmdp-in { display: flex; align-items: center; gap: 10px; padding: 12px 14px; border-bottom: 1px solid var(--hm-border); }
.cmdp-si { font-size: 18px; color: var(--el-text-color-secondary); }
.cmdp-q { flex: 1; border: 0; outline: 0; background: transparent; font-size: 15.5px; color: inherit; font-family: inherit; }
.cmdp-q::placeholder { color: var(--hm-text-3); }
.cmdp-list { overflow: auto; padding: 6px; flex: 1; min-height: 0; }
.cmdp-g { font-size: 11.5px; color: var(--el-text-color-secondary); padding: 8px 10px 4px; letter-spacing: .5px; }
.cmdp-i { display: flex; align-items: center; gap: 10px; padding: 7px 10px; border-radius: 8px; cursor: pointer; font-size: 13.5px; min-height: 34px; }
.cmdp-i.on { background: var(--hm-primary-soft); box-shadow: inset 3px 0 0 var(--hm-primary); }
.cmdp-ic { color: var(--el-text-color-secondary); font-size: 16px; flex: none; } .cmdp-i.on .cmdp-ic { color: var(--el-color-primary); }
.cmdp-t { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cmdp-h { color: var(--el-text-color-secondary); font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.cmdp-k { display: inline-flex; gap: 3px; flex: none; }
kbd { font-family: var(--hm-font-mono); font-size: 11px; line-height: 18px; min-width: 18px; text-align: center; padding: 0 5px; border-radius: 4px;
  border: 1px solid var(--hm-border-strong); border-bottom-width: 2px; background: var(--hm-surface-2); color: var(--hm-text-2); }
.cmdp-esc { flex: none; }
.cmdp-foot { display: flex; gap: 14px; align-items: center; padding: 7px 14px; border-top: 1px solid var(--hm-border); background: var(--hm-surface-2); font-size: 11.5px; color: var(--el-text-color-secondary); }
.cmdp-foot span { display: inline-flex; gap: 3px; align-items: center; }
.grow { flex: 1; }
</style>
