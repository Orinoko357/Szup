@echo off
REM ============================================================
REM  SZUP - wysylka plikow projektu na serwer do /root/szup-deploy
REM
REM  Zastepuje reczne kopiowanie przez FileZilla. Wysyla tylko
REM  zmienione pliki (synchronizacja WinSCP). NIE wysyla: node_modules,
REM  bazy danych, katalogu data/, logow, sekretow (.env, klucze).
REM
REM  Wymaga zainstalowanego WinSCP (uzywa WinSCP.com).
REM
REM  >>> UZUPELNIJ PONIZEJ swoje dane, potem zapisz i uruchom <<<
REM ============================================================

setlocal
cd /d "%~dp0"

REM --- DANE DO UZUPELNIENIA -----------------------------------
set "HOST=172.16.3.201"
set "USER=root"
set "PASSWORD=TU_WPISZ_HASLO"
set "REMOTE=/root/szup-deploy"
REM Sciezka do WinSCP.com (zmien, jesli masz w innym miejscu):
set "WINSCP=C:\Program Files (x86)\WinSCP\WinSCP.com"
REM ------------------------------------------------------------

if not exist "%WINSCP%" (
  echo [BLAD] Nie znaleziono WinSCP.com:
  echo        "%WINSCP%"
  echo Zainstaluj WinSCP albo popraw sciezke WINSCP w tym pliku.
  pause
  exit /b 1
)

if not exist "frontend\dist\index.html" (
  echo [UWAGA] Brak frontend\dist - frontend nie jest zbudowany.
  echo         Zbuduj najpierw lokalnie:  cd frontend ^&^& npm run build
  echo Nacisnij dowolny klawisz aby wyslac mimo to, albo Ctrl+C aby przerwac.
  pause
)

REM Skrypt WinSCP budujemy do pliku tymczasowego (prostsze cytowanie).
set "SCRIPT=%TEMP%\szup-upload-%RANDOM%.txt"
> "%SCRIPT%" echo option batch abort
>>"%SCRIPT%" echo option confirm off
>>"%SCRIPT%" echo open sftp://%USER%@%HOST%/ -hostkey=* -password="%PASSWORD%"
>>"%SCRIPT%" echo synchronize remote -filemask="^|node_modules/;.git/;__pycache__/;.venv/;venv/;data/;logs/;deploy/audit-reports/;*.db;*.db-shm;*.db-wal;*.bak;*.key;*.keytab;*.pem;.env;.env.*;*.bat;winscp-upload.log" "%CD%" "%REMOTE%"
>>"%SCRIPT%" echo exit

echo.
echo Wysylanie do %USER%@%HOST%:%REMOTE% ...
"%WINSCP%" /ini=nul /log="%~dp0winscp-upload.log" /script="%SCRIPT%"
set "RC=%ERRORLEVEL%"
del "%SCRIPT%" >nul 2>&1

echo.
if "%RC%"=="0" (
  echo === Pliki wyslane. Teraz na serwerze uruchom wdrozenie: ===
  echo    cd %REMOTE% ^&^& ./deploy/deploy.sh
  echo    ^(deploy.sh sam restartuje usluge szup^)
) else (
  echo [BLAD] WinSCP zakonczyl z kodem %RC%. Zajrzyj do winscp-upload.log
)
echo.
pause
