<template>
  <el-dialog v-model="show" :title="isPlantFile ? $t('packageOpen.factoryFile') : $t('packageOpen.assignmentPackage')" width="560px" append-to-body>
    <div v-if="err" class="vp-fail">{{ err }}</div>
    <div v-else-if="!info" class="vp-muted vp-small">{{ $t('common.loading') }}</div>
    <template v-else>
      <div class="vp-kv pk-kv">
        <span>{{ $t('common.working') }}</span><span><b>{{ info.title || info.task_name || '—' }}</b></span>
        <span>{{ $t('common.student') }}</span><span>{{ info.student?.name || '—' }}{{ info.student?.username ? $t('common.k459') + info.student.username + $t('common.k460') : '' }}</span>
        <span>{{ $t('common.type') }}</span><span>{{ KIND_CN[info.kind] || info.kind }}{{ info.course ? $t('packageOpen.course') + info.course + ' / ' + info.lesson : info.scene ? $t('packageOpen.scenario') + info.scene : '' }}</span>
        <span>{{ $t('packageOpen.schoolServer') }}</span><span>{{ info.server || $t('packageOpen.exportedFromLocalPractice') }}{{ info.assignment_id ? $t('packageOpen.assignmentId') + info.assignment_id : '' }}</span>
        <span>{{ $t('packageOpen.exportTime') }}</span><span>{{ info.created }}{{ info.client_version ? $t('packageOpen.desktopClient') + info.client_version : '' }}</span>
        <span v-if="info.plant">{{ $t('common.factory') }}</span><span v-if="info.plant">{{ $t('packageOpen.n0Objects1Plc2', [info.plant.name, info.plant.blocks, (info.plant.plcs || []).join($t('common.k360')) || $t('common.none')]) }}</span>
        <span>{{ $t('common.content') }}</span><span>{{ info.cells.length ? $t('packageOpen.plcProgram') + info.cells.join($t('common.k360')) + ' ' : '' }}{{ info.has_model ? (info.kind === 'factory' ? $t('packageOpen.factoryModel') : $t('packageOpen.lineModel')) : '' }}{{ info.answers ? $t('packageOpen.answers') + info.answers + $t('packageOpen.questions') : '' }} · {{ (info.size / 1024).toFixed(1) }} KB</span>
        <span>{{ $t('packageOpen.localEstimatedScore') }}</span><span>{{ info.local_score?.score ?? '—' }}<span class="vp-small vp-muted">{{ $t('packageOpen.calculatedOnTheStudentS') }}</span></span>
      </div>
      <div v-if="!info.runnable" class="vp-fail vp-small" style="margin-top: 8px">{{ info.why }}</div>
      <div v-else-if="student && notMine" class="vp-fail vp-small" style="margin-top: 8px" data-k="pkg-not-mine">{{ $t('packageOpen.thisAssignmentPackageBelongsTo') }}</div>
      <div v-else-if="student && info.kind === 'factory'" class="vp-small vp-muted" style="margin-top: 8px">{{ $t('packageOpen.openingThisPackageImportsThe') }}</div>
      <div v-else-if="student" class="vp-small vp-muted" style="margin-top: 8px">{{ $t('packageOpen.whenOpened0FromThe', [info.kind === 'cell' ? $t('packageOpen.thePlcProgramWillBe') : $t('packageOpen.theModelWillBeLoaded')]) }}</div>
    </template>
    <template #footer>
      <el-button size="small" @click="show = false">{{ $t('common.close') }}</el-button>
      <el-button size="small" type="primary" :disabled="!info?.runnable || (student && notMine)" :loading="busy" data-k="pkg-run" @click="run">
        <el-icon><VideoPlay /></el-icon>{{ student ? (info?.kind === 'factory' ? $t('packageOpen.importToMyFactories') : $t('packageOpen.loadIntoMySandboxAnd')) : $t('packageOpen.openAndRunLocally') }}</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// Open .vfhw in the desktop client: the launcher passes ?open=<path> (desk.openPath) on double-click, or select a file in "My Courses"/Teaching. Show assignment info from the package:
// Teachers (and local admins in standalone mode) run it in a local review sandbox; students can only open their own packages into their assignment sandbox to continue (emit own; the course panel opens the lesson).
import { computed, ref } from 'vue';
import { ElMessage } from 'element-plus';
import { post, session } from '../../api';
import { ed } from '../../editor/store';
import './panel.css';

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'own', r: any): void }>();
const student = computed(() => session.user?.role === 'student');
const notMine = computed(() => !!info.value?.student?.username && info.value.student.username !== session.user?.username);
const show = computed({ get: () => props.modelValue, set: (v) => emit('update:modelValue', v) });
const KIND_CN: Record<string, string> = { cell: $t('packageOpen.plcControl'), plant: $t('common.line'), diagnose: $t('common.troubleshooting'), factory: $t('packageOpen.factoryDesignEntireFactory') };
const isPlantFile = computed(() => String(info.value?.path || '').toLowerCase().endsWith('.vfplant'));   // Double-click .vfplant (exported factory file).
const info = ref<any>(null);
const err = ref('');
const busy = ref(false);

async function openWith(body: any) {
  info.value = null; err.value = ''; show.value = true;
  try { info.value = await post('/api/client/open_package', body); } catch (e: any) { err.value = e.message; }
}
const openPath = (path: string) => openWith({ path });
async function openFile(f: File) {
  const b64 = await new Promise<string>((ok) => { const rd = new FileReader(); rd.onload = () => ok(String(rd.result)); rd.readAsDataURL(f); });
  await openWith({ data: b64 });
}
async function run() {
  busy.value = true;
  try {
    const r = await post(`/api/client/packages/${info.value.id}/run`, {});
    show.value = false;
    if (r.own) { ElMessage.success(r.msg || $t('packageOpen.loadedIntoYourSandbox')); emit('own', r); return; }
    ed.teach = { ...(ed.teach || {}), pid: r.pid, review: true, kind: r.kind || ed.teach?.kind, open: { pid: r.pid, bid: r.bid, readonly: false, review: true, n: Date.now() } };
    if (!ed.teach.handled) {
      const { router } = await import('../../router');
      router.push(`/p/${encodeURIComponent(r.pid)}/workbench`);
    }
  } finally { busy.value = false; }
}
defineExpose({ openPath, openFile });
</script>

<style scoped>
.pk-kv { grid-template-columns: 90px 1fr; row-gap: 6px; }
</style>
