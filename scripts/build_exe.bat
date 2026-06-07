@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0.."

echo [1/4] Installing build dependencies...
python -m pip install -r requirements-build.txt
if errorlevel 1 exit /b 1

echo [2/4] Restoring desktop icons and stopping running app...
python scripts\prepare_build.py
if errorlevel 1 exit /b 1

echo [3/4] Cleaning old build output...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [4/4] Building one-file windowed executable...
python -m PyInstaller --noconfirm --clean --windowed --onefile --name DesktopCleaner --icon assets\icons\app.ico --add-data "assets\icons;assets\icons" --hidden-import=pythoncom --hidden-import=pywintypes --hidden-import=win32gui --hidden-import=win32con --hidden-import=win32com.shell main.py
if errorlevel 1 exit /b 1

echo.
echo Done. Output: dist\DesktopCleaner.exe
endlocal
