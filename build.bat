@echo off
REM ============================================================
REM  FilmVault — PyInstaller build script
REM  Produces dist/FilmVault/FilmVault.exe (portable, onedir)
REM ============================================================

cd /d "%~dp0"

echo [1/3] Cleaning old builds...
if exist dist rmdir /S /Q dist
if exist build rmdir /S /Q build

echo [2/3] Building with PyInstaller...
call .venv\Scripts\python.exe -m PyInstaller ^
    --onedir ^
    --windowed ^
    --name FilmVault ^
    --hidden-import aiosqlite ^
    --add-data "data/site_configs.json;data/" ^
    --add-data "data/posters;data/posters/" ^
    --add-data "data/thumbs;data/thumbs/" ^
    --add-data "assets/icon.png;assets/" ^
    --add-data "assets/icon.ico;assets/" ^
    --add-data "assets/icon_titlebar.png;assets/" ^
    --clean ^
    run_flet.py

if %ERRORLEVEL% neq 0 (
    echo BUILD FAILED!
    pause
    exit /b 1
)

echo [3/3] Build complete!
echo Output: %cd%\dist\FilmVault\
pause
