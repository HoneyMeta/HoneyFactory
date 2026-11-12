// Teaching module/shell contract: the panel sets ed.teach.open (enter sandbox / observe); this switches to that factory.
// Both the Workbench and Teaching page register this listener; setting ed.teach.handled = true prevents the panel from navigating on its own.
import { watch } from 'vue';
import { ownLocalPlant, session } from '../../api';
import { router } from '../../router';
import { ed } from '../store';

export const role = () => session.user?.role || '';
/** Student in a school sandbox: Teaching workspace only; structure edits disabled for PLC lessons. Excludes students opening My Factories in the desktop client, where all workspaces are available as for engineers. */
export const isStudent = () => role() === 'student' && !(location.pathname.startsWith('/p/') && ownLocalPlant());
export const isTeachRole = () => ['student', 'teacher'].includes(role());

/** Open the sandbox referenced by ed.teach.open; readonly makes the entire Workbench read-only (teacher observation). */
export function handleTeachOpen(current: () => string) {
  ed.teach = { ...(ed.teach || {}), handled: true };
  // n changed = new sandbox opened; readonly changed = teacher takes over (editable) or hands back control (read-only)
  return watch(() => [ed.teach?.open?.n, ed.teach?.open?.readonly], () => {
    const o = ed.teach?.open;
    if (!o?.pid) return;
    session.readonlyPid = o.readonly ? o.pid : '';
    if (o.pid !== current()) router.push(`/p/${encodeURIComponent(o.pid)}/workbench`);
  });
}
