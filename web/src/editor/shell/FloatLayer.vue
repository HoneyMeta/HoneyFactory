<template>
  <div class="fl-layer">
    <div v-for="w in ed.floats" :key="w.id" class="fw" :data-float="w.id" :class="{ max: w.max, top: w.z === topZ }"
      :style="w.max ? { zIndex: w.z } : { left: w.x + 'px', top: w.y + 'px', width: w.w + 'px', height: w.h + 'px', zIndex: w.z }" @pointerdown="front(w)">
      <header class="fw-h" @pointerdown="startDrag($event, w)" @dblclick="w.max = !w.max">
        <el-icon><component :is="w.icon || 'Document'" /></el-icon><b>{{ w.title }}</b><span class="grow" />
        <button class="fw-b" :title="w.max ? $t('floatLayer.restore') : $t('floatLayer.maximize')" @pointerdown.stop @click="w.max = !w.max"><el-icon><component :is="w.max ? 'CopyDocument' : 'FullScreen'" /></el-icon></button>
        <button class="fw-b" :title="$t('common.close')" @pointerdown.stop @click="closeFloat(w.id)"><el-icon><Close /></el-icon></button>
      </header>
      <div class="fw-body"><component :is="w.component" v-bind="w.props" /></div>
      <i v-if="!w.max" class="fw-rs" @pointerdown.stop="startResize($event, w)" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { closeFloat, ed } from '../store';

const topZ = computed(() => Math.max(0, ...ed.floats.map((w: any) => w.z)));
function front(w: any) { if (w.z !== topZ.value) w.z = topZ.value + 1; }
function track(e: PointerEvent, move: (dx: number, dy: number) => void) {
  const x0 = e.clientX, y0 = e.clientY;
  const mv = (ev: PointerEvent) => move(ev.clientX - x0, ev.clientY - y0);
  const up = () => { removeEventListener('pointermove', mv); removeEventListener('pointerup', up); };
  addEventListener('pointermove', mv); addEventListener('pointerup', up);
}
function startDrag(e: PointerEvent, w: any) {
  if (w.max || (e.target as HTMLElement).closest('button')) return;
  const x = w.x, y = w.y;
  track(e, (dx, dy) => { w.x = Math.max(0, Math.min(innerWidth - 120, x + dx)); w.y = Math.max(0, Math.min(innerHeight - 60, y + dy)); });
}
function startResize(e: PointerEvent, w: any) {
  const ww = w.w, hh = w.h;
  track(e, (dx, dy) => { w.w = Math.max(320, ww + dx); w.h = Math.max(200, hh + dy); });
}
</script>
