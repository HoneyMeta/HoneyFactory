<template>
  <div class="vp class-manager">
    <div class="vp-head">
      <span class="ttl">{{ $t('common.classesRosters') }}</span>
      <el-button size="small" type="primary" @click="newClass"><el-icon><Plus /></el-icon>{{ $t('classManager.newClass') }}</el-button>
      <el-button size="small" text @click="load"><el-icon><Refresh /></el-icon></el-button>
    </div>
    <div class="vp-body">
      <div class="vp-split">
        <div class="side">
          <div v-if="!classes.length" class="vp-empty">{{ $t('classManager.noClassesYetClickNew') }}</div>
          <div class="vp-list">
            <div v-for="c in classes" :key="c.id" class="vp-item" :class="{ on: cid === c.id }" @click="open(c.id)" :data-class="c.id">
              <div class="t">{{ c.name }}</div>
              <div class="vp-small vp-muted">{{ $t('classManager.n0Students1AssignmentsTeacher', [c.students, c.assignments, c.teacher]) }}</div>
            </div>
          </div>
        </div>
        <div class="main" v-if="cur">
          <div class="vp-row" style="margin-bottom: 8px">
            <b style="font-size: 15px">{{ cur.name }}</b><span class="vp-muted vp-small">{{ cur.descr }}</span>
            <span class="vp-grow" />
            <el-button size="small" text @click="rename">{{ $t('common.rename') }}</el-button>
            <el-button size="small" text type="danger" @click="remove">{{ $t('classManager.deleteClass') }}</el-button>
          </div>
          <el-tabs v-model="tab">
            <el-tab-pane :label="$t('classManager.students0', [cur.members.length])" name="members">
              <div class="vp-row" style="margin-bottom: 8px">
                <el-button size="small" type="primary" @click="openImport"><el-icon><Upload /></el-icon>{{ $t('classManager.importRoster') }}</el-button>
                <el-input v-model="one.username" size="small" :placeholder="$t('classManager.studentId')" style="width: 110px" />
                <el-input v-model="one.name" size="small" :placeholder="$t('common.name2')" style="width: 90px" />
                <el-button size="small" @click="addOne">{{ $t('classManager.add') }}</el-button>
                <span class="vp-grow" />
                <el-input v-model="kw" size="small" :placeholder="$t('opsApp.search')" clearable style="width: 120px" />
              </div>
              <div class="vp-row batch" v-if="cur.members.length">
                <el-checkbox :model-value="allSel" :indeterminate="sel.length > 0 && !allSel" @change="toggleAll">{{ $t('common.selectAll') }}</el-checkbox>
                <span class="vp-small vp-muted">{{ $t('classManager.selected0', [sel.length]) }}</span>
                <el-dropdown size="small" trigger="click" :disabled="!sel.length" @command="resetPw">
                  <el-button size="small" :disabled="!sel.length">{{ $t('org.resetPassword') }}<el-icon class="el-icon--right"><ArrowDown /></el-icon></el-button>
                  <template #dropdown><el-dropdown-menu>
                    <el-dropdown-item command="random">{{ $t('classManager.random6DigitPasswordFor') }}</el-dropdown-item>
                    <el-dropdown-item command="same">{{ $t('classManager.resetAllTo123456') }}</el-dropdown-item>
                  </el-dropdown-menu></template>
                </el-dropdown>
                <el-button size="small" :disabled="!sel.length" @click="printSlips(members.filter((m: any) => sel.includes(m.username)).map((m: any) => ({ ...m, password: $t('classManager.currentPassword') })))">{{ $t('classManager.printLoginSlips') }}</el-button>
                <el-button size="small" type="danger" plain :disabled="!sel.length" @click="dropMany">{{ $t('classManager.removeFromClass') }}</el-button>
              </div>
              <table class="vp-tbl members">
                <tr><th style="width: 28px"></th><th>{{ $t('classManager.studentId') }}</th><th>{{ $t('common.name2') }}</th><th>{{ $t('common.lastLogin') }}</th></tr>
                <tr v-for="m in members" :key="m.username" :class="{ hi: sel.includes(m.username) }">
                  <td><el-checkbox :model-value="sel.includes(m.username)" @change="(v: any) => toggle(m.username, v)" /></td>
                  <td class="mono">{{ m.username }}</td><td>{{ m.name }}</td><td class="vp-muted">{{ m.last_login || $t('classManager.neverLoggedIn') }}</td>
                </tr>
              </table>
              <div v-if="!cur.members.length" class="vp-empty">{{ $t('classManager.noStudentsYetClickImport') }}</div>
            </el-tab-pane>
            <el-tab-pane :label="$t('classManager.gradebook')" name="grades">
              <div class="vp-row" style="margin-bottom: 8px">
                <el-button size="small" @click="exportGrades('xlsx')"><el-icon><Download /></el-icon>{{ $t('classManager.exportToExcelIncludesGrading') }}</el-button>
                <el-button size="small" @click="exportGrades('csv')"><el-icon><Download /></el-icon>{{ $t('tables.exportCsv') }}</el-button>
                <span class="vp-small vp-muted">{{ $t('classManager.usesTheHighestScoreFor') }}</span>
              </div>
              <div class="gb-wrap">
                <table class="vp-tbl gb" v-if="grades">
                  <tr><th v-for="(h, i) in grades.head" :key="i" :class="{ num: i >= 2 }">{{ h }}</th></tr>
                  <tr v-for="r in grades.rows" :key="r[0]">
                    <td v-for="(v, i) in r" :key="i" :class="{ num: i >= 2, mono: i === 0, link: i >= 2 && i < r.length - 1 }"
                        @click="i >= 2 && i < r.length - 1 && review(grades.assignments[i - 2].id, r[0])">{{ v ?? '—' }}</td>
                  </tr>
                </table>
              </div>
            </el-tab-pane>
          </el-tabs>
        </div>
        <div class="main" v-else><div class="vp-empty">{{ $t('classManager.selectAClassOnThe') }}</div></div>
      </div>
    </div>

    <el-dialog v-model="importOpen" :title="$t('classManager.importStudentRoster')" width="720px" append-to-body destroy-on-close class="fit-dialog">
      <div class="vp-small vp-muted" style="margin-bottom: 8px">
        {{ $t('classManager.oneStudentPerLine') }}<b>{{ $t('classManager.studentIdNameInitialPassword') }}</b>{{ $t('classManager.copyAndPasteTwoOr') }}
      </div>
      <div class="vp-row" style="margin-bottom: 6px">
        <input ref="fileEl" type="file" accept=".csv,.txt,.xlsx" style="display: none" @change="readFile" />
        <el-button size="small" @click="fileEl?.click()"><el-icon><Upload /></el-icon>{{ $t('classManager.chooseFileXlsxCsv') }}</el-button>
        <el-button size="small" text @click="template"><el-icon><Download /></el-icon>{{ $t('classManager.downloadRosterTemplateXlsx') }}</el-button>
        <span class="vp-small vp-muted">{{ fileName }}</span>
      </div>
      <el-input v-if="!xlsx" v-model="csv" type="textarea" :rows="6" :placeholder="$t('classManager.studentIdNameS2026001Zhang')" @input="schedulePreview" />
      <div class="vp-row" style="margin-top: 8px"><span class="vp-small">{{ $t('classManager.defaultPassword') }}</span><el-input v-model="defPw" size="small" style="width: 120px" />
        <span class="vp-grow" /><el-button size="small" :disabled="!csv.trim() && !xlsx" @click="doPreview">{{ $t('classManager.preview') }}</el-button></div>
      <div v-if="preview" class="prev">
        <div class="vp-small" style="margin: 6px 0">
          {{ $t('classManager.n0RowsTotal1New', [preview.rows.length, preview.counts.new || 0, preview.counts.exists || 0, preview.counts.in_class || 0]) }}
          <span :class="{ 'vp-fail': preview.counts.error }">{{ $t('classManager.n0WithIssues', [preview.counts.error || 0]) }}</span>{{ $t('classManager.rowsWithIssuesWillNot') }}
        </div>
        <div class="prev-wrap"><table class="vp-tbl">
          <tr><th>{{ $t('classManager.row') }}</th><th>{{ $t('classManager.studentId') }}</th><th>{{ $t('common.name2') }}</th><th>{{ $t('classManager.status') }}</th></tr>
          <tr v-for="r in preview.rows" :key="r.line" :class="'st-' + r.status"><td class="num">{{ r.line }}</td><td class="mono">{{ r.username }}</td><td>{{ r.name }}</td>
            <td>{{ ST_CN[r.status] }}<span v-if="r.msg && r.status !== 'new'" class="vp-small"> · {{ r.msg }}</span></td></tr>
        </table></div>
      </div>
      <div v-if="importRes" class="vp-card vp-small" style="margin-top: 8px">
        {{ $t('classManager.accountsCreated0AddedTo', [importRes.created, importRes.added, importRes.already]) }}
        <div v-for="e in importRes.errors.slice(0, 10)" :key="e" class="vp-fail">{{ e }}</div>
        <el-button v-if="importRes.accounts?.length" size="small" style="margin-top: 6px" @click="printSlips(importRes.accounts)">{{ $t('classManager.printNewLoginSlips0', [importRes.accounts.length]) }}</el-button>
      </div>
      <template #footer>
        <el-button size="small" @click="importOpen = false">{{ $t('common.close') }}</el-button>
        <el-button size="small" type="primary" :loading="importing" :disabled="!preview || !(preview.rows.length - (preview.counts.error || 0))" @click="doImport">
          {{ $t('classManager.import0', [preview ? $t('classManager.n0Students', [preview.rows.length - (preview.counts.error || 0)]) : '']) }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { del, get, patch, post } from '../../api';
import { classesChanged, openReview, saveFile, teachBus } from './util';
import './panel.css';

defineProps<{ pid?: string }>();
const ST_CN: Record<string, string> = { new: $t('classManager.createAccount'), exists: $t('classManager.addToThisClass'), in_class: $t('classManager.alreadyInClassSkip'), error: $t('classManager.hasIssues') };
const classes = ref<any[]>([]);
const cid = ref<number | null>(null);
const cur = ref<any>(null);
const tab = ref('members');
const kw = ref('');
const sel = ref<string[]>([]);
const one = reactive({ username: '', name: '' });
const importOpen = ref(false);
const csv = ref('');
const xlsx = ref('');
const defPw = ref('123456');
const fileEl = ref<HTMLInputElement | null>(null);
const fileName = ref('');
const importing = ref(false);
const importRes = ref<any>(null);
const preview = ref<any>(null);
const grades = ref<any>(null);
const members = computed(() => (cur.value?.members || []).filter((m: any) => !kw.value || m.username.includes(kw.value) || (m.name || '').includes(kw.value)));
const allSel = computed(() => members.value.length > 0 && members.value.every((m: any) => sel.value.includes(m.username)));

async function load() {
  classes.value = await get('/api/teach/classes');
  if (!cid.value && classes.value.length) open(classes.value[0].id);
}
async function open(id: number) {
  cid.value = id;
  sel.value = [];
  cur.value = await get(`/api/teach/classes/${id}`);
  if (tab.value === 'grades') loadGrades();
}
async function loadGrades() { if (cid.value) grades.value = await get(`/api/teach/classes/${cid.value}/gradebook`); }
watch(tab, (t) => { if (t === 'grades') loadGrades(); });
watch(() => teachBus.classes, load);

function toggle(u: string, v: any) { sel.value = v ? [...new Set([...sel.value, u])] : sel.value.filter((x) => x !== u); }
function toggleAll(v: any) { sel.value = v ? members.value.map((m: any) => m.username) : []; }

async function newClass() {
  const { value } = await ElMessageBox.prompt($t('classManager.className'), $t('classManager.newClass'), { inputPlaceholder: $t('classManager.eGElectricalAutomationClass'), inputValidator: (v) => !!v?.trim() || $t('classManager.cannotBeEmpty') });
  const r = await post('/api/teach/classes', { name: value.trim() });
  classesChanged();                          // Also refresh class dropdowns in assignment/course publishing.
  await load();
  open(r.id);
}
async function rename() {
  const { value } = await ElMessageBox.prompt($t('classManager.className'), $t('common.rename'), { inputValue: cur.value.name });
  await patch(`/api/teach/classes/${cid.value}`, { name: value });
  classesChanged();
  await load(); open(cid.value!);
}
async function remove() {
  await ElMessageBox.confirm($t('classManager.deleteClass0AllAssignments', [cur.value.name]), $t('classManager.deleteClass'), { type: 'warning' });
  await del(`/api/teach/classes/${cid.value}`);
  cid.value = null; cur.value = null;
  classesChanged();
  load();
}
async function addOne() {
  if (!one.username.trim()) return;
  await post(`/api/teach/classes/${cid.value}/members`, { username: one.username.trim(), name: one.name.trim() });
  one.username = ''; one.name = '';
  ElMessage.success($t('classManager.addedNewAccountsUseThe'));
  open(cid.value!); load();
}
async function dropMany() {
  await ElMessageBox.confirm($t('classManager.removeTheSelected0Students', [sel.value.length]), $t('classManager.remove'), { type: 'warning' });
  await post(`/api/teach/classes/${cid.value}/members/remove`, { usernames: sel.value });
  open(cid.value!); load();
}
async function resetPw(cmd: string) {
  await ElMessageBox.confirm(cmd === 'random' ? $t('classManager.generateARandom6Digit', [sel.value.length]) : $t('classManager.resetThePasswordsForThe', [sel.value.length]), $t('org.resetPassword'), { type: 'warning' });
  const r = await post(`/api/teach/classes/${cid.value}/members/reset_password`, { usernames: sel.value, random: cmd === 'random' });
  ElMessage.success($t('classManager.passwordsResetFor0Students', [r.accounts.length]));
  if (cmd === 'random') printSlips(r.accounts);
}
/** Print account slips: multiple per page, cut out and distribute to students. */
function printSlips(accounts: any[]) {
  const w = window.open('', '_blank');
  if (!w) { ElMessage.warning($t('classManager.yourBrowserBlockedThePop')); return; }
  const esc = (s: string) => String(s ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c] as string));
  const site = location.origin;
  w.document.write(`<!doctype html><html><head><meta charset="utf-8"><title>${$t('classManager.loginSlips')} ${esc(cur.value?.name || '')}</title><style>
    body{font-family:"Microsoft YaHei",sans-serif;margin:12mm} .g{display:grid;grid-template-columns:1fr 1fr;gap:6mm}
    .s{border:1px dashed #888;padding:4mm 5mm;font-size:13px;line-height:1.8} .s b{font-size:15px} .u{font-family:Consolas,monospace;font-size:15px}
    @media print{button{display:none}}</style></head><body><button onclick="print()">${$t('classManager.print')}</button>
    <h3>${esc(cur.value?.name || '')} ${$t('classManager.loginSlips2')}</h3><div class="g">${accounts.map((a) => `<div class="s"><b>${esc(a.name)}</b><br>${$t('classManager.url')}${esc(site)}<br>
    ${$t('classManager.account')}<span class="u">${esc(a.username)}</span><br>${$t('classManager.password')}<span class="u">${esc(a.password)}</span><br><small>${$t('classManager.changeYourPasswordAfterYour')}</small></div>`).join('')}</div></body></html>`);
  w.document.close();
}
function openImport() { csv.value = ''; xlsx.value = ''; fileName.value = ''; preview.value = null; importRes.value = null; importOpen.value = true; }
function readFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (!f) return;
  fileName.value = f.name;
  preview.value = null;
  const rd = new FileReader();
  if (/\.xlsx$/i.test(f.name)) {
    rd.onload = () => { xlsx.value = String(rd.result); csv.value = ''; doPreview(); };
    rd.readAsDataURL(f);
    return;
  }
  rd.onload = () => {
    const buf = rd.result as ArrayBuffer;
    let text = new TextDecoder('utf-8').decode(buf);
    if (text.includes('�')) text = new TextDecoder('gbk').decode(buf);     // CSV files saved from Excel often use GBK.
    csv.value = text; xlsx.value = '';
    doPreview();
  };
  rd.readAsArrayBuffer(f);
}
const body = () => (xlsx.value ? { xlsx: xlsx.value } : { csv: csv.value });
// Auto-preview after pasting (after half a second of inactivity), so teachers need not click "Preview".
let pvTimer: any = null;
function schedulePreview() {
  preview.value = null;
  clearTimeout(pvTimer);
  pvTimer = setTimeout(() => { if (csv.value.trim()) doPreview(); }, 500);
}
async function doPreview() { preview.value = await post(`/api/teach/classes/${cid.value}/roster`, { ...body(), default_password: defPw.value, preview: true }); }
async function doImport() {
  importing.value = true;
  try {
    importRes.value = await post(`/api/teach/classes/${cid.value}/roster`, { ...body(), default_password: defPw.value });
    ElMessage.success($t('classManager.importComplete0StudentsAdded', [importRes.value.added]));
    preview.value = null;
    open(cid.value!); load(); classesChanged();
  } finally { importing.value = false; }
}
function template() { saveFile('/api/teach/roster_template.xlsx', $t('classManager.studentRosterTemplateXlsx')); }
function exportGrades(fmt: string) { saveFile(`/api/teach/classes/${cid.value}/gradebook.${fmt}`, $t('classManager.gradebook01', [cur.value.name, fmt])); }
function review(aid: number, username: string) { openReview(aid, username); }

onMounted(load);
</script>

<style scoped>
.gb-wrap { overflow: auto; max-height: 60vh; }
.gb th.num, .gb td.num { text-align: center; }
.gb td.link { cursor: pointer; color: var(--el-color-primary); }
.gb td.link:hover { text-decoration: underline; }
.batch { margin-bottom: 6px; padding: 4px 6px; background: var(--el-fill-color-light); border-radius: 4px; }
.members { margin-bottom: 64px; }
.prev-wrap { max-height: 240px; overflow: auto; }
.st-error td { background: var(--el-color-danger-light-9); color: var(--bad, var(--el-color-danger)); }
.st-in_class td { color: var(--el-text-color-placeholder); }
</style>
