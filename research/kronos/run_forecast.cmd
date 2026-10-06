@echo off
cd /d C:\Users\007pe\src\orderflow_edge_lab
set PYTHONPATH=src
.venv-kronos\Scripts\python.exe -u scripts\kronos_forecast_2026_10_01.py >> research\kronos\run.log 2>&1
echo exit=%ERRORLEVEL% >> research\kronos\run.log
