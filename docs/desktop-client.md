# Windows desktop client

The desktop client runs HoneyFactory on a student's or engineer's own PC. It is an Electron shell (`desktop/`)
around the same web UI, served by a local Python server (`python -m vfactory desktop`) that listens on 127.0.0.1 only.
Plants, sandboxes and the teaching MES run on the local machine; the client can log in to a school or company server
for accounts, assignments and grades, or be used stand-alone.


## Install

- `HoneyVF-Setup-<version>.exe`: NSIS installer, per user, installation folder selectable, Start menu and desktop
  shortcuts, file associations for `.vfhw` (homework package) and `.vfplant` (plant). Uninstalling keeps the data
  unless you tick the box.
- `HoneyVF-Portable-<version>.zip`: unzip and run; data stays in `data\` next to the program (for lab PCs with restore
  cards and USB sticks).
- Data of an installed client: `%LOCALAPPDATA%\HoneyVF`.
- The builds are not code-signed, so Windows SmartScreen may warn on first start.

## Using it

- **Login.** The login page offers the default cloud server (`VF_CLOUD_URL`, see
  [configuration.md](configuration.md#desktop-client)), "my school's / company's own server" (address prefilled from
  `server.json` in the installation folder) and "use without a server". After login the client has the same functions
  as the web version, with the user's server role; the local server forwards `/api` and `/ws` to the server, so the
  server token never reaches the page. Logins are remembered for `VF_SESSION_HOURS` (default 7 days) and work offline.
- **Local and server plants** are listed side by side; a server plant can be downloaded to the PC.
- **Courses offline.** All built-in courses are included; lessons unlock and are graded locally ("local estimate").
- **Homework.** Assignments from the server open in a local sandbox; "Submit to teacher" sends program, model and
  answers. Without a network the submission is queued and sent later, or exported as a `.vfhw` package that the
  teacher can import. A self-hosted server re-grades every package itself and ignores the score the client reports.
- **Progress.** While open, the client reports the current lesson, step and local score to the server every minute
  and shortly after each change, so teachers see live class progress.
- **Teaching MES.** The **MES** entry starts the teaching MES (`vfmes/`) for one local plant on demand (127.0.0.1
  only, stops after 30 idle minutes). Its pages are part of the web UI (`web/src/mes/`, routes `/mes/...`); data goes
  through the local server's `/api/mes/*` proxy.
- **AI.** Without its own model configuration the client asks the logged-in server's AI proxy; offline the tutor
  gives the built-in hints only.
- **Shell.** Splash screen, single instance, tray menu (recent plants, homework status, check for updates, settings,
  quit), window position memory, taskbar jump list and badge for pending homework, Windows notifications,
  `vfactory://open?file=...|plant=...|path=...` links. The page sees `window.vfNative` (system dialogs,
  notifications; see `web/src/native.ts`).
- **Protocols.** OPC UA, Modbus and MQTT are off in the client by default and can be switched on in the settings
  (the MES lessons switch them on for the plant they use).

## Updates

The client updates from the server it is connected to (`/api/client/update/`). To publish a new client version on a
server:

```bash
python tools/publish_client_update.py --server http://<server>:8800 --user admin
```

Without a server connection it uses `VF_UPDATE_URL` or `update.json` (`{"url": "..."}`) in the data directory or the
installation's `resources` folder.

## Development

```bat
dev-start.cmd            :: server on :8800 (if not running) + Electron client from source
dev-start.cmd fresh      :: wipe the development client's data first
dev-start.cmd noserver   :: client only
```

`tools\dev-start.ps1` installs Electron into `desktop\node_modules` on first use. Overrides: `VF_PYTHON` (Python
interpreter), `VF_NODE_DIR` (folder with `node`/`npm`), `VF_DEV_CLIENT_HOME` (client data, default
`%LOCALAPPDATA%\HoneyVF-dev`). The local server alone: `python -m vfactory desktop --home <dir> [--server URL]
[--protocols]`.

## Building the installer

On Windows with Node.js and PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File tools\build_electron.ps1 [-Server http://<server>:8800] [-SkipWeb] [-Mirror none]
```

The script builds `web/dist`, prepares a trimmed Python 3.12 embedded runtime with `requirements.txt` (and
`tools/client/mes-requirements.txt` for the teaching MES) in `desktop\.stage`, copies `vfactory`, `templates`, `vfmes`
and `web\dist` into the app resources and runs electron-builder. Output: `dist-electron\`. `-Server` prefills the
server address; `-Mirror cn` (default) downloads Electron from a mirror, `-Mirror none` uses the official download
location. The version number comes from `vfactory/__init__.py`.

The older client (C# launcher + Edge app window, IExpress installer) is still buildable with
`tools\build_client.ps1`; output in `dist-client\`.

Checks: `tests/client_check.py` (server + desktop mode, login, offline queue), `tests/package_check.py` (homework
packages and server re-grading), `tests/mes_edu_check.py` (teaching MES sidecar), `tests/electron_smoke.js`,
`tests/electron_install_check.ps1`.
