@echo off
set "CURRENT_DIR=%~dp0"
rem fix log encoding on Windows consoles
set PYTHONUTF8=1
echo ***** Current directory: %CURRENT_DIR% *****
%CURRENT_DIR%lib\git\bin\git.exe -C %CURRENT_DIR%MoneyPrinterTurbo pull 

%CURRENT_DIR%\lib\python\Scripts\pip.exe install -r %CURRENT_DIR%MoneyPrinterTurbo\requirements.txt

echo ##### Update completed #####
pause