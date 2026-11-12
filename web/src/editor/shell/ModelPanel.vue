<template>
  <div class="mp">
    <el-radio-group v-model="ed.modelTab" size="small" class="mp-tabs">
      <el-radio-button value="check">{{ $t('common.check') }} <span v-if="vErr" class="badge bad">{{ vErr }}</span><span v-else-if="vWarn" class="badge warn">{{ vWarn }}</span></el-radio-button>
      <el-radio-button value="changes">{{ $t('modelPanel.changes') }} <span v-if="ed.changes.length" class="badge">{{ ed.changes.length }}</span></el-radio-button>
      <el-radio-button value="tryrun">{{ $t('modelPanel.testRun') }}</el-radio-button>
      <el-radio-button value="history">{{ $t('modelPanel.history') }}</el-radio-button>
    </el-radio-group>
    <el-scrollbar class="mp-body">
      <template v-if="ed.modelTab === 'check'">
        <div v-for="(i, k) in ed.validation?.issues || []" :key="k" class="iss click" @click="i.id && pick(i.id)">
          <el-icon :class="i.level === 'error' ? 'bad' : 'warn'"><component :is="i.level === 'error' ? 'CircleCloseFilled' : 'WarningFilled'" /></el-icon>
          <span class="cat">{{ i.cat }}</span><span>{{ i.msg }}</span>
        </div>
        <div v-if="!(ed.validation?.issues || []).length" class="muted small">{{ $t('modelPanel.noIssuesFound') }}</div>
      </template>
      <template v-else-if="ed.modelTab === 'changes'">
        <p class="muted small">{{ $t('modelPanel.changesInTheDraftRelative') }}</p>
        <ChangeList :items="ed.changes" @pick="pick" />
        <div v-if="!ed.changes.length" class="muted small">{{ $t('modelPanel.noUnsavedChanges') }}</div>
        <el-button v-if="ed.changes.length" size="small" text type="danger" @click="discard">{{ $t('workbench.discardChanges') }}</el-button>
      </template>
      <template v-else-if="ed.modelTab === 'tryrun'">
        <div class="row"><span class="muted small">{{ $t('modelPanel.fastForwardBothTheDraft') }}</span>
          <el-select v-model="hours" size="small" style="width:90px"><el-option v-for="h in [2, 4, 8, 24]" :key="h" :value="h" :label="h + $t('common.hours2')" /></el-select>
          <el-button size="small" type="primary" :loading="busy" :disabled="!!vErr" @click="tryRun">{{ $t('modelPanel.testRun') }}</el-button></div>
        <table v-if="ed.tryrun && !busy" class="tt"><tr><th>{{ $t('common.kpi') }}</th><th v-for="r in ed.tryrun.rows" :key="r.name">{{ r.name }}</th><th>{{ $t('common.change') }}</th></tr>
          <tr v-for="k in ed.tryrun.kpis" :key="k.key"><td>{{ k.label }}</td><td v-for="r in ed.tryrun.rows" :key="r.name" class="mono">{{ fmtK(k.key, r.kpi[k.key]) }}</td>
            <td class="mono" :class="dcls(k, ed.tryrun.rows[1].delta[k.key])">{{ pctD(ed.tryrun.rows[1].delta[k.key]) }}</td></tr></table>
        <p v-for="(x, i) in (busy ? [] : ed.tryrun?.text || [])" :key="i" class="small">{{ x }}</p>
      </template>
      <template v-else>
        <div v-for="(h, i) in [...ed.undo].reverse()" :key="i" class="iss"><span class="mono muted">{{ ed.undo.length - i }}</span>{{ h.label || $t('common.edit2') }}</div>
        <div v-if="!ed.undo.length" class="muted small">{{ $t('modelPanel.noChangesYet') }}</div>
      </template>
    </el-scrollbar>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, ref } from 'vue';
import { del, P, post } from '../../api';
import ChangeList from '../ChangeList.vue';
import { blocksById, ed, focusOn, loadModel, saveDraft, select } from '../store';

const hours = ref(4), busy = ref(false);
if (!ed.modelTab) ed.modelTab = 'check';
const vErr = computed(() => ed.validation?.summary?.error || 0), vWarn = computed(() => ed.validation?.summary?.warn || 0);
const fmtK = (k: string, v: any) => (v === null || v === undefined ? '—' : k === 'scrap_rate' ? (v * 100).toFixed(2) + '%' : typeof v === 'number' ? (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(2)) : v);
const dcls = (k: any, d: any) => (d === null || d === undefined || Math.abs(d) < 0.005 ? '' : (d > 0) === (k.better > 0) ? 'up' : 'down');
const pctD = (d: any) => (d === null || d === undefined ? '—' : (d > 0 ? '+' : '') + (d * 100).toFixed(1) + '%');
function pick(id: string) {
  if (blocksById.value[id] || (ed.model.groups || []).some((g: any) => g.id === id)) { select([id]); focusOn(id); }
  else if ((ed.model.links || []).some((l: any) => l.id === id)) { ed.sel = []; ed.selLink = id; }
  else if (String(id).startsWith('path:')) { ed.view = 'plan'; setTimeout(() => focusOn(id), 300); }   // Road network issue: select and center the node/edge in the floor plan.
}
async function tryRun() {
  busy.value = true;
  try { await saveDraft(); ed.tryrun = await post(P(ed.pid) + '/model/tryrun', { model: ed.model, hours: hours.value }); } finally { busy.value = false; }
}
async function discard() {
  await ElMessageBox.confirm($t('modelPanel.discardAllUnsavedChanges'), $t('workbench.discardChanges2'), { type: 'warning' });
  await del(P(ed.pid) + '/model/draft'); await loadModel(ed.pid); ed.rebuild3d = (ed.rebuild3d || 0) + 1; ElMessage.success($t('workbench.draftDiscarded'));
}
</script>
