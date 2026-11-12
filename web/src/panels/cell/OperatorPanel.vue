<template>
  <div class="opp" :class="{ big }">
    <template v-for="c in comps" :key="c.id">
      <button v-if="c.type === 'button'" :data-tour="'btn-' + c.id" class="pb" :class="['c-' + (c.params?.color || 'green'), { down: v(c)?.s }]" :title="tip(c)"
        @pointerdown.prevent="down(c, $event)" @pointerup="up(c)" @pointerleave="v(c)?.s && up(c)">
        <span class="cap">{{ name(c) }}</span><small v-if="big" class="nc">{{ latched.has(c.id) ? $t('operatorPanel.heldDown') : c.params?.nc ? $t('common.nc') : $t('common.no3') }}</small></button>
      <button v-else-if="c.type === 'estop'" :data-tour="'btn-' + c.id" class="pb estop" :class="{ on: v(c)?.s }" :title="v(c)?.s ? $t('operatorPanel.eStopIsLatchedClick') : $t('operatorPanel.eStopNormallyClosed1')"
        @click="act(c.id, v(c)?.s ? 'release' : 'press')">{{ v(c)?.s ? $t('common.reset') : $t('operatorPanel.eStop') }}</button>
      <button v-else-if="c.type === 'switch'" class="pb sw" :class="{ on: v(c)?.s }" @click="act(c.id, 'toggle')">{{ $t('common.n01', [name(c), v(c)?.s ? $t('operatorPanel.on') : $t('operatorPanel.off')]) }}</button>
      <span v-else-if="c.type === 'potentiometer'" class="pot">{{ name(c) }}
        <el-slider :model-value="v(c)?.s || 0" :max="c.params?.max || 1000" size="small" style="width: 110px" @change="(x: any) => act(c.id, 'set', x)" /></span>
      <span v-else-if="c.type === 'lamp'" :data-tour="'lamp-' + c.id" class="lamp" :class="['c-' + (c.params?.color || 'green'), { on: v(c)?.on }]"><i />{{ name(c) }}</span>
      <span v-else-if="c.type === 'display'" class="disp mono">{{ name(c) }} <b>{{ v(c)?.v ?? 0 }}</b></span>
    </template>
    <span v-if="!comps.length" class="muted small">{{ $t('operatorPanel.thisCellHasNoOperator') }}</span>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Cell operator panel: buttons (hold to press), E-Stop (latching, click to reset), selector switches, potentiometers, indicator lamps, and numeric displays. Buttons use /cells/{bid}/panel; also available in student sandboxes.
import { computed, reactive } from 'vue';
import { toast } from '../../api';
import { press } from './state';

const props = defineProps<{ pid: string; cell: any; live: any; big?: boolean }>();
const TYPES = ['estop', 'button', 'switch', 'potentiometer', 'lamp', 'display'];
const comps = computed(() => (props.cell?.components || []).filter((c: any) => TYPES.includes(c.type))
  .sort((a: any, b: any) => (a.pos?.[0] ?? 0) - (b.pos?.[0] ?? 0)));
const v = (c: any) => props.live?.comps?.[c.id];
const name = (c: any) => c.label || c.params?.label || c.id;
const tip = (c: any) => $t('operatorPanel.n0HoldToPress1', [c.id, c.params?.nc ? $t('operatorPanel.ncContact1WhenReleased') : $t('operatorPanel.noContact1WhenPressed')]);
/** Shift+click: latch a button in the pressed state (the mouse can only hold one button; use this to press Start and Stop simultaneously). */
const latched = reactive(new Set<string>());
function down(c: any, e: PointerEvent) {
  if (e.shiftKey) {
    if (latched.has(c.id)) { latched.delete(c.id); act(c.id, 'release'); } else { latched.add(c.id); act(c.id, 'set', 1); }
    return;
  }
  act(c.id, 'set', 1);
}
function up(c: any) { if (!latched.has(c.id)) act(c.id, 'release'); }
async function act(comp: string, action: string, value: any = null) {
  try { await press(props.pid, comp, action, value); } catch (e: any) { toast(e.message || String(e)); }
}
</script>

<style scoped>
.opp { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.pb { border: none; border-radius: 14px; padding: 5px 12px; color: #fff; font-weight: 600; cursor: pointer; font-size: 12px; user-select: none;
  box-shadow: inset 0 -2px 0 rgba(0, 0, 0, .25); display: inline-flex; flex-direction: column; align-items: center; line-height: 1.2; }
.pb:active, .pb.down { transform: translateY(1px); box-shadow: inset 0 1px 3px rgba(0, 0, 0, .4); filter: brightness(.9); }
.pb .nc { font-weight: 400; font-size: 10px; opacity: .85; }
.pb.c-green { background: #1f9d55; } .pb.c-red { background: #d23c3c; } .pb.c-yellow { background: #d9a400; } .pb.c-blue { background: #2c66ad; }
.pb.c-white { background: #e8ecef; color: #1d2125; } .pb.c-black { background: #2a2f35; }
.pb.estop { background: #d42a24; border: 3px solid #f2c230; border-radius: 50%; width: 56px; height: 56px; padding: 0; font-size: 11px; justify-content: center; }
.pb.estop.on { background: #7a1512; box-shadow: inset 0 2px 6px rgba(0, 0, 0, .5); }
.pb.sw { background: var(--el-color-info); border-radius: 4px; } .pb.sw.on { background: var(--el-color-success); }
.lamp { display: inline-flex; align-items: center; gap: 4px; font-size: 11.5px; }
.lamp i { width: 12px; height: 12px; border-radius: 50%; background: var(--el-fill-color-darker); box-shadow: inset 0 0 0 1px var(--el-border-color-darker); }
.lamp.on.c-green i { background: #22c55e; box-shadow: 0 0 8px #22c55e; } .lamp.on.c-red i { background: #ef4444; box-shadow: 0 0 8px #ef4444; }
.lamp.on.c-yellow i { background: #f5c518; box-shadow: 0 0 8px #f5c518; } .lamp.on.c-blue i { background: #3b82f6; box-shadow: 0 0 8px #3b82f6; }
.disp b { background: #0c0f12; color: #ff3b30; padding: 1px 6px; border-radius: 3px; font-family: Consolas, monospace; letter-spacing: 1px; }
.pot { display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; }
.mono { font-family: Consolas, monospace; } .muted { color: var(--el-text-color-secondary); } .small { font-size: 11.5px; }
/* Large buttons (floating operator panel) */
.opp.big { gap: 10px; }
.opp.big .pb { min-width: 74px; min-height: 46px; font-size: 14px; border-radius: 10px; justify-content: center; }
.opp.big .pb.estop { min-width: 0; width: 66px; height: 66px; border-radius: 50%; font-size: 13px; }
.opp.big .lamp { font-size: 13px; } .opp.big .lamp i { width: 18px; height: 18px; }
.opp.big .disp { font-size: 13px; } .opp.big .disp b { font-size: 18px; padding: 2px 8px; }
</style>
