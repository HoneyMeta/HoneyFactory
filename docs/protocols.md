# Protocols

Every simulated plant publishes its signals over three real protocol servers. Any standard client (UaExpert,
Node-RED, Ignition, a PLC, a SCADA or MES, your own code) can connect to them; there is nothing HoneyFactory-specific
in the wire format.

| Service | Default address | Notes |
|---|---|---|
| Web UI and HTTP API | `http://<host>:8800` | REST under `/api`, live updates over WebSocket `/ws/<plant>`, API docs at `/docs` (Swagger UI) and `/redoc`, both work offline |
| OPC UA | `opc.tcp://<host>:4840/vfactory/` | one server for all plants, anonymous, no encryption |
| Modbus TCP | one port per plant, from `5020` | `modbus_port` in the plant file; new plants get the next free port |
| MQTT | `<host>:1883` | embedded broker; optional login with an API token as password |

Start-up options: `python -m vfactory serve --http 8800 --opcua 4840 --mqtt 1883 --modbus 5020`. Each port can also be
set with `VF_HTTP`, `VF_OPCUA`, `VF_MQTT`, `VF_MODBUS` (see [configuration.md](configuration.md)).

## Point table

Every block of a plant model publishes its points (process values, states, counters, set-points, custom formula
points). The structured point table, with the address of every point in all three protocols, is available from:

- the UI: **Signal centre → Points** (browse, live value, trend, write), export as Excel, CSV or OPC UA NodeSet2;
- the API: `GET /api/p/<plant>/points/v2` (English keys).

## OPC UA

- NodeId: `ns=2;s=<plant>/<device>/<point>`.
- Numeric points are `AnalogItemType` with `EngineeringUnits` and `EURange`; every value carries a `SourceTimestamp`.
- `HistoryRead` returns the last 24 hours of raw values.
- Alarms are published as `AlarmConditionType` events (Alarms & Conditions).
- Writable points (set-points, commands) accept writes; a value outside the range returns `BadOutOfRange` unless
  out-of-range writes are allowed in the protocol settings.

## Modbus TCP

- One TCP port per plant, one Modbus unit id per device.
- All numeric points get an address automatically (holding registers from 1000, `float32` with ABCD word order by
  default). Data type and word order can be changed per point in **Signal centre → Protocol settings**.
- Set-points are writable.
- Standard exception codes: 02 (illegal address), 03 (illegal value), 04 (device failure), 0B (gateway target failed
  to respond, used when the device is cut off by a simulated network fault).

## MQTT

- Topic per point: `vfactory/<plant>/<area>/<device>/<point>`.
- Payload: `{"value": ..., "unit": ..., "quality": ..., "ts": ..., "sim_ts": ..., "wall_ts": ...}`; timestamps are ISO
  8601 with time zone. `ts` follows the clock chosen in the protocol settings (simulation time or wall clock).
- Write: publish to `.../set` either `{"value": x, "id": "<request id>"}` or a plain number. The result comes back on
  `.../set/ack`; failures are also reported on `vfactory/<plant>/_errors`.
- AGVs publish a VDA 5050-style state on `vda5050/v2/<plant>/<agv>/state`.
- Bad-quality values are not flooded: a point that stays bad is republished only when its state changes.
- The broker can require an API token as password (**Settings → API tokens**, token prefix `vf_`).

### MES topics (`_mes`)

For MES and MOM systems the plant also publishes business events, in addition to raw signals:

| Topic | Payload |
|---|---|
| `vfactory/<plant>/_mes/part` | one message per part event: `{sn, type, station, event, t, data, attrs?, sim_ts, wall_ts}` (no simulation ground truth) |
| `vfactory/<plant>/_mes/event` | structured production log: `{seq, t, station, kind, msg, ...fields, sim_ts, wall_ts}` |

[HoneyMOM](https://github.com/HoneyMeta/HoneyMOM) consumes these topics directly. During a protocol-level freeze or
disconnect the `_mes` messages are held and sent in order when the connection recovers, the way an edge gateway
buffers; delay, jitter and packet loss apply to them too. When you inject a fault you can choose to leave `_mes` out.
With a network model, a device whose link to the gateway is down has its reports held at the gateway, and when every
MES node is cut off all `_mes` messages are held.

## Gateways and networks

A plant model can contain a control and network layer: PLCs, HMIs, switches, industrial gateways, SCADA stations and
an MES node, connected by signal wires (device ⇄ PLC) and network links (with a protocol). When a plant has gateways,
devices report through them:

| Protocol | Address through a gateway |
|---|---|
| OPC UA | `ns=2;s=<plant>/<gateway>/<device>/<point>` (under the gateway object) |
| MQTT | `vfactory/<plant>/<gateway>/<device>/<point>`; gateway status on `vfactory/<plant>/<gateway>/_status` |
| Modbus | unit addresses unchanged |

The addresses without a gateway stay available as aliases of the main gateway, so existing clients keep working.
Plants without gateways behave as described above.

Faults on network links (disconnected, delay, jitter, packet loss, bad quality, frozen values) and on switches,
gateways and PLCs act on all three protocols along the path device → gateway. Architecture data:
`GET /api/p/<plant>/architecture`; inject a fault on a link: `POST /api/p/<plant>/architecture/links/<link>/fault`.

## Delivery package

An MES should connect to a plant the way it would on a real site: from the integrator's delivery documents, not from
a private API. The delivery package (`vfactory/delivery.py`) is that set of documents. Download it with the
**Delivery package** button in the signal centre or the workbench toolbar, or `GET /api/p/<plant>/delivery.zip`:

| File | Content |
|---|---|
| `points.xlsx` | four sheets: devices, point table, protocols, notes; column format in [interface/点表格式.md](interface/点表格式.md) (the same format as HoneyMOM's onboarding) |
| `layout.dxf` | floor plan in metres, one layer per kind (`VF_WALL`, `VF_AREA`, `VF_AISLE`, `VF_DEVICE`, `VF_CONVEYOR`, `VF_AGV_PATH`, `VF_TEXT`); devices are blocks with `CODE`, `NAME`, `TYPE` attributes |
| `models/<type>.glb`, `models/scene.glb` | 3D models (from the browser: the models shown in the UI; from the API: simplified models generated on the server) |
| `README.md` | protocol endpoints, OPC UA namespace, MQTT topics and payloads, Modbus conventions, coordinate system |

HoneyMOM imports this package (validate, preview, confirm, then check tag by tag). The OPC UA namespace URI is
`http://honeymeta.cn/vfactory`; clients should resolve its index by URI instead of hard-coding `ns=2`.

### Raw-site mode

Real sites rarely have clean tag names. With raw-site mode (`plant.raw_site`, off by default; the switch in the
delivery-package dialog or `PUT /api/p/<plant>/delivery/raw_site {"on": true}`) the OPC UA and MQTT names change to
integrator-style names (`S7.PLC2.DB10.DBD4`, `M3_ZZFZ`, `.../edge01/PLC2/DB10.DBD4`; a few topics are irregular and one
PLC sends plain-text payloads), and the exported point table only has code, protocol, address and type. The mapping
to the real meaning is written only to `<data dir>/data/delivery/<plant>/answer_key.json`, to score an MES's
AI-assisted tag mapping. Switching rebuilds only the protocol layer; the simulation is not reset.

## Communication faults

Independently of the network model, **Signal centre → Communication faults** injects faults per protocol × device ×
point: disconnect, bad quality, delay, jitter, packet loss, frozen data, stuck value, drift. Faults can also be part
of a timed scenario or a test script, so MES and SCADA error handling can be tested repeatably.

## Protocol settings

**Signal centre → Protocol settings** (per plant):

- clock used for published timestamps (simulation time or wall clock);
- lenient types (accept a string `"12.5"` for a number, and so on);
- whether out-of-range writes are rejected;
- Modbus data type and word order.

## Recording, capture and test scripts

- **Recording and replay** of all signals (`data/recordings/`).
- **Message capture**: MQTT and MES messages filtered by device, export as CSV or JSONL.
- **Test scripts**: step tables (JSON in advanced mode) that set values, inject faults, wait and assert on values
  read back over OPC UA, MQTT or the API. Run them in the UI (**Commissioning** workspace) or headless:

  ```bash
  python -m vfactory test tests/scripts/smoke_foundry.json --junit out.xml
  ```

  Exit code 0 when all steps pass, 1 otherwise. With `--no-protocols` the OPC UA and MQTT assertions are skipped.
  Warm-up snapshots are cached in `data/warm-cache/`, so repeated runs start in seconds.

## External PLCs

The soft PLC of a control cell can be replaced by a real PLC: the cell then exposes its I/O as a Modbus server or
client, over OPC UA or S7 (see [modeling.md](modeling.md#control-layer-and-soft-plc)).

## Checking the protocol servers

With a server running:

```bash
python tests/check_protocols.py    # basic reads and writes, several plants, editing API
python tests/protocol_check2.py    # timestamps, EU ranges, out-of-range writes, HistoryRead, A&C, acks, faults, tokens
python tests/protocol_check3.py    # gateways, network links and faults
```
