<template>
  <div class="pi">
    <template v-if="d.t === 'num' || d.t === 'int'">
      <el-input-number :model-value="num" size="small" :controls="false" :precision="d.t === 'int' ? 0 : undefined" :placeholder="mixed ? $t('paramInput.multipleValues') : ''"
        @change="(v: any) => v !== null && v !== undefined && emit('set', v)" />
      <span v-if="d.unit" class="unit">{{ d.unit }}</span>
    </template>
    <ExprInput v-else-if="d.t === 'expr'" :model-value="mixed ? '' : value" :placeholder="mixed ? $t('paramInput.multipleValues') : ''" @change="(v: any) => emit('set', v)" />
    <el-switch v-else-if="d.t === 'bool'" :model-value="!!value" size="small" @change="(v: any) => emit('set', v)" />
    <el-select v-else-if="d.t === 'enum'" :model-value="value" size="small" :placeholder="mixed ? $t('paramInput.multipleValues') : ''" @change="(v: any) => emit('set', v)">
      <el-option v-for="(lab, k) in d.options" :key="k" :value="k" :label="lab" />
    </el-select>
    <el-select v-else-if="d.t === 'ref'" :model-value="value || ''" size="small" clearable :placeholder="mixed ? $t('paramInput.multipleValues') : $t('paramInput.notRequired')" @change="(v: any) => emit('set', v || '')">
      <el-option v-for="b in refs" :key="b.id" :value="b.id" :label="`${b.id} ${b.name}`" />
    </el-select>
    <template v-else-if="d.t === 'json'">
      <el-input type="textarea" :model-value="jtext" :autosize="{ minRows: 1, maxRows: 8 }" size="small" class="mono" :class="{ bad: jerr }"
        @change="setJson" @input="(v: string) => (jtext = v)" />
      <div v-if="jerr" class="ex-err">{{ jerr }}</div>
    </template>
    <el-input v-else :model-value="value ?? ''" size="small" :placeholder="mixed ? $t('paramInput.multipleValues') : ''" @change="(v: any) => emit('set', v)" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { computed, ref, watch } from 'vue';
import ExprInput from './ExprInput.vue';
import { ed } from './store';

const props = defineProps<{ d: any; value: any; mixed?: boolean }>();
const emit = defineEmits<{ (e: 'set', v: any): void }>();
const num = computed(() => (props.mixed || props.value === '' || props.value === null || props.value === undefined || isNaN(Number(props.value)) ? undefined : Number(props.value)));
const refs = computed(() => (ed.model?.blocks || []).filter((b: any) => b.type === props.d.ref));
const jtext = ref(''), jerr = ref('');
watch(() => props.value, (v) => { jtext.value = v === undefined || v === null ? '' : JSON.stringify(v); jerr.value = ''; }, { immediate: true });
function setJson(v: string) {
  if (!v.trim()) { jerr.value = ''; emit('set', null); return; }
  try { const x = JSON.parse(v); jerr.value = ''; emit('set', x); } catch (e: any) { jerr.value = $t('paramInput.invalidJson') + e.message; }
}
</script>
