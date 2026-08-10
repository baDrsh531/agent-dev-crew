@echo off
setlocal EnableExtensions
title Agent Dev Crew - launcher

rem ---------------------------------------------------------------------------
rem  Agent Dev Crew launcher.
rem
rem  One app, one process, one URL. The interface is built once and served by
rem  the API itself, so there is a single window to start, a single one to
rem  stop, and nothing that can quietly die while the other half looks fine.
rem
rem  `dev` is the exception and says so: it runs Vite alongside for hot reload,
rem  which genuinely needs its own port. That is a development convenience, not
rem  how the app runs.
rem
rem  Usage:
rem     start.bat              build the UI, then serve everything on one port
rem     start.bat api          API only, skip the UI build
rem     start.bat dev          add Vite hot reload on its own port
rem     start.bat setup        install/refresh dependencies, launch nothing
rem ---------------------------------------------------------------------------

set "ROOT=%~dp0"
set "VENV_PY=%ROOT%.venv\Scripts\python.exe"
set "API_PORT=8000"
set "UI_PORT=5173"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=all"

rem  --reload is off by default on purpose. It runs uvicorn as a supervisor plus
rem  a worker child; if the console is closed the child can outlive it, keep the
rem  port bound, and make the next launch fail. One process is one thing to stop.
set "RELOAD="
set "DEVUI="
if /i "%MODE%"=="dev" (
    set "RELOAD=--reload"
    set "DEVUI=1"
    set "MODE=all"
)

echo.
echo  ==========================================
echo    Agent Dev Crew
echo  ==========================================
echo.

rem -- python ----------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo  [X] Python was not found on PATH.
    echo      Install Python 3.11+ and tick "Add python.exe to PATH".
    goto :fail
)

rem -- virtual environment ---------------------------------------------------
if not exist "%VENV_PY%" (
    echo  [1/5] Creating the virtual environment ...
    python -m venv "%ROOT%.venv"
    if errorlevel 1 (
        echo  [X] Could not create the virtual environment.
        goto :fail
    )
    set "FRESH_VENV=1"
) else (
    echo  [1/5] Virtual environment      ... ok
)

rem -- backend dependencies --------------------------------------------------
rem  Probing an import is cheaper and more honest than a marker file: it stays
rem  correct if someone deletes a package by hand.
"%VENV_PY%" -c "import fastapi, anthropic, sse_starlette" >nul 2>&1
if errorlevel 1 (
    echo  [2/5] Installing backend dependencies ... this takes a minute
    "%VENV_PY%" -m pip install --upgrade pip --quiet
    "%VENV_PY%" -m pip install -r "%ROOT%requirements.txt" --quiet
    if errorlevel 1 (
        echo  [X] pip install failed. Run it manually to see why:
        echo      "%VENV_PY%" -m pip install -r "%ROOT%requirements.txt"
        goto :fail
    )
) else (
    echo  [2/5] Backend dependencies     ... ok
)

rem -- configuration ---------------------------------------------------------
if not exist "%ROOT%.env" (
    copy /y "%ROOT%.env.example" "%ROOT%.env" >nul
    echo  [3/5] Created .env from .env.example
    echo        No API key yet - the fake provider will run ^(offline, free^).
    echo        Add ANTHROPIC_API_KEY to .env for real runs.
) else (
    echo  [3/5] Configuration            ... ok
)

rem -- frontend dependencies -------------------------------------------------
set "HAVE_NODE=1"
if /i "%MODE%"=="api" goto :skip_node

where npm >nul 2>&1
if errorlevel 1 (
    set "HAVE_NODE="
    echo  [4/5] npm not found - the UI will be skipped ^(API still works^).
    goto :skip_node
)

if not exist "%ROOT%frontend\node_modules" (
    echo  [4/5] Installing frontend dependencies ... this takes a minute
    pushd "%ROOT%frontend"
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        popd
        echo  [X] npm install failed.
        goto :fail
    )
    popd
) else (
    echo  [4/5] Frontend dependencies    ... ok
)

rem -- build the interface ---------------------------------------------------
rem  Built here rather than served by a second dev server: the API serves
rem  frontend\dist itself, so this is what makes one port enough.
if /i "%MODE%"=="api" goto :skip_build
if not defined HAVE_NODE goto :skip_build

echo  [5/5] Building the interface   ... a few seconds
pushd "%ROOT%frontend"
call npm run build >nul 2>&1
if errorlevel 1 (
    popd
    echo  [X] The UI build failed. Run it manually to see why:
    echo      cd "%ROOT%frontend" ^&^& npm run build
    goto :fail
)
popd

:skip_build

if /i "%MODE%"=="setup" (
    echo.
    echo  Setup complete. Run start.bat again to launch.
    goto :done
)

rem -- launch ----------------------------------------------------------------
rem  cmd /s keeps the inner quotes intact, which matters because this project
rem  path may contain spaces.
echo.
echo  Starting Agent Dev Crew -^> http://127.0.0.1:%API_PORT%
start "Agent Dev Crew" cmd /s /k "pushd "%ROOT%backend" && "%VENV_PY%" -m uvicorn app.main:app --port %API_PORT% %RELOAD%"

if defined DEVUI if defined HAVE_NODE (
    echo  Hot reload (dev only) -^> http://localhost:%UI_PORT%
    start "Agent Dev Crew - hot reload" cmd /s /k "pushd "%ROOT%frontend" && npm run dev"
)

rem  A fixed sleep is a guess; uvicorn --reload can take well over ten seconds
rem  on a cold start, and opening the page before it is up shows an error.
echo.
echo  Waiting for the server to come up ...
call :waitport %API_PORT% 45
if errorlevel 1 (
    echo  [!] Nothing is listening on %API_PORT% yet.
    echo      Check the "Agent Dev Crew" window for the reason.
) else (
    echo      Ready.
)

rem  Chained ifs cannot carry an else — it would bind to the inner one. Pick
rem  the URL first, then open it once.
set "OPEN_URL=http://127.0.0.1:%API_PORT%"
if defined DEVUI if defined HAVE_NODE set "OPEN_URL=http://localhost:%UI_PORT%"
if /i "%MODE%"=="api" if not defined HAVE_NODE set "OPEN_URL=http://127.0.0.1:%API_PORT%/docs"
start "" "%OPEN_URL%"

echo.
echo  Running. Close the server window to stop it.
echo.
goto :done

:fail
echo.
echo  Startup aborted.
echo.
pause
exit /b 1

:done
call :sleep 3
endlocal
exit /b 0

rem  `timeout` refuses to run when stdin is redirected, which happens whenever
rem  this script is called from another process. ping always works.
:sleep
set /a "_ticks=%~1 + 1"
ping -n %_ticks% 127.0.0.1 >nul 2>&1
exit /b 0

rem  Poll until a port accepts connections. %1 = port, %2 = seconds to wait.
rem  Returns 1 on timeout so the caller can report it instead of pretending.
:waitport
set /a "_left=%~2"
:waitport_loop
netstat -an | findstr /r /c:":%~1 .*LISTENING" >nul 2>&1
if not errorlevel 1 exit /b 0
set /a "_left-=1"
if %_left% leq 0 exit /b 1
call :sleep 1
goto :waitport_loop
