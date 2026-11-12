// 界面测试用：给示范工厂（草稿）加一套控制层 / 通讯层（PLC、HMI、交换机、网关、MES、信号线、网络线）。
// 已有同编号的对象就不重复加。用法：const { addControl } = require('./scripts/control_fixture'); await addControl(api, tok, PID)
const SIG = (n) => [
  { point: 'Running', ch: `I${n}.0`, dir: 'in' }, { point: 'Fault', ch: `I${n}.1`, dir: 'in' }, { point: 'PartIn', ch: `I${n}.2`, dir: 'in' },
  { point: 'Count', ch: `IW${64 + n * 2}`, dir: 'in' }, { point: 'Enable', ch: `Q${n}.0`, dir: 'out' }, { point: 'Reset', ch: `Q${n}.1`, dir: 'out' }];

async function addControl(api, tok, pid) {
  const m = (await api(tok, 'GET', `/api/p/${pid}/model`)).model;
  const has = (id) => m.blocks.some((b) => b.id === id);
  const at = (id) => m.blocks.find((b) => b.id === id);
  const blk = (id, type, name, pos, node, size = [1.2, 0.6]) => { if (!has(id)) m.blocks.push({ id, type, name, pos, size, rot: 0, node, params: {} }); };
  const f1 = at('FUR1')?.pos || [10, 30], c1 = at('CNC1')?.pos || [95, 30];
  blk('PLCT1', 'plc', '熔炼 PLC', [f1[0] + 4, f1[1] + 8], [120, 900]);
  blk('PLCT2', 'plc', '机加 PLC', [c1[0] + 4, c1[1] + 8], [1400, 900]);
  blk('HMIT1', 'hmi', '熔炼 HMI', [f1[0] + 8, f1[1] + 8], [260, 900], [0.6, 0.4]);
  blk('SW1', 'switch', '车间交换机', [60, 3], [700, -300], [0.8, 0.3]);
  blk('GW1', 'gateway', '工业网关', [66, 3], [800, -420], [0.8, 0.5]);
  blk('MES1', 'mes', '蜂元 MES', [72, 3], [900, -540], [1, 0.8]);
  const lk = (l) => { if (!m.links.some((x) => x.id === l.id)) m.links.push(l); };
  [['ST1', 'FUR1', 'PLCT1', 0], ['ST2', 'FUR2', 'PLCT1', 1], ['ST3', 'CNC1', 'PLCT2', 0], ['ST4', 'CNC2', 'PLCT2', 1]]
    .forEach(([id, dev, plc, n]) => lk({ id, kind: 'signal', from: dev, to: plc, signals: SIG(n) }));
  [['NT1', 'PLCT1', 'SW1', 'profinet'], ['NT2', 'PLCT2', 'SW1', 'profinet'], ['NT3', 'HMIT1', 'PLCT1', 'profinet'], ['NT4', 'SW1', 'GW1', 'ethernet'], ['NT5', 'GW1', 'MES1', 'mqtt']]
    .forEach(([id, from, to, protocol]) => lk({ id, kind: 'network', from, to, protocol }));
  const r = await api(tok, 'PUT', `/api/p/${pid}/model`, { model: m });
  return r;
}
module.exports = { addControl };
