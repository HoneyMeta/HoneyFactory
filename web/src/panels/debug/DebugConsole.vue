<template>
  <div class="vp debug-console">
    <el-tabs v-model="tab" class="dc-tabs">
      <!-- Tag table -->
      <el-tab-pane :label="$t('deliveryExport.tagList')" name="points">
        <div class="vp-body">
          <div class="vp-row" style="margin-bottom: 6px">
            <el-select v-model="stFilter" size="small" :placeholder="$t('spc.allEquipment')" clearable filterable style="width: 150px">
              <el-option v-for="s in tree" :key="s.id" :value="s.id" :label="`${s.id} ${s.name}`" />
            </el-select>
            <el-input v-model="kw" size="small" :placeholder="$t('debugConsole.searchTagsAddresses')" clearable class="vp-grow" style="min-width: 120px" />
            <el-select v-model="addrCol" size="small" style="width: 110px">
              <el-option value="opcua" label="OPC UA" /><el-option value="mqtt" :label="$t('livePanel.mqttTopic')" /><el-option value="modbus" label="Modbus" />
            </el-select>
            <el-checkbox v-model="writableOnly" size="small">{{ $t('debugConsole.writableOnly') }}</el-checkbox>
          </div>
          <div class="vp-small vp-muted" style="margin-bottom: 4px">{{ $t('debugConsole.n0TagsRefreshedEvery2', [points.length]) }} <span v-if="endpoints">{{ endpointText }}</span></div>
          <table class="vp-tbl pts">
            <tr><th>{{ $t('debugConsole.tags0', [ADDR_CN[addrCol]]) }}</th><th class="num">{{ $t('common.value') }}</th><th></th></tr>
            <tr v-for="t in shownPoints" :key="t.key" :class="{ hi: changed[t.key] }">
              <td><div class="mono">{{ t.key }}</div><div class="vp-small vp-muted">{{ t.desc }}{{ t.unit ? $t('common.k459') + t.unit + $t('common.k460') : '' }}</div>
                <div class="mono addr" :title="t[addrCol] || ''">{{ t[addrCol] || '—' }}</div></td>
              <td class="num mono val">{{ fmtVal(t.value) }}</td>
              <td class="num"><el-button v-if="t.writable" size="small" text @click="writeTag(t)">{{ $t('debugConsole.write') }}</el-button></td>
            </tr>
          </table>
          <div v-if="points.length > shownPoints.length" class="vp-small vp-muted" style="margin-top: 4px">{{ $t('debugConsole.onlyTheFirst0Are', [shownPoints.length]) }}</div>
        </div>
      </el-tab-pane>

      <!-- Connection and communication faults -->
      <el-tab-pane :label="$t('common.connection')" name="conn">
        <div class="vp-body">
          <div class="vp-sec"><div class="lbl">{{ $t('plants.connectionAddresses') }}<span class="grow" /><span v-if="endpoints?.hostname" class="vp-muted">{{ $t('debugConsole.host0', [endpoints.hostname]) }}</span></div>
            <div v-if="endpoints?.sandbox" class="vp-small vp-muted">{{ $t('debugConsole.sandboxFactoriesDoNotExpose') }}</div>
            <div v-else-if="endpoints" class="eps">
              <div v-for="p in PROTOS" :key="p.key" class="ep"><span class="vp-muted">{{ p.label }}</span>
                <code class="vp-mono">{{ endpoints[p.key] || '—' }}</code>
                <el-button v-if="endpoints[p.key]" size="small" text @click="copy(endpoints[p.key])"><el-icon><CopyDocument /></el-icon></el-button>
                <span v-if="(endpoints.all?.[p.key] || []).length > 1" class="vp-small vp-muted">{{ $t('signals.otherNetworkAdapters') }}<a v-for="a in endpoints.all[p.key].slice(1)" :key="a" class="lnk" @click="copy(a)">{{ a }}</a></span></div>
              <div class="vp-small vp-muted">{{ $t('debugConsole.externalTime0ChangeIn', [status?.settings?.time === 'wall' ? $t('common.wallClock') : $t('common.simTime'), endpoints.mqtt_prefix]) }}</div></div></div>
          <div class="vp-sec"><div class="lbl">{{ $t('debugConsole.onlineClients0', [status?.clients?.length || 0]) }}</div>
            <table class="vp-tbl"><tr><th>{{ $t('common.protocol') }}</th><th>{{ $t('debugConsole.peer') }}</th><th>{{ $t('common.description') }}</th></tr>
              <tr v-for="(c, i) in status?.clients || []" :key="i"><td>{{ c.protocol }}</td><td class="mono">{{ c.peer }}</td><td class="vp-muted">{{ c.detail }}</td></tr></table>
            <div v-if="!status?.clients?.length" class="vp-small vp-muted">{{ $t('debugConsole.noExternalClientsConnectedMes') }}</div></div>
          <div class="vp-sec"><div class="lbl">{{ $t('debugConsole.communicationFaultInjectionProtocolD') }}<span class="grow" />
              <el-button v-if="status?.rules?.length" size="small" text type="danger" :disabled="!isEngineer()" @click="clearAll">{{ $t('signals.restoreAll') }}</el-button></div>
            <div class="vp-card">
              <div class="vp-row">
                <el-select v-model="cf.protocol" size="small" style="width: 100px" @change="fixMode"><el-option v-for="p in PROTOS" :key="p.key" :value="p.key" :label="p.label" /></el-select>
                <el-select v-model="cf.station" size="small" clearable filterable :placeholder="$t('signals.entireProtocol')" style="width: 130px" @change="cf.tag = ''">
                  <el-option v-for="s in tree" :key="s.id" :value="s.id" :label="`${s.id} ${s.name}`" /></el-select>
                <el-select v-model="cf.tag" size="small" clearable filterable :placeholder="$t('signals.entireDevice')" :disabled="!cf.station" style="width: 170px">
                  <el-option v-for="t in tagsOf(cf.station)" :key="t" :value="t" :label="t" /></el-select>
              </div>
              <div class="vp-row" style="margin-top: 6px">
                <el-select v-model="cf.mode" size="small" style="width: 110px"><el-option v-for="m in status?.supported?.[cf.protocol] || []" :key="m" :value="m" :label="status.modes[m]" /></el-select>
                <el-input-number v-if="cf.mode === 'latency' || cf.mode === 'jitter'" v-model="cf.latency" size="small" :min="0.1" :max="120" controls-position="right" style="width: 90px" />
                <span v-if="cf.mode === 'latency' || cf.mode === 'jitter'" class="vp-small vp-muted">{{ $t('debugConsole.s') }}</span>
                <el-input-number v-if="cf.mode === 'drop'" v-model="cf.drop_pct" size="small" :min="1" :max="100" controls-position="right" style="width: 90px" />
                <span v-if="cf.mode === 'drop'" class="vp-small vp-muted">%</span>
                <el-input v-if="cf.mode === 'stuck'" v-model="cf.value" size="small" :placeholder="$t('debugConsole.valueBlankCurrentValue')" style="width: 110px" />
                <el-input-number v-if="cf.mode === 'drift'" v-model="cf.rate" size="small" :step="0.5" controls-position="right" style="width: 90px" />
                <span v-if="cf.mode === 'drift'" class="vp-small vp-muted">{{ $t('debugConsole.min') }}</span>
                <el-input-number v-model="cf.minutes" size="small" :min="0" :max="600" controls-position="right" style="width: 90px" />
                <span class="vp-small vp-muted">{{ $t('breakpoints.min') }}</span>
                <el-checkbox v-if="cf.protocol === 'mqtt' && !cf.station" v-model="cf.include_mes" size="small">{{ $t('debugConsole.includeMes') }}</el-checkbox>
                <el-button size="small" type="danger" plain :disabled="!isEngineer() || !cf.mode" @click="setComm">{{ $t('common.inject') }}</el-button>
              </div>
              <div class="vp-small vp-muted" style="margin-top: 4px">{{ $t('debugConsole.n0SetMinutesTo0', [status?.help?.[cf.mode]]) }}</div>
            </div>
            <div v-for="r in status?.rules || []" :key="r.id" class="vp-row rule"><el-tag size="small" type="danger">{{ r.desc }}</el-tag>
              <span class="vp-small vp-muted">{{ r.left_min != null ? $t('signals.n0MinRemaining', [r.left_min]) : $t('signals.keepIndefinitely') }}</span><span class="vp-grow" />
              <el-button size="small" text :disabled="!isEngineer()" @click="clearRule(r)">{{ $t('common.restore') }}</el-button></div>
            <div v-if="!status?.rules?.length" class="vp-small vp-muted" style="margin-top: 6px">{{ $t('debugConsole.noActiveCommunicationFaults') }}</div>
          </div>
        </div>
      </el-tab-pane>

      <!-- Messages -->
      <el-tab-pane :label="$t('debugConsole.messages')" name="msgs">
        <div class="vp-body msgs">
          <div class="vp-row" style="margin-bottom: 6px">
            <el-select v-model="msgStation" size="small" clearable filterable :placeholder="$t('spc.allEquipment')" style="width: 130px">
              <el-option v-for="s in tree" :key="s.id" :value="s.id" :label="`${s.id} ${s.name}`" /></el-select>
            <el-input v-model="msgFilter" size="small" :placeholder="$t('debugConsole.filterByTopicOrContent')" clearable class="vp-grow" style="min-width: 100px" />
            <el-checkbox v-model="mesOnly" size="small">{{ $t('debugConsole.mesStatusOnly') }}</el-checkbox>
            <el-button size="small" text @click="paused = !paused">{{ paused ? $t('common.continue') : $t('common.pause') }}</el-button>
            <el-button size="small" text @click="msgs = []">{{ $t('debugConsole.clear') }}</el-button>
            <el-dropdown size="small" trigger="click" @command="exportMsgs">
              <el-button size="small" text><el-icon><Download /></el-icon>{{ $t('common.export') }}</el-button>
              <template #dropdown><el-dropdown-menu><el-dropdown-item command="csv">{{ $t('debugConsole.csvExcel') }}</el-dropdown-item><el-dropdown-item command="jsonl">JSONL</el-dropdown-item></el-dropdown-menu></template>
            </el-dropdown>
          </div>
          <div class="vp-small vp-muted" style="margin-bottom: 4px">{{ msgInfo }}</div>
          <div class="msg-head vp-small vp-muted"><span class="c1">{{ $t('debugConsole.receivedTimeLocal') }}</span><span class="c2">{{ $t('debugConsole.simTimeSimTsT') }}</span></div>
          <div v-for="m in msgs.slice().reverse().slice(0, 300)" :key="m.seq" class="msg" :class="{ mes: m.topic.includes('/_mes/'), err: m.topic.endsWith('/_errors') }" @click="m._open = !m._open">
            <div class="vp-row nowrap vp-small"><span class="vp-muted mono c1" :title="$t('debugConsole.receivedTimeLocal') + m.recv">{{ m.ts }}</span><span class="vp-muted mono c2" :title="$t('debugConsole.simTime') + m.sim">{{ simShort(m.sim) }}</span></div>
            <div class="mono topic">{{ m.topic }}</div>
            <pre v-if="m._open" class="payload">{{ pretty(m.payload) }}</pre>
            <div v-else class="mono vp-small vp-muted ell">{{ m.payload }}</div>
          </div>
          <div v-if="!msgs.length" class="vp-empty">{{ msgOk ? $t('debugConsole.waitingForMessages') : msgErr }}</div>
        </div>
      </el-tab-pane>

      <!-- Test scripts -->
      <el-tab-pane :label="$t('debugConsole.testScripts')" name="tests">
        <div class="vp-body">
          <div class="vp-row" style="margin-bottom: 6px">
            <el-select v-model="tid" size="small" :placeholder="$t('debugConsole.selectScript')" clearable style="width: 180px" @change="openScript">
              <el-option v-for="t in tests" :key="t.id" :value="t.id" :label="t.name">
                <span>{{ t.name }}</span><span class="vp-small" style="float: right" :class="t.last?.status === 'passed' ? 'vp-pass' : t.last?.status ? 'vp-fail' : 'vp-muted'">{{ STATUS_CN[t.last?.status] || '' }}</span></el-option>
            </el-select>
            <el-button size="small" @click="newScript">{{ $t('common.new') }}</el-button>
            <el-dropdown size="small" trigger="click" @command="addStep">
              <el-button size="small">{{ $t('debugConsole.addStep') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
              <template #dropdown><el-dropdown-menu>
                <el-dropdown-item v-for="(s, k) in STEP_TPL" :key="k" :command="k">{{ s.label }}</el-dropdown-item>
              </el-dropdown-menu></template>
            </el-dropdown>
            <span class="vp-grow" />
            <el-radio-group v-model="view" size="small" @change="switchView"><el-radio-button value="table">{{ $t('debugConsole.stepTable') }}</el-radio-button><el-radio-button value="json">{{ $t('debugConsole.jsonAdvanced') }}</el-radio-button></el-radio-group>
          </div>

          <template v-if="view === 'table'">
            <div class="vp-row" style="margin-bottom: 6px"><span class="vp-small vp-muted">{{ $t('common.name') }}</span><el-input v-model="sc.name" size="small" class="vp-grow" style="min-width: 140px" />
              <span class="vp-small vp-muted">{{ $t('debugConsole.speed') }}</span><el-input-number v-model="sc.speed" size="small" :min="0.1" :max="3600" controls-position="right" style="width: 100px" />
              <el-checkbox v-model="sc.stop_on_fail" size="small">{{ $t('debugConsole.stopOnFailure') }}</el-checkbox></div>
            <div v-for="(st, i) in sc.steps" :key="i" class="step" :class="resClass(i)">
              <div class="vp-row nowrap">
                <span class="idx">{{ i + 1 }}</span>
                <span class="res" :title="resOf(i)?.msg">{{ resIcon(i) }}</span>
                <el-select :model-value="st.kind" size="small" style="width: 128px; flex: none" @change="(k: string) => changeKind(i, k)">
                  <el-option v-for="(n, k) in KIND_CN" :key="k" :value="k" :label="n" /></el-select>
                <span class="vp-grow" />
                <el-button size="small" text :disabled="i === 0" @click="move(i, -1)">↑</el-button>
                <el-button size="small" text :disabled="i === sc.steps.length - 1" @click="move(i, 1)">↓</el-button>
                <el-button size="small" text type="danger" @click="sc.steps.splice(i, 1)">✕</el-button>
              </div>
              <el-input v-model="st.name" size="small" :placeholder="$t('debugConsole.stepDescriptionOptionalShownIn')" class="sname" />
              <div class="vp-row fields">
                <template v-for="f in fieldsOf(st)" :key="f.k">
                  <span class="vp-small vp-muted">{{ f.label }}</span>
                  <el-select v-if="f.t === 'station'" :model-value="getP(st, f.k)" size="small" filterable allow-create style="width: 110px" @update:model-value="(v: any) => setP(st, f.k, v)">
                    <el-option v-for="s in tree" :key="s.id" :value="s.id" :label="s.id" /></el-select>
                  <el-select v-else-if="f.t === 'tag' || f.t === 'wtag'" :model-value="getP(st, f.k)" size="small" filterable allow-create style="width: 190px"
                    @update:model-value="(v: any) => setP(st, f.k, v)">
                    <el-option v-for="t in tagsOf(getP(st, f.st || 'station'), f.t === 'wtag')" :key="t" :value="t" :label="t" /></el-select>
                  <el-select v-else-if="f.t === 'fault'" :model-value="getP(st, f.k)" size="small" filterable allow-create style="width: 130px" @update:model-value="(v: any) => setP(st, f.k, v)">
                    <el-option v-for="(n, k) in faultsOf(st.station)" :key="k" :value="k" :label="n" /></el-select>
                  <el-select v-else-if="f.t === 'op'" :model-value="getP(st, f.k) || '=='" size="small" style="width: 66px" @update:model-value="(v: any) => setP(st, f.k, v)">
                    <el-option v-for="o in OPS" :key="o" :value="o" :label="o" /></el-select>
                  <el-select v-else-if="f.t === 'via'" :model-value="getP(st, f.k) || 'rest'" size="small" style="width: 86px" @update:model-value="(v: any) => setP(st, f.k, v)">
                    <el-option value="rest" :label="$t('debugConsole.api')" /><el-option value="opcua" label="OPC UA" /><el-option value="mqtt" label="MQTT" /></el-select>
                  <el-select v-else-if="f.t === 'proto'" :model-value="getP(st, f.k)" size="small" style="width: 92px" @update:model-value="(v: any) => setP(st, f.k, v)">
                    <el-option v-for="p in PROTOS" :key="p.key" :value="p.key" :label="p.label" /></el-select>
                  <el-select v-else-if="f.t === 'mode'" :model-value="getP(st, f.k) || '-'" size="small" style="width: 104px" @update:model-value="(v: any) => setP(st, f.k, v === '-' ? undefined : v)">
                    <el-option value="-" :label="$t('common.restore')" /><el-option v-for="m in status?.supported?.[st.protocol] || []" :key="m" :value="m" :label="status.modes[m]" /></el-select>
                  <el-select v-else-if="f.t === 'topic'" :model-value="getP(st, f.k) || 'event'" size="small" style="width: 80px" @update:model-value="(v: any) => setP(st, f.k, v)">
                    <el-option value="event" label="event" /><el-option value="part" label="part" /></el-select>
                  <el-checkbox v-else-if="f.t === 'bool'" :model-value="!!getP(st, f.k)" size="small" @update:model-value="(v: any) => setP(st, f.k, v || undefined)" />
                  <el-input-number v-else-if="f.t === 'num'" :model-value="getP(st, f.k)" size="small" :controls="false" style="width: 70px" @update:model-value="(v: any) => setP(st, f.k, v ?? undefined)" />
                  <el-input v-else-if="f.t === 'json'" :model-value="jsonOf(getP(st, f.k))" size="small" class="mono-in" style="width: 220px" @change="(v: string) => setJson(st, f.k, v)" />
                  <el-input v-else :model-value="getP(st, f.k) == null ? '' : String(getP(st, f.k))" size="small" style="width: 90px" @update:model-value="(v: string) => setP(st, f.k, typed(v))" />
                </template>
              </div>
              <div v-if="resOf(i)" class="vp-small" :class="resOf(i).ok ? 'vp-muted' : resOf(i).skipped ? 'vp-muted' : 'vp-fail'">{{ resOf(i).msg }}<template v-if="resOf(i).ms !== undefined"> · {{ resOf(i).ms }} ms</template></div>
            </div>
            <div v-if="!sc.steps.length" class="vp-empty">{{ $t('debugConsole.noStepsYetClickAdd') }}</div>
          </template>
          <template v-else>
            <el-input v-model="scriptText" type="textarea" :rows="16" class="mono-ta" spellcheck="false" placeholder='{"name": "...", "speed": 30, "steps": [...]}' />
          </template>
          <div v-if="scriptErr" class="vp-small vp-fail" style="margin-top: 4px">{{ scriptErr }}</div>
          <div class="vp-row" style="margin-top: 6px">
            <el-button size="small" type="primary" :loading="running" :disabled="!isEngineer()" @click="runScript"><el-icon><VideoPlay /></el-icon>{{ $t('common.run') }}</el-button>
            <el-button size="small" :disabled="!isEngineer()" @click="saveScript">{{ $t('common.save') }}</el-button>
            <el-button size="small" text type="danger" v-if="tid" :disabled="!isEngineer()" @click="delScript">{{ $t('common.delete') }}</el-button>
            <span class="vp-grow" />
            <el-button size="small" text v-if="run?.id" @click="junit"><el-icon><Download /></el-icon>JUnit</el-button>
            <el-button size="small" text v-if="running" @click="cancel">{{ $t('common.cancel') }}</el-button>
          </div>
          <div v-if="run" class="vp-card run-card" style="margin-top: 8px">
            <div class="vp-row sp"><b :class="run.status === 'passed' ? 'vp-pass' : run.status === 'running' ? '' : 'vp-fail'">{{ STATUS_CN[run.status] || run.status }}</b>
              <span class="vp-small vp-muted">{{ run.passed !== undefined ? $t('debugConsole.n0Passed1Failed2', [run.passed, run.failed, run.skipped ? ' / ' + run.skipped + $t('debugConsole.skipped') : '', run.duration_s]) : $t('debugConsole.running') }}</span></div>
            <template v-if="view === 'json'">
              <div v-for="s in run.steps" :key="s.i" class="res-row">
                <span class="ic" :class="s.ok ? 'vp-pass' : s.ok === false ? 'vp-fail' : 'vp-muted'">{{ s.ok ? '✓' : s.ok === false ? '✗' : s.skipped ? '–' : '…' }}</span>
                <span class="vp-grow"><span>{{ s.i }}. {{ s.desc }}</span><div class="vp-small vp-muted">{{ s.msg }}<template v-if="s.ms !== undefined"> · {{ s.ms }} ms</template></div></span>
              </div>
            </template>
            <div v-for="n in run.notes || []" :key="n" class="vp-small vp-fail">{{ n }}</div>
          </div>
          <div class="vp-small vp-muted" style="margin-top: 8px">{{ $t('debugConsole.commandLineCi') }}<code>{{ $t('debugConsole.pythonMVfactoryTestScript', [pid]) }}</code>{{ $t('debugConsole.add') }} <code>--no-protocols</code> {{ $t('debugConsole.protocolServicesAreNotStarted') }}</div>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { del, get, P, post, put } from '../../api';
import { fmtVal, isEngineer, poll, saveFile } from '../teach/util';
import '../teach/panel.css';

const props = defineProps<{ pid: string }>();
const tab = ref('points');
// ---- Tag table ----
const tree = ref<any[]>([]);
const stFilter = ref('');
const kw = ref('');
const addrCol = ref('opcua');
const writableOnly = ref(false);
const changed = reactive<Record<string, boolean>>({});
const ADDR_CN: Record<string, string> = { opcua: 'OPC UA NodeId', mqtt: $t('livePanel.mqttTopic'), modbus: $t('debugConsole.modbusAddress') };
const points = computed(() => tree.value.flatMap((s: any) => s.tags.map((t: any) => ({ ...t, station: s.id }))));
const shownPoints = computed(() => points.value.filter((t: any) => (!stFilter.value || t.station === stFilter.value) && (!writableOnly.value || t.writable)
  && (!kw.value || [t.key, t.desc, t.opcua, t.mqtt, t.modbus].some((x) => (x || '').includes(kw.value)))).slice(0, 400));
const tagsOf = (sid: string, writable = false) => { const st = tree.value.find((x: any) => x.id === sid); return st ? st.tags.filter((t: any) => !writable || t.writable).map((t: any) => t.name) : []; };
let prevVals: Record<string, any> = {};
async function loadTree() {
  if (tab.value !== 'points' && tree.value.length) return;
  const r = await get(P(props.pid) + '/signals/tree', true);
  for (const s of r) for (const t of s.tags) {
    if (t.key in prevVals && prevVals[t.key] !== t.value) { changed[t.key] = true; setTimeout(() => { delete changed[t.key]; }, 900); }
    prevVals[t.key] = t.value;
  }
  tree.value = r;
}
async function writeTag(t: any) {
  const { value } = await ElMessageBox.prompt(`${t.key}${t.lo !== null && t.lo !== undefined ? $t('debugConsole.range01', [t.lo, t.hi]) : ''}`, $t('debugConsole.writeTag'), { inputValue: String(t.value ?? '') });
  await post(P(props.pid) + `/station/${encodeURIComponent(t.station)}/write`, { tag: t.name, value });
  ElMessage.success($t('signals.written'));
}
function copy(t: string) { navigator.clipboard?.writeText(t).then(() => ElMessage.success($t('common.copied')), () => ElMessage.info(t)); }
// ---- Connections ----
const status = ref<any>(null);
const endpoints = computed(() => status.value?.endpoints);
const endpointText = computed(() => endpoints.value?.sandbox ? $t('debugConsole.sandboxFactoriesDoNotExpose2') : `OPC UA ${endpoints.value?.opcua || '—'} · Modbus ${endpoints.value?.modbus || '—'}`);
const PROTOS = [{ key: 'opcua', label: 'OPC UA' }, { key: 'modbus', label: 'Modbus TCP' }, { key: 'mqtt', label: 'MQTT' }];
const cf = reactive<any>({ protocol: 'mqtt', station: '', tag: '', mode: 'freeze', latency: 3, drop_pct: 30, value: '', rate: 1, minutes: 0, include_mes: true });
async function loadStatus() { status.value = await get(P(props.pid) + '/signals/status', true); fixMode(); }
function fixMode() { const sup = status.value?.supported?.[cf.protocol] || []; if (sup.length && !sup.includes(cf.mode)) cf.mode = sup[0]; }
async function setComm() {
  const b: any = { protocol: cf.protocol, mode: cf.mode, minutes: cf.minutes, station: cf.station || undefined, tag: cf.tag || undefined };
  if (cf.mode === 'latency' || cf.mode === 'jitter') b.latency = cf.latency;
  if (cf.mode === 'drop') b.drop_pct = cf.drop_pct;
  if (cf.mode === 'stuck' && cf.value !== '') b.value = typed(cf.value);
  if (cf.mode === 'drift') b.rate = cf.rate;
  if (cf.protocol === 'mqtt' && !cf.station) b.include_mes = cf.include_mes;
  await post(P(props.pid) + '/signals/comm', b);
  ElMessage.success($t('debugConsole.injected'));
  loadStatus();
}
async function clearRule(r: any) { await del(P(props.pid) + `/signals/comm/${r.id}`); ElMessage.success($t('common.restored')); loadStatus(); }
async function clearAll() { await del(P(props.pid) + '/signals/comm'); ElMessage.success($t('signals.restoreAll')); loadStatus(); }
// ---- Messages ----
const msgs = ref<any[]>([]);
const msgFilter = ref('');
const msgStation = ref('');
const mesOnly = ref(false);
const paused = ref(false);
const msgOk = ref(true);
const msgErr = ref('');
const msgInfo = ref('');
let seq = 0;
const msgQuery = () => `mes=${mesOnly.value ? 1 : 0}&filter=${encodeURIComponent(msgFilter.value)}&station=${encodeURIComponent(msgStation.value || '')}`;
async function loadMsgs() {
  if (tab.value !== 'msgs' || paused.value) return;
  const r = await get(P(props.pid) + `/debug/messages?since=${seq}&${msgQuery()}&limit=300`, true);
  msgOk.value = r.ok; msgErr.value = r.msg || '';
  if (!r.ok) return;
  seq = r.seq;
  msgs.value = [...msgs.value, ...r.items].slice(-600);
  msgInfo.value = $t('debugConsole.received1MessagesSince0', [r.started, r.count, r.rate]);
}
watch([msgFilter, mesOnly, msgStation], () => { msgs.value = []; seq = Math.max(0, seq - 2000); });
const pretty = (s: string) => { try { return JSON.stringify(JSON.parse(s), null, 1); } catch { return s; } };
const simShort = (s: string) => (s ? String(s).replace('T', ' ').slice(5, 19) : '—');
function exportMsgs(fmt: string) { saveFile(P(props.pid) + `/debug/messages.${fmt}?${msgQuery()}`, `messages-${props.pid}.${fmt}`); }
// ---- Test scripts ----
const tests = ref<any[]>([]);
const tid = ref<number | null>(null);
const view = ref<'table' | 'json'>('table');
const sc = reactive<any>({ name: $t('debugConsole.newTestScript'), speed: 30, stop_on_fail: false, steps: [] });
const scriptText = ref('');
const scriptErr = ref('');
const run = ref<any>(null);
const running = ref(false);
const stations = ref<any[]>([]);
const STATUS_CN: Record<string, string> = { passed: $t('debugConsole.approve'), failed: $t('experiments.failed2'), error: $t('debugConsole.error'), running: $t('common.running2'), cancelled: $t('debugConsole.cancelled') };
const OPS = ['==', '!=', '>', '>=', '<', '<='];
const KIND_CN: Record<string, string> = { setpoint: $t('common.writeSetpoint'), set_tag: $t('debugConsole.setTag'), fault: $t('common.injectFailure'), cell_fault: $t('debugConsole.componentFailure'), comm_fault: $t('audit.communicationFailure'), wait: $t('common.waiting'),
  wait_until: $t('debugConsole.waitForCondition'), assert: $t('debugConsole.assertTag'), assert_mes: $t('debugConsole.assertMesMessage'), assert_kpi: $t('debugConsole.assertMetric') };
type F = { k: string; label: string; t: string; st?: string };
const FIELDS: Record<string, F[]> = {
  setpoint: [{ k: 'station', label: $t('common.equipment'), t: 'station' }, { k: 'tag', label: $t('common.tag'), t: 'wtag' }, { k: 'value', label: $t('common.value'), t: 'val' }],
  set_tag: [{ k: 'station', label: $t('common.equipment'), t: 'station' }, { k: 'tag', label: $t('common.tag'), t: 'tag' }, { k: 'value', label: $t('common.value'), t: 'val' }],
  fault: [{ k: 'station', label: $t('common.equipment'), t: 'station' }, { k: 'fault', label: $t('common.fault'), t: 'fault' }],
  cell_fault: [{ k: 'station', label: $t('cellInspector.cell'), t: 'station' }, { k: 'comp', label: $t('common.components'), t: 'val' }, { k: 'fault', label: $t('common.fault'), t: 'val' }],
  comm_fault: [{ k: 'protocol', label: $t('common.protocol'), t: 'proto' }, { k: 'mode', label: $t('debugConsole.mode'), t: 'mode' }, { k: 'station', label: $t('common.equipment'), t: 'station' },
    { k: 'tag', label: $t('common.tag'), t: 'tag' }, { k: 'minutes', label: $t('breakpoints.min'), t: 'num' }, { k: 'latency', label: $t('debugConsole.s'), t: 'num' }, { k: 'drop_pct', label: $t('debugConsole.packetLoss'), t: 'num' },
    { k: 'value', label: $t('debugConsole.stuckValue'), t: 'val' }, { k: 'rate', label: $t('debugConsole.driftMin'), t: 'num' }],
  wait: [{ k: 'seconds', label: $t('debugConsole.simTimeS'), t: 'num' }],
  wait_until: [{ k: 'cond.id', label: $t('common.equipment'), t: 'station' }, { k: 'cond.tag', label: $t('common.tag'), t: 'tag', st: 'cond.id' }, { k: 'cond.op', label: '', t: 'op' },
    { k: 'cond.value', label: $t('common.value'), t: 'val' }, { k: 'timeout', label: $t('debugConsole.timeoutS'), t: 'num' }],
  assert: [{ k: 'via', label: $t('debugConsole.read'), t: 'via' }, { k: 'station', label: $t('common.equipment'), t: 'station' }, { k: 'tag', label: $t('common.tag'), t: 'tag' }, { k: 'op', label: '', t: 'op' },
    { k: 'value', label: $t('debugConsole.expected'), t: 'val' }, { k: 'tol', label: $t('debugConsole.tolerance'), t: 'num' }, { k: 'within', label: $t('debugConsole.waitS'), t: 'num' }, { k: 'expect_bad', label: $t('debugConsole.expectBadQuality'), t: 'bool' }],
  assert_mes: [{ k: 'topic', label: $t('debugConsole.topic'), t: 'topic' }, { k: 'match', label: $t('debugConsole.match'), t: 'json' }, { k: 'within', label: $t('debugConsole.withinSimTimeS'), t: 'num' }],
  assert_kpi: [{ k: 'key', label: $t('common.kpi'), t: 'val' }, { k: 'op', label: '', t: 'op' }, { k: 'value', label: $t('common.value'), t: 'val' }],
};
const STEP_TPL: Record<string, any> = {
  setpoint: { label: $t('common.writeSetpoint'), step: { kind: 'setpoint', station: 'CNC1', tag: 'Monitoring/Feed/Override', value: 90 } },
  set_tag: { label: $t('debugConsole.setTagSimulateSensor'), step: { kind: 'set_tag', station: 'INS1', tag: 'Setpoint/Sensitivity', value: 0.7 } },
  fault: { label: $t('debugConsole.injectEquipmentFailure'), step: { kind: 'fault', station: 'CNC1', fault: 'failure' } },
  cell_fault: { label: $t('debugConsole.injectComponentFailureControlUnit'), step: { kind: 'cell_fault', station: 'CELL1', comp: 'S1', fault: 'sensor_stuck_on' } },
  comm_fault: { label: $t('audit.communicationFailure'), step: { kind: 'comm_fault', protocol: 'mqtt', mode: 'freeze', minutes: 0 } },
  wait: { label: $t('debugConsole.waitSimTimeInS'), step: { kind: 'wait', seconds: 60 } },
  wait_until: { label: $t('debugConsole.waitUntilConditionIsMet'), step: { kind: 'wait_until', cond: { kind: 'tag', id: 'CNC1', tag: 'Common/State', op: '==', value: 'Stopped' }, timeout: 300 } },
  assert_rest: { label: $t('debugConsole.assertApiValue'), step: { kind: 'assert', via: 'rest', station: 'CNC1', tag: 'Common/State', op: '==', value: 'Stopped' } },
  assert_opcua: { label: $t('debugConsole.assertOpcUaValue'), step: { kind: 'assert', via: 'opcua', station: 'CNC1', tag: 'Common/State', op: '==', value: 'Stopped', within: 6 } },
  assert_mqtt: { label: $t('debugConsole.assertMqttReceivedValue'), step: { kind: 'assert', via: 'mqtt', station: 'CNC1', tag: 'Common/State', op: '==', value: 'Stopped', within: 6 } },
  assert_mes: { label: $t('debugConsole.assertMesMessage'), step: { kind: 'assert_mes', topic: 'event', match: { station: 'CNC1', kind: 'fault' }, within: 60 } },
  assert_kpi: { label: $t('debugConsole.assertFactoryWideMetrics'), step: { kind: 'assert_kpi', key: 'good', op: '>', value: 0 } },
};
const MODE_FIELD: Record<string, string> = { latency: 'latency', drop_pct: 'drop_pct', value: 'value', rate: 'rate' };
function fieldsOf(st: any): F[] {
  const fs = FIELDS[st.kind] || [];
  if (st.kind !== 'comm_fault') return fs;
  const need = st.mode === 'latency' || st.mode === 'jitter' ? 'latency' : st.mode === 'drop' ? 'drop_pct' : st.mode === 'stuck' ? 'value' : st.mode === 'drift' ? 'rate' : '';
  return fs.filter((f) => !MODE_FIELD[f.k] || f.k === need).filter((f) => f.k !== 'tag' || st.station).filter((f) => st.mode || ['protocol', 'mode', 'station', 'tag'].includes(f.k));
}
const clone = (x: any) => JSON.parse(JSON.stringify(x));
function getP(o: any, path: string) { return path.split('.').reduce((a, k) => (a == null ? undefined : a[k]), o); }
function setP(o: any, path: string, v: any) {
  const ks = path.split('.'); let cur = o;
  for (const k of ks.slice(0, -1)) cur = cur[k] ||= (k === 'cond' ? { kind: 'tag' } : {});
  const last = ks[ks.length - 1];
  if (v === undefined || v === '') delete cur[last]; else cur[last] = v;
}
const typed = (v: string) => { const s = String(v ?? '').trim(); if (s === '') return ''; if (s === 'true' || s === 'false') return s === 'true'; const n = Number(s); return isNaN(n) ? s : n; };
const jsonOf = (v: any) => (v === undefined ? '' : JSON.stringify(v));
function setJson(st: any, k: string, v: string) { try { setP(st, k, v.trim() ? JSON.parse(v) : undefined); scriptErr.value = ''; } catch (e: any) { scriptErr.value = $t('debugConsole.step01IsNot', [sc.steps.indexOf(st) + 1, k, e.message]); } }
const faultsOf = (sid: string) => stations.value.find((s: any) => s.id === sid)?.faults || { failure: $t('forkPanel.equipmentFailureDowntime'), clear: $t('common.clearFailure') };
function changeKind(i: number, k: string) { const old = sc.steps[i]; sc.steps[i] = { ...clone(Object.values(STEP_TPL).find((x: any) => x.step.kind === k)?.step || { kind: k }), name: old.name }; }
function move(i: number, d: number) { const a = sc.steps; [a[i], a[i + d]] = [a[i + d], a[i]]; }
const resOf = (i: number) => run.value?.steps?.find((s: any) => s.i === i + 1);
const resIcon = (i: number) => { const r = resOf(i); if (!r) return run.value?.status === 'running' ? '·' : ''; return r.ok ? '✓' : r.ok === false ? '✗' : r.skipped ? '–' : '…'; };
const resClass = (i: number) => { const r = resOf(i); return !r ? '' : r.ok ? 'pass' : r.ok === false ? 'fail' : r.skipped ? 'skip' : 'busy'; };
function toScript() { const s = clone(sc); if (!s.stop_on_fail) delete s.stop_on_fail; return s; }
function fromScript(s: any) { Object.assign(sc, { name: s.name || $t('debugConsole.newTestScript'), speed: s.speed ?? 30, stop_on_fail: !!s.stop_on_fail, steps: s.steps || [] });
  for (const k of Object.keys(s)) if (!['name', 'speed', 'stop_on_fail', 'steps'].includes(k)) sc[k] = s[k]; }
function switchView(v: string) {
  if (v === 'json') { scriptText.value = JSON.stringify(toScript(), null, 2); scriptErr.value = ''; return; }
  try { fromScript(JSON.parse(scriptText.value || '{}')); scriptErr.value = ''; } catch (e: any) { scriptErr.value = $t('debugConsole.invalidJsonFixItBefore') + e.message; view.value = 'json'; }
}
function parsed() {
  if (view.value === 'table') return toScript();
  try { scriptErr.value = ''; return JSON.parse(scriptText.value || '{}'); } catch (e: any) { scriptErr.value = $t('debugConsole.invalidJson') + e.message; throw e; }
}
async function loadTests() { tests.value = await get(P(props.pid) + '/tests', true); }
async function loadStations() { try { stations.value = (await get(P(props.pid) + '/scenarios', true)).stations || []; } catch { stations.value = []; } }
async function openScript() {
  if (!tid.value) return;
  const r = await get(P(props.pid) + `/tests/${tid.value}`);
  fromScript(r.script); scriptText.value = JSON.stringify(r.script, null, 2);
  run.value = r.last ? await get(P(props.pid) + `/tests/runs/${r.last.id}`, true) : null;
}
function newScript() {
  tid.value = null; run.value = null;
  fromScript({ name: $t('debugConsole.newTestScript'), speed: 30, steps: [clone(STEP_TPL.setpoint.step), clone(STEP_TPL.assert_opcua.step)] });
  scriptText.value = JSON.stringify(toScript(), null, 2);
}
function addStep(k: string) {
  if (view.value === 'json') { try { fromScript(JSON.parse(scriptText.value || '{}')); } catch (e: any) { scriptErr.value = $t('debugConsole.invalidJson') + e.message; return; } }
  sc.steps.push(clone(STEP_TPL[k].step));
  if (view.value === 'json') scriptText.value = JSON.stringify(toScript(), null, 2);
}
async function saveScript() {
  const s = parsed();
  if (tid.value) await put(P(props.pid) + `/tests/${tid.value}`, { script: s });
  else tid.value = (await post(P(props.pid) + '/tests', { script: s })).id;
  ElMessage.success($t('common.saved'));
  loadTests();
}
async function delScript() {
  await ElMessageBox.confirm($t('debugConsole.deleteThisScript'), $t('common.delete'), { type: 'warning' });
  await del(P(props.pid) + `/tests/${tid.value}`);
  tid.value = null; fromScript({ steps: [] }); scriptText.value = ''; run.value = null; loadTests();
}
let stopRun: any = null;
async function runScript() {
  const s = parsed();
  const v = await post(P(props.pid) + '/tests/validate', { script: s });
  if (v.errors.length) { scriptErr.value = v.errors.join($t('common.k344')); return; }
  scriptErr.value = '';
  if (tid.value) await put(P(props.pid) + `/tests/${tid.value}`, { script: s });      // Saved script: save before running; run history is stored under this script.
  const r = tid.value ? await post(P(props.pid) + `/tests/${tid.value}/run`) : await post(P(props.pid) + '/tests/run', { script: s });
  running.value = true;
  run.value = { id: r.run_id, status: 'running', steps: [] };
  stopRun?.();
  stopRun = poll(async () => {
    run.value = await get(P(props.pid) + `/tests/runs/${r.run_id}`, true);
    if (run.value.status !== 'running') { running.value = false; stopRun?.(); loadTests(); }
  }, 700);
}
async function cancel() { if (run.value?.id) await post(P(props.pid) + `/tests/runs/${run.value.id}/cancel`); }
function junit() { saveFile(P(props.pid) + `/tests/runs/${run.value.id}/junit.xml`, `junit-${run.value.id}.xml`); }

let stops: any[] = [];
function startPolls() {
  stops.forEach((f) => f());
  prevVals = {}; tree.value = []; msgs.value = []; seq = 0;
  stops = [poll(loadTree, 2000), poll(loadStatus, 3000), poll(loadMsgs, 1000)];
  loadTests(); loadStations();
}
watch(() => props.pid, startPolls);
watch(tab, (t) => { if (t === 'points') loadTree(); if (t === 'tests' && !sc.steps.length && !tid.value) newScript(); });
onMounted(startPolls);
onBeforeUnmount(() => { stops.forEach((f) => f()); stopRun?.(); });
</script>

<style scoped>
.dc-tabs { flex: 1; min-height: 0; }
.dc-tabs :deep(.el-tabs__header) { margin: 0; padding: 0 10px; }
.dc-tabs :deep(.el-tabs__content) { flex: 1; min-height: 0; overflow: auto; }
.pts .addr { color: var(--el-color-primary); font-size: 11px; word-break: break-all; }
.pts .val { white-space: nowrap; }
.eps { display: grid; gap: 4px; } .ep { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 12px; } .ep > .vp-muted:first-child { width: 72px; }
.ep code { background: var(--el-fill-color-light); color: var(--el-text-color-primary); padding: 1px 6px; border-radius: 4px; word-break: break-all; }
.lnk { cursor: pointer; margin-right: 6px; font-family: Consolas, monospace; }
.rule { margin-top: 4px; }
.nowrap { flex-wrap: nowrap; }
.msg-head { display: flex; gap: 8px; border-bottom: 1px solid var(--el-border-color-lighter); padding: 2px; }
.c1 { width: 96px; flex: none; } .c2 { flex: 1; min-width: 0; white-space: nowrap; overflow: hidden; }
.msg { border-bottom: 1px solid var(--el-border-color-extra-light); padding: 4px 2px; cursor: pointer; }
.msg.mes .topic { color: var(--el-color-primary); font-weight: 600; }
.msg.err .topic { color: var(--bad, var(--el-color-danger)); font-weight: 600; }
.msg .topic { word-break: break-all; min-width: 0; }
.payload { margin: 4px 0; padding: 6px; background: var(--el-fill-color-light); border-radius: 4px; font-size: 11.5px; white-space: pre-wrap; word-break: break-all; }
.ell { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mono-ta :deep(textarea), .mono-in :deep(input) { font-family: Consolas, 'Courier New', monospace; font-size: 12px; }
.step { border: 1px solid var(--el-border-color-lighter); border-left: 3px solid var(--el-border-color); border-radius: 6px; padding: 6px 8px; margin-bottom: 6px; background: var(--el-fill-color-blank); }
.step.pass { border-left-color: var(--ok, var(--el-color-success)); } .step.fail { border-left-color: var(--bad, var(--el-color-danger)); } .step.skip { border-left-color: var(--el-text-color-placeholder); }
.step.busy { border-left-color: var(--el-color-primary); }
.step .idx { width: 18px; text-align: right; color: var(--el-text-color-secondary); font-size: 12px; flex: none; }
.step .res { width: 14px; font-weight: 700; flex: none; } .step.pass .res { color: var(--ok, var(--el-color-success)); } .step.fail .res { color: var(--bad, var(--el-color-danger)); }
.step .fields { margin: 6px 0 2px; gap: 4px 6px; } .step .sname { margin-top: 4px; }
.step .el-button + .el-button { margin-left: 0; } .step > .vp-row.nowrap { gap: 4px; } .step > .vp-row.nowrap .el-button { padding: 0 4px; }
.res-row { display: flex; gap: 8px; padding: 4px 0; border-bottom: 1px solid var(--el-border-color-extra-light); }
.res-row .ic { width: 14px; font-weight: 700; }
</style>
