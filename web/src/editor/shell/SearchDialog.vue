<template>
  <el-dialog v-model="ed.searchOpen" :title="$t('searchDialog.find')" width="560px" append-to-body top="12vh" @opened="focus">
    <el-input ref="inp" v-model="q" :placeholder="$t('searchDialog.equipmentNameIdPlcChannel')" clearable @keydown.enter="pick(results[0])" @keydown.down.prevent="move(1)" @keydown.up.prevent="move(-1)" />
    <div class="sd-list">
      <div v-for="(r, i) in results" :key="r.key" class="sd-i" :class="{ on: i === cur }" @click="pick(r)" @mouseenter="cur = i">
        <i class="sd-ly" :style="{ background: r.color }" /><b>{{ r.title }}</b><small class="muted">{{ r.sub }}</small>
      </div>
      <p v-if="q && !results.length" class="muted small">{{ $t('searchDialog.nothingFound') }}</p>
      <p v-if="!q" class="muted small">{{ $t('searchDialog.searchEquipmentPlcsAndGateways') }}</p>
    </div>
  </el-dialog>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Find (Ctrl+F, 4.3): search any object by name, ID, type, IP, PLC channel, or signal tag; press Enter or click to select and locate it.
import { computed, nextTick, ref, watch } from 'vue';
import { blocksById, ed, typeOf } from '../store';
import { goTo, linkKind } from './relations';

const q = ref(''), cur = ref(0), inp = ref<any>(null);
const color = (id: string) => ed.cat?.layers?.[typeOf(blocksById.value[id])?.layer || 'process']?.color || '#888';
const results = computed(() => {
  const k = q.value.trim().toLowerCase(); if (!k) return [];
  const out: any[] = [];
  for (const b of ed.model?.blocks || []) {
    const t = typeOf(b), hay = [b.name, b.id, t.label, b.params?.ip].filter(Boolean).join(' ').toLowerCase();
    if (hay.includes(k)) out.push({ key: 'b' + b.id, id: b.id, title: b.name, sub: `${b.id} · ${t.label}${b.params?.ip ? ' · ' + b.params.ip : ''}`, color: color(b.id) });
  }
  for (const l of ed.model?.links || []) {
    if (linkKind(l) !== 'signal') continue;
    for (const s of l.signals || []) {
      if (!(`${s.point} ${s.ch}`.toLowerCase().includes(k))) continue;
      const dev = blocksById.value[l.from]?.type === 'plc' ? l.to : l.from, plc = dev === l.from ? l.to : l.from;
      out.push({ key: `s${l.id}${s.point}${s.ch}`, id: dev, title: $t('common.n012', [s.point, s.ch]), sub: `${blocksById.value[dev]?.name || dev} ${s.dir === 'in' ? '→' : '←'} ${blocksById.value[plc]?.name || plc}`, color: '#e07a20' });
    }
  }
  return out.slice(0, 40);
});
watch(q, () => { cur.value = 0; });
function move(d: number) { cur.value = Math.max(0, Math.min(results.value.length - 1, cur.value + d)); }
function pick(r: any) { if (!r) return; ed.searchOpen = false; goTo(r.id); }
function focus() { nextTick(() => inp.value?.focus()); }
// Focus immediately on open (before the animation ends) and select all previous text
watch(() => ed.searchOpen, (v) => { if (v) setTimeout(() => { inp.value?.focus(); inp.value?.select?.(); }, 30); });
</script>

<style>
.sd-list { margin-top: 8px; max-height: 50vh; overflow-y: auto; }
.sd-i { display: flex; align-items: center; gap: 8px; padding: 6px 8px; border-radius: 6px; cursor: pointer; }
.sd-i.on, .sd-i:hover { background: var(--hm-primary-soft); color: var(--hm-setup-ink); } .sd-i small { margin-left: auto; }
.sd-ly { width: 10px; height: 10px; border-radius: 3px; flex: none; }
</style>
