<template>
  <div class="ol">
    <div class="ol-top">
      <el-input v-model="q" size="small" :placeholder="$t('outliner.searchByIdNameOr')" clearable><template #prefix><el-icon><Search /></el-icon></template></el-input>
      <el-radio-group v-model="by" size="small">
        <el-radio-button value="area">{{ $t('details.zone') }}</el-radio-button><el-radio-button value="cat">{{ $t('outliner.category') }}</el-radio-button><el-radio-button value="group">{{ $t('common.group') }}</el-radio-button>
      </el-radio-group>
    </div>
    <el-scrollbar class="ol-list">
      <div v-for="sec in sections" :key="sec.name" class="ol-sec">
        <div class="ol-sh click" @click="toggle(sec.name)"><el-icon><component :is="fold[sec.name] ? 'CaretRight' : 'CaretBottom'" /></el-icon>{{ sec.name }}<small>{{ sec.items.length }}</small></div>
        <template v-if="!fold[sec.name]">
          <div v-for="b in sec.items" :key="b.id" class="ol-i" :class="{ sel: ed.sel.includes(b.id), hl: ed.highlight.includes(b.id), err: issue[b.id] === 'error', warn: issue[b.id] === 'warn' }"
            @click="(e: MouseEvent) => pick(b.id, e)" @dblclick="focusOn(b.id)">
            <el-icon :style="{ color: typeOf(b).color }"><component :is="typeOf(b).icon" /></el-icon>
            <span class="nm">{{ b.name }}</span><small class="mono">{{ b.id }}</small>
            <i v-if="rtById[b.id]" class="dot" :style="{ background: STATE_COLOR[rtById[b.id].state] || '#888' }" :title="STATE_CN[rtById[b.id].state]" />
          </div>
        </template>
      </div>
      <div v-if="(ed.model?.notes || []).length" class="ol-sec">
        <div class="ol-sh">{{ $t('common.comment') }}<small>{{ ed.model.notes.length }}</small></div>
        <div v-for="n in ed.model.notes" :key="n.id" class="ol-i" :class="{ sel: ed.sel.includes(n.id) }" @click="select([n.id])" @dblclick="focusOn(n.id)">
          <el-icon><Memo /></el-icon><span class="nm">{{ (n.text || $t('outliner.empty')).slice(0, 24) }}</span></div>
      </div>
    </el-scrollbar>
    <div class="ol-foot muted small">{{ $t('outliner.n0BlocksClickToSelect', [(ed.model?.blocks || []).length]) }}</div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, reactive, ref } from 'vue';
import { areaOf, ed, focusOn, rtById, select, STATE_CN, STATE_COLOR, typeOf } from './store';

const q = ref(''), by = ref(localStorage.getItem('vf_ol_by') || 'area');
const fold = reactive<Record<string, boolean>>({});
const issue = computed(() => { const m: Record<string, string> = {}; for (const i of ed.validation?.issues || []) if (i.id && m[i.id] !== 'error') m[i.id] = i.level; return m; });
const sections = computed(() => {
  localStorage.setItem('vf_ol_by', by.value);
  const k = q.value.trim().toLowerCase();
  const bs = (ed.model?.blocks || []).filter((b: any) => !k || b.id.toLowerCase().includes(k) || (b.name || '').toLowerCase().includes(k) || typeOf(b).label.includes(k));
  const groups = Object.fromEntries((ed.model?.groups || []).map((g: any) => [g.id, g.name]));
  const key = (b: any) => (by.value === 'area' ? b.area || areaOf(b.pos) || $t('outliner.unzoned') : by.value === 'cat' ? typeOf(b).cat || $t('common.other') : groups[b.group] || $t('outliner.ungrouped'));
  const m = new Map<string, any[]>();
  for (const b of bs) { const s = key(b); if (!m.has(s)) m.set(s, []); m.get(s)!.push(b); }
  return [...m.entries()].map(([name, items]) => ({ name, items: items.sort((a, b) => a.id.localeCompare(b.id, 'en', { numeric: true })) }));
});
function toggle(n: string) { fold[n] = !fold[n]; }
function pick(id: string, e: MouseEvent) {
  if (e.ctrlKey || e.shiftKey) { if (ed.sel.includes(id)) ed.sel = ed.sel.filter((x: string) => x !== id); else select([id], true); }
  else select([id]);
}
</script>
