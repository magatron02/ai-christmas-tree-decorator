@echo off
REM Builds the Windows desktop installer end to end.
REM Output: dist_installer\TreeDecorator-Setup-<version>.exe
setlocal
cd /d "%~dp0"

set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo Inno Setup 6 not found. Install it with:  winget install JRSoftware.InnoSetup
    exit /b 1
)

echo [1/3] Staging the rembg model...
if not exist "build_assets\models" mkdir "build_assets\models"
if not exist "build_assets\models\u2net.onnx" (
    if exist "%USERPROFILE%\.u2net\u2net.onnx" (
        copy /y "%USERPROFILE%\.u2net\u2net.onnx" "build_assets\models\u2net.onnx" >nul
    ) else (
        echo   u2net.onnx not found in %USERPROFILE%\.u2net — cut-out will download it on first use.
    )
)

echo [2/3] Freezing the app with PyInstaller...
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean TreeDecorator.spec
if errorlevel 1 exit /b 1

echo [3/3] Building the installer with Inno Setup...
%ISCC% "installer\TreeDecorator.iss"
if errorlevel 1 exit /b 1

echo.
echo Done. Installer is in dist_installer\
