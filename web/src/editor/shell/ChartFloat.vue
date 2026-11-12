<template>
  <div class="cf">
    <div class="cf-bar"><span class="muted small">{{ sid }} · {{ tag }}</span><span class="grow" />
      <el-select v-model="h" size="small" style="width:84px" @change="load"><el-option v-for="x in [1, 4, 12, 24]" :key="x" :value="x" :label="x + $t('common.hours2')" /></el-select></div>
    <Chart v-if="data" :option="opt" :height="height" @click="onClick" />
    <p class="muted small cf-tip">{{ $t('chartFloat.clickAPointOnThe') }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { get, P } from '../../api';
import Chart from '../../components/Chart.vue';
import { ed } from '../store';

const props = defineProps<{ sid: string; tag: string; hours?: number }>();
const h = ref(props.hours || 4), data = ref<any>(null);
const height = 220;
const opt = computed(() => ({ tooltip: { trigger: 'axis' }, grid: { left: 46, right: 10, top: 12, bottom: 24 }, xAxis: { type: 'category', data: data.value.t },
  yAxis: { type: 'value', scale: true }, series: [{ type: 'line', showSymbol: false, data: data.value.v, areaStyle: { opacity: 0.08 } }] }));
let timer: any = null;
async function load() { data.value = await get(`${P(ed.pid)}/signals/trend?key=${encodeURIComponent(props.sid + '/' + props.tag)}&hours=${h.value}`, true).catch(() => null); }
function onClick(p: any) {
  const label = data.value?.t?.[p.dataIndex]; if (!label) return;
  window.dispatchEvent(new CustomEvent('vf:replay-to', { detail: { label } }));
}
onMounted(() => { load(); timer = setInterval(load, 5000); });
onUnmounted(() => clearInterval(timer));
</script>
