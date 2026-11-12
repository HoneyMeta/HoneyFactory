<template>
  <div class="aid-root" :class="{ wb: inWorkbench }">
    <button v-if="!open" class="aid-pill" :title="$t('assistantDock.openAiAssistant')" @click="openPanel()"><span class="sp" aria-hidden="true" />{{ $t('common.aiAssistant') }}</button>
    <aside v-else class="aid-panel" @keydown.esc="onEsc">
      <header class="aid-h">
        <b>{{ view === 'history' ? $t('assistantDock.chatHistory') : tutor ? $t('common.aiTutor') : $t('common.aiAssistant') }}</b>
        <small class="aid-sub">{{ plantName }}</small>
        <span class="aid-grow" />
        <button class="aid-ib" :title="$t('assistantDock.newChat')" @click="newThread"><el-icon><Plus /></el-icon></button>
        <button v-if="!tutor" class="aid-ib" :class="{ on: view === 'history' }" :title="$t('assistantDock.chatHistory')" @click="toggleHistory"><el-icon><Clock /></el-icon></button>
        <button class="aid-ib" :title="$t('assistantDock.collapseEsc')" @click="open = false"><el-icon><Minus /></el-icon></button>
      </header>

      <div v-if="view === 'history'" class="aid-body">
        <div v-for="t in threads" :key="t.id" class="aid-th" :class="{ on: t.id === tid }" @click="loadThread(t.id)">
          <div class="aid-tt">
            <input v-if="renaming === t.id" v-model="renameText" class="aid-ren" @click.stop @keydown.enter="doRename(t)" @blur="doRename(t)" />
            <b v-else @dblclick.stop="startRename(t)">{{ t.title }}</b>
            <small>{{ $t('assistantDock.n01Messages', [rel(t.updated), t.count]) }}</small>
          </div>
          <button class="aid-ib" :title="$t('common.rename')" @click.stop="startRename(t)"><el-icon><EditPen /></el-icon></button>
          <button class="aid-ib" :title="$t('common.delete')" @click.stop="removeThread(t)"><el-icon><Delete /></el-icon></button>
        </div>
        <p v-if="!threads.length" class="aid-muted">{{ $t('assistantDock.noConversationsYet') }}</p>
      </div>

      <div v-else ref="list" class="aid-body">
        <div v-if="!msgs.length && tutor" class="aid-intro">
          <p>{{ $t('assistantDock.iMYourLabTutor') }}<b>{{ $t('assistantDock.andOfferHintsAndGuidance') }}</b>{{ $t('common.k266') }}</p>
          <p v-if="!tutorAid" class="aid-muted">{{ $t('assistantDock.firstOpenATaskS') }}</p>
          <div v-else class="aid-open"><span v-for="o in tutorOpeners" :key="o" @click="send(o)">{{ o }}</span></div>
        </div>
        <div v-else-if="!msgs.length" class="aid-intro">
          <p>{{ $t('assistantDock.iCanReadLiveSimulation') }}<b>{{ $t('assistantDock.iLlTestChangesOn') }}</b>{{ $t('assistantDock.showYouTheExpectedImpact') }}</p>
          <p class="aid-muted">{{ $t('assistantDock.iWonTChangeReal') }}</p>
          <div class="aid-open"><span v-for="o in openers" :key="o" @click="send(o)">{{ o }}</span></div>
        </div>
        <div v-for="(m, i) in msgs" :key="i" :class="['aid-m', m.role]">
          <template v-if="m.role === 'user'">
            <div v-if="m.ctx?.length" class="aid-ctx"><span v-for="c in m.ctx" :key="c">{{ c }}</span></div>
            <div class="aid-b">{{ m.content }}<img v-if="m.imgUrl" :src="m.imgUrl" class="aid-img" /></div>
          </template>
          <template v-else>
            <div v-if="m.content" class="aid-b md" v-html="md(m.content)" />
            <!-- 4.6 AI Tutor "Look here": click to highlight the target with the guided-tour spotlight (open panels, switch tabs, and select equipment first). -->
            <div v-if="m.points?.length" class="aid-look" data-k="tutor-points">
              <button v-for="(p, k) in m.points" :key="k" class="aid-lk" :data-key="p.key" :title="$t('assistantDock.circle') + p.label + $t('assistantDock.k274')" @click="look(p)"><el-icon><Aim /></el-icon>{{ $t('assistantDock.lookHere0', [p.label]) }}</button>
            </div>
            <div v-for="(c, k) in m.cards || []" :key="k" :class="['aid-card', c.kind]">
              <template v-if="c.kind === 'proposal'">
                <div class="aid-ch"><el-icon><EditPen /></el-icon><b>{{ c.summary }}</b></div>
                <ol class="aid-lines"><li v-for="l in c.lines.slice(0, 10)" :key="l">{{ l }}</li></ol>
                <table v-if="c.measure" class="aid-meas">
                  <tr><th>{{ $t('assistantDock.testRunFor0Hours', [c.measure.hours]) }}</th><th>{{ $t('common.current') }}</th><th>{{ $t('assistantDock.after') }}</th><th /></tr>
                  <tr v-for="r in c.measure.rows" :key="r.key"><td>{{ r.label }}</td><td>{{ num(r.before, r.key) }}</td><td>{{ num(r.after, r.key) }}</td>
                    <td :class="r.good === true ? 'up' : r.good === false ? 'down' : ''">{{ r.delta === null ? '' : (r.delta > 0 ? '+' : '') + (r.delta * 100).toFixed(1) + '%' }}</td></tr>
                </table>
                <div v-if="c.measure" class="aid-muted small">{{ $t('assistantDock.bottleneck01', [c.measure.bottleneck_before, c.measure.bottleneck_after]) }}</div>
                <div v-for="w in c.warn || []" :key="w" class="aid-warn">{{ $t('assistantDock.note0', [w]) }}</div>
                <div class="aid-btns">
                  <template v-if="!c.applied">
                    <button v-if="aiCtx.highlight" @click="aiCtx.highlight(ids(c.ops))">{{ $t('assistantDock.markOnGraph') }}</button>
                    <button class="pri" :disabled="c.busy" @click="commit(c)">{{ $t('assistantDock.applyToDraft') }}</button>
                  </template>
                  <template v-else><span class="ok">{{ $t('assistantDock.appliedToDraft') }}</span><button v-if="c.undoAt" @click="revert(c)">{{ $t('workbench.undo') }}</button></template>
                </div>
              </template>
              <template v-else-if="c.kind === 'wrote'">
                <div class="aid-ch"><span class="ok">✓</span><b>{{ c.summary }}</b></div>
                <div v-for="l in c.lines" :key="l" class="aid-line">{{ l }}</div>
              </template>
              <template v-else-if="c.kind === 'plc'">
                <div class="aid-ch"><el-icon><Cpu /></el-icon><b>{{ c.summary }}</b></div>
                <div v-for="l in c.lines" :key="l" class="aid-muted small">{{ l }}</div>
                <details class="aid-code"><summary>{{ $t('assistantDock.viewProgram') }}</summary><pre>{{ c.program?.source }}</pre></details>
                <div class="aid-btns">
                  <button v-if="!c.done" class="pri" :disabled="c.busy" @click="downloadPlc(c)">{{ $t('assistantDock.downloadToPlcAndRun') }}</button>
                  <template v-else><span class="ok">✓ {{ c.done }}</span><button @click="openPanel2('plc-editor-float')">{{ $t('workbench.openPlcProgramming') }}</button></template>
                </div>
              </template>
              <template v-else-if="c.kind === 'went'">
                <span class="aid-went" @click="go(c)">{{ $t('assistantDock.navigatedTo0', [c.why]) }}</span>
              </template>
              <template v-else-if="c.kind === 'action'">
                <div class="aid-ch"><el-icon><component :is="c.type === 'scenario' ? 'VideoPlay' : 'DataAnalysis'" /></el-icon>
                  <b>{{ $t('common.n01', [c.type === 'scenario' ? $t('common.scenario') : $t('assistantDock.experiment'), c.payload.name]) }}</b></div>
                <div class="aid-muted small">{{ c.type === 'scenario' ? $t('assistantDock.n01Steps', [c.payload.descr || '', (c.payload.steps || []).length]) : (c.payload.variants || []).map((v: any) => v.name).join(' / ') }}</div>
                <div class="aid-btns">
                  <template v-if="!c.done">
                    <button v-if="c.type === 'scenario'" @click="saveScenario(c, false)">{{ $t('common.save') }}</button>
                    <button v-if="c.type === 'scenario'" class="pri" @click="saveScenario(c, true)">{{ $t('assistantDock.saveAndRun') }}</button>
                    <button v-else class="pri" @click="startExperiment(c)">{{ $t('assistantDock.startExperiment') }}</button>
                  </template>
                  <template v-else><span class="ok">✓ {{ c.done }}</span><button @click="router.push(`/p/${plant}/${c.type === 'scenario' ? 'scenarios' : 'experiments'}`)">{{ $t('assistantDock.view') }}</button></template>
                </div>
              </template>
            </div>
          </template>
        </div>
        <div v-if="busy" class="aid-prog"><el-icon class="is-loading"><Loading /></el-icon>{{ progress || $t('assistantDock.thinking') }}</div>
        <div v-if="err" class="aid-err">{{ err }}</div>
      </div>

      <footer v-if="view === 'chat'" class="aid-in">
        <div v-if="aiCtx.names.length" class="aid-ctx sm"><span v-for="n in aiCtx.names.slice(0, 5)" :key="n">{{ n }}</span><i v-if="aiCtx.names.length > 5">{{ $t('assistantDock.and0More', [aiCtx.names.length]) }}</i></div>
        <div class="aid-row">
          <img v-if="image" :src="image" class="aid-img sm" :title="$t('assistantDock.clickToRemove')" @click="image = ''" />
          <textarea ref="ta" v-model="text" rows="2" :disabled="busy" :placeholder="tutor ? $t('assistantDock.describeWhatHappenedEG') : $t('assistantDock.askAQuestionOrDescribe')"
            @keydown="onKey" @paste="onPaste" />
          <button class="aid-send" :disabled="busy || (!text.trim() && !image)" @click="send()"><el-icon><Promotion /></el-icon></button>
        </div>
      </footer>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { del, get, P, patch, post, put, session } from '../api';
import { aiCtx, streamEvents } from '../assistant';
import { md } from '../editor/md';
import { applyOps, ed } from '../editor/store';

const route = useRoute(), router = useRouter();
const open = ref(localStorage.getItem('vf_ai_open') === '1');
const tid = ref<number | null>(Number(localStorage.getItem('vf_ai_thread')) || null);
const view = ref<'chat' | 'history'>('chat');
const msgs = ref<any[]>([]), threads = ref<any[]>([]);
const text = ref(''), image = ref(''), busy = ref(false), progress = ref(''), err = ref('');
const list = ref<HTMLElement>(), ta = ref<HTMLTextAreaElement>();
const renaming = ref<number | null>(null), renameText = ref('');

const plant = computed(() => (route.params.pid as string) || aiCtx.plant || localStorage.getItem('vf_last_plant') || session.plants[0]?.id || '');
const plantName = computed(() => session.plants.find((p: any) => p.id === plant.value)?.name || '');
const inWorkbench = computed(() => route.path.includes('/workbench'));
const OPENERS: Record<string, string[]> = {
  workbench: [$t('assistantDock.whereIsTheCurrentBottleneck'), $t('assistantDock.whyHasOutputDroppedOver'), $t('assistantDock.pauseAutomaticallyWhenMachiningCente')],
  plan: [$t('assistantDock.canNextWeekSOrders'), $t('assistantDock.howMuchDoesChangeoverTime')],
  scenarios: [$t('assistantDock.createAScenarioWithA'), $t('assistantDock.whatIsEachOfThese')],
  experiments: [$t('assistantDock.designAnExperimentToSee'), $t('assistantDock.interpretTheLatestExperimentResults')],
  reports: [$t('assistantDock.summarizeTheThreeKeyPoints'), $t('assistantDock.whatAreTheMainCauses')],
};
const openers = computed(() => {
  if (aiCtx.names.length) return [$t('assistantDock.howIs0DoingNow', [aiCtx.names[0]]), $t('assistantDock.reduceTheCycleTimeOf', [aiCtx.names[0]]), $t('assistantDock.pauseWhen0Fails', [aiCtx.names[0]])];
  const k = Object.keys(OPENERS).find((x) => route.path.includes('/' + x)) || 'workbench';
  return OPENERS[k];
});
const TOOL_HINT: Record<string, string> = { try_changes: $t('assistantDock.testingOnACopy'), get_report: $t('assistantDock.reviewingReports'), get_runtime: $t('assistantDock.readingLiveStatus') };

watch(open, (v) => { localStorage.setItem('vf_ai_open', v ? '1' : '0'); if (v) nextTick(() => { ta.value?.focus(); scroll(); }); });
watch(tid, (v) => localStorage.setItem('vf_ai_thread', v ? String(v) : ''));

function scroll() { nextTick(() => { if (list.value) list.value.scrollTop = list.value.scrollHeight; }); }
function rel(t: string) {
  const d = (Date.now() - new Date(t.replace(' ', 'T')).getTime()) / 60000;
  return d < 1 ? $t('common.justNow') : d < 60 ? $t('common.n0MinAgo', [Math.round(d)]) : d < 1440 ? $t('common.n0HoursAgo', [Math.round(d / 60)]) : t.slice(0, 10);
}
const num = (v: any, k: string) => (v === null || v === undefined ? '—' : k === 'scrap_rate' ? (v * 100).toFixed(2) + '%' : Math.abs(v) >= 100 ? Math.round(v) : (+v).toFixed(2));
const ids = (ops: any[]) => [...new Set(ops.flatMap((o: any) => [o.block?.id, o.link?.id, o.link?.from, o.link?.to, o.id]).filter(Boolean))] as string[];

async function openPanel() { open.value = true; if (!tutor.value && tid.value && !msgs.value.length) await loadThread(tid.value, false); }
async function newThread() { tid.value = null; msgs.value = []; view.value = 'chat'; err.value = ''; nextTick(() => ta.value?.focus()); }
async function toggleHistory() { view.value = view.value === 'history' ? 'chat' : 'history'; if (view.value === 'history') threads.value = await get('/api/assistant/threads', true).catch(() => []); }
async function loadThread(id: number, switchView = true) {
  try {
    const t = await get('/api/assistant/threads/' + id, true);
    tid.value = id; msgs.value = t.messages.map((m: any) => ({ ...m, cards: (m.cards || []).map((c: any) => ({ ...c, applied: c.applied ?? c.kind !== 'proposal' })) }));
    if (switchView) view.value = 'chat';
    scroll();
  } catch { tid.value = null; msgs.value = []; }
}
function startRename(t: any) { renaming.value = t.id; renameText.value = t.title; }
async function doRename(t: any) { if (renaming.value !== t.id) return; renaming.value = null; if (renameText.value.trim() && renameText.value !== t.title) { await patch('/api/assistant/threads/' + t.id, { title: renameText.value }); t.title = renameText.value; } }
async function removeThread(t: any) {
  await ElMessageBox.confirm($t('assistantDock.deleteConversation0', [t.title]), $t('assistantDock.deleteConversation'), { type: 'warning' });
  await del('/api/assistant/threads/' + t.id); threads.value = threads.value.filter((x) => x.id !== t.id);
  if (tid.value === t.id) newThread();
}
function onEsc() { if (view.value === 'history') view.value = 'chat'; else open.value = false; }
function onKey(e: KeyboardEvent) { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } }
function onPaste(e: ClipboardEvent) {
  const f = [...(e.clipboardData?.files || [])].find((x) => x.type.startsWith('image/'));
  if (f) { e.preventDefault(); const rd = new FileReader(); rd.onload = () => (image.value = String(rd.result)); rd.readAsDataURL(f); }
}

// Students use the AI Tutor (/api/tutor/ask, hints only); the general assistant is disabled for student accounts
const tutor = computed(() => session.user?.role === 'student');
const tutorAid = computed(() => ed.teach?.assignment || Number(String(route.params.pid || '').match(/^sb-.+-(\d+)$/)?.[1]) || 0);
const tutorOpeners = [$t('assistantDock.whyIsnTMyProgram'), $t('assistantDock.whereShouldIStartWith'), $t('assistantDock.helpMeUnderstandWhereI')];
async function askTutor(q: string) {
  if (!q || busy.value) return;
  if (!tutorAid.value) { err.value = $t('assistantDock.openALabTaskFirst'); return; }
  const history = msgs.value.slice(-8).map((m: any) => ({ role: m.role, content: m.content }));
  msgs.value.push({ role: 'user', content: q });
  msgs.value.push({ role: 'assistant', content: '', cards: [] });
  const sl = msgs.value[msgs.value.length - 1];
  text.value = ''; busy.value = true; progress.value = $t('assistantDock.theTutorIsReviewingYour'); err.value = ''; scroll();
  // No answer after 15 seconds: show the task's first hint so students aren't left waiting
  const slow = setTimeout(async () => {
    if (sl.content) return;
    const h = await get(`/api/tutor/hint?assignment_id=${tutorAid.value}`, true).catch(() => null);
    if (h?.hint && !sl.content) progress.value = $t('assistantDock.theTutorIsStillThinking', [h.hint]);
  }, 15000);
  try {
    const r = await post('/api/tutor/ask', { assignment_id: tutorAid.value, question: q, history });
    sl.content = r.answer + (r.filtered ? $t('assistantDock.theTutorOnlyProvidesHints') : '');
    sl.points = Array.isArray(r.points) ? r.points.slice(0, 3) : [];
  } catch (e: any) { err.value = $t('assistantDock.theTutorCouldnTAnswer') + e.message; } finally { clearTimeout(slow); busy.value = false; progress.value = ''; scroll(); }
}

async function send(prompt?: string, fresh = false) {
  if (tutor.value) return askTutor((prompt ?? text.value).trim());
  const q = (prompt ?? text.value).trim();
  if ((!q && !image.value) || busy.value || !plant.value) return;
  if (fresh) { tid.value = null; msgs.value = []; }
  view.value = 'chat'; err.value = '';
  if (!tid.value) tid.value = (await post('/api/assistant/threads', { plant: plant.value })).id;
  const ctx = [...aiCtx.names];
  const img = image.value;
  msgs.value.push({ role: 'user', content: q || $t('assistantDock.viewImage'), ctx, imgUrl: img });
  const slot: any = { role: 'assistant', content: '', cards: [] };
  msgs.value.push(slot);
  const sl = msgs.value[msgs.value.length - 1];
  text.value = ''; image.value = ''; busy.value = true; progress.value = ''; scroll();
  try {
    await streamEvents(`/api/assistant/threads/${tid.value}/message`, {
      plant: plant.value, message: q, ctx, page: route.path, view: aiCtx.view, selection: aiCtx.selection, replay_time: aiCtx.replayTime,
      model: aiCtx.getModel ? aiCtx.getModel() : undefined, image: img || undefined,
    }, (kind, d) => {
      if (kind === 'tool') progress.value = d.phrase || TOOL_HINT[d.tool] || $t('assistantDock.processing');
      else if (kind === 'proposal') { sl.cards.push({ ...d, applied: false }); aiCtx.highlight?.(ids(d.ops)); }
      else if (kind === 'wrote') { const c = { ...d }; sl.cards.push(c); if (d.ops?.length) applyLocal(c); if (d.breakpoint) window.dispatchEvent(new CustomEvent('vf:breakpoints-changed')); }
      else if (kind === 'action' || kind === 'plc') sl.cards.push({ ...d });
      else if (kind === 'navigate') { const c = { kind: 'went', ...d }; sl.cards.push(c); go(c); }
      else if (kind === 'answer') sl.content = d.text;
      else if (kind === 'error') err.value = d.msg;
      scroll();
    });
  } catch (e: any) { err.value = $t('assistantDock.couldNotComplete') + e.message; } finally { busy.value = false; progress.value = ''; scroll(); }
}

/** Apply changes to the draft as one step: use the command bus in the Workbench (undoable); otherwise edit the draft file directly. */
async function applyLocal(c: any) {
  if (aiCtx.apply) { aiCtx.apply(c.ops, $t('assistantDock.ai') + (c.summary || $t('common.edit2'))); c.applied = true; c.undoAt = (window as any).__vfUndoDepth?.() || 0; return; }
  const r = await get(P(plant.value) + '/model'); applyOps(r.model, c.ops); await put(P(plant.value) + '/model', { model: r.model });
  c.applied = true; ElMessage.success($t('assistantDock.changesSavedToTheDraft'));
}
async function commit(c: any) {
  c.busy = true;
  try {
    const model = aiCtx.getModel ? aiCtx.getModel() : (await get(P(plant.value) + '/model')).model;
    const r = await post('/api/assistant/commit', { model, ops: c.ops, token: c.token, thread: tid.value });
    await applyLocal(c);
    c.lines = r.lines;
    if (tid.value) ElMessage.success($t('assistantDock.changesSavedToTheDraft2'));
  } catch { /* Error already shown (e.g. model changed after the trial run) */ } finally { c.busy = false; }
}
function revert(c: any) {
  const depth = (window as any).__vfUndoDepth?.();
  if (depth !== c.undoAt) { ElMessage.warning($t('assistantDock.otherChangesHaveBeenMade')); return; }
  (window as any).__vfUndo?.(); c.applied = false; c.undoAt = 0;
  if (tid.value && c.token) post(`/api/assistant/threads/${tid.value}/card`, { token: c.token, applied: false });
}
function go(c: any) {
  if (c.path && route.path !== c.path) router.push(c.path).then(() => setTimeout(() => aiCtx.navigate?.(c), 1200));
  else aiCtx.navigate?.(c);
}
async function saveScenario(c: any, run: boolean) {
  const r = await post(P(plant.value) + '/scenarios', c.payload);
  if (run) { await post(P(plant.value) + '/scenarios/run', { id: r.id }); c.done = $t('assistantDock.theScenarioIsNowRunning'); } else c.done = $t('assistantDock.scenarioSaved');
}
async function downloadPlc(c: any) {
  c.busy = true;
  try {
    const r = await post(`${P(plant.value)}/cells/${encodeURIComponent(c.cell)}/program/download`, { program: c.program, run: true });
    if (r.ok === false) { err.value = $t('assistantDock.downloadFailed') + (r.errors || []).map((e: any) => e.msg).join($t('common.k344')); return; }
    c.done = $t('assistantDock.downloadedTo01', [c.cell_name || c.cell, r.state === 'RUN' ? $t('assistantDock.running') : r.state]);
  } finally { c.busy = false; }
}
/** "Look here": spotlight the target; collapse the assistant panel if it obscures the target (chat is preserved; reopen at bottom right). */
async function look(p: any) {
  const t = await import('../panels/teach/tour/tour');
  await t.pointAt({ label: p.label, text: p.text || $t('assistantDock.theAiTutorWantsYou'), target: p.target, goto: p.goto, plc: p.plc,
    pid: (route.params.pid as string) || ed.pid });
  const h = t.resolveTarget(p.target), box = document.querySelector('.aid-panel')?.getBoundingClientRect();
  if (h && box && h.rect.right > box.left && h.rect.left < box.right && h.rect.bottom > box.top && h.rect.top < box.bottom) open.value = false;
}
function openPanel2(id: string) { window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id } })); }
async function startExperiment(c: any) { await post(P(plant.value) + '/experiments', { reps: 2, hours: 24, ...c.payload }); c.done = $t('assistantDock.theExperimentHasStartedIn'); }

function onAsk(e: any) { open.value = true; nextTick(() => send(e.detail.prompt, true)); }
function onToggle() { if (open.value) open.value = false; else openPanel(); }
onMounted(() => { addEventListener('vf:assistant-ask', onAsk); addEventListener('vf:assistant-toggle', onToggle); if (open.value && tid.value && !tutor.value) loadThread(tid.value, false); });
onUnmounted(() => { removeEventListener('vf:assistant-ask', onAsk); removeEventListener('vf:assistant-toggle', onToggle); });
</script>

<style>
/* 5.0.1: match HoneyMOM's AI button / panel (white pill + cyan→blue→purple gradient border and star icon; white panel with thin border, cobalt-blue primary action) */
.aid-root { position: fixed; right: 22px; bottom: 22px; z-index: 2000; font-size: var(--hm-fs-sm); }
.aid-root.wb { bottom: 34px; }
.aid-pill { display: inline-flex; align-items: center; gap: 6px; height: 34px; padding: 0 14px 0 12px; border-radius: var(--hm-r-pill); cursor: pointer; font: inherit; font-weight: 700; font-size: 12.5px; letter-spacing: .06em;
  color: var(--hm-primary-press); border: 1px solid transparent; background: linear-gradient(#fff, #fff) padding-box, var(--hm-ai-grad) border-box; box-shadow: var(--hm-e2);
  transition: box-shadow var(--hm-dur-2) var(--hm-ease), transform var(--hm-dur-2) var(--hm-ease); }
.aid-pill:hover { box-shadow: var(--hm-e3); transform: translateY(-1px); }
.aid-pill:active { background: var(--hm-ai-grad) border-box; color: #fff; } .aid-pill:active .sp { background: #fff; }
.aid-pill .sp { width: 14px; height: 14px; background: var(--hm-ai-grad); clip-path: polygon(50% 0, 62% 38%, 100% 50%, 62% 62%, 50% 100%, 38% 62%, 0 50%, 38% 38%); flex: none; }
.aid-panel { width: min(400px, calc(100vw - 30px)); height: min(600px, calc(100vh - 80px)); display: flex; flex-direction: column; background: var(--hm-surface); color: var(--hm-text);
  border: 1px solid var(--hm-border); border-radius: var(--hm-r-lg); box-shadow: var(--hm-e3); overflow: hidden; position: relative; }
.aid-panel::before { content: ''; position: absolute; left: 0; right: 0; top: 0; height: 2px; background: var(--hm-ai-grad); }
.aid-h { display: flex; align-items: center; gap: 6px; padding: 9px 10px; border-bottom: 1px solid var(--hm-border); background: var(--hm-surface-2); }
.aid-h b { font-size: var(--hm-fs-md); } .aid-sub { color: var(--hm-text-3); } .aid-grow { flex: 1; }
.aid-ib { border: 0; background: transparent; width: 26px; height: 26px; border-radius: var(--hm-r-sm); cursor: pointer; color: var(--hm-text-2); display: inline-flex; align-items: center; justify-content: center; }
.aid-ib:hover, .aid-ib.on { background: var(--hm-surface-3); color: var(--hm-text); }
.aid-body { flex: 1; overflow: auto; padding: 10px 12px; }
.aid-intro { line-height: 1.7; color: var(--hm-text-2); } .aid-muted { color: var(--hm-text-3); } .aid-muted.small, .small { font-size: 11.5px; }
.aid-open { display: flex; flex-direction: column; gap: 6px; margin-top: 8px; } .aid-open span { border: 1px solid var(--hm-border); border-radius: var(--hm-r-md); padding: 6px 10px; cursor: pointer; background: var(--hm-surface); }
.aid-open span:hover { border-color: var(--el-color-primary-light-5); background: var(--hm-ai-soft); }
.aid-m { margin-bottom: 12px; } .aid-m.user { display: flex; flex-direction: column; align-items: flex-end; }
.aid-b { padding: 7px 10px; border-radius: var(--hm-r-md); line-height: 1.65; max-width: 100%; word-break: break-word; }
.aid-m.user .aid-b { background: var(--hm-primary-soft); border: 1px solid var(--hm-primary-soft-2); white-space: pre-wrap; }
.aid-m.assistant .aid-b { background: var(--hm-surface-2); border: 1px solid var(--hm-border); }
.aid-b.md p { margin: 3px 0; } .aid-b.md ul { margin: 3px 0; padding-left: 18px; } .aid-b.md code { background: var(--hm-surface-3); padding: 0 4px; border-radius: 3px; font-family: var(--hm-font-mono); }
.aid-b.md .mh { font-weight: 700; margin: 6px 0 2px; } .aid-b.md .mt { display: flex; gap: 8px; font-size: 12px; } .aid-b.md .mt span { flex: 1; }
.aid-ctx { display: flex; flex-wrap: wrap; gap: 4px; margin-bottom: 3px; justify-content: flex-end; } .aid-ctx span { font-size: 11px; padding: 0 7px; border-radius: var(--hm-r-pill); background: var(--hm-ai-soft); color: var(--hm-setup-ink); }
.aid-ctx.sm { justify-content: flex-start; margin: 0 0 4px; } .aid-ctx i { font-size: 11px; color: var(--hm-text-3); font-style: normal; }
.aid-img { max-width: 140px; max-height: 90px; border-radius: var(--hm-r-sm); display: block; margin-top: 4px; } .aid-img.sm { max-width: 60px; max-height: 44px; cursor: pointer; }
.aid-card { margin-top: 8px; border-radius: var(--hm-r-md); padding: 8px 10px; border: 1px solid var(--hm-border); background: var(--hm-surface); }
.aid-card.proposal { border-color: var(--hm-primary-soft-2); background: var(--hm-ai-soft); }
.aid-card.wrote { border: 0; border-left: 3px solid var(--hm-run); background: var(--hm-run-soft); border-radius: var(--hm-r-xs); }
.aid-card.went { border: 0; padding: 0; background: none; }
.aid-ch { display: flex; align-items: center; gap: 6px; } .aid-ch b { font-size: 13px; }
.aid-lines { margin: 6px 0; padding-left: 18px; font-size: 12px; line-height: 1.6; } .aid-line { font-size: 12px; padding-left: 16px; }
.aid-meas { width: 100%; border-collapse: collapse; font-size: 12px; margin: 4px 0; } .aid-meas th { text-align: left; color: var(--hm-text-3); font-weight: 500; }
.aid-meas td, .aid-meas th { padding: 2px 4px; border-bottom: 1px solid var(--hm-border); font-variant-numeric: tabular-nums; } .aid-meas .up { color: var(--hm-run-ink); } .aid-meas .down { color: var(--hm-fault-ink); }
.aid-warn { font-size: 11.5px; color: var(--hm-idle-ink); }
.aid-btns { display: flex; gap: 6px; align-items: center; margin-top: 6px; }
.aid-btns button { border: 1px solid var(--el-border-color); background: var(--hm-surface); border-radius: var(--hm-r-sm); padding: 3px 10px; cursor: pointer; font-size: 12px; color: var(--hm-text); }
.aid-btns button:hover:not(:disabled) { border-color: var(--el-color-primary-light-5); color: var(--hm-primary); }
.aid-btns button.pri, .aid-btns button.pri:hover:not(:disabled) { background: var(--hm-primary); border-color: var(--hm-primary); color: #fff; } .aid-btns button.pri:hover:not(:disabled) { background: var(--hm-primary-hover); }
.aid-btns button:disabled { opacity: .5; }
.aid-code summary { cursor: pointer; font-size: 12px; color: var(--hm-primary); } .aid-code pre { max-height: 220px; overflow: auto; font-size: 11.5px; background: var(--hm-surface-2); border: 1px solid var(--hm-border); padding: 6px; border-radius: var(--hm-r-sm); font-family: var(--hm-font-mono); }
.aid-look { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.aid-lk { display: inline-flex; align-items: center; gap: 4px; border: 1px solid var(--hm-primary-soft-2); background: var(--hm-primary-soft); color: var(--hm-setup-ink); border-radius: var(--hm-r-pill); padding: 3px 10px; cursor: pointer; font-size: 12px; }
.aid-lk:hover { background: var(--hm-primary-soft-2); border-color: var(--hm-primary); color: var(--hm-primary-press); }
.aid-went { font-size: 12px; color: var(--hm-primary); cursor: pointer; text-decoration: underline dotted; }
.ok { color: var(--hm-run-ink); }
.aid-prog { display: flex; align-items: center; gap: 6px; color: var(--hm-text-3); font-size: 12.5px; }
.aid-err { color: var(--hm-fault-ink); font-size: 12.5px; margin-top: 6px; }
.aid-th { display: flex; align-items: center; gap: 4px; padding: 7px 6px; border-radius: var(--hm-r-md); cursor: pointer; } .aid-th:hover, .aid-th.on { background: var(--hm-surface-3); }
.aid-tt { flex: 1; min-width: 0; display: flex; flex-direction: column; } .aid-tt b { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aid-tt small { color: var(--hm-text-3); font-size: 11px; } .aid-ren { font: inherit; padding: 2px 4px; }
.aid-in { border-top: 1px solid var(--hm-border); padding: 8px 10px; }
.aid-row { display: flex; gap: 6px; align-items: flex-end; }
.aid-row textarea { flex: 1; resize: none; border: 1px solid var(--el-border-color); border-radius: var(--hm-r-md); padding: 6px 8px; font: inherit; max-height: 120px; background: var(--hm-surface); color: inherit; }
.aid-row textarea:focus { outline: none; border-color: var(--hm-primary); box-shadow: 0 0 0 2px rgba(20, 99, 214, .15); }
.aid-send { border: 0; background: var(--hm-primary); color: #fff; border-radius: var(--hm-r-md); width: 34px; height: 34px; cursor: pointer; } .aid-send:hover:not(:disabled) { background: var(--hm-primary-hover); } .aid-send:disabled { opacity: .45; }
</style>