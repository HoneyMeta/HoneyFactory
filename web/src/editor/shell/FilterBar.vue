<template>
  <el-popover placement="bottom-end" :width="260" trigger="click">
    <template #reference>
      <el-button class="fb-btn" size="small" :type="anyOff ? 'warning' : ''"><el-icon><Filter /></el-icon>{{ $t('filterBar.show') }}</el-button>
    </template>
    <div class="fb">
      <div class="fb-h">{{ $t('filterBar.showByLayer') }}</div>
      <label v-for="(v, k) in layers" :key="k" class="fb-row">
        <el-checkbox :model-value="ed.filter.layers[k] !== false" @change="(x: any) => set('layers', String(k), x)" />
        <i class="fb-sw" :style="{ background: v.color }" />{{ v.label }}
      </label>
      <div class="fb-h">{{ $t('common.connections') }}</div>
      <label v-for="(v, k) in links" :key="k" class="fb-row">
        <el-checkbox :model-value="ed.filter.links[k] !== false" @change="(x: any) => set('links', String(k), x)" />
        <i class="fb-ln" :class="k" :style="{ borderColor: v.color }" />{{ v.label }}
      </label>
      <el-button size="small" text @click="reset">{{ $t('filterBar.showAll') }}</el-button>
    </div>
  </el-popover>
</template>

<script setup lang="ts">
// Layer filters (4.3): production equipment / control / communications / information systems; connections: material / signal / network. All views share ed.filter and retain selections.
import { computed } from 'vue';
import { ed } from '../store';
import { defaultFilter, saveFilter } from './relations';

const layers = computed(() => { const l = { ...(ed.cat?.layers || {}) }; delete l.field; return l; });
const links = computed(() => ed.cat?.link_kinds || {});
const anyOff = computed(() => [...Object.values(ed.filter?.layers || {}), ...Object.values(ed.filter?.links || {})].some((x) => x === false));
function set(group: 'layers' | 'links', k: string, v: boolean) { ed.filter = { ...ed.filter, [group]: { ...ed.filter[group], [k]: v } }; saveFilter(); }
function reset() { ed.filter = defaultFilter(); saveFilter(); }
</script>

<style>
.fb { display: grid; gap: 2px; font-size: 12.5px; } .fb-h { color: var(--el-text-color-secondary); margin: 6px 0 2px; font-size: 11.5px; }
.fb-row { display: flex; align-items: center; gap: 6px; cursor: pointer; }
.fb-sw { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
.fb-ln { width: 22px; height: 0; border-top: 2px solid; display: inline-block; } .fb-ln.signal { border-top-style: dashed; }
</style>
