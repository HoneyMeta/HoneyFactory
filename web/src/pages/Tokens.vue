<template>
  <div class="page tokens">
    <div class="page-head"><h2>{{ $t('common.apiTokens') }}</h2><span class="sub">{{ $t('tokens.useTokensForHttpApi') }}</span><span class="grow" />
      <el-button @click="open('/docs')"><el-icon><Reading /></el-icon>{{ $t('signals.apiDocumentation') }}</el-button>
      <el-button v-if="edit" type="primary" @click="dlg = true"><el-icon><Plus /></el-icon>{{ $t('tokens.newToken') }}</el-button></div>
    <el-alert v-if="fresh" type="success" :closable="false" style="margin-bottom:12px" :title="$t('tokens.newTokenShownOnlyOnce')">
      <code class="tok">{{ fresh }}</code> <el-button size="small" @click="copy">{{ $t('common.copy') }}</el-button></el-alert>
    <div class="card"><el-table :data="rows" size="small">
      <el-table-column prop="name" :label="$t('common.name')" min-width="140" /><el-table-column :label="$t('sections.token')" width="120"><template #default="{ row }"><span class="mono">{{ row.prefix }}…</span></template></el-table-column>
      <el-table-column :label="$t('common.scope')" width="150"><template #default="{ row }"><span class="tag-st" :class="'sc-' + (row.scope || 'legacy')">{{ row.scope || $t('tokens.oldToken') }}</span>
        <div class="small muted">{{ row.scope_name }}</div></template></el-table-column>
      <el-table-column :label="$t('tokens.factoryScope')" min-width="120"><template #default="{ row }">{{ row.plants?.length ? row.plants.join($t('common.k360')) : $t('common.all') }}</template></el-table-column>
      <el-table-column :label="$t('tokens.expiresOn')" width="150"><template #default="{ row }"><span :class="{ bad: row.expired }">{{ row.expires || $t('org.perpetual') }}</span></template></el-table-column>
      <el-table-column :label="$t('opsApp.ipAllowlist')" min-width="110"><template #default="{ row }"><span class="mono small">{{ row.ips || $t('common.unrestricted') }}</span></template></el-table-column>
      <el-table-column prop="username" :label="$t('tokens.owner')" width="90" /><el-table-column prop="created" :label="$t('tokens.createdAt')" width="150" />
      <el-table-column :label="$t('common.recentlyUsed')" width="170"><template #default="{ row }"><template v-if="row.last_used">{{ row.last_used }}<div class="small muted">{{ $t('tokens.n01Uses', [row.last_ip, row.uses]) }}</div></template>
        <span v-else class="muted">{{ $t('tokens.neverUsed') }}</span></template></el-table-column>
      <el-table-column :label="$t('common.status')" width="80"><template #default="{ row }"><span class="tag-st" :class="row.revoked || row.expired ? 'st-Stopped' : 'st-done'">{{ row.revoked ? $t('tokens.revoked') : row.expired ? $t('org.expired') : $t('tokens.active') }}</span></template></el-table-column>
      <el-table-column width="70"><template #default="{ row }"><el-popconfirm v-if="!row.revoked" :title="$t('tokens.revokingThisTokenImmediatelyBlocks')" @confirm="revoke(row)">
        <template #reference><el-button link type="danger">{{ $t('tokens.revoke') }}</el-button></template></el-popconfirm></template></el-table-column></el-table></div>
    <div class="card" style="margin-top:14px"><h3>{{ $t('tokens.usageExamples') }}</h3>
      <pre class="small">{{ $t('tokens.curlHAuthorizationBearerToken', [host, host, host, hostname]) }}</pre>
      <p class="small muted">{{ $t('tokens.scopesReadReadOnlyWrite') }}</p></div>

    <el-dialog v-model="dlg" :title="$t('tokens.newApiToken')" width="520px">
      <el-form label-width="90px" size="default">
        <el-form-item :label="$t('tokens.purpose')"><el-input v-model="nf.name" :placeholder="$t('tokens.eGHoneymomIntegrationTest')" maxlength="40" /></el-form-item>
        <el-form-item :label="$t('common.scope')"><el-radio-group v-model="nf.scope" class="scopes">
          <el-radio v-for="o in opts.scopes" :key="o.value" :value="o.value" :disabled="!o.allowed"><b>{{ o.value }}</b> <span class="small muted">{{ o.label }}</span></el-radio></el-radio-group></el-form-item>
        <el-form-item :label="$t('tokens.factoryScope')"><el-select v-model="nf.plants" multiple clearable :placeholder="$t('tokens.unrestrictedAllFactories')" style="width:100%">
          <el-option v-for="p in opts.plants" :key="p.id" :label="`${p.id} ${p.name}`" :value="p.id" /></el-select></el-form-item>
        <el-form-item :label="$t('tokens.validityPeriod')"><el-select v-model="nf.days" style="width:160px"><el-option v-for="d in DAYS" :key="d[0]" :label="d[1]" :value="d[0]" /></el-select></el-form-item>
        <el-form-item :label="$t('opsApp.ipAllowlist')"><el-input v-model="nf.ips" :placeholder="$t('tokens.leaveBlankForUnrestrictedAccess')" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="dlg = false">{{ $t('common.cancel') }}</el-button><el-button type="primary" :disabled="!nf.name" @click="create">{{ $t('tables.create') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { onMounted, reactive, ref, watch } from 'vue';
import { canEdit, del, get, post } from '../api';

const rows = ref<any[]>([]), fresh = ref(''), edit = canEdit(), host = location.host, hostname = location.hostname, dlg = ref(false);
const opts = ref<any>({ scopes: [], plants: [] });
const DAYS: [number, string][] = [[7, $t('quality.n7Days')], [30, $t('quality.n30Days')], [90, $t('tokens.n90Days')], [365, $t('tokens.n1Year')], [0, $t('tokens.neverExpires')]];
const nf = reactive<any>({ name: '', scope: 'read', plants: [], days: 90, ips: '' });
const open = (u: string) => window.open(u);
async function load() { rows.value = await get('/api/tokens'); }
async function create() {
  const r = await post('/api/tokens', { name: nf.name, scope: nf.scope, plants: nf.plants, expires_days: nf.days || undefined, ips: nf.ips });
  fresh.value = r.token; dlg.value = false; nf.name = ''; load();
}
async function revoke(r: any) { await del('/api/tokens/' + r.id); load(); }
function copy() { navigator.clipboard?.writeText(fresh.value); ElMessage.success($t('common.copied')); }
watch(dlg, async (v) => { if (v) opts.value = await get('/api/tokens/options'); });
onMounted(load);
</script>

<style scoped>
.tok { font-size: 14px; background: var(--hm-surface-2); border: 1px solid var(--hm-border); color: var(--hm-text); font-family: var(--hm-font-mono); padding: 2px 6px; border-radius: 4px; }
pre { background: var(--hm-surface-2); border: 1px solid var(--hm-border); color: var(--hm-text); font-family: var(--hm-font-mono); padding: 10px; border-radius: var(--hm-r-md); white-space: pre-wrap; }
.scopes { display: grid; gap: 4px; } .scopes :deep(.el-radio) { height: auto; margin-right: 0; }
.sc-admin { background: var(--el-color-danger-light-9); color: var(--el-color-danger); } .sc-control { background: var(--el-color-warning-light-9); color: var(--el-color-warning); }
.sc-write { background: var(--el-color-primary-light-9); }
</style>
