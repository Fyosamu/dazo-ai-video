@echo off
set "CURRENT_DIR=%~dp0"
rem fix log encoding on Windows consoles
set PYTHONUTF8=1
echo ***** Current directory: %CURRENT_DIR% *****

set FFMPEG_BINARY=%CURRENT_DIR%lib\ffmpeg\ffmpeg-7.0-essentials_build\ffmpeg.exe
echo ***** FFmpeg file: %FFMPEG_BINARY% *****

%CURRENT_DIR%lib\python\python.exe  %CURRENT_DIR%MoneyPrinterTurbo\main.py
