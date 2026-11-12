// Public entry point for control cells: other panels (PLC, HMI, external PLC empty pages, etc.) call this to create a control cell.
//
//   import { newCell } from '../panels/cell/api';
//   const id = await newCell();                                   // Empty control cell
//   const id = await newCell({ scene: 's04_sort_color' });        // Use the lab scenario layout and I/O table (without the reference solution)
//   const id = await newCell({ name: 'Assembly Section', pos: [40, 12] });
//
// Add a block via the Workbench command bus (undoable), select it, and open the "Control Cell" sidebar. Return the new block ID; throw an Error with a localized message on failure.
// 4.3: PLCs are separate devices—by default, create a PLC beside the cell and wire all cell I/O to it (skip when plc: false).
import { $t } from '../../i18n';
import { canEdit, get } from '../../api';
import { blocksById, ed, exec, makeBlock, select } from '../../editor/store';
import { cs } from './state';

export type NewCellOpts = { scene?: string; name?: string; pos?: number[]; open?: boolean; plc?: boolean };

export const BLANK_CELL = () => ({ size: [8, 4], components: [], io: [] });

export async function newCell(opts: NewCellOpts = {}): Promise<string> {
  if (!ed.model) throw new Error($t('cellApi.theFactoryModelHasNot'));
  if (!canEdit()) throw new Error($t('cellApi.yourAccountHasViewOnly'));
  ed.cat ||= await get('/api/catalog');
  let cell: any = BLANK_CELL(), name = opts.name || '';
  if (opts.scene) {
    const s = await get('/api/scenes/' + encodeURIComponent(opts.scene));
    cell = JSON.parse(JSON.stringify(s.cell));
    delete cell.plc;                                    // Do not include the reference solution in student/user factories (use the scenario's plc section for PLC settings)
    if (s.plc) cell.plc = { mode: s.plc.mode || 'internal', scan_ms: s.plc.scan_ms || 20 };
    name ||= s.name;
  }
  const floor = ed.model.plant?.floor || [60, 40];
  const pos = opts.pos || (ed.cursor && (ed.cursor[0] || ed.cursor[1]) ? ed.cursor : [floor[0] / 2, floor[1] / 2]);
  const b: any = makeBlock('cell', pos, [240, 240]);
  b.size = [...(cell.size || [8, 4])];
  b.params = { ...(b.params || {}), cell };
  if (name) b.name = name.slice(0, 40);
  if (opts.plc !== false) cell.plc ||= { mode: 'internal', scan_ms: 20 };   // attachPlc below splits this into a separate PLC block + signal wires
  exec([{ op: 'add_block', block: b }], opts.scene ? $t('cellApi.createControlCell0From', [b.name]) : $t('cellApi.createControlCell0', [b.id]));
  if (!blocksById.value[b.id]) throw new Error($t('cellApi.couldNotCreateTheControl'));
  if (opts.plc !== false) {
    const { attachPlc } = await import('../../plc/cellActions');
    if (attachPlc(b.id)) {
      const u = ed.undo.splice(-2);                     // Group cell creation + PLC setup into one undo step
      if (u.length === 2) ed.undo.push({ ops: u.flatMap((h: any) => h.ops), inv: [...u].reverse().flatMap((h: any) => h.inv), label: u[0].label });
      else ed.undo.push(...u);
    }
  }
  select([b.id]);
  cs.bid = b.id;
  cs.comp = '';
  if (opts.open !== false) window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'cell-editor' } }));
  return b.id;
}

/** Control cell blocks in the current factory. */
export function cellIds(): string[] {
  return (ed.model?.blocks || []).filter((b: any) => b.type === 'cell').map((b: any) => b.id);
}

/** Open the equipment interior view (control cell → cell editor; regular equipment → its control I/O panel). The Objects panel's "Equipment Interior" button can also call this directly. */
export function openInterior(id: string) {
  ed.interior = id;
  window.dispatchEvent(new CustomEvent('vf:open-panel', { detail: { id: 'cell-editor' } }));
}

/** Scenario library list (for the "Load from Lab Scenario" dropdown). */
let scenesCache: any[] | null = null;
export async function sceneList(): Promise<any[]> {
  if (!scenesCache) scenesCache = await get('/api/scenes', true).catch(() => []);
  return scenesCache || [];
}

export const hasBlock = (id: string) => !!blocksById.value[id];
