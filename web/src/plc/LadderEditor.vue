<template>
  <div class="lde" :class="{ online: isOnline, dragging: !!drag }">
    <!-- Instruction toolbar: click to insert at the selection, or drag onto a rung -->
    <div v-if="ro" class="lde-ro">{{ $t('ladderEditor.readOnlyYouCanView', [readonly ? $t('ladderEditor.referenceSolution') : $t('ladderEditor.viewerOrReadOnlyAccount')]) }}</div>
    <div v-else class="lde-tools" data-tour="ld-tools" @mousedown.prevent>
      <template v-for="g in TOOL_GROUPS" :key="g.name">
        <div class="tg">
          <button v-for="t in g.items" :key="t.k" class="tb" :class="'tb-' + t.k" :title="$t('common.n012', [t.cn, t.key])" draggable="true"
            :data-tool="t.k" @dragstart="startDrag($event, t.k)" @dragend="drag = ''" @click="tool(t.k)">
            <svg viewBox="0 0 40 24" width="36" height="22"><g v-html="glyph(t.k)" /></svg>
            <span>{{ t.short }}</span>
          </button>
        </div>
        <i class="tsep" />
      </template>
      <el-dropdown trigger="click" @command="(c: string) => tool('FB:' + c)">
        <button class="tb tb-fb" :title="$t('ladderEditor.functionBlocksTimersCountersEdge')" draggable="true" data-tool="FB:TON" @dragstart="startDrag($event, 'FB:TON')" @dragend="drag = ''">
          <svg viewBox="0 0 40 24" width="36" height="22"><g v-html="glyph('FB')" /></svg><span>{{ $t('ladderEditor.functionBlocks') }}</span>
        </button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item v-for="(d, k) in FB_TYPES" :key="k" :command="k"><b class="mono">{{ k }}</b>&nbsp;&nbsp;<span class="muted">{{ d.cn }}</span></el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <button class="tb" :title="$t('ladderEditor.comparisonBlocks')" draggable="true" data-tool="CMP" @dragstart="startDrag($event, 'CMP')" @dragend="drag = ''" @click="tool('CMP')">
        <svg viewBox="0 0 40 24" width="36" height="22"><g v-html="glyph('CMP')" /></svg><span>{{ $t('ladderEditor.compare') }}</span></button>
      <button class="tb" :title="$t('ladderEditor.arithmeticBlocksAddSubtractMultiply')" draggable="true" data-tool="MATH" @dragstart="startDrag($event, 'MATH')" @dragend="drag = ''" @click="tool('MATH')">
        <svg viewBox="0 0 40 24" width="36" height="22"><g v-html="glyph('MATH')" /></svg><span>{{ $t('ladderEditor.arithmetic') }}</span></button>
      <button class="tb" :title="$t('ladderEditor.moveMove')" draggable="true" data-tool="MOVE" @dragstart="startDrag($event, 'MOVE')" @dragend="drag = ''" @click="tool('MOVE')">
        <svg viewBox="0 0 40 24" width="36" height="22"><g v-html="glyph('MOVE')" /></svg><span>{{ $t('ladderEditor.move') }}</span></button>
      <i class="tsep" />
      <button class="tb" :title="$t('ladderEditor.addAParallelBranchAround')" data-tool="PAR" @click="tool('PAR')"><svg viewBox="0 0 40 24" width="36" height="22"><g v-html="glyph('PAR')" /></svg><span>{{ $t('ladderEditor.parallel') }}</span></button>
      <button class="tb" :title="$t('ladderEditor.newRungCtrlEnter')" data-tool="RUNG" @click="newRung()"><svg viewBox="0 0 40 24" width="36" height="22"><g v-html="glyph('RUNG')" /></svg><span>{{ $t('ladderEditor.rung') }}</span></button>
      <span class="grow" />
      <button class="tb ic" :title="$t('store.undoCtrlZ')" :disabled="!S.undo.length" @click="sess.undoOne()"><el-icon><RefreshLeft /></el-icon></button>
      <button class="tb ic" :title="$t('workbench.redoCtrlY')" :disabled="!S.redo.length" @click="sess.redoOne()"><el-icon><RefreshRight /></el-icon></button>
      <button class="tb ic" :title="$t('ladderEditor.deleteSelectedDel')" :disabled="!S.sel.length && S.selRung < 0" @click="del()"><el-icon><Delete /></el-icon></button>
    </div>

    <div ref="scroller" class="lde-body" tabindex="0" @keydown="onKey" @mousedown.self="clearSel" @contextmenu.prevent>
      <div v-for="(r, ri) in rungs" :key="ri" class="rung" :class="{ selr: S.selRung === ri, err: rungErr(ri), halt: haltRung === ri, bp: bps.has(ri + 1) }"
        :data-rung="ri">
        <div class="rh" @mousedown="selectRung(ri, $event)" @contextmenu.prevent="menuRung($event, ri)">
          <span class="bpdot" :title="bps.has(ri + 1) ? $t('ladderEditor.removeBreakpoint') : $t('ladderEditor.setABreakpointPauseBefore')" @mousedown.stop @click.stop="toggleBp(ri)" />
          <b class="rn">{{ $t('common.rung0', [ri + 1]) }}</b>
          <span v-if="haltRung === ri" class="haltb">{{ $t('ladderEditor.pausedHere') }}</span>
          <span v-if="isOnline" class="rpow" :class="{ on: S.online?.rungs?.[ri] }">{{ S.online?.rungs?.[ri] ? $t('ladderEditor.true') : $t('ladderEditor.false') }}</span>
          <span v-if="diag && diag.rung === ri" class="rdiag" :title="diag.msg" data-k="rung-diag">{{ $t('ladderEditor.diagnosticsPowerFlowStopsHere') }}</span>
          <button v-if="!readonly" class="rexp" :class="{ on: expl.ri === ri }" :data-act="'explain-' + ri" :title="$t('ladderEditor.explainThisRungStepBy')"
            @mousedown.stop @click.stop="explain(ri)">{{ $t('ladderEditor.explain') }}</button>
          <input v-if="editComment === ri" ref="cmtInput" v-model="cmtVal" class="cmt-in" :placeholder="$t('ladderEditor.rungCommentDescribeWhatThis')"
            @keydown.enter.stop="commitComment" @keydown.esc.stop="editComment = -1" @blur="commitComment" @mousedown.stop />
          <span v-else class="cmt" :class="{ empty: !r.comment }" @dblclick.stop="startComment(ri)" @mousedown.stop="selectRung(ri, $event)">{{ r.comment || $t('ladderEditor.doubleClickToAddA') }}</span>
          <span v-for="e in rungMsgs(ri)" :key="e.msg" class="rmsg" :class="e.kind" :title="e.msg">{{ e.kind === 'err' ? '✖' : '⚠' }} {{ e.msg }}</span>
        </div>
        <div v-if="expl.ri === ri" class="rexpl" data-k="rung-explain" @mousedown.stop>
          <div v-if="expl.loading" class="muted">{{ $t('ladderEditor.readingLivePlcValues') }}</div>
          <template v-else>
            <div v-for="(l, i) in expl.lines" :key="i" class="rexpl-l">{{ l }}</div>
            <div v-if="expl.summary" class="rexpl-s">{{ expl.summary }}</div>
            <div class="rexpl-f muted">{{ $t('ladderEditor.theseValuesWereCapturedWhen') }}<a @click="explain(ri, true)">{{ $t('common.refresh') }}</a> · <a @click="expl.ri = -1">{{ $t('common.close') }}</a></div>
          </template>
        </div>
        <div class="rd" :style="{ height: lay[ri].height + 'px' }">
          <svg :width="lay[ri].width + 4" :height="lay[ri].height" class="rsvg" @mousedown.self="selectRung(ri, $event)">
            <line class="rail" x1="1" :y1="0" x2="1" :y2="lay[ri].height" :class="{ p: railOn }" />
            <line class="rail" :x1="lay[ri].width + 1" :y1="0" :x2="lay[ri].width + 1" :y2="lay[ri].height" />
            <g transform="translate(1,0)">
              <template v-for="(p, pi) in lay[ri].prims" :key="pi">
                <line v-if="p.k === 'wire'" class="wire" :class="pw(p.p)" :x1="p.x1" :y1="p.y1" :x2="p.x2" :y2="p.y2" />
              </template>
              <g v-for="p in elsOf(ri)" :key="p.el.id" class="el" :class="elClass(p)" :data-id="p.el.id" :data-t="p.el.t"
                @mousedown.stop="selectEl(p.el.id, $event)" @dblclick.stop="editDefault(p, ri)" @contextmenu.prevent.stop="menuEl($event, p, ri)">
                <rect class="hit" :x="p.x + 2" :y="p.y + 2" :width="p.w - 4" :height="p.h - 4" rx="4" />
                <!-- Contacts / coils -->
                <template v-if="!isBox(p.el)">
                  <line class="wire" :class="pw(p.pin)" :x1="p.x" :y1="p.y + p.wy" :x2="p.x + p.w / 2 - 11" :y2="p.y + p.wy" />
                  <line class="wire" :class="pw(p.pout)" :x1="p.x + p.w / 2 + 11" :y1="p.y + p.wy" :x2="p.x + p.w" :y2="p.y + p.wy" />
                  <g :transform="`translate(${p.x + p.w / 2},${p.y + p.wy})`" class="sym" :class="{ closed: p.c === true, open: p.c === false }" v-html="symbol(p.el)" />
                  <text class="opnd" :class="{ ph: !p.el.var, forced: isForced(p.el.var) }" :x="p.x + p.w / 2" :y="p.y + p.wy - 21" text-anchor="middle"
                    @mousedown.stop="selectEl(p.el.id, $event)" @dblclick.stop="startEdit(p, 'var', ri)">{{ clip(p.el.var || '<??>', 13) }}</text>
                  <text class="addr" :x="p.x + p.w / 2" :y="p.y + p.wy + 27" text-anchor="middle">{{ subLabel(p.el.var) }}</text>
                  <g v-if="isForced(p.el.var)"><rect class="fbadge" :x="p.x + p.w - 20" :y="p.y + p.wy - 33" width="14" height="13" rx="2" /><text class="fbt" :x="p.x + p.w - 13" :y="p.y + p.wy - 23" text-anchor="middle">F</text></g>
                </template>
                <!-- Boxes: function blocks / comparisons / arithmetic / moves -->
                <template v-else>
                  <line class="wire" :class="pw(p.pin)" :x1="p.x" :y1="p.y + p.wy" :x2="bx(p)" :y2="p.y + p.wy" />
                  <line class="wire" :class="pw(p.pout)" :x1="bx(p) + G.boxW" :y1="p.y + p.wy" :x2="p.x + p.w" :y2="p.y + p.wy" />
                  <text v-if="p.el.t === 'FB'" class="inst" :class="{ ph: !p.el.inst }" :x="bx(p) + G.boxW / 2" :y="p.y + 15" text-anchor="middle"
                    @dblclick.stop="startEdit(p, 'inst', ri)">{{ p.el.inst || $t('ladderEditor.instance') }}</text>
                  <rect class="box" :x="bx(p)" :y="p.y + 22" :width="G.boxW" :height="boxH(p.el)" rx="3" />
                  <rect class="boxh" :x="bx(p)" :y="p.y + 22" :width="G.boxW" height="22" rx="3" />
                  <text class="btitle" :x="bx(p) + G.boxW / 2" :y="p.y + 37" text-anchor="middle" @dblclick.stop="startEdit(p, 'title', ri)">{{ boxTitle(p.el) }}</text>
                  <template v-for="(pin, k) in pinsOf(p.el).ins" :key="'i' + pin">
                    <text class="pinl" :x="bx(p) + 6" :y="pinY(p, k) + 4">{{ pin }}</text>
                    <template v-if="k > 0">
                      <line class="stub" :x1="bx(p) - 10" :y1="pinY(p, k)" :x2="bx(p)" :y2="pinY(p, k)" />
                      <text class="opnd sm" :class="{ ph: !inVal(p.el, pin) }" :x="bx(p) - 13" :y="pinY(p, k) + 4" text-anchor="end"
                        @dblclick.stop="startEdit(p, 'in:' + pin, ri)" @mousedown.stop="selectEl(p.el.id, $event)">{{ clip(inVal(p.el, pin) || '<??>', 9) }}</text>
                      <text v-if="isOnline && liveIn(p.el, pin) !== null" class="live" :x="bx(p) - 13" :y="pinY(p, k) + 15" text-anchor="end">{{ liveIn(p.el, pin) }}</text>
                    </template>
                  </template>
                  <template v-for="(pin, k) in pinsOf(p.el).outs" :key="'o' + pin">
                    <text class="pinl" :x="bx(p) + G.boxW - 6" :y="pinY(p, k) + 4" text-anchor="end">{{ pin }}</text>
                    <template v-if="k > 0 || p.el.t === 'CMP'">
                      <template v-if="k > 0">
                        <line class="stub" :x1="bx(p) + G.boxW" :y1="pinY(p, k)" :x2="bx(p) + G.boxW + 10" :y2="pinY(p, k)" />
                        <text class="opnd sm" :class="{ ph: !outVal(p.el, pin) && p.el.t !== 'FB' }" :x="bx(p) + G.boxW + 13" :y="pinY(p, k) + 4"
                          @dblclick.stop="startEdit(p, 'out:' + pin, ri)" @mousedown.stop="selectEl(p.el.id, $event)">{{ clip(outVal(p.el, pin) || (p.el.t === 'FB' ? '' : '<??>'), 9) }}</text>
                      </template>
                    </template>
                    <text v-if="isOnline && liveOut(p.el, pin) !== null" class="live" :x="bx(p) + G.boxW + 13" :y="pinY(p, k) + (k > 0 ? 15 : -6)">{{ liveOut(p.el, pin) }}</text>
                  </template>
                </template>
                <title>{{ tip(p) }}</title>
              </g>
              <!-- Drop target -->
              <template v-if="drag">
                <template v-for="(p, pi) in lay[ri].prims" :key="'d' + pi">
                  <rect v-if="p.k === 'drop'" class="drop" :class="{ hov: hov === 'd' + ri + ':' + pi }" :x="p.x" :y="p.y" :width="p.w" :height="p.h" rx="4"
                    @dragover.prevent="hov = 'd' + ri + ':' + pi" @dragleave="hov = ''" @drop.prevent="dropSer(p, ri)" />
                  <rect v-else-if="p.k === 'dropPar' && !isCoilTool" class="dropp" :class="{ hov: hov === 'p' + ri + ':' + pi }" :x="p.x" :y="p.y" :width="p.w" :height="p.h" rx="3"
                    @dragover.prevent="hov = 'p' + ri + ':' + pi" @dragleave="hov = ''" @drop.prevent="dropPar(p)" />
                </template>
              </template>
            </g>
          </svg>
          <!-- Empty rung: show first-time users how to start -->
          <div v-if="!r.elements.length && !drag && !ro" class="empty-r" @mousedown.stop>
            <span>{{ $t('ladderEditor.emptyRungClickNoContact') }} <kbd>C</kbd> {{ $t('ladderEditor.toAddAnNoContact') }}<kbd>O</kbd> {{ $t('ladderEditor.toAddACoilYou') }}</span>
            <button v-if="ri === 0 && rungs.length === 1" class="plc-btn" data-act="example" @click="insertExample(ri)">{{ $t('ladderEditor.insertExampleStartStopSeal') }}</button>
          </div>
          <!-- Operand editor + autocomplete -->
          <div v-if="ed && ed.ri === ri" class="opedit" :style="{ left: ed.x + 'px', top: ed.y + 'px', width: ed.w + 'px' }" @mousedown.stop>
            <select v-if="ed.kind === 'select'" ref="edInput" v-model="ed.value" class="op-in" @change="commitEdit()" @keydown.esc.stop="ed = null" @blur="commitEdit()">
              <option v-for="o in ed.options" :key="o[0]" :value="o[0]">{{ o[1] }}</option>
            </select>
            <template v-else>
              <input ref="edInput" v-model="ed.value" class="op-in mono" spellcheck="false" :placeholder="ed.ph" @keydown="edKey" @blur="onBlur" @input="acSel = 0" />
              <div v-if="acList.length" class="ac">
                <div v-for="(a, i) in acList" :key="a.name" class="ac-i" :class="{ on: i === acSel, gs: i > 0 && (acList[i - 1] as any).grp !== (a as any).grp }" @mousedown.prevent="pick(a)">
                  <em class="g">{{ [$t('common.input'), $t('common.output'), $t('common.variable')][(a as any).grp] }}</em>
                  <b class="mono">{{ a.name }}</b><small>{{ a.type }}</small><i>{{ a.info }}</i>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
      <div v-if="!ro" class="rung-add" @click="newRung()">{{ $t('ladderEditor.newRung') }}</div>
      <div v-if="!ro" class="hint muted">{{ $t('ladderEditor.shortcutsCNoContactX') }}</div>
    </div>

    <!-- Context menu -->
    <div v-if="menu" class="ctx" :style="{ left: menu.x + 'px', top: menu.y + 'px' }" @mousedown.stop>
      <div v-for="(m, i) in menu.items" :key="i" :class="m === '-' ? 'sep' : ['it', { dis: m.dis }]" @click="m !== '-' && !m.dis && (menu = null, m.run())">
        <template v-if="m !== '-'">{{ m.label }}<small v-if="m.key">{{ m.key }}</small></template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
import { ElMessage, ElMessageBox } from 'element-plus';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { BOXES, boxPins, COILS, CONTACTS, flatten, G, insert, isEl, layoutRung, locate, makeEl, MATH_OPS, CMP_OPS, newId, removeIds, reId, addParallel, T_CN } from './ld';
import { canEdit, get } from '../api';
import { C } from './plcApi';
import { FB_FIELD_TYPE, FB_TYPES, fmtVal } from './plcApi';
import type { Sess } from './session';

const props = defineProps<{ sess: Sess; readonly?: boolean }>();
const emit = defineEmits<{ (e: 'xref', name: string): void }>();
/** Read-only: teachers observing student sandboxes, read-only accounts, and reference answer comparison. View and select only; no edits or forcing. */
const ro = computed(() => !!props.readonly || !canEdit());
const sess = props.sess;
const S = sess.s;

const TOOL_GROUPS = [
  { name: $t('common.contact'), items: [{ k: 'NO', cn: $t('ladderEditor.noContact'), short: $t('common.no3'), key: 'C' }, { k: 'NC', cn: $t('ladderEditor.ncContact'), short: $t('common.nc'), key: 'X' },
    { k: 'P', cn: $t('ladderEditor.risingEdgeContact'), short: $t('ladderEditor.risingEdge'), key: 'P' }, { k: 'N', cn: $t('ladderEditor.fallingEdgeContact'), short: $t('ladderEditor.fallingEdge'), key: 'N' }] },
  { name: $t('ladderEditor.coil'), items: [{ k: 'COIL', cn: $t('ladderEditor.coil'), short: $t('ladderEditor.coil'), key: 'O' }, { k: 'NCOIL', cn: $t('ladderEditor.negatedCoil'), short: $t('ladderEditor.negate'), key: '' },
    { k: 'SET', cn: $t('common.setCoil'), short: $t('ladderEditor.set'), key: 'S' }, { k: 'RESET', cn: $t('common.resetCoil'), short: $t('common.reset'), key: 'R' }] },
];

const rungs = computed(() => S.program?.source?.rungs || []);
const scroller = ref<HTMLElement>();
const width = ref(900);
const drag = ref('');
const hov = ref('');
const menu = ref<any>(null);
const editComment = ref(-1);
const cmtVal = ref('');
const cmtInput = ref<any>();
const ed = ref<any>(null);
const edInput = ref<any>();
const acSel = ref(0);

/** 4.5 diagnostics (the PLC programming window sets S.diag from coach data, only when program hashes match): highlight blocking elements in red; hover for details. */
const diag = computed<any>(() => (S as any).diag || null);
const diagIds = computed(() => new Set<string>(diag.value?.elems || []));
const expl = ref<any>({ ri: -1, lines: [], summary: '', loading: false });
async function explain(ri: number, again = false) {
  if (expl.value.ri === ri && !again) { expl.value = { ri: -1, lines: [], summary: '' }; return; }
  expl.value = { ri, lines: [], summary: '', loading: true };
  try {
    const r = await get(`${C(S.pid, S.bid)}/explain?rung=${ri}`, true);
    expl.value = { ri, lines: r.lines || [], summary: r.summary || '', loading: false };
  } catch (e: any) { expl.value = { ri, lines: [$t('ladderEditor.cannotReadLivePlcValues') + (e?.message || e)], summary: '', loading: false }; }
}
const isOnline = computed(() => !!S.online && S.monitor && ['RUN', 'HALT', 'STOP', 'ERROR'].includes(S.online.state) && S.online.lang === 'LD');
const railOn = computed(() => (isOnline.value ? ['RUN', 'HALT'].includes(S.online.state) : null));
const flags = computed(() => (isOnline.value ? S.online.ld || {} : null));
const haltRung = computed(() => (S.online?.state === 'HALT' && S.online.halt?.mid_scan ? S.online.halt.rung : -1));
const bps = computed(() => new Set<number>(S.online?.bps || []));
const lay = computed(() => {
  void S.rev;
  return rungs.value.map((r: any) => layoutRung(r, flags.value, railOn.value, Math.max(420, width.value - 40), true));
});
const isCoilTool = computed(() => COILS.includes(drag.value));
const errById = computed(() => {
  const m: Record<string, string> = {};
  for (const e of S.errors || []) if (e.elem) m[e.elem] = e.msg;
  return m;
});

function elsOf(ri: number) { return lay.value[ri].prims.filter((p: any) => p.k === 'el') as any[]; }
const isBox = (el: any) => BOXES.includes(el.t);
const bx = (p: any) => p.x + G.boxSide;
const pinsOf = (el: any) => boxPins(el);
const boxH = (el: any) => { const { ins, outs } = boxPins(el); return G.boxHead + Math.max(ins.length, outs.length) * G.boxPinH + 6; };
const pinY = (p: any, k: number) => p.y + 22 + G.boxHead + k * G.boxPinH + G.boxPinH / 2;
const clip = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + '…' : s);
const pw = (v: boolean | null | undefined) => (v === true ? 'p' : v === false ? 'np' : '');

function boxTitle(el: any) {
  if (el.t === 'FB') return el.fb;
  if (el.t === 'CMP') return 'CMP ' + (el.op || '');
  if (el.t === 'MATH') return el.op || 'ADD';
  return 'MOVE';
}
function inVal(el: any, pin: string) {
  if (el.t === 'FB') return el.in?.[pin] || '';
  if (el.t === 'CMP' || el.t === 'MATH') return pin === 'IN1' ? el.a : el.b;
  return el.in;
}
function outVal(el: any, pin: string) {
  if (el.t === 'FB') return el.out?.[pin] || '';
  return el.out;
}
function liveVar(name: string) {
  if (!isOnline.value || !name) return null;
  const vars = S.online.vars || {};
  const up = String(name).toUpperCase();
  if (up.includes('.')) {
    const [b, f] = name.split('.');
    const k = Object.keys(vars).find((x) => x.toUpperCase() === b.toUpperCase());
    const v = k ? vars[k]?.[f.toUpperCase()] : undefined;
    return v === undefined ? null : fmtVal(v, FB_FIELD_TYPE[f.toUpperCase()]);
  }
  const k = Object.keys(vars).find((x) => x.toUpperCase() === up);
  if (!k) return null;
  return fmtVal(vars[k], S.online.types?.[k]);
}
function liveIn(el: any, pin: string) {
  if (el.t === 'FB') {
    if (!/^[A-Za-z_%]/.test(inVal(el, pin) || '') || /^T(IME)?#/i.test(inVal(el, pin) || '')) return null;     // Don't display constants twice
    const v = S.online?.vars?.[el.inst]?.[pin];
    return v === undefined ? null : fmtVal(v, FB_FIELD_TYPE[pin]);
  }
  const x = inVal(el, pin);
  return /^[A-Za-z_%]/.test(x || '') ? liveVar(x) : null;
}
function liveOut(el: any, pin: string) {
  if (el.t === 'FB') {
    const v = S.online?.vars?.[el.inst]?.[pin];
    if (v === undefined || (FB_FIELD_TYPE[pin] === 'BOOL' && pin === FB_TYPES[el.fb]?.pout)) return null;
    return fmtVal(v, FB_FIELD_TYPE[pin]);
  }
  if (pin === 'OUT' && el.t !== 'CMP') return liveVar(el.out);
  return null;
}
function subLabel(v: string) {
  if (!v) return '';
  const up = v.toUpperCase();
  const io = S.io.find((e: any) => e.name.toUpperCase() === up);
  if (io) return io.addr || '';
  const vv = (S.program?.vars || []).find((x: any) => x.name?.toUpperCase() === up);
  if (vv?.addr) return vv.addr;
  if (isOnline.value) { const lv = liveVar(v); if (lv !== null && lv !== 'TRUE' && lv !== 'FALSE') return lv; }
  return '';
}
function isForced(v: string) {
  if (!v || !S.online?.forced) return false;
  const up = v.toUpperCase();
  return Object.keys(S.online.forced).some((k) => k.toUpperCase() === up);
}
function elClass(p: any) {
  return { sel: S.sel.includes(p.el.id), e: !!errById.value[p.el.id], pon: p.pout === true, coil: COILS.includes(p.el.t), dg: diagIds.value.has(p.el.id) };
}
function tip(p: any) {
  const e = errById.value[p.el.id];
  let s = T_CN[p.el.t] || p.el.t;
  if (p.el.var) s += $t('common.k546') + p.el.var;
  if (p.el.inst) s += $t('common.k546') + p.el.inst;
  const info = p.el.var ? sess.symbols().find((x) => x.name.toUpperCase() === p.el.var.toUpperCase()) : null;
  if (info) s += $t('ladderEditor.n01', [info.type, info.info ? $t('common.k521') + info.info : '']);
  if (e) s += $t('ladderEditor.error') + e;
  if (diagIds.value.has(p.el.id) && diag.value) s += $t('ladderEditor.diagnostics') + diag.value.msg;
  const io = p.el.var ? S.io.find((x: any) => String(x.name).toUpperCase() === String(p.el.var).toUpperCase()) : null;
  if (io?.contact === 'NC') s += $t('ladderEditor.n0IsAnNcInput', [io.name]);
  return s;
}
function rungErr(ri: number) { return (S.errors || []).some((e: any) => e.rung === ri); }
function rungMsgs(ri: number) {
  return [...(S.errors || []).filter((e: any) => e.rung === ri && !e.elem).map((e: any) => ({ kind: 'err', msg: e.msg })),
    ...(S.warnings || []).filter((e: any) => e.rung === ri).map((e: any) => ({ kind: 'warn', msg: e.msg }))];
}

// ---------------------------------------------------------------- Graphics
const SYM: Record<string, string> = {
  NO: '<rect class="fill" x="-10" y="-12" width="20" height="24"/><line x1="-10" y1="-13" x2="-10" y2="13"/><line x1="10" y1="-13" x2="10" y2="13"/>',
  NC: '<rect class="fill" x="-10" y="-12" width="20" height="24"/><line x1="-10" y1="-13" x2="-10" y2="13"/><line x1="10" y1="-13" x2="10" y2="13"/><line x1="-8" y1="11" x2="8" y2="-11"/>',
  P: '<rect class="fill" x="-10" y="-12" width="20" height="24"/><line x1="-10" y1="-13" x2="-10" y2="13"/><line x1="10" y1="-13" x2="10" y2="13"/><text x="0" y="5" text-anchor="middle">P</text>',
  N: '<rect class="fill" x="-10" y="-12" width="20" height="24"/><line x1="-10" y1="-13" x2="-10" y2="13"/><line x1="10" y1="-13" x2="10" y2="13"/><text x="0" y="5" text-anchor="middle">N</text>',
  COIL: '<path class="fillc" d="M-5,-12 A17,17 0 0 0 -5,12 L5,12 A17,17 0 0 0 5,-12 Z"/><path d="M-5,-12 A17,17 0 0 0 -5,12"/><path d="M5,-12 A17,17 0 0 1 5,12"/>',
  NCOIL: '<path class="fillc" d="M-5,-12 A17,17 0 0 0 -5,12 L5,12 A17,17 0 0 0 5,-12 Z"/><path d="M-5,-12 A17,17 0 0 0 -5,12"/><path d="M5,-12 A17,17 0 0 1 5,12"/><line x1="-6" y1="9" x2="6" y2="-9"/>',
  SET: '<path class="fillc" d="M-5,-12 A17,17 0 0 0 -5,12 L5,12 A17,17 0 0 0 5,-12 Z"/><path d="M-5,-12 A17,17 0 0 0 -5,12"/><path d="M5,-12 A17,17 0 0 1 5,12"/><text x="0" y="5" text-anchor="middle">S</text>',
  RESET: '<path class="fillc" d="M-5,-12 A17,17 0 0 0 -5,12 L5,12 A17,17 0 0 0 5,-12 Z"/><path d="M-5,-12 A17,17 0 0 0 -5,12"/><path d="M5,-12 A17,17 0 0 1 5,12"/><text x="0" y="5" text-anchor="middle">R</text>',
};
function symbol(el: any) { return SYM[el.t] || ''; }
function glyph(k: string) {
  const w = '<line x1="0" y1="12" x2="13" y2="12"/><line x1="27" y1="12" x2="40" y2="12"/>';
  const c = (s: string) => `<g transform="translate(20,12) scale(0.62)">${s}</g>`;
  if (SYM[k]) return w + c(SYM[k]);
  if (k === 'FB') return '<line x1="0" y1="12" x2="8" y2="12"/><line x1="32" y1="12" x2="40" y2="12"/><rect x="8" y="3" width="24" height="18" rx="2"/><text x="20" y="16" text-anchor="middle" style="font-size:8px">TON</text>';
  if (k === 'CMP') return '<line x1="0" y1="12" x2="8" y2="12"/><line x1="32" y1="12" x2="40" y2="12"/><rect x="8" y="3" width="24" height="18" rx="2"/><text x="20" y="16" text-anchor="middle" style="font-size:9px">&gt;=</text>';
  if (k === 'MATH') return '<line x1="0" y1="12" x2="8" y2="12"/><line x1="32" y1="12" x2="40" y2="12"/><rect x="8" y="3" width="24" height="18" rx="2"/><text x="20" y="16" text-anchor="middle" style="font-size:9px">+−</text>';
  if (k === 'MOVE') return '<line x1="0" y1="12" x2="8" y2="12"/><line x1="32" y1="12" x2="40" y2="12"/><rect x="8" y="3" width="24" height="18" rx="2"/><text x="20" y="16" text-anchor="middle" style="font-size:8px">MOV</text>';
  if (k === 'PAR') return '<line x1="0" y1="6" x2="40" y2="6"/><line x1="6" y1="6" x2="6" y2="19"/><line x1="34" y1="6" x2="34" y2="19"/><line x1="6" y1="19" x2="15" y2="19"/><line x1="25" y1="19" x2="34" y2="19"/><line x1="15" y1="14" x2="15" y2="23"/><line x1="25" y1="14" x2="25" y2="23"/>';
  if (k === 'RUNG') return '<line x1="3" y1="2" x2="3" y2="22"/><line x1="37" y1="2" x2="37" y2="22"/><line x1="3" y1="12" x2="37" y2="12" stroke-dasharray="3 3"/><line x1="20" y1="6" x2="20" y2="18"/><line x1="14" y1="12" x2="26" y2="12"/>';
  return '';
}

// ---------------------------------------------------------------- Selection
function selectEl(id: string, e?: MouseEvent) {
  menu.value = null;
  if (e?.shiftKey && S.sel.length) {
    const a = locate(rungs.value, S.sel[0]), b = locate(rungs.value, id);
    if (a && b && a.list === b.list) {
      const [i, j] = [a.index, b.index].sort((x, y) => x - y);
      S.sel = a.list.slice(i, j + 1).filter(isEl).map((x: any) => x.id);
      return;
    }
  }
  if (e?.ctrlKey) { S.sel = S.sel.includes(id) ? S.sel.filter((x) => x !== id) : [...S.sel, id]; return; }
  S.sel = [id];
  const h = locate(rungs.value, id);
  S.selRung = -1;
  if (h) curRung.value = h.rung;
  focus();
}
const curRung = ref(0);
function selectRung(ri: number, e?: MouseEvent) {
  if (e && (e.target as HTMLElement).closest?.('.bpdot')) return;
  menu.value = null; S.sel = []; S.selRung = ri; curRung.value = ri; focus();
}
function clearSel() { S.sel = []; S.selRung = -1; menu.value = null; }
function focus() { nextTick(() => { if (!ed.value && editComment.value < 0) scroller.value?.focus({ preventScroll: true }); }); }

// ---------------------------------------------------------------- Editing
function change(fn: (rs: any[]) => void) { sess.change((p) => fn(p.source.rungs)); }
function uniqueInst(fb: string) {
  const pre = FB_TYPES[fb]?.prefix || 'FB';
  const used = new Set(sess.symbols().map((x) => x.name.toUpperCase()));
  for (const r of rungs.value) for (const e of flatten(r.elements)) if (e.inst) used.add(String(e.inst).toUpperCase());
  let i = 1;
  while (used.has((pre + i).toUpperCase())) i++;
  return pre + i;
}
function makeFromTool(k: string) {
  if (k.startsWith('FB:')) {
    const fb = k.slice(3);
    const inst = uniqueInst(fb);
    const d = FB_TYPES[fb];
    const ins: any = {};
    if (d.in.includes('PT')) ins.PT = 'T#2s';
    if (d.in.includes('PV')) ins.PV = '10';
    return makeEl('FB', { fb, inst, in: ins, out: {} });
  }
  return makeEl(k);
}
function declareInst(el: any) {
  if (el.t !== 'FB' || !el.inst) return;
  const vars = S.program.vars;
  if (!vars.some((v: any) => v.name?.toUpperCase() === el.inst.toUpperCase())) vars.push({ name: el.inst, type: el.fb, comment: FB_TYPES[el.fb]?.cn || '' });
}
function tool(k: string) {
  if (ro.value) return;
  if (k === 'PAR') return parallel();
  const el = makeFromTool(k);
  const after = S.sel.length ? S.sel[S.sel.length - 1] : undefined;
  const ri = S.selRung >= 0 ? S.selRung : curRung.value;
  change((rs) => { if (!rs.length) rs.push({ comment: '', elements: [] }); insert(rs, ri, el, after); });
  if (el.t === 'FB') declareInst(el);
  S.sel = [el.id];
  nextTick(() => editDefaultById(el.id));
}
function parallel() {
  if (ro.value) return;
  if (!S.sel.length) { ElMessage.info($t('ladderEditor.selectTheElementsToBranch')); return; }
  const el = makeEl('NO');
  let ok = false;
  change((rs) => { ok = addParallel(rs, S.sel, el); });
  if (!ok) { sess.undoOne(); ElMessage.warning($t('ladderEditor.aParallelBranchCanOnly')); return; }
  S.sel = [el.id];
  nextTick(() => editDefaultById(el.id));
}
/** Example: Start ‖ Seal-in — Stop (NC) — Output coil. Pick names from the I/O table. */
function insertExample(ri: number) {
  if (ro.value) return;
  const ins = S.io.filter((e: any) => e.dir === 'in' && (e.type || 'BOOL') === 'BOOL');
  const outs = S.io.filter((e: any) => e.dir === 'out' && (e.type || 'BOOL') === 'BOOL');
  const pick = (list: any[], re: RegExp) => list.find((e) => re.test(`${e.name} ${e.comment || ''}`))?.name;
  // 4.5: use the I/O table's "Contact" column (previously guessed from "NC" in comments; all guesses in lesson 15 were wrong, and the inserted NC STOP kept the rung false)
  const start = pick(ins, /start|\u542f\u52a8|fwd|\u6b63\u8f6c/i) || ins.find((e: any) => e.contact !== 'NC' && !/running|\u53cd\u9988|feedback|_AT|HOME|BACK/i.test(e.name))?.name || 'Start';
  const stop = pick(ins.filter((e: any) => e.name !== start), /stop|\u505c\u6b62/i) || 'Stop';
  const out = pick(outs, /motor|fwd|conveyor|\u7535\u673a|\u8f93\u9001|\u6b63\u8f6c|_RUN\b/i) || outs[0]?.name || 'Motor';
  const stopIo = S.io.find((e: any) => e.name === stop);
  const stopNcButton = stopIo?.contact === 'NC';                // NC button: 1 when not pressed → use an NO contact
  const guards = ins.filter((e: any) => e.contact === 'NC' && e.name !== stop).map((e: any) => e.name);   // Also wire the thermal overload relay and E-Stop in series
  change((rs) => {
    rs[ri].comment ||= $t('ladderEditor.startStopSealInPressing');
    rs[ri].elements = [{ par: [[makeEl('NO', { var: start })], [makeEl('NO', { var: out })]] }, makeEl(stopIo && !stopNcButton ? 'NC' : 'NO', { var: stop }),
      ...guards.map((g: string) => makeEl('NO', { var: g })), makeEl('COIL', { var: out })];
  });
  ElMessage.success($t('ladderEditor.inserted0StartWith1', [start, out, stop, stopNcButton ? $t('ladderEditor.ncButton1WhenNot') : '', guards.length ? $t('common.k360') + guards.join($t('common.k360')) + $t('ladderEditor.ncWithAnNoContact') : '', out]));
}
function newRung(after?: number) {
  if (ro.value) return;
  const i = after ?? (S.selRung >= 0 ? S.selRung : S.sel.length ? (locate(rungs.value, S.sel[0])?.rung ?? rungs.value.length - 1) : rungs.value.length - 1);
  change((rs) => rs.splice(i + 1, 0, { comment: '', elements: [] }));
  S.sel = []; S.selRung = i + 1; curRung.value = i + 1;
  nextTick(() => scroller.value?.querySelector(`[data-rung="${i + 1}"]`)?.scrollIntoView({ block: 'nearest' }));
}
function del() {
  if (ro.value) return;
  if (S.sel.length) {
    const ids = [...S.sel];
    change((rs) => removeIds(rs, ids));
    S.sel = [];
  } else if (S.selRung >= 0) {
    const ri = S.selRung;
    change((rs) => { rs.splice(ri, 1); if (!rs.length) rs.push({ comment: '', elements: [] }); });
    S.selRung = Math.min(ri, rungs.value.length - 1);
  }
}
function copy(cut = false) {
  if (S.sel.length) {
    const els = S.sel.map((id) => locate(rungs.value, id)?.el).filter(Boolean);
    S.clip = { kind: 'els', data: JSON.parse(JSON.stringify(els)) };
    if (cut) del();
  } else if (S.selRung >= 0) {
    S.clip = { kind: 'rung', data: JSON.parse(JSON.stringify(rungs.value[S.selRung])) };
    if (cut) del();
  }
}
function paste() {
  if (ro.value) return;
  const c = S.clip;
  if (!c) return;
  if (c.kind === 'rung') {
    const i = S.selRung >= 0 ? S.selRung : curRung.value;
    const r = { comment: c.data.comment, elements: reId(c.data.elements) };
    change((rs) => rs.splice(i + 1, 0, r));
    S.selRung = i + 1; S.sel = [];
  } else {
    const els = reId(c.data);
    let after = S.sel.length ? S.sel[S.sel.length - 1] : undefined;
    change((rs) => { for (const e of els) { insert(rs, curRung.value, e, after); after = e.id; } });
    S.sel = els.map((e: any) => e.id);
  }
}
function move(dir: number) {
  const r = rungs.value;
  if (!S.sel.length) {
    const ri = Math.max(0, Math.min(r.length - 1, (S.selRung >= 0 ? S.selRung : curRung.value) + (dir === 2 ? 1 : dir === -2 ? -1 : 0)));
    if (dir === 1 || dir === -1) { const f = flatten(r[ri]?.elements || []); if (f.length) S.sel = [f[dir === 1 ? 0 : f.length - 1].id], S.selRung = -1, curRung.value = ri; return; }
    S.selRung = ri; curRung.value = ri; return;
  }
  const h = locate(r, S.sel[S.sel.length - 1]);
  if (!h) return;
  if (dir === 1 || dir === -1) {
    const f = flatten(r[h.rung].elements);
    const i = f.findIndex((x) => x.id === h.el.id) + dir;
    if (i >= 0 && i < f.length) S.sel = [f[i].id];
  } else {
    const ri = h.rung + (dir > 0 ? 1 : -1);
    if (ri >= 0 && ri < r.length) { const f = flatten(r[ri].elements); if (f.length) S.sel = [f[0].id]; else { S.sel = []; S.selRung = ri; } curRung.value = ri; }
  }
}
function onKey(e: KeyboardEvent) {
  if (ed.value || editComment.value >= 0) return;
  const k = e.key.toLowerCase();
  const ctl = e.ctrlKey || e.metaKey;
  if (ro.value) {
    if (k.startsWith('arrow')) { e.preventDefault(); e.stopPropagation(); move(k === 'arrowright' ? 1 : k === 'arrowleft' ? -1 : k === 'arrowdown' ? 2 : -2); }
    if (ctl && k === 'c') { e.stopPropagation(); copy(); }
    return;
  }
  if (!(ctl && k === 'k')) e.stopPropagation();     // When the ladder editor has focus, keep keystrokes from the Workbench (undo, delete, etc. belong to the ladder editor)
  if (ctl && k === 'z') { e.preventDefault(); sess.undoOne(); return; }
  if (ctl && (k === 'y' || (e.shiftKey && k === 'z'))) { e.preventDefault(); sess.redoOne(); return; }
  if (ctl && k === 'c') { e.preventDefault(); copy(); return; }
  if (ctl && k === 'x') { e.preventDefault(); copy(true); return; }
  if (ctl && k === 'v') { e.preventDefault(); paste(); return; }
  if (ctl && k === 'enter') { e.preventDefault(); newRung(); return; }
  if (ctl && k === 's') { e.preventDefault(); sess.save(); return; }
  if (ctl) return;
  const map: Record<string, string> = { c: 'NO', x: 'NC', p: 'P', n: 'N', o: 'COIL', s: 'SET', r: 'RESET' };
  if (map[k]) { e.preventDefault(); tool(map[k]); return; }
  if (k === 'b') { e.preventDefault(); tool('FB:TON'); return; }
  if (k === 'v') { e.preventDefault(); parallel(); return; }
  if (k === 'delete' || k === 'backspace') { e.preventDefault(); del(); return; }
  if (k === 'enter' || k === 'f2') { e.preventDefault(); if (S.sel.length) editDefaultById(S.sel[0]); else if (S.selRung >= 0) startComment(S.selRung); return; }
  if (k === 'arrowright') { e.preventDefault(); move(1); } else if (k === 'arrowleft') { e.preventDefault(); move(-1); }
  else if (k === 'arrowdown') { e.preventDefault(); move(2); } else if (k === 'arrowup') { e.preventDefault(); move(-2); }
  else if (k === 'escape') clearSel();
}

// ---------------------------------------------------------------- Drag and drop
function startDrag(e: DragEvent, k: string) {
  drag.value = k;
  e.dataTransfer?.setData('text/plain', 'plc:' + k);
  if (e.dataTransfer) e.dataTransfer.effectAllowed = 'copy';
}
function dropSer(p: any, ri: number) {
  if (ro.value) return;
  const k = drag.value; drag.value = ''; hov.value = '';
  if (!k) return;
  const el = makeFromTool(k);
  sess.snap();
  p.list.splice(p.index, 0, el);
  S.rev++;
  if (el.t === 'FB') declareInst(el);
  S.sel = [el.id]; curRung.value = ri;
  nextTick(() => editDefaultById(el.id));
}
function dropPar(p: any) {
  if (ro.value) return;
  const k = drag.value; drag.value = ''; hov.value = '';
  if (!k) return;
  const el = makeFromTool(k);
  change((rs) => addParallel(rs, [p.id], el));
  if (el.t === 'FB') declareInst(el);
  S.sel = [el.id];
  nextTick(() => editDefaultById(el.id));
}

// ---------------------------------------------------------------- Operand editing
function primOf(id: string) {
  for (let ri = 0; ri < lay.value.length; ri++) {
    const p = lay.value[ri].prims.find((q: any) => q.k === 'el' && q.el.id === id);
    if (p) return { p, ri };
  }
  return null;
}
function editDefaultById(id: string) { const h = primOf(id); if (h) editDefault(h.p, h.ri); }
function editDefault(p: any, ri: number) {
  const t = p.el.t;
  if (CONTACTS.includes(t) || COILS.includes(t)) startEdit(p, 'var', ri);
  else if (t === 'FB') startEdit(p, p.el.inst ? 'in:' + (boxPins(p.el).ins[1] || 'PT') : 'inst', ri);
  else if (t === 'CMP' || t === 'MATH') startEdit(p, 'in:IN1', ri);
  else startEdit(p, 'in:IN', ri);
}
function startEdit(p: any, key: string, ri: number) {
  if (ro.value) return;
  S.sel = [p.el.id];
  const el = p.el;
  let x = p.x + p.w / 2 - 70, y = p.y + p.wy - 36, w = 140, value = '', kind = 'text', options: any[] = [], ph = $t('ladderEditor.variableNameOrAddress');
  if (key === 'var') value = el.var || '';
  else if (key === 'inst') { value = el.inst || ''; x = bx(p) + G.boxW / 2 - 70; y = p.y + 2; ph = $t('ladderEditor.instanceNameEGT1'); }
  else if (key === 'title') {
    kind = 'select'; x = bx(p) + 10; y = p.y + 22; w = G.boxW - 20;
    if (el.t === 'FB') { value = el.fb; options = Object.entries(FB_TYPES).map(([k, d]) => [k, `${k} ${d.cn}`]); }
    else if (el.t === 'CMP') { value = el.op; options = CMP_OPS.map((o) => [o, o]); }
    else if (el.t === 'MATH') { value = el.op; options = Object.entries(MATH_OPS).map(([k, v]) => [k, $t('common.n012', [k, v])]); }
    else return;
  } else if (key.startsWith('in:')) {
    const pin = key.slice(3);
    const k = boxPins(el).ins.indexOf(pin);
    value = inVal(el, pin) || ''; x = p.x - 4; y = pinY(p, k) - 13; w = G.boxSide + 6; ph = pin === 'PT' ? 'T#2s' : pin === 'PV' ? '10' : $t('ladderEditor.valueOrVariable');
    w = 120; x = bx(p) - 124;
  } else if (key.startsWith('out:')) {
    const pin = key.slice(4);
    const k = boxPins(el).outs.indexOf(pin);
    value = outVal(el, pin) || ''; x = bx(p) + G.boxW + 4; y = pinY(p, k) - 13; w = 120; ph = $t('ladderEditor.variableOptional');
  }
  ed.value = { id: el.id, key, ri, x, y, w, value, orig: value, kind, options, ph, type: el.t };
  acSel.value = 0;
  nextTick(() => { const i = Array.isArray(edInput.value) ? edInput.value[0] : edInput.value; i?.focus(); i?.select?.(); });
}
const acList = computed(() => {
  const e = ed.value;
  if (!e || e.kind !== 'text' || e.key === 'inst') return [];
  const q = String(e.value || '').trim().toUpperCase();
  const wantBool = e.key === 'var';
  let list = sess.symbols();
  if (wantBool) list = list.filter((x) => x.type === 'BOOL');
  if (q) list = list.filter((x) => x.name.toUpperCase().includes(q) || (x.info || '').toUpperCase().includes(q));
  const io = new Map(S.io.map((x: any) => [x.name.toUpperCase(), x]));
  const grp = (x: any) => { const d = (io.get(x.name.toUpperCase()) as any)?.dir; return d === 'in' ? 0 : d === 'out' ? 1 : 2; };
  list = list.map((x) => ({ ...x, grp: grp(x), ak: addrKey((io.get(x.name.toUpperCase()) as any)?.addr) }));
  list.sort((a: any, b: any) => (q ? (a.name.toUpperCase() === q ? 0 : 1) - (b.name.toUpperCase() === q ? 0 : 1) : 0)     // 4.5: rank exact name matches first (M1_RUNNING must not take priority over M1_RUN)
    || (q ? (a.name.toUpperCase().startsWith(q) ? 0 : 1) - (b.name.toUpperCase().startsWith(q) ? 0 : 1) : 0)
    || a.grp - b.grp || a.ak - b.ak || a.name.localeCompare(b.name));
  if (list.length === 1 && list[0].name.toUpperCase() === q) return [];
  return list.slice(0, 14);
});
/** %I1.2 → numeric sort key (byte*8+bit; word addresses sort after bit addresses). */
function addrKey(a?: string) {
  const m = /^%[IQM]([XWBD]?)(\d+)(?:\.(\d+))?/i.exec(a || '');
  if (!m) return 1e9;
  return (m[1] && m[1].toUpperCase() !== 'X' ? 1e6 : 0) + Number(m[2]) * 8 + Number(m[3] || 0);
}
function edKey(e: KeyboardEvent) {
  e.stopPropagation();                       // Prevent editor keystrokes from bubbling up to ladder shortcuts
  const n = acList.value.length;
  if (e.key === 'ArrowDown' && n) { e.preventDefault(); acSel.value = (acSel.value + 1) % n; }
  else if (e.key === 'ArrowUp' && n) { e.preventDefault(); acSel.value = (acSel.value + n - 1) % n; }
  else if (e.key === 'Enter' || e.key === 'Tab') {
    e.preventDefault();
    const typed = String(ed.value.value).trim();
    const exact = acList.value.some((a: any) => a.name.toUpperCase() === typed.toUpperCase());
    if (n && acSel.value >= 0 && typed && acList.value[acSel.value] && !(exact && acSel.value === 0)) ed.value.value = acList.value[acSel.value].name;
    else if (exact) ed.value.value = acList.value.find((a: any) => a.name.toUpperCase() === typed.toUpperCase()).name;
    const id = ed.value.id;
    commitEdit();
    if (e.key === 'Tab') { const h = locate(rungs.value, id); if (h) { const f = flatten(rungs.value[h.rung].elements); const i = f.findIndex((x) => x.id === id); if (f[i + 1]) { S.sel = [f[i + 1].id]; nextTick(() => editDefaultById(f[i + 1].id)); } } }
    else focus();
  } else if (e.key === 'Escape') { e.preventDefault(); ed.value = null; focus(); }
}
function pick(a: any) { if (ed.value) { ed.value.value = a.name; commitEdit(); focus(); } }
function onBlur() { setTimeout(() => { if (ed.value && document.activeElement !== (Array.isArray(edInput.value) ? edInput.value[0] : edInput.value)) commitEdit(); }, 120); }
function commitEdit() {
  const e = ed.value;
  if (!e) return;
  ed.value = null;
  const v = String(e.value ?? '').trim();
  if (v === e.orig) return;
  let declared = '';
  change((rs) => {
    const h = locate(rs, e.id);
    if (!h) return;
    const el = h.el;
    if (e.key === 'var') {
      el.var = v;
      if (v && /^[A-Za-z_][A-Za-z0-9_]*$/.test(v) && !sess.typeOf(v)) {
        S.program.vars.push({ name: v, type: 'BOOL', comment: '' });
        declared = v;
      }
    } else if (e.key === 'inst') {
      const old = el.inst;
      el.inst = v;
      const vv = S.program.vars.find((x: any) => x.name?.toUpperCase() === String(old || '').toUpperCase() && x.type === el.fb);
      if (vv && old && !rs.some((r: any) => flatten(r.elements).some((x: any) => x !== el && x.inst === old))) vv.name = v;
      else declareInst(el);
    } else if (e.key === 'title') {
      if (el.t === 'FB') {
        el.fb = v;
        const vv = S.program.vars.find((x: any) => x.name?.toUpperCase() === String(el.inst || '').toUpperCase());
        if (vv) vv.type = v;
        const d = FB_TYPES[v];
        for (const k of Object.keys(el.in || {})) if (!d.in.includes(k)) delete el.in[k];
        for (const k of Object.keys(el.out || {})) if (!d.out.includes(k)) delete el.out[k];
        if (d.in.includes('PT') && !el.in.PT) el.in.PT = 'T#2s';
        if (d.in.includes('PV') && !el.in.PV) el.in.PV = '10';
      } else el.op = v;
    } else if (e.key.startsWith('in:')) {
      const pin = e.key.slice(3);
      if (el.t === 'FB') { el.in ||= {}; if (v) el.in[pin] = v; else delete el.in[pin]; }
      else if (el.t === 'CMP' || el.t === 'MATH') { if (pin === 'IN1') el.a = v; else el.b = v; }
      else el.in = v;
    } else if (e.key.startsWith('out:')) {
      const pin = e.key.slice(4);
      if (el.t === 'FB') { el.out ||= {}; if (v) el.out[pin] = v; else delete el.out[pin]; }
      else el.out = v;
    }
  });
  if (declared) ElMessage({ type: 'info', message: $t('ladderEditor.created0BoolInThe', [declared]), duration: 2500 });
}
function startComment(ri: number) {
  if (ro.value) return;
  editComment.value = ri; cmtVal.value = rungs.value[ri]?.comment || '';
  nextTick(() => { const i = Array.isArray(cmtInput.value) ? cmtInput.value[0] : cmtInput.value; i?.focus(); });
}
function commitComment() {
  const ri = editComment.value;
  if (ri < 0) return;
  editComment.value = -1;
  if ((rungs.value[ri]?.comment || '') !== cmtVal.value) change((rs) => { rs[ri].comment = cmtVal.value; });
  focus();
}

// ---------------------------------------------------------------- Online: breakpoints, forcing
async function toggleBp(ri: number) {
  if (ro.value) return;
  if (!S.online || S.online.state === 'EXTERNAL') { ElMessage.info($t('ladderEditor.noProgramHasBeenDownloaded')); return; }
  await sess.act({ action: 'breakpoint', rung: ri, on: 'toggle' });
}
async function force(name: string, value: any) {
  try { await sess.act({ action: 'force', name, value }); } catch { /* Already notified */ }
}
async function writeVal(name: string) {
  try {
    const r: any = await ElMessageBox.prompt($t('ladderEditor.writeAValueTo0', [name]), $t('signals.write'), { inputValue: '' });
    await sess.act({ action: 'write', name, value: r.value });
  } catch { /* Cancel */ }
}
function menuEl(e: MouseEvent, p: any, ri: number) {
  if (!S.sel.includes(p.el.id)) S.sel = [p.el.id];
  curRung.value = ri;
  const v = p.el.var;
  const t = p.el.t;
  const items: any[] = [];
  if (!ro.value) {
    const TO: Record<string, string[]> = { NO: ['NC', 'P', 'N'], NC: ['NO', 'P', 'N'], P: ['NO', 'NC', 'N'], N: ['NO', 'NC', 'P'],
      COIL: ['NCOIL', 'SET', 'RESET'], NCOIL: ['COIL', 'SET', 'RESET'], SET: ['COIL', 'RESET', 'NCOIL'], RESET: ['COIL', 'SET', 'NCOIL'] };
    for (const x of TO[t] || []) items.push({ label: $t('ladderEditor.changeTo0', [T_CN[x]]), run: () => changeType(p.el.id, x) });
    if (items.length) items.push('-');
    items.push({ label: CONTACTS.includes(t) || COILS.includes(t) ? $t('ladderEditor.changeVariable') : $t('ladderEditor.editParameters'), key: 'Enter', run: () => editDefault(p, ri) },
      { label: $t('ladderEditor.insertNoContactBefore'), run: () => insertBefore(p.el.id, 'NO') },
      { label: $t('ladderEditor.insertNoContactAfter'), key: 'C', run: () => tool('NO') },
      { label: $t('ladderEditor.insertNcContactAfter'), key: 'X', run: () => tool('NC') },
      { label: $t('ladderEditor.parallelBranchAddAParallel'), key: 'V', run: () => parallel() },
      { label: $t('common.copy'), key: 'Ctrl+C', run: () => copy() },
      { label: $t('common.delete'), key: 'Del', run: () => del() });
  }
  const xv = v || p.el.inst || p.el.out;
  if (xv && /^[A-Za-z_%]/.test(xv)) items.push('-', { label: $t('ladderEditor.crossReferenceWhere0Is', [String(xv).split('.')[0]]), run: () => emit('xref', String(xv).split('.')[0]) });
  if (v && isOnline.value && !ro.value) {
    items.push('-',
      { label: $t('ladderEditor.force0True', [v]), run: () => force(v, true) },
      { label: $t('ladderEditor.force0False', [v]), run: () => force(v, false) },
      { label: $t('ladderEditor.unforce0', [v]), dis: !isForced(v), run: () => force(v, null) },
      { label: $t('ladderEditor.writeTo0', [v]), run: () => writeVal(v) });
  }
  if (p.el.t === 'FB' && isOnline.value && !ro.value) items.push('-', { label: $t('ladderEditor.writeTo01', [p.el.inst, FB_TYPES[p.el.fb]?.in.includes('PT') ? 'PT' : 'PV']), run: () => writeVal(`${p.el.inst}.${FB_TYPES[p.el.fb]?.in.includes('PT') ? 'PT' : 'PV'}`) });
  openMenu(e, items);
}
function changeType(id: string, t: string) {
  change((rs) => { const h = locate(rs, id); if (h) h.el.t = t; });
}
function insertBefore(id: string, t: string) {
  if (ro.value) return;
  const el = makeEl(t);
  change((rs) => { const h = locate(rs, id); if (h) h.list.splice(h.index, 0, el); });
  S.sel = [el.id];
  nextTick(() => editDefaultById(el.id));
}
function menuRung(e: MouseEvent, ri: number) {
  selectRung(ri);
  if (ro.value) return;
  openMenu(e, [
    { label: $t('ladderEditor.insertRungBelow'), key: 'Ctrl+Enter', run: () => newRung(ri) },
    { label: $t('ladderEditor.insertRungAbove'), run: () => { change((rs) => rs.splice(ri, 0, { comment: '', elements: [] })); S.selRung = ri; } },
    { label: $t('ladderEditor.editComment'), run: () => startComment(ri) },
    { label: $t('ladderEditor.copyRung'), key: 'Ctrl+C', run: () => copy() },
    { label: $t('contextMenu.paste'), key: 'Ctrl+V', dis: !S.clip, run: () => paste() },
    { label: $t('ladderEditor.deleteRung'), key: 'Del', run: () => del() },
    '-',
    { label: bps.value.has(ri + 1) ? $t('ladderEditor.removeBreakpoint') : $t('graphdebug.setBreakpoint'), run: () => toggleBp(ri) },
  ]);
}
function openMenu(e: MouseEvent, items: any[]) {
  const host = (e.currentTarget as Element).closest('.lde') as HTMLElement;
  const rc = host.getBoundingClientRect();
  menu.value = { x: Math.min(e.clientX - rc.left, rc.width - 220), y: Math.min(e.clientY - rc.top, rc.height - items.length * 28 - 10), items };
}

// ---------------------------------------------------------------- Dimensions
let resizeObs: ResizeObserver | null = null;
const closeMenu = () => { menu.value = null; };
onMounted(() => {
  resizeObs = new ResizeObserver(() => { if (scroller.value) width.value = scroller.value.clientWidth - 70; });
  if (scroller.value) { resizeObs.observe(scroller.value); width.value = scroller.value.clientWidth - 70; }
  addEventListener('mousedown', closeMenu);
});
onBeforeUnmount(() => { resizeObs?.disconnect(); removeEventListener('mousedown', closeMenu); });
watch(() => S.program, () => { S.sel = S.sel.filter((id) => locate(rungs.value, id)); });
defineExpose({ newRung, tool, focus });
void newId;
</script>

<style scoped>
.lde { position: relative; display: flex; flex-direction: column; height: 100%; min-height: 0; background: var(--ld-bg); color: var(--ld-tx); user-select: none; }
.lde-tools { display: flex; align-items: center; flex-wrap: wrap; gap: 2px; padding: 4px 8px; border-bottom: 1px solid var(--ld-ln); background: var(--ld-bar); }
.tg { display: flex; gap: 2px; }
.tsep { width: 1px; height: 30px; background: var(--ld-ln); margin: 0 4px; }
.tb { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0; min-width: 44px; height: 40px; padding: 2px 4px; border: 1px solid transparent;
  border-radius: 5px; background: none; color: var(--ld-tx); cursor: pointer; font-size: 10.5px; font-family: inherit; }
.tb:hover:not(:disabled) { background: var(--ld-hov); border-color: var(--ld-ln); }
.tb:disabled { opacity: .35; cursor: default; }
.tb.ic { min-width: 30px; font-size: 16px; }
.tb svg :deep(line), .tb svg :deep(path), .tb svg :deep(rect) { stroke: currentColor; stroke-width: 1.6; fill: none; }
.tb svg :deep(text) { fill: currentColor; font-size: 10px; font-weight: 700; font-family: Consolas, monospace; stroke: none; }
.tb svg :deep(.fill), .tb svg :deep(.fillc) { stroke: none; fill: none; }
.lde-body { flex: 1; min-height: 0; overflow: auto; outline: none; padding: 6px 10px 20px 6px; }
.rung { margin: 0 0 6px; border: 1px solid var(--ld-ln); border-left: 3px solid var(--ld-ln); border-radius: 4px; background: var(--ld-card); }
.rung.selr { border-color: var(--ld-sel); border-left-color: var(--ld-sel); }
.rung.err { border-left-color: var(--ld-bad); }
.rung.halt { border-left-color: var(--ld-halt); box-shadow: 0 0 0 1px var(--ld-halt); }
.rh { display: flex; align-items: center; gap: 8px; height: 26px; padding: 0 8px 0 4px; border-bottom: 1px dashed var(--ld-ln); font-size: 12px; overflow: hidden; }
.bpdot { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid var(--ld-mu); flex: none; cursor: pointer; opacity: .55; }
.bpdot:hover { opacity: 1; border-color: var(--ld-bad); }
.rung.bp .bpdot { background: var(--ld-bad); border-color: var(--ld-bad); opacity: 1; }
.rn { font-weight: 600; white-space: nowrap; color: var(--ld-tx); }
.haltb { color: #1f2933; background: var(--ld-halt); border-radius: 3px; padding: 0 6px; font-size: 11px; white-space: nowrap; }
.rpow { font-size: 10.5px; padding: 0 5px; border-radius: 3px; background: var(--ld-hov); color: var(--ld-mu); }
.rpow.on { background: var(--ld-pow-bg); color: var(--ld-pow); }
.cmt { color: var(--ld-cmt); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: text; flex: 1; min-width: 40px; }
.cmt.empty { color: var(--ld-mu); opacity: .5; font-style: italic; }
.cmt-in { flex: 1; height: 20px; border: 1px solid var(--ld-sel); border-radius: 3px; background: var(--ld-card); color: var(--ld-tx); padding: 0 6px; font: inherit; outline: none; }
.rmsg { font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 40%; }
.rmsg.err { color: var(--ld-bad); } .rmsg.warn { color: var(--ld-warn); }
.rd { position: relative; overflow: visible; }
.rsvg { display: block; overflow: visible; }
.rail { stroke: var(--ld-rail); stroke-width: 3; }
.rail.p { stroke: var(--ld-pow); }
.wire { stroke: var(--ld-wire); stroke-width: 1.6; }
.wire.p { stroke: var(--ld-pow); stroke-width: 3; }
.wire.np { stroke: var(--ld-wire-off); }
.stub { stroke: var(--ld-wire); stroke-width: 1.2; }
.el { cursor: pointer; }
.el .hit { fill: transparent; stroke: none; }
.el:hover .hit { fill: var(--ld-hov); }
.el.sel .hit { fill: var(--ld-selbg); stroke: var(--ld-sel); stroke-width: 1.2; }
.el.e .hit { stroke: var(--ld-bad); stroke-dasharray: 4 3; stroke-width: 1.4; fill: var(--ld-bad-bg); }
.el.dg .hit { stroke: var(--ld-bad); stroke-width: 2.2; fill: var(--ld-bad-bg); animation: ld-dg 1.2s ease-in-out infinite; }
.el.dg .opnd { fill: var(--ld-bad); font-weight: 700; }
@keyframes ld-dg { 50% { stroke-opacity: .35; } }
.rdiag { font-size: 11px; color: var(--ld-bad); background: var(--ld-bad-bg); border-radius: 3px; padding: 0 6px; white-space: nowrap; cursor: help; }
.rexp { flex: none; border: 1px solid var(--ld-ln2); background: var(--ld-card); color: var(--ld-mu); border-radius: 3px; font-size: 11px; height: 18px; padding: 0 6px;
  cursor: pointer; margin-left: auto; order: 9; }
.rexp:hover, .rexp.on { color: var(--ld-sel); border-color: var(--ld-sel); }
.rexpl { margin: 0 8px 4px 22px; padding: 6px 10px; border: 1px solid var(--ld-ln); border-left: 3px solid var(--ld-sel); border-radius: 4px; background: var(--ld-info-bg);
  font-size: 12px; line-height: 1.65; color: var(--ld-tx); white-space: pre-wrap; }
.rexpl-s { margin-top: 3px; font-weight: 600; }
.rexpl-f { margin-top: 3px; font-size: 11px; } .rexpl-f a { cursor: pointer; color: var(--ld-sel); }
.sym :deep(line), .sym :deep(path) { stroke: var(--ld-sym); stroke-width: 2; fill: none; }
.sym :deep(text) { fill: var(--ld-sym); font: 700 12px Consolas, monospace; }
.sym :deep(.fill), .sym :deep(.fillc) { fill: transparent; stroke: none; }
.sym.closed :deep(.fill) { fill: var(--ld-pow-bg); }
.sym.closed :deep(line), .sym.closed :deep(path) { stroke: var(--ld-pow); }
.el.coil .sym.closed :deep(.fillc) { fill: var(--ld-pow-bg); }
.opnd { fill: var(--ld-op); font: 600 12.5px Consolas, "Microsoft YaHei", monospace; cursor: text; }
.opnd.sm { font-size: 11.5px; font-weight: 500; }
.opnd.ph { fill: var(--ld-bad); }
.opnd.forced { fill: var(--ld-force); }
.addr { fill: var(--ld-mu); font: 10.5px Consolas, monospace; }
.inst { fill: var(--ld-op); font: 700 12px Consolas, monospace; cursor: text; }
.inst.ph { fill: var(--ld-bad); }
.box { fill: var(--ld-box); stroke: var(--ld-sym); stroke-width: 1.4; }
.boxh { fill: var(--ld-boxh); stroke: none; }
.btitle { fill: var(--ld-tx); font: 700 12px Consolas, monospace; cursor: pointer; }
.pinl { fill: var(--ld-mu); font: 10.5px Consolas, monospace; }
.live { fill: var(--ld-live); font: 600 10.5px Consolas, monospace; }
.fbadge { fill: var(--ld-force); }
.fbt { fill: #fff; font: 700 10px Consolas, monospace; }
.drop { fill: var(--ld-selbg); stroke: var(--ld-sel); stroke-width: 1; stroke-dasharray: 3 2; }
.drop.hov { fill: var(--ld-in-bg); }
.dropp { fill: var(--ld-pow-bg); stroke: var(--ld-pow); stroke-width: 1; stroke-dasharray: 3 2; }
.dropp.hov { fill: var(--ld-pow-bg); }
.empty-r { position: absolute; left: 160px; top: 8px; right: 30px; display: flex; align-items: center; gap: 10px; padding: 4px 10px; border-radius: 5px;
  background: var(--ld-card); color: var(--ld-mu); font-size: 12px; border: 1px dashed var(--ld-ln2); }
.empty-r kbd { font: 11px Consolas, monospace; padding: 0 4px; border: 1px solid var(--ld-ln2); border-radius: 3px; background: var(--ld-bar); color: var(--ld-tx); }
.empty-r .plc-btn { height: 24px; flex: none; }
.rung-add { margin: 2px 0 8px; padding: 6px; text-align: center; border: 1px dashed var(--ld-ln); border-radius: 4px; color: var(--ld-mu); cursor: pointer; }
.rung-add:hover { border-color: var(--ld-sel); color: var(--ld-tx); }
.hint { font-size: 11px; padding: 0 4px; line-height: 1.6; }
.muted { color: var(--ld-mu); }
.opedit { position: absolute; z-index: 5; }
.op-in { width: 100%; height: 24px; border: 1.5px solid var(--ld-sel); border-radius: 3px; background: var(--ld-card); color: var(--ld-tx); padding: 0 6px; font-size: 12.5px; outline: none;
  box-shadow: 0 2px 10px var(--ld-shadow); }
.ac { position: absolute; top: 26px; left: 0; min-width: 260px; max-height: 260px; overflow: auto; background: var(--ld-card); border: 1px solid var(--ld-ln); border-radius: 4px;
  box-shadow: 0 6px 18px var(--ld-shadow); }
.ac-i { display: flex; gap: 8px; align-items: baseline; padding: 3px 8px; cursor: pointer; white-space: nowrap; }
.ac-i.gs { border-top: 1px solid var(--ld-ln); }
.ac-i .g { flex: none; width: 28px; font-style: normal; font-size: 10.5px; color: var(--ld-mu); }
.lde-ro { padding: 6px 10px; font-size: 12px; border-bottom: 1px solid var(--ld-ln); background: var(--ld-info-bg); color: var(--ld-tx); }
.ac-i.on, .ac-i:hover { background: var(--ld-selbg); }
.ac-i small { color: var(--ld-in); font-size: 10.5px; } .ac-i i { color: var(--ld-mu); font-style: normal; font-size: 11px; overflow: hidden; text-overflow: ellipsis; }
.ctx { position: absolute; z-index: 20; min-width: 200px; padding: 4px 0; background: var(--ld-card); border: 1px solid var(--ld-ln); border-radius: 6px; box-shadow: 0 8px 24px var(--ld-shadow); font-size: 12.5px; }
.ctx .it { display: flex; justify-content: space-between; gap: 16px; padding: 5px 12px; cursor: pointer; }
.ctx .it:hover { background: var(--ld-selbg); } .ctx .it.dis { opacity: .4; cursor: default; }
.ctx .it small { color: var(--ld-mu); }
.ctx .sep { height: 1px; margin: 4px 0; background: var(--ld-ln); }
.mono { font-family: Consolas, monospace; }
.grow { flex: 1; }
</style>
