@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Agent Dev Crew - stop

rem ---------------------------------------------------------------------------
rem  Stops whatever start.bat launched.
rem
rem  Closing the server window normally suffices. This exists for the case
rem  where a worker outlives its console and keeps the port bound, which makes
rem  the next launch fail with "address already in use".
rem
rem  The UI port is still swept: `start.bat dev` runs Vite alongside for hot
rem  reload. In the normal one-port setup nothing is listening there and the
rem  sweep simply reports it as free.
rem
rem  netstat reports the pid that *opened* the socket, which after a supervisor
rem  crash can be a pid that no longer exists. So we kill by port, then by
rem  window title, then verify the port is actually free instead of assuming it.
rem ---------------------------------------------------------------------------

set "API_PORT=8000"
set "UI_PORT=5173"

echo.
echo  Stopping Agent Dev Crew ...
echo.

call :kill_port %API_PORT% "app"
call :kill_port %UI_PORT% "hot reload"

rem  Sweep the consoles too: their child may hold the socket under a pid that
rem  netstat attributes to an already-dead parent.
taskkill /F /T /FI "WINDOWTITLE eq Agent Dev Crew*" >nul 2>&1

ping -n 3 127.0.0.1 >nul 2>&1

echo.
call :verify %API_PORT% "app"
call :verify %UI_PORT% "hot reload"
echo.
endlocal
exit /b 0

:kill_port
rem  %1 = port, %2 = label
set "_found="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%~1 .*LISTENING"') do (
    if not "%%p"=="0" (
        set "_found=1"
        taskkill /PID %%p /T /F >nul 2>&1
    )
)
if defined _found (
    echo   %~2 on port %~1 ... signalled
) else (
    echo   %~2 on port %~1 ... not running
)
exit /b 0

:verify
netstat -an | findstr /r /c:":%~1 .*LISTENING" >nul 2>&1
if errorlevel 1 (
    echo   %~2 port %~1 ... free
) else (
    echo   [!] %~2 port %~1 is STILL bound.
    echo       A worker is running under a pid netstat cannot attribute.
    echo       Find and kill it with:
    echo         powershell -NoProfile -Command "Get-CimInstance Win32_Process ^| Where-Object { $_.CommandLine -like '*uvicorn*' -or $_.CommandLine -like '*spawn_main*' } ^| Stop-Process -Force"
)
exit /b 0
