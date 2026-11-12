<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('common.dataSubmodels') }}</h2><span class="sub">{{ $t('tables.globalDataTablesOrderSchedule') }}</span></div>
    <el-tabs v-model="tab">
      <!-- ================= Data tables ================= -->
      <el-tab-pane :label="$t('tables.dataTables')" name="tables">
        <div class="grid main">
          <div class="card list">
            <div class="lh"><b>{{ $t('tables.dataTables') }}</b><span class="grow" />
              <el-button v-if="edit" size="small" @click="newTable">{{ $t('common.new') }}</el-button>
              <el-button v-if="edit" size="small" type="primary" @click="pickFile"><el-icon><Upload /></el-icon>{{ $t('tables.import') }}</el-button>
              <input ref="fileInp" type="file" accept=".csv,.xlsx,.xlsm,.txt" style="display:none" @change="onFile" /></div>
            <div v-for="t in list" :key="t.name" class="it click" :class="{ on: cur?.name === t.name && !isNew }" @click="open(t.name)">
              <b>{{ t.name }}</b> <span class="small muted">{{ $t('tables.n0Rows1Columns', [t.n_rows, t.columns.length]) }}</span>
              <div class="small muted" v-if="t.used_by.length">{{ $t('tables.referencedBy0', [t.used_by.map((u: any) => u.name).join($t('common.k360'))]) }}</div>
              <div class="small muted" v-else-if="t.desc">{{ t.desc }}</div>
            </div>
            <p v-if="!list.length" class="small muted">{{ $t('tables.noDataTablesYetImport') }}</p>
            <div class="help small">
              <b>{{ $t('library.howToUse') }}</b>
              <div>· <b>{{ $t('tables.orderScheduleDrivenIncomingParts') }}</b>{{ $t('tables.includeTimeProductQuantityOrder') }}</div>
              <div>· <b>{{ $t('tables.expressionLookups') }}</b>{{ $t('tables.tblTablenameKeyColumnnameLooks') }}</div>
              <div>· <b>{{ $t('mesNav.routings') }}</b>{{ $t('tables.columnsProductOperationNoEquipment') }}</div>
              <div>· <b>BOM</b>{{ $t('tables.columnsParentPartChildPart') }}</div>
              <div>{{ $t('tables.tableChangesTakeEffectImmediately') }}</div>
            </div>
          </div>
          <div class="card" v-if="cur">
            <h3><el-input v-model="cur.name" size="small" style="width:180px" :disabled="!edit" /><el-input v-model="cur.desc" size="small" :placeholder="$t('common.description')" style="width:240px" :disabled="!edit" />
              <span class="grow" />
              <template v-if="edit">
                <el-button size="small" @click="addRow">{{ $t('tables.row') }}</el-button><el-button size="small" @click="addCol">{{ $t('tables.column') }}</el-button>
                <el-button size="small" type="primary" :loading="busy" @click="save">{{ $t('common.save') }}</el-button></template>
              <el-button v-if="!isNew" size="small" @click="download(`${api}/tables/${encodeURIComponent(orig)}/export.csv`)">{{ $t('tables.exportCsv') }}</el-button>
              <el-dropdown v-if="edit && !isNew" size="small" @command="toOps" style="margin-left:6px">
                <el-button size="small">{{ $t('tables.generateEditCommands') }} <el-icon><ArrowDown /></el-icon></el-button>
                <template #dropdown><el-dropdown-menu><el-dropdown-item command="routing">{{ $t('tables.byRoutingProcessingTimesBy') }}</el-dropdown-item><el-dropdown-item command="bom">{{ $t('tables.byBomAssemblyBlocks') }}</el-dropdown-item></el-dropdown-menu></template>
              </el-dropdown>
              <el-popconfirm v-if="edit && !isNew" :title="$t('tables.deleteThisTable')" @confirm="remove"><template #reference><el-button size="small" type="danger" plain>{{ $t('common.delete') }}</el-button></template></el-popconfirm></h3>
            <div class="small muted" v-if="usedBy.length" style="margin-bottom:6px">{{ $t('tables.referencedBy02', [usedBy.map((u: any) => $t('common.n012', [u.name, u.id])).join($t('common.k360'))]) }}</div>
            <el-table :data="pageRows" size="small" border max-height="560">
              <el-table-column type="index" :index="(i: number) => (page - 1) * PS + i + 1" width="50" fixed />
              <el-table-column v-for="(c, ci) in cur.columns" :key="ci" min-width="120">
                <template #header><div class="ch"><el-input v-model="cur.columns[ci]" size="small" :disabled="!edit" @change="(v: string) => renameCol(ci, v)" />
                  <el-button v-if="edit" link type="danger" size="small" @click="delCol(ci)"><el-icon><Close /></el-icon></el-button></div></template>
                <template #default="{ row }"><el-input v-model="row[c]" size="small" :disabled="!edit" class="cell" /></template>
              </el-table-column>
              <el-table-column width="46" fixed="right"><template #default="{ row }"><el-button v-if="edit" link type="danger" @click="delRow(row)"><el-icon><Delete /></el-icon></el-button></template></el-table-column>
            </el-table>
            <el-pagination v-if="cur.rows.length > PS" v-model:current-page="page" :page-size="PS" :total="cur.rows.length" layout="prev, pager, next, total" small style="margin-top:6px" />
          </div>
        </div>
      </el-tab-pane>

      <!-- ================= Submodels ================= -->
      <el-tab-pane :label="$t('tables.submodels')" name="sub">
        <div class="card">
          <h3>{{ $t('tables.submodelDefinitions') }} <small>{{ $t('tables.packageASectionOfA') }}</small><span class="grow" />
            <el-select v-if="edit" v-model="tplPick" size="small" :placeholder="$t('tables.createFromEditorTemplate')" style="width:220px" filterable>
              <el-option v-for="t in subs.templates" :key="t.id" :label="$t('tables.n01Blocks', [t.name, t.blocks])" :value="t.id" /></el-select>
            <el-button v-if="edit" size="small" type="primary" :disabled="!tplPick" @click="fromTpl">{{ $t('tables.create') }}</el-button></h3>
          <el-table :data="subs.defs" size="small">
            <el-table-column :label="$t('common.no2')" prop="id" width="110" />
            <el-table-column :label="$t('common.name')" prop="name" min-width="140" />
            <el-table-column :label="$t('tables.internalBlocks')" min-width="220"><template #default="{ row }"><span class="small">{{ row.blocks.map((b: any) => b.name || b.id).join($t('common.k360')) }}</span></template></el-table-column>
            <el-table-column :label="$t('tables.entryExit')" min-width="150"><template #default="{ row }"><span class="small mono">{{ row.entry_resolved?.[0] || '—' }} → {{ row.exit_resolved?.[0] || '—' }}</span></template></el-table-column>
            <el-table-column :label="$t('tables.exposedParameters')" min-width="200"><template #default="{ row }"><span class="small">{{ (row.expose || []).map((e: any) => `${e.label || e.name}→${(e.targets || []).join(',')}`).join($t('common.k344')) || '—' }}</span></template></el-table-column>
            <el-table-column :label="$t('tables.usedBy')" min-width="100"><template #default="{ row }"><span class="small">{{ row.used_by.join($t('common.k360')) || '—' }}</span></template></el-table-column>
            <el-table-column width="120"><template #default="{ row }"><el-button v-if="edit" link type="primary" @click="editSub(row)">{{ $t('common.edit') }}</el-button>
              <el-popconfirm v-if="edit" :title="$t('tables.deleteThisSubmodelDefinition')" @confirm="delSub(row.id)"><template #reference><el-button link type="danger">{{ $t('common.delete') }}</el-button></template></el-popconfirm></template></el-table-column>
          </el-table>
          <p class="small muted">{{ $t('tables.exposedParametersEnterNameValue') }}</p>
        </div>
      </el-tab-pane>

      <!-- ================= Background images ================= -->
      <el-tab-pane :label="$t('tables.dxfUnderlay')" name="dxf">
        <div class="card"><h3>{{ $t('tables.importDxfUnderlay') }} <small>{{ $t('tables.supportsLinesPolylinesIncludingArc') }}</small></h3>
          <DxfImport :pid="pid" @done="(r: any) => (dxf = r)" />
          <div v-if="dxf && edit" style="margin-top:10px"><el-button type="primary" size="small" :loading="busy" @click="dxfToDraft">{{ $t('tables.setAsFloorPlanUnderlay') }}</el-button>
            <span class="small muted">{{ $t('tables.onceSavedYouCanAdjust') }}</span></div>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="opsDlg" :title="opsKind === 'bom' ? $t('tables.bomEditCommands') : $t('tables.routingEditCommands')" width="min(760px, 96vw)">
      <div v-for="i in ops?.issues || []" :key="i.msg" :class="i.level === 'error' ? 'bad' : 'warn'" class="small">· {{ i.msg }}</div>
      <el-table :data="ops?.ops || []" size="small" style="margin-top:6px">
        <el-table-column :label="$t('tables.block')" prop="id" width="110" />
        <el-table-column :label="$t('common.settings')"><template #default="{ row }"><span class="small mono wrap">{{ JSON.stringify(row.set) }}</span></template></el-table-column>
      </el-table>
      <template #footer><el-button type="primary" :disabled="!ops?.ops?.length" :loading="busy" @click="opsToDraft">{{ $t('tables.saveToDraft') }}</el-button></template>
    </el-dialog>
    <el-dialog v-model="subDlg" :title="$t('tables.editSubmodel')" width="min(760px, 96vw)">
      <el-form v-if="sub" label-width="90px" size="small">
        <el-form-item :label="$t('common.name')"><el-input v-model="sub.name" /></el-form-item>
        <el-form-item :label="$t('tables.entryBlock')"><el-select v-model="sub.entryId" clearable :placeholder="$t('tables.autoFirstBlockWithNo')"><el-option v-for="b in sub.blocks" :key="b.id" :label="`${b.id} ${b.name || ''}`" :value="b.id" /></el-select></el-form-item>
        <el-form-item :label="$t('tables.exitBlock')"><el-select v-model="sub.exitId" clearable :placeholder="$t('tables.autoLastBlockWithNo')"><el-option v-for="b in sub.blocks" :key="b.id" :label="`${b.id} ${b.name || ''}`" :value="b.id" /></el-select></el-form-item>
        <el-form-item :label="$t('tables.exposedParameters')"><el-input v-model="sub.exposeText" type="textarea" :rows="6" class="mono" />
          <div class="small muted">{{ $t('tables.jsonListEGName') }}</div></el-form-item>
      </el-form>
      <template #footer><el-button type="primary" @click="saveSub">{{ $t('common.save') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { computed, onMounted, ref } from 'vue';
import { canEdit, del, download, get, P, post, put } from '../api';
import DxfImport from '../components/DxfImport.vue';

const props = defineProps<{ pid: string }>();
const api = P(props.pid), edit = canEdit(), PS = 100;
const tab = ref('tables'), list = ref<any[]>([]), cur = ref<any>(null), orig = ref(''), isNew = ref(false), usedBy = ref<any[]>([]), busy = ref(false), page = ref(1);
const fileInp = ref<HTMLInputElement>(), opsDlg = ref(false), ops = ref<any>(null), opsKind = ref('routing');
const subs = ref<any>({ defs: [], templates: [] }), tplPick = ref(''), subDlg = ref(false), sub = ref<any>(null), dxf = ref<any>(null);
const pageRows = computed(() => cur.value.rows.slice((page.value - 1) * PS, page.value * PS));

async function load() { list.value = await get(api + '/tables'); }
async function loadSubs() { subs.value = await get(api + '/submodels'); }
onMounted(async () => { await load(); if (list.value[0]) open(list.value[0].name); loadSubs(); });
async function open(name: string) {
  const t = await get(`${api}/tables/${encodeURIComponent(name)}`);
  cur.value = { name: t.name, desc: t.desc || '', columns: [...t.columns], rows: t.rows.map((r: any) => ({ ...r })) };
  orig.value = t.name; usedBy.value = t.used_by || []; isNew.value = false; page.value = 1;
}
function newTable() {
  cur.value = { name: $t('common.order') + (list.value.length + 1), desc: '', columns: [$t('common.time'), $t('common.product'), $t('plan.quantity'), $t('common.order')], rows: [{ [$t('common.time')]: 0, [$t('common.product')]: 'A', [$t('plan.quantity')]: 10, [$t('common.order')]: 'SO-001' }] };
  orig.value = cur.value.name; usedBy.value = []; isNew.value = true; page.value = 1;
}
function addRow() { cur.value.rows.push(Object.fromEntries(cur.value.columns.map((c: string) => [c, '']))); page.value = Math.ceil(cur.value.rows.length / PS); }
function delRow(r: any) { cur.value.rows.splice(cur.value.rows.indexOf(r), 1); }
function addCol() { let n = 1; while (cur.value.columns.includes($t('tables.column2') + n)) n++; cur.value.columns.push($t('tables.column2') + n); }
function delCol(i: number) { const c = cur.value.columns.splice(i, 1)[0]; cur.value.rows.forEach((r: any) => delete r[c]); }
function renameCol(i: number, v: string) {
  // Column renamed: move each row's old key to the new key (resolve the old name from the saved list position)
  const old = Object.keys(cur.value.rows[0] || {}).find((k) => !cur.value.columns.includes(k));
  if (old) cur.value.rows.forEach((r: any) => { r[v] = r[old]; delete r[old]; });
}
async function save() {
  busy.value = true;
  try {
    const t = await put(`${api}/tables/${encodeURIComponent(orig.value)}`, cur.value);
    ElMessage.success($t('common.saved')); await load(); open(t.name);
  } finally { busy.value = false; }
}
async function remove() { await del(`${api}/tables/${encodeURIComponent(orig.value)}`); cur.value = null; await load(); if (list.value[0]) open(list.value[0].name); }
function pickFile() { fileInp.value?.click(); }
function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = async () => {
    busy.value = true;
    try {
      const t = await post(api + '/tables/import', { filename: f.name, data_url: rd.result, name: f.name.replace(/\.[^.]+$/, '') });
      ElMessage.success($t('tables.imported0Rows', [t.n_rows])); await load(); open(t.name);
    } finally { busy.value = false; }
  };
  rd.readAsDataURL(f);
  (e.target as HTMLInputElement).value = '';
}
async function toOps(kind: string) { opsKind.value = kind; ops.value = await post(`${api}/tables/${encodeURIComponent(orig.value)}/ops`, { kind }); opsDlg.value = true; }
async function writeDraft(opsList: any[]) {
  const m = (await get(api + '/model')).model;
  const r = await post(api + '/model/ops', { model: m, ops: opsList });
  await put(api + '/model', { model: r.model });
  return r;
}
async function opsToDraft() {
  busy.value = true;
  try { const r = await writeDraft(ops.value.ops); opsDlg.value = false; ElMessage.success($t('tables.savedToDraft0Commands', [ops.value.ops.length, r.validation.ok ? '' : $t('tables.theDraftContainsErrorsCheck')])); } finally { busy.value = false; }
}
async function dxfToDraft() {
  busy.value = true;
  try { await writeDraft([{ op: 'update_plant', set: { 'plant.underlay': dxf.value.underlay } }]); ElMessage.success($t('tables.underlaySavedToDraftView')); } finally { busy.value = false; }
}
async function fromTpl() { await post(api + '/submodels/from-template', { template: tplPick.value }); tplPick.value = ''; ElMessage.success($t('tables.submodelDefinitionCreated')); loadSubs(); }
function editSub(d: any) {
  sub.value = { ...JSON.parse(JSON.stringify(d)), entryId: d.entry?.block || (typeof d.entry === 'string' ? d.entry : ''), exitId: d.exit?.block || (typeof d.exit === 'string' ? d.exit : ''),
    exposeText: JSON.stringify(d.expose || [], null, 1) };
  subDlg.value = true;
}
async function saveSub() {
  let expose;
  try { expose = JSON.parse(sub.value.exposeText || '[]'); } catch { ElMessage.error($t('tables.exposedParametersAreNotValid')); return; }
  const s = sub.value;
  await put(`${api}/submodels/${s.id}`, { name: s.name, desc: s.desc, blocks: s.blocks, links: s.links, expose,
    entry: s.entryId ? { block: s.entryId, port: 'in' } : null, exit: s.exitId ? { block: s.exitId, port: 'out' } : null });
  subDlg.value = false; ElMessage.success($t('common.saved')); loadSubs();
}
async function delSub(id: string) { await del(`${api}/submodels/${id}`); loadSubs(); }
</script>

<style scoped>
.main { grid-template-columns: 300px minmax(0, 1fr); }
.list { max-height: calc(100vh - 190px); overflow: auto; } .lh { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
.it { padding: 7px 8px; border-radius: var(--hm-r-md); border-bottom: 1px solid var(--hm-border); cursor: pointer; } .it:hover { background: var(--hm-surface-3); } .it.on { background: var(--hm-primary-soft); box-shadow: inset 3px 0 0 var(--hm-primary); }
.help { background: var(--hm-surface-2); border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); padding: 8px 10px; margin-top: 12px; line-height: 1.7; color: var(--hm-text-2); }
.ch { display: flex; align-items: center; gap: 2px; } .cell :deep(.el-input__wrapper) { box-shadow: none; padding: 0 4px; }
.wrap { white-space: normal; word-break: break-all; }
@media (max-width: 900px) { .main { grid-template-columns: 1fr !important; } }
</style>
