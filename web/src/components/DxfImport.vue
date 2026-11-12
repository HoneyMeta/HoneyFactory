<template>
  <div class="dx">
    <div class="row">
      <el-button size="small" @click="pick" :loading="busy"><el-icon><Upload /></el-icon>{{ $t('dxfImport.selectDxfFile') }}</el-button>
      <span class="small muted">{{ $t('common.unit') }}</span>
      <el-select v-model="unit" size="small" style="width:130px" :placeholder="$t('dxfImport.fromFileAuto')"><el-option :label="$t('dxfImport.fromFileAuto')" value="" /><el-option v-for="u in ['mm', 'cm', 'm', 'in', 'ft']" :key="u" :label="u" :value="u" /></el-select>
      <span class="small muted">{{ $t('dxfImport.placeAt') }}</span><el-input-number v-model="ox" size="small" :controls="false" style="width:64px" />,<el-input-number v-model="oy" size="small" :controls="false" style="width:64px" /> m
      <input ref="inp" type="file" accept=".dxf" style="display:none" @change="onFile" />
    </div>
    <div v-if="r" class="info small">
      <div>{{ $t('dxfImport.n01MUnit2', [r.w, r.h, r.unit, r.n_polylines, r.n_texts]) }}<span v-if="r.truncated" class="warn">{{ $t('dxfImport.excessLinesTruncated') }}</span></div>
      <div class="layers">{{ $t('dxfImport.layers') }}<el-checkbox-group v-model="layers" size="small"><el-checkbox v-for="(n, k) in r.layers" :key="k" :value="k">{{ $t('common.n012', [k, n]) }}</el-checkbox></el-checkbox-group>
        <el-button size="small" link type="primary" @click="reparse">{{ $t('dxfImport.regenerateUsingOnlyTheSelected') }}</el-button></div>
      <img :src="r.underlay.url + '&token=' + tok()" class="pv" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * DXF underlay import. props.pid; after upload, the server parses DXF into polylines (meters) and SVG. Event done(result):
 * result.underlay = {url, x, y, w, h, opacity, show, kind:'dxf'} can be assigned directly to model plant.underlay; result.polylines supports snapping.
 */
import { ref } from 'vue';
import { P, post, tok } from '../api';

const props = defineProps<{ pid: string }>();
const emit = defineEmits(['done']);
const inp = ref<HTMLInputElement>(), busy = ref(false), r = ref<any>(null), unit = ref(''), ox = ref(0), oy = ref(0), layers = ref<string[]>([]);
let last = '';
function pick() { inp.value?.click(); }
async function send(data: string, lay?: string[]) {
  busy.value = true;
  try {
    r.value = await post(P(props.pid) + '/underlay/dxf', { data_url: data, unit: unit.value || undefined, origin: [ox.value, oy.value], layers: lay });
    if (!lay) layers.value = Object.keys(r.value.layers);
    emit('done', r.value);
  } finally { busy.value = false; }
}
function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => { last = String(rd.result); send(last); };
  rd.readAsDataURL(f);
  (e.target as HTMLInputElement).value = '';
}
function reparse() { if (last) send(last, layers.value); }
</script>

<style scoped>
.row { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.info { margin-top: 8px; } .layers { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin: 4px 0; }
.pv { max-width: 100%; max-height: 260px; border: 1px solid var(--ln); border-radius: var(--hm-r-sm); background: var(--hm-surface); display: block; margin-top: 6px; }
</style>
