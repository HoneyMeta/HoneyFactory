<template>
  <div class="chl">
    <div v-for="c in items" :key="c.coll + c.id" class="chl-i click" @click="emit('pick', c.id)">
      <span :class="['k', c.kind]">{{ { add: $t('common.add'), remove: $t('common.delete'), change: $t('common.edit2') }[c.kind as string] }}</span>
      <span>{{ $t('changeList.n01', [c.label, c.name]) }}</span><span class="mono muted">{{ c.id }}</span>
      <div v-if="c.changes?.length" class="chl-d">
        <div v-for="x in c.changes.slice(0, 6)" :key="x.path" class="mono small"><span class="muted">{{ x.path }}</span> {{ short(x.old) }} → <b>{{ short(x.new) }}</b></div>
        <div v-if="c.changes.length > 6" class="muted small">{{ $t('changeList.n0MoreItems', [c.changes.length - 6]) }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ items: any[] }>();
const emit = defineEmits<{ (e: 'pick', id: string): void }>();
const short = (v: any) => { const s = v === undefined || v === null ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v); return s.length > 40 ? s.slice(0, 39) + '…' : s; };
</script>
