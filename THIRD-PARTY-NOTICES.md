# Third-party notices

HoneyFactory, Copyright (C) 2026 蜂元科技（郑州）有限责任公司 (HoneyMeta Technology (Zhengzhou) Co., Ltd.), is licensed
under AGPL-3.0-or-later (see [LICENSE](LICENSE)). It builds on the open-source projects and assets listed below. Each
component is licensed under its own terms; the license texts are included in the respective packages (Python wheels,
npm packages), next to the bundled files in this repository, and, for the Docker image and the desktop client, in the
installed packages. This list covers direct dependencies and the components bundled into the web UI, the server and
the desktop client; transitive dependencies are listed in the package metadata (`pip show`, `web/package-lock.json`,
`desktop/package-lock.json`). At the time of writing all npm dependencies in both lock files, including transitive
ones, are under permissive licenses (MIT, ISC, BSD, Apache-2.0, BlueOak-1.0.0, 0BSD, Python-2.0, WTFPL, CC0).

## Acknowledgement: ktg-mes

The module division and the data structures of the teaching MES (`vfmes/`) were designed with reference to the module
division of the open-source MES **ktg-mes** (https://gitee.com/kutangguo/ktg-mes). The teaching MES's source code and
user interface are written independently; no ktg-mes source code is included. We thank the ktg-mes authors. ktg-mes
is distributed under the MIT License:

```
The MIT License (MIT)

Copyright (c) 2018 ktg

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

## Python runtime dependencies

From `requirements.txt`; the teaching MES additionally needs `tools/client/mes-requirements.txt`.

| Package | Used for | License |
|---|---|---|
| FastAPI | web framework | MIT |
| Starlette (via FastAPI) | ASGI toolkit, static files | BSD-3-Clause |
| Pydantic (via FastAPI) | request validation | MIT |
| Uvicorn (`uvicorn[standard]`, with websockets, httptools, watchfiles) | ASGI server, WebSocket | BSD-3-Clause (websockets BSD-3-Clause, httptools MIT, watchfiles MIT) |
| NumPy | numerics (statistics, experiments, optimisation) | BSD-3-Clause; the wheels bundle OpenBLAS (BSD-3-Clause) and the GCC runtime (GPL-3.0 with the GCC Runtime Library Exception) |
| PyYAML | plant and template files | MIT |
| asyncua (opcua-asyncio) | OPC UA server, external-PLC OPC UA driver, protocol checks | LGPL-3.0-or-later |
| pymodbus | Modbus TCP servers and clients | BSD-3-Clause |
| amqtt | embedded MQTT broker and MQTT client | MIT |
| openpyxl | Excel import/export (point tables, rosters, reports) | MIT |
| python-docx | Word reports | MIT |
| python-pptx | PowerPoint reports | MIT |
| Pillow | server-side charts and images | MIT-CMU (HPND) |
| cryptography | Ed25519 signatures for licence files and course packages | Apache-2.0 OR BSD-3-Clause |
| SQLAlchemy (teaching MES only) | database access of `vfmes/` | MIT |

asyncua is used unmodified as a separately installed library, as the LGPL permits. If you distribute HoneyFactory,
including under a commercial license or inside the desktop client's bundled Python runtime, keep it replaceable (as an
installed package, not merged into other code) and include its license text.

No dependency of HoneyFactory is under the AGPL, the GPL (other than the GCC runtime under its library exception) or a
license that restricts commercial use, so the HoneyFactory commercial license needs no additional third-party
commercial license.

## Web UI dependencies

From `web/package.json`; bundled into `web/dist` by the build.

| Package | Used for | License |
|---|---|---|
| Vue | UI framework | MIT |
| Vue Router | routing | MIT |
| Vue I18n | translations | MIT |
| Element Plus, @element-plus/icons-vue | UI components, icons | MIT |
| Apache ECharts | charts | Apache-2.0 |
| three.js | 3D views | MIT |
| Vue Flow (`@vue-flow/core`, `background`, `controls`, `minimap`) | flow-chart view | MIT |
| CodeMirror 6 (`@codemirror/*`), Lezer (`@lezer/highlight`) | Structured Text and script editors | MIT |
| splitpanes | resizable panels | MIT |
| qrcode-generator | QR code for binding an authenticator app (operations console) | MIT |

Build tools (not part of the shipped UI): Vite (MIT), @vitejs/plugin-vue (MIT), TypeScript (Apache-2.0), vue-tsc
(MIT).

## Files bundled in this repository

| Files | Component | License |
|---|---|---|
| `vfactory/static/apidocs/swagger-ui-bundle.js`, `swagger-ui.css` | Swagger UI (offline API documentation at `/docs`) | Apache-2.0, `LICENSE-swagger-ui.txt` |
| `vfactory/static/apidocs/redoc.standalone.js` | Redoc (offline API documentation at `/redoc`) | MIT, `LICENSE-redoc.txt` |
| `web/public/models/factory/*.glb` | Kenney **Factory Kit** 3.0 (conveyors, robot arm, boxes, hopper, screens, pipes) | CC0 1.0, `LICENSE-Kenney-Factory-Kit.txt` |
| `web/public/models/people/*.glb` | Kenney **Mini Characters** 1.0 (workers) | CC0 1.0, `LICENSE-Kenney-Mini-Characters.txt` |

The Kenney assets (https://www.kenney.nl) are in the public domain under CC0; we credit Kenney with thanks, as the
author asks (not required). Foundry equipment, CNC machines and AGVs are generated procedurally in code. Logos,
illustrations and course covers under `web/public/brand/`, `web/public/art/` and `docs/brand/` were made for
HoneyFactory and are part of it; the names and logos "HoneyMeta" and "HoneyFactory" identify the copyright holder's
products (see [NOTICE](NOTICE)).

## Desktop client

From `desktop/package.json`; built on Windows with `tools/build_electron.ps1`.

| Component | Used for | License |
|---|---|---|
| Electron (includes Chromium and Node.js) | desktop shell | MIT; Chromium and Node.js components under their own licenses, listed in `LICENSES.chromium.html` and `LICENSE` in the installed client |
| electron-updater | automatic updates | MIT |
| electron-builder (build only) | installer and portable build | MIT; the generated installer uses NSIS (zlib/libpng license) |
| Python 3.12 embeddable package | local server runtime in the client | PSF License (Python-2.0) |

The client also bundles the Python packages listed above (and SQLAlchemy for the teaching MES).

## Docker images

| Image | Used for | License |
|---|---|---|
| `python:3.12-slim-trixie` | runtime base of the HoneyFactory image (Debian packages under their own licenses; Python under the PSF License) | various |
| `node:22-bookworm-slim` | build stage for the web UI only, not part of the final image | various |

Debian packages added to the runtime image: `fonts-wqy-microhei` (WenQuanYi Micro Hei, Apache-2.0 or GPL-3.0 with font
embedding exception; used to draw CJK text in report charts), `tzdata` (public domain), `tini` (MIT).

## Demo data

The demo plant `foundry-housing` (a ductile-iron steering-housing foundry with machining), its products, orders,
workers and process data, the plant templates, the courses and the demo class are fictional. They are part of
HoneyFactory and licensed under AGPL-3.0-or-later.
