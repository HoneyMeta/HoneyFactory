"""OPC UA 外接驱动。

opcua_server：在虚拟工厂自己的 OPC UA 服务器（和工厂点位同一个端口）上发布本单元 I/O：
    NodeId ns=<idx>;s=<工厂>/<单元>/PLC/Inputs/<名称>（传感器，外部只读）
           ns=<idx>;s=<工厂>/<单元>/PLC/Outputs/<名称>（执行器，外部 PLC 写）
opcua：虚拟工厂当客户端连外部 OPC UA 服务器（CODESYS、PLCSIM Advanced、TwinCAT…），mapping 里每个 I/O 填 NodeId。
"""
from ...i18n import _tr
import asyncio

from asyncua import Client, ua

from ..external import PollingDriver

VT = {'BOOL': ua.VariantType.Boolean, 'SINT': ua.VariantType.SByte, 'INT': ua.VariantType.Int16, 'DINT': ua.VariantType.Int32,
      'LINT': ua.VariantType.Int64, 'USINT': ua.VariantType.Byte, 'UINT': ua.VariantType.UInt16, 'UDINT': ua.VariantType.UInt32,
      'BYTE': ua.VariantType.Byte, 'WORD': ua.VariantType.UInt16, 'DWORD': ua.VariantType.UInt32, 'REAL': ua.VariantType.Float,
      'LREAL': ua.VariantType.Double, 'TIME': ua.VariantType.Int32}


def _cast(t, v):
    if t == 'BOOL':
        return bool(v)
    if t in ('REAL', 'LREAL'):
        return float(v or 0)
    return int(v or 0)


class OpcUaServerDriver:
    def __init__(self, ext, ctx):
        self.ext, self.ctx = ext, ctx or {}
        hub = getattr(self.ctx.get('mgr'), 'opcua', None)
        if hub is None:
            raise RuntimeError(_tr('虚拟工厂的 OPC UA 服务器没有启动'))
        self.hub = hub
        self.pid, self.bid = self.ctx.get('pid', 'plant'), self.ctx.get('bid', 'cell')
        self.nodes_in, self.nodes_out = [], []
        self.top = None
        self.task = None

    def nid(self, s):
        return ua.NodeId(f'{self.pid}/{self.bid}/PLC/{s}', self.hub.idx)

    async def start(self):
        hub = self.hub
        qn = lambda s: ua.QualifiedName(s, hub.idx)  # noqa: E731
        try:
            old = hub.server.get_node(self.nid('_root'))
            await hub.server.delete_nodes([old], recursive=True)
        except Exception:
            pass
        self.top = await hub.root.add_object(self.nid('_root'), qn(f'{self.pid}.{self.bid}.PLC'))
        fin = await self.top.add_folder(self.nid('Inputs'), qn('Inputs'))
        fout = await self.top.add_folder(self.nid('Outputs'), qn('Outputs'))
        ext = self.ext
        for m in ext.mapping:
            t = (m.get('type') or 'BOOL').upper()
            vt = VT.get(t, ua.VariantType.Double)
            name = m['name']
            if m['dir'] == 'in':
                v = await fin.add_variable(self.nid(f'Inputs/{name}'), qn(name), ua.Variant(_cast(t, ext.inputs.get(name)), vt))
                self.nodes_in.append([v, name, t, vt, None])
            else:
                v = await fout.add_variable(self.nid(f'Outputs/{name}'), qn(name), ua.Variant(_cast(t, ext.outputs.get(name)), vt))
                await v.set_writable()
                self.nodes_out.append([v, name, t, vt])
        for m in ext.mapping:
            m['addr'] = f"ns={hub.idx};s={self.pid}/{self.bid}/PLC/{'Inputs' if m['dir'] == 'in' else 'Outputs'}/{m['name']}"
        ext.status.update(connected=True, error='', peer=hub.endpoint)
        self.task = asyncio.create_task(self._loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
        if self.top is not None:
            try:
                await self.hub.server.delete_nodes([self.top], recursive=True)
            except Exception:
                pass
            self.top = None

    def on_scan(self):
        pass

    async def _loop(self):
        srv, aspace, ext = self.hub.server, self.hub.aspace, self.ext
        period = max(0.01, float(ext.cfg.get('poll_ms') or ext.scan_ms) / 1000)
        while True:
            try:
                for rec in self.nodes_in:
                    node, name, t, vt, last = rec
                    v = _cast(t, ext.inputs.get(name))
                    if v != last:
                        await srv.write_attribute_value(node.nodeid, ua.DataValue(ua.Variant(v, vt)))
                        rec[4] = v
                for node, name, t, vt in self.nodes_out:
                    dv = aspace.read_attribute_value(node.nodeid, ua.AttributeIds.Value)
                    if dv is not None and dv.Value is not None:
                        ext.set_output(name, dv.Value.Value)
                ext.status['polls'] += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                ext.status['errors'] += 1
                ext.status['error'] = str(e)
            await asyncio.sleep(period)


class OpcUaClientDriver(PollingDriver):
    def __init__(self, ext, ctx):
        super().__init__(ext, ctx)
        self.url = str(ext.cfg.get('endpoint') or 'opc.tcp://127.0.0.1:4840')
        self.client = None
        self.ext.status['peer'] = self.url
        for m in ext.mapping:
            try:
                ua.NodeId.from_string(m['addr'])
            except Exception:
                raise ValueError(_tr('{name} 的 NodeId 写法不对：{addr}（例：ns=2;s=Application.GVL.Start）', name=m["name"], addr=m["addr"]))

    async def connect(self):
        c = Client(self.url, timeout=3)
        if self.ext.cfg.get('username'):
            c.set_user(self.ext.cfg['username'])
            c.set_password(self.ext.cfg.get('password') or '')
        await c.connect()
        self.client = c
        self.w_nodes, self.w_meta, self.r_nodes, self.r_meta = [], [], [], []
        for m in self.ext.mapping:
            node = c.get_node(m['addr'])
            t = (m.get('type') or 'BOOL').upper()
            if m['dir'] == 'in':
                self.w_nodes.append(node)
                self.w_meta.append((m['name'], t))
            else:
                self.r_nodes.append(node)
                self.r_meta.append((m['name'], t))
        # 写入时用服务器上节点的真实类型（CODESYS 的 INT 是 Int16，类型不对会被拒绝）
        self.w_vt = []
        for node, (name, t) in zip(self.w_nodes, self.w_meta):
            try:
                vt = await node.read_data_type_as_variant_type()
            except Exception:
                vt = VT.get(t, ua.VariantType.Double)
            self.w_vt.append(vt)

    async def close(self):
        if self.client is not None:
            try:
                await self.client.disconnect()
            except Exception:
                pass
            self.client = None

    async def exchange(self):
        ext = self.ext
        if self.w_nodes:
            vals = [ua.DataValue(ua.Variant(_cast(t, ext.inputs.get(name)) if vt != ua.VariantType.Float else float(ext.inputs.get(name) or 0), vt))
                    for (name, t), vt in zip(self.w_meta, self.w_vt)]
            await self.client.write_values(self.w_nodes, vals)
        if self.r_nodes:
            vals = await self.client.read_values(self.r_nodes)
            for (name, t), v in zip(self.r_meta, vals):
                ext.set_output(name, v)
