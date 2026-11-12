<template>
  <div class="ex">
    <el-input v-model="text" size="small" :placeholder="placeholder || $t('exprInput.expressionEGNormal60')" :class="{ bad: err }" class="mono" @change="commit">
      <template #append><el-button size="small" :title="$t('exprInput.evaluate5Times')" @click="test"><el-icon><CaretRight /></el-icon></el-button></template>
    </el-input>
    <div v-if="err" class="ex-err">{{ err }}</div>
    <div v-else-if="samples" class="ex-ok mono">{{ $t('exprInput.results0', [samples.join($t('common.k521'))]) }}</div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { post } from '../api';

const props = defineProps<{ modelValue: any; placeholder?: string }>();
const emit = defineEmits<{ (e: 'change', v: any): void }>();
const text = ref(String(props.modelValue ?? ''));
const err = ref(''), samples = ref<any[] | null>(null);
watch(() => props.modelValue, (v) => { text.value = String(v ?? ''); err.value = ''; samples.value = null; });
async function check() {
  const r = await post('/api/expr/check', { expr: text.value }).catch(() => null);
  if (!r) return false;
  err.value = r.ok ? '' : r.error; samples.value = r.ok ? r.samples : null;
  return r.ok;
}
async function commit() {
  if (!text.value.trim()) { emit('change', ''); return; }
  if (await check()) emit('change', /^-?\d+(\.\d+)?$/.test(text.value.trim()) ? Number(text.value) : text.value.trim());
}
const test = check;
</script>
