# HoneyFactory

**English** | [简体中文](README.zh-CN.md)

[![CI](https://github.com/HoneyMeta/HoneyFactory/actions/workflows/ci.yml/badge.svg)](https://github.com/HoneyMeta/HoneyFactory/actions/workflows/ci.yml)
[![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue.svg)](LICENSE)

HoneyFactory is an open-source virtual factory. It simulates a plant from process models (melting, moulding, machining,
inspection, conveyors, robots, AGVs, people) and publishes every signal over real OPC UA, Modbus TCP and MQTT servers,
so MES, SCADA, data platforms and AI algorithms can be developed and tested against it as if it were a real plant. A
browser workbench edits the plant in 3D, on a floor plan, as a flow chart and as a control and network architecture;
a built-in soft PLC (ladder diagram and Structured Text) and HMI editor run the control layer. Courses, classes,
per-student sandboxes and automatic grading make it a training system for PLC programming and production operations.
The backend is Python (FastAPI, asyncua, pymodbus, amqtt), the web UI is Vue 3 with three.js. A demo plant, a
fictional ductile-iron foundry with machining, runs out of the box.

What makes the data useful for testing:

- **Causal signals.** Every point is computed from process formulas, and stations influence each other (a colder
  pour produces more cold shuts downstream, a worn tool grows the bore size).
- **Real protocols.** Standard clients connect directly; writes change the simulation.
- **Controllable.** Change parameters, inject equipment, component, network and protocol faults, add or remove devices
  while it runs.
- **Ground truth.** The full genealogy and the true defects of every part are recorded, so you can score an AI
  algorithm or an MES against what really happened.

It pairs with [HoneyMOM](https://github.com/HoneyMeta/HoneyMOM), the open-source MOM/MES from the same team: HoneyMOM
onboards a HoneyFactory plant from its standard delivery package and consumes its `_mes` MQTT topics.

- [Features](#features)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [AI configuration](#ai-configuration)
- [Protocols](#protocols)
- [Architecture](#architecture)
- [Roadmap](#roadmap)
- [License](#license)
- [Contributing](#contributing)

## Features

### Simulation and models

- Generic blocks (source, process, batch, buffer, conveyor, inspection, rework, assembly, split, sink, warehouse,
  worker pool, transport fleet) and high-fidelity process models for a foundry and a machine shop: induction furnace
  energy balance, nodularising, sand plant control, defect models for castings, Kienzle cutting force, Taylor tool
  life, tool wear and bore size, borescope inspection with probability of detection. Details in
  [docs/modeling.md](docs/modeling.md).
- Parameters as distributions and formulas, custom formula points, data tables (routings, BOMs, release schedules),
  sub-models, shifts, breaks, products and orders, changeover matrices, Weibull failures, workers with skills who walk
  to the machines that need them.
- Action-level signals for machining centres, moulding lines and robots (door, clamp, spindle, NC block, cylinder
  strokes) published with millisecond timestamps, and action faults such as a leaking cylinder that slows the cycle.
- Several plants run at once; templates for a blank plant, foundry, machine shop, foundry + machining and the full
  demo plant.

### Workbench

- One model, four views: 3D, floor plan (CAD-like: walls, zones, dimensions, AGV road network, DXF underlay), flow
  chart and an architecture view (information systems, network, control, equipment).
- Edit while it runs, like a game-engine editor: run, pause, step, run to a time or a state, speed 1× to 3600×,
  breakpoints on states, values, alarms and KPIs, replay of the last 24 hours, draft → check → trial run → apply with
  undo/redo and versions.
- Object panel with every relation of a device: material flow, the PLC that controls it, signal wires with channel and
  live value, network links and the reporting path.
- Workspaces for general use, teaching, design and commissioning; English and Simplified Chinese UI.

### Control layer and soft PLC

- 32 device-level component types (conveyors, sensors, cylinders, stoppers, turntables, lifts, pick-and-place, stacker
  crane, operator panels) with I/O tables and component faults; 15 training scenes from a motor latch to a full line.
- PLC, HMI, switch, gateway, SCADA and MES as separate devices connected by signal wires and network links.
- Soft PLC with its own compiler and virtual machine for ladder diagram and Structured Text: online monitoring,
  forcing, breakpoints, single step, download in run mode, PLCopen XML import/export, I/O timing diagram,
  cross-references. A real PLC can take over a cell over Modbus, OPC UA or S7.

### Teaching

- Built-in courses: Factory and Equipment Basics, Sensors and Actuators, Production Operations Basics, PLC Control
  Basics (15 lessons), Production Line Simulation and Optimization (machining), Foundry Operations, MES Basics.
- Lesson types: PLC exercise, production-line task graded by KPI, budget and limit rules, fault diagnosis, quiz,
  "point at the device" and MES tasks; teachers build their own courses in a course editor.
- Classes, roster import, assignments, one sandbox per student (sleeps when idle), automatic grading with anti-cheat
  checks, teacher review, fault injection for troubleshooting exercises, live class progress, grade book export.
- AI tutor that gives hints, not answers (optional), and AI-assisted grading suggestions for the teacher.
- A teaching MES (`vfmes/`: work orders, dispatch and reporting, OEE, quality, SPC, traceability, inventory) that the
  desktop client starts locally for MES lessons. Details in [docs/teaching.md](docs/teaching.md).

### Commissioning and integration

- Signal centre: browse all points with their OPC UA, Modbus and MQTT addresses, live values, trends and writes;
  communication faults per protocol × device × point (disconnect, bad quality, delay, jitter, loss, frozen, stuck,
  drift); recording and replay; message capture.
- Network model: link, switch and gateway faults act on all three protocols along the path device → gateway; gateways
  buffer MES reports while a link is down.
- **Standard delivery package** (`points.xlsx` point table, `layout.dxf` floor plan, `*.glb` 3D models, README), the
  same format HoneyMOM's onboarding reads, and a **raw-site mode** that renames tags the way a real integrator would
  (`S7.PLC2.DB10.DBD4`) to test AI-assisted tag mapping against an answer key.
- Test scripts (step tables with assertions over REST, OPC UA and MQTT) in the UI or headless with JUnit output for CI.
- API tokens with scopes, plant restriction, expiry and IP allow-list; OpenAPI documentation at `/docs` and `/redoc`.

### Analysis and design

- Time breakdown per device, WIP, lead times, OEE by period, shifting-bottleneck analysis, Sankey and Gantt charts,
  energy with peak demand and time-of-use tariffs.
- Experiments with replications and 95 % confidence intervals, full-factorial designs, multi-objective optimisation
  (genetic algorithm), "fork from now" what-if runs.
- Scenarios (timed faults and operator actions), datasets with ground-truth labels for AI work, reports in Excel, PDF,
  Word and PowerPoint (with your company template), SOP walk-throughs in 3D.

### Platform

- Roles: administrator, engineer, read-only guest, teacher, student, organisation administrator; audit log.
- Self-hosted (plants run on the server) or SaaS mode (accounts, organisations, seats, courses and grades on the server;
  plants run in the desktop clients), signed offline licence files for seats, an operations console with TOTP. See
  [docs/deployment.md](docs/deployment.md).
- Windows desktop client (Electron) that runs plants locally, works offline and submits homework to a school server.
  See [docs/desktop-client.md](docs/desktop-client.md).

## Quick start

### Docker (demo)

Requires Docker with Compose v2.

```bash
git clone https://github.com/HoneyMeta/HoneyFactory.git
cd HoneyFactory
docker compose up
```

The first run builds the image (a few minutes). Then open http://localhost:8800 and log in as `admin` with password
`honey123` (also `engineer` and the read-only `guest`, same password). The demo class has the teacher `demo_teacher`
(`teach123`) and the students `demo_s01` … `demo_s06` (`123456`). The demo plant `foundry-housing` is running; connect
an OPC UA client to `opc.tcp://localhost:4840/vfactory/`, an MQTT client to `localhost:1883` (topic `vfactory/#`) or
a Modbus client to `localhost:5020`.

For production (no demo accounts, the first start asks you to create the administrator):

```bash
cp docker/env.example .env        # VF_LANG, TZ, ports, AI endpoint ...
docker compose -f docker-compose.yml -f docker/compose.production.yml up -d
```

See [docs/deployment.md](docs/deployment.md) for production, HTTPS, backups and the SaaS mode.

### Manual setup (development)

Requires Python 3.12 and Node.js 20 or later.

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cd web && npm ci && npm run build && cd ..

VF_DEMO=1 python -m vfactory serve   # Windows: set VF_DEMO=1 && python -m vfactory serve
```

Open http://localhost:8800. Without `VF_DEMO=1` you get a production install: no accounts; create the administrator
in the browser or with `python -m vfactory create-admin --username admin`. On Windows, `run.cmd` does the same
(`VF_PYTHON` selects the interpreter).

For front-end work, run `npm run dev` in `web/` (Vite dev server; `/api` and `/ws` are proxied to port 8800).

Without a server, fast-forward a plant and print its KPIs:

```bash
python -m vfactory sim --config plants/foundry-housing.yaml --hours 24
```

## Configuration

HoneyFactory reads environment variables at start-up. The most used ones:

| Variable | Default | Meaning |
|---|---|---|
| `VF_DEMO` | off | `1`: demo accounts (password `honey123`) and the demo class. Off: production install, no accounts. |
| `VF_LANG` | `en` | Server language, `en` or `zh-CN`: default for requests without a language and language of the running plants. |
| `VF_HOME` | program directory | Data directory: `data/` (database, drafts, versions, recordings, sandboxes), `plants/`, `config/`, `logs/`. |
| `VF_MODE` | `selfhost` | `selfhost` or `saas` (see [docs/deployment.md](docs/deployment.md)). Also `config/deploy.json`. |
| `VF_LLM_BASE_URL`, `VF_LLM_API_KEY`, `VF_LLM_MODEL` | – | OpenAI-compatible model endpoint for the AI features. |
| `VF_SANDBOX_MAX_ACTIVE`, `VF_SANDBOX_IDLE_S` | `40`, `600` | Student sandboxes running at once; idle seconds before a sandbox sleeps. |
| `VF_HTTPS` | off | `1`: treat requests as HTTPS behind a proxy that does not send `X-Forwarded-Proto`. |

`python -m vfactory serve` takes `--http` (default 8800), `--opcua` (4840), `--mqtt` (1883), `--modbus` (5020, first
Modbus port) and `--no-mqtt`. The full list, including security, SaaS and desktop-client variables, is in
[docs/configuration.md](docs/configuration.md).

## AI configuration

The AI features (the modeling assistant on every page, the AI tutor for students, AI grading suggestions for
teachers) use the OpenAI chat-completions API format (`POST <base_url>/chat/completions`, with tool calling), so they
work with hosted services and with self-hosted servers such as vLLM, Ollama or LM Studio that offer an
OpenAI-compatible endpoint.

Configure the endpoint either with environment variables

```bash
VF_LLM_BASE_URL=https://api.example.com/v1
VF_LLM_API_KEY=...
VF_LLM_MODEL=your-model-name
```

or by copying `config/llm.example.json` to `config/llm.local.json` (in the data directory, git-ignored) and filling it
in. Environment variables take precedence over the file.

HoneyFactory ships with no model endpoint, model name or key, and no keys are stored in the repository. AI stays off
until all three values are configured; the tutor then falls back to the built-in hints. Model changes proposed by the
assistant are tried on a copy first and applied only after you confirm them. When a model is configured, prompts that
contain model data, plant data and student answers are sent to that endpoint. Desktop clients without their own
configuration use the server's AI proxy (`/api/ai/proxy`), so the key stays on the server.

## Protocols

| Service | Default address | Notes |
|---|---|---|
| Web UI and REST API | `http://<host>:8800` | `/api/...`, WebSocket `/ws/<plant>`, OpenAPI at `/docs` and `/redoc` |
| OPC UA | `opc.tcp://<host>:4840/vfactory/` | NodeId `ns=2;s=<plant>/<device>/<point>`, AnalogItemType with EU and range, HistoryRead (24 h), Alarms & Conditions events |
| Modbus TCP | `<host>:5020` and up | one port per plant, one unit per device, holding registers from 1000, `float32` ABCD by default |
| MQTT | `<host>:1883` | embedded broker; `vfactory/<plant>/<area>/<device>/<point>`, writes on `.../set` with `.../set/ack` |
| MQTT for MES | same broker | `vfactory/<plant>/_mes/part` (part events), `vfactory/<plant>/_mes/event` (production log) |
| Delivery package | `GET /api/p/<plant>/delivery.zip` | `points.xlsx`, `layout.dxf`, `models/*.glb`, `README.md` |

Payloads, gateways, faults, protocol settings and test scripts: [docs/protocols.md](docs/protocols.md).

## Architecture

```
  Browser (Vue 3 + three.js)            Windows desktop client (Electron)       MES / SCADA / AI clients
  workbench, signal centre, courses     same UI, local server, offline work     (HoneyMOM, UaExpert, Node-RED ...)
              │ HTTP /api, WebSocket /ws          │ /api proxy, homework              │ OPC UA / Modbus / MQTT
 ┌────────────┴───────────────────────────────────┴───────────────────────────────────┴──────────┐
 │ HoneyFactory: one Python process (FastAPI)                                                      │
 │   plants: simulation kernel + process models + control cells + soft PLC + network model         │
 │   protocol servers: OPC UA (asyncua), Modbus TCP (pymodbus), MQTT broker (amqtt)                │
 │   workbench API · run control · analysis · experiments · reports · delivery package             │
 │   teaching (classes, sandboxes, grading) · AI assistant and tutor · accounts, tenancy, audit    │
 └────────────┬────────────────────────────────────────────────────────────────────────────────────┘
              │ SQLite (data/vf.db), YAML plant files (plants/*.yaml), files under data/
```

- `vfactory/core.py`, `vfactory/models/`: simulation kernel (clock, points, part records, buffers, failures) and
  process models; `vfactory/flow/`: block catalogue, model, edit commands, validation, expressions.
- `vfactory/protocols/`, `vfactory/netmodel.py`, `vfactory/comm.py`: OPC UA, Modbus and MQTT adapters, gateways and
  network faults, communication faults.
- `vfactory/control/`, `vfactory/plc/`: control layer, training scenes, soft PLC (compiler, runtime, PLCopen, external
  PLC drivers).
- `vfactory/server.py`, `editor_api.py`, `runctl.py`, `analysis.py`, `experiment.py`, `report_export.py`,
  `delivery.py`: plant manager and HTTP API, workbench, run control, analysis, experiments, reports, delivery package.
- `vfactory/teach/`, `vfactory/courses/`, `vfactory/tutor.py`: teaching, courses, AI tutor;
  `vfactory/assistant.py`, `copilot.py`: AI assistant; `vfactory/tenancy/`: organisations, seats, licences, SaaS,
  operations console.
- `vfactory/locale/`, `vfactory/i18n.py`: backend translations; content maps in `*/i18n/*.en.json`.
- `vfmes/`: teaching MES; `desktop/`: Electron shell; `web/`: Vue 3 front end, built into `web/dist` and served by the
  backend.
- `plants/`, `templates/`: plant files and templates; `tests/`: offline and API checks (`*_check.py`), browser
  walk-throughs (`*_ui.js`), test scripts.

## Roadmap

Possible next steps, not commitments; discussion and contributions are welcome in the issues:

- more process models and plant templates (injection moulding, assembly, process industry);
- more UI and content languages;
- running the browser walk-throughs (Playwright) in CI;
- a published container image and a Helm chart;
- server-side re-scoring of homework submitted in SaaS mode;
- desktop clients for Linux and macOS.

## License

Copyright (C) 2026 蜂元科技（郑州）有限责任公司 (HoneyMeta Technology (Zhengzhou) Co., Ltd.)

HoneyFactory is licensed under the **GNU Affero General Public License v3.0 or later** ([LICENSE](LICENSE)). If you
run a modified version for users over a network, the AGPL requires you to offer them its source code.

A **commercial license** is available for organisations that want to use HoneyFactory without the AGPL obligations, for
example in a proprietary training product or a hosted service, and it can include support with an SLA. See
[COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md) or contact dev@honeymeta.com, https://www.honeymeta.com.

Third-party components and acknowledgements: [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Contributing

Bug reports, fixes, translations, process models, plant templates and courses are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) first. Contributors sign the [CLA](CLA.md) once; the CLA bot asks on your first pull
request. Please follow the [code of conduct](CODE_OF_CONDUCT.md) and report security problems privately as described in
[SECURITY.md](SECURITY.md).

Main repository: https://github.com/HoneyMeta/HoneyFactory. Read-only mirrors on Gitee and GitCode.
