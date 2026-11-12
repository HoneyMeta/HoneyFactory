# Configuration

HoneyFactory is configured with environment variables, command-line options and a few optional files in the data
directory. Plant-specific settings (protocol settings, energy tariffs, shifts, scenarios) are edited in the UI and
stored with the plant.

## Command line

```bash
python -m vfactory serve [--http 8800] [--opcua 4840] [--mqtt 1883] [--modbus 5020] [--no-mqtt]
python -m vfactory create-admin [--username U] [--password P] [--name N]
python -m vfactory sim  --config plants/foundry-housing.yaml --hours 8
python -m vfactory test tests/scripts/smoke_foundry.json [--config plants/...] [--junit out.xml] [--no-protocols]
python -m vfactory desktop [--home DIR] [--server URL] [--protocols] [--port 0]
```

- `serve`: runs every plant in `<data dir>/plants/` with the web UI, the API and the protocol servers. `--modbus` is the
  first Modbus TCP port; each plant uses its own port (`modbus_port` in the plant file). The server listens on all
  interfaces (`0.0.0.0`).
- `create-admin`: first administrator of a production install (same rules as the browser form: at least 8
  characters, not a well-known initial password; only while no active administrator exists).
- `sim`: fast-forwards one plant without UI and prints its KPIs.
- `test`: runs test scripts headless (see [protocols.md](protocols.md#recording-capture-and-test-scripts)).
- `desktop`: local server of the Windows client (see [desktop-client.md](desktop-client.md)).

Uvicorn's `FORWARDED_ALLOW_IPS` (default `127.0.0.1`) decides which reverse proxies are trusted for
`X-Forwarded-For`; login rate limiting, IP allow-lists and the audit log use the resulting client address.

## Environment variables

### General

| Variable | Default | Meaning |
|---|---|---|
| `VF_DEMO` | off | `1`: create the demo accounts `admin` / `engineer` / `guest` (password `honey123`) and the demo class (`demo_teacher` / `teach123`, `demo_s01`–`demo_s06` / `123456`) on a fresh database. Never in SaaS mode. |
| `VF_LANG` | `en` | Server language (`en`, `zh-CN`): default for requests that send no `X-Lang`, `?lang=` or `Accept-Language`, and the language of the running plants. |
| `VF_HOME` | program directory | Data directory. Holds `data/` (SQLite database `vf.db`, drafts, versions, recordings, PLC programs, sandboxes, warm-up cache, report templates), `plants/`, `config/`, `logs/`. Must be set before the process starts. |
| `VF_MODE` | `selfhost` | `selfhost` or `saas`. Also `mode` in `config/deploy.json`; the environment wins. |
| `VF_HTTPS` | off | `1`: treat every request as HTTPS (Secure cookies, HSTS) when the proxy does not send `X-Forwarded-Proto`. |
| `TZ` | system | Time zone used for shifts, reports and timestamps. |

### AI

| Variable | Default | Meaning |
|---|---|---|
| `VF_LLM_BASE_URL` | – | OpenAI-compatible endpoint, e.g. `https://api.example.com/v1` (`/chat/completions` is appended). |
| `VF_LLM_API_KEY` | – | API key for that endpoint. |
| `VF_LLM_MODEL` | – | Model name. |
| `VF_TUTOR_TIMEOUT` | `90` | Seconds the AI tutor waits for an answer before it falls back to the built-in hints. |

The AI features are off until all three `VF_LLM_*` values are set (or `base_url`, `api_key` and `model` in
`config/llm.local.json`; environment variables win). There are no built-in defaults.

### Teaching

| Variable | Default | Meaning |
|---|---|---|
| `VF_SANDBOX_MAX_ACTIVE` | `40` | Student sandboxes that run at the same time; above that the least recently used one sleeps. |
| `VF_SANDBOX_IDLE_S` | `600` | Seconds without a viewer before a sandbox sleeps (simulation stops, state kept in memory). |
| `VF_SANDBOX_UNLOAD_S` | `7200` | Seconds asleep before a sandbox may be saved and unloaded ... |
| `VF_SANDBOX_MAX_LOADED` | `200` | ... when more than this many sandboxes are in memory. |
| `VF_STUCK_MIN` | `10` | Minutes on the same step before the class progress board marks a student as stuck. |

### Security and accounts

These can also be set in `config/deploy.json` under the lower-case name without the `VF_` prefix (for example
`"session_hours": 168`); the environment wins.

| Variable | Default | Meaning |
|---|---|---|
| `VF_SESSION_HOURS` | `168` | Lifetime of a login session (also how long a desktop client stays logged in offline). |
| `VF_LOCKOUT_N`, `VF_LOCKOUT_MIN` | `5`, `15` | Failed logins before an account is locked, and for how many minutes. |
| `VF_IP_FAIL_N` | `30` | Failed logins from one IP address within 10 minutes before it is paused. |
| `VF_PW_POLICY` | – | `strict`: at least 8 characters with letters and digits, not containing the user name, not a common password (always on in SaaS mode). |
| `VF_MAX_BODY_MB` | `64` | Maximum request size (413 above it). |
| `VF_LICENSE_REQUIRED` | off | `1`: without a licence file the trial limits apply (5 teachers, 50 students); otherwise seats are unlimited until a licence is installed. |

### SaaS operations console

| Variable | Default | Meaning |
|---|---|---|
| `VF_OPS_IPS` | – | IP allow-list for `/api/ops` (for example `10.0.0.0/8, 203.0.113.7`); overrides the setting in the console. |
| `VF_OPS_IDLE_MIN` | `15` | Idle minutes before an operations session ends. |
| `VF_OPS_MAX_HOURS` | `8` | Maximum length of an operations session. |

### Desktop client

| Variable | Default | Meaning |
|---|---|---|
| `VF_CLOUD_URL` | placeholder | Default server on the client's login page. Also `"cloud"` in `server.json` next to the installation or `"VF_CLOUD_URL"` in `<data dir>/config/client.json`. Without it the login page asks for a server address. |
| `VF_UPDATE_URL` | – | Update feed of the Electron client when it is not connected to a server. |
| `VF_PYTHON`, `VF_ENTRY`, `VF_SOURCE` | – | Development: interpreter, start script and source folder for the Electron shell. |
| `VF_DEBUG` | off | `1`: allow the developer tools in an installed client. |
| `VF_NODE_DIR` | – | `tools/dev-start.ps1`, `tools/build_electron.ps1`: folder with `node`/`npm` to put in front of `PATH`. |
| `VF_DEV_CLIENT_HOME` | `%LOCALAPPDATA%\HoneyVF-dev` | `tools/dev-start.ps1`: data directory of the development client. |
| `VF_PROGRESS_PERIOD`, `VF_PROGRESS_DELAY` | `60`, `10` | Seconds between progress heartbeats, and delay after a change, for clients reporting to a school server. |

### Tests and development

| Variable | Meaning |
|---|---|
| `VF_URL`, `VF_PLANT` | Server and plant the API checks talk to (default `http://127.0.0.1:8800`, `foundry-housing`). |
| `VF_HOST`, `VF_HTTP`, `VF_OPCUA`, `VF_MQTT`, `VF_MODBUS` | Host and ports the protocol checks connect to. |
| `VF_TEST_LANG` | Language the Python checks send in `X-Lang` (default `zh-CN`, see `tests/i18n_pin.py`). |
| `VF_LLM_FAKE`, `VF_AIGRADE_FAKE` | `1`: canned model answers instead of calling a model (for tests). |
| `VF_MES_PORT`, `VF_MES_RULE_MODULES` | Fixed port of the teaching MES sidecar; extra modules that register MES grading queries. |
| `VF_KEEP_BUILDS` | `web/` build: how many earlier builds' asset files to keep in `web/dist` (default 2, so open pages keep working after an upgrade). |

## Files in the data directory

| File | Content |
|---|---|
| `config/llm.local.json` | `{"base_url": "...", "api_key": "...", "model": "..."}`; template `config/llm.example.json`. Not in git. |
| `config/deploy.json` | Deployment settings, e.g. `{"mode": "saas", "license_required": false, "session_hours": 168, "ops_ips": ""}`. |
| `config/license.vflic` | Licence file for self-hosted installs (also imported in the UI under **Organisation → Licence**). |
| `config/client.json` | Desktop client: default cloud server. |
| `plants/*.yaml` | Running plants (file name = plant id). Written by the workbench when you apply changes. |
| `data/vf.db` | Accounts, tokens, audit log, scenarios, experiments, classes, submissions. |
| `data/recordings/` | Signal recordings. |
| `data/warm-cache/` | Warm-up snapshots by model content (safe to delete). |

Back up `data/`, `plants/` and `config/` (stop the server or copy `vf.db` with SQLite's backup command).
