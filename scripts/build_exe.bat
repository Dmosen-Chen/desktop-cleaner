@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo [1/3] Installing build dependencies...
python -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

echo [2/3] Cleaning old build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [3/3] Building one-file windowed executable...
python -m PyInstaller --noconfirm --clean --windowed --onefile --name DesktopCleaner --hidden-import=pythoncom --hidden-import=pywintypes --hidden-import=win32gui --hidden-import=win32con --hidden-import=win32com.shell main.py
if errorlevel 1 exit /b 1

echo.
echo Done. Output: dist\DesktopCleaner.exe
endlocal
