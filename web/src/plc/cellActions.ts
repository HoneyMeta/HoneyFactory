// "New Control Unit / Load from Lab Scenario": prefer newCell(opts) exported by the control unit module (web/src/panels/cell/),
// otherwise use this fallback (add a cell block via the command bus and open the control unit editor).
// 4.3: after creation, split the built-in PLC out of the unit definition into a separate PLC block + signal wire (same rules as server-side vfactory/plc/migrate.py).
import { $t } from '../i18n';
import { ElMessage } from 'element-plus';
import { get } from '../api';
import { ed, exec, makeBlock, newId, select } from '../editor/store';

/** PLC address → signal wire channel syntax (omit %, and X for bit addresses): %IX0.0 → I0.0, %QW64 → QW64. */
export function chOf(addr?: string): string {
  const a = String(addr || '').trim().replace(/^%/, '').toUpperCase();
  const m = /^([IQM])X?(\d+\.\d+)$/.exec(a);
  return m ? m[1] + m[2] : a;
}

/** If a draft control unit has a built-in PLC (params.cell.plc), split it into a PLC block + signal wire (all_io) and return the PLC ID. */
export function attachPlc(cellId: string): string | null {
  const b = (ed.model?.blocks || []).find((x: any) => x.id === cellId);
  const cell = b?.params?.cell;
  if (!b || !cell || !('plc' in cell) || cell.plc?.mode === 'none') return null;
  const plc = cell.plc || {};
  const io: any[] = cell.io || [];
  const pid = newId('PLC');
  const size = b.size || [8, 4], pos = b.pos || [0, 0];
  const isBool = (e: any) => (e.type || 'BOOL').toUpperCase() === 'BOOL';
  const blk: any = {
    id: pid, type: 'plc', name: `${b.name || b.id} PLC`, rot: 0, size: [1.2, 0.6],
    pos: [Math.round((pos[0] + size[0] / 2 + 1.5) * 10) / 10, Math.round((pos[1] - size[1] / 2 + 0.5) * 10) / 10],
    node: [b.node?.[0] || 0, (b.node?.[1] || 0) + 170],
    params: {
      model: 'generic', scan_ms: plc.scan_ms || 20, mode: plc.mode || 'internal', program: plc.program && typeof plc.program === 'object' ? plc.program : null,
      di: io.filter((e) => e.dir === 'in' && isBool(e)).length, do: io.filter((e) => e.dir === 'out' && isBool(e)).length,
      ai: io.filter((e) => e.dir === 'in' && !isBool(e)).length, ao: io.filter((e) => e.dir === 'out' && !isBool(e)).length, migrated_from: b.id,
    },
  };
  if (plc.external) blk.params.external = plc.external;
  if (b.area) blk.area = b.area;
  const newCellDef = JSON.parse(JSON.stringify(cell));
  delete newCellDef.plc;
  if (Array.isArray(newCellDef.hmi) && newCellDef.hmi.length) { blk.params.hmi = newCellDef.hmi.map((h: any) => ({ ...h, cell: pid })); }
  delete newCellDef.hmi;
  const link = {
    id: newId('SIG', [pid]), kind: 'signal', from: b.id, to: pid, all_io: true,
    signals: io.filter((e) => e.name).map((e) => ({ point: e.name, ch: chOf(e.addr) || e.name, dir: e.dir || 'in' })),
  };
  exec([{ op: 'update_block', id: b.id, set: { 'params.cell': newCellDef } }, { op: 'add_block', block: blk }, { op: 'add_link', link }],
    $t('cellActions.assignAPlcTo0', [b.name || b.id, pid, link.id]));
  return pid;
}

const cellMods = import.meta.glob('../panels/cell/*.ts');

export type NewCellOpts = { scene?: string; name?: string };

export async function newCell(opts: NewCellOpts = {}): Promise<string | null> {
  let fn: any = null;
  for (const load of Object.values(cellMods)) {
    try { const m: any = await load(); if (typeof m.newCell === 'function') { fn = m.newCell; break; } } catch { /* Try the next one */ }
  }
  if (!fn) return fallbackNewCell(opts);
  try {
    const id = await fn(opts);
    const pid = id ? attachPlc(id) : null;
    if (id) ElMessage.success($t('cellActions.createdControlUnit01', [id, pid ? $t('cellActions.andItsControllingPlc0', [pid]) : '']));
    return id || null;
  } catch (e: any) {
    ElMessage.error(e?.message || $t('cellActions.failedToCreateControlUnit'));
    return null;
  }
}

async function fallbackNewCell(opts: NewCellOpts) {
  if (!ed.model) { ElMessage.warning($t('cellActions.useTheWorkbenchAFactory')); return null; }
  ed.cat ||= await get('/api/catalog');
  let cell: any = null, name = opts.name || '';
  if (opts.scene) {
    const s = await get(`/api/scenes/${encodeURIComponent(opts.scene)}`);
    cell = JSON.parse(JSON.stringify(s.cell || null));
    name ||= s.name;
  }
  const b: any = makeBlock('cell', ed.cursor?.length ? ed.cursor : [10, 10], [0, 0]);
  if (cell) b.params = { ...(b.params || {}), cell };
  if (name) b.name = name;
  exec([{ op: 'add_block', block: b }], opts.scene ? $t('cellActions.loadControlUnit0From', [b.name]) : $t('cellActions.createControlUnit0', [b.name]));
  attachPlc(b.id);
  select([b.id]);
  ed.leftPanel = 'cell-editor'; ed.leftOpen = true;
  ElMessage.success($t('cellActions.createdControlUnit0Click', [b.id]));
  return b.id;
}

export async function listScenes(): Promise<any[]> {
  try { const r = await get('/api/scenes', true); return Array.isArray(r) ? r : r.items || r.scenes || []; } catch { return []; }
}
