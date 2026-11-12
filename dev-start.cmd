@echo off
rem Dev: start the server (http://localhost:8800, if not running) and the Electron desktop client from source.
rem Options: fresh (wipe client data) / legacy (old Edge window instead of Electron) / noserver (client only). nomes is ignored since 5.0.1 (the teaching MES pages are part of web\), student / full since 4.3.
rem Overrides: VF_PYTHON (Python interpreter), VF_NODE_DIR (folder with node/npm), VF_DEV_CLIENT_HOME (client data); see tools\dev-start.ps1.
set "OPT="
for %%a in (%*) do (
  if /i "%%~a"=="fresh" call set "OPT=%%OPT%% -Fresh"
  if /i "%%~a"=="legacy" call set "OPT=%%OPT%% -Legacy"
  if /i "%%~a"=="noserver" call set "OPT=%%OPT%% -NoServer"
  if /i "%%~a"=="nomes" call set "OPT=%%OPT%% -NoMes"
  if /i "%%~a"=="student" call set "OPT=%%OPT%% -Edition student"
  if /i "%%~a"=="full" call set "OPT=%%OPT%% -Edition full"
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\dev-start.ps1" %OPT%
if errorlevel 1 pause
