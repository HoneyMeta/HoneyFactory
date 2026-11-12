<template>
  <div class="ste">
    <div ref="host" class="ste-host" />
  </div>
</template>

<script setup lang="ts">
import { $t } from '../i18n';
// Structured Text editor (CodeMirror 6): syntax highlighting, autocomplete, compile error markers, breakpoints (click left of line numbers), paused-line highlighting, and live values after variables.
import { closeBrackets, completionKeymap } from '@codemirror/autocomplete';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
import { bracketMatching, indentOnInput, indentUnit } from '@codemirror/language';
import { lintGutter, setDiagnostics } from '@codemirror/lint';
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search';
import { EditorState, RangeSetBuilder, StateEffect, StateField } from '@codemirror/state';
import { Decoration, DecorationSet, drawSelection, EditorView, gutter, GutterMarker, highlightActiveLine, highlightActiveLineGutter, keymap, lineNumbers,
  ViewPlugin, ViewUpdate, WidgetType } from '@codemirror/view';
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { canEdit } from '../api';
import { FB_FIELD_TYPE, fmtVal } from './plcApi';
import type { Sess } from './session';
import { stCompletion, stLanguage, stSyntax } from './stLang';

const props = defineProps<{ sess: Sess; readonly?: boolean }>();
const ro = computed(() => !!props.readonly || !canEdit());
const sess = props.sess;
const S = sess.s;
const host = ref<HTMLElement>();
let view: EditorView | null = null;
let applying = false;

// ---- Breakpoints
const setBps = StateEffect.define<number[]>();
const bpField = StateField.define<Set<number>>({
  create: () => new Set(),
  update(v, tr) { for (const e of tr.effects) if (e.is(setBps)) return new Set(e.value); return v; },
});
class BpMarker extends GutterMarker { toDOM() { const d = document.createElement('span'); d.className = 'st-bp'; return d; } }
const bpMarker = new BpMarker();
const bpGutter = gutter({
  class: 'st-bpg',
  markers: (v) => {
    const b = new RangeSetBuilder<GutterMarker>();
    const set = v.state.field(bpField);
    for (let i = 1; i <= v.state.doc.lines; i++) if (set.has(i)) { const l = v.state.doc.line(i); b.add(l.from, l.from, bpMarker); }
    return b.finish();
  },
  initialSpacer: () => bpMarker,
  domEventHandlers: {
    mousedown(v, line) {
      const ln = v.state.doc.lineAt(line.from).number;
      toggleBp(ln);
      return true;
    },
  },
});

// ---- Paused line
const setHalt = StateEffect.define<number>();
const haltField = StateField.define<DecorationSet>({
  create: () => Decoration.none,
  update(v, tr) {
    for (const e of tr.effects) if (e.is(setHalt)) {
      if (e.value <= 0 || e.value > tr.state.doc.lines) return Decoration.none;
      const l = tr.state.doc.line(e.value);
      return Decoration.set([Decoration.line({ class: 'st-halt' }).range(l.from)]);
    }
    return v.map(tr.changes);
  },
  provide: (f) => EditorView.decorations.from(f),
});

// ---- Live values
const setOnline = StateEffect.define<any>();
const onlineField = StateField.define<any>({
  create: () => null,
  update(v, tr) { for (const e of tr.effects) if (e.is(setOnline)) return e.value; return v; },
});
class ValW extends WidgetType {
  constructor(readonly text: string, readonly cls: string) { super(); }
  eq(o: ValW) { return o.text === this.text && o.cls === this.cls; }
  toDOM() { const s = document.createElement('span'); s.className = 'st-val ' + this.cls; s.textContent = this.text; return s; }
  ignoreEvent() { return true; }
}
function valueOf(on: any, name: string): [string, string] | null {
  const vars = on.vars || {};
  const types = on.types || {};
  const up = name.toUpperCase();
  if (up.includes('.')) {
    const [b, f] = name.split('.');
    const k = Object.keys(vars).find((x) => x.toUpperCase() === b.toUpperCase());
    const v = k ? vars[k]?.[f.toUpperCase()] : undefined;
    if (v === undefined) return null;
    return [fmtVal(v, FB_FIELD_TYPE[f.toUpperCase()]), typeof v === 'boolean' ? (v ? 't' : 'f') : 'n'];
  }
  const k = Object.keys(vars).find((x) => x.toUpperCase() === up);
  if (!k) return null;
  const v = vars[k];
  if (v && typeof v === 'object') return null;
  const forced = Object.keys(on.forced || {}).some((x) => x.toUpperCase() === up);
  return [fmtVal(v, types[k]) + (forced ? ' F' : ''), (typeof v === 'boolean' ? (v ? 't' : 'f') : 'n') + (forced ? ' forced' : '')];
}
const onlinePlugin = ViewPlugin.fromClass(class {
  deco: DecorationSet;
  constructor(v: EditorView) { this.deco = this.build(v); }
  update(u: ViewUpdate) { if (u.docChanged || u.viewportChanged || u.transactions.some((t) => t.effects.some((e) => e.is(setOnline)))) this.deco = this.build(u.view); }
  build(v: EditorView) {
    const on = v.state.field(onlineField);
    if (!on) return Decoration.none;
    const b = new RangeSetBuilder<Decoration>();
    for (const { from, to } of v.visibleRanges) {
      const text = v.state.doc.sliceString(from, to);
      const re = /(\(\*[\s\S]*?\*\)|\/\/[^\n]*|'[^']*')|(%[IQM][XBWD]?\d+(?:\.\d+)?|[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)/g;
      let m: RegExpExecArray | null;
      let inVar = false;
      let n = 0;
      while ((m = re.exec(text)) && n < 400) {
        if (m[1]) continue;
        const w = m[2];
        const W = w.toUpperCase();
        if (W === 'VAR' || W.startsWith('VAR_')) inVar = true;
        if (W === 'END_VAR') { inVar = false; continue; }
        if (inVar) continue;
        const r = valueOf(on, w);
        if (!r) continue;
        const pos = from + m.index + w.length;
        b.add(pos, pos, Decoration.widget({ widget: new ValW(r[0], r[1]), side: 1 }));
        n++;
      }
    }
    return b.finish();
  }
}, { decorations: (p) => p.deco });

function toggleBp(line: number) {
  if (ro.value) return;
  if (!S.online || !['RUN', 'STOP', 'HALT', 'ERROR'].includes(S.online.state)) return;
  sess.act({ action: 'breakpoint', line, on: 'toggle' }, true);
}

function mkState(doc: string) {
  return EditorState.create({
    doc,
    extensions: [
      bpField, bpGutter, lineNumbers(), highlightActiveLineGutter(), lintGutter(), history(), drawSelection(), indentOnInput(), bracketMatching(), closeBrackets(),
      highlightActiveLine(), highlightSelectionMatches(), indentUnit.of('    '), EditorState.tabSize.of(4),
      EditorState.readOnly.of(ro.value), EditorView.editable.of(!ro.value),
      stLanguage, stSyntax, stCompletion(() => sess.symbols()), haltField, onlineField, onlinePlugin,
      keymap.of([...completionKeymap, ...defaultKeymap, ...historyKeymap, ...searchKeymap, indentWithTab,
        { key: 'Mod-s', run: () => { sess.save(); return true; } }]),
      EditorView.updateListener.of((u) => {
        if (u.docChanged && !applying) {
          const txt = u.state.doc.toString();
          if (S.program && S.program.source !== txt) { S.program.source = txt; S.rev++; }
        }
      }),
    ],
  });
}

function syncDiagnostics() {
  if (!view) return;
  const doc = view.state.doc;
  const ds: any[] = [];
  const add = (e: any, severity: 'error' | 'warning') => {
    if (!e.line || e.line > doc.lines) return;
    const l = doc.line(e.line);
    const from = Math.min(l.to, l.from + Math.max(0, (e.col || 1) - 1));
    let to = from;
    const m = /^[A-Za-z0-9_%.#]+/.exec(doc.sliceString(from, l.to));
    to = m ? from + m[0].length : Math.min(l.to, from + 1);
    if (to === from) { if (from > l.from) return ds.push({ from: from - 1, to: from, severity, message: e.msg }); to = l.to; }
    ds.push({ from, to: Math.max(to, from), severity, message: e.msg });
  };
  for (const e of S.errors || []) add(e, 'error');
  for (const e of S.warnings || []) add(e, 'warning');
  const dg = (S as any).diag;                    // 4.5 "Why no response": highlight the diagnostic target line in red
  if (dg?.line) add({ line: dg.line, col: 1, msg: $t('plcWorkbench.diagnostics') + dg.msg }, 'error');
  view.dispatch(setDiagnostics(view.state, ds));
}
function syncOnline() {
  if (!view) return;
  const on = S.online && S.monitor && S.online.lang === 'ST' ? S.online : null;
  const halt = on?.state === 'HALT' && on.halt?.mid_scan ? on.halt.line : 0;
  view.dispatch({ effects: [setOnline.of(on), setBps.of(on?.bps || []), setHalt.of(halt)] });
}

onMounted(() => {
  view = new EditorView({ state: mkState(S.program?.source || ''), parent: host.value! });
});
onBeforeUnmount(() => { view?.destroy(); view = null; });
// Program changed externally (undo, import, reload)
watch(() => S.rev, () => {
  if (!view || !S.program || S.program.lang !== 'ST') return;
  const cur = view.state.doc.toString();
  if (cur !== S.program.source) {
    applying = true;
    view.dispatch({ changes: { from: 0, to: cur.length, insert: S.program.source || '' } });
    applying = false;
  }
});
watch(() => [S.errors, S.warnings, (S as any).diag], syncDiagnostics, { deep: false });
watch(() => [S.online, S.monitor], syncOnline);

function gotoLine(line: number) {
  if (!view || line < 1 || line > view.state.doc.lines) return;
  const l = view.state.doc.line(line);
  view.dispatch({ selection: { anchor: l.from }, scrollIntoView: true });
  view.focus();
}
function insertText(s: string) {
  if (!view) return;
  const r = view.state.selection.main;
  view.dispatch({ changes: { from: r.from, to: r.to, insert: s }, selection: { anchor: r.from + s.length } });
  view.focus();
}
defineExpose({ gotoLine, insertText });
</script>

<style scoped>
.ste { height: 100%; min-height: 0; display: flex; flex-direction: column; background: var(--ld-card); }
.ste-host { flex: 1; min-height: 0; overflow: hidden; }
.ste-host :deep(.cm-editor) { height: 100%; font-size: 13.5px; background: var(--ld-card); color: var(--st-var); }
.ste-host :deep(.cm-scroller) { font-family: Consolas, "Cascadia Mono", "Microsoft YaHei", monospace; line-height: 1.55; }
.ste-host :deep(.cm-gutters) { background: var(--ld-bar); border-right: 1px solid var(--ld-ln); color: var(--ld-mu); }
.ste-host :deep(.cm-activeLine) { background: var(--st-active); }
.ste-host :deep(.cm-activeLineGutter) { background: var(--st-active); }
.ste-host :deep(.cm-cursor) { border-left-color: var(--ld-tx); }
.ste-host :deep(.cm-selectionBackground), .ste-host :deep(.cm-focused .cm-selectionBackground) { background: var(--st-selection) !important; }
.ste-host :deep(.st-bpg) { width: 16px; cursor: pointer; }
.ste-host :deep(.st-bpg .cm-gutterElement) { display: flex; align-items: center; justify-content: center; }
.ste-host :deep(.st-bp) { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: var(--ld-bad); }
.ste-host :deep(.st-halt) { background: var(--ld-halt-bg) !important; box-shadow: inset 3px 0 0 var(--ld-halt); }
.ste-host :deep(.st-val) { display: inline-block; margin: 0 2px 0 3px; padding: 0 4px; border-radius: 3px; font-size: 11px; line-height: 15px; vertical-align: 1px;
  background: var(--ld-hov); color: var(--ld-tx); font-family: Consolas, monospace; }
.ste-host :deep(.st-val.t) { background: var(--ld-pow-bg); color: var(--ld-pow); }
.ste-host :deep(.st-val.f) { background: var(--ld-hov); color: var(--ld-mu); }
.ste-host :deep(.st-val.forced) { outline: 1px solid var(--ld-force); color: var(--ld-force); }
.ste-host :deep(.cm-tooltip) { background: var(--ld-card); border: 1px solid var(--ld-ln); color: var(--ld-tx); }
.ste-host :deep(.cm-tooltip-autocomplete ul li[aria-selected]) { background: var(--st-selection); color: var(--ld-tx); }
.ste-host :deep(.cm-completionDetail) { color: var(--ld-in); font-style: normal; margin-left: 8px; }
.ste-host :deep(.cm-diagnostic-error) { border-left-color: var(--ld-bad); }
.ste-host :deep(.cm-lintRange-error) { background-image: none; text-decoration: underline wavy var(--ld-bad); text-underline-offset: 3px; }
.ste-host :deep(.cm-lintRange-warning) { background-image: none; text-decoration: underline wavy var(--ld-warn); text-underline-offset: 3px; }
.ste-host :deep(.cm-matchingBracket) { background: var(--st-selection); outline: none; }
.ste-host :deep(.cm-searchMatch) { background: var(--ld-halt-bg); }
</style>
