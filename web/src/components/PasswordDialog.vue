<template>
  <el-dialog :model-value="modelValue" :title="title || $t('passwordDialog.changePassword')" width="420px" append-to-body :close-on-click-modal="false"
             :close-on-press-escape="!must" :show-close="!must" class="pw-dlg" @update:model-value="(v: boolean) => !v && modelValue && cancel()" @opened="focus">
    <div v-if="intro" class="pw-intro">{{ intro }}</div>
    <el-form label-position="top" size="default" @submit.prevent="save">
      <el-form-item v-if="!knownOld" :label="$t('passwordDialog.currentPassword')">
        <el-input ref="firstEl" v-model="f.old" type="password" show-password autocomplete="current-password" data-k="pw-old" />
      </el-form-item>
      <el-form-item :label="$t('passwordDialog.newPassword')">
        <el-input ref="newEl" v-model="f.n1" type="password" show-password autocomplete="new-password" data-k="pw-new" />
      </el-form-item>
      <el-form-item :label="$t('passwordDialog.confirmNewPassword')" :error="mismatch ? $t('passwordDialog.theNewPasswordsDoNot') : ''">
        <el-input v-model="f.n2" type="password" show-password autocomplete="new-password" data-k="pw-new2" @keyup.enter="save" />
      </el-form-item>
    </el-form>
    <ul class="pw-rules" data-k="pw-rules">
      <li v-for="r in rules" :key="r.t" :class="r.ok === null ? '' : r.ok ? 'ok' : 'bad'">
        <el-icon><CircleCheckFilled v-if="r.ok" /><CircleCloseFilled v-else-if="r.ok === false" /><InfoFilled v-else /></el-icon>{{ r.t }}</li>
    </ul>
    <div v-if="desk.on && desk.mode === 'server'" class="pw-note">{{ $t('passwordDialog.thisChangesYourAccountPassword', [host]) }}</div>
    <template #footer>
      <el-button v-if="!must" @click="cancel">{{ laterText || $t('common.cancel') }}</el-button>
      <el-button v-else-if="laterText" @click="cancel">{{ laterText }}</el-button>
      <el-button type="primary" :loading="busy" :disabled="!canSave" data-k="pw-save" @click="save">{{ $t('passwordDialog.saveNewPassword') }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
// Shared password dialog: avatar menu "Change Password", mandatory change on first login with the initial password, and student password-change prompt.
// Match server rules (vfactory/api2.py /api/me/password): at least 6 characters, different from the old password, not the initial password; both entries must match.
import { ElMessage } from 'element-plus';
import { computed, reactive, ref, watch } from 'vue';
import { desk, post } from '../api';

const props = defineProps<{ modelValue: boolean; old?: string; must?: boolean; title?: string; intro?: string; laterText?: string }>();
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'done'): void; (e: 'later'): void }>();
const INITIAL = ['honey123', '123456', 'teach123'];
const f = reactive({ old: '', n1: '', n2: '' });
const busy = ref(false);
const firstEl = ref<any>(null), newEl = ref<any>(null);
const knownOld = computed(() => !!props.old);
const oldPw = computed(() => props.old || f.old);
const host = computed(() => (desk.server || '').replace(/^https?:\/\//, ''));
const mismatch = computed(() => !!f.n2 && f.n1 !== f.n2);
const rules = computed(() => [
  { t: $t('passwordDialog.atLeast6Characters'), ok: f.n1 ? f.n1.length >= 6 : null },
  { t: $t('passwordDialog.differentFromTheCurrentPassword'), ok: f.n1 && oldPw.value ? f.n1 !== oldPw.value : null },
  { t: $t('passwordDialog.cannotUseADefaultPassword'), ok: f.n1 ? !INITIAL.includes(f.n1) : null },
  { t: $t('passwordDialog.passwordsMatch'), ok: f.n2 ? f.n1 === f.n2 : null },
]);
const canSave = computed(() => !!oldPw.value && rules.value.every((r) => r.ok === true));
watch(() => props.modelValue, (v) => { if (v) Object.assign(f, { old: '', n1: '', n2: '' }); });
function focus() { (knownOld.value ? newEl.value : firstEl.value)?.focus?.(); }
function cancel() { emit('update:modelValue', false); emit('later'); }
async function save() {
  if (!canSave.value) { if (mismatch.value) ElMessage.error($t('passwordDialog.theNewPasswordsDoNot')); return; }
  busy.value = true;
  try {
    const r = await post('/api/me/password', { old: oldPw.value, new: f.n1 });
    ElMessage.success(r.offline_login_updated ? $t('passwordDialog.passwordChangedForBothYour') : $t('passwordDialog.passwordChangedUseTheNew'));
    emit('update:modelValue', false);
    emit('done');
  } catch { /* Server message already shown */ } finally { busy.value = false; }
}
</script>

<style scoped>
.pw-intro { font-size: 13px; color: var(--el-text-color-regular); margin-bottom: 10px; line-height: 1.6; }
.pw-rules { list-style: none; padding: 8px 10px; margin: 0; background: var(--el-fill-color-light); border-radius: 6px; font-size: 12.5px; }
.pw-rules li { display: flex; align-items: center; gap: 6px; line-height: 1.9; color: var(--el-text-color-secondary); }
.pw-rules li.ok { color: var(--el-color-success); }
.pw-rules li.bad { color: var(--el-color-danger); }
.pw-note { margin-top: 8px; font-size: 12px; color: var(--el-text-color-secondary); }
</style>
