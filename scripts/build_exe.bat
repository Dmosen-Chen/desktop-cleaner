@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo [1/3] 安装打包依赖 PyInstaller ...
python -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

echo [2/3] 清理旧构建 ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] 打包单文件 exe（无控制台窗口，含托盘依赖）...
python -m PyInstaller --noconfirm --clean --windowed --onefile --name DesktopTidy --add-data "config.default.json;." --hidden-import=pystray --hidden-import=PIL --hidden-import=windnd --collect-all=pystray --collect-all=PIL main.py
if errorlevel 1 exit /b 1

echo.
echo 完成。输出: dist\DesktopTidy.exe
endlocal
