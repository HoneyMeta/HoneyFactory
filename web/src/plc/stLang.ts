// CodeMirror 6 language support for Structured Text (IEC 61131-3 ST): highlighting, autocomplete, snippets.
import { $t } from '../i18n';
import { autocompletion, CompletionContext, snippetCompletion } from '@codemirror/autocomplete';
import { HighlightStyle, StreamLanguage, syntaxHighlighting } from '@codemirror/language';
import { tags as t } from '@lezer/highlight';

const KW = new Set(('PROGRAM END_PROGRAM VAR VAR_INPUT VAR_OUTPUT VAR_IN_OUT VAR_GLOBAL VAR_TEMP VAR_EXTERNAL END_VAR RETAIN NON_RETAIN PERSISTENT CONSTANT AT ' +
  'IF THEN ELSIF ELSE END_IF CASE OF END_CASE FOR TO BY DO END_FOR WHILE END_WHILE REPEAT UNTIL END_REPEAT EXIT CONTINUE RETURN ARRAY').split(' '));
const OPW = new Set(['AND', 'OR', 'XOR', 'NOT', 'MOD']);
const TYPES = new Set('BOOL SINT INT DINT LINT USINT UINT UDINT ULINT BYTE WORD DWORD LWORD REAL LREAL TIME STRING'.split(' '));
const FBS = new Set('TON TOF TP CTU CTD CTUD R_TRIG F_TRIG SR RS'.split(' '));
const FUNCS = new Set('ABS MIN MAX LIMIT SEL MUX SQRT LN LOG EXP SIN COS TAN ASIN ACOS ATAN EXPT TRUNC SHL SHR ROL ROR MOVE'.split(' '));

type St = { comment: boolean };
export const stLanguage = StreamLanguage.define<St>({
  name: 'st',
  startState: () => ({ comment: false }),
  token(s, st) {
    if (st.comment) {
      if (s.skipTo('*)') || s.skipTo('*/')) { s.next(); s.next(); st.comment = false; } else s.skipToEnd();
      return 'comment';
    }
    if (s.eatSpace()) return null;
    if (s.match('(*') || s.match('/*')) { st.comment = true; return 'comment'; }
    if (s.match('//')) { s.skipToEnd(); return 'comment'; }
    if (s.match(/^'[^']*'?/)) return 'string';
    if (s.match(/^(T|TIME|LT|LTIME)#-?[\d.]+[a-z]*(?:[\d.]+[a-z]+)*/i)) return 'number';
    if (s.match(/^%[IQM][XBWDL]?\d+(\.\d+)?/i)) return 'atom';
    if (s.match(/^(2|8|16)#[0-9A-F_]+/i) || s.match(/^\d[\d_]*(\.\d[\d_]*)?(E[+-]?\d+)?/i)) return 'number';
    if (s.match(/^[A-Za-z_][A-Za-z0-9_]*#/)) return 'typeName';
    if (s.match(/^[A-Za-z_][A-Za-z0-9_]*/)) {
      const w = s.current().toUpperCase();
      if (w === 'TRUE' || w === 'FALSE') return 'bool';
      if (KW.has(w)) return 'keyword';
      if (OPW.has(w)) return 'operatorKeyword';
      if (TYPES.has(w)) return 'typeName';
      if (FBS.has(w)) return 'className';
      if (FUNCS.has(w) || /_TO_/.test(w)) return 'macroName';
      return 'variableName';
    }
    if (s.match(':=') || s.match('=>') || s.match('<>') || s.match('<=') || s.match('>=') || s.match('**')) return 'operator';
    s.next();
    return /[+\-*/=<>&]/.test(s.current()) ? 'operator' : 'punctuation';
  },
  languageData: { commentTokens: { line: '//', block: { open: '(*', close: '*)' } } },
});

export const stHighlight = HighlightStyle.define([
  { tag: t.keyword, color: 'var(--st-kw)', fontWeight: '600' },
  { tag: t.operatorKeyword, color: 'var(--st-kw)', fontWeight: '600' },
  { tag: t.comment, color: 'var(--st-cmt)', fontStyle: 'italic' },
  { tag: t.string, color: 'var(--st-str)' },
  { tag: t.number, color: 'var(--st-num)' },
  { tag: t.bool, color: 'var(--st-num)', fontWeight: '600' },
  { tag: t.atom, color: 'var(--st-addr)' },
  { tag: t.typeName, color: 'var(--st-type)' },
  { tag: t.className, color: 'var(--st-fb)', fontWeight: '600' },
  { tag: t.macroName, color: 'var(--st-fn)' },
  { tag: t.variableName, color: 'var(--st-var)' },
  { tag: t.operator, color: 'var(--st-op)' },
]);

export const FB_DOC: Record<string, string> = {
  TON: $t('stLang.tonOnDelayQBecomes'), TOF: $t('stLang.tofOffDelayQBecomes'), TP: $t('stLang.tpPulseARisingEdge'),
  CTU: $t('stLang.ctuUpCounterARising'), CTD: $t('stLang.ctdDownCounterARising'),
  CTUD: $t('stLang.ctudUpDownCounter'), R_TRIG: $t('stLang.rTrigRisingEdgeQ'), F_TRIG: $t('stLang.fTrigFallingEdge'), SR: $t('stLang.srSetDominantLatch'), RS: $t('stLang.rsResetDominantLatch'),
};
const FB_CALL: Record<string, string> = {
  TON: '(IN := ${}, PT := T#${2s});', TOF: '(IN := ${}, PT := T#${2s});', TP: '(IN := ${}, PT := T#${1s});', CTU: '(CU := ${}, R := ${}, PV := ${10});',
  CTD: '(CD := ${}, LD := ${}, PV := ${10});', CTUD: '(CU := ${}, CD := ${}, R := ${}, LD := ${}, PV := ${10});', R_TRIG: '(CLK := ${});', F_TRIG: '(CLK := ${});',
  SR: '(S1 := ${}, R := ${});', RS: '(S := ${}, R1 := ${});',
};
const FB_MEM: Record<string, string[]> = { TON: ['Q', 'ET', 'IN', 'PT'], TOF: ['Q', 'ET', 'IN', 'PT'], TP: ['Q', 'ET', 'IN', 'PT'], CTU: ['Q', 'CV', 'CU', 'R', 'PV'],
  CTD: ['Q', 'CV', 'CD', 'LD', 'PV'], CTUD: ['QU', 'QD', 'CV', 'PV'], R_TRIG: ['Q', 'CLK'], F_TRIG: ['Q', 'CLK'], SR: ['Q1'], RS: ['Q1'] };

const SNIPS = [
  snippetCompletion($t('stLang.ifConditionThenEndIf'), { label: 'IF', detail: $t('details.condition'), type: 'keyword' }),
  snippetCompletion($t('stLang.ifConditionThenElseEnd'), { label: 'IF…ELSE', detail: $t('stLang.conditionalBranch'), type: 'keyword' }),
  snippetCompletion($t('stLang.caseStateOf01'), { label: 'CASE', detail: $t('stLang.stateMachine'), type: 'keyword' }),
  snippetCompletion('FOR ${i} := ${1} TO ${10} DO\n\t${}\nEND_FOR;', { label: 'FOR', detail: $t('stLang.loop'), type: 'keyword' }),
  snippetCompletion($t('stLang.whileConditionDoEndWhile'), { label: 'WHILE', detail: $t('stLang.loop'), type: 'keyword' }),
  snippetCompletion($t('stLang.repeatUntilConditionEndRepeat'), { label: 'REPEAT', detail: $t('stLang.loop'), type: 'keyword' }),
  snippetCompletion($t('stLang.varNameBoolEndVar'), { label: 'VAR', detail: $t('stLang.variableDeclaration'), type: 'keyword' }),
];
const WORDS = [...KW, ...OPW, 'TRUE', 'FALSE'].map((w) => ({ label: w, type: 'keyword' }));
const TYPEC = [...TYPES].map((w) => ({ label: w, type: 'type' }));
const FBC = [...FBS].map((w) => ({ label: w, type: 'class', info: FB_DOC[w] }));
const FNC = [...FUNCS].map((w) => ({ label: w, type: 'function', apply: w + '(' }));

/** symbols() → [{name, type, info}] */
export function stCompletion(symbols: () => { name: string; type: string; info: string }[]) {
  return autocompletion({
    activateOnTyping: true,
    override: [(ctx: CompletionContext) => {
      const mem = ctx.matchBefore(/[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z0-9_]*/);
      const syms = symbols();
      if (mem) {
        const [base] = mem.text.split('.');
        const s = syms.find((x) => x.name.toUpperCase() === base.toUpperCase());
        const m = s ? FB_MEM[s.type] : null;
        if (m) return { from: mem.from + base.length + 1, options: m.map((x) => ({ label: x, type: 'property', detail: s!.type })) };
        return null;
      }
      const w = ctx.matchBefore(/[A-Za-z_%][A-Za-z0-9_.%]*/);
      if (!w || (w.from === w.to && !ctx.explicit)) return null;
      const line = ctx.state.doc.lineAt(ctx.pos).text;
      const callCtx = /^\s*[A-Za-z_][A-Za-z0-9_]*$/.test(line.slice(0, ctx.pos - ctx.state.doc.lineAt(ctx.pos).from));
      const opts: any[] = syms.filter((s) => !s.name.includes('.')).map((s) => {
        const call = FB_CALL[s.type];
        if (call && callCtx) return snippetCompletion(s.name + call, { label: s.name, detail: s.type, info: s.info || FB_DOC[s.type], type: 'variable', boost: 3 });
        return { label: s.name, detail: s.type, info: s.info, type: 'variable', boost: 3 };
      });
      return { from: w.from, options: [...opts, ...SNIPS, ...WORDS, ...TYPEC, ...FBC, ...FNC], validFor: /^[A-Za-z0-9_]*$/ };
    }],
  });
}

export const stSyntax = syntaxHighlighting(stHighlight);
