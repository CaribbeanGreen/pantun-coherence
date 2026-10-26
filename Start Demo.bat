@echo off
REM Double-click this file to open the Pantun Connection Checker in your browser.
REM Keep this black window open while using the demo; close it to stop.
cd /d "%~dp0"
echo Starting the Pantun Connection Checker... your browser will open shortly.
echo (Keep this window open. Close it when you are done.)
".venv\Scripts\streamlit.exe" run app.py --server.headless false --server.address localhost --browser.gatherUsageStats false
pause
