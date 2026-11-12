<template>
  <!-- Quick Add (like Tab / "+" in the graph): search block types, then press Enter or click to add; when starting from equipment, list only compatible downstream types (equipment with inlets after production equipment; control/communication/information system equipment after switches/gateways) -->
  <div class="qa pv-qa" :style="{ left: x + 'px', top: y + 'px' }" @mousedown.stop @wheel.stop @contextmenu.stop.prevent>
    <div class="pv-qa-t">{{ title }}</div>
    <el-input ref="inp" v-model="q" size="small" :placeholder="$t('graphView.searchBlockTypesEG')" clearable
      @keydown.enter="list[i] && emit('pick', list[i].key)" @keydown.esc="emit('close')"
      @keydown.down.prevent="i = Math.min(list.length - 1, i + 1)" @keydown.up.prevent="i = Math.max(0, i - 1)" />
    <div class="qa-list">
      <div v-for="(t, k) in list" :key="t.key" :class="['qa-i', { on: k === i }]" :title="t.help || ''" @mouseenter="i = k" @click="emit('pick', t.key)">
        <el-icon :style="{ color: t.color }"><component :is="t.icon" /></el-icon><span>{{ t.label }}</span><small>{{ t.cat }}</small>
      </div>
      <div v-if="!list.length" class="muted small" style="padding:6px">{{ $t('graphView.noMatchingTypes') }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { ed } from '../store';

const props = defineProps<{ x: number; y: number; title: string; only?: 'in' | 'ctl' | '' }>();
const emit = defineEmits<{ (e: 'pick', key: string): void; (e: 'close'): void }>();
const q = ref(''), i = ref(0), inp = ref<any>();
const list = computed(() => {
  const s = q.value.trim().toLowerCase();
  return Object.entries(ed.cat?.types || {}).map(([key, t]: any) => ({ key, ...t }))
    .filter((t: any) => props.only !== 'in' || (t.in.length && (t.layer || 'process') === 'process'))
    .filter((t: any) => props.only !== 'ctl' || (t.layer || 'process') !== 'process')
    .filter((t: any) => !s || t.label.toLowerCase().includes(s) || t.key.includes(s) || (t.cat || '').includes(s) || (t.help || '').includes(s))
    .sort((a: any, b: any) => Number(a.legacy) - Number(b.legacy)).slice(0, 14);
});
watch(q, () => { i.value = 0; });
// Focus after the opening mouse / keyboard event completes (otherwise the browser's default action steals focus)
onMounted(() => nextTick(() => setTimeout(() => inp.value?.focus(), 0)));
</script>
