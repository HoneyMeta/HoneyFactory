<template>
  <div class="page">
    <div class="page-head"><h2>{{ $t('mesNav.andonBoard') }}</h2><span class="sub">{{ $t('andon.dataTime0RefreshesEvery', [d?.now]) }}</span><span class="grow" />
      <el-button v-if="writable" type="danger" @click="openRaise"><el-icon><Bell /></el-icon>{{ $t('andon.raiseAndon') }}</el-button>
      <el-button @click="router.push('/mes/e/andon')">{{ $t('andon.allRecords') }}</el-button></div>
    <div class="grid g2" v-if="d">
      <div class="card">
        <h3>{{ $t('andon.openAndonCalls') }} <small>{{ $t('common.n03', [d.open.length]) }}</small></h3>
        <p v-if="!d.open.length" class="ok">{{ $t('andon.noOpenAndonCalls') }}</p>
        <div v-for="a in d.open" :key="a.id" class="an" :class="'t-' + a.atype">
          <div class="ah"><b>{{ a.code }}</b><el-tag size="small" :type="a.status === 'open' ? 'danger' : 'warning'">{{ a.status === 'open' ? $t('andon.awaitingResponse') : $t('andon.inProgress') }}</el-tag>
            <span class="muted small">{{ T[a.atype] || a.atype }} · {{ a.equipment__label || a.station || '' }} · {{ (a.raised_at || '').slice(5, 16) }}</span></div>
          <div class="desc">{{ a.description }}</div>
          <div class="muted small" v-if="a.responder">{{ $t('andon.responder0', [a.responder]) }}</div>
          <div class="btns">
            <el-button v-if="writable && a.status === 'open'" size="small" @click="act(a, 'respond')">{{ $t('andon.iLlRespond') }}</el-button>
            <el-button v-if="writable" size="small" type="success" plain @click="closeA(a)">{{ $t('common.close') }}</el-button>
          </div>
        </div>
      </div>
      <div class="card">
        <h3>{{ $t('andon.recentlyClosed') }}</h3><p v-if="!d.closed.length" class="muted small">{{ $t('common.none') }}</p>
        <div v-for="a in d.closed" :key="a.id" class="small cl"><b>{{ a.code }}</b> {{ a.description }} <span class="muted">· {{ a.responder || '' }} · {{ a.close_note || '' }}</span></div>
      </div>
    </div>
    <el-dialog v-model="raiseOpen" :title="$t('andon.raiseAndon2')" width="min(460px, 96vw)">
      <el-form label-width="80px">
        <el-form-item :label="$t('common.type')"><el-radio-group v-model="form.atype"><el-radio-button v-for="(v, k) in T" :key="k" :value="k">{{ v }}</el-radio-button></el-radio-group></el-form-item>
        <el-form-item :label="$t('common.equipment')"><RefSelect v-model="form.equipment" entity="equipment" /></el-form-item>
        <el-form-item :label="$t('andon.problemDescription')"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="raiseOpen = false">{{ $t('common.cancel') }}</el-button><el-button type="danger" @click="raise">{{ $t('andon.raised') }}</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { canWrite, get, post } from '../api';
import RefSelect from '../components/RefSelect.vue';

const router = useRouter();
const d = ref<any>(null), raiseOpen = ref(false), form = reactive<any>({ atype: 'equipment', equipment: null, description: '' });
const T: Record<string, string> = { equipment: $t('common.equipment'), quality: $t('andon.quality'), material: $t('common.material'), safety: $t('andon.safety'), other: $t('common.other') };
const writable = computed(() => canWrite($t('mesNav.productionManagement')));
async function load() { d.value = await get('/api/andon/board', true).catch(() => d.value); }
let timer: any;
onMounted(() => { load(); timer = setInterval(load, 5000); });
onUnmounted(() => clearInterval(timer));
function openRaise() { Object.assign(form, { atype: 'equipment', equipment: null, description: '' }); raiseOpen.value = true; }
async function raise() {
  if (!form.description) { ElMessage.error($t('andon.pleaseEnterAProblemDescription')); return; }
  await post('/api/e/andon', { ...form, raised_at: d.value?.now, status: 'open', source: 'manual', raised_by: '' });
  raiseOpen.value = false; ElMessage.success($t('andon.raised2')); load();
}
async function act(a: any, name: string) { await post(`/api/e/andon/${a.id}/do/${name}`, {}); load(); }
async function closeA(a: any) {
  const { value } = await ElMessageBox.prompt($t('andon.resolution'), $t('andon.close0', [a.code]), { inputValue: $t('andon.resolved') });
  await post(`/api/e/andon/${a.id}/do/close`, { note: value }); load();
}
</script>

<style scoped>
.an { border: 1px solid var(--hm-border); border-left: 4px solid var(--hm-fault); border-radius: var(--hm-r-md); padding: 8px 10px; margin-bottom: 8px; background: var(--hm-surface); }
.an.t-quality { border-left-color: var(--hm-ai-1, #6d5ae6); } .an.t-material { border-left-color: var(--hm-primary); } .an.t-safety { border-left-color: var(--hm-idle); }
.ah { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; } .desc { font-size: var(--hm-fs-sm); margin: 4px 0; color: var(--hm-text); } .btns { display: flex; gap: 6px; margin-top: 4px; }
.cl { padding: 4px 0; border-bottom: 1px dashed var(--hm-border); }
</style>
