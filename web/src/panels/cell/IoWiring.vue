<template>
  <div class="iow">
    <div class="iow-bar muted small">
      <span>{{ $t('ioWiring.wiringDiagramOnTheLeft') }}</span>
      <span class="grow" />
      <span class="lg"><i class="on" />{{ $t('ioWiring.energizedValue1') }}</span><span class="lg"><i />{{ $t('common.disconnected') }}</span>
    </div>
    <svg :viewBox="`0 0 ${W} ${H}`" class="iow-svg" :style="{ height: H * scale + 'px' }">
      <!-- Power bus -->
      <line :x1="XL" :y1="Y0 - 18" :x2="XL" :y2="H - 18" class="rail p" />
      <text :x="XL" :y="Y0 - 24" class="rl">L+ 24V</text>
      <line :x1="XR" :y1="Y0 - 18" :x2="XR" :y2="H - 18" class="rail m" />
      <text :x="XR" :y="Y0 - 24" class="rl">M 0V</text>
      <!-- PLC module -->
      <rect :x="PX" :y="Y0 - 20" :width="PW" :height="H - Y0 + 4" rx="6" class="plc" />
      <text :x="PX + PW / 2" :y="Y0 - 6" class="plct">{{ plcName || 'PLC' }}</text>
      <text :x="PX + PW / 2" :y="Y0 + 8" class="plcs">{{ plcLabel }}</text>
      <text :x="PX + 8" :y="H - 24" class="term">1M → M</text>
      <line :x1="PX + 2" :y1="H - 20" :x2="XR" :y2="H - 20" class="w" stroke-dasharray="4 3" />
      <!-- Inputs -->
      <g v-for="(e, i) in ins" :key="e.name" :transform="`translate(0, ${Y0 + 18 + Number(i) * RH})`" :class="{ on: on(e) }">
        <title>{{ e.comment || e.name }}</title>
        <template v-if="e.type === 'BOOL'">
          <line :x1="XL" y1="0" :x2="XL + 40" y2="0" class="w" />
          <!-- Contact symbols: NO = raised blade; NC = lowered blade with stop -->
          <g :transform="`translate(${XL + 40}, 0)`">
            <circle cx="0" cy="0" r="2" class="dotp" /><circle cx="22" cy="0" r="2" class="dotp" />
            <line v-if="e.contact === 'NC'" x1="0" y1="0" x2="24" y2="4" class="blade" />
            <line v-else x1="0" y1="0" x2="20" y2="-10" class="blade" />
            <line v-if="e.contact === 'NC'" x1="22" y1="-7" x2="22" y2="0" class="w" />
            <text x="11" y="-12" class="ct" :class="{ nc: e.contact === 'NC' }">{{ e.contact === 'NC' ? $t('common.nc') : $t('common.no3') }}</text>
          </g>
          <line :x1="XL + 64" y1="0" :x2="PX" y2="0" class="w" />
        </template>
        <template v-else>
          <rect :x="XL + 30" y="-9" width="44" height="18" rx="3" class="ana" />
          <text :x="XL + 52" y="4" class="anat">{{ $t('ioWiring.dataWord') }}</text>
          <line :x1="XL + 74" y1="0" :x2="PX" y2="0" class="w" />
        </template>
        <text :x="XL + 82" y="-4" class="dev">{{ devName(e) }}</text>
        <text :x="PX - 6" y="13" class="nm">{{ e.name }}<tspan class="val"> = {{ fmt(val(e)) }}</tspan></text>
        <circle :cx="PX" cy="0" r="3.5" class="term-dot" />
        <text :x="PX + 8" y="4" class="addr" :class="{ nw: !chOf(e) }">{{ chOf(e) || $t('cellEditor.notConnected') }}</text>
      </g>
      <!-- Outputs -->
      <g v-for="(e, i) in outs" :key="e.name" :transform="`translate(0, ${Y0 + 18 + Number(i) * RH})`" :class="{ on: on(e) }">
        <title>{{ e.comment || e.name }}</title>
        <text :x="PX + PW - 8" y="4" class="addr r" :class="{ nw: !chOf(e) }">{{ chOf(e) || $t('cellEditor.notConnected') }}</text>
        <circle :cx="PX + PW" cy="0" r="3.5" class="term-dot" />
        <line :x1="PX + PW" y1="0" :x2="XR - 66" y2="0" class="w" />
        <g :transform="`translate(${XR - 54}, 0)`">
          <template v-if="e.type !== 'BOOL'"><rect x="-12" y="-9" width="24" height="18" rx="3" class="ana" /></template>
          <template v-else-if="isLamp(e)"><circle cx="0" cy="0" r="9" class="load" /><line x1="-6" y1="-6" x2="6" y2="6" class="w" /><line x1="-6" y1="6" x2="6" y2="-6" class="w" /></template>
          <template v-else><rect x="-12" y="-8" width="24" height="16" class="load" /></template>
        </g>
        <line :x1="XR - 42" y1="0" :x2="XR" y2="0" class="w" />
        <text :x="PX + PW + 10" y="-4" class="dev">{{ devName(e) }}</text>
        <text :x="PX + PW + 10" y="13" class="nm l">{{ e.name }}<tspan class="val"> = {{ fmt(val(e)) }}</tspan></text>
      </g>
    </svg>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Simplified I/O wiring diagram: button/sensor NO and NC contacts connect to PLC input terminals; PLC output terminals connect to coils/indicator lamps. Shows live on/off states.
import { computed } from 'vue';

// wiring: PLC and channel connected to each cell I/O (wiring from server /cells/{bid}/io); terminals display PLC channels
const props = defineProps<{ cell: any; values?: Record<string, any>; plcState?: string; plcName?: string; wiring?: Record<string, any[]> | null }>();
const W = 760, RH = 34, Y0 = 46, XL = 24, XR = 736, PX = 300, PW = 160;
const scale = 1;
const ins = computed(() => (props.cell?.io || []).filter((e: any) => e.dir === 'in'));
const outs = computed(() => (props.cell?.io || []).filter((e: any) => e.dir === 'out'));
const H = computed(() => Y0 + 30 + Math.max(ins.value.length, outs.value.length, 1) * RH + 20);
const comps = computed(() => Object.fromEntries((props.cell?.components || []).map((c: any) => [c.id, c])));
const plcLabel = computed(() => (props.wiring && !Object.keys(props.wiring).length ? $t('cellEditor.noPlcConnected')
  : (props.cell?.plc?.mode === 'external' ? $t('common.externalPlc') : $t('ioWiring.softPlc')) + (props.plcState && props.plcState !== 'NONE' ? ` · ${props.plcState}` : '')));
/** Terminal label: use the PLC channel (I0.0) when wired; fall back to the cell I/O table address if wiring data is unavailable. */
const chOf = (e: any) => (props.wiring ? (props.wiring[e.name]?.[0]?.ch || '') : String(e.addr || '').replace(/^%/, ''));
const val = (e: any) => props.values?.[e.name];
const on = (e: any) => !!val(e) && (e.type || 'BOOL') === 'BOOL';
const fmt = (v: any) => (v === undefined || v === null ? '—' : typeof v === 'boolean' ? (v ? 1 : 0) : v);
const isLamp = (e: any) => ['lamp'].includes(comps.value[e.comp]?.type);
const TYPE_CN: Record<string, string> = { button: $t('common.button'), estop: $t('ioWiring.eStopButton'), switch: $t('ioWiring.selectorSwitch'), potentiometer: $t('ioWiring.potentiometer'), diffuse_sensor: $t('ioWiring.diffusePhotoEye'),
  retro_sensor: $t('ioWiring.throughBeamPhotoEye'), capacitive: $t('ioWiring.capacitiveProximitySwitch'), inductive: $t('ioWiring.inductiveProximitySwitch'), vision_sensor: $t('ioWiring.vision'), height_sensor: $t('ioWiring.heightMeasurement'), encoder: $t('ioWiring.encoder'), motor: $t('ioWiring.motor'),
  lamp: $t('ioWiring.indicatorLamp'), display: $t('ioWiring.sevenSegmentDisplay'), pusher: $t('ioWiring.pusherSolenoidValve'), stopper: $t('ioWiring.stopperSolenoidValve'), belt_conveyor: $t('ioWiring.conveyorContactor'), roller_conveyor: $t('ioWiring.conveyorContactor'),
  curved_conveyor: $t('ioWiring.conveyorContactor'), turntable: $t('ioWiring.turntable'), lift: $t('ioWiring.liftTable'), pick_place: $t('ioWiring.manipulator'), stacker_crane: $t('ioWiring.stackerCrane'), gripper: $t('ioWiring.gripper'), pivot_arm: $t('ioWiring.swingArm'),
  chain_transfer: $t('ioWiring.transferUnit'), emitter: $t('ioWiring.hopper'), cell_entry: $t('ioWiring.cellInlet'), cell_exit: $t('ioWiring.cellOutlet') };
function devName(e: any) {
  const c = comps.value[e.comp];
  const lab = c?.label || c?.params?.label || '';
  return `${TYPE_CN[c?.type] || c?.type || ''}${lab ? ' ' + lab : ''} · ${e.signal}`;
}
</script>

<style scoped>
.iow { display: flex; flex-direction: column; gap: 4px; }
.iow-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.iow-bar .grow { flex: 1; }
.lg { display: inline-flex; align-items: center; gap: 4px; }
.lg i { width: 16px; height: 3px; background: var(--el-text-color-secondary); display: inline-block; } .lg i.on { background: var(--el-color-success); }
.iow-svg { width: 100%; min-width: 560px; }
.rail { stroke-width: 3; } .rail.p { stroke: var(--el-color-danger); } .rail.m { stroke: var(--el-color-primary); }
.rl { font-size: 11px; text-anchor: middle; fill: var(--el-text-color-regular); font-weight: 600; }
.plc { fill: var(--el-fill-color-light); stroke: var(--el-border-color-darker); stroke-width: 1.5; }
.plct { font-size: 14px; font-weight: 700; text-anchor: middle; fill: var(--el-text-color-primary); }
.plcs { font-size: 10.5px; text-anchor: middle; fill: var(--el-text-color-secondary); }
.term { font-size: 10px; fill: var(--el-text-color-secondary); }
.w { stroke: var(--el-text-color-secondary); stroke-width: 1.4; fill: none; }
.blade { stroke: var(--el-text-color-primary); stroke-width: 2; }
.dotp { fill: var(--el-text-color-primary); }
.ct { font-size: 9.5px; text-anchor: middle; fill: var(--el-text-color-secondary); } .ct.nc { fill: var(--el-color-warning-dark-2); font-weight: 700; }
.dev { font-size: 10.5px; fill: var(--el-text-color-secondary); }
.nm { font-size: 11px; text-anchor: end; font-family: Consolas, monospace; fill: var(--el-text-color-primary); font-weight: 600; } .nm.l { text-anchor: start; }
.val { font-weight: 400; fill: var(--el-text-color-secondary); }
.addr { font-size: 10.5px; font-family: Consolas, monospace; fill: var(--el-text-color-regular); } .addr.r { text-anchor: end; }
.addr.nw { fill: var(--el-color-warning-dark-2); font-family: inherit; }
.term-dot { fill: var(--el-bg-color); stroke: var(--el-text-color-regular); stroke-width: 1.4; }
.ana { fill: var(--el-fill-color); stroke: var(--el-text-color-secondary); } .anat { font-size: 9.5px; text-anchor: middle; fill: var(--el-text-color-secondary); }
.load { fill: var(--el-bg-color); stroke: var(--el-text-color-regular); stroke-width: 1.4; }
g.on .w, g.on .blade { stroke: var(--el-color-success); } g.on .term-dot { fill: var(--el-color-success); stroke: var(--el-color-success); }
g.on .load { fill: color-mix(in srgb, var(--el-color-success) 30%, transparent); stroke: var(--el-color-success); } g.on .val { fill: var(--el-color-success); font-weight: 700; }
.muted { color: var(--el-text-color-secondary); } .small { font-size: 11.5px; }
</style>
