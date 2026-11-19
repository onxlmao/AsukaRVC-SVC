@echo off
title AsukaRVC-SVC - RVC Singing Studio
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
if errorlevel 1 pause
