@echo off
REM Puts the demo online at https://pantun.aimanjamal.com (Cloudflare Tunnel), temporarily.
REM 1. Start the demo first: double-click "Start Demo.bat".
REM 2. Double-click this file. Keep this window open while sharing; close it to go offline.
REM 3. In the demo, open the "Kongsi" page, switch sharing on and give visitors the 6-digit code.
REM Visitors cannot get in without the current code, and no code works while sharing is off.
cd /d "%~dp0"
echo Putting Semak Pantun online at https://pantun.aimanjamal.com ...
echo (Keep this window open. Close it to take the site offline.)
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --config "%USERPROFILE%\.cloudflared\pantun.yml" run pantun
pause
