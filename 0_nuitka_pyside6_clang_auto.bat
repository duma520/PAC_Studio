@echo off
rem ============================================================
rem  PAC Studio - Nuitka build launcher (thin wrapper)
rem
rem  Build logic lives in ONE place: _scaffold\build_exe.py
rem    - version metadata is read from pacs\constants.py
rem      (PACS_APP_VERSION), so bumping the app version is enough
rem    - after a successful build, icon.ico and docs\ are copied
rem      into the dist folder automatically
rem    - data\ is NOT packaged: it is user data and is created
rem      next to the exe on first run
rem
rem  Usage: double-click to build, or run:
rem    python _scaffold\build_exe.py          (print command only)
rem    python _scaffold\build_exe.py --post   (refresh dist files only)
rem    python _scaffold\build_exe.py --run    (what this file does)
rem
rem  Pure ASCII + CRLF on purpose (cmd codepage 936).
rem ============================================================
chcp 65001 >nul
cd /d "%~dp0"
python "_scaffold\build_exe.py" --run
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto failed
echo.
echo [OK] build finished: build_output\PAC_Studio.dist\PAC_Studio.exe
echo      ship the whole PAC_Studio.dist folder
pause
exit /b 0

:failed
echo.
echo [X] build FAILED (exit %RC%) - scroll up for the error lines
pause
exit /b %RC%
