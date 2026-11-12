<template>
  <!-- Array copy (layout elements and equipment together): opened via "Array…" in the context menu / right properties panel (pv.arrayOpen) -->
  <el-dialog v-model="arr.show" :title="$t('arrayDialog.arrayCopy')" width="360px" append-to-body>
    <div class="pc-arr">
      <div class="pc-f"><label>{{ $t('arrayDialog.columns') }}</label><el-input-number v-model="arr.cols" :min="1" :max="50" size="small" /><label class="l2">{{ $t('arrayDialog.columnSpacing') }}</label><el-input-number v-model="arr.dx" :step="0.5" size="small" :controls="false" /><span class="u">m</span></div>
      <div class="pc-f"><label>{{ $t('arrayDialog.rows') }}</label><el-input-number v-model="arr.rows" :min="1" :max="50" size="small" /><label class="l2">{{ $t('arrayDialog.rowSpacing') }}</label><el-input-number v-model="arr.dy" :step="0.5" size="small" :controls="false" /><span class="u">m</span></div>
      <p class="muted small">{{ $t('arrayDialog.theOriginalCountsAsThe', [arr.rows * arr.cols, arr.rows * arr.cols - 1]) }}</p>
    </div>
    <template #footer><el-button @click="arr.show = false">{{ $t('common.cancel') }}</el-button><el-button type="primary" :disabled="arr.rows * arr.cols < 2" @click="doArray">{{ $t('view3D.array') }}</el-button></template>
  </el-dialog>
</template>

<script setup lang="ts">
import { reactive, watch } from 'vue';
import { arraySel, pv, selBox } from './state';

const arr = reactive({ show: false, rows: 1, cols: 3, dx: 5, dy: 5 });
function openArray() {
  const bb = selBox(); if (!bb) return;
  const up = (x: number) => Math.max(0.5, Math.ceil((x + 1) * 2) / 2);
  Object.assign(arr, { show: true, dx: up(bb.x1 - bb.x0), dy: up(bb.y1 - bb.y0) });
}
function doArray() { arraySel(arr.rows, arr.cols, arr.dx, arr.dy); arr.show = false; }
watch(() => pv.arrayOpen, (v) => { if (v) { pv.arrayOpen = false; openArray(); } }, { immediate: true });
</script>
