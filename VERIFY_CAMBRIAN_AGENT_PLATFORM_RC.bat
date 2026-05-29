@echo off
setlocal
set "ROOT=%~dp0"
set "VENV_PYTHON=%ROOT%.venv\Scripts\python.exe"
set "PYTHON_EXE="

call :bootstrap_venv
if errorlevel 1 exit /b 1

"%VENV_PYTHON%" "%ROOT%scripts\verify_platform_alpha.py"
exit /b %ERRORLEVEL%

:bootstrap_venv
if exist "%VENV_PYTHON%" goto ensure_deps

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do (
  if not defined PYTHON_EXE if exist "%%~fD\python.exe" call :try_python "%%~fD\python.exe"
)

for /f "delims=" %%P in ('where python 2^>nul') do (
  if not defined PYTHON_EXE call :try_python "%%P"
)

if defined PYTHON_EXE (
  echo Creating Cambrian local virtual environment...
  "%PYTHON_EXE%" -m venv "%ROOT%.venv"
  if errorlevel 1 exit /b 1
  goto ensure_deps
)

where py >nul 2>nul
if not errorlevel 1 (
  py -3 --version >nul 2>nul
  if not errorlevel 1 (
    py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
    if not errorlevel 1 (
      echo Creating Cambrian local virtual environment...
      py -3 -m venv "%ROOT%.venv"
      if errorlevel 1 exit /b 1
      goto ensure_deps
    )
  )
)

echo Python 3.11 or newer was not found.
exit /b 1

:ensure_deps
"%VENV_PYTHON%" -c "import jsonschema, yaml" >nul 2>nul
if not errorlevel 1 exit /b 0
echo Installing Cambrian verification dependencies...
"%VENV_PYTHON%" -m pip install -e "%ROOT%."
if errorlevel 1 exit /b 1
exit /b 0

:try_python
"%~1" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 exit /b 0
set "PYTHON_EXE=%~1"
exit /b 0
