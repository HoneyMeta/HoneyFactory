<template>
  <!-- Drawing symbols for control / communication / information system equipment (screen pixels, centered at 0,0, about 36 px wide). Layer colors: control orange, communication purple, information systems green -->
  <g :class="['lsym', 'lsym-' + type]" :style="{ '--lc': color }">
    <template v-if="type === 'plc'">
      <rect x="-17" y="-13" width="34" height="26" rx="2" class="lsym-b" />
      <rect x="-17" y="-13" width="34" height="7" rx="2" class="lsym-f" />
      <rect v-for="i in 4" :key="i" :x="-14 + (i - 1) * 7" y="-3" width="5" height="12" rx="0.8" class="lsym-m" />
      <text x="-14" y="-7.2" class="lsym-t">PLC</text>
      <circle cx="12" cy="-9.5" r="2.2" :class="['lsym-led', state]" />
    </template>
    <template v-else-if="type === 'hmi'">
      <rect x="-15" y="-12" width="30" height="20" rx="2" class="lsym-b" />
      <rect x="-12" y="-9" width="24" height="14" rx="1" class="lsym-f" />
      <path d="M -6 -2 h 5 M -6 1.5 h 9" class="lsym-l2" />
      <path d="M 0 8 V 12 M -6 12.5 H 6" class="lsym-l" />
    </template>
    <template v-else-if="type === 'gateway'">
      <rect x="-16" y="-10" width="32" height="20" rx="4" class="lsym-b" />
      <path d="M -9 -3 H 8 M 5 -6 L 8 -3 L 5 0 M 9 3 H -8 M -5 0 L -8 3 L -5 6" class="lsym-l" />
      <path d="M 10 -10 L 13 -16" class="lsym-l" /><circle cx="13.5" cy="-17" r="1.8" class="lsym-fill" />
    </template>
    <template v-else-if="type === 'switch'">
      <rect x="-19" y="-8" width="38" height="16" rx="2" class="lsym-b" />
      <rect v-for="i in 6" :key="i" :x="-15.5 + (i - 1) * 5.4" y="-1" width="3.6" height="4" class="lsym-fill" />
      <circle cx="-14" cy="-4.5" r="1.1" class="lsym-fill" /><circle cx="-10.5" cy="-4.5" r="1.1" class="lsym-fill" />
    </template>
    <template v-else-if="type === 'scada'">
      <rect x="-16" y="-13" width="32" height="21" rx="2" class="lsym-b" />
      <rect x="-13" y="-10" width="26" height="15" rx="1" class="lsym-f" />
      <polyline points="-10,2 -5,-3 -1,0 4,-6 9,-2" class="lsym-l2" />
      <path d="M 0 8 V 12 M -7 12.5 H 7" class="lsym-l" />
    </template>
    <template v-else>
      <!-- mes / other servers: rack -->
      <rect x="-12" y="-15" width="24" height="30" rx="2" class="lsym-b" />
      <path d="M -12 -5 H 12 M -12 5 H 12" class="lsym-l" />
      <circle v-for="i in 3" :key="i" cx="7.5" :cy="-10 + (i - 1) * 10" r="1.4" class="lsym-fill" />
      <text x="-9" y="-7.5" class="lsym-t lsym-t2">{{ type === 'mes' ? 'MES' : '' }}</text>
    </template>
  </g>
</template>

<script setup lang="ts">
defineProps<{ type: string; color: string; state?: string }>();
</script>
