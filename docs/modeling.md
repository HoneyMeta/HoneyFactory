# Modeling

A HoneyFactory plant is a model file `plants/<plant>.yaml` (the file name is the plant id). Every file in `plants/`
runs when the server starts. New plants are created in the UI from the templates in `templates/` (blank plant,
foundry, machining, foundry + machining, full showcase) or by copying an existing plant. The recommended way to change
a plant is the workbench in the UI; you can also edit the YAML and restart.

## Model kernel

The model (`version: 2`) is made of **blocks**, **links** and **groups** (`vfactory/flow/`):

- `catalog.py`: block types, their parameters, ports and layer;
- `model.py`: the model, edit commands and validation;
- `expr.py`: the expression language.

Generic blocks: source, process, batch, buffer, conveyor, inspection (pass and NG outputs), rework, assembly, split,
sink, warehouse, worker pool and transport fleet. High-fidelity process models (foundry and machining, see below)
are available as advanced blocks. A `submodel` block refers to a definition in the model's `submodels` section; it can
be nested and expose parameters, and its inner blocks are real devices at run time.

Each block type has a layer: `process`, `field`, `control`, `network` or `it`. There are three kinds of links:

| Link | Connects | Fields |
|---|---|---|
| material | process blocks | transport fleet, product filter, condition, weight, queue capacity |
| signal | device ⇄ PLC | `signals: [{point, ch, dir}]`, channels like `I0.0`, `Q0.0`, `IW64` |
| network | device / PLC / switch / gateway / SCADA / MES | `protocol`, optional `fault` |

### Expressions

Times, intervals, defect probabilities and other parameters accept distributions and formulas: `normal`, `expo`,
`tri`, `lognormal`, `noise`, `walk`, `lag`, `ramp`, `pulse`, `if_`, `tag`, `param`, `tbl('table', key, 'column')`.
Expressions are evaluated by an AST allow-list, never with `eval`. Any block can have **custom points** (formula
driven, published on all protocols) and **parameter bindings**.

### Data-driven models

- Global data tables in the model's `tables` section (CSV or Excel import).
- A source block can release material from a table (time, product, quantity, order; optionally looping).
- Routing tables generate per-product process times and changeover matrices; BOM tables drive assembly blocks.

### Failures, changeovers, people

- Failures by operating time or calendar time (`fail_basis`), Weibull shape (`fail_beta`), log-normal repair times.
- Sequence-dependent changeover matrices (`setup_matrix`).
- Worker pools with names, skills and efficiency (`workers`, `skill`); process blocks follow shifts by default
  (`follow_shifts`). Workers walk to the devices that need them, and their position and state are published as points
  (like UWB tracking).
- Production plan: shifts and working days, breaks, planned downtime, products (cycle-time factor, changeover time)
  and orders.

### Action-level signals

Machining centres (guard door, clamping cylinder, spindle, NC program block, cycle start/stop), moulding lines (sand
shooting, squeeze and push-out cylinders) and deburring robots (gripper, fixture clamp, program step) publish the
actions inside each cycle under `Actions/` (`vfactory/actions.py`). Each change is published over MQTT and OPC UA with
the exact simulated time of the action (milliseconds); every action has a standard duration plus jitter, and without
faults the simulation results are the same as without action signals. Generic process blocks switch them on with the
parameter `actions: cnc|press|robot`. `GET /api/p/<plant>/actions` shows each device's action template, action faults
and last durations.

Action faults slow individual actions, and the extra time is added to the cycle, so output drops:

- `cyl_leak`: a leaking cylinder extends `extra_s` seconds slower, optionally getting worse by `drift_s_per_day`;
- `sticky_clamp`: the fixture releases slowly;
- `slow_door`: the guard door moves slowly.

Inject them from the device's fault menu, in scenarios (`cyl_leak:cyl=clamp,extra_s=2`), with
`POST /api/p/<plant>/station/<device>/fault {"kind": "cyl_leak", "params": {"extra_s": 2}}` or the block parameter
`action_faults`. This is what cycle-time analysis in an MES (for example HoneyMOM's breakdown down to individual
machine actions) is meant to find.

## Workbench

The workbench (`/p/<plant>/workbench`) works like a game-engine editor: the same viewport shows the running plant and
edits it.

- **Three views of one model:** 3D, floor plan and flow chart, plus an architecture view with four swim lanes
  (information systems, communication, control, production equipment).
- **States:** running, paused, editing (after reset) and replay. Parameter and position changes made while paused
  apply to the running plant; structural changes ask to save and rebuild when you press run.
- **Run control:** reset (rebuild and warm up; warm-up results are cached by model content), run/pause (space), step
  (next event, 1 min, 10 min, 1 h), run to (N hours, a time, a device entering a state), speed 1× to 3600×.
  API: `POST /api/p/<plant>/ctl {action: play|pause|step|run_to|cancel}`, `POST /api/p/<plant>/ctl/reset`.
- **Breakpoints:** a device enters a state or stays in it longer than N minutes, alarms, buffer levels, plant KPIs,
  point values, events, times. Set them from the context menu of any view (F9); a hit pauses the plant and shows
  where. API: `/api/p/<plant>/breakpoints`.
- **Replay:** a snapshot every simulated minute (kept for 24 hours); drag the timeline or jump to a marked fault.
- **Draft → check → trial run → apply:** every edit goes through a command bus (undo/redo, auto-saved draft); a trial
  run compares the draft with the current model in the background; applying hot-updates parameters and rebuilds for
  structural changes; each apply stores a version that can be compared and restored.
- **Object panel:** select anything to see all its relations (upstream/downstream material, the PLC that controls it,
  every signal with channel and live value, network links, reporting path) and jump between them (Alt+←/→).
- **Floor plan (CAD-like):** metric placement, snapping (orthogonal, midpoint, perpendicular), typed lengths and
  angles, walls, zones, doors, dimensions, AGV road network with one-way edges, multiple floors, DXF underlay import
  (`POST /api/p/<plant>/underlay/dxf`), image underlay with two-point calibration.
- **3D:** measuring, camera bookmarks, first-person walk, box select, align, array, heat-map layers (utilisation, OEE,
  power), bottleneck colouring, "follow one part" through the plant.
- **Layer filter and search:** show/hide by layer and link kind; Ctrl+F finds names, ids, IP addresses, PLC channels
  and signal names.

The UI is organised in workspaces (general, teaching, design, commissioning), each with its own default view and
panels. Panels are registered in `web/src/editor/shell/panels.ts`; `web/src/panels/*/index.ts` are loaded
automatically; 3D view extensions live in `web/src/scene_ext/*.ts`.

## Control layer and soft PLC

- **Control cells** (`vfactory/control/`, `vfactory/models/cell.py`): device-level sensors, actuators and kinematics:
  belt, roller and chain conveyors; photoelectric, inductive, capacitive, vision and height sensors; encoders; push
  cylinders, stoppers, swing arms, turntables, lifts, pick-and-place handlers, stacker cranes; push buttons, e-stops,
  indicator lights (32 component types), each with an I/O table and component-level faults. 15 training scenes are
  generated by `vfactory/control/scenes/build.py`.
- **PLC, HMI, gateway, switch, SCADA and MES** are separate blocks. One PLC controls several devices through signal
  wires (`vfactory/plc/station.py`). Every device has standard control points (running, fault, part present, done
  count into the PLC; run enable and fault reset out of the PLC; plus type-specific points, see
  `vfactory/control/iface.py`). A device wired to a run-enable output waits for the PLC (time category `wait_plc`).
- **Soft PLC** (`vfactory/plc/`): ladder diagram and Structured Text, with its own compiler and virtual machine (no
  `exec`/`eval`). Online monitoring, forcing, breakpoints, single step, download in run mode with variable values
  kept, PLCopen XML import/export, cross-references, double-coil warnings, I/O timing diagram (logic analyser),
  scan-time warnings. HMI screen editor.
- **External PLC:** a cell can be driven by a real PLC over Modbus (server or client), OPC UA or S7.
- API: `/api/p/<plant>/cells/<plc>/program|compile|download|online|plc|external`, `/api/p/<plant>/plc/status`,
  `/api/p/<plant>/plc/<plc>/io`, `/api/p/<plant>/hmi`.

## Analysis

- **Time categories** per device: running, changeover, starved, blocked, failed, idle, planned downtime, off shift,
  disabled (`plant.class_log`), warm-up excluded. WIP sampled every minute, lead time P50/P90, OEE by period.
  `GET /api/p/<plant>/analysis/stats?hours=&warmup=1`.
- **Common random numbers:** cycle time, failures, routing, product mix and quality each use an independent random
  stream derived from seed + block id + purpose, so changing one parameter does not shift unrelated random events.
- **Bottleneck analysis:** active-period method (shifting bottleneck), groups of identical devices combined,
  blocking/starving and buffer levels as supporting evidence, ties reported when the top two are within 5 percentage
  points, continuous-process devices excluded with a reason. `GET /api/p/<plant>/analysis/bottleneck`.
- **Experiments:** baseline plus variants (add/remove devices, parameters, set-points, staffing, buffers, a model
  version, another shift plan) or a full-factorial design; N replications with common seeds; mean ± 95 % confidence
  interval (t distribution), paired differences and significance; warnings when replications are too few. Export
  Excel/CSV. `POST /api/p/<plant>/experiments`.
- **Optimisation:** decision variables (parameters, buffer sizes, number of devices, staffing), one or more
  objectives, constraints; genetic algorithm or random search in a process pool; recommended solution, Pareto front
  and convergence. `POST /api/p/<plant>/optimize`.
- **Fork from now:** copy the running plant twice (as is / with changes), fast-forward N hours in the background and
  compare KPIs without touching the running plant. `POST /api/p/<plant>/fork`.
- **Sankey and Gantt charts:** actual part flow (rework loops unrolled), Gantt by resource, order or part.
- **Energy:** power by state (`power_by_state`), 15-minute peak demand, time-of-use tariffs, demand charges, CO₂,
  energy per part. `/api/p/<plant>/analysis/energy`, `GET|PUT /api/p/<plant>/energy/settings`.
- **Scenarios:** timed scripts of faults, disturbances and operator actions (inject fault, write set-point, ramp,
  disable, absence, communication fault). Every action is recorded in the ground-truth labels.
- **Datasets:** time series + events + parts (with true defects) + label intervals, exported as ZIP, for training and
  validating AI algorithms against a known ground truth.
- **Reports:** production, scrap, energy, lead-time distribution, time breakdown, bottleneck, conclusions; Excel and
  PDF; Word/PowerPoint design reports with embedded charts and your company template (`/api/report/templates`). All
  numbers come from one summary (`history.summary`) and are checked for consistency before export
  (`/report/export/check`).

## Process models of the demo plant

The demo plant `foundry-housing` is a fictional ductile-iron steering-housing foundry with machining: melting →
nodularising → moulding and pouring → cooling and shake-out → shot blasting → CNC machining → robot deburring →
automated borescope inspection → automated warehouse, plus an AGV fleet and a sorting control cell (ladder program
and HMI). Its high-fidelity models:

| Station | Model |
|---|---|
| Induction furnace | energy balance m·dh/dt = η·P − Q_rad − Q_wall with latent heat of melting; enthalpy mixing when cold charge is added; heats, spectrometer chemistry, cooling-water temperature rise, lining wear and leakage current |
| Nodularising and inoculation | two-ladle scheduling timed by the moulding cycle; magnesium recovery, temperature loss, Newtonian ladle cooling, residual-magnesium fade, return to furnace on timeout |
| Sand plant | PI-controlled water addition, evaporation depending on return-sand temperature; compactability and green strength vs moisture; hopper level |
| Moulding line and pouring | moulding cycle, waiting for iron; per casting, gas porosity, shrinkage, cold shuts and poor nodularity sampled with logistic models of pouring temperature, moisture, compactability, residual Mg and carbon equivalent |
| Cooling line, shot blasting | cooling time and shake-out temperature; blast batches, wheel current, shot consumption; visual detection of cold shuts, test bars for nodularity |
| CNC machining centre | Kienzle cutting force → spindle power and load; extended Taylor tool life; three-stage flank-wear curve; tool change at end of life, tool breakage; spindle thermal growth + tool wear → bore size (with compensation); drill wear → burrs at cross holes |
| Robot deburring | removal capacity vs brush wear and spindle speed; residual burrs |
| Automated borescope inspection | probability of detection POD(a), sizing error; light intensity and threshold affect misses and false calls; one rework for burrs |
| AGV fleet | task dispatch (blank delivery, finished goods, buffer transfer), polyline driving, battery consumption and charging; VDA 5050-style state |
| Automated warehouse | stacker-crane cycle, scheduled shipments |
| All devices | Weibull failures + log-normal repairs, energy per device, OEE = availability × performance × quality |

Most lines can be built from generic blocks. For a new high-fidelity process model, add a class under
`vfactory/models/`, register it in `REGISTRY` and register its parameters and ports in `vfactory/flow/catalog.py`.

## Headless runs

```bash
python -m vfactory sim --config plants/foundry-housing.yaml --hours 24
python tests/sim_all.py 24        # every file in plants/ and templates/
```
