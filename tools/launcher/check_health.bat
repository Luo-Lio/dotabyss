@echo off
rem ============================================================
rem  dotabyss offline health check (pure ASCII on purpose:
rem  the game folder name is Shift-JIS, a UTF-8 bat would garble)
rem  Usage: double-click me, or: check_health.bat <game-folder>
rem  NOTE: launch the game ONLY via DotabyssOfflineLauncher.exe.
rem        Never use DMM GAME PLAYER (that starts the online game).
rem ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
rem -- absolute paths for external tools: bare 'find' can resolve to
rem -- GNU find (Git/MSYS) whose syntax differs and would scan C:\ !
set "FIND=%SystemRoot%\System32\find.exe"
set "FINDSTR=%SystemRoot%\System32\findstr.exe"
set "NETSTAT=%SystemRoot%\System32\netstat.exe"

set "GAMEDIR=%~dp0"
if not "%~1"=="" set "GAMEDIR=%~1"
if "%GAMEDIR:~-1%"=="\" set "GAMEDIR=%GAMEDIR:~0,-1%"
echo ============================================================
echo  dotabyss offline health check
echo  game dir: %GAMEDIR%
echo ============================================================
set FAIL=0

echo [1/14] game exe
set "EXECOUNT=0"
for /f %%C in ('dir /b "%GAMEDIR%\*.exe" 2^>nul ^| "%FINDSTR%" /v /i /c:"DotabyssOfflineLauncher" ^| "%FIND%" /c /v ""') do set EXECOUNT=%%C
if !EXECOUNT! GEQ 1 (echo   OK: game exe present) else (echo   FAIL: no game exe found - wrong folder? & set FAIL=1)

echo [2/14] winhttp.dll
if exist "%GAMEDIR%\winhttp.dll" (echo   OK: winhttp.dll present) else (echo   FAIL: winhttp.dll missing - BepInEx will not inject & set FAIL=1)

echo [3/14] BepInEx
if exist "%GAMEDIR%\BepInEx\core" (echo   OK: BepInEx installed) else (echo   FAIL: BepInEx\core missing - extract the pack again & set FAIL=1)

echo [4/14] plugin dll
if exist "%GAMEDIR%\BepInEx\plugins\StoryViewer\StoryViewer.dll" (echo   OK: StoryViewer.dll present) else (echo   FAIL: StoryViewer.dll missing & set FAIL=1)

echo [5/14] story index
set "STORIES=%GAMEDIR%\BepInEx\plugins\StoryViewer\stories.json"
set "SIZE=0"
if exist "%STORIES%" (
  for %%A in ("%STORIES%") do set SIZE=%%~zA
  echo   INFO: stories.json size !SIZE!
  if !SIZE! LSS 102400 (echo   FAIL: stories.json looks like a stub - re-copy the plugin folder & set FAIL=1) else (echo   OK: stories.json)
) else (
  echo   FAIL: stories.json missing & set FAIL=1
)

echo [6/14] previews
set "PREV=%GAMEDIR%\BepInEx\plugins\StoryViewer\previews"
set "PC=0"
if exist "%PREV%" (
  for /f %%C in ('dir /b "%PREV%\*.jpg" "%PREV%\*.png" 2^>nul ^| "%FIND%" /c /v ""') do set PC=%%C
  echo   INFO: !PC! preview images
  if !PC! LSS 100 (
    echo   FAIL: previews look incomplete - re-copy the plugin folder
    set FAIL=1
  ) else (
    echo   OK: previews present
  )
) else (
  echo   FAIL: previews dir missing & set FAIL=1
)

echo [7/14] offline config keys
set "CFG=%GAMEDIR%\BepInEx\config\dotabyss.storyviewer.cfg"
if exist "%CFG%" (
  call :ckkey OfflineAuth true
  call :ckkey OfflineApi true
  call :ckkey RedirectAssetServer true
  call :ckkey ServeCachedBundles true
  call :ckkey SkipRequestEncryption true
  call :ckkey ForceDmmSdkSuccess true
  call :ckkey CaptureForward false
) else (
  echo   FAIL: dotabyss.storyviewer.cfg missing - run launcher Repair & set FAIL=1
)

echo [8/14] bundle cache
set "DATADIR="
for /d %%D in ("%GAMEDIR%\*_Data") do set "DATADIR=%%~fD"
if defined DATADIR (
  set "CC=0"
  for /f %%C in ('dir /b /ad "!DATADIR!\Caches" 2^>nul ^| "%FIND%" /c /v ""') do set CC=%%C
  echo   INFO: !DATADIR!
  echo   INFO: Caches entries: !CC!
  if !CC! LSS 10000 (
    echo   FAIL: cache looks incomplete - re-extract the full pack, the game WILL blackscreen with missing resources
    set FAIL=1
  ) else (
    echo   OK: cache looks complete
  )
) else (
  echo   FAIL: no *_Data folder next to the game exe & set FAIL=1
)

echo [9/14] port 18923
"%NETSTAT%" -ano | "%FINDSTR%" /c:":18923" >nul
if errorlevel 1 (echo   OK: port free) else (echo   INFO: port in use - if the game is NOT running now, inspect with: netstat -ano ^| findstr 18923)

echo [10/14] last run log
set "LOG=%GAMEDIR%\BepInEx\LogOutput.log"
if exist "%LOG%" (
  echo   OK: LogOutput.log exists
  "%FINDSTR%" /c:"StoryViewer" "%LOG%" >nul
  if errorlevel 1 (echo   WARN: no StoryViewer line in log - plugin may not be loading) else (echo   OK: plugin was active in last run)
  set MISS=0
  rem -- NOTE: the command inside for /f must NOT start with a quoted
  rem -- path (cmd strips the outer quotes -> 'syntax is incorrect');
  rem -- System32 has no spaces, so keep these two unquoted.
  for /f %%C in ('%SystemRoot%\System32\findstr.exe /c:"404" "%LOG%" ^| %SystemRoot%\System32\find.exe /c /v ""') do set MISS=%%C
  echo   INFO: 404 lines in log: !MISS!   ^(0 = every requested resource was served from cache^)
  echo   HINT: 404 ^> 0 = cache incomplete or story asks for a resource the pack does not contain
) else (
  echo   WARN: no LogOutput.log - game never ran with BepInEx here, or files were blocked by Windows
)

echo [11/14] launcher config
set "LJ=%GAMEDIR%\launcher.json"
if exist "%LJ%" (
  "%FINDSTR%" /c:"github_repo" "%LJ%" >nul
  if errorlevel 1 (echo   WARN: launcher.json has no github_repo - the Update button stays disabled) else (echo   OK: launcher.json present)
) else (
  echo   WARN: launcher.json missing - the Update button stays disabled
)

echo [12/14] offline identity
if defined DATADIR (
  if exist "!DATADIR!\app.info" (
    "%FINDSTR%" /c:"_offline" "!DATADIR!\app.info" >nul
    if errorlevel 1 (
      echo   FAIL: app.info product name has no _offline suffix - run launcher Repair
      set FAIL=1
    ) else (
      echo   OK: identity isolated ^(product name *_offline^)
    )
  ) else (
    echo   FAIL: app.info missing in !DATADIR! - incomplete pack & set FAIL=1
  )
) else (
  echo   FAIL: no *_Data folder - cannot check identity & set FAIL=1
)

echo [13/14] catalog seed
set "SEED=%GAMEDIR%\BepInEx\plugins\StoryViewer\catalog_seed"
if exist "%SEED%\catalog_1.bin" (
  set "BSIZE=0"
  for %%A in ("%SEED%\catalog_1.bin") do set BSIZE=%%~zA
  echo   INFO: catalog_1.bin size !BSIZE!
  if !BSIZE! LSS 1024 (
    echo   FAIL: catalog_1.bin looks like a stub - re-extract the full pack
    set FAIL=1
  ) else (
    echo   OK: catalog seed present
  )
  if exist "%SEED%\catalog_1.bin.hash" (echo   OK: catalog hash present) else (echo   WARN: catalog_1.bin.hash missing - plugin cannot verify the catalog)
) else (
  echo   FAIL: catalog seed missing - re-extract the full pack ^(needed on fresh PCs^) & set FAIL=1
)

echo [14/14] launcher exe + saves
if exist "%GAMEDIR%\DotabyssOfflineLauncher.exe" (echo   OK: DotabyssOfflineLauncher.exe present) else (echo   WARN: launcher exe missing - start the game exe directly)
set "SAVE="
for /d %%D in ("%USERPROFILE%\AppData\LocalLow\EXNOA*") do set "SAVE=%%~fD"
if defined SAVE (
  echo   INFO: save root: !SAVE!
  if exist "!SAVE!\*_offline" (echo   OK: offline identity folder exists) else (echo   INFO: offline identity folder not created yet - first launch will create it)
) else (
  echo   INFO: no EXNOA save root yet - created on first launch
)

echo ============================================================
if "!FAIL!"=="1" (echo  RESULT: FAILURES FOUND - fix every FAIL line above) else (echo  RESULT: no structural failure - check WARN/INFO lines above)
echo ============================================================
if not "%~2"=="nopause" pause
exit /b 0

:ckkey
rem -- check one "Key = value" in the offline cfg (case-insensitive)
"%FINDSTR%" /i /r /c:"%~1 *= *%~2" "%CFG%" >nul
if errorlevel 1 (echo   FAIL: %~1 should be %~2 - run launcher Repair & set FAIL=1) else (echo   OK: %~1 = %~2)
exit /b 0
