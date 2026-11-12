<template>
  <div class="vp report-export">
    <div class="vp-head">
      <span class="ttl">{{ $t('reportExport.exportDesignReport') }}</span>
      <el-button size="small" text @click="load"><el-icon><Refresh /></el-icon></el-button>
    </div>
    <div class="vp-body">
      <div class="vp-sec">
        <div class="lbl">{{ $t('reportExport.reportingPeriod') }}</div>
        <TimeRangePicker v-model:hours="hours" v-model:warmup="warmup" />
        <div v-if="pre" class="vp-small pre">
          <div>{{ $t('reportExport.reportingPeriodSimTime') }}<b>{{ pre.window }}</b></div>
          <div class="vp-muted">{{ $t('reportExport.theReportHeaderIncludesBoth', [pre.sim_time]) }}</div>
        </div>
      </div>
      <div class="vp-sec">
        <div class="lbl">{{ $t('reportExport.reportContents') }}</div>
        <el-checkbox-group v-model="sections" class="secs">
          <el-checkbox v-for="(label, k) in opts.sections" :key="k" :value="k">{{ label }}<span v-if="skipped[k]" class="skip" :title="skipped[k]">{{ $t('reportExport.noDataSkipped') }}</span></el-checkbox>
        </el-checkbox-group>
        <div class="vp-small vp-muted" style="margin-top:4px">{{ $t('reportExport.eachChapterIncludesServerGenerated') }}</div>
      </div>
      <div class="vp-sec" v-if="sections.includes('layout')">
        <div class="lbl">{{ $t('reportExport.layout') }}</div>
        <el-radio-group v-model="imgMode" size="small">
          <el-radio value="view">{{ $t('reportExport.currentCanvasScreenshot') }}</el-radio>
          <el-radio value="server">{{ $t('reportExport.serverGeneratedFloorPlan') }}</el-radio>
        </el-radio-group>
        <div v-if="imgMode === 'view'" class="vp-row" style="margin-top: 6px">
          <el-button size="small" @click="grab"><el-icon><Camera /></el-icon>{{ $t('reportExport.captureCurrentView') }}</el-button>
          <span class="vp-small vp-muted">{{ shot ? $t('reportExport.captured0Kb', [(shot.length / 1024 / 1.37).toFixed(0)]) : $t('reportExport.capturedAutomaticallyOnExportUses') }}</span>
        </div>
        <img v-if="shot && imgMode === 'view'" :src="shot" class="thumb" :alt="$t('reportExport.layoutScreenshot')" />
      </div>
      <div class="vp-sec" v-if="sections.includes('experiments')">
        <div class="lbl">{{ $t('reportExport.designComparisonCompletedExperiments') }}</div>
        <div v-if="!opts.experiments.length" class="vp-small vp-muted">{{ $t('reportExport.noCompletedExperimentsYetThis') }}</div>
        <el-checkbox-group v-model="exps">
          <div v-for="e in opts.experiments" :key="e.id"><el-checkbox :value="e.id">{{ e.name }}
            <span class="vp-small vp-muted">{{ $t('reportExport.n0123H', [e.kind === 'optimize' ? $t('experiments.optimize') : $t('experiments.compare'), e.variants, e.kind === 'optimize' ? $t('paretoChart.candidate') : $t('common.solution'), e.hours, e.reps]) }}</span>
            <el-tooltip v-if="e.warnings?.length" :content="e.warnings.join(' ')" placement="top" popper-class="tip-wrap"><span class="warn">{{ $t('reportExport.tooFewReplications') }}</span></el-tooltip></el-checkbox></div>
        </el-checkbox-group>
      </div>
      <div class="vp-sec">
        <div class="lbl">{{ $t('reportExport.companyTemplate') }}</div>
        <div v-for="k in (['docx', 'pptx'] as const)" :key="k" class="vp-row tpl">
          <span class="tk">{{ k === 'docx' ? 'Word' : 'PPT' }}</span>
          <span v-if="opts.templates?.[k]" class="vp-small">{{ opts.templates[k].name }} <span class="vp-muted">{{ $t('reportExport.n0Kb1', [(opts.templates[k].size / 1024).toFixed(0), opts.templates[k].uploaded?.slice(0, 16)]) }}</span></span>
          <span v-else class="vp-small vp-muted">{{ $t('reportExport.noTemplateUploadedUsingDefault') }}</span>
          <span class="grow" />
          <template v-if="edit">
            <el-button size="small" link type="primary" @click="pick(k)">{{ opts.templates?.[k] ? $t('reportExport.replace') : $t('reportExport.upload') }}</el-button>
            <el-popconfirm v-if="opts.templates?.[k]" :title="$t('reportExport.deleteThisTemplate')" @confirm="removeTpl(k)"><template #reference><el-button size="small" link type="danger">{{ $t('common.delete') }}</el-button></template></el-popconfirm>
          </template>
        </div>
        <el-checkbox v-if="opts.templates?.docx || opts.templates?.pptx" v-model="useTpl" size="small">{{ $t('reportExport.applyACompanyTemplateWhen') }}</el-checkbox>
        <div class="vp-small vp-muted">{{ $t('reportExport.useDotxDocxForWord') }}</div>
        <input ref="file" type="file" style="display:none" :accept="pickKind === 'docx' ? '.dotx,.docx' : '.potx,.pptx'" @change="upload" />
      </div>
      <div class="vp-sec">
        <div class="lbl">{{ $t('reportExport.author') }}</div>
        <el-form label-width="50px" size="small">
          <el-form-item :label="$t('reportExport.title')"><el-input v-model="title" :placeholder="$t('reportExport.defaultFactoryNameDesignReport')" /></el-form-item>
          <el-form-item :label="$t('reportExport.preparedBy')"><el-input v-model="author" :placeholder="$t('cellInspector.optional')" /></el-form-item>
        </el-form>
      </div>
    </div>
    <div class="foot">
      <div v-if="pre" class="vp-small check" :class="pre.check.ok ? 'ok' : 'bad'">
        <el-icon><component :is="pre.check.ok ? 'CircleCheck' : 'Warning'" /></el-icon>
        {{ $t('reportExport.dataCheck01Items', [pre.check.passed, pre.check.total]) }}<template v-if="!pre.check.ok">{{ $t('reportExport.n0', [pre.check.checks.filter((c: any) => !c.ok).map((c: any) => c.name).join($t('common.k344'))]) }}</template>
      </div>
      <div class="vp-row">
        <el-button type="primary" size="small" :loading="busy === 'docx'" :disabled="!sections.length" @click="exportAs('docx')"><el-icon><Document /></el-icon>{{ $t('reportExport.exportWord') }}</el-button>
        <el-button type="primary" size="small" plain :loading="busy === 'pptx'" :disabled="!sections.length" @click="exportAs('pptx')"><el-icon><Present /></el-icon>{{ $t('reportExport.exportPpt') }}</el-button>
      </div>
      <div v-if="last" class="vp-small vp-muted last" style="margin-top: 6px">{{ last }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { canEdit, del, get, P, post, session } from '../../api';
import TimeRangePicker from '../../components/TimeRangePicker.vue';
import { ed } from '../../editor/store';
import '../teach/panel.css';

const props = defineProps<{ pid: string }>();
const edit = canEdit();
const opts = reactive<any>({ sections: {}, experiments: [], templates: {} });
const sections = ref<string[]>([]);
const exps = ref<number[]>([]);
const hours = ref(24);
const warmup = ref(true);
const title = ref('');
const author = ref('');
const imgMode = ref('view');
const shot = ref('');
const busy = ref('');
const last = ref('');
const useTpl = ref(true);
const pre = ref<any>(null);
const file = ref<HTMLInputElement>();
const pickKind = ref<'docx' | 'pptx'>('docx');
const skipped = computed<Record<string, string>>(() => Object.fromEntries((pre.value?.skipped || []).map((x: any) => [x.key, x.reason])));

async function load() {
  const r = await get(P(props.pid) + '/report/export/options');
  Object.assign(opts, r);
  if (!sections.value.length) sections.value = Object.keys(r.sections);
  exps.value = r.experiments.slice(0, 3).map((e: any) => e.id);
  check();
}
const query = () => `hours=${hours.value}&warmup=${warmup.value ? 1 : 0}&sections=${sections.value.join(',')}&experiments=${exps.value.join(',')}`;
let timer: any;
function check() {
  clearTimeout(timer);
  timer = setTimeout(async () => { pre.value = await get(P(props.pid) + '/report/export/check?' + query(), true).catch(() => null); }, 250);
}

/** Capture the current canvas: use the shell's ed.capture() if available (3D or floor plan); otherwise use the largest canvas on the page (3D enables preserveDrawingBuffer). */
function capture(): string {
  try { if (typeof ed.capture === 'function') { const d = ed.capture(); if (d) return d; } } catch { /* */ }
  const cs = [...document.querySelectorAll('canvas')].filter((c) => c.width * c.height > 300 * 200).sort((a, b) => b.width * b.height - a.width * a.height);
  for (const c of cs) {
    try { const d = c.toDataURL('image/png'); if (d.length > 8000) return d; } catch { /* Cross-origin canvas */ }
  }
  return '';
}
function grab() {
  shot.value = capture();
  if (!shot.value) ElMessage.warning($t('reportExport.noCanvasAvailableForCapture'));
}

async function fetchReport(fmt: string, body: any) {
  const r = await fetch(P(props.pid) + `/report/export.${fmt}`, { method: 'POST', headers: { Authorization: 'Bearer ' + session.token, 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    return { error: typeof j.detail === 'string' ? j.detail : r.statusText, status: r.status };
  }
  return { blob: await r.blob(), headers: r.headers };
}
function save(blob: Blob, name: string) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

async function exportAs(fmt: 'docx' | 'pptx') {
  busy.value = fmt;
  try {
    let image: string | undefined;
    if (sections.value.includes('layout') && imgMode.value === 'view') image = shot.value || capture() || undefined;
    const body: any = { sections: sections.value, experiments: exps.value, hours: hours.value, warmup: warmup.value, title: title.value || undefined,
      author: author.value || undefined, image, template: useTpl.value };
    let r: any = await fetchReport(fmt, body);
    if (r.status === 409) {
      const go = await ElMessageBox.confirm(r.error, $t('reportExport.dataCheckFailed'), { confirmButtonText: $t('reportExport.exportAnyway'), cancelButtonText: $t('common.cancel'), type: 'warning' }).then(() => true).catch(() => false);
      if (!go) return;
      r = await fetchReport(fmt, { ...body, force: true });
    }
    if (r.error) { ElMessage.error(r.error); return; }
    const name = `${title.value || props.pid + $t('reportExport.designReport')}.${fmt}`;
    save(r.blob, name);
    const src = r.headers.get('X-Report-Image'), tpl = r.headers.get('X-Report-Template'), ck = r.headers.get('X-Report-Check');
    const sk = decodeURIComponent(r.headers.get('X-Report-Skipped') || '').split(',').filter(Boolean).map((k: string) => opts.sections[k] || k);
    last.value = $t('reportExport.exported01KbLayout', [name, (r.blob.size / 1024).toFixed(0), src === 'client' ? $t('reportExport.canvasScreenshot') : src === 'server' ? $t('reportExport.serverRenderedFloorPlan') : $t('common.none')])
      + $t('reportExport.n0DataCheck12', [tpl === 'company' ? $t('reportExport.companyTemplate') : $t('reportExport.defaultStyles'), ck, sk.length ? $t('reportExport.skipped0', [sk.join($t('common.k360'))]) : '']);
  } finally { busy.value = ''; }
}

function pick(k: 'docx' | 'pptx') { pickKind.value = k; setTimeout(() => file.value?.click()); }
async function upload(ev: Event) {
  const f = (ev.target as HTMLInputElement).files?.[0];
  (ev.target as HTMLInputElement).value = '';
  if (!f) return;
  const data_url = await new Promise<string>((ok, bad) => { const rd = new FileReader(); rd.onload = () => ok(String(rd.result)); rd.onerror = bad; rd.readAsDataURL(f); });
  await post('/api/report/templates', { kind: pickKind.value, name: f.name, data_url });
  ElMessage.success($t('reportExport.templateUploadedItWillBe'));
  load();
}
async function removeTpl(k: string) { await del(`/api/report/templates/${k}`); load(); }

watch(() => props.pid, load);
watch([hours, warmup, sections, exps], check, { deep: true });
onMounted(load);
</script>

<style scoped>
.secs { display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
.skip { color: var(--el-text-color-placeholder); font-size: 11px; }
.pre { margin-top: 6px; line-height: 1.7; }
.warn { margin-left: 4px; font-size: 11px; color: var(--el-color-warning); }
.tpl { gap: 8px; margin-bottom: 4px; } .tk { width: 36px; font-weight: 600; font-size: 12px; } .grow { flex: 1; }
.foot { border-top: 1px solid var(--el-border-color-lighter); padding: 8px 10px; }
.check { display: flex; align-items: flex-start; gap: 4px; margin-bottom: 6px; line-height: 1.5; }
.check.ok { color: var(--el-color-success); } .check.bad { color: var(--el-color-danger); }
.thumb { margin-top: 6px; max-width: 100%; max-height: 160px; border: 1px solid var(--el-border-color-lighter); border-radius: 4px; }
</style>
