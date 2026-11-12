"""外接 PLC 驱动：modbus（服务器/客户端）、opcua（服务器/客户端）、s7（客户端，自带 S7comm 实现）。"""


from ...i18n import _tr
def make_driver(ext, ctx):
    p = ext.protocol
    if p == 'modbus_server':
        from .modbus import ModbusServerDriver
        return ModbusServerDriver(ext, ctx)
    if p == 'modbus':
        from .modbus import ModbusClientDriver
        return ModbusClientDriver(ext, ctx)
    if p == 'opcua_server':
        from .opcua import OpcUaServerDriver
        return OpcUaServerDriver(ext, ctx)
    if p == 'opcua':
        from .opcua import OpcUaClientDriver
        return OpcUaClientDriver(ext, ctx)
    if p == 's7':
        from .s7 import S7Driver
        return S7Driver(ext, ctx)
    raise ValueError(_tr('不支持的协议 {p}（可用：modbus_server、modbus、opcua_server、opcua、s7）', p=p))
