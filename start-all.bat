@echo off
rem ============================================================
rem  MoneyPrinterTurbo + Telegram Bot  —  اجیرای کامل با یک کلیک
rem 1) سرور ویدیو (پورت 8080)  2) ربات تلگرام
rem ============================================================
cd /d "%~dp0"
set PYTHONUTF8=1

echo [1/2] Starting API server...
start "MPT Server" cmd /k "cd /d "%~dp0MoneyPrinterTurbo" && set PYTHONUTF8=1 && set FFMPEG_BINARY=%~dp0lib\ffmpeg\ffmpeg-7.0-essentials_build\ffmpeg.exe && ..\lib\python\python.exe main.py"

echo [2/2] Waiting for server, then starting bot...
timeout /t 25 /nobreak >nul
cd /d "%~dp0bot"
..\lib\python\python.exe -u bot.py
pause
