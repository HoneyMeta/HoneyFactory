// Signal wire / network cable creation (4.3): drag-to-connect, "Add PLC Control", and "Connect to Network" all use this.
// Signal wire {kind:'signal', from: equipment, to: PLC, signals:[{point, ch, dir}]}; dir is relative to the PLC: in equipment→PLC, out PLC→equipment.
import { $t } from '../../i18n';
import { ElMessage } from 'element-plus';
import { blocksById, ed, exec, makeBlock, newId, select } from '../store';
import { layerOf, linkKind } from './relations';
import { chOf } from '../../plc/cellActions';

const isBool = (t: string) => !t || t === 'BOOL';

/** Equipment control points (catalog defaults + type-specific, minus exclude; none types have no points; matches server control/iface.points_of_type). */
export function controlPoints(type: string) {
  const def = ed.cat?.control_points || { in: [], out: [] }, own = ed.cat?.types?.[type]?.control || {};
  if (own.none) return { in: [], out: [] };
  const skip = new Set<string>(own.exclude || []);
  const merge = (a: any[], b: any[]) => [...a.filter((y: any) => !(b || []).some((x: any) => x.name === y.name)), ...(b || [])].filter((x: any) => !skip.has(x.name));
  return { in: merge(def.in || [], own.in), out: merge(def.out || [], own.out) };
}

/** Channels already used by a PLC. */
function usedChannels(plc: string) {
  const used = new Set<string>();
  for (const l of ed.model?.links || []) if (linkKind(l) === 'signal' && (l.to === plc || l.from === plc)) for (const s of l.signals || []) used.add(s.ch);
  return used;
}
/** Next free channel: digital I0.0…/Q0.0…, analog IW64…/QW64… (increments of 2). */
function nextCh(used: Set<string>, dir: 'in' | 'out', bool: boolean) {
  const p = dir === 'in' ? 'I' : 'Q';
  if (bool) { for (let b = 0; b < 64; b++) for (let i = 0; i < 8; i++) { const c = `${p}${b}.${i}`; if (!used.has(c)) { used.add(c); return c; } } }
  for (let w = 64; w < 512; w += 2) { const c = `${p}W${w}`; if (!used.has(c)) { used.add(c); return c; } }
  return '';
}

/** Default equipment ⇄ PLC signal wire: running / failure / part in position / completion count into PLC; run enable / fault reset out of PLC. */
export function signalLinkOp(dev: string, plc: string) {
  const D = blocksById.value[dev]; if (!D) return null;
  if ((ed.model?.links || []).some((l: any) => linkKind(l) === 'signal' && ((l.from === dev && l.to === plc) || (l.from === plc && l.to === dev)))) return null;
  // Control cell: its I/O table defines its control points; connect all I/O using table addresses (same as plc/cellActions.attachPlc)
  if (D.type === 'cell') {
    const io: any[] = D.params?.cell?.io || [];
    const signals = io.filter((e) => e.name).map((e) => ({ point: e.name, ch: chOf(e.addr) || e.name, dir: e.dir || 'in' }));
    return { op: 'add_link', link: { id: newId('S'), kind: 'signal', from: dev, to: plc, all_io: true, signals } };
  }
  const used = usedChannels(plc), cp = controlPoints(D.type);
  if (!cp.in.length && !cp.out.length) { ElMessage.info($t('wiring.n0HasNoControlPoints', [D.name || dev])); return null; }
  const signals = [...cp.in.map((p: any) => ({ point: p.name, ch: nextCh(used, 'in', isBool(p.type)), dir: 'in' })),
    ...cp.out.map((p: any) => ({ point: p.name, ch: nextCh(used, 'out', isBool(p.type)), dir: 'out' }))];
  return { op: 'add_link', link: { id: newId('S'), kind: 'signal', from: dev, to: plc, signals } };
}

const PROTO: Record<string, string> = { plc: 'profinet', hmi: 'profinet', switch: 'ethernet', gateway: 'opcua', scada: 'opcua', mes: 'mqtt' };
export function networkLinkOp(a: string, b: string) {
  if ((ed.model?.links || []).some((l: any) => linkKind(l) === 'network' && ((l.from === a && l.to === b) || (l.from === b && l.to === a)))) return null;
  const ta = blocksById.value[a]?.type, tb = blocksById.value[b]?.type;
  const proto = [ta, tb].includes('mes') || [ta, tb].includes('scada') ? (PROTO[tb] || PROTO[ta]) : 'ethernet';
  return { op: 'add_link', link: { id: newId('N'), kind: 'network', from: a, to: b, protocol: proto } };
}

/** Drag to connect two objects: endpoint layers determine signal wire or network cable. Return whether handled. */
export function connectByLayer(a: string, b: string) {
  const la = layerOf(a), lb = layerOf(b);
  let op: any = null, label = '';
  if (la === 'process' && lb === 'control' && blocksById.value[b]?.type === 'plc') { op = signalLinkOp(a, b); label = $t('wiring.connectPlcSignal'); }
  else if (lb === 'process' && la === 'control' && blocksById.value[a]?.type === 'plc') { op = signalLinkOp(b, a); label = $t('wiring.connectPlcSignal'); }
  else if (la !== 'process' && lb !== 'process') { op = networkLinkOp(a, b); label = $t('wiring.networkConnection'); }
  else return false;
  if (!op) { ElMessage.info($t('wiring.theseTwoAreAlreadyConnected')); return true; }
  exec([op], label); ed.sel = []; ed.selLink = op.link.id;
  return true;
}

/** "Add PLC Control": use an existing PLC (plcId) or create one beside the equipment. */
export function addPlcControl(dev: string, plcId?: string) {
  const D = blocksById.value[dev]; if (!D) return;
  const cp = controlPoints(D.type);
  if (D.type !== 'cell' && !cp.in.length && !cp.out.length) { ElMessage.info($t('wiring.n0HasNoControlPoints', [D.name || dev])); return; }
  const ops: any[] = [];
  let plc = plcId;
  if (!plc) {
    const b: any = makeBlock('plc', [D.pos[0], D.pos[1] + (D.size?.[1] || 3) / 2 + 1.5], [(D.node?.[0] || 0) + 40, (D.node?.[1] || 0) + 230]);
    b.name = `PLC-${D.name || D.id}`; if (D.floor) b.floor = D.floor;
    ops.push({ op: 'add_block', block: b }); plc = b.id;
    // Add the new PLC to the model before allocating channels (signalLinkOp reads connections from the model)
    exec(ops, $t('wiring.addAPlcTo0', [D.name]));
  }
  const s = signalLinkOp(dev, plc!);
  if (s) exec([s], $t('wiring.connect0To1', [D.name, blocksById.value[plc!]?.name || plc]));
  if (plcId === undefined && s) { const u = ed.undo.splice(-2); if (u.length === 2) ed.undo.push({ ops: u.flatMap((h: any) => h.ops), inv: [...u].reverse().flatMap((h: any) => h.inv), label: $t('wiring.addPlcControlTo0', [D.name]) }); }
  select([plc!]);
}

/** "Connect to Network": connect to an existing switch/gateway or create a switch. */
export function addNetwork(id: string, target?: string) {
  const A = blocksById.value[id]; if (!A) return;
  let t = target;
  if (!t) {
    const b: any = makeBlock('switch', [A.pos[0] + 2, A.pos[1] - 2], [(A.node?.[0] || 0) + 40, (A.node?.[1] || 0) - 160]);
    exec([{ op: 'add_block', block: b }], $t('archView.createSwitch')); t = b.id;
  }
  const op = networkLinkOp(id, t!); if (op) exec([op], $t('wiring.connect0ToTheNetwork', [A.name]));
  select([t!]);
}
