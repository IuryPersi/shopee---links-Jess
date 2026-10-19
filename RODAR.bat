@echo off
cd /d "%~dp0"
py -3.12 -m robo rodar
if "%1"=="" (
  if exist "saida\ultima\vitrine.html" start "" "saida\ultima\vitrine.html"
  pause
)
