@echo off
setlocal enabledelayedexpansion
title Build AudiobookGdrive.exe
cd /d "%~dp0"

REM ============================================================
REM  build_exe.bat
REM  Dong goi AudiobookGdrive thanh 1 file .exe doc lap (Windows)
REM  bang PyInstaller (--onefile --windowed).
REM  File ket qua: dist\AudiobookGdrive.exe
REM ============================================================

call :find_python
if "%PY_EXE%"=="" (
    echo [LOI] Khong tim thay Python tren may nay.
    echo.
    echo Hay cai Python 3.9 tro len tu https://www.python.org/downloads/
    echo Luc cai dat, nho tick chon "Add python.exe to PATH" o man hinh dau tien.
    echo Neu da cai roi ma van thay loi nay: mo lai bo cai dat Python tu
    echo Control Panel/Settings ^> Apps, chon "Modify" ^> tick "Add python.exe
    echo to PATH" ^> Install, roi chay lai file nay.
    echo.
    pause
    exit /b 1
)

echo Da tim thay Python: %PY_EXE% %PY_ARGS%
"%PY_EXE%" %PY_ARGS% --version

if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Dang tao moi truong ao .venv...
    "%PY_EXE%" %PY_ARGS% -m venv .venv
    if errorlevel 1 (
        echo [LOI] Khong tao duoc .venv.
        pause
        exit /b 1
    )
)

set "VENV_PY=.venv\Scripts\python.exe"

echo [2/4] Dang cai dat PyQt5 + PyInstaller...
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install PyQt5==5.15.10 pyinstaller==6.10.0
if errorlevel 1 (
    echo [LOI] Cai dat thu vien that bai. Kiem tra lai ket noi mang.
    pause
    exit /b 1
)

echo [3/4] Dang don cac file / thu muc build cu neu co...

REM --- Tu dong tat process AudiobookGdrive.exe neu dang chay ---
tasklist /FI "IMAGENAME eq AudiobookGdrive.exe" 2>nul | find /I "AudiobookGdrive.exe" >nul
if not errorlevel 1 (
    echo   - Phat hien AudiobookGdrive.exe dang chay, dang tat...
    taskkill /F /IM AudiobookGdrive.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
)

REM Thu kill them lan nua neu con sot
taskkill /F /IM AudiobookGdrive.exe >nul 2>&1
timeout /t 1 /nobreak >nul

REM Xoa thu muc build
if exist "build" (
    rmdir /s /q "build" 2>nul
)
if exist "build" (
    echo   - Thu xoa lai thu muc build...
    timeout /t 1 /nobreak >nul
    rmdir /s /q "build" 2>nul
)

REM Xoa file exe cu trong dist neu bi khoa
if exist "dist\AudiobookGdrive.exe" (
    echo   - Dang xoa dist\AudiobookGdrive.exe cu...
    del /f /q "dist\AudiobookGdrive.exe" 2>nul
)
if exist "dist\AudiobookGdrive.exe" (
    ren "dist\AudiobookGdrive.exe" "AudiobookGdrive_old.exe" 2>nul
    del /f /q "dist\AudiobookGdrive_old.exe" 2>nul
)
if exist "dist\AudiobookGdrive.exe" (
    echo.
    echo [LOI] Khong the xoa dist\AudiobookGdrive.exe - file dang bi khoa.
    echo.
    echo Hay thu cac buoc sau roi chay lai:
    echo   1. Mo Task Manager Ctrl+Shift+Esc tat het AudiobookGdrive.exe
    echo   2. Dong cua so Explorer dang mo thu muc dist
    echo   3. Chay lenh: taskkill /f /im AudiobookGdrive.exe
    echo   4. Neu van loi, tam tat antivirus / Windows Defender roi thu lai
    echo.
    pause
    exit /b 1
)

REM Xoa toan bo thu muc dist
if exist "dist" (
    rmdir /s /q "dist" 2>nul
)
if exist "dist" (
    timeout /t 1 /nobreak >nul
    rmdir /s /q "dist" 2>nul
)

if exist "AudiobookGdrive.spec" del /q "AudiobookGdrive.spec" 2>nul

echo   - Da don sach xong.

echo [4/4] Dang build AudiobookGdrive.exe - co the mat vai phut...
"%VENV_PY%" -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "AudiobookGdrive" ^
    --icon "audiobookgdrive\resources\icon.ico" ^
    --add-data "audiobookgdrive\resources\icon.png;audiobookgdrive\resources" ^
    --add-data "audiobookgdrive\resources\icon.ico;audiobookgdrive\resources" ^
    --collect-submodules audiobookgdrive ^
    main.py

if errorlevel 1 (
    echo.
    echo [LOI] Build that bai. Xem thong bao loi o tren.
    echo Neu van gap Access is denied, hay tat AudiobookGdrive.exe trong Task Manager
    echo roi chay lai file nay.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Build thanh cong!  File exe nam o:  dist\AudiobookGdrive.exe
echo  Ban co the copy rieng file nay sang may khac de chay
echo  khong can cai Python, chi can may dich co Windows 10/11.
echo ============================================================
echo.
pause
endlocal
exit /b 0


REM ------------------------------------------------------------
REM  :find_python  (giong het run_AudiobookGdrive.bat)
REM ------------------------------------------------------------
:find_python
set "PY_EXE="
set "PY_ARGS="

where python >nul 2>nul
if not errorlevel 1 (
    set "PY_EXE=python"
    goto :eof
)

where py >nul 2>nul
if not errorlevel 1 (
    py -3 --version >nul 2>nul
    if not errorlevel 1 (
        set "PY_EXE=py"
        set "PY_ARGS=-3"
        goto :eof
    )
)

for %%D in (
    "%LocalAppData%\Programs\Python\Python313\python.exe"
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%LocalAppData%\Programs\Python\Python39\python.exe"
    "C:\Python313\python.exe"
    "C:\Python312\python.exe"
    "C:\Python311\python.exe"
    "C:\Python310\python.exe"
    "C:\Python39\python.exe"
) do (
    if exist "%%~D" (
        set "PY_EXE=%%~D"
        goto :eof
    )
)

goto :eof
