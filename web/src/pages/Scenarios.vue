<template>
  <div class="page" v-if="d">
    <div class="page-head"><h2>{{ $t('common.scenario') }}</h2><span class="sub">{{ $t('scenarios.scheduleFailuresDisturbancesAndOpera') }}</span><span class="grow" />
      <el-button v-if="edit" type="primary" @click="newSc"><el-icon><Plus /></el-icon>{{ $t('scenarios.newScenario') }}</el-button></div>
    <div v-if="run" class="card running">
      <h3><span class="tag-st st-running">{{ $t('common.running2') }}</span>{{ run.name }} <small>{{ $t('scenarios.startedAt0Elapsed1', [run.start, run.elapsed_min]) }}</small><span class="grow" />
        <el-button v-if="edit" size="small" type="danger" plain @click="stop">{{ $t('common.stop') }}</el-button><el-button size="small" @click="router.push(`/p/${pid}/workbench`)">{{ $t('scenarios.viewInWorkbench') }}</el-button></h3>
      <el-steps :active="run.steps.filter((s: any) => s.done).length" finish-status="success" align-center>
        <el-step v-for="(s, i) in run.steps" :key="i" :title="$t('common.n0Min', [s.at])" :description="`${s.action} ${s.target || ''} ${s.tag || ''} ${s.value ?? ''}${s.done ? '' : $t('scenarios.after0Min', [s.eta_min])}`" />
      </el-steps>
      <div class="log"><div v-for="(l, i) in run.log.slice().reverse()" :key="i" class="small"><span class="mono muted">{{ l.t.slice(11) }}</span> {{ l.msg }}</div></div>
    </div>
    <div class="grid g3" style="margin-top:14px">
      <div v-for="s in d.items" :key="s.id" class="card sc">
        <h3>{{ s.name }}<span v-if="s.builtin" class="tag-st">{{ $t('scenarios.builtIn') }}</span><span class="grow" /><span class="small muted">{{ $t('scenarios.n0Steps1', [s.steps.length, dur(s)]) }}</span></h3>
        <p class="small">{{ s.descr || $t('scenarios.noNotes') }}</p>
        <p v-if="s.missing.length" class="small warn">{{ $t('scenarios.thisFactoryHasNo0', [s.missing.join($t('common.k360'))]) }}</p>
        <div class="acts"><el-button v-if="edit" size="small" type="primary" :disabled="!!run" @click="start(s)">{{ $t('common.run') }}</el-button>
          <el-button size="small" @click="open(s)">{{ s.builtin || !edit ? $t('scenarios.view') : $t('common.edit') }}</el-button>
          <el-button v-if="edit && s.builtin" size="small" @click="copy(s)">{{ $t('scenarios.copyToMyScenarios') }}</el-button>
          <el-popconfirm v-if="edit && !s.builtin" :title="$t('scenarios.deleteThisScenario')" @confirm="remove(s)"><template #reference><el-button size="small" type="danger" plain>{{ $t('common.delete') }}</el-button></template></el-popconfirm></div>
      </div>
    </div>
    <div class="card" style="margin-top:14px" v-if="d.status.history.length"><h3>{{ $t('scenarios.runHistory') }}</h3>
      <el-table :data="d.status.history" size="small"><el-table-column prop="name" :label="$t('common.scenario')" /><el-table-column prop="start" :label="$t('common.start')" width="160" /><el-table-column prop="end" :label="$t('heats.end')" width="160" />
        <el-table-column prop="why" :label="$t('scenarios.endReason')" /><el-table-column :label="$t('commandPalette.execute')" width="300"><template #default="{ row }"><span class="small">{{ row.log.map((l: any) => l.msg).join($t('common.k344')) }}</span></template></el-table-column></el-table></div>

    <el-dialog v-model="dlg" :title="cur.builtin ? cur.name : (cur.id ? $t('audit.editScenario') : $t('scenarios.newScenario2'))" width="min(920px, 96vw)">
      <el-form label-width="70px" size="small"><el-form-item :label="$t('common.name')"><el-input v-model="cur.name" :disabled="cur.builtin" /></el-form-item>
        <el-form-item :label="$t('common.description')"><el-input v-model="cur.descr" type="textarea" :rows="2" :disabled="cur.builtin" /></el-form-item></el-form>
      <el-table :data="cur.steps" size="small">
        <el-table-column :label="$t('sections.minuteN')" width="100"><template #default="{ row }"><el-input-number v-model="row.at" :min="0" :controls="false" size="small" style="width:70px" :disabled="cur.builtin" /></template></el-table-column>
        <el-table-column :label="$t('scenarios.action')" width="130"><template #default="{ row }"><el-select v-model="row.action" size="small" :disabled="cur.builtin"><el-option v-for="(n, k) in d.actions" :key="k" :label="n" :value="k" /></el-select></template></el-table-column>
        <el-table-column :label="$t('common.object')" width="150"><template #default="{ row }">
          <el-select v-if="row.action === 'comm'" v-model="row.target" size="small" :disabled="cur.builtin"><el-option v-for="p in ['opcua', 'modbus', 'mqtt']" :key="p" :label="p" :value="p" /></el-select>
          <el-select v-else-if="!['absent', 'speed', 'note'].includes(row.action)" v-model="row.target" size="small" filterable :disabled="cur.builtin">
            <el-option v-for="s in d.stations" :key="s.id" :label="`${s.id} ${s.name}`" :value="s.id" /></el-select></template></el-table-column>
        <el-table-column :label="$t('scenarios.tagFailure')" min-width="170"><template #default="{ row }">
          <el-select v-if="['write', 'ramp'].includes(row.action)" v-model="row.tag" size="small" filterable :disabled="cur.builtin"><el-option v-for="t in stOf(row.target)?.writable || []" :key="t" :label="t" :value="t" /></el-select>
          <el-select v-else-if="row.action === 'fault'" v-model="row.value" size="small" :disabled="cur.builtin"><el-option v-for="(n, k) in stOf(row.target)?.faults || {}" :key="k" :label="n" :value="k" /></el-select>
          <el-select v-else-if="row.action === 'comm'" v-model="row.value" size="small" :disabled="cur.builtin"><el-option v-for="(n, k) in MODES" :key="k" :label="n" :value="k" /></el-select></template></el-table-column>
        <el-table-column :label="$t('common.value')" width="110"><template #default="{ row }"><el-input v-if="['write', 'ramp', 'absent', 'speed', 'note'].includes(row.action)" v-model="row.value" size="small" :disabled="cur.builtin" /></template></el-table-column>
        <el-table-column :label="$t('scenarios.durationMin')" width="90"><template #default="{ row }"><el-input-number v-if="['ramp', 'disable', 'absent', 'comm'].includes(row.action)" v-model="row.minutes" :controls="false" size="small" style="width:65px" :disabled="cur.builtin" /></template></el-table-column>
        <el-table-column width="45"><template #default="{ $index }"><el-button v-if="!cur.builtin" link type="danger" @click="cur.steps.splice($index, 1)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
      </el-table>
      <el-button v-if="!cur.builtin" size="small" style="margin-top:8px" @click="cur.steps.push({ at: 0, action: 'fault', target: d.stations[0]?.id })">{{ $t('scenarios.step') }}</el-button>
      <p class="small muted">{{ $t('scenarios.rampChangesTheSetpointLinearly') }}</p>
      <template #footer><el-button v-if="edit && !cur.builtin" type="primary" @click="saveSc">{{ $t('common.save') }}</el-button>
        <el-button v-if="edit" @click="dlg = false; start(cur)">{{ cur.builtin ? $t('common.run') : $t('scenarios.runWithoutSaving') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { canEdit, del, get, P, post } from '../api';

const props = defineProps<{ pid: string }>();
const router = useRouter(), api = P(props.pid), edit = canEdit();
const d = ref<any>(null), dlg = ref(false), cur = reactive<any>({ steps: [] });
const MODES = { freeze: $t('scenarios.dataFreeze'), bad: $t('live.badQuality'), disconnect: $t('common.disconnected'), latency: $t('live.latency') };
const run = computed(() => d.value?.status.running);
const stOf = (id: string) => d.value.stations.find((s: any) => s.id === id);
const dur = (s: any) => { const m = Math.max(0, ...s.steps.map((x: any) => (+x.at || 0) + (+x.minutes || 0))); return m >= 60 ? $t('scenarios.n0H', [(m / 60).toFixed(1)]) : $t('mesBar.n0Min', [m]); };
let t: any;
async function load() { d.value = await get(api + '/scenarios', true); }
onMounted(() => { load(); t = setInterval(load, 3000); });
onUnmounted(() => clearInterval(t));
function open(s: any) { Object.assign(cur, JSON.parse(JSON.stringify(s))); dlg.value = true; }
function newSc() { Object.assign(cur, { id: null, builtin: false, name: $t('scenarios.newScenario3'), descr: '', steps: [{ at: 0, action: 'fault', target: d.value.stations[0]?.id }] }); dlg.value = true; }
function copy(s: any) { Object.assign(cur, { ...JSON.parse(JSON.stringify(s)), id: null, builtin: false, name: s.name + $t('scenarios.copy') }); dlg.value = true; }
async function saveSc() { await post(api + '/scenarios', cur); ElMessage.success($t('common.saved')); dlg.value = false; load(); }
async function start(s: any) {
  await post(api + '/scenarios/run', s.builtin || s.id ? { id: s.id } : { name: s.name, steps: s.steps });
  ElMessage.success($t('scenarios.scenarioStarted')); load();
}
async function stop() { await post(api + '/scenarios/stop'); load(); }
async function remove(s: any) { await del(`${api}/scenarios/${s.id}`); load(); }
</script>

<style scoped>
.running { border-color: var(--hm-primary-soft-2); background: var(--hm-primary-soft); } .log { max-height: 140px; overflow: auto; margin-top: 10px; }
.sc { display: grid; align-content: start; gap: 4px; } .sc p { margin: 0; } .acts { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 6px; } .acts .el-button { margin: 0; }
</style>
