@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo [1/3] 安装打包依赖 ...
python -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

echo [2/3] 清理旧构建 ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] 打包单文件 exe（无控制台窗口）...
python -m PyInstaller --noconfirm --clean --windowed --onefile --name DesktopCleaner --hidden-import=pythoncom --hidden-import=pywintypes --hidden-import=win32gui --hidden-import=win32con --hidden-import=win32com.shell main.py
if errorlevel 1 exit /b 1

echo.
echo 完成。输出: dist\DesktopCleaner.exe
endlocal
