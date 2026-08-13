@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo === AI Christmas Tree Decorator - setup ===
echo.

where uv >nul 2>nul
if errorlevel 1 (
    echo uv is not installed. Get it from https://docs.astral.sh/uv/getting-started/installation/
    echo then run this file again.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Creating virtual environment...
    uv venv --python 3.11
)

echo Installing dependencies...
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt
if errorlevel 1 (
    echo Install failed - see the error above.
    pause
    exit /b 1
)

if not exist ".env" (
    echo.
    echo No .env found. Paste your OpenAI API key ^(from platform.openai.com/api-keys^)
    echo the account needs billing set up, gpt-image-2 has no free tier.
    set /p APIKEY="OPENAI_API_KEY="
    echo OPENAI_API_KEY=!APIKEY!> .env
    echo Saved to .env
)

if not exist "catalog\images" (
    for %%f in (catalog-images*.zip) do (
        echo Found %%f - extracting to catalog\images ...
        powershell -NoProfile -Command "Expand-Archive -Path '%%f' -DestinationPath 'catalog' -Force"
    )
)
if not exist "catalog\images" (
    echo.
    echo NOTE: catalog\images\ is missing - the catalogue picker/search will show no photos
    echo until you unzip the catalog-images bundle that came with this handover into catalog\images\.
)

echo.
echo === One-time checks (each of these costs real OpenAI usage) ===
set /p RUNCHECK="Run the engine check now? It makes one real billed generation. [y/N] "
if /i "!RUNCHECK!"=="y" (
    .venv\Scripts\python.exe scripts\check_edit_endpoint.py
)

if not exist "catalog\embeddings.npy" (
    echo.
    echo Catalogue search index is not built yet - it costs a small billed call per product photo.
    echo Build it later from the Settings page ^("sync search index"^), or now:
    set /p RUNSYNC="Build catalogue search now? [y/N] "
    if /i "!RUNSYNC!"=="y" (
        .venv\Scripts\python.exe scripts\describe_catalog.py
        .venv\Scripts\python.exe scripts\embed_catalog.py
    )
)

set SHORTCUT=%USERPROFILE%\Desktop\Tree Decorator.lnk
if not exist "%SHORTCUT%" (
    echo Adding a desktop shortcut...
    powershell -NoProfile -Command "$s = (New-Object -COM WScript.Shell).CreateShortcut('%SHORTCUT%'); $s.TargetPath = '%~f0'; $s.WorkingDirectory = '%~dp0'; $s.IconLocation = '%~dp0frontend\icon.ico'; $s.Save()"
)

echo.
echo Starting server at http://localhost:8000 ...
start "" http://localhost:8000
.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
