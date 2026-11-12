// Drag to connect or use "+" to add and connect in Floor Plan / Architecture (4.4): same rules as the graph—
// Production equipment uses material links (first source outlet → first target inlet; two buffers require a transport fleet), equipment ⇄ PLC uses signal wires, and control/communication/information systems use network cables.
import { $t } from '../../i18n';
import { ElMessage } from 'element-plus';
import { blocksById, ed, exec, flash, makeBlock, newId, select, typeOf, type Op } from '../store';
import { layerOf, linkKind } from '../shell/relations';
import { connectByLayer } from '../shell/wiring';

/** Link type when dragging from a to b: material / signal / network; returns '' if incompatible. */
export function connKind(a: string, b: string): string {
  const A = blocksById.value[a], B = blocksById.value[b];
  if (!A || !B || a === b) return '';
  const la = layerOf(a), lb = layerOf(b);
  if (la === 'process' && lb === 'process') return typeOf(A).out.length && typeOf(B).in.length ? 'material' : '';
  if ((la === 'process' && B.type === 'plc') || (lb === 'process' && A.type === 'plc')) return 'signal';
  if (la !== 'process' && lb !== 'process') return 'network';
  return '';
}
export const CONN_CN: Record<string, string> = { material: $t('connect.materialFlowLine'), signal: $t('connect.signalWire'), network: $t('connect.networkCable') };
/** Brief explanation when a connection is not allowed. */
export function connWhy(a: string, b: string) {
  const A = blocksById.value[a], B = blocksById.value[b]; if (!A || !B) return '';
  if (a === b) return $t('connect.cannotConnectAnObjectTo');
  const la = layerOf(a), lb = layerOf(b);
  if (la === 'process' && lb === 'process') return !typeOf(A).out.length ? $t('connect.n0HasNoOutputPort', [A.name]) : $t('connect.n0HasNoInputPort', [B.name]);
  if (la === 'process' || lb === 'process') return $t('connect.productionEquipmentCanOnlyConnect');
  return '';
}

/** Material link (same rules as GraphView.linkOp). extra: blocks created in this step (not yet in the model). */
export function materialLinkOp(from: string, to: string, extra?: any, fp?: string, tp?: string): Op | null {
  const by = extra ? { ...blocksById.value, [extra.id]: extra } : blocksById.value, A = by[from], B = by[to];
  if (!A || !B || from === to) return null;
  const f = fp || typeOf(A).out[0], t = tp || typeOf(B).in[0];
  if (!f || !t) return null;
  if ((ed.model.links || []).some((l: any) => linkKind(l) === 'material' && l.from === from && l.to === to && (l.from_port || 'out') === f && (l.to_port || 'in') === t)) return null;
  const link: any = { id: newId('L'), kind: 'material', from, from_port: f, to, to_port: t };
  if (A.type === 'buffer' && B.type === 'buffer') {
    const tr = ed.model.blocks.find((b: any) => b.type === 'transporter');
    if (tr) link.via = tr.id; else ElMessage.warning($t('graphView.transportBetweenTwoBuffersRequires'));
  }
  return { op: 'add_link', link };
}

/** On drag release, create the link matching the endpoint layers. Return whether connected. */
export function connectBlocks(a: string, b: string): boolean {
  const k = connKind(a, b);
  if (!k) { const w = connWhy(a, b); if (w) ElMessage.info(w); return false; }
  if (k === 'material') {
    const op = materialLinkOp(a, b);
    if (!op) { ElMessage.info($t('connect.theseTwoDevicesAreAlready')); return false; }
    exec([op], $t('common.connections')); ed.sel = []; ed.selLink = (op as any).link.id; flash([a, b], 1200);
    return true;
  }
  const ok = connectByLayer(a, b);
  if (ok) flash([a, b], 1200);
  return ok;
}

/** "+" or drag to empty space: create a type at pos (floor plan coordinates) and connect from from, as one undo step. */
export function addConnected(type: string, from: string, pos: number[]) {
  const A = blocksById.value[from], t = ed.cat?.types?.[type]; if (!A || !t) return null;
  const node = [Math.round(((A.node?.[0] || 0) + 290) / 10) * 10, Math.round((A.node?.[1] || 0) / 10) * 10];
  const b: any = makeBlock(type, pos, node);
  if (A.floor) b.floor = A.floor;
  const ops: Op[] = [{ op: 'add_block', block: b }];
  const k = layerOf(from) === 'process' && (t.layer || 'process') === 'process' ? 'material' : '';
  if (k === 'material') { const op = materialLinkOp(from, b.id, b); if (op) ops.push(op); }
  exec(ops, (ops.length > 1 ? $t('graphView.addAndConnect') : $t('common.add2')) + t.label);
  if (k !== 'material') connectByLayer(from, b.id);
  select([b.id]); flash([b.id], 1500);
  return b;
}

/** Default "+" position: place the next unit 2 m along the equipment's outlet direction (right at 0°). */
export function nextPos(from: string, type: string) {
  const A = blocksById.value[from], t = ed.cat?.types?.[type]; if (!A || !t) return [0, 0];
  const rot = ((Math.round((A.rot || 0) / 90) % 4) + 4) % 4, ext = rot % 2 ? [A.size[1], A.size[0]] : A.size;
  const tw = t.size?.[0] || 3, th = t.size?.[1] || 3, gap = 2;
  const dir = [[1, 0], [0, 1], [-1, 0], [0, -1]][rot];
  return [A.pos[0] + dir[0] * (ext[0] / 2 + gap + tw / 2), A.pos[1] + dir[1] * (ext[1] / 2 + gap + th / 2)];
}
