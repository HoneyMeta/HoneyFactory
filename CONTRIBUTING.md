# Contributing to HoneyFactory

Thank you for helping. This page explains how to set up a development environment, which checks to run and how
pull requests are handled.

## Before you start

- **Bugs:** open an issue with steps to reproduce, the version (`/api/health` shows it), how you run HoneyFactory
  (Docker, from source, desktop client; self-hosted or SaaS mode) and the plant you used.
- **Features and larger changes:** open an issue first and describe the problem (the plant, the lesson, the
  integration). Agreeing on the approach before you write code saves both sides time.
- **Security problems:** do not open a public issue; see [SECURITY.md](SECURITY.md).
- **Code of conduct:** [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) applies to all project spaces.

## Contributor License Agreement

HoneyFactory is dual-licensed (AGPL-3.0-or-later and commercial, see [COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md)).
Before we can merge your first pull request you sign the [Individual CLA](CLA.md) once. The CLA bot posts a comment on
your pull request; reply with the sentence it shows. You keep the copyright in your contribution; the CLA allows
HoneyMeta to distribute it under the AGPL and under commercial terms.

## Development setup

Requirements: Python 3.12, Node.js 20 or later, Git. Windows, Linux and macOS work for the server; the desktop client
and its installer are Windows only.

```bash
git clone https://github.com/HoneyMeta/HoneyFactory.git
cd HoneyFactory
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r tools/client/mes-requirements.txt
cd web && npm ci && npm run build && cd ..

VF_DEMO=1 python -m vfactory serve       # http://localhost:8800, admin / honey123
cd web && npm run dev                    # optional, second terminal: Vite dev server with hot reload
```

`VF_HOME=<dir>` keeps a separate data directory per experiment; delete it to start from a fresh database and the demo
plant. `VF_LANG=zh-CN` runs the plants in Chinese (the legacy test suites expect that, see below). On Windows,
`run.cmd` starts the server and `dev-start.cmd` the server plus the Electron client from source (`VF_PYTHON`,
`VF_NODE_DIR` select the interpreter and Node).

## Project layout

| Path | Content |
|---|---|
| `vfactory/core.py`, `vfactory/models/` | Simulation kernel and process models |
| `vfactory/flow/` | Block catalogue (`catalog.py`), model, edit commands and validation (`model.py`), expressions (`expr.py`) |
| `vfactory/protocols/`, `netmodel.py`, `comm.py` | OPC UA, Modbus TCP, MQTT; gateways and network faults; communication faults |
| `vfactory/control/`, `vfactory/plc/` | Control cells and training scenes; soft PLC (compiler, VM, PLCopen, external PLC drivers) |
| `vfactory/server.py`, `editor_api.py`, `api2.py`, `runctl.py` | Plant manager and HTTP API, workbench API, run control |
| `vfactory/analysis.py`, `experiment.py`, `report_export.py`, `delivery.py` | Analysis, experiments, reports, delivery package |
| `vfactory/teach/`, `vfactory/courses/`, `tutor.py` | Teaching, courses, AI tutor |
| `vfactory/assistant.py`, `copilot.py` | AI assistant and model configuration |
| `vfactory/tenancy/` | Organisations, seats, licences, SaaS mode, operations console, security middleware |
| `vfactory/locale/`, `vfactory/i18n.py`, `*/i18n/*.en.json` | Backend translations and content maps |
| `vfmes/` | Teaching MES (started by the desktop client) |
| `web/src/` | Vue 3 front end; translations in `web/src/locales/` |
| `desktop/`, `tools/` | Electron shell; build, release and maintenance scripts |
| `plants/`, `templates/` | Demo plant and templates for new plants |
| `tests/` | Checks (`*_check.py`), browser walk-throughs (`*_ui.js`), test scripts (`tests/scripts/`) |
| `docs/` | Documentation |

## Rules

- **Models stay compatible.** Plant files are data that users edit and save. A change to the model format needs a
  migration on load (see `vfactory/plc/migrate.py` for an example) and the demo plant must give the same KPIs before
  and after (`tests/flow_check.py`).
- **Common random numbers.** Every random decision of a block draws from its own stream (seed + block id + purpose).
  New random behaviour gets a new stream, so existing experiments do not shift.
- **No `eval`/`exec` on user input.** Expressions and PLC programs go through the AST allow-list (`flow/expr.py`) and
  the PLC compiler.
- **Protocol addresses are contracts.** Tag names, block ids, NodeIds, MQTT topics and Modbus addresses are used by
  MES systems such as HoneyMOM and by recorded datasets. Do not rename them; add aliases when a structure changes.
- **Translations.** Backend messages are the original Chinese texts wrapped in `_tr(...)`, with English in
  `vfactory/locale/en.json`; content (courses, scenes, tours, templates, plants) has English maps next to each file
  (`python tools/i18n_maps.py --sync`). The front end has no CJK characters in `web/src` outside
  `web/src/locales/zh-CN.json`; `en.json` and `zh-CN.json` must have the same keys. Compare codes, never display
  texts. Run `python tests/i18n_check.py` and `python tests/i18n_web_check.py`. Details: `docs/translating-content.md`.
- **Permissions and tenants.** New endpoints check roles like the existing ones and filter by organisation
  (`vfactory/tenancy/policy.py`); `tests/tenant_check.py` enumerates every endpoint and fails on new ones that leak.
- **AI proposes, people confirm.** Changes suggested by the assistant are tried on a copy and applied only after the
  user confirms; the tutor never reveals solutions.
- **No secrets or personal data.** No API keys, passwords, tokens, licence signing keys, real customer, school or
  person names in code, plants, courses, fixtures or screenshots. Demo data uses fictional names.

## Tests

Checks without a server (these run in CI):

```bash
python tests/i18n_check.py
python tests/flow_check.py
python tests/layout_check.py
python tests/plc_check.py
python tests/plc_station_check.py
python tests/plc_diag_internal_check.py
python tests/control_check.py
python tests/analysis_check.py --quick
python tests/course_check.py --offline
python tests/courses_check.py --offline
python tests/tutor_point_check.py
python -m vfactory test tests/scripts/smoke_foundry.json --junit test-results/junit.xml
```

Checks against a running demo server (also in CI). Start it on a fresh data directory with the plants in Chinese:

```bash
VF_HOME=/tmp/vf VF_DEMO=1 VF_LANG=zh-CN VF_LLM_FAKE=1 VF_SANDBOX_IDLE_S=20 VF_SANDBOX_MAX_ACTIVE=25 python -m vfactory serve

python tests/api_check.py            # VF_URL defaults to http://127.0.0.1:8800
python tests/check_protocols.py
python tests/protocol_check2.py
python tests/protocol_check3.py
python tests/sim_api_check.py
python tests/workbench_check.py
python tests/editor_check.py
python tests/teach_check.py
python tests/teach_audit_check.py
python tests/course_check.py
python tests/courses_check.py
python tests/coach_overlay_check.py
python tests/package_check.py
python tests/report_check2.py
```

The Python suites send `X-Lang: zh-CN` (`tests/i18n_pin.py`) because they assert Chinese messages. A production
first-run check: start a server without `VF_DEMO` on a fresh data directory and run `python tests/setup_check.py`.

Other checks: `tests/tenant_check.py` (SaaS isolation and security), `tests/client_check.py` and
`tests/mes_edu_check.py` (desktop mode), `tests/delivery_check.py` (delivery package, raw-site mode, action signals),
`tests/sim_all.py 24` (fast-forward every plant and template). Browser walk-throughs use Playwright
(`node tests/workbench_ui.js`, `views_ui.js`, `teach_ui.js`, ...; set `VF_URL` and `SHOT_DIR`); most expect a
`VF_LANG=zh-CN` demo server, `tests/i18n_ui.js` an English one. Run the ones that cover the pages you changed. The web
build must pass: `cd web && npm run build`.

## Pull requests

- Branch from `main`, keep a pull request to one topic, and describe what changed and how you tested it.
- Keep commits focused; we squash or rebase when merging.
- Update the documentation in `docs/` and the README when behaviour, configuration or commands change.
- New dependencies: explain why, and check that the license is compatible with the AGPL and with commercial
  distribution (MIT, BSD, Apache-2.0, ISC, PSF, LGPL are fine; GPL-only and non-commercial licenses are not). Add
  runtime dependencies to [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). 3D models, textures and icons need a
  license that allows redistribution (CC0 or CC-BY with attribution).
- A maintainer reviews the change. CI must be green and the CLA signed before merging.

## Plants, templates and courses

- Plant templates are YAML files in `templates/`; new process models are classes in `vfactory/models/` registered in
  `REGISTRY`, with parameters and ports in `vfactory/flow/catalog.py` (see [docs/modeling.md](docs/modeling.md)).
- Courses are JSON files in `vfactory/courses/` (built by `vfactory/courses/build*.py`), PLC scenes in
  `vfactory/control/scenes/` (built by `scenes/build.py`). Every lesson needs a reference solution that scores full
  marks and a starting point that does not; `python tests/course_check.py --offline` checks both. Add the English
  texts to the content maps.
- Make sure plants, courses and datasets contain no real company, school, person or site names.
