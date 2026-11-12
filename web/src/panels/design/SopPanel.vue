<template>
  <div class="vp sop-panel">
    <div class="vp-head">
      <span class="ttl">{{ mode === 'play' ? $t('sopPanel.trainingWalkthrough') : $t('sopPanel.sopWalkthrough') }}</span>
      <template v-if="mode === 'list'">
        <el-button size="small" type="primary" :disabled="!canEdit()" @click="addSop"><el-icon><Plus /></el-icon>{{ $t('common.new') }}</el-button>
      </template>
      <template v-else>
        <el-button size="small" text @click="stopPlay(); mode = 'list'"><el-icon><Back /></el-icon>{{ $t('sopPanel.back') }}</el-button>
      </template>
    </div>

    <!-- List -->
    <div v-if="mode === 'list'" class="vp-body">
      <div v-if="!sops.length" class="vp-empty">
        <div>{{ $t('sopPanel.noSopsYetLinkOperating') }}</div>
        <div class="vp-row" style="justify-content: center; margin-top: 10px">
          <el-button size="small" type="primary" :disabled="!canEdit()" @click="addSop"><el-icon><Plus /></el-icon>{{ $t('common.new') }}</el-button>
          <el-button size="small" @click="loadSample"><el-icon><Reading /></el-icon>{{ $t('sopPanel.viewExample') }}</el-button>
        </div>
      </div>
      <div class="vp-list">
        <div v-for="s in sops" :key="s.id" class="vp-item" :data-sop="s.id">
          <div class="vp-row sp"><span class="t">{{ s.name }}</span><span class="vp-small vp-muted">{{ $t('guides.n0Steps', [s.steps.length]) }}</span></div>
          <div class="vp-small vp-muted" v-if="s.desc">{{ s.desc }}</div>
          <div class="vp-row" style="margin-top: 6px">
            <el-button size="small" type="primary" :disabled="!s.steps.length" @click="play(s)"><el-icon><VideoPlay /></el-icon>{{ $t('sopPanel.startWalkthrough') }}</el-button>
            <el-button size="small" :disabled="!canEdit()" @click="edit(s)">{{ $t('common.edit') }}</el-button>
            <el-button size="small" text type="danger" :disabled="!canEdit()" @click="removeSop(s)">{{ $t('common.delete') }}</el-button>
          </div>
        </div>
      </div>
    </div>

    <!-- Edit -->
    <div v-else-if="mode === 'edit' && cur" class="vp-body">
      <el-form label-width="52px" size="small">
        <el-form-item :label="$t('common.name')"><el-input v-model="cur.name" /></el-form-item>
        <el-form-item :label="$t('common.description')"><el-input v-model="cur.desc" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <div class="vp-sec">
        <div class="lbl"><span>{{ $t('sopPanel.steps') }}</span><span class="grow" /><el-button size="small" text @click="addStep"><el-icon><Plus /></el-icon>{{ $t('sopPanel.addStep') }}</el-button></div>
        <div v-for="(st, i) in cur.steps" :key="st.id" class="vp-card step" :class="{ on: ei === i }" @click="ei = i">
          <div class="vp-row sp"><b>{{ i + 1 }}. {{ st.title || $t('sopPanel.untitled') }}</b>
            <span>
              <el-button size="small" text :disabled="i === 0" @click.stop="move(i, -1)"><el-icon><Top /></el-icon></el-button>
              <el-button size="small" text :disabled="i === cur.steps.length - 1" @click.stop="move(i, 1)"><el-icon><Bottom /></el-icon></el-button>
              <el-button size="small" text type="danger" @click.stop="cur.steps.splice(i, 1)"><el-icon><Delete /></el-icon></el-button>
            </span>
          </div>
          <template v-if="ei === i">
            <el-input v-model="st.title" size="small" :placeholder="$t('sopPanel.stepTitleEGConfirm')" style="margin: 4px 0" />
            <el-input v-model="st.text" type="textarea" :rows="3" size="small" :placeholder="$t('sopPanel.instructionsBasicMarkdownSupported')" />
            <div class="vp-row" style="margin-top: 4px">
              <el-select v-model="st.target.block" size="small" :placeholder="$t('sopPanel.targetEquipment')" clearable filterable style="width: 160px">
                <el-option v-for="b in blocks" :key="b.id" :value="b.id" :label="$t('common.n012', [b.name, b.id])" />
              </el-select>
              <el-button size="small" text @click="useSelection(st)" :disabled="!ed.sel?.length">{{ $t('sopPanel.useCanvasSelection') }}</el-button>
            </div>
            <div class="vp-row" style="margin-top: 4px">
              <el-input v-model="st.target.comp" size="small" :placeholder="$t('sopPanel.componentIdWithinControlUnit')" style="width: 160px" />
              <el-select v-model="st.camera.mode" size="small" style="width: 110px">
                <el-option value="orbit" :label="$t('sopPanel.orbitView')" /><el-option value="walk" :label="$t('sopPanel.firstPerson')" />
              </el-select>
            </div>
            <div class="vp-row" style="margin-top: 4px">
              <el-button size="small" text @click="recordCam(st)" :disabled="!ed.camera">{{ $t('sopPanel.captureCurrentView') }}</el-button>
              <span class="vp-small vp-muted">{{ st.camera.pos ? $t('sopPanel.captured0', [st.camera.pos.map((x: number) => x.toFixed(1)).join(', ')]) : $t('sopPanel.automaticallyFocusesOnTheTarget') }}</span>
            </div>
            <div class="vp-row" style="margin-top: 4px">
              <span class="vp-small">{{ $t('sopPanel.autoAdvance') }}</span>
              <el-input-number v-model="st.duration_s" size="small" :min="0" :max="600" controls-position="right" style="width: 110px" :placeholder="$t('debugConsole.s')" />
              <span class="vp-small vp-muted">{{ $t('sopPanel.leaveBlankToClickNext') }}</span>
            </div>
          </template>
        </div>
      </div>
      <div class="vp-row">
        <el-button size="small" type="primary" :loading="saving" @click="save">{{ $t('common.save') }}</el-button>
        <el-button size="small" @click="play(cur)" :disabled="!cur.steps.length">{{ $t('sopPanel.preview') }}</el-button>
      </div>
    </div>

    <!-- Playback -->
    <div v-else-if="mode === 'play' && cur" class="vp-body play">
      <div class="vp-small vp-muted">{{ cur.name }}</div>
      <el-progress :percentage="Math.round(((idx + 1) / cur.steps.length) * 100)" :format="() => `${idx + 1}/${cur.steps.length}`" style="margin: 6px 0" />
      <div class="vp-card">
        <div class="step-ttl">{{ idx + 1 }}. {{ step.title }}</div>
        <div class="vp-small vp-muted" v-if="step.target.block">{{ $t('sopPanel.equipment0', [nameOf(step.target.block)]) }}<template v-if="step.target.comp"> {{ $t('sopPanel.component0', [step.target.comp]) }}</template> · {{ step.camera.mode === 'walk' ? $t('sopPanel.firstPerson') : $t('sopPanel.orbitView') }}</div>
        <div class="vp-md" v-html="md(step.text || '')" style="margin-top: 6px" />
      </div>
      <div class="vp-row" style="margin-top: 10px">
        <el-button size="small" :disabled="idx === 0" @click="go(idx - 1)"><el-icon><ArrowLeft /></el-icon>{{ $t('common.back') }}</el-button>
        <el-button size="small" type="primary" v-if="idx < cur.steps.length - 1" @click="go(idx + 1)">{{ $t('common.next') }}<el-icon class="el-icon--right"><ArrowRight /></el-icon></el-button>
        <el-button size="small" type="success" v-else @click="finish">{{ $t('common.done') }}</el-button>
        <el-button size="small" text @click="togglePause">{{ ed.sop?.playing ? $t('sopPanel.pauseAutoAdvance') : $t('sopPanel.resumeAutoAdvance') }}</el-button>
      </div>
      <div class="vp-list" style="margin-top: 12px">
        <div v-for="(s, i) in cur.steps" :key="s.id" class="vp-small step-li" :class="{ on: i === idx, done: i < idx }" @click="go(i)">{{ i + 1 }}. {{ s.title }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../../i18n';
// SOP walkthrough: steps are stored at /api/p/{pid}/sop; playback state is written to ed.sop, which the 3D view (owned by the lead engineer) uses to move the camera and highlight equipment:
//   ed.sop = { id, name, index, total, playing, step: {id, title, text, target: {block, comp}, camera: {mode, pos?, look?}, duration_s}, n }
//   ed.sop = null means no playback. Increment n on each step change; also set ed.highlight = [block] and call focusOn(block).
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { canEdit, get, P, put } from '../../api';
import { md } from '../../editor/md';
import { ed, focusOn } from '../../editor/store';
import '../teach/panel.css';

const props = defineProps<{ pid: string }>();
const sops = ref<any[]>([]);
const mode = ref<'list' | 'edit' | 'play'>('list');
const cur = ref<any>(null);
const ei = ref(0);
const idx = ref(0);
const saving = ref(false);
const meta = ref<any>(null);
let timer: any = null;

const blocks = computed(() => (ed.pid === props.pid && ed.model?.blocks?.length ? ed.model.blocks : meta.value?.stations || [])
  .filter((b: any) => !['crew', 'agv'].includes(b.kind)).map((b: any) => ({ id: b.id, name: b.name })));
const step = computed(() => cur.value?.steps[idx.value] || { target: {}, camera: {} });
const nameOf = (id: string) => blocks.value.find((b: any) => b.id === id)?.name || id;
const uid = () => Math.random().toString(36).slice(2, 8);
const blankStep = () => ({ id: 's' + uid(), title: '', text: '', target: { block: null, comp: null }, camera: { mode: 'orbit' }, duration_s: null, check: { kind: 'manual' } });

async function load() {
  const [r, m] = await Promise.all([get(P(props.pid) + '/sop'), get(P(props.pid) + '/meta', true).catch(() => null)]);
  sops.value = r.sops;
  meta.value = m;
}
/** View example: demo factories have built-in SOPs; other factories generate one in equipment order. Play directly; edit and save to keep it. */
async function loadSample() {
  const smp = await get(P(props.pid) + '/sop/sample');
  for (const st of smp.steps) { st.target ||= { block: null, comp: null }; st.camera ||= { mode: 'orbit' }; }
  if (canEdit()) { cur.value = smp; ei.value = 0; mode.value = 'edit'; ElMessage.info($t('sopPanel.thisIsAnExampleClick')); }
  else play(smp);
}
function addSop() {
  cur.value = { id: 'sop' + uid(), name: $t('sopPanel.newSop'), desc: '', steps: [blankStep()] };
  ei.value = 0; mode.value = 'edit';
}
function edit(s: any) {
  cur.value = JSON.parse(JSON.stringify(s));
  for (const st of cur.value.steps) { st.target ||= { block: null, comp: null }; st.camera ||= { mode: 'orbit' }; }
  ei.value = 0; mode.value = 'edit';
}
function addStep() { cur.value.steps.push(blankStep()); ei.value = cur.value.steps.length - 1; }
function move(i: number, d: number) { const s = cur.value.steps; [s[i], s[i + d]] = [s[i + d], s[i]]; ei.value = i + d; }
function useSelection(st: any) { st.target.block = ed.sel[0]; if (!st.title) st.title = nameOf(ed.sel[0]); }
function recordCam(st: any) { if (ed.camera) st.camera = { ...st.camera, pos: [...ed.camera.pos], look: [...ed.camera.look] }; }
async function persist(list: any[]) {
  const r = await put(P(props.pid) + '/sop', { sops: list });
  sops.value = r.sops;
}
async function save() {
  saving.value = true;
  try {
    const list = sops.value.filter((s) => s.id !== cur.value.id);
    const i = sops.value.findIndex((s) => s.id === cur.value.id);
    list.splice(i < 0 ? list.length : i, 0, cur.value);
    await persist(list);
    ElMessage.success($t('common.saved'));
    mode.value = 'list';
  } finally { saving.value = false; }
}
async function removeSop(s: any) {
  await ElMessageBox.confirm($t('sopPanel.deleteSop0', [s.name]), $t('common.delete'), { type: 'warning' });
  await persist(sops.value.filter((x) => x.id !== s.id));
}

function publish(playing: boolean) {
  const st = cur.value.steps[idx.value];
  ed.sop = { id: cur.value.id, name: cur.value.name, index: idx.value, total: cur.value.steps.length, playing, step: JSON.parse(JSON.stringify(st)), n: (ed.sop?.n || 0) + 1 };
  if (st.target?.block) { ed.highlight = [st.target.block]; focusOn(st.target.block); } else ed.highlight = [];
  clearTimeout(timer);
  if (playing && st.duration_s && idx.value < cur.value.steps.length - 1) timer = setTimeout(() => go(idx.value + 1), st.duration_s * 1000);
}
function play(s: any) { cur.value = JSON.parse(JSON.stringify(s)); idx.value = 0; mode.value = 'play'; publish(true); }
function go(i: number) { idx.value = Math.max(0, Math.min(cur.value.steps.length - 1, i)); publish(ed.sop?.playing ?? true); }
function togglePause() { publish(!ed.sop?.playing); }
function stopPlay() { clearTimeout(timer); if (ed.sop) { ed.sop = null; ed.highlight = []; } }
function finish() { stopPlay(); ElMessage.success($t('sopPanel.walkthroughComplete')); mode.value = 'list'; }

watch(() => props.pid, () => { stopPlay(); mode.value = 'list'; load(); });
onMounted(load);
onBeforeUnmount(stopPlay);
</script>

<style scoped>
.step { margin-bottom: 6px; cursor: pointer; padding: 7px 9px; }
.step.on { border-color: var(--el-color-primary); }
.step-ttl { font-size: 15px; font-weight: 600; }
.step-li { padding: 4px 6px; border-radius: 4px; cursor: pointer; color: var(--el-text-color-secondary); }
.step-li.on { background: var(--el-color-primary-light-9); color: var(--el-text-color-primary); font-weight: 600; }
.step-li.done { color: var(--el-text-color-placeholder); text-decoration: line-through; }
</style>
