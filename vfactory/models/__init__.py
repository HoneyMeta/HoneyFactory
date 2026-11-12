from .logistics import AGVFleet, Warehouse
from .machining import CNC, DeburrCell, Inspection
from .melting import InductionFurnace, TreatmentStation
from .molding import CoolingLine, MoldingLine, SandSystem, ShotBlast
from .people import Receiving, WorkerCrew

REGISTRY = {
    'induction_furnace': InductionFurnace,
    'treatment': TreatmentStation,
    'sand_system': SandSystem,
    'molding_line': MoldingLine,
    'cooling_line': CoolingLine,
    'shot_blast': ShotBlast,
    'cnc': CNC,
    'deburr_cell': DeburrCell,
    'inspection': Inspection,
    'agv_fleet': AGVFleet,
    'warehouse': Warehouse,
    'worker_crew': WorkerCrew,
    'receiving': Receiving,
}

from .generic import GENERIC  # noqa: E402

REGISTRY.update(GENERIC)

from .cell import Cell  # noqa: E402

REGISTRY['cell'] = Cell

from ..plc.station import HmiStation, PlcStation  # noqa: E402  4.3：PLC、HMI 是独立设备
REGISTRY['plc'] = PlcStation
REGISTRY['hmi'] = HmiStation

from ..netmodel import register as _register_net  # noqa: E402

_register_net(REGISTRY)                  # 4.3：网关 / 交换机 / SCADA / MES（通讯层与信息系统，见 vfactory/netmodel.py）
