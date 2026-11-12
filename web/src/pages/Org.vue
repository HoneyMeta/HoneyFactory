<template>
  <!-- Organization management (5.0): org admins manage their teachers, students, seats, usage, and data; self-hosted deployments also import license files here -->
  <div class="page org-page" data-k="org-page">
    <div class="page-head"><h2>{{ $t('common.organizationManagement') }}</h2><span class="sub">{{ info?.org?.name }}<template v-if="info?.org?.id">{{ $t('common.n0', [info.org.id]) }}</template></span><span class="grow" />
      <el-tag v-if="info?.mode === 'saas'" type="info">{{ $t('login.honeyCloud') }}</el-tag><el-tag v-else type="info">{{ $t('org.selfHosted') }}</el-tag></div>

    <div v-if="info" class="cards">
      <div class="kpi stat" data-k="org-seat-teachers"><small>{{ $t('opsApp.teacherSeats') }}</small><b>{{ L.used.teachers }} / {{ L.teachers ?? $t('common.unrestricted') }}</b>
        <el-progress v-if="L.teachers" :percentage="pct(L.used.teachers, L.teachers)" :status="L.left.teachers === 0 ? 'exception' : undefined" :show-text="false" /></div>
      <div class="kpi stat" data-k="org-seat-students"><small>{{ $t('opsApp.studentSeats') }}</small><b>{{ L.used.students }} / {{ L.students ?? $t('common.unrestricted') }}</b>
        <el-progress v-if="L.students" :percentage="pct(L.used.students, L.students)" :status="L.left.students === 0 ? 'exception' : undefined" :show-text="false" />
        <span class="muted">{{ $t('org.archived0NoSeatsUsed', [L.used.archived]) }}</span></div>
      <div class="kpi stat"><small>{{ L.source === 'licence' ? $t('org.licenseExpiry') : L.source === 'console' ? $t('org.serviceExpiry') : $t('org.license') }}</small>
        <b :class="{ bad: L.expired }">{{ L.source === 'unlicensed' ? $t('org.notActivated') : (L.expires || $t('org.perpetual')) }}</b><span v-if="L.expired" class="bad">{{ $t('org.expiredNewAccountsCannotBe') }}</span></div>
      <div class="kpi stat"><small>{{ $t('org.aiUsageThisMonth') }}</small><b>{{ fmtN(info.usage.ai_tokens_month) }}</b><span class="muted">{{ $t('org.quota0', [L.ai_quota == null ? $t('common.unrestricted') : fmtN(L.ai_quota) + ' tokens']) }}</span></div>
      <div class="kpi stat"><small>{{ $t('org.activeIn30DaysSubmissions') }}</small><b>{{ info.usage.active_30d }} / {{ info.usage.submissions_month }}</b><span class="muted">{{ $t('org.classes0', [info.usage.classes]) }}</span></div>
    </div>
    <el-alert v-if="info && L.source === 'unlicensed' && info.mode !== 'saas'" type="warning" :closable="false" show-icon style="margin-bottom:10px"
              :title="$t('org.noLicenseFileImportedSeats')" />

    <el-tabs v-model="tab" class="org-tabs" @tab-change="loadUsers">
      <el-tab-pane :label="$t('opsApp.teacher')" name="teacher">
        <div class="tools"><el-button type="primary" data-k="org-new-teacher" @click="run(newTeacher, $event)">{{ $t('org.createTeacher') }}</el-button>
          <span class="muted">{{ $t('org.teachersUseTeacherSeatsLeave') }}</span></div>
        <el-table :data="users" size="small" data-k="org-teachers">
          <el-table-column prop="username" :label="$t('common.username')" /><el-table-column prop="name" :label="$t('common.name2')" />
          <el-table-column :label="$t('common.status')" width="110"><template #default="{ row }">{{ row.archived ? $t('opsApp.archived') : row.active ? (row.locked ? $t('opsApp.locked') : $t('common.normal')) : $t('common.disabled2') }}</template></el-table-column>
          <el-table-column prop="last_login" :label="$t('common.lastLogin')" width="160" />
          <el-table-column width="230"><template #default="{ row }">
            <el-button link type="primary" @click="run(resetPw, row)">{{ $t('org.resetPassword') }}</el-button>
            <el-button v-if="row.active" link type="warning" @click="run(setActive, row, false)">{{ $t('common.disabled') }}</el-button>
            <el-button v-else link type="success" @click="run(setActive, row, true)">{{ $t('common.enable') }}</el-button>
          </template></el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="$t('common.student')" name="student">
        <div class="tools">
          <el-button type="primary" data-k="org-import" @click="openImport">{{ $t('org.bulkImportStudents') }}</el-button>
          <el-button :disabled="!sel.length" data-k="org-archive" @click="run(archive, $event)">{{ $t('org.archiveSelected0', [sel.length]) }}</el-button>
          <el-button :disabled="!sel.length" @click="run(restore, $event)">{{ $t('org.restoreSelected') }}</el-button>
          <el-select v-model="archClass" :placeholder="$t('org.archiveByClassEndOf')" clearable style="width:220px" @change="run(archiveClass, $event)">
            <el-option v-for="c in classes" :key="c.id" :label="$t('common.n01Members', [c.name, c.students])" :value="c.id" /></el-select>
          <span class="grow" /><el-radio-group v-model="showArch" size="small" @change="loadUsers"><el-radio-button :value="0">{{ $t('org.active') }}</el-radio-button><el-radio-button :value="1">{{ $t('opsApp.archived') }}</el-radio-button></el-radio-group>
        </div>
        <el-table :data="users" size="small" data-k="org-students" @selection-change="(v: any[]) => sel = v">
          <el-table-column type="selection" width="40" />
          <el-table-column prop="username" :label="$t('common.username')" /><el-table-column prop="name" :label="$t('common.name2')" />
          <el-table-column :label="$t('common.status')" width="100"><template #default="{ row }">{{ row.archived ? $t('opsApp.archived') : row.active ? (row.locked ? $t('opsApp.locked') : $t('common.normal')) : $t('common.disabled2') }}</template></el-table-column>
          <el-table-column prop="last_login" :label="$t('common.lastLogin')" width="160" />
          <el-table-column width="110"><template #default="{ row }"><el-button link type="primary" @click="run(resetPw, row)">{{ $t('org.resetPassword') }}</el-button></template></el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane :label="$t('org.data')" name="data">
        <div class="card">
          <h3>{{ $t('org.exportAllOrganizationData') }}</h3>
          <p class="muted">{{ $t('org.exportAccountsExcludingPasswordsClas') }}</p>
          <el-button data-k="org-export" @click="run(exportData, $event)">{{ $t('org.exportPasswordRequired') }}</el-button>
        </div>
        <div class="card danger">
          <h3>{{ $t('org.deleteAllOrganizationData') }}</h3>
          <p class="muted">{{ $t('org.deleteClassesAssignmentsSubmissionsA', [info?.mode === 'saas' ? $t('org.includingYourOwnAccount') : $t('org.keepYourOwnAdminAccount')]) }}</p>
          <el-button type="danger" plain @click="run(deleteData, $event)">{{ $t('org.delete') }}</el-button>
        </div>
      </el-tab-pane>

      <el-tab-pane v-if="info?.mode !== 'saas'" :label="$t('org.licenseFile')" name="license">
        <div class="card" data-k="org-license">
          <h3>{{ $t('org.license') }}</h3>
          <template v-if="info?.license?.ok">
            <p>{{ $t('org.licensedOrganization') }}<b>{{ info.license.payload.org_name }}</b>&emsp;{{ $t('org.licenseId0', [info.license.payload.license_id]) }}</p>
            <p>{{ $t('org.seatsTeachers0Students1', [info.license.payload.seats?.teachers, info.license.payload.seats?.students, info.license.payload.starts, info.license.payload.expires]) }}
              <el-tag v-if="info.license.expired" type="danger" size="small">{{ $t('org.expired') }}</el-tag><span v-else class="muted">{{ $t('org.n0DaysRemaining', [info.license.days_left]) }}</span></p>
            <p>{{ $t('org.featurePackage0', [featText(info.license.payload.features)]) }}</p>
          </template>
          <p v-else-if="info?.license?.installed" class="bad">{{ $t('org.invalidLicenseFile0', [info.license.error]) }}</p>
          <p v-else class="muted">{{ $t('org.noLicenseFileHasBeen') }}</p>
          <input ref="licFile" type="file" accept=".vflic,.json,.txt" style="display:none" @change="run(uploadLicense, $event)" />
          <el-button type="primary" data-k="org-license-upload" @click="($refs.licFile as any).click()">{{ $t('org.importLicenseFileVflic') }}</el-button>
          <p class="muted">{{ $t('org.licenseFilesAreIssuedBy') }}</p>
        </div>
      </el-tab-pane>
    </el-tabs>

    <el-dialog v-model="impOpen" :title="$t('org.bulkImportStudents')" width="min(720px, 96vw)">
      <p class="muted">{{ $t('org.oneStudentPerLineStudent') }}</p>
      <el-input v-model="imp.csv" type="textarea" :rows="8" :placeholder="$t('org.s2026001ZhangSanS2026002Li')" data-k="org-import-csv" />
      <div class="tools" style="margin-top:8px">
        <el-select v-model="imp.class_id" :placeholder="$t('org.alsoAddToClassOptional')" clearable style="width:220px">
          <el-option v-for="c in classes" :key="c.id" :label="c.name" :value="c.id" /></el-select>
        <el-checkbox v-model="imp.prefix">{{ $t('org.prefixAccountsWithTheOrganization', [info?.org?.id]) }}</el-checkbox>
      </div>
      <div v-if="preview" class="prev" data-k="org-import-preview">
        {{ $t('org.newAccounts0StudentSeats', [preview.new, preview.limits.left.students ?? $t('common.unrestricted')]) }}
        <b v-if="!preview.seat_ok" class="bad">{{ $t('org.notEnoughSeats0New', [preview.new, preview.limits.left.students]) }}</b>
        <div v-for="r in preview.rows.filter((x: any) => x.status === 'error')" :key="r.line" class="bad">{{ $t('org.line012', [r.line, r.username, r.msg]) }}</div>
      </div>
      <template #footer>
        <el-button data-k="org-import-preview-btn" @click="run(doImport, true)">{{ $t('common.check') }}</el-button>
        <el-button type="primary" data-k="org-import-go" @click="run(doImport, false)">{{ $t('common.import') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="accOpen" :title="$t('org.newAccountsAndTemporaryPasswords')" width="min(560px, 96vw)">
      <el-table :data="accounts" size="small" max-height="360" data-k="org-accounts"><el-table-column prop="username" :label="$t('common.username')" /><el-table-column prop="name" :label="$t('common.name2')" />
        <el-table-column prop="password" :label="$t('org.temporaryPassword')" /></el-table>
      <template #footer><el-button @click="downloadAccounts">{{ $t('org.downloadAccountSlipsCsv') }}</el-button><el-button type="primary" @click="accOpen = false">{{ $t('common.close') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
/** Button action: api already shows errors (including cancellation); do not rethrow as a page script error. */
const run = (fn: (...a: any[]) => any, ...a: any[]) => Promise.resolve().then(() => fn(...a)).catch(() => null);
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, reactive, ref } from 'vue';
import { get, post, session } from '../api';

const info = ref<any>(null), tab = ref('teacher'), users = ref<any[]>([]), sel = ref<any[]>([]), classes = ref<any[]>([]);
const showArch = ref(0), archClass = ref<any>(null);
const L = computed(() => info.value?.limits || { used: {}, left: {} });
const pct = (a: number, b: number) => Math.min(100, Math.round((a / Math.max(1, b)) * 100));
const fmtN = (n: any) => (n == null ? '—' : Number(n).toLocaleString());
const featText = (f: any) => [f?.plc && $t('common.plcLab'), f?.ai && 'AI', f?.client && $t('common.desktopClient'), f?.courses === 'all' ? $t('org.allCourses') : $t('org.courses0', [(f?.courses || []).join($t('common.k360'))])].filter(Boolean).join($t('common.k360'));

async function load() { info.value = await get('/api/org'); }
async function loadUsers() {
  if (tab.value !== 'teacher' && tab.value !== 'student') return;
  users.value = (await get(`/api/org/users?role=${tab.value}&archived=${tab.value === 'student' ? showArch.value : -1}`)).users;
  sel.value = [];
}
async function loadClasses() { try { classes.value = await get('/api/teach/classes', true); } catch { classes.value = []; } }
const refresh = async () => { await load(); await loadUsers(); };

const accounts = ref<any[]>([]), accOpen = ref(false);
function showAccounts(a: any[]) { accounts.value = a; accOpen.value = a.length > 0; }
async function newTeacher() {
  const { value } = await ElMessageBox.prompt($t('org.teacherUsernameAndNameSeparated'), $t('org.createTeacher'), { inputPlaceholder: $t('org.n0WangTeacherWang', [info.value?.org?.id || '']) });
  const [username, name] = String(value || '').split(/[,\uff0c]/).map((x) => x.trim());
  const r = await post('/api/org/teachers', { username, name });
  showAccounts([{ username: r.username, name: name || r.username, password: r.password }]); refresh();
}
async function resetPw(row: any) {
  await ElMessageBox.confirm($t('org.resetThePasswordFor0', [row.name, row.username]), $t('org.resetPassword'));
  const r = await post(`/api/org/users/${encodeURIComponent(row.username)}/reset_password`, {});
  showAccounts([{ username: r.username, name: row.name, password: r.password }]);
}
async function setActive(row: any, on: boolean) { await post(`/api/org/users/${encodeURIComponent(row.username)}/active`, { active: on }); refresh(); }
async function archive() {
  await ElMessageBox.confirm($t('org.archiveThe0SelectedAccounts', [sel.value.length]), $t('org.archive'));
  const r = await post('/api/org/users/archive', { usernames: sel.value.map((x) => x.username) }); ElMessage.success($t('org.accountsArchived0', [r.archived])); refresh();
}
async function archiveClass(cid: any) {
  if (!cid) return;
  const c = classes.value.find((x) => x.id === cid);
  try {
    await ElMessageBox.confirm($t('org.endOfSemesterArchiveAll', [c?.name]), $t('org.archiveByClass'));
    const r = await post('/api/org/users/archive', { class_id: cid }); ElMessage.success($t('org.accountsArchived0', [r.archived])); refresh();
  } finally { archClass.value = null; }
}
async function restore() { const r = await post('/api/org/users/restore', { usernames: sel.value.map((x) => x.username) }); ElMessage.success($t('org.accountsRestored0', [r.restored])); refresh(); }

const impOpen = ref(false), imp = reactive<any>({ csv: '', class_id: null, prefix: false }), preview = ref<any>(null);
function openImport() { Object.assign(imp, { csv: '', class_id: null, prefix: info.value?.mode === 'saas' }); preview.value = null; impOpen.value = true; loadClasses(); }
async function doImport(pre: boolean) {
  const r = await post('/api/org/students/import', { ...imp, preview: pre });
  if (pre) { preview.value = r; return; }
  impOpen.value = false;
  ElMessage.success($t('org.accountsCreated0AddedTo', [r.created, r.added]) + (r.errors.length ? $t('org.rowsWithIssues0', [r.errors.length]) : ''));
  if (r.errors.length) ElMessageBox.alert(r.errors.join('\n'), $t('org.theseRowsWereNotImported'));
  showAccounts(r.accounts); refresh();
}
function downloadAccounts() {
  const csv = $t('org.accountNameTemporaryPassword') + accounts.value.map((a) => `${a.username},${a.name},${a.password}`).join('\n');
  const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' })); a.download = 'accounts.csv'; a.click();
}
async function exportData() {
  const { value } = await ElMessageBox.prompt($t('org.enterYourOwnLoginPassword'), $t('org.exportOrganizationData'), { inputType: 'password' });
  const r = await fetch('/api/org/export', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + session.token }, body: JSON.stringify({ password: value }) });
  if (!r.ok) { ElMessage.error((await r.json().catch(() => ({}))).detail || $t('org.exportFailed')); return; }
  const a = document.createElement('a'); a.href = URL.createObjectURL(await r.blob()); a.download = `org-${info.value.org.id}.zip`; a.click();
}
async function deleteData() {
  const { value: name } = await ElMessageBox.prompt($t('org.thisWillPermanentlyDeleteAll', [info.value.org.name]), $t('org.deleteOrganizationData'), { confirmButtonType: 'danger' } as any);
  const { value: pw } = await ElMessageBox.prompt($t('org.enterYourOwnLoginPassword2'), $t('org.deleteOrganizationData'), { inputType: 'password', confirmButtonType: 'danger' } as any);
  const r = await post('/api/org/delete', { confirm: name, password: pw });
  ElMessage.success($t('org.deleted') + Object.entries(r.deleted).map(([k, v]) => `${k} ${v}`).join($t('common.k521')));
  if (info.value.mode === 'saas') { session.token = ''; localStorage.removeItem('vf_token'); location.href = '/login'; } else refresh();
}
async function uploadLicense(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (!f) return;
  const text = await f.text();
  (e.target as HTMLInputElement).value = '';
  await post('/api/org/license', { data: text }); ElMessage.success($t('org.licenseFileImported')); load();
}
onMounted(async () => { await refresh(); loadClasses(); });
</script>

<style scoped>
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(calc(200px * var(--hm-scale)), 1fr)); gap: var(--hm-gap); margin-bottom: var(--hm-gap); }
.org-tabs { background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); box-shadow: var(--hm-e1); padding: 4px 16px 14px; }
.stat { display: flex; flex-direction: column; gap: 4px; } .stat b { font-size: var(--hm-fs-xl); font-family: var(--hm-font-num); font-variant-numeric: tabular-nums; font-weight: 600; }
.tools { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; flex-wrap: wrap; } .grow { flex: 1; }
.muted { color: var(--hm-text-3); font-size: 12px; } .bad { color: var(--hm-fault-ink); }
.card.danger { border: 1px solid rgba(220, 43, 43, .35); box-shadow: inset 3px 0 0 var(--hm-fault), var(--hm-e1); } .prev { margin-top: 10px; font-size: 13px; line-height: 1.8; }
</style>
