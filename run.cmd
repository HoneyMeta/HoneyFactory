@echo off
rem HoneyFactory: simulation + OPC UA + Modbus + MQTT + web UI (http://localhost:8800). Close this window to stop.
rem Overrides: VF_PYTHON = Python interpreter (default: python on PATH), VF_NODE_DIR = folder with node/npm,
rem VF_DEMO=1 = demo accounts (admin / honey123), VF_LANG = en or zh-CN, VF_HOME = data directory (default: this folder).
cd /d "%~dp0"
set "PY=python"
if defined VF_PYTHON set "PY=%VF_PYTHON%"
if defined VF_NODE_DIR set "PATH=%VF_NODE_DIR%;%PATH%"
if not exist "web\dist\index.html" (
  echo Building web UI for the first time...
  pushd web && call npm ci && call npm run build && popd
)
if "%VF_DEMO%"=="1" (
  echo HoneyFactory starting in demo mode... open http://localhost:8800  ^(admin / honey123^)
) else (
  echo HoneyFactory starting... open http://localhost:8800  ^(first start: create the administrator in the browser^)
)
"%PY%" -m vfactory serve
pause
