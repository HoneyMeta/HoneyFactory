<template>
  <div class="page my-plants">
    <div class="page-head">
      <h2>{{ $t('common.myFactories') }}</h2>
      <span class="sub">{{ $t('myPlants.keepUnlimitedFactoriesOnThis') }}</span>
      <span class="grow" />
      <input ref="fileEl" type="file" accept=".vfplant,.vfhw" style="display: none" @change="pickFile" />
      <el-button data-k="mine-import" @click="fileEl?.click()"><el-icon><Upload /></el-icon>{{ $t('myPlants.import') }}</el-button>
      <el-button type="primary" data-k="mine-new" @click="newOpen = true"><el-icon><Plus /></el-icon>{{ $t('common.newFactory') }}</el-button>
    </div>

    <div v-if="!loading && !list.length" class="empty-mine card" data-k="mine-empty">
      <img v-if="emptyImg.src" :src="emptyImg.src" :srcset="emptyImg.srcset || undefined" alt="" class="em-img" />
      <el-icon v-else :size="40" class="em-i"><OfficeBuilding /></el-icon>
      <div class="em-t">{{ $t('common.noFactoriesYet') }}</div>
      <div class="em-d">{{ $t('myPlants.chooseAStartingPointA') }}</div>
      <el-button type="primary" style="margin-top: 12px" @click="newOpen = true"><el-icon><Plus /></el-icon>{{ $t('common.newFactory') }}</el-button>
    </div>

    <div v-else class="grid" v-loading="loading">
      <div v-for="p in list" :key="p.id" class="pl card" :data-pid="p.id">
        <div class="pl-h">
          <el-icon class="pl-i"><OfficeBuilding /></el-icon>
          <b class="pl-n" :title="p.name">{{ p.name }}</b>
          <el-tag v-if="p.draft" size="small" type="warning" effect="plain" :title="$t('myPlants.theWorkbenchHasUnsavedChanges')">{{ $t('myPlants.draftAvailable') }}</el-tag>
        </div>
        <div class="pl-m">{{ $t('myPlants.n0Objects1PlcsModified', [p.blocks, p.plcs, p.updated || '—']) }}</div>
        <div class="pl-m muted">{{ fromText(p.from) }}<template v-if="p.created"> {{ $t('myPlants.created0', [p.created.slice(0, 16)]) }}</template></div>
        <div class="pl-a">
          <el-button size="small" type="primary" data-k="mine-open" @click="openIt(p)"><el-icon><Monitor /></el-icon>{{ $t('common.open') }}</el-button>
          <el-button size="small" @click="rename(p)">{{ $t('common.rename') }}</el-button>
          <el-button size="small" :loading="busy === 'c' + p.id" @click="copy(p)">{{ $t('common.copy') }}</el-button>
          <el-button size="small" :loading="busy === 'e' + p.id" @click="exportIt(p)" :title="$t('myPlants.exportAsAVfplantFile')"><el-icon><Download /></el-icon>{{ $t('common.export') }}</el-button>
          <span class="grow" />
          <el-button size="small" text type="danger" @click="remove(p)"><el-icon><Delete /></el-icon></el-button>
        </div>
      </div>
    </div>

    <el-dialog v-model="newOpen" :title="$t('common.newFactory')" width="640px" append-to-body destroy-on-close>
      <el-form label-width="80px" size="default" @submit.prevent>
        <el-form-item :label="$t('common.name')"><el-input v-model="form.name" :placeholder="$t('myPlants.eGMyAssemblyLine')" maxlength="40" data-k="mine-name" /></el-form-item>
        <el-form-item :label="$t('details.start')">
          <div class="tpl-list">
            <template v-for="g in groups" :key="g.name">
              <div class="tpl-g">{{ g.name }}</div>
              <div v-for="t in g.items" :key="t.key" class="tpl" :class="{ on: form.template === t.key }" :data-tpl="t.key" @click="form.template = t.key">
                <el-icon v-if="form.template === t.key" class="ok"><CircleCheckFilled /></el-icon>
                <b>{{ t.name }}</b><span class="muted small">{{ t.desc }}</span>
              </div>
            </template>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newOpen = false">{{ $t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="busy === 'new'" data-k="mine-create" @click="create">{{ $t('myPlants.createAndOpen') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
// Desktop client "My Factories" (4.4): unlimited student-owned local factories, stored only on this computer (vfactory/teach/myplants.py).
// Open = Workbench (all workspaces, unrestricted editing as for engineers); submit a factory for a design assignment under "Teaching → This Assignment".
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { del, get, patch, post } from '../api';
import { saveFile } from '../panels/teach/util';
import { brand, loadBrand, themed } from '../brand';

loadBrand();
const emptyImg = computed(() => (brand.loaded ? themed('empty-factories') : { src: '', srcset: '' }));   // Designer-provided empty-state illustration (fall back to an icon)

const router = useRouter();
const list = ref<any[]>([]);
const templates = ref<any[]>([]);
const loading = ref(false);
const busy = ref('');
const newOpen = ref(false);
const form = reactive({ name: '', template: 'blank' });
const fileEl = ref<HTMLInputElement | null>(null);
const groups = computed(() => {
  const m: Record<string, any[]> = {};
  for (const t of templates.value) (m[t.group] ||= []).push(t);
  return Object.entries(m).map(([name, items]) => ({ name, items }));
});
const fromText = (f: string) => {
  if (!f) return '';
  if (f === 'import') return $t('myPlants.imported');
  if (f.startsWith('local-')) return $t('myPlants.copied');
  const t = templates.value.find((x) => x.key === f);
  return t ? $t('myPlants.startingPoint0', [t.name]) : '';
};

async function load() {
  loading.value = true;
  try { const r = await get('/api/client/myplants'); list.value = r.plants; templates.value = r.templates; } finally { loading.value = false; }
}
function openIt(p: any) { router.push(`/p/${encodeURIComponent(p.id)}/workbench`); }
async function create() {
  busy.value = 'new';
  try {
    const r = await post('/api/client/myplants', { name: form.name || templates.value.find((t) => t.key === form.template)?.name || $t('common.myFactories'), template: form.template });
    newOpen.value = false; form.name = '';
    ElMessage.success($t('myPlants.created02', [r.name]));
    openIt(r);
  } finally { busy.value = ''; }
}
async function rename(p: any) {
  const { value } = await ElMessageBox.prompt($t('myPlants.newName'), $t('common.rename'), { inputValue: p.name, inputPattern: /\S/, inputErrorMessage: $t('myPlants.nameCannotBeEmpty') });
  await patch(`/api/client/myplants/${encodeURIComponent(p.id)}`, { name: value });
  await load();
}
async function copy(p: any) {
  busy.value = 'c' + p.id;
  try { await post(`/api/client/myplants/${encodeURIComponent(p.id)}/copy`, {}); ElMessage.success($t('common.copied')); await load(); } finally { busy.value = ''; }
}
async function remove(p: any) {
  await ElMessageBox.confirm($t('myPlants.deleteFactory0FilesWill', [p.name]), $t('common.delete'), { type: 'warning' });
  await del(`/api/client/myplants/${encodeURIComponent(p.id)}`);
  await load();
}
async function exportIt(p: any) {
  busy.value = 'e' + p.id;
  try { await saveFile(`/api/client/myplants/${encodeURIComponent(p.id)}/export`, `${p.name}.vfplant`); ElMessage.success($t('myPlants.exportedUseImportOnAnother')); } finally { busy.value = ''; }
}
async function pickFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  (e.target as HTMLInputElement).value = '';
  if (!f) return;
  const b64 = await new Promise<string>((ok) => { const rd = new FileReader(); rd.onload = () => ok(String(rd.result)); rd.readAsDataURL(f); });
  const r = await post('/api/client/myplants/import', { data: b64 });
  ElMessage.success($t('myPlants.imported0', [r.name]));
  await load();
}
onMounted(load);
</script>

<style scoped>
.my-plants { max-width: 1600px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 12px; }
.pl { display: flex; flex-direction: column; gap: 6px; }
.pl-h { display: flex; align-items: center; gap: 8px; min-width: 0; }
.pl-i { color: var(--hm-primary); background: var(--hm-primary-soft); border-radius: var(--hm-r-md); padding: 5px; font-size: 26px; flex: none; }
.pl:hover { border-color: var(--el-color-primary-light-5); box-shadow: var(--hm-e2); }
.pl-n { font-size: var(--hm-fs-md); font-weight: var(--hm-fw-semibold); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.pl-m { font-size: var(--hm-fs-xs); color: var(--hm-text-2); }
.pl-a { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; margin-top: 4px; }
.pl-a .el-button + .el-button { margin-left: 0; }
.empty-mine { max-width: 560px; margin: 50px auto; text-align: center; padding: 30px; }
.em-i { color: var(--el-color-primary); }
.em-t { font-size: var(--hm-fs-lg); font-weight: 600; margin-top: 6px; }
.em-d { font-size: var(--hm-fs-sm); color: var(--hm-text-3); margin-top: 6px; line-height: 1.7; }
.tpl-list { width: 100%; max-height: 52vh; overflow: auto; border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 6px; }
.tpl-g { font-size: 12px; color: var(--el-text-color-secondary); margin: 8px 4px 4px; }
.tpl { display: flex; align-items: baseline; gap: 8px; padding: 6px 8px; border-radius: 5px; cursor: pointer; line-height: 1.5; }
.tpl:hover { background: var(--el-fill-color-light); }
.tpl.on { background: var(--el-color-primary-light-9); box-shadow: 0 0 0 1px var(--el-color-primary-light-5) inset; }
.tpl .ok { color: var(--el-color-primary); align-self: center; }
.tpl b { white-space: nowrap; font-weight: 500; }
.em-img { width: min(220px, 60%); height: auto; margin-bottom: 6px; }
</style>
