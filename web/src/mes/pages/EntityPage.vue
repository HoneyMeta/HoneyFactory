<template>
  <div class="page" v-if="E">
    <div class="page-head">
      <h2>{{ E.label }}</h2><span class="cnt" data-k="mes-total">{{ $t('entityPage.n0Records', [total]) }}</span>
      <span class="sub">{{ E.module_label || E.module }}{{ E.internal ? $t('entityPage.recordedAutomatically') : '' }}</span>
    </div>
    <div class="card tbar" data-k="mes-toolbar">
      <el-input v-model="q" :placeholder="$t('entityPage.searchNoName')" clearable style="width:220px" @change="load(1)"><template #prefix><el-icon><Search /></el-icon></template></el-input>
      <el-select v-for="f in enumFilters" :key="f.name" v-model="filters[f.name]" :placeholder="f.label" clearable style="width:130px" @change="load(1)">
        <el-option v-for="(v, k) in f.enum" :key="k" :label="v" :value="k" />
      </el-select>
      <span class="grow" />
      <el-tooltip :content="$t('common.refresh')"><el-button @click="load()"><el-icon><Refresh /></el-icon></el-button></el-tooltip>
      <el-button @click="exportCsv"><el-icon><Download /></el-icon>{{ $t('entityPage.export') }}</el-button>
      <el-button v-if="!E.internal && writable" type="primary" @click="openForm()"><el-icon><Plus /></el-icon>{{ $t('entityPage.new') }}</el-button>
    </div>
    <div class="card tcard">
      <el-table :data="rows" v-loading="loading" highlight-current-row @row-click="openDetail" @sort-change="onSort" style="width:100%" height="calc(100vh - 330px)">
        <el-table-column v-for="f in cols" :key="f.name" :prop="f.name" :label="f.label" :sortable="'custom'" :min-width="colWidth(f)" :align="isNum(f) ? 'right' : 'left'">
          <template #default="{ row }"><Cell :f="f" :row="row" /></template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total" :page-sizes="[20, 50, 100, 200]" layout="total, sizes, prev, pager, next"
          @current-change="load()" @size-change="load(1)" />
      </div>
    </div>

    <!-- Detail -->
    <el-drawer v-model="drawer" :size="drawerSize" :title="detailTitle" destroy-on-close>
      <template v-if="detail">
        <div class="acts">
          <el-button v-for="(lab, a) in acts(E.name, detail.item)" :key="a" type="primary" plain size="small" @click="doAction(E.name, detail.item, a as string, lab)" :disabled="!writable">{{ lab }}</el-button>
          <el-button v-if="E.name === 'insp_record' && writable" size="small" type="primary" plain @click="openValues">{{ $t('entityPage.enterInspectionValues') }}</el-button>
          <el-button v-if="E.name === 'part' || (detail.item.sn && E.name !== 'part')" size="small" @click="router.push('/mes/trace?sn=' + detail.item.sn)">{{ $t('common.traceability') }}</el-button>
          <el-button v-if="E.name === 'work_order'" size="small" @click="router.push('/mes/production/gantt')">{{ $t('entityPage.schedulingGantt') }}</el-button>
          <el-button v-if="E.name === 'equipment'" size="small" @click="router.push('/mes/equipment/oee?eid=' + detail.item.id)">OEE</el-button>
          <span class="grow" />
          <el-button v-if="!E.internal && writable" size="small" @click="openForm(detail.item)"><el-icon><Edit /></el-icon>{{ $t('entityPage.edit') }}</el-button>
          <el-popconfirm v-if="!E.internal && writable" :title="$t('entityPage.deleteThisRecord')" @confirm="remove(detail.item)">
            <template #reference><el-button size="small" type="danger" plain><el-icon><Delete /></el-icon></el-button></template>
          </el-popconfirm>
        </div>
        <el-descriptions :column="descCols" border size="small">
          <el-descriptions-item v-for="f in E.fields.filter((x: any) => x.name !== 'password_hash')" :key="f.name" :label="f.label" :span="f.t === 'text' || f.t === 'json' ? descCols : 1">
            <Cell :f="f" :row="detail.item" full />
          </el-descriptions-item>
        </el-descriptions>
        <template v-for="(items, child) in detail.children" :key="child">
          <h4 class="child-h">{{ ent(String(child))?.label }} <small>{{ $t('common.n03', [items.length]) }}</small>
            <el-button v-if="!ent(String(child))?.internal && writable" size="small" link type="primary" @click="addChild(String(child))">{{ $t('entityPage.new2') }}</el-button></h4>
          <el-table :data="items" size="small" border max-height="360">
            <el-table-column v-for="f in childCols(String(child))" :key="f.name" :label="f.label" :min-width="colWidth(f)">
              <template #default="{ row }"><Cell :f="f" :row="row" /></template>
            </el-table-column>
            <el-table-column v-if="Object.keys(ent(String(child))?.actions || {}).length || !ent(String(child))?.internal" label="" width="140" fixed="right">
              <template #default="{ row }">
                <el-button v-for="(lab, a) in acts(String(child), row)" :key="a" link type="primary" size="small" @click="doAction(String(child), row, String(a), lab)">{{ lab }}</el-button>
                <el-button v-if="!ent(String(child))?.internal && writable" link size="small" @click="openForm(row, String(child))">{{ $t('common.edit') }}</el-button>
              </template>
            </el-table-column>
          </el-table>
        </template>
      </template>
    </el-drawer>

    <!-- Form -->
    <el-dialog v-model="formOpen" :title="(form.id ? $t('common.edit') : $t('common.add')) + (ent(formEntity)?.label || '')" width="min(720px, 96vw)" destroy-on-close>
      <el-form label-width="110px" :model="form">
        <div class="form-grid">
          <el-form-item v-for="f in formFields" :key="f.name" :label="f.label" :required="f.req" :class="{ wide: f.t === 'text' || f.t === 'json' }">
            <el-input v-if="f.auto && !form.id" disabled :placeholder="$t('entityPage.autoGenerated')" />
            <el-select v-else-if="f.t === 'enum'" v-model="form[f.name]" clearable style="width:100%"><el-option v-for="(v, k) in f.enum" :key="k" :label="v" :value="k" /></el-select>
            <RefSelect v-else-if="f.t === 'ref'" v-model="form[f.name]" :entity="f.ref" :label="form[f.name + '__label']" />
            <el-input-number v-else-if="f.t === 'int' || f.t === 'float'" v-model="form[f.name]" :step="f.t === 'int' ? 1 : 0.01" :controls="false" style="width:100%" />
            <el-switch v-else-if="f.t === 'bool'" v-model="form[f.name]" />
            <el-date-picker v-else-if="f.t === 'date'" v-model="form[f.name]" type="date" value-format="YYYY-MM-DD" style="width:100%" />
            <el-date-picker v-else-if="f.t === 'datetime'" v-model="form[f.name]" type="datetime" value-format="YYYY-MM-DD HH:mm:ss" style="width:100%" />
            <el-input v-else-if="f.t === 'text' || f.t === 'json'" v-model="form[f.name]" type="textarea" :rows="3" />
            <el-input v-else v-model="form[f.name]" :placeholder="f.hint" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer><el-button @click="formOpen = false">{{ $t('common.cancel') }}</el-button><el-button type="primary" @click="save">{{ $t('common.save') }}</el-button></template>
    </el-dialog>

    <!-- Action parameters -->
    <el-dialog v-model="actOpen" :title="act.label" width="min(480px, 96vw)">
      <el-form label-width="96px">
        <el-form-item v-for="f in act.fields" :key="f.name" :label="f.label">
          <RefSelect v-if="f.t === 'ref'" v-model="act.body[f.name]" :entity="f.ref" />
          <el-select v-else-if="f.t === 'enum'" v-model="act.body[f.name]" style="width:100%"><el-option v-for="(v, k) in f.enum" :key="k" :label="v" :value="k" /></el-select>
          <el-input v-else v-model="act.body[f.name]" :type="f.t === 'text' ? 'textarea' : 'text'" />
        </el-form-item>
      </el-form>
      <template #footer><el-button @click="actOpen = false">{{ $t('common.cancel') }}</el-button><el-button type="primary" :loading="act.busy" @click="runAction">{{ $t('entityPage.ok') }}</el-button></template>
    </el-dialog>

    <!-- Inspection value entry -->
    <el-dialog v-model="valOpen" :title="$t('entityPage.enterInspectionValuesJudgedAutomatic')" width="min(640px, 96vw)">
      <el-table :data="valItems" size="small">
        <el-table-column prop="name" :label="$t('entityPage.item')" /><el-table-column prop="std" :label="$t('entityPage.standard')" />
        <el-table-column :label="$t('entityPage.measured')" width="160"><template #default="{ row }">
          <el-input-number v-if="row.lo != null || row.hi != null" v-model="row.value" :controls="false" style="width:130px" />
          <el-select v-else v-model="row.ok" style="width:130px"><el-option :value="true" :label="$t('common.good')" /><el-option :value="false" :label="$t('view3DHover.ng')" /></el-select>
        </template></el-table-column>
      </el-table>
      <template #footer><el-button type="primary" @click="saveValues">{{ $t('entityPage.saveJudge') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, defineComponent, h, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { canWrite, del, ent, get, openFile, post, put } from '../api';
import RefSelect from '../components/RefSelect.vue';

const props = defineProps<{ entity: string }>();
const route = useRoute(), router = useRouter();
const E = computed(() => ent(props.entity));
const writable = computed(() => E.value && canWrite(E.value.module));
const rows = ref<any[]>([]), total = ref(0), page = ref(1), size = ref(20), loading = ref(false), q = ref('');
const filters = reactive<Record<string, any>>({}), sort = ref('');
const drawer = ref(false), detail = ref<any>(null);
const formOpen = ref(false), form = reactive<any>({}), formEntity = ref('');
const actOpen = ref(false), act = reactive<any>({ fields: [], body: {}, label: '', entity: '', row: null, name: '', busy: false });
const valOpen = ref(false), valItems = ref<any[]>([]);
const drawerSize = innerWidth < 800 ? '100%' : '62%';
const descCols = innerWidth < 800 ? 1 : 2;

const STATUS_NAMES = ['status', 'result', 'disposition', 'state'];
const cols = computed(() => (E.value?.fields || []).filter((f: any) => f.list !== false && !['text', 'json'].includes(f.t)).slice(0, 12));
const enumFilters = computed(() => (E.value?.fields || []).filter((f: any) => f.t === 'enum').sort((a: any, b: any) => +STATUS_NAMES.includes(b.name) - +STATUS_NAMES.includes(a.name)).slice(0, 3));
const formFields = computed(() => (ent(formEntity.value)?.fields || []).filter((f: any) => !f.ro));
const detailTitle = computed(() => detail.value ? $t('common.n01', [E.value.label, labelOf(detail.value.item)]) : '');
const labelOf = (r: any) => r.code ? `${r.code}${r.name ? ' ' + r.name : ''}` : r.sn || r.name || r.title || r.username || '#' + r.id;
const isNum = (f: any) => f.t === 'int' || f.t === 'float';
const colWidth = (f: any) => (f.t === 'datetime' ? 150 : f.t === 'ref' ? 140 : f.name === 'code' || f.name === 'sn' ? 130 : f.t === 'enum' || f.t === 'bool' ? 90 : 110);
const childCols = (c: string) => {
  const fk = (E.value?.children || []).find((x: any) => x[0] === c)?.[1];
  return (ent(c)?.fields || []).filter((f: any) => f.list !== false && !['text', 'json'].includes(f.t) && f.name !== fk).slice(0, 10);
};

const Cell = defineComponent({
  props: { f: Object, row: Object, full: Boolean },
  setup(p: any) {
    return () => {
      const f = p.f, v = p.row[f.name];
      if (v === null || v === undefined || v === '') return h('span', { class: 'muted' }, '—');
      if (f.t === 'ref') return h('span', p.row[f.name + '__label'] || '#' + v);
      if (f.t === 'enum') return STATUS_NAMES.includes(f.name) || f.name === 'level' ? h('span', { class: 'tag-st st-' + v }, f.enum?.[v] || v) : h('span', f.enum?.[v] || v);
      if (f.t === 'bool') return h('span', { class: v ? 'ok' : 'muted' }, v ? '✓' : '—');
      if (f.t === 'float') return h('span', { class: 'mono' }, Math.abs(v) >= 100 ? (+v).toFixed(1) : (+v).toFixed(Math.abs(v) < 1 ? 4 : 2).replace(/0+$/, '').replace(/\.$/, ''));
      if (f.t === 'datetime') return h('span', { class: 'mono' }, p.full ? v : String(v).slice(5, 16));
      if (f.t === 'json') return h('pre', { style: 'margin:0;white-space:pre-wrap;font-size:12px' }, JSON.stringify(v, null, 1));
      if (f.t === 'text') return h('div', { class: 'md' }, String(v));
      return h('span', String(v));
    };
  },
});

async function load(p?: number) {
  if (p) page.value = p;
  loading.value = true;
  const qs = new URLSearchParams({ page: String(page.value), size: String(size.value), q: q.value, sort: sort.value });
  for (const [k, v] of Object.entries(filters)) if (v !== '' && v !== null && v !== undefined) qs.set('f_' + k, v);
  for (const [k, v] of Object.entries(route.query)) if (k.startsWith('f_') && !qs.has(k)) qs.set(k, String(v));
  try { const r = await get(`/api/e/${props.entity}?${qs}`); rows.value = r.items; total.value = r.total; } finally { loading.value = false; }
}
function onSort({ prop, order }: any) { sort.value = order ? (order === 'descending' ? '-' : '') + prop : ''; load(1); }
async function openDetail(row: any) {
  detail.value = await get(`/api/e/${props.entity}/${row.id}`); drawer.value = true;
}
function openForm(row?: any, entity?: string) {
  formEntity.value = entity || props.entity;
  for (const k of Object.keys(form)) delete form[k];
  const fe = ent(formEntity.value);
  if (row) Object.assign(form, row);
  else for (const f of fe.fields) if (f.default !== undefined) form[f.name] = f.default;
  formOpen.value = true;
}
function addChild(child: string) {
  const ch = E.value.children.find((c: any) => c[0] === child);
  openForm(undefined, child);
  form[ch[1]] = ch[2] ? detail.value.item[ch[2]] : detail.value.item.id;
  form[ch[1] + '__label'] = labelOf(detail.value.item);
}
async function save() {
  const e = formEntity.value;
  if (form.id) await put(`/api/e/${e}/${form.id}`, form); else await post(`/api/e/${e}`, form);
  ElMessage.success($t('common.saved')); formOpen.value = false; load();
  if (drawer.value && detail.value) detail.value = await get(`/api/e/${props.entity}/${detail.value.item.id}`);
}
async function remove(row: any) {
  await del(`/api/e/${props.entity}/${row.id}`); ElMessage.success($t('entityPage.deleted')); drawer.value = false; load();
}

// States in which an action is available (actions not in the table are always available)
const ACTION_WHEN: Record<string, (r: any) => boolean> = {
  'work_order.release': (r) => r.status === 'draft', 'work_order.cancel': (r) => ['draft', 'released'].includes(r.status),
  'work_order.close': (r) => ['in_progress', 'completed', 'released'].includes(r.status),
  'wo_op.dispatch': (r) => r.status !== 'done',
  'ncr.rework': (r) => r.status !== 'closed', 'ncr.scrap': (r) => r.status !== 'closed', 'ncr.concession': (r) => r.status !== 'closed', 'ncr.close': (r) => r.status !== 'closed',
  'repair_order.assign': (r) => r.status === 'reported', 'repair_order.start': (r) => ['reported', 'assigned'].includes(r.status),
  'repair_order.finish': (r) => r.status === 'repairing', 'repair_order.verify': (r) => r.status === 'done',
  'nc_program.approve': (r) => r.status === 'draft', 'nc_program.release': (r) => r.status === 'approved', 'nc_program.obsolete': (r) => r.status !== 'obsolete',
  'alarm.ack': (r) => !r.ack_by,
  'andon.respond': (r) => r.status === 'open', 'andon.close': (r) => r.status !== 'closed',
  'material_request.issue': (r) => r.status === 'submitted', 'material_request.reject': (r) => r.status === 'submitted',
};
function acts(entity: string, row: any) {
  const all = ent(entity)?.actions || {};
  return Object.fromEntries(Object.entries(all).filter(([a]) => (ACTION_WHEN[`${entity}.${a}`] || (() => true))(row)));
}
const ACTION_FORM: Record<string, any[]> = {
  'wo_op.dispatch': [{ name: 'assignee', label: $t('entityPage.assignTo'), t: 'ref', ref: 'employee' }],
  'repair_order.assign': [{ name: 'assignee', label: $t('entityPage.repairedBy'), t: 'ref', ref: 'employee' }],
  'repair_order.finish': [{ name: 'cause', label: $t('entityPage.failureCause'), t: 'text' }, { name: 'solution', label: $t('entityPage.fixApplied'), t: 'text' }],
  'ncr.rework': [{ name: 'remark', label: $t('entityPage.reworkInstructions') }], 'ncr.scrap': [{ name: 'remark', label: $t('entityPage.scrapNote') }], 'ncr.concession': [{ name: 'remark', label: $t('entityPage.concessionNote') }],
  'maint_plan.execute': [{ name: 'result', label: $t('entityPage.result'), t: 'enum', enum: { ok: $t('common.normal'), abnormal: $t('common.abnormal') } }, { name: 'notes', label: $t('common.description'), t: 'text' }],
  'alarm.ack': [{ name: 'note', label: $t('entityPage.resolutionNote') }],
  'datasource.import_vf': [{ name: 'url', label: $t('entityPage.apiUrl'), default: 'http://127.0.0.1:8800/api/p/foundry-housing' }, { name: 'token', label: $t('common.apiTokens') }],
  'andon.close': [{ name: 'note', label: $t('andon.resolution'), default: $t('andon.resolved') }], 'material_request.reject': [{ name: 'note', label: $t('entityPage.reasonForReturn') }],
  'tool.change': [{ name: 'reason', label: $t('common.reason'), t: 'enum', enum: { manual: $t('entityPage.manual'), life: $t('entityPage.endOfLife'), broken: $t('entityPage.toolBreakage') }, default: 'manual' }],
};
async function doAction(entity: string, row: any, name: string, label: any) {
  const fields = ACTION_FORM[`${entity}.${name}`];
  Object.assign(act, { entity, row, name, label: $t('common.n01', [label, labelOf(row)]), fields: fields || [], body: {}, busy: false });
  for (const f of fields || []) if (f.default) act.body[f.name] = f.default;
  if (fields) { actOpen.value = true; return; }
  await ElMessageBox.confirm($t('entityPage.confirm0', [label]), labelOf(row));
  await runAction();
}
async function runAction() {
  act.busy = true;
  try {
    const r = await post(`/api/e/${act.entity}/${act.row.id}/do/${act.name}`, act.body);
    ElMessage.success(r.msg || $t('entityPage.completed')); actOpen.value = false; load();
    if (detail.value) detail.value = await get(`/api/e/${props.entity}/${detail.value.item.id}`);
  } finally { act.busy = false; }
}
async function openValues() {
  const rec = detail.value.item;
  if (!rec.template) { ElMessage.warning($t('entityPage.thisInspectionHasNoTemplate')); return; }
  const t = await get(`/api/e/insp_template/${rec.template}`);
  const old = Object.fromEntries((detail.value.children.insp_value || []).map((v: any) => [v.item, v]));
  valItems.value = (t.children.insp_item || []).map((i: any) => ({ ...i, value: old[i.id]?.value ?? null, ok: old[i.id]?.ok ?? true }));
  valOpen.value = true;
}
async function saveValues() {
  const r = await post(`/api/quality/record/${detail.value.item.id}/values`, { values: valItems.value.map((i) => ({ item: i.id, value: i.value, ok: i.ok })) });
  ElMessage.success($t('entityPage.result2') + (r.record === 'OK' ? $t('common.good') : $t('view3DHover.ng'))); valOpen.value = false;
  detail.value = await get(`/api/e/insp_record/${detail.value.item.id}`); load();
}
function exportCsv() {
  const qs = new URLSearchParams({ q: q.value });
  for (const [k, v] of Object.entries(filters)) if (v) qs.set('f_' + k, v);
  openFile(`/api/e/${props.entity}.csv?${qs.toString()}`);
}
onMounted(() => {
  for (const [k, v] of Object.entries(route.query)) if (k.startsWith('f_') && enumFilters.value.some((f: any) => 'f_' + f.name === k)) filters[k.slice(2)] = v;
  load();
  if (route.query.id) openDetail({ id: route.query.id });
});
</script>

<style scoped>
.page-head .cnt { font-size: var(--hm-fs-xs); color: var(--hm-text-3); background: var(--hm-surface-2); border: 1px solid var(--hm-border); border-radius: var(--hm-r-pill); padding: 0 8px; line-height: 20px; }
.page-head .sub { flex-basis: 100%; margin-top: -6px; }
.tbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 10px 12px; margin-bottom: var(--hm-gap); }
.tbar .el-button + .el-button { margin-left: 0; }
.tcard { padding: 0; overflow: hidden; }
.pager { padding: 8px 12px; display: flex; justify-content: flex-end; border-top: 1px solid var(--hm-border); }
.acts { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; align-items: center; } .grow { flex: 1; }
.child-h { margin: 18px 0 6px; font-size: var(--hm-fs-md); color: var(--hm-text); } .child-h small { color: var(--hm-text-3); font-weight: 400; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 12px; } .form-grid .wide { grid-column: 1 / -1; }
@media (max-width: 700px) { .form-grid { grid-template-columns: 1fr; } }
</style>
