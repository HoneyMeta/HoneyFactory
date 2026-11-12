<template>
  <div class="nn" :class="{ sel: selected }">
    <textarea :value="n.text" :placeholder="$t('noteNode.writeANote')" class="nodrag" @change="(e: any) => exec([{ op: 'update_note', id, set: { text: e.target.value } }], $t('details.editComment'))" />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { ed, exec } from './store';

const props = defineProps<{ id: string; data: any; selected?: boolean }>();
const n = computed(() => (ed.model.notes || []).find((x: any) => x.id === props.id) || {});
</script>
