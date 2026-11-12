<template>
  <div v-if="ctx.show" ref="root" class="xm" :style="pos(ctx.x, ctx.y, root)" @pointerdown.stop @contextmenu.prevent>
    <template v-for="(g, gi) in ctx.groups" :key="gi">
      <div v-if="gi" class="xm-sep" />
      <div v-if="g.title" class="xm-t">{{ g.title }}</div>
      <div v-for="(it, i) in g.items" :key="i" class="xm-i" :class="{ dis: it.disabled, bad: it.danger, sub: !!it.children, open: openKey === gi + ':' + i }"
        @pointerenter="hover(gi + ':' + i, it, $event)" @click="click(it)">
        <span class="xm-c">{{ it.checked ? '✓' : '' }}</span><span class="xm-l">{{ it.label }}</span>
        <small v-if="it.hint" class="xm-h">{{ it.hint }}</small><kbd v-if="it.kbd">{{ it.kbd }}</kbd>
        <el-icon v-if="it.children" class="xm-a"><ArrowRight /></el-icon>
      </div>
    </template>
    <div v-if="subItems" ref="subEl" class="xm xm-subm" :style="pos(sub.x, sub.y, subEl)" @pointerdown.stop>
      <div v-if="!subItems.length" class="xm-i dis"><span class="xm-c" /><span class="xm-l">{{ $t('outliner.empty') }}</span></div>
      <div v-for="(it, i) in subItems" :key="i" class="xm-i" :class="{ dis: it.disabled, bad: it.danger }" @click="click(it)">
        <span class="xm-c">{{ it.checked ? '✓' : '' }}</span><span class="xm-l">{{ it.label }}</span><kbd v-if="it.kbd">{{ it.kbd }}</kbd>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
// Global context menu (shared by all three views; data in contextMenu.ts). Submenus open on hover; children can be a function evaluated on opening (e.g., equipment tags).
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue';
import { closeCtx, ctx, type MenuItem } from './contextMenu';

const root = ref<HTMLElement | null>(null), subEl = ref<HTMLElement | null>(null);
const openKey = ref(''), sub = reactive<{ x: number; y: number; it: MenuItem | null }>({ x: 0, y: 0, it: null });
const subItems = computed(() => { const c = sub.it?.children; return c ? (typeof c === 'function' ? c() : c) : null; });
watch(() => ctx.show, () => { openKey.value = ''; sub.it = null; });

/** Keep within the window. */
function pos(x: number, y: number, el: HTMLElement | null) {
  const w = el?.offsetWidth || 220, h = el?.offsetHeight || 300;
  return { left: Math.max(4, Math.min(x, innerWidth - w - 6)) + 'px', top: Math.max(4, Math.min(y, innerHeight - h - 6)) + 'px' };
}
function hover(k: string, it: MenuItem, e: PointerEvent) {
  if (!it.children) { openKey.value = ''; sub.it = null; return; }
  const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
  openKey.value = k; sub.it = it;
  sub.x = r.right + 2 + 220 > innerWidth ? r.left - 222 : r.right + 2; sub.y = r.top - 4;
}
function click(it: MenuItem) {
  if (it.disabled || it.children) return;
  closeCtx();
  it.run?.();
}
const away = () => closeCtx();
const esc = (e: KeyboardEvent) => { if (e.key === 'Escape' && ctx.show) { e.stopPropagation(); closeCtx(); } };
onMounted(() => { addEventListener('pointerdown', away); addEventListener('keydown', esc, true); addEventListener('blur', away); });
onUnmounted(() => { removeEventListener('pointerdown', away); removeEventListener('keydown', esc, true); removeEventListener('blur', away); });
</script>

<style>
.xm { position: fixed; z-index: 4000; min-width: 210px; max-width: 320px; max-height: 70vh; overflow-y: auto; padding: 4px 0; border-radius: var(--hm-r-md);
  background: var(--hm-surface); border: 1px solid var(--hm-border); box-shadow: var(--hm-e3); font-size: 13px; color: var(--el-text-color-primary); user-select: none; }
.xm-t { padding: 6px 12px 3px; font-size: 11.5px; color: var(--el-text-color-secondary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.xm-sep { height: 1px; margin: 4px 0; background: var(--el-border-color-lighter); }
.xm-i { display: flex; align-items: center; gap: 6px; padding: 5px 12px 5px 6px; cursor: pointer; white-space: nowrap; }
.xm-i:hover, .xm-i.open { background: var(--hm-primary-soft); color: var(--hm-setup-ink); }
.xm-i.dis { color: var(--el-text-color-placeholder); cursor: default; }
.xm-i.dis:hover { background: none; }
.xm-i.bad { color: var(--el-color-danger); }
.xm-c { width: 14px; text-align: center; color: var(--el-color-primary); flex: none; }
.xm-l { flex: 1; overflow: hidden; text-overflow: ellipsis; }
.xm-h { color: var(--el-text-color-secondary); }
.xm kbd { font: 11px ui-monospace, Consolas, monospace; color: var(--el-text-color-secondary); background: none; border: 0; }
.xm-a { color: var(--el-text-color-secondary); }
</style>
