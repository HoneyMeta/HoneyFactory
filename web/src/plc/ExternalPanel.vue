<template>
  <div class="plc-root xp">
    <div v-if="!noCells" class="xh">
      <el-select v-model="bid" size="small" style="flex: 1" placeholder="PLC">
        <el-option v-for="o in options.filter((x) => x.id !== '_sandbox')" :key="o.id" :value="o.id" :label="o.label" />
      </el-select>
    </div>
    <EmptyCells v-if="noCells" :running="running" :title="$t('externalPanel.anExternalPlcReplacesA')"
      :desc="$t('externalPanel.anExternalPlcPlcsimAdvanced')" />
    <div v-else-if="!bid || bid === '_sandbox'" class="pad muted">{{ $t('externalPanel.loadingPlcs') }}</div>
    <template v-else-if="cfg">
      <div class="xbody">
        <div class="sec">{{ $t('cellInspector.controlMode') }}</div>
        <el-radio-group v-model="mode" size="small">
          <el-radio-button value="internal">{{ $t('cellInspector.builtInSoftPlc') }}</el-radio-button>
          <el-radio-button value="external">{{ $t('common.externalPlc') }}</el-radio-button>
        </el-radio-group>
        <div v-if="mode === 'internal'" class="note muted">{{ $t('externalPanel.thisUnitIsCurrentlyControlled') }}</div>
        <template v-if="mode === 'external'">
          <div class="sec">{{ $t('common.protocol') }}</div>
          <el-select v-model="cfg.protocol" size="small" style="width: 100%" @change="refreshMap">
            <el-option v-for="(cn, k) in protocols" :key="k" :value="k" :label="cn" />
          </el-select>
          <div class="grid2">
            <template v-if="cfg.protocol === 'modbus_server'">
              <label>{{ $t('externalPanel.listeningPort') }}</label><el-input-number v-model="cfg.port" size="small" :min="1" :max="65535" controls-position="right" />
              <label>{{ $t('externalPanel.slaveId') }}</label><el-input-number v-model="cfg.unit" size="small" :min="0" :max="247" controls-position="right" />
            </template>
            <template v-else-if="cfg.protocol === 'modbus'">
              <label>{{ $t('externalPanel.remoteAddress') }}</label><el-input v-model="cfg.endpoint" size="small" placeholder="192.168.0.10:502" />
              <label>{{ $t('externalPanel.slaveId') }}</label><el-input-number v-model="cfg.unit" size="small" :min="0" :max="247" controls-position="right" />
            </template>
            <template v-else-if="cfg.protocol === 'opcua'">
              <label>{{ $t('common.server') }}</label><el-input v-model="cfg.endpoint" size="small" placeholder="opc.tcp://192.168.0.10:4840" />
              <label>{{ $t('externalPanel.username') }}</label><el-input v-model="cfg.username" size="small" :placeholder="$t('externalPanel.leaveBlankForAnonymousAccess')" />
              <label>{{ $t('common.password') }}</label><el-input v-model="cfg.password" size="small" type="password" show-password />
            </template>
            <template v-else-if="cfg.protocol === 's7'">
              <label>{{ $t('externalPanel.plcAddress') }}</label><el-input v-model="cfg.endpoint" size="small" placeholder="192.168.0.1" />
              <label>{{ $t('externalPanel.rackSlot') }}</label>
              <div class="row"><el-input-number v-model="cfg.rack" size="small" :min="0" :max="7" controls-position="right" /><el-input-number v-model="cfg.slot" size="small" :min="0" :max="31" controls-position="right" /></div>
            </template>
            <label>{{ $t('externalPanel.pollingIntervalMs') }}</label><el-input-number v-model="cfg.poll_ms" size="small" :min="10" :max="1000" :step="10" controls-position="right" />
          </div>
          <el-checkbox v-model="cfg.realtime" size="small">{{ $t('externalPanel.realTimeModeSimulationSpeed') }}</el-checkbox>
          <div class="note muted">{{ NOTES[cfg.protocol] }}</div>
          <div class="sec">{{ $t('externalPanel.signalMapping') }} <small class="muted">{{ $t('externalPanel.plcChannelExternalAddressLeave') }}</small></div>
          <table class="tbl">
            <thead><tr><th>I/O</th><th>{{ $t('common.direction') }}</th><th>{{ $t('common.type') }}</th><th>{{ $t('externalPanel.externalAddress') }}</th></tr></thead>
            <tbody>
              <tr v-for="m in mapping" :key="m.name">
                <td class="mono">{{ m.name }}</td><td><span class="dir" :class="m.dir">{{ m.dir === 'in' ? $t('externalPanel.sensorPlc') : $t('externalPanel.plcActuator') }}</span></td>
                <td class="mono muted">{{ m.type }}</td>
                <td><input class="ci mono" :value="userAddr[m.name] ?? ''" :placeholder="m.addr" :disabled="cfg.protocol === 'opcua_server'" @change="userAddr[m.name] = ($event.target as any).value" /></td>
              </tr>
            </tbody>
          </table>
        </template>
        <div v-if="status" class="stat">
          <div><span class="led" :class="{ on: status.connected }" /> {{ status.connected ? $t('common.connected') : $t('externalPanel.notConnected') }} <span class="muted">{{ status.peer }}</span></div>
          <div class="muted small mono">{{ $t('externalPanel.exchanges0Errors1', [status.polls, status.errors]) }}<template v-if="status.last_ms"> {{ $t('externalPanel.lastExchange0Ms', [status.last_ms]) }}</template></div>
          <div v-if="status.error" class="bad small">{{ status.error }}</div>
        </div>
      </div>
      <div class="xf">
        <button class="plc-btn pri" data-act="apply-ext" @click="apply"><el-icon><Check /></el-icon>{{ $t('common.apply') }}</button>
        <span class="muted small">{{ curMode === 'external' ? $t('externalPanel.currentExternalPlc') : $t('externalPanel.currentBuiltInSoftPlc') }}</span>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import './plc.css';
import { ElMessage } from 'element-plus';
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useCells } from './cells';
import EmptyCells from './EmptyCells.vue';
import { plcApi } from './plcApi';

const props = defineProps<{ pid: string; bid?: string }>();
const { bid, options, noCells, running, cells } = useCells(() => props.pid, () => props.bid);
watch(cells, (cs) => { if (bid.value === '_sandbox' && cs.length) bid.value = cs[0].id; });
const cfg = ref<any>(null);
const mode = ref('internal');
const curMode = ref('internal');
const protocols = ref<Record<string, string>>({});
const mapping = ref<any[]>([]);
const userAddr = ref<Record<string, string>>({});
const status = ref<any>(null);
const NOTES: Record<string, string> = {
  modbus_server: $t('externalPanel.theVirtualFactoryActsAs'),
  modbus: $t('externalPanel.theVirtualFactoryActsAs2'),
  opcua_server: $t('externalPanel.publishesThisUnitSI'),
  opcua: $t('externalPanel.theVirtualFactoryActsAs3'),
  s7: $t('externalPanel.siemensS7S712001500'),
};
async function load() {
  if (!bid.value || bid.value === '_sandbox') { cfg.value = null; return; }
  const r = await plcApi.external(props.pid, bid.value);
  cfg.value = { protocol: 'modbus_server', port: 1502, unit: 1, realtime: true, poll_ms: 20, rack: 0, slot: 1, ...r.config };
  mode.value = curMode.value = r.mode; protocols.value = r.protocols; mapping.value = r.mapping; status.value = r.status;
  userAddr.value = Object.fromEntries((r.config.mapping || []).filter((m: any) => m.addr).map((m: any) => [m.name, m.addr]));
}
async function refreshMap() { userAddr.value = {}; mapping.value = (await plcApi.external(props.pid, bid.value, cfg.value.protocol)).mapping; }
async function apply() {
  const body = { ...cfg.value, mode: mode.value, mapping: Object.entries(userAddr.value).filter(([, a]) => a).map(([name, addr]) => ({ name, addr })) };
  const r = await plcApi.setExternal(props.pid, bid.value, body);
  ElMessage.success(r.mode === 'external' ? $t('externalPanel.switchedToExternalPlc') : $t('externalPanel.switchedBackToTheBuilt'));
  await load();
}
watch(bid, load, { immediate: true });
const t = setInterval(async () => { if (curMode.value === 'external' && bid.value) { try { status.value = (await plcApi.external(props.pid, bid.value)).status; } catch { /* */ } } }, 1500);
onBeforeUnmount(() => clearInterval(t));
</script>

<style scoped>
.xp { display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ld-bg); }
.xh { display: flex; padding: 8px; border-bottom: 1px solid var(--ld-ln); }
.xbody { flex: 1; overflow: auto; padding: 4px 10px 10px; display: flex; flex-direction: column; gap: 6px; }
.sec { font-weight: 600; margin-top: 8px; }
.grid2 { display: grid; grid-template-columns: 92px 1fr; gap: 6px 8px; align-items: center; }
.grid2 label { color: var(--ld-mu); font-size: 12px; }
.note { font-size: 11.5px; line-height: 1.6; }
.tbl { width: 100%; border-collapse: collapse; font-size: 12px; }
.tbl th { text-align: left; color: var(--ld-mu); font-weight: 500; padding: 3px 4px; border-bottom: 1px solid var(--ld-ln); }
.tbl td { padding: 2px 4px; border-bottom: 1px solid var(--ld-ln); }
.ci { width: 100%; height: 22px; border: 1px solid var(--ld-ln); border-radius: 3px; background: var(--ld-card); color: var(--ld-tx); padding: 0 5px; font-size: 12px; }
.dir { font-size: 10.5px; padding: 0 4px; border-radius: 3px; white-space: nowrap; }
.dir.in { background: var(--ld-in-bg); color: var(--ld-in); } .dir.out { background: var(--ld-pow-bg); color: var(--ld-pow); }
.stat { margin-top: 8px; padding: 8px; border: 1px solid var(--ld-ln); border-radius: 6px; background: var(--ld-card); display: flex; flex-direction: column; gap: 3px; }
.led { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: var(--ld-ln); vertical-align: -1px; }
.led.on { background: var(--ld-on-led); box-shadow: 0 0 6px var(--ld-on-led); }
.xf { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-top: 1px solid var(--ld-ln); }
.row { display: flex; gap: 4px; } .bad { color: var(--ld-bad); } .small { font-size: 11.5px; } .pad { padding: 14px; }
</style>
