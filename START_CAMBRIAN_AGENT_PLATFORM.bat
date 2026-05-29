@echo off
setlocal
set "ROOT=%~dp0"
set "PLATFORM=%ROOT%web\platform\index.html"

if not exist "%PLATFORM%" (
  echo web\platform\index.html was not found.
  echo Run this file from the extracted Cambrian folder.
  exit /b 1
)

start "" "%PLATFORM%"
echo Cambrian Agent Platform Builder opened.
exit /b 0
