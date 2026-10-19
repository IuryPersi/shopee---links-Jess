@echo off
cd /d "%~dp0"
start "" "http://127.0.0.1:8031"
py -3.12 -m robo.painel
pause
