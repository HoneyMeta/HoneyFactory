<template>
  <div class="lib">
    <div v-if="tip" class="lib-tip">
      <b>{{ $t('library.howToUse') }}</b>{{ $t('library.k1050') }}<b>{{ $t('library.drag') }}</b>{{ $t('library.anAssetIntoThe3d') }}<b>{{ $t('library.click') }}</b>{{ $t('library.anAssetThenClickThe') }}<a @click="hideTip">{{ $t('common.gotIt') }}</a>
    </div>
    <el-input v-model="q" size="small" :placeholder="$t('library.searchBlockTypesOrTemplates')" clearable class="lib-q"><template #prefix><el-icon><Search /></el-icon></template></el-input>
    <el-scrollbar class="lib-list">
      <div v-for="c in cats" :key="c.name" class="lib-sec">
        <div class="ol-sh click" @click="fold[c.name] = !fold[c.name]"><el-icon><component :is="fold[c.name] ? 'CaretRight' : 'CaretBottom'" /></el-icon>{{ c.name }}<small>{{ c.items.length }}</small></div>
        <div v-if="!fold[c.name]" class="tiles">
          <el-tooltip v-for="t in c.items" :key="t.key" :content="t.help || t.label" placement="right" :show-after="500">
            <div class="tile" :class="{ on: ed.placing?.type === t.key }" :data-tour="'lib-' + t.key" draggable="true" @dragstart="(e: DragEvent) => { ed.placing = null; e.dataTransfer!.setData('vf/type', t.key); }"
              @click="startPlacing(t.key)" @dblclick="ed.placing = null; emit('add', t.key)">
              <el-icon :style="{ background: t.color }"><component :is="t.icon" /></el-icon><span>{{ t.label }}</span>
            </div>
          </el-tooltip>
        </div>
      </div>
      <div class="lib-sec">
        <div class="ol-sh">{{ $t('library.myTemplates') }}<small>{{ tpls.length }}</small></div>
        <div v-for="t in tpls" :key="t.id" class="tpl" draggable="true" @dragstart="(e: DragEvent) => e.dataTransfer!.setData('vf/tpl', t.id)">
          <el-icon><Collection /></el-icon><div><b>{{ t.name }}</b><small class="muted">{{ $t('library.n0Blocks1', [t.blocks.length, t.user]) }}</small></div>
          <el-button size="small" text type="danger" @click.stop="remove(t)"><el-icon><Delete /></el-icon></el-button>
        </div>
        <div v-if="!tpls.length" class="muted small" style="padding:4px 8px">{{ $t('library.selectSeveralBlocksRightClick') }}</div>
      </div>
    </el-scrollbar>
    <div class="ol-foot muted small">{{ $t('library.dragOntoTheCanvasClick') }}</div>
  </div>
</template>

<script setup lang="ts">
import { $t, variants } from '../i18n';
import { ElMessageBox } from 'element-plus';
import { computed, onMounted, reactive, ref } from 'vue';
import { del } from '../api';
import { startPlacing } from './shell/place';
import { ed, reloadTemplates } from './store';

const emit = defineEmits<{ (e: 'add', type: string): void }>();
const q = ref('');
const tip = ref((() => { try { return localStorage.getItem('vf_lib_tip') !== '0'; } catch { return true; } })());
function hideTip() { tip.value = false; try { localStorage.setItem('vf_lib_tip', '0'); } catch { /* */ } }
const fold = reactive<Record<string, boolean>>({});
const tpls = computed(() => (ed.templates || []).filter((t: any) => !q.value || t.name.includes(q.value)));
const cats = computed(() => {
  const k = q.value.trim().toLowerCase();
  const m = new Map<string, any[]>();
  for (const [key, t] of Object.entries(ed.cat?.types || {}) as any) {
    if (k && !(t.label.toLowerCase().includes(k) || key.includes(k) || (t.help || '').includes(k))) continue;
    if (!m.has(t.cat)) m.set(t.cat, []);
    m.get(t.cat)!.push({ key, ...t });
  }
  const order = ed.cat?.cats || [];
  return [...m.entries()].map(([name, items]) => ({ name, items })).sort((a, b) => order.indexOf(a.name) - order.indexOf(b.name));
});
async function remove(t: any) {
  await ElMessageBox.confirm($t('library.deleteTemplate0', [t.name]), $t('library.deleteTemplate'), { type: 'warning' });
  await del('/api/templates/' + t.id); reloadTemplates();
}
onMounted(() => { for (const c of ed.cat?.types ? Object.values(ed.cat.types) as any : []) if (variants('blockNode.advanced').some((v) => c.cat.startsWith(v))) fold[c.cat] = true; reloadTemplates(); });
</script>
