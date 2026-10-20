@echo off
rem Abre a tela "Achadinhos de hoje". O navegador abre sozinho quando o painel ja estiver no ar.
rem Deixe esta janela aberta enquanto usa: fechar a janela desliga o painel.
rem Se o painel ja estiver aberto, um segundo clique so abre o navegador nele (e esta janela fecha).
cd /d "%~dp0"
title Achadinhos - painel (deixe esta janela aberta)
py -3.12 -m robo.painel --abrir
if errorlevel 1 pause
