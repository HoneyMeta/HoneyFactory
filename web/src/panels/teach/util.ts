// Shared utilities for teaching / design / integration test panels.
import { $t, localize, variants } from '../../i18n';
import { ElMessage } from 'element-plus';
import { session } from '../../api';
import { native } from '../../native';

export const isTeacher = () => ['teacher', 'admin'].includes(session.user?.role);
export const isStudent = () => session.user?.role === 'student';
export const isEngineer = () => ['engineer', 'admin'].includes(session.user?.role);

// Student progress states. Rows carry `state_code` (and the response `counts_code`); older servers only send the display text `state`
// (Chinese, or English) - both are accepted.
const STU_STATES: [string, string, string][] = [
  ['not_started', 'courseHome.notStarted', 'var(--el-text-color-placeholder)'], ['no_program', 'teachUtil.noProgramDownloaded', 'var(--warn, var(--el-color-warning))'],
  ['in_progress', 'common.inProgress', 'var(--el-color-primary)'], ['sleeping', 'teachUtil.sleeping', 'var(--el-color-info)'], ['stuck', 'common.stuck', 'var(--bad, var(--el-color-danger))'],
  ['submitted', 'classProgress.submitted', 'var(--warn, var(--el-color-warning))'], ['full_score', 'teachUtil.fullScore', 'var(--ok, var(--el-color-success))'],
  ['away', 'teachUtil.away', 'var(--el-text-color-secondary)'], ['faulted', 'teachUtil.faulted', 'var(--bad, var(--el-color-danger))'],
  ['awaiting_grading', 'teachUtil.awaitingGrading', 'var(--el-color-warning)'], ['graded', 'teacherConsole.graded', 'var(--ok, var(--el-color-success))'],
];
/** Colour by state code or by state text (either language). */
export const STU_STATE_COLOR: Record<string, string> = Object.fromEntries(STU_STATES.flatMap(([code, k, c]) => [[code, c], ...variants(k).map((t) => [t, c])]));
/** A student state (code or backend text) shown in the UI language. */
export const stuStateLabel = (s: unknown) => { const hit = STU_STATES.find((x) => x[0] === s); return hit ? $t(hit[1]) : localize(s, STU_STATES.map((x) => x[1])); };
/** The state of a progress row: the code when the server sends one. */
export const stuState = (r: any) => (r?.state_code && r.state_code !== 'other' ? r.state_code : r?.state);
// Student-facing lesson status (sandbox is an implementation detail: absent = not started; sleeping sandboxes resume automatically on entry)
export const SANDBOX_CN: Record<string, string> = { none: $t('classProgress.notStarted'), running: $t('teachUtil.inProgress'), sleeping: $t('teachUtil.partiallyCompleteOpenToResume') };
export const PLC_CN: Record<string, string> = { RUN: $t('common.running'), STOP: $t('common.stop'), HALT: $t('live.pausedAtBreakpoint'), ERROR: $t('debugConsole.error'), STEP: $t('common.step') };

export const FAULT_CN: Record<string, string> = {
  sensor_stuck_on: $t('teachUtil.sensorStuckOn'), sensor_stuck_off: $t('teachUtil.sensorStuckOff'), sensor_flicker: $t('teachUtil.signalChatter'), wire_break: $t('teachUtil.disconnectedSignalAlways0'),
  actuator_jam: $t('teachUtil.actuatorJammed'), actuator_slow: $t('teachUtil.actuatorSlowdown'), motor_overload: $t('teachUtil.motorOverload'),
};
export const faultLabel = (f: any) => (f?.label && f.label !== f.kind ? f.label : `${f?.comp ? f.comp + ' ' : ''}${FAULT_CN[f?.kind] || f?.kind}`);

/** Fetch and save a binary file with a token (Word/PPT/Excel exports, etc.). Use POST if body is nonempty. */
export async function saveFile(path: string, filename: string, body?: any) {
  const r = await fetch(path, {
    method: body === undefined ? 'GET' : 'POST',
    headers: { Authorization: 'Bearer ' + session.token, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    const msg = typeof j.detail === 'string' ? j.detail : r.statusText;
    ElMessage.error(msg);
    throw new Error(msg);
  }
  const blob = await r.blob();
  if (native) {                                   // Electron client: use the system "Save As" dialog (remembers the last folder), not browser downloads
    const saved = await native.saveFileDialog({ defaultName: filename, data: new Uint8Array(await blob.arrayBuffer()) });
    if (!saved) throw new Error($t('teachUtil.saveCanceled'));
    return { size: blob.size, headers: r.headers, path: saved };
  }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  return { size: blob.size, headers: r.headers };
}

/** Polling: call the returned stop on component unmount. */
export function poll(fn: () => any, ms: number) {
  let alive = true, t: any = null;
  const tick = async () => { if (!alive) return; try { await fn(); } catch { /* Display handled by the caller */ } if (alive) t = setTimeout(tick, ms); };
  tick();
  return () => { alive = false; clearTimeout(t); };
}

export const fmtVal = (v: any) => (v === true ? '1' : v === false ? '0' : v === null || v === undefined ? '—' : typeof v === 'number' ? (Number.isInteger(v) ? String(v) : v.toFixed(3)) : String(v));

/** Small event bus for teaching panels: class list changes (create/delete) and requests to open a student's review. */
import { reactive as _reactive } from 'vue';
export const teachBus = _reactive<{ classes: number; review: { aid: number; username?: string; n: number } | null }>({ classes: 0, review: null });
export const classesChanged = () => { teachBus.classes++; };
export const openReview = (aid: number, username?: string) => { teachBus.review = { aid, username, n: Date.now() }; };

/** Student-friendly grading rules: "= 1" → required; "≥ 6" → at least 6. */
export function humanRule(r: any) {
  const op = r.op, v = r.target ?? r.value;
  if (r.kind === 'answer') return $t('teachUtil.pointsForCorrectAnswer');
  if (v === undefined || v === null || v === '') return r.desc || '';
  if (op === '==' && (v === 1 || v === true)) return $t('teachUtil.achieve');
  if (op === '==' && (v === 0 || v === false)) return $t('teachUtil.mustNotOccur');
  if (op === '>=' ) return $t('teachUtil.atLeast0', [fmtNum(v)]);
  if (op === '>') return $t('teachUtil.greaterThan0', [fmtNum(v)]);
  if (op === '<=') return $t('teachUtil.atMost0', [fmtNum(v)]);
  if (op === '<') return $t('teachUtil.lessThan0', [fmtNum(v)]);
  if (op === '==') return $t('teachUtil.equalTo0', [fmtNum(v)]);
  return `${op || ''} ${fmtNum(v)}`;
}
export function humanValue(d: any) {
  const v = d.value ?? d.actual;
  if (d.kind === 'answer') return v === null || v === undefined ? $t('teacherConsole.unanswered') : d.ok ? $t('teachUtil.correct') : $t('teachUtil.incorrect');
  if (d.op === '==' && (d.target === 1 || d.target === 0) && (v === 0 || v === 1)) return (v === 1) === (d.target === 1) ? (d.target === 1 ? $t('teachUtil.achieved') : $t('teachUtil.didNotOccur')) : (d.target === 1 ? $t('teachUtil.notAchieved') : $t('teachUtil.occurred'));
  return fmtNum(v);
}
/** 4.6.2 When to reveal correct answers and explanations to students (assignments.reveal). */
export const REVEAL_OPTS = [{ v: 'submit', l: $t('teachUtil.showAfterSubmission') }, { v: 'due', l: $t('teachUtil.showAfterDeadline') }, { v: 'never', l: $t('teachUtil.doNotShow') }];
export function revealHint(v: string, due?: string | null) {
  if (v === 'due') return due ? $t('teachUtil.afterTheDeadline0Students', [due]) : $t('teachUtil.aDeadlineIsRequiredWithout');
  if (v === 'never') return $t('teachUtil.studentsSeeOnlyTheirOwn');
  return $t('teachUtil.studentsCanSeeTheCorrect');
}
export const fmtNum = (v: any) => (typeof v === 'number' ? String(Number(v.toFixed(2))) : v === null || v === undefined ? '—' : String(v));

/** Program snapshot → text (ST unchanged; ladder diagram as one line per rung) for viewing and comparison. */
export function programText(p: any): string {
  if (!p) return '';
  if (typeof p.source === 'string') return p.source;
  if (p.blocks && p.links) return modelText(p);
  if (p.model?.blocks) {                       // Submitted factory: model + program for each PLC
    const progs = Object.entries(p.programs || {}).map(([k, v]: [string, any]) => $t('teachUtil.programFor01', [k, v?.lang || '']) + programText(v)).join('\n');
    return modelText(p.model) + (progs || $t('teachUtil.noPlcProgram'));
  }
  const rungs = p.source?.rungs || [];
  const el = (e: any): string => {
    if (!e) return '';
    if (Array.isArray(e)) return e.map(el).join(' — ');
    if (e.ser) return e.ser.map(el).join(' — ');
    if (e.par) return '[' + e.par.map(el).join($t('teachUtil.or')) + ']';
    const t = String(e.t === false ? 'NO' : e.t || '').toUpperCase();
    const M: Record<string, string> = { NO: '┤ ├', NC: '┤/├', P: '┤P├', N: '┤N├', COIL: '( )', NCOIL: '(/)', SET: '(S)', RESET: '(R)' };
    if (M[t]) return `${M[t]} ${e.var ?? ''}`;
    if (t === 'FB') return `[${e.fb} ${e.inst || ''}${e.in ? ' ' + Object.entries(e.in).map(([k, v]) => k + '=' + v).join(' ') : ''}]`;
    if (t === 'CMP') return `[${e.a} ${e.op} ${e.b}]`;
    if (t === 'MATH') return `[${e.out} := ${e.a} ${e.op} ${e.b}]`;
    if (t === 'MOVE') return `[${e.out} := ${e.in}]`;
    return t;
  };
  return rungs.map((r: any, i: number) => $t('teachUtil.rung01', [i + 1, r.comment ? $t('common.k459') + r.comment + $t('common.k460') : '']) + (r.elements || []).map(el).join(' — ')).join('\n');
}
export function modelText(m: any): string {
  const lines = (m.blocks || []).map((b: any) => $t('teachUtil.n01', [b.id, b.name || '']) + Object.entries(b.params || {}).filter(([k]) => !['defects', 'signals'].includes(k))
    .map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join($t('common.k521')));
  lines.push($t('teachUtil.connections') + (m.links || []).map((l: any) => `${l.from}→${l.to}${l.via ? $t('common.k459') + l.via + $t('common.k460') : ''}`).join($t('common.k521')));
  return lines.join('\n');
}
/** Minimal line-by-line diff (LCS): [{t:' '|'+'|'-', s}] */
export function lineDiff(a: string, b: string) {
  const A = (a || '').split('\n'), B = (b || '').split('\n');
  const n = A.length, m = B.length;
  const L = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = A[i] === B[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const out: { t: string; s: string }[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { out.push({ t: ' ', s: A[i] }); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) out.push({ t: '-', s: A[i++] });
    else out.push({ t: '+', s: B[j++] });
  }
  while (i < n) out.push({ t: '-', s: A[i++] });
  while (j < m) out.push({ t: '+', s: B[j++] });
  return out;
}

const OLD_STAT_CN: Record<string, string> = { removed: $t('teachUtil.completedParts'), sorted_ok: $t('teachUtil.correctlySorted'), sorted_wrong: $t('teachUtil.incorrectlySorted'), sort_accuracy: $t('teachUtil.sortingAccuracy'),
  throughput_per_min: $t('teachUtil.partsPerMinute'), collisions: $t('teachUtil.collisions'), jams: $t('teachUtil.jammedParts'), dropped: $t('teachUtil.droppedParts'), faults: $t('teachUtil.currentFault') };
function metricText(key: string, v: any): string {
  if (v === null || v === undefined || (typeof v === 'number' && !Number.isFinite(v))) return '—';
  if (typeof v === 'number') return /accuracy|_rate$/.test(key) && v <= 1 ? (v * 100).toFixed(1) + '%' : String(Math.round(v * 100) / 100);
  if (typeof v === 'boolean') return v ? $t('common.yes') : $t('common.no');
  if (typeof v === 'object') return Object.entries(v).map(([k, x]) => `${k} ${metricText(key, x)}`).join($t('common.k521'));
  return String(v);
}
/**
 * Sandbox metrics → [{key, label, text}]. Use stats.metrics from the control unit if provided (lesson-specific grading metrics; no sorting metrics for motor lessons);
 * for legacy fixed stats, list only grading metrics (ruleKeys) plus completed parts. Append the current fault count separately.
 */
export function metricRows(stats: any, ruleKeys: string[] = []): { key: string; label: string; text: string }[] {
  if (!stats) return [];
  let out: { key: string; label: string; text: string }[];
  if (Array.isArray(stats.metrics) && stats.metrics.length) {
    out = stats.metrics.map((m: any) => ({ key: m.key, label: m.label || m.key, text: metricText(m.key, m.value) }));
  } else {
    out = Object.keys(OLD_STAT_CN).filter((k) => k !== 'faults' && k in stats && (k === 'removed' || ruleKeys.includes(k)))
      .map((k) => ({ key: k, label: OLD_STAT_CN[k], text: metricText(k, stats[k]) }));
  }
  if (stats.faults) out.push({ key: 'faults', label: $t('teachUtil.currentFault'), text: String(stats.faults) });
  return out;
}
