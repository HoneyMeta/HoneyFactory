<template>
  <div class="gn" :class="{ sel: selected, col: g.collapsed }" :style="{ '--c': g.color || '#3b82c4', width: data.w + 'px', height: data.h + 'px' }">
    <div class="gn-h">
      <el-icon class="click" @click.stop="toggle"><component :is="g.collapsed ? 'CaretRight' : 'CaretBottom'" /></el-icon>
      <b>{{ g.name }}</b><small>{{ $t('groupNode.n0Blocks', [data.count]) }}</small>
    </div>
    <div v-if="g.collapsed" class="gn-body">
      <span v-for="s in data.states" :key="s[0]" class="gn-st"><i :style="{ background: STATE_COLOR[s[0]] || '#888' }" />{{ STATE_CN[s[0]] || s[0] }} {{ s[1] }}</span>
    </div>
    <Handle v-if="g.collapsed" type="target" :position="Position.Left" id="in" :connectable="false" />
    <Handle v-if="g.collapsed" type="source" :position="Position.Right" id="out" :connectable="false" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { Handle, Position } from '@vue-flow/core';
import { computed } from 'vue';
import { ed, exec, STATE_CN, STATE_COLOR } from './store';

const props = defineProps<{ id: string; data: any; selected?: boolean }>();
const g = computed(() => (ed.model.groups || []).find((x: any) => x.id === props.id) || {});
function toggle() { exec([{ op: 'update_group', id: props.id, set: { collapsed: !g.value.collapsed } }], g.value.collapsed ? $t('common.expandGroup') : $t('details.collapseGroup')); }
</script>
