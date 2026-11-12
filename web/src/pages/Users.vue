<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('common.usersRoles') }}</h2><span class="sub">{{ $t('users.adminAllFeaturesEngineerRun') }}</span><span class="grow" />
      <el-button type="primary" @click="openForm()"><el-icon><Plus /></el-icon>{{ $t('users.addUser') }}</el-button></div>
    <div class="card"><el-table :data="rows" size="small">
      <el-table-column prop="username" :label="$t('common.username')" /><el-table-column prop="name" :label="$t('common.name2')" />
      <el-table-column :label="$t('users.roles')"><template #default="{ row }">{{ roles[row.role] }}</template></el-table-column>
      <el-table-column :label="$t('common.status')"><template #default="{ row }"><span class="tag-st" :class="row.active ? 'st-done' : 'st-Stopped'">{{ row.active ? $t('common.enable') : $t('common.disabled') }}</span></template></el-table-column>
      <el-table-column prop="last_login" :label="$t('common.lastLogin')" width="160" /><el-table-column prop="created" :label="$t('tokens.createdAt')" width="160" />
      <el-table-column width="80"><template #default="{ row }"><el-button link type="primary" @click="openForm(row)">{{ $t('common.edit') }}</el-button></template></el-table-column></el-table></div>
    <el-dialog v-model="dlg" :title="f.id ? $t('users.editUser') : $t('users.addUser2')" width="min(440px, 96vw)">
      <el-form label-width="70px">
        <el-form-item :label="$t('common.username')"><el-input v-model="f.username" :disabled="!!f.id" /></el-form-item>
        <el-form-item :label="$t('common.name2')"><el-input v-model="f.name" /></el-form-item>
        <el-form-item :label="$t('users.roles')"><el-radio-group v-model="f.role"><el-radio-button v-for="(n, k) in roles" :key="k" :value="k">{{ n }}</el-radio-button></el-radio-group></el-form-item>
        <el-form-item :label="$t('common.password')"><el-input v-model="f.password" type="password" show-password :placeholder="f.id ? $t('users.leaveBlankToKeepUnchanged') : $t('users.defaultHoney123')" /></el-form-item>
        <el-form-item v-if="f.id" :label="$t('common.enable')"><el-switch v-model="f.active" /></el-form-item>
      </el-form>
      <template #footer><el-button type="primary" @click="save">{{ $t('common.save') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { onMounted, reactive, ref } from 'vue';
import { get, post } from '../api';

const rows = ref<any[]>([]), roles = ref<any>({}), dlg = ref(false), f = reactive<any>({});
async function load() { const r = await get('/api/admin/users'); rows.value = r.users; roles.value = r.roles; }
function openForm(r?: any) { Object.assign(f, { id: null, username: '', name: '', role: 'engineer', password: '', active: true }, r ? { ...r, active: !!r.active, password: '' } : {}); dlg.value = true; }
async function save() { await post('/api/admin/users', f); ElMessage.success($t('common.saved')); dlg.value = false; load(); }
onMounted(load);
</script>
