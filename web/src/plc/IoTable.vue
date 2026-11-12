<template>
  <div class="iot" :class="{ compact }">
    <div v-if="!compact" class="iot-bar">
      <b>{{ $t('ioTable.iOMonitor') }}</b><span class="muted">{{ $t('ioTable.fieldSignalsAndPlcOutputs') }}</span>
      <span class="grow" />
      <el-button size="small" :disabled="!nForced || ro" @click="unforceAll"><el-icon><CircleClose /></el-icon>{{ $t('ioTable.removeAllForces0', [nForced]) }}</el-button>
    </div>
    <div class="iot-scroll">
      <table class="tbl">
        <thead><tr><th style="width: 30px" /><th>{{ $t('common.address') }}</th><th>{{ $t('common.name') }}</th><th v-if="dev && !compact" :title="$t('ioTable.theEquipmentAndTagConnected')">{{ $t('ioTable.connectedTo') }}</th><th :title="$t('ioTable.no0WhenNotPressed')">{{ $t('ioTable.contactRestState') }}</th><th v-if="!compact">{{ $t('common.description') }}</th><th v-if="ext">{{ $t('externalPanel.externalAddress') }}</th><th style="width: 76px">{{ $t('common.value') }}</th><th :style="{ width: compact ? '96px' : '150px' }">{{ $t('ioTable.force') }}</th></tr></thead>
        <tbody>
          <template v-for="d in ['in', 'out']" :key="d">
            <tr class="sec"><td :colspan="(compact ? 6 : ext ? 8 : 7) + (dev && !compact ? 1 : 0)">{{ d === 'in' ? $t('ioTable.inputsISensorsButtons') : $t('hmiPanel.outputsQActuatorsIndicatorLamps') }}</td></tr>
            <tr v-for="r in rows.filter((x: any) => x.dir === d)" :key="r.name" :class="{ forced: r.forced }">
              <td class="c"><span class="led" :class="ledCls(r)" /></td>
              <td class="mono muted">{{ r.addr }}</td>
              <td class="mono nm" :title="r.comment">{{ r.name }}</td>
              <td v-if="dev && !compact" class="dv"><a v-if="r.device" href="#" :title="$t('ioTable.select0InTheWorkbench', [r.device])" @click.prevent="goto(r.device)">{{ r.device }}</a><span v-if="r.point && r.point !== r.name" class="mono muted"> · {{ r.point }}</span></td>
              <td class="ct"><span v-if="r.contact" class="ctag" :class="r.contact" :title="r.contact === 'NC' ? $t('ioTable.ncContact1WhenNot') : $t('ioTable.noContact0WhenNot')">{{ $t('common.n012', [r.contact === 'NC' ? $t('common.nc') : $t('common.no3'), r.idle]) }}</span></td>
              <td v-if="!compact" class="muted iot-cm">{{ r.comment }}</td>
              <td v-if="ext" class="mono muted">{{ r.ext }}</td>
              <td class="mono v" :class="ledCls(r)">{{ fmt(r) }}<em v-if="r.forced" class="fz">F</em></td>
              <td class="fc">
                <template v-if="(r.type || 'BOOL') === 'BOOL'">
                  <button class="fb t" :disabled="ro" :class="{ on: r.forced && r.value === true }" :title="$t('cellEditor.forceTo1')" @click="force(r, true)">1</button>
                  <button class="fb f" :disabled="ro" :class="{ on: r.forced && r.value === false }" :title="$t('cellEditor.forceTo0')" @click="force(r, false)">0</button>
                </template>
                <input v-else :disabled="ro" class="num mono" :placeholder="r.forced ? String(r.value) : $t('ioTable.value')" @keydown.enter="force(r, ($event.target as any).value); ($event.target as any).value = ''" />
                <button class="fb x" :disabled="!r.forced || ro" :title="$t('cellEditor.removeForce')" @click="force(r, null)">×</button>
              </td>
            </tr>
          </template>
          <tr v-if="!rows.length"><td colspan="9" class="muted c pad">{{ $t('ioTable.thisPlcHasNoI') }}</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { canEdit } from '../api';
import { fmtVal } from './plcApi';
import { ed, select } from '../editor/store';
import type { Sess } from './session';

const props = defineProps<{ sess: Sess; compact?: boolean }>();
const sess = props.sess;
const S = sess.s;
const ro = computed(() => !canEdit());
const rows = computed(() => {
  const on = S.online?.io;
  const extra = new Map((S.io || []).map((e: any) => [e.name, e]));
  const x = (n: string, k: string) => (extra.get(n) as any)?.[k];
  if (on?.length) return on.map((r: any) => ({ contact: x(r.name, 'contact'), idle: x(r.name, 'idle'), device: x(r.name, 'device'), point: x(r.name, 'point'), ...r }));
  return (S.io || []).map((e: any) => ({ ...e, value: null, forced: false }));
});
const ext = computed(() => rows.value.some((r: any) => r.ext));
/** 4.3: PLC block I/O comes from signal wires; each channel identifies its connected equipment. */
const dev = computed(() => rows.value.some((r: any) => r.device));
function goto(id: string) {
  if (!ed.model) return;
  select([id]);
}
const nForced = computed(() => rows.value.filter((r: any) => r.forced).length + Object.keys(S.online?.forced || {}).filter((k) => !rows.value.some((r: any) => r.name === k)).length);
const fmt = (r: any) => fmtVal(r.value, r.type);
const ledCls = (r: any) => (r.value === true ? 'on' : r.value === false ? 'off' : typeof r.value === 'number' && r.value ? 'on' : '');
async function force(r: any, v: any) {
  if (v === '') return;
  await sess.act({ action: 'force', name: r.name, value: v });
}
async function unforceAll() { await sess.act({ action: 'unforce_all' }); }
</script>

<style scoped>
.iot { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ld-card); color: var(--ld-tx); }
.iot-bar { display: flex; align-items: center; gap: 10px; padding: 6px 10px; border-bottom: 1px solid var(--ld-ln); font-size: 12px; }
.iot-scroll { flex: 1; overflow: auto; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.compact .tbl { font-size: 12px; }
.tbl th { position: sticky; top: 0; z-index: 1; background: var(--ld-bar); color: var(--ld-mu); font-weight: 500; text-align: left; padding: 4px 6px; border-bottom: 1px solid var(--ld-ln); }
.tbl td { padding: 2px 6px; border-bottom: 1px solid var(--ld-ln); height: 26px; white-space: nowrap; }
.tbl tr.sec td { background: var(--ld-bar); color: var(--ld-mu); font-size: 11.5px; height: auto; padding: 3px 8px; }
.tbl tr.forced td { background: var(--ld-bad-bg); }
.nm { font-weight: 600; }
.dv { font-size: 12px; white-space: nowrap; }
.ct { white-space: nowrap; }
.ctag { font-size: 11px; padding: 0 5px; border-radius: 3px; background: var(--ld-bar); color: var(--ld-mu); }
.ctag.NC { background: var(--ld-halt-bg); color: var(--ld-tx); font-weight: 600; } .iot-cm { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.led { display: inline-block; width: 11px; height: 11px; border-radius: 50%; background: var(--ld-ln); box-shadow: inset 0 0 0 1px var(--ld-shadow); }
.led.on { background: var(--ld-on-led); box-shadow: 0 0 6px var(--ld-on-led); }
.v.on { color: var(--ld-pow); font-weight: 600; } .v.off { color: var(--ld-mu); }
.fz { font-style: normal; margin-left: 4px; padding: 0 3px; border-radius: 2px; background: var(--ld-force); color: #fff; font-size: 10px; }
.fc { display: flex; gap: 3px; align-items: center; height: 26px; }
.fb { width: 24px; height: 20px; border: 1px solid var(--ld-ln); border-radius: 3px; background: var(--ld-bg); color: var(--ld-tx); font: 600 11px Consolas, monospace; cursor: pointer; }
.fb:hover:not(:disabled) { border-color: var(--ld-sel); }
.fb.t.on { background: var(--ld-force); color: #fff; border-color: var(--ld-force); } .fb.f.on { background: var(--ld-mu); color: #fff; border-color: var(--ld-mu); }
.fb:disabled { opacity: .35; cursor: default; }
.num { width: 64px; height: 20px; border: 1px solid var(--ld-ln); border-radius: 3px; background: var(--ld-bg); color: var(--ld-tx); padding: 0 4px; font-size: 11.5px; }
.mono { font-family: Consolas, monospace; } .muted { color: var(--ld-mu); } .c { text-align: center; } .pad { padding: 14px !important; white-space: normal; }
.grow { flex: 1; }
</style>
