// Asset library placement: drag into any view, or click an asset to enter placement mode, then click the canvas to place it (Shift for repeated placement, Esc to cancel).
// All three views call placeBlock with their own coordinates (graph node / floor plan and 3D pos); infer the other coordinates nearby.
import { $t } from '../../i18n';
import { ElMessage } from 'element-plus';
import { canEdit } from '../../api';
import { ed, exec, flash, makeBlock, nodePosNear, planPosNear, select } from '../store';

export function placeBlock(type: string, at: { pos?: number[]; node?: number[] }) {
  const t = ed.cat?.types?.[type]; if (!t) return null;
  if (!canEdit()) { ElMessage.info($t('place.viewOnlyEditingIsDisabled')); return null; }
  const pos = at.pos ? [at.pos[0], at.pos[1]] : planPosNear(at.node!);
  const node = at.node ? [at.node[0], at.node[1]] : nodePosNear(pos);
  const b: any = makeBlock(type, pos, node);
  if ((ed.floor || 'F1') !== 'F1') b.floor = ed.floor;   // Current floor in the floor plan
  exec([{ op: 'add_block', block: b }], $t('common.add0', [t.label]));
  select([b.id]); flash([b.id], 1500);
  return b;
}
export function startPlacing(type: string) {
  const t = ed.cat?.types?.[type]; if (!t) return;
  ed.placing = ed.placing?.type === type ? null : { type, label: t.label.replace(/\s*[\uff08(][^\uff09)]*[\uff09)]/, '') };
}
/** Place on a view click; exit placement mode unless Shift is held. Return whether the click was handled. */
export function placeAt(e: MouseEvent, at: { pos?: number[]; node?: number[] }) {
  if (!ed.placing) return false;
  placeBlock(ed.placing.type, at);
  if (!e.shiftKey) ed.placing = null;
  return true;
}
/** Drag-and-drop data (library block type). */
export const dropType = (e: DragEvent) => e.dataTransfer?.getData('vf/type') || '';
