<template>
  <!-- Rulers (top, left), scale bar (top left; reserve bottom left for the selection bar), compass (bottom right): screen coordinates, unaffected by zoom, for screenshots and exports -->
  <g class="pr" pointer-events="none">
    <g v-if="rulers">
      <rect :x="0" :y="0" :width="w" :height="RS" class="pr-bg" />
      <rect :x="0" :y="0" :width="RS" :height="h" class="pr-bg" />
      <line :x1="RS" :y1="RS - 0.5" :x2="w" :y2="RS - 0.5" class="pr-edge" /><line :x1="RS - 0.5" :y1="RS" :x2="RS - 0.5" :y2="h" class="pr-edge" />
      <template v-for="t in xt" :key="'x' + t.v">
        <line :x1="t.p" :y1="t.major ? 4 : RS - 5" :x2="t.p" :y2="RS" class="pr-t" />
        <text v-if="t.major" :x="t.p + 3" :y="11" class="pr-n">{{ t.txt }}</text>
      </template>
      <template v-for="t in yt" :key="'y' + t.v">
        <line :x1="t.major ? 4 : RS - 5" :y1="t.p" :x2="RS" :y2="t.p" class="pr-t" />
        <text v-if="t.major" :x="11" :y="t.p + 3" class="pr-n" :transform="`rotate(-90 11 ${t.p + 3})`">{{ t.txt }}</text>
      </template>
      <path v-if="cx > RS" :d="`M ${cx} ${RS} l -4 -6 h 8 z`" class="pr-cur" />
      <path v-if="cy > RS" :d="`M ${RS} ${cy} l -6 -4 v 8 z`" class="pr-cur" />
      <rect :x="0" :y="0" :width="RS" :height="RS" class="pr-bg" /><text :x="RS / 2" :y="12" class="pr-n pr-m">m</text>
    </g>
    <g :transform="`translate(${(rulers ? RS : 0) + 14},${(rulers ? RS : 0) + 30})`" class="pr-scale">
      <rect x="-6" y="-17" :width="bar.px + 40" height="26" rx="4" class="pr-plate" />
      <rect v-for="i in 4" :key="i" :x="(i - 1) * bar.px / 4" y="-4" :width="bar.px / 4" height="6" :class="i % 2 ? 'pr-b' : 'pr-w'" />
      <rect x="0" y="-4" :width="bar.px" height="6" class="pr-o" />
      <text x="0" y="-7" class="pr-n">0</text><text :x="bar.px" y="-7" class="pr-n pr-c">{{ bar.txt }}</text>
    </g>
    <g :transform="`translate(${w - 34},${(rulers ? RS : 0) + 32})`" class="pr-north">
      <circle r="19" class="pr-plate" />
      <g :transform="`rotate(${north || 0})`">
        <path d="M 0 -3 L 5.5 13 L 0 9 L -5.5 13 Z" class="pr-arrow" /><text x="0" y="-5" class="pr-n pr-c pr-nn">{{ $t('planRulers.n') }}</text>
      </g>
    </g>
  </g>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { niceStep } from './geom';

const props = defineProps<{ k: number; tx: number; ty: number; w: number; h: number; cursor: number[]; north?: number; rulers?: boolean }>();
const RS = 18;
const fmt = (x: number, st: number) => (st >= 1 ? String(Math.round(x)) : x.toFixed(st >= 0.1 ? 1 : 2));
function ticks(off: number, len: number) {
  const major = niceStep(64 / props.k), minor = major / (major * props.k >= 120 ? 10 : 5);
  const out: { v: number; p: number; major: boolean; txt: string }[] = [];
  const a = (RS - off) / props.k, b = (len - off) / props.k;
  if (minor * props.k < 5) return out;
  for (let v = Math.ceil(a / minor) * minor; v <= b; v += minor) {
    const isMaj = Math.abs(v / major - Math.round(v / major)) < 1e-6;
    out.push({ v: +v.toFixed(4), p: Math.round(off + v * props.k) + 0.5, major: isMaj, txt: fmt(v, major) });
    if (out.length > 600) break;
  }
  return out;
}
const xt = computed(() => ticks(props.tx, props.w));
const yt = computed(() => ticks(props.ty, props.h));
const cx = computed(() => props.tx + props.cursor[0] * props.k);
const cy = computed(() => props.ty + props.cursor[1] * props.k);
const bar = computed(() => { const m = niceStep(90 / props.k); return { px: m * props.k, txt: (m >= 1 ? m : +m.toFixed(2)) + ' m' }; });
</script>
