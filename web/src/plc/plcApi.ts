// PLC API wrapper (backend: vfactory/plc/api.py).
import { $t } from '../i18n';
import { call, get, P, post, put, session } from '../api';

export const C = (pid: string, bid: string) => `${P(pid)}/cells/${encodeURIComponent(bid)}`;

export const plcApi = {
  cells: (pid: string) => get(`${P(pid)}/plc/cells`, true),
  /** 4.3: Status of all PLC blocks {plcs:[{bid,name,state,label,halt,bps,devices}], halted}. */
  status: (pid: string) => get(`${P(pid)}/plc/status`, true),
  /** 4.3: PLC channel table [{ch,dir,point,device,device_name,value,forced,name,type,addr,link}]. */
  io: (pid: string, bid: string) => get(`${P(pid)}/plc/${encodeURIComponent(bid)}/io`, true),
  program: (pid: string, bid: string) => get(C(pid, bid) + '/program'),
  save: (pid: string, bid: string, program: any) => put(C(pid, bid) + '/program', program),
  compile: (pid: string, bid: string, program: any) => post(C(pid, bid) + '/program/compile', { program }),
  download: (pid: string, bid: string, program: any, opts: any = {}) => post(C(pid, bid) + '/program/download', { program, ...opts }),
  online: (pid: string, bid: string, ld = true) => call('GET', C(pid, bid) + '/online' + (ld ? '' : '?ld=0'), undefined, true),
  action: (pid: string, bid: string, body: any) => post(C(pid, bid) + '/plc', body),
  importXml: (pid: string, bid: string, xml: string, save = false) => post(C(pid, bid) + '/program/import', { xml, save }),
  exportUrl: (pid: string, bid: string) => C(pid, bid) + '/program/export.xml',
  external: (pid: string, bid: string, protocol = '') => get(C(pid, bid) + '/plc/external' + (protocol ? '?protocol=' + protocol : '')),
  setExternal: (pid: string, bid: string, body: any) => put(C(pid, bid) + '/plc/external', body),
  hmiList: (pid: string) => get(`${P(pid)}/hmi`),
  hmiGet: (pid: string, id: string) => get(`${P(pid)}/hmi/${encodeURIComponent(id)}`),
  hmiPut: (pid: string, id: string, d: any) => put(`${P(pid)}/hmi/${encodeURIComponent(id)}`, d),
  hmiRestore: (pid: string) => post(`${P(pid)}/hmi/_restore`, {}),
  hmiDel: (pid: string, id: string) => call('DELETE', `${P(pid)}/hmi/${encodeURIComponent(id)}`),
};

/** Download a file with a token. */
export async function downloadFile(url: string, name: string) {
  const r = await fetch(url, { headers: { Authorization: 'Bearer ' + session.token } });
  const b = await r.blob();
  const a = document.createElement('a');
  a.href = URL.createObjectURL(b);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/** Milliseconds → T#1m30s500ms */
export function fmtTime(ms: number) {
  ms = Math.round(ms || 0);
  if (!ms) return 'T#0ms';
  const neg = ms < 0; ms = Math.abs(ms);
  let s = '';
  for (const [u, k] of [['d', 86400000], ['h', 3600000], ['m', 60000], ['s', 1000]] as [string, number][]) if (ms >= k) { s += Math.floor(ms / k) + u; ms %= k; }
  if (ms) s += ms + 'ms';
  return 'T#' + (neg ? '-' : '') + s;
}

/** Format an online value by type. */
export function fmtVal(v: any, t?: string) {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  if (t === 'TIME') return fmtTime(v);
  if (typeof v === 'number') return Number.isInteger(v) ? String(v) : (Math.abs(v) >= 1000 ? v.toFixed(1) : v.toPrecision(5).replace(/\.?0+$/, ''));
  if (Array.isArray(v)) return '[' + v.slice(0, 8).map((x) => fmtVal(x)).join(', ') + (v.length > 8 ? ', …' : '') + ']';
  if (typeof v === 'object') return '{…}';
  return String(v);
}

export const STATE_CN: Record<string, string> = { RUN: $t('common.running'), STOP: $t('common.stop'), HALT: $t('common.pause'), ERROR: $t('common.error'), EXTERNAL: $t('plcApi.external') };
export const TYPES = ['BOOL', 'INT', 'DINT', 'REAL', 'TIME', 'WORD', 'BYTE', 'DWORD', 'UINT', 'UDINT', 'SINT', 'LREAL', 'STRING',
  'TON', 'TOF', 'TP', 'CTU', 'CTD', 'CTUD', 'R_TRIG', 'F_TRIG', 'SR', 'RS'];
export const FB_TYPES: Record<string, { cn: string; in: string[]; out: string[]; pin: string; pout: string; prefix: string }> = {
  TON: { cn: $t('plcApi.onDelay'), in: ['IN', 'PT'], out: ['Q', 'ET'], pin: 'IN', pout: 'Q', prefix: 'T' },
  TOF: { cn: $t('plcApi.offDelay'), in: ['IN', 'PT'], out: ['Q', 'ET'], pin: 'IN', pout: 'Q', prefix: 'T' },
  TP: { cn: $t('plcApi.pulse'), in: ['IN', 'PT'], out: ['Q', 'ET'], pin: 'IN', pout: 'Q', prefix: 'T' },
  CTU: { cn: $t('plcApi.countUp'), in: ['CU', 'R', 'PV'], out: ['Q', 'CV'], pin: 'CU', pout: 'Q', prefix: 'C' },
  CTD: { cn: $t('plcApi.countDown'), in: ['CD', 'LD', 'PV'], out: ['Q', 'CV'], pin: 'CD', pout: 'Q', prefix: 'C' },
  CTUD: { cn: $t('plcApi.upDownCounter'), in: ['CU', 'CD', 'R', 'LD', 'PV'], out: ['QU', 'QD', 'CV'], pin: 'CU', pout: 'QU', prefix: 'C' },
  R_TRIG: { cn: $t('ladderEditor.risingEdge'), in: ['CLK'], out: ['Q'], pin: 'CLK', pout: 'Q', prefix: 'RT' },
  F_TRIG: { cn: $t('ladderEditor.fallingEdge'), in: ['CLK'], out: ['Q'], pin: 'CLK', pout: 'Q', prefix: 'FT' },
  SR: { cn: $t('plcApi.setDominant'), in: ['S1', 'R'], out: ['Q1'], pin: 'S1', pout: 'Q1', prefix: 'SR' },
  RS: { cn: $t('plcApi.resetDominant'), in: ['S', 'R1'], out: ['Q1'], pin: 'S', pout: 'Q1', prefix: 'RS' },
};
export const FB_FIELD_TYPE: Record<string, string> = { IN: 'BOOL', PT: 'TIME', Q: 'BOOL', ET: 'TIME', CU: 'BOOL', CD: 'BOOL', R: 'BOOL', LD: 'BOOL', PV: 'INT', CV: 'INT',
  QU: 'BOOL', QD: 'BOOL', CLK: 'BOOL', S1: 'BOOL', S: 'BOOL', R1: 'BOOL', Q1: 'BOOL' };
