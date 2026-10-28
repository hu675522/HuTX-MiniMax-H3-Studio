@echo off
chcp 65001 >nul
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-SpeechRuntime.ps1" %*
echo.
if errorlevel 1 echo 安装未完成，请查看上方报错；修复后可重新运行。
pause
