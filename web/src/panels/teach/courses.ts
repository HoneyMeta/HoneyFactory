// 4.6 Shared course covers, lesson types, and progress text for student course cards, course details, and the teacher's course library and editor.
import { $t } from '../../i18n';
import { brandUrl } from '../../brand';
import { session } from '../../api';

export const KIND_CN: Record<string, string> = { cell: $t('common.plcLab'), plant: $t('courseEditor.lineTask'), diagnose: $t('common.troubleshooting'), factory: $t('common.factoryDesign'), quiz: $t('common.quiz'), point: $t('courses.selectEquipment'), mes: $t('courseEditor.mesTask') };
export const KIND_ICON: Record<string, string> = { cell: 'Cpu', plant: 'DataLine', diagnose: 'WarningFilled', factory: 'OfficeBuilding', quiz: 'EditPen', point: 'Aim', mes: 'Tickets' };
const BY_ID: Record<string, string> = { machining: 'course-machining.png', foundry: 'course-foundry.png', plc_basics: 'course-plc.png' };

/** Course cover URL: explicit cover (/brand/… or assets/… from a course package or teacher upload) > built-in course cover > generic cover by lesson type. */
export function courseCover(c: any): string {
  const id = c?.course || c?.id || '';
  const cv = String(c?.cover || '');
  if (cv.startsWith('/brand/')) { const u = brandUrl(cv.slice(7)); if (u) return u; }
  else if (cv.startsWith('assets/')) return `/api/teach/courses/${encodeURIComponent(id)}/assets/${encodeURIComponent(cv.slice(7))}?token=${encodeURIComponent(session.token || '')}`;
  else if (/^(https?:|data:)/.test(cv)) return cv;
  if (BY_ID[id]) { const u = brandUrl(BY_ID[id]); if (u) return u; }
  const kinds: string[] = c?.kinds || [];
  const pick = kinds.length === 1 && kinds[0] === 'quiz' ? 'course-custom-quiz.png' : kinds.length === 1 && kinds[0] === 'mes' ? 'course-custom-mes.png'
    : kinds.every((k) => k === 'cell') && kinds.length ? 'course-plc.png' : kinds.every((k) => ['plant', 'point', 'diagnose'].includes(k)) && kinds.length ? 'course-custom-line.png' : 'course-custom-mixed.png';
  return brandUrl(pick);
}

/** Progress: 0–100. */
export const pct = (c: any) => (c?.total ? Math.round((c.done / c.total) * 100) : 0);

/** Next lesson in the course (use next if present). */
export function nextLesson(c: any) {
  for (const ch of c?.chapters || []) for (const l of ch.lessons || []) if (l.aid === c.next) return { ...l, chapter: ch.title };
  return null;
}

export function courseState(c: any): 'done' | 'doing' | 'new' {
  if (c?.total && c.done >= c.total) return 'done';
  const any = (c?.chapters || []).some((ch: any) => ch.lessons.some((l: any) => l.best !== null && l.best !== undefined || l.submissions));
  return c?.done || any ? 'doing' : 'new';
}
