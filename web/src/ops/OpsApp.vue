<template>
  <!-- Platform operations console (5.0, SaaS): separate from organization accounts; cookie sessions + TOTP; sensitive actions require another verification code. No organization impersonation. -->
  <div class="ops hm-grid-bg">
    <header class="bar">
      <img :src="markUrl()" alt="" />
      <div class="brand"><b>{{ $t('opsApp.honeyfactoryPlatformOperations') }}</b><small>{{ $t('opsApp.saasOperationsConsole') }}</small></div>
      <span class="grow" />
      <LangSwitch compact />
      <template v-if="me">
        <span class="who" data-k="ops-who">{{ $t('common.n012', [me.admin.name, me.admin.username]) }}</span>
        <span class="muted">{{ $t('opsApp.automaticallySignsOutAfter0', [me.idle_min]) }}</span>
        <el-button size="small" @click="run(logout, $event)" data-k="ops-logout">{{ $t('common.exit') }}</el-button>
      </template>
    </header>

    <!-- Login: username/password → set up TOTP (first time) / enter verification or recovery code -->
    <div v-if="!me" class="center">
      <div class="box" v-if="step === 'pw'">
        <h2>{{ $t('opsApp.operationsSignIn') }}</h2>
        <p class="muted">{{ $t('opsApp.forHoneyOperationsStaffOnly') }}</p>
        <el-form label-position="top" @submit.prevent="run(login, $event)">
          <el-form-item :label="$t('opsApp.operationsAccount')"><el-input v-model="lf.username" data-k="ops-user" autofocus /></el-form-item>
          <el-form-item :label="$t('common.password')"><el-input v-model="lf.password" type="password" show-password data-k="ops-pw" @keyup.enter="run(login, $event)" /></el-form-item>
          <el-button type="primary" style="width:100%" :loading="busy" data-k="ops-login" @click="run(login, $event)">{{ $t('common.next') }}</el-button>
        </el-form>
      </div>
      <div class="box wide" v-else-if="step === 'enroll'">
        <h2>{{ $t('opsApp.firstSignInSetUp') }}</h2>
        <ol class="steps">
          <li>{{ $t('opsApp.openAnAuthenticatorAppOn') }}</li>
          <li>{{ $t('opsApp.ifYouCannotScanIt') }}<code data-k="ops-secret">{{ pending.secret }}</code>{{ $t('common.k344') }}</li>
          <li>{{ $t('opsApp.enterThe6DigitCode') }}</li>
        </ol>
        <div class="qr" data-k="ops-qr" v-html="qrSvg" />
        <el-input v-model="code" maxlength="6" :placeholder="$t('opsApp.n6DigitVerificationCode')" data-k="ops-code" @keyup.enter="run(enroll, $event)" style="max-width:200px" />
        <el-button type="primary" :loading="busy" data-k="ops-enroll" @click="run(enroll, $event)" style="margin-left:8px">{{ $t('opsApp.setUpSignIn') }}</el-button>
      </div>
      <div class="box" v-else-if="step === 'totp'">
        <h2>{{ $t('opsApp.enterOneTimeCode') }}</h2>
        <el-form label-position="top" @submit.prevent="run(verify, $event)">
          <el-form-item v-if="!useRecovery" :label="$t('opsApp.n6DigitCodeFromYour')"><el-input v-model="code" maxlength="6" data-k="ops-code" autofocus @keyup.enter="run(verify, $event)" /></el-form-item>
          <el-form-item v-else :label="$t('opsApp.recoveryCodeSingleUse')"><el-input v-model="recovery" placeholder="xxxxx-xxxxx" data-k="ops-recovery" @keyup.enter="run(verify, $event)" /></el-form-item>
          <el-button type="primary" style="width:100%" :loading="busy" data-k="ops-verify" @click="run(verify, $event)">{{ $t('common.signIn') }}</el-button>
          <div class="alt"><el-button link type="info" @click="useRecovery = !useRecovery">{{ useRecovery ? $t('opsApp.useVerificationCode') : $t('opsApp.phoneUnavailableUseARecovery') }}</el-button></div>
        </el-form>
      </div>
    </div>

    <!-- Recovery codes (shown only once) -->
    <el-dialog v-model="codesOpen" :title="$t('opsApp.recoveryCodesShownOnlyOnce')" width="min(520px, 96vw)" :close-on-click-modal="false" :show-close="false">
      <p>{{ $t('opsApp.ifYouLoseYourPhone') }}</p>
      <div class="codes" data-k="ops-codes"><code v-for="c in codes" :key="c">{{ c }}</code></div>
      <template #footer>
        <el-button @click="downloadCodes">{{ $t('opsApp.downloadAsTextFile') }}</el-button>
        <el-button type="primary" data-k="ops-codes-ok" @click="codesOpen = false">{{ $t('opsApp.iVeSavedThem') }}</el-button>
      </template>
    </el-dialog>

    <!-- Initial password: change it first -->
    <div v-if="me && me.admin.must_change" class="center">
      <div class="box">
        <h2>{{ $t('opsApp.changeYourInitialPassword') }}</h2>
        <el-form label-position="top">
          <el-form-item :label="$t('passwordDialog.currentPassword')"><el-input v-model="pf.old" type="password" show-password /></el-form-item>
          <el-form-item :label="$t('opsApp.newPasswordAtLeast8')"><el-input v-model="pf.new" type="password" show-password data-k="ops-newpw" /></el-form-item>
          <el-button type="primary" @click="run(changePw, $event)" data-k="ops-savepw">{{ $t('common.save') }}</el-button>
        </el-form>
      </div>
    </div>

    <main v-if="me && !me.admin.must_change" class="main">
      <div class="page-head"><h2>{{ $t('opsApp.platformOperations') }}</h2><span class="sub">{{ $t('opsApp.organizationSetupSeatsUsageOperation') }}</span></div>
      <el-tabs class="ops-tabs" v-model="tab" @tab-change="run(loadTab, $event)">
        <!-- ---------------- Organizations ---------------- -->
        <el-tab-pane :label="$t('common.unit')" name="orgs">
          <div class="tools">
            <el-button type="primary" data-k="ops-new-org" @click="openOrg()">{{ $t('opsApp.createAccount') }}</el-button>
            <el-button data-k="ops-new-trial" @click="openTrial">{{ $t('opsApp.trialAccount30Days') }}</el-button>
            <span class="grow" />
            <el-input v-model="q" :placeholder="$t('opsApp.searchOrganizations')" clearable style="width:200px" />
          </div>
          <el-table :data="orgList" size="small" data-k="ops-orgs" row-key="id">
            <el-table-column prop="id" :label="$t('opsApp.code')" width="110" />
            <el-table-column :label="$t('common.unit')" min-width="180"><template #default="{ row }"><b>{{ row.name }}</b>
              <el-tag v-if="row.trial" size="small" type="warning" style="margin-left:4px">{{ $t('opsApp.trial') }}</el-tag>
              <el-tag v-if="row.status !== 'active'" size="small" type="danger" style="margin-left:4px">{{ row.status_name }}</el-tag>
              <el-tag v-else-if="row.expired" size="small" type="danger" style="margin-left:4px">{{ $t('opsApp.expired') }}</el-tag></template></el-table-column>
            <el-table-column :label="$t('opsApp.teacher')" width="90"><template #default="{ row }">{{ row.usage.teachers }} / {{ row.seats_teachers ?? $t('common.unrestricted') }}</template></el-table-column>
            <el-table-column :label="$t('common.student')" width="100"><template #default="{ row }">{{ row.usage.students }} / {{ row.seats_students ?? $t('common.unrestricted') }}</template></el-table-column>
            <el-table-column prop="expires" :label="$t('maint.expires')" width="100" />
            <el-table-column :label="$t('opsApp.aiThisMonth')" width="140"><template #default="{ row }">{{ fmtN(row.usage.ai_tokens_month) }} / {{ row.ai_quota == null ? $t('common.unrestricted') : fmtN(row.ai_quota) }}</template></el-table-column>
            <el-table-column :label="$t('opsApp.contract')" width="120"><template #default="{ row }">{{ row.plan || '' }} {{ row.contract_no || '' }}</template></el-table-column>
            <el-table-column width="300"><template #default="{ row }">
              <el-button link type="primary" :data-k="'ops-edit-' + row.id" @click="openOrg(row)">{{ $t('common.edit') }}</el-button>
              <el-button link type="primary" @click="run(addAdmin, row)">{{ $t('opsApp.addOrgAdmin') }}</el-button>
              <el-button v-if="row.status === 'active'" link type="danger" :data-k="'ops-suspend-' + row.id" @click="run(suspend, row)">{{ $t('common.disabled') }}</el-button>
              <el-button v-else link type="success" @click="run(resume, row)">{{ $t('common.restore') }}</el-button>
              <el-button link @click="run(exportOrg, row)">{{ $t('opsApp.exportData') }}</el-button>
            </template></el-table-column>
          </el-table>
          <p class="muted">{{ $t('opsApp.billingIsSettledOfflineOnly') }}</p>
        </el-tab-pane>

        <!-- ---------------- Usage ---------------- -->
        <el-tab-pane :label="$t('opsApp.usage')" name="usage">
          <el-table :data="usage" size="small" data-k="ops-usage">
            <el-table-column prop="name" :label="$t('common.unit')" min-width="160" />
            <el-table-column prop="active_30d" :label="$t('opsApp.activeInLast30Days')" width="100" />
            <el-table-column prop="teachers" :label="$t('opsApp.teacher')" width="70" /><el-table-column prop="students" :label="$t('common.student')" width="70" />
            <el-table-column prop="archived" :label="$t('opsApp.archived')" width="80" /><el-table-column prop="classes" :label="$t('opsApp.class')" width="70" />
            <el-table-column prop="submissions_month" :label="$t('opsApp.submissionsThisMonth')" width="90" /><el-table-column prop="submissions" :label="$t('opsApp.totalSubmissions')" width="90" />
            <el-table-column :label="$t('opsApp.aiTokensThisMonth')" width="130"><template #default="{ row }">{{ fmtN(row.ai_tokens_month) }}</template></el-table-column>
            <el-table-column :label="$t('opsApp.totalAiTokens')" width="130"><template #default="{ row }">{{ fmtN(row.ai_tokens_total) }}</template></el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ---------------- Operations Accounts ---------------- -->
        <el-tab-pane :label="$t('opsApp.operationsAccount')" name="admins">
          <div class="tools"><el-button type="primary" @click="run(newAdmin, $event)">{{ $t('opsApp.createOperationsAccount') }}</el-button></div>
          <el-table :data="admins" size="small">
            <el-table-column prop="username" :label="$t('common.username')" /><el-table-column prop="name" :label="$t('common.name2')" />
            <el-table-column label="TOTP" width="80"><template #default="{ row }">{{ row.totp_on ? $t('opsApp.linked') : $t('opsApp.notLinked') }}</template></el-table-column>
            <el-table-column prop="recovery_left" :label="$t('opsApp.recoveryCodesRemaining')" width="100" />
            <el-table-column :label="$t('common.status')" width="80"><template #default="{ row }">{{ row.active ? (row.locked ? $t('opsApp.locked') : $t('common.normal')) : $t('common.disabled2') }}</template></el-table-column>
            <el-table-column prop="last_login" :label="$t('common.lastLogin')" width="160" />
            <el-table-column width="200"><template #default="{ row }">
              <el-button link type="warning" @click="run(resetTotp, row)">{{ $t('opsApp.resetTotp') }}</el-button>
              <el-button v-if="row.active && row.username !== me.admin.username" link type="danger" @click="run(disableAdmin, row)">{{ $t('common.disabled') }}</el-button>
            </template></el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ---------------- Audit ---------------- -->
        <el-tab-pane :label="$t('opsApp.auditLog')" name="audit">
          <div class="tools">
            <el-button data-k="ops-verify-chain" @click="run(verifyChain, $event)">{{ $t('opsApp.verifyHashChain') }}</el-button>
            <span v-if="chain" :class="chain.ok ? 'good' : 'bad'" data-k="ops-chain">{{ chain.ok ? $t('opsApp.intact0RecordsNoneModified', [chain.count]) : $t('opsApp.issueDetected0', [chain.problems.map((p: any) => '#' + p.id + ' ' + p.why).join($t('common.k344'))]) }}</span>
            <span class="grow" /><el-input v-model="aq" :placeholder="$t('opsApp.search')" clearable style="width:200px" @change="run(loadAudit, $event)" />
          </div>
          <el-table :data="audit" size="small" data-k="ops-audit">
            <el-table-column prop="id" label="#" width="60" /><el-table-column prop="t" :label="$t('common.time')" width="150" />
            <el-table-column prop="admin" :label="$t('opsApp.operations')" width="110" /><el-table-column prop="action" :label="$t('common.actions')" width="140" />
            <el-table-column prop="target" :label="$t('common.object')" width="120" /><el-table-column prop="detail" :label="$t('opsApp.details')" min-width="200" show-overflow-tooltip />
            <el-table-column prop="ip" label="IP" width="110" />
            <el-table-column :label="$t('opsApp.hash')" width="100"><template #default="{ row }"><code class="h">{{ row.hash.slice(0, 10) }}</code></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- ---------------- Settings ---------------- -->
        <el-tab-pane :label="$t('common.settings')" name="settings">
          <div class="card">
            <h3>{{ $t('opsApp.ipAllowlist') }}</h3>
            <p class="muted">{{ $t('opsApp.onlyTheseAddressesCanAccess', [me.ip]) }}</p>
            <el-input v-model="ipAllow" style="max-width:480px" />
            <el-button type="primary" style="margin-left:8px" @click="run(saveIps, $event)">{{ $t('opsApp.saveVerificationCodeRequired') }}</el-button>
          </div>
          <div class="card">
            <h3>{{ $t('opsApp.changeMyPassword') }}</h3>
            <el-input v-model="pf.old" type="password" :placeholder="$t('passwordDialog.currentPassword')" style="max-width:220px" />
            <el-input v-model="pf.new" type="password" :placeholder="$t('passwordDialog.newPassword')" style="max-width:220px;margin-left:8px" />
            <el-button style="margin-left:8px" @click="run(changePw, $event)">{{ $t('common.save') }}</el-button>
          </div>
        </el-tab-pane>
      </el-tabs>
    </main>

    <!-- Create / edit organization -->
    <el-dialog v-model="orgOpen" :title="of.edit ? $t('opsApp.editOrganization') + of.name : (of.trial ? $t('opsApp.createTrialAccount30Days') : $t('opsApp.createAccount'))" width="min(640px, 96vw)">
      <el-form label-width="110px" data-k="ops-org-form">
        <el-form-item :label="$t('opsApp.organizationCode')"><el-input v-model="of.id" :disabled="of.edit" :placeholder="$t('opsApp.mustStartWithALowercase')" data-k="ops-org-id" /></el-form-item>
        <el-form-item :label="$t('opsApp.organizationName')"><el-input v-model="of.name" data-k="ops-org-name" /></el-form-item>
        <el-form-item :label="$t('common.type')"><el-radio-group v-model="of.kind"><el-radio-button value="school">{{ $t('opsApp.school') }}</el-radio-button><el-radio-button value="enterprise">{{ $t('opsApp.company') }}</el-radio-button></el-radio-group></el-form-item>
        <template v-if="!of.trial">
          <el-form-item :label="$t('opsApp.planContractNumber')"><el-input v-model="of.plan" :placeholder="$t('common.solution')" style="width:45%" /><el-input v-model="of.contract_no" :placeholder="$t('opsApp.contractNumber')" style="width:45%;margin-left:4%" /></el-form-item>
          <el-form-item :label="$t('opsApp.startAndEndDates')"><el-date-picker v-model="of.start_date" value-format="YYYY-MM-DD" :placeholder="$t('common.start')" style="width:45%" />
            <el-date-picker v-model="of.expires" value-format="YYYY-MM-DD" :placeholder="$t('maint.expires')" style="width:45%;margin-left:4%" data-k="ops-org-expires" /></el-form-item>
          <el-form-item :label="$t('opsApp.teacherSeats')"><el-input-number v-model="of.seats_teachers" :min="0" data-k="ops-org-teachers" /></el-form-item>
          <el-form-item :label="$t('opsApp.studentSeats')"><el-input-number v-model="of.seats_students" :min="0" data-k="ops-org-students" /></el-form-item>
          <el-form-item :label="$t('opsApp.monthlyAiQuota')"><el-input-number v-model="of.ai_quota" :min="0" :step="100000" /> <span class="muted">{{ $t('opsApp.tokensBlankUnlimited') }}</span></el-form-item>
          <el-form-item :label="$t('opsApp.featurePackage')">
            <el-checkbox v-model="of.features.plc">{{ $t('common.plcLab') }}</el-checkbox><el-checkbox v-model="of.features.ai">{{ $t('opsApp.aiTutorAssistant') }}</el-checkbox><el-checkbox v-model="of.features.client">{{ $t('common.desktopClient') }}</el-checkbox>
          </el-form-item>
          <el-form-item :label="$t('opsApp.coursePackage')"><el-input v-model="of.courses" :placeholder="$t('opsApp.allAllCoursesOrComma')" /></el-form-item>
        </template>
        <el-form-item v-if="!of.edit" :label="$t('opsApp.orgAdmin')"><el-input v-model="of.admin_username" :placeholder="$t('opsApp.usernameEGZzuAdmin')" data-k="ops-org-admin" style="width:45%" />
          <el-input v-model="of.admin_name" :placeholder="$t('common.name2')" style="width:45%;margin-left:4%" /></el-form-item>
        <el-form-item :label="$t('opsApp.contactNotes')"><el-input v-model="of.contact" :placeholder="$t('opsApp.contact')" style="width:45%" /><el-input v-model="of.notes" :placeholder="$t('opsApp.notes')" style="width:45%;margin-left:4%" /></el-form-item>
      </el-form>
      <template #footer><el-button type="primary" data-k="ops-org-save" @click="run(saveOrg, $event)">{{ of.edit ? $t('common.save') : $t('opsApp.createAccount') }}</el-button></template>
    </el-dialog>

    <!-- Password shown only once -->
    <el-dialog v-model="secretOpen" :title="$t('opsApp.initialPasswordShownOnlyOnce')" width="min(440px, 96vw)">
      <p>{{ $t('common.username') }} <b data-k="ops-new-user">{{ secretShow.username }}</b> {{ $t('opsApp.sInitialPassword') }}</p>
      <p><code class="big" data-k="ops-new-pw">{{ secretShow.password }}</code></p>
      <p class="muted">{{ $t('opsApp.shareItInPersonOr') }}</p>
      <template #footer><el-button type="primary" data-k="ops-secret-ok" @click="secretOpen = false">{{ $t('common.gotIt') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import LangSwitch from '../components/LangSwitch.vue';
import { $t } from '../i18n';
/** Button action: api already shows errors (including cancellation); do not rethrow as a page script error. */
const run = (fn: (...a: any[]) => any, ...a: any[]) => Promise.resolve().then(() => fn(...a)).catch(() => null);
import { ElMessage, ElMessageBox } from 'element-plus';
import qrcode from 'qrcode-generator';
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { markUrl } from '../brand';

document.title = $t('opsApp.honeyfactoryPlatformOperations');
const me = ref<any>(null), step = ref<'pw' | 'enroll' | 'totp'>('pw'), busy = ref(false);
const lf = reactive({ username: '', password: '' }), pending = reactive<any>({ pending: '', secret: '', uri: '' });
const code = ref(''), recovery = ref(''), useRecovery = ref(false), codes = ref<string[]>([]), codesOpen = ref(false);
const tab = ref('orgs'), orgs = ref<any[]>([]), usage = ref<any[]>([]), admins = ref<any[]>([]), audit = ref<any[]>([]), chain = ref<any>(null);
const q = ref(''), aq = ref(''), ipAllow = ref(''), pf = reactive({ old: '', new: '' });
let csrf = '';

async function ops(method: string, path: string, body?: any, headers: Record<string, string> = {}) {
  const r = await fetch(path, { method, credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...(csrf ? { 'X-CSRF-Token': csrf } : {}), ...headers },
    body: body !== undefined ? JSON.stringify(body) : undefined });
  const ct = r.headers.get('content-type') || '';
  const j = ct.includes('json') ? await r.json().catch(() => ({})) : await r.blob();
  if (r.status === 401 && me.value) { me.value = null; step.value = 'pw'; ElMessage.warning($t('opsApp.yourSessionHasExpiredPlease')); }
  if (!r.ok) { const m = (j as any)?.detail || $t('common.operationFailed0', [r.status]); ElMessage.error(m); throw new Error(m); }
  return j as any;
}
/** Sensitive action: require another verification code. */
async function askTotp(what: string) {
  const { value } = await ElMessageBox.prompt($t('opsApp.n0IsASensitiveAction', [what]), $t('opsApp.verifyAgain'), {
    inputPattern: /^\d{6}$/, inputErrorMessage: $t('opsApp.n6Digits'), confirmButtonText: $t('entityPage.ok'), cancelButtonText: $t('common.cancel'), inputPlaceholder: $t('opsApp.n6DigitVerificationCode') });
  return value as string;
}

const qrSvg = computed(() => {
  if (!pending.uri) return '';
  const qr = qrcode(0, 'M');
  qr.addData(pending.uri);
  qr.make();
  return qr.createSvgTag({ cellSize: 5, margin: 3 });
});

async function login() {
  busy.value = true;
  try {
    const j = await ops('POST', '/api/ops/login', lf);
    Object.assign(pending, j); code.value = ''; step.value = j.step;
  } finally { busy.value = false; }
}
function started(j: any) {
  csrf = j.csrf; lf.password = '';
  if (j.recovery_codes) { codes.value = j.recovery_codes; codesOpen.value = true; }
  if (j.recovery_left !== undefined && j.recovery_left <= 3) ElMessage.warning($t('opsApp.recoveryCodesRemaining0Ask', [j.recovery_left]));
  return loadMe();
}
async function enroll() {
  busy.value = true;
  try { await started(await ops('POST', '/api/ops/enroll', { pending: pending.pending, code: code.value })); } finally { busy.value = false; }
}
async function verify() {
  busy.value = true;
  try {
    await started(await ops('POST', '/api/ops/verify', useRecovery.value ? { pending: pending.pending, recovery: recovery.value } : { pending: pending.pending, code: code.value }));
  } finally { busy.value = false; }
}
async function loadMe() {
  try {
    const j = await fetch('/api/ops/me', { credentials: 'same-origin' });
    if (!j.ok) { me.value = null; return; }
    me.value = await j.json(); csrf = me.value.csrf; ipAllow.value = me.value.ip_allow || '';
    if (!me.value.admin.must_change) loadTab().catch(() => null);
  } catch { me.value = null; }
}
async function logout() { await ops('POST', '/api/ops/logout', {}); me.value = null; step.value = 'pw'; csrf = ''; }
function downloadCodes() {
  const blob = new Blob([$t('opsApp.honeyfactoryOperationsRecoveryCodes0', [me.value?.admin?.username, new Date().toLocaleString()]) + codes.value.join('\n') + '\n'], { type: 'text/plain' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'vf-ops-recovery-codes.txt'; a.click();
}
async function changePw() {
  await ops('POST', '/api/ops/password', { old: pf.old, new: pf.new });
  ElMessage.success($t('opsApp.passwordChanged')); pf.old = pf.new = ''; await loadMe();
}

const orgList = computed(() => orgs.value.filter((o) => !q.value || (o.name + o.id).includes(q.value)));
const fmtN = (n: any) => (n == null ? '—' : Number(n).toLocaleString());
async function loadTab() {
  if (tab.value === 'orgs') orgs.value = (await ops('GET', '/api/ops/orgs')).orgs;
  if (tab.value === 'usage') usage.value = (await ops('GET', '/api/ops/usage')).orgs;
  if (tab.value === 'admins') admins.value = (await ops('GET', '/api/ops/admins')).admins;
  if (tab.value === 'audit') loadAudit();
}
async function loadAudit() { audit.value = (await ops('GET', '/api/ops/audit?limit=500' + (aq.value ? '&q=' + encodeURIComponent(aq.value) : ''))).rows; }
async function verifyChain() { chain.value = await ops('GET', '/api/ops/audit/verify'); }

const orgOpen = ref(false), of = reactive<any>({ features: {} });
const SENS = ['seats_teachers', 'seats_students', 'expires', 'ai_quota', 'features'];
function openOrg(row?: any) {
  const f = row?.features || { courses: 'all', plc: true, ai: true, client: true };
  Object.assign(of, { edit: !!row, trial: false, id: '', name: '', kind: 'school', plan: '', contract_no: '', start_date: '', expires: '', seats_teachers: 10,
    seats_students: 200, ai_quota: 1000000, admin_username: '', admin_name: '', contact: '', notes: '' }, row ? { ...row } : {},
  { features: { plc: !!f.plc, ai: !!f.ai, client: !!f.client }, courses: Array.isArray(f.courses) ? f.courses.join(',') : (f.courses || 'all'), _orig: row });
  orgOpen.value = true;
}
function openTrial() { openOrg(); of.trial = true; }
const secretOpen = ref(false), secretShow = reactive({ username: '', password: '' });
function showSecret(u: string, p: string) { Object.assign(secretShow, { username: u, password: p }); secretOpen.value = true; }
async function saveOrg() {
  const feats = { ...of.features, courses: (of.courses || 'all').trim() === 'all' ? 'all' : of.courses.split(',').map((x: string) => x.trim()).filter(Boolean) };
  if (of.trial) {
    const r = await ops('POST', '/api/ops/trials', { id: of.id, name: of.name, kind: of.kind, admin_username: of.admin_username, admin_name: of.admin_name, contact: of.contact, notes: of.notes });
    orgOpen.value = false; if (r.admin) showSecret(r.admin.username, r.admin.password); return loadTab();
  }
  const body: any = { name: of.name, kind: of.kind, plan: of.plan, contract_no: of.contract_no, start_date: of.start_date || null, expires: of.expires || null,
    seats_teachers: of.seats_teachers, seats_students: of.seats_students, ai_quota: of.ai_quota, features: feats, contact: of.contact, notes: of.notes };
  if (of.edit) {
    const o = of._orig;
    const changed = SENS.filter((k) => JSON.stringify(k === 'features' ? feats : body[k]) !== JSON.stringify(k === 'features' ? { ...o.features, ...feats } : o[k]));
    if (!changed.length) SENS.forEach((k) => delete body[k]);
    else body.totp = await askTotp($t('opsApp.changeSeatsExpirationDateFeature'));
    await ops('PATCH', `/api/ops/orgs/${of.id}`, body);
    ElMessage.success($t('common.saved'));
  } else {
    body.id = of.id; body.admin_username = of.admin_username; body.admin_name = of.admin_name; body.totp = await askTotp($t('opsApp.createAccount'));
    const r = await ops('POST', '/api/ops/orgs', body);
    if (r.admin) showSecret(r.admin.username, r.admin.password);
  }
  orgOpen.value = false; loadTab();
}
async function addAdmin(row: any) {
  const { value } = await ElMessageBox.prompt($t('opsApp.createAnotherOrgAdminFor', [row.name]), $t('opsApp.addOrgAdmin'), { inputPlaceholder: `${row.id}.admin2` });
  const r = await ops('POST', `/api/ops/orgs/${row.id}/admins`, { username: value, totp: await askTotp($t('opsApp.createOrgAdmin')) });
  showSecret(r.username, r.password);
}
async function suspend(row: any) {
  const { value } = await ElMessageBox.prompt($t('opsApp.disable0AllAccountsWill', [row.name]), $t('opsApp.disableOrganization'), { confirmButtonText: $t('common.next') });
  await ops('POST', `/api/ops/orgs/${row.id}/suspend`, { reason: value, totp: await askTotp($t('opsApp.disableOrganization')) }); ElMessage.success($t('common.disabled2')); loadTab();
}
async function resume(row: any) { await ops('POST', `/api/ops/orgs/${row.id}/resume`, { totp: await askTotp($t('opsApp.restoreOrganization')) }); ElMessage.success($t('common.restored')); loadTab(); }
async function exportOrg(row: any) {
  const blob = await ops('GET', `/api/ops/orgs/${row.id}/export`, undefined, { 'X-OPS-TOTP': await askTotp($t('opsApp.exportOrganizationData')) });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = `org-${row.id}.zip`; a.click();
}
async function newAdmin() {
  const { value } = await ElMessageBox.prompt($t('opsApp.newOperationsAccountLinkTotp'), $t('opsApp.createOperationsAccount'), { inputPlaceholder: 'ops.wang' });
  const r = await ops('POST', '/api/ops/admins', { username: value, totp: await askTotp($t('opsApp.createOperationsAccount')) }); showSecret(r.username, r.password); loadTab();
}
async function disableAdmin(row: any) { await ops('POST', `/api/ops/admins/${row.id}/disable`, { totp: await askTotp($t('opsApp.disableOperationsAccount')) }); loadTab(); }
async function resetTotp(row: any) { await ops('POST', `/api/ops/admins/${row.id}/reset_totp`, { totp: await askTotp($t('opsApp.resetTotp')) }); ElMessage.success($t('opsApp.resetCompleteTheUserMust')); loadTab(); }
async function saveIps() { const r = await ops('PUT', '/api/ops/settings', { ip_allow: ipAllow.value, totp: await askTotp($t('opsApp.changeIpAllowlist')) }); ipAllow.value = r.ip_allow; ElMessage.success($t('common.saved')); }

let timer: any;
onMounted(() => { loadMe(); timer = setInterval(() => { if (me.value) loadMe(); }, 60000); });
onUnmounted(() => clearInterval(timer));
</script>

<style scoped>
/* 5.0.1: same light theme as HoneyMOM: white top bar with a thin border, light gray fine-grid canvas, white cards */
.ops { min-height: 100vh; color: var(--hm-text); }
.bar { position: sticky; top: 0; z-index: 10; display: flex; align-items: center; gap: 10px; height: var(--hm-top-h); padding: 0 18px; background: var(--hm-glass-strong);
  backdrop-filter: var(--hm-glass-blur); border-bottom: 1px solid var(--hm-border); color: var(--hm-text); }
.bar img { height: 28px; }
.brand { display: flex; flex-direction: column; line-height: 1.2; } .brand b { font-size: var(--hm-fs-md); font-weight: 700; } .brand small { font-size: var(--hm-fs-2xs); color: var(--hm-text-3); }
.bar .who { font-size: var(--hm-fs-sm); color: var(--hm-text-2); } .bar .muted { color: var(--hm-text-3); font-size: 12px; } .grow { flex: 1; }
.center { display: flex; justify-content: center; padding: 60px 16px; }
.box { width: min(400px, 100%); background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); padding: 24px 28px; box-shadow: var(--hm-e3); }
.box.wide { width: min(560px, 100%); } .box h2 { margin: 0 0 10px; font-size: var(--hm-fs-xl); font-weight: var(--hm-fw-semibold); }
.steps { padding-left: 18px; line-height: 1.8; font-size: 13px; } .steps code, code { background: var(--hm-surface-2); border: 1px solid var(--hm-border); font-family: var(--hm-font-mono); padding: 1px 5px; border-radius: var(--hm-r-xs); word-break: break-all; }
.qr { margin: 10px 0 14px; } .qr :deep(svg) { width: 200px; height: 200px; }
.alt { text-align: center; margin-top: 8px; }
.codes { display: grid; grid-template-columns: repeat(2, 1fr); gap: 6px; margin: 10px 0; } .codes code { font-size: 15px; text-align: center; padding: 6px; }
.main { padding: var(--hm-sp-4) var(--hm-sp-5) var(--hm-sp-8); max-width: calc(1920px * var(--hm-scale)); }
.ops-tabs { background: var(--hm-surface); border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); box-shadow: var(--hm-e1); padding: 4px 16px 14px; }
.tools { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
.muted { color: var(--hm-text-3); font-size: 12px; }
.card { background: var(--hm-surface-2); border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); padding: 14px 18px; margin-bottom: 12px; box-shadow: none; }
.good { color: var(--hm-run-ink); } .bad { color: var(--hm-fault-ink); } .big { font-size: 20px; padding: 4px 10px; } .h { font-size: 11px; }
@media (max-width: 700px) { .bar .muted { display: none; } .main { padding: 10px; } }
</style>