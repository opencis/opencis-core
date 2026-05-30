@echo off
:: =============================================================================
:: run_smbus_test.bat — SMBus-MCTP Integration Test (Windows)
::
:: Two modes:
::   MODE 1 (WSL) : Runs the full stack through WSL — FM + Switch + adapter
::                  + slave + master. Requires WSL2 with Ubuntu installed.
::
::   MODE 2 (Native) : Builds C code with MinGW gcc and runs ONLY the C unit
::                     tests (mctp_packet.h wire format). No FM/switch needed.
::                     Full relay test requires WSL (Unix sockets).
::
:: Prerequisites:
::   WSL mode   : WSL2 + Ubuntu + Python venv with opencis-core installed
::   Native mode: MinGW-w64 gcc in PATH (https://winlibs.com)
::                or Cygwin gcc, or MSYS2 gcc
::
:: Usage:
::   run_smbus_test.bat           -- auto-detect (WSL first, then native)
::   run_smbus_test.bat wsl       -- force WSL mode
::   run_smbus_test.bat native    -- force native (unit tests only)
:: =============================================================================

setlocal enabledelayedexpansion
title SMBus-MCTP Integration Test

:: ── Colours via ANSI (Windows 10+) ──────────────────────────────────────────
for /f %%a in ('echo prompt $E^| cmd') do set "ESC=%%a"
set "BOLD=%ESC%[1m"
set "CYAN=%ESC%[96m"
set "GREEN=%ESC%[92m"
set "YELLOW=%ESC%[93m"
set "RED=%ESC%[91m"
set "RESET=%ESC%[0m"

echo %BOLD%%CYAN%
echo ╔══════════════════════════════════════════════════════════════╗
echo ║   SMBus-MCTP Integration Test  (Windows Batch)             ║
echo ╚══════════════════════════════════════════════════════════════╝
echo %RESET%

:: ── Locate script directory ──────────────────────────────────────────────────
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

:: ── Mode selection ───────────────────────────────────────────────────────────
set "MODE=%~1"
if /i "%MODE%"=="" (
    call :detect_mode
) else if /i "%MODE%"=="wsl" (
    set "MODE=wsl"
) else if /i "%MODE%"=="native" (
    set "MODE=native"
) else (
    echo %RED%Unknown mode '%MODE%'. Use: wsl ^| native%RESET%
    exit /b 1
)

if /i "%MODE%"=="wsl" goto :run_wsl
if /i "%MODE%"=="native" goto :run_native

:: ── Detect best available mode ───────────────────────────────────────────────
:detect_mode
    wsl echo ok >nul 2>&1
    if %errorlevel% equ 0 (
        echo %CYAN%[detect] WSL available — using full-stack WSL mode%RESET%
        set "MODE=wsl"
    ) else (
        echo %YELLOW%[detect] WSL not found — using native MinGW unit-test mode%RESET%
        set "MODE=native"
    )
goto :EOF

:: =============================================================================
:: MODE 1: Full test via WSL
:: =============================================================================
:run_wsl
echo %BOLD%Mode: WSL (full stack test)%RESET%
echo.

:: Convert Windows path to WSL path
for /f "usebackq delims=" %%p in (`wsl wslpath -u "%SCRIPT_DIR%"`) do set "WSL_DIR=%%p"
echo %CYAN%WSL script dir: %WSL_DIR%%RESET%
echo.

echo %BOLD%── Running full integration test via WSL ───────────────────%RESET%
echo %YELLOW%This will start: FM + Switch + Adapter + Master + Slave%RESET%
echo.

wsl bash -c "cd '%WSL_DIR%' && bash run_smbus_test.sh"
set "WSL_RC=%errorlevel%"

echo.
if %WSL_RC% equ 0 (
    echo %BOLD%%GREEN%
    echo ╔══════════════════════════════════════════════╗
    echo ║  ✓  PASS — All integration tests passed     ║
    echo ╚══════════════════════════════════════════════╝
    echo %RESET%
) else (
    echo %BOLD%%RED%
    echo ╔══════════════════════════════════════════════╗
    echo ║  ✗  FAIL — Exit code: %WSL_RC%                    ║
    echo ╚══════════════════════════════════════════════╝
    echo %RESET%
)
exit /b %WSL_RC%

:: =============================================================================
:: MODE 2: Native Windows build + C unit tests (MinGW)
:: =============================================================================
:run_native
echo %BOLD%Mode: Native MinGW (C unit tests only)%RESET%
echo %YELLOW%Note: Full relay test needs WSL (Unix domain sockets are Linux-only)%RESET%
echo.

:: ── Check for gcc ─────────────────────────────────────────────────────────
where gcc >nul 2>&1
if %errorlevel% neq 0 (
    echo %RED%[ERROR] gcc not found in PATH.%RESET%
    echo.
    echo Install one of:
    echo   MinGW-w64  : https://winlibs.com  (add to PATH)
    echo   MSYS2      : https://www.msys2.org (pacman -S mingw-w64-ucrt-x86_64-gcc)
    echo   Cygwin     : https://www.cygwin.com
    echo.
    echo Or use WSL mode:
    echo   run_smbus_test.bat wsl
    exit /b 1
)

for /f "tokens=*" %%g in ('gcc --version 2^>^&1 ^| findstr /r "gcc"') do (
    echo %GREEN%[gcc] %%g%RESET%
)
echo.

:: ── Step 1: Build unit test executable ─────────────────────────────────────
echo %BOLD%── Step 1: Build test_mctp_packet (unit tests) ────────────%RESET%
cd /d "%SCRIPT_DIR%"

set "CFLAGS=-O2 -Wall -Wextra -std=c11 -I."
set "OUT_UNIT=test_mctp_packet.exe"

echo   Compiling test_mctp_packet.c ...
gcc %CFLAGS% -o %OUT_UNIT% test_mctp_packet.c
if %errorlevel% neq 0 (
    echo %RED%[ERROR] Compilation failed.%RESET%
    exit /b 1
)
echo %GREEN%  Build OK → %OUT_UNIT%%RESET%
echo.

:: ── Step 2: Run unit tests ──────────────────────────────────────────────────
echo %BOLD%── Step 2: Run C unit tests (mctp_packet.h wire format) ───%RESET%
echo.
%OUT_UNIT%
set "UNIT_RC=%errorlevel%"
echo.

:: ── Step 3: Build adapter, slave, master (compile only, cannot run) ─────────
echo %BOLD%── Step 3: Compile adapter + slave + master (Windows build) %RESET%
echo %YELLOW%  Note: Unix socket runtime requires WSL/Linux%RESET%
echo.

set "WINSOCK=-lws2_32"

echo   Compiling smbus_mctp_adapter.c ...
gcc %CFLAGS% -o smbus_mctp_adapter.exe smbus_mctp_adapter.c %WINSOCK% 2>nul
if %errorlevel% equ 0 (
    echo %GREEN%    smbus_mctp_adapter.exe  OK%RESET%
) else (
    echo %YELLOW%    smbus_mctp_adapter.exe  SKIP (Unix socket headers unavailable)%RESET%
)

echo   Compiling smbus_slave.c ...
gcc %CFLAGS% -o smbus_slave.exe smbus_slave.c %WINSOCK% 2>nul
if %errorlevel% equ 0 (
    echo %GREEN%    smbus_slave.exe          OK%RESET%
) else (
    echo %YELLOW%    smbus_slave.exe          SKIP%RESET%
)

echo   Compiling smbus_master.c ...
gcc %CFLAGS% -o smbus_master.exe smbus_master.c %WINSOCK% 2>nul
if %errorlevel% equ 0 (
    echo %GREEN%    smbus_master.exe         OK%RESET%
) else (
    echo %YELLOW%    smbus_master.exe         SKIP%RESET%
)

echo.

:: ── Step 4: Instructions for full test ─────────────────────────────────────
echo %BOLD%── Step 4: Full relay test instructions ───────────────────%RESET%
echo.
echo %YELLOW%To run the full integration test (adapter + FM + slave + master):%RESET%
echo.
echo   Option A — Run in WSL directly:
echo     wsl bash -c "cd smbus_c ^&^& bash run_smbus_test.sh"
echo.
echo   Option B — Use WSL mode of this batch file:
echo     run_smbus_test.bat wsl
echo.
echo   Option C — Run each component manually in WSL terminals:
echo     WSL T1^:  python run_pbr_env.py --smbus-bridge /tmp/smbus_bridge.sock
echo     WSL T2^:  ./smbus_mctp_adapter /tmp/smbus_slave.sock /tmp/smbus_master.sock
echo     WSL T3^:  ./smbus_master /tmp/smbus_master.sock
echo     WSL T4^:  ./smbus_slave  /tmp/smbus_slave.sock
echo.

:: ── Result ───────────────────────────────────────────────────────────────────
if %UNIT_RC% equ 0 (
    echo %BOLD%%GREEN%
    echo ╔══════════════════════════════════════════════════════╗
    echo ║  ✓  C Unit Tests PASSED                            ║
    echo ║  Use WSL mode for full relay integration test      ║
    echo ╚══════════════════════════════════════════════════════╝
    echo %RESET%
) else (
    echo %BOLD%%RED%
    echo ╔══════════════════════════════════════════════════════╗
    echo ║  ✗  C Unit Tests FAILED (exit code %UNIT_RC%)          ║
    echo ╚══════════════════════════════════════════════════════╝
    echo %RESET%
)
exit /b %UNIT_RC%
