# Backup i ciągłość działania — SZUP

## Dane aplikacji

SZUP przechowuje dane w jednym pliku SQLite: `$SZUP_DATA_DIR/szup.db`
(domyślnie `/opt/szup/data/szup.db`; `SZUP_DATA_DIR` ustawia `szup.service`
albo `/opt/szup/.env`).

Zawartość bazy:
- Użytkownicy i ich role
- Jednostki i komórki, kierownicy i zastępcy
- Systemy IT i słownik uprawnień
- Wnioski o uprawnienia (historia, kroki obiegu, oświadczenia)
- Nocne migawki uprawnień
- Audit log (retencja co najmniej 24 miesiące: superadmin może usunąć tylko
  wpisy starsze niż 24 miesiące; ślady czyszczeń i resetów są nieusuwalne)
- Zdarzenia bezpieczeństwa
- Konfiguracja (SMTP, LDAP, szablony powiadomień) — hasła zaszyfrowane kluczem Fernet

### Klucze — kopiujemy je razem z bazą

Sama baza nie wystarczy do pełnego odtworzenia. W katalogu danych
(`$SZUP_DATA_DIR`) albo w `/opt/szup/.env` leżą klucze, bez których część
danych z kopii jest bezużyteczna:

| Klucz | Skąd go bierze aplikacja | Do czego służy | Skutek utraty |
|---|---|---|---|
| sekret obiegu | `SZUP_WORKFLOW_SECRET` z `.env`, a gdy brak — plik `data/workflow_secret.key` | podpisy łańcuchowe kroków obiegu wniosków (weryfikacja integralności historii akceptacji) | **cała dotychczasowa historia obiegu przestaje się weryfikować** — łańcuchy podpisów wyglądają na naruszone, tracimy dowód nienaruszalności akceptacji |
| klucz Fernet | `SZUP_SECRET_KEY` z `.env`, a gdy brak — plik `data/secret.key` | szyfrowanie haseł zapisanych w bazie (SMTP, konto usługowe LDAP) | zapisanych haseł nie da się odszyfrować — trzeba je ponownie wpisać w Ustawieniach |
| klucz JWT | plik `data/jwt_secret.key` | podpis sesji (tokenów logowania) | wszyscy zostają wylogowani; danych nie tracimy — przy starcie generuje się nowy |

Dlatego każda kopia bazy ma odpowiadającą jej kopię kluczy
(`szup-keys-RRRR-MM-DD-GGMMSS.tar.gz`: pliki `*.key` z katalogu danych
i `/opt/szup/.env`). Archiwum kluczy to **sekret**: uprawnienia `600`,
a poza serwer kopiujemy je w inne, zaszyfrowane miejsce niż kopie bazy
(sejf, zaszyfrowane archiwum, menedżer haseł) — kto ma bazę i klucz Fernet,
odczyta hasła SMTP i LDAP.

### Tryb WAL

Gdy SQLite pracuje w trybie WAL, część ostatnich zmian może być jeszcze
w plikach `szup.db-wal` i `szup.db-shm`. Dlatego **nie kopiujemy samego pliku
`szup.db` działającej bazy** (`cp`), tylko używamy `sqlite3 .backup`, które
tworzy spójną kopię „na gorąco” razem z zawartością dziennika.

## Kopie zapasowe

Wszystkie kopie trafiają do `/opt/szup/backups/` (katalog `700`, pliki `600`).
Nazwy zawierają datę i godzinę, więc sortują się chronologicznie. Dwa rodzaje
kopii mają **różne prefiksy**, żeby retencja jednego nie kasowała drugiego:

| Prefiks | Kto tworzy | Retencja |
|---|---|---|
| `szup-RRRR-MM-DD-GGMMSS.db` + `szup-keys-RRRR-MM-DD-GGMMSS.tar.gz` | codzienna kopia (cron) | 30 dni wg daty modyfikacji pliku (`find -mtime +30`) |
| `szup-predeploy-RRRR-MM-DD-GGMMSS.db` | `deploy/deploy.sh` przed wdrożeniem | 10 najnowszych wg nazwy |

### Kopia przed każdym wdrożeniem

`deploy/deploy.sh` robi kopię przed podmianą kodu (migracje uruchamiają się
przy restarcie usługi) i zostawia 10 najnowszych kopii z prefiksem
`szup-predeploy-` — kopii z crona nie rusza. Nieudana albo pusta kopia
przerywa wdrożenie. Brak bazy przy istniejącej instalacji (np. zła ścieżka
`SZUP_DATA_DIR` / `SZUP_DB_URL`) też przerywa wdrożenie, podobnie jak katalog
danych wewnątrz `/opt/szup/backend` (synchronizacja kodu z `--delete` mogłaby
go skasować). Katalog `data/`, pliki `.env*`, `*.db*` i `*.key` są przy
synchronizacji backendu wykluczone i chronione — wdrożenie ich nie nadpisze
ani nie usunie. Kluczy `deploy.sh` nie kopiuje (nie zmienia ich) — robi to
kopia codzienna.

### Codzienna kopia (cron)

Skrypt `/usr/local/sbin/szup-backup` (właściciel `root`, prawa `700`):

```bash
#!/usr/bin/env bash
# Codzienna kopia SZUP: baza (sqlite3 .backup) + klucze (tar, prawa 600).
set -euo pipefail
umask 077                                   # nowe pliki tylko dla roota
APP_DIR=/opt/szup
DATA_DIR=/opt/szup/data                     # = SZUP_DATA_DIR usługi
BACKUP_DIR=/opt/szup/backups
STAMP="$(date +%F-%H%M%S)"

# Brak bazy albo pusty plik (np. inny SZUP_DATA_DIR niż wpisany wyżej) przerywa
# kopię — inaczej sqlite3 utworzyłby pustą bazę i „udaną”, ale bezwartościową kopię.
if [ ! -s "$DATA_DIR/szup.db" ]; then
    echo "szup-backup: brak bazy $DATA_DIR/szup.db (albo plik jest pusty) — kopia przerwana" >&2
    exit 1
fi

mkdir -p "$BACKUP_DIR"; chmod 700 "$BACKUP_DIR"
sqlite3 "$DATA_DIR/szup.db" ".backup '$BACKUP_DIR/szup-$STAMP.db'"
# Kopia musi być spójna — w przeciwnym razie błąd (cron wyśle wynik mailem).
CHECK="$(sqlite3 "$BACKUP_DIR/szup-$STAMP.db" 'PRAGMA integrity_check;')"
if [ "$CHECK" != "ok" ]; then
    echo "szup-backup: kopia $BACKUP_DIR/szup-$STAMP.db nie przeszła integrity_check: $CHECK" >&2
    exit 1
fi
# Klucze: workflow_secret.key, secret.key, jwt_secret.key i .env (gdy klucze
# są w zmiennych SZUP_WORKFLOW_SECRET / SZUP_SECRET_KEY). Brakujący plik
# (np. klucz trzymany tylko w .env) tar pomija z ostrzeżeniem.
tar -czf "$BACKUP_DIR/szup-keys-$STAMP.tar.gz" --ignore-failed-read \
    -C / "${DATA_DIR#/}/workflow_secret.key" "${DATA_DIR#/}/secret.key" \
         "${DATA_DIR#/}/jwt_secret.key" "${APP_DIR#/}/.env"
chmod 600 "$BACKUP_DIR/szup-$STAMP.db" "$BACKUP_DIR/szup-keys-$STAMP.tar.gz"

# Retencja 30 dni (wg daty modyfikacji pliku) — tylko kopie codzienne
# (szup-<data>…); kopii przedwdrożeniowych (szup-predeploy-…) nie ruszamy,
# mają własną retencję.
find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name 'szup-[0-9]*.db' -o -name 'szup-keys-[0-9]*.tar.gz' \) \
    -mtime +30 -delete
```

```bash
# /etc/cron.d/szup-backup — codziennie o 2:15
15 2 * * * root /usr/local/sbin/szup-backup
```

Wymaga pakietu `sqlite3` (`apt install sqlite3`). Katalog
`/opt/szup/backups/` warto dodatkowo kopiować poza serwer (kopia
systemowa / NAS), bo sam serwer jest pojedynczym punktem awarii —
archiwa `szup-keys-*` osobno i zaszyfrowane (patrz wyżej).

## Przywracanie

```bash
# 1. Zatrzymaj usługę — nic nie może pisać do bazy w trakcie podmiany.
systemctl stop szup
cd /opt/szup/data

# 2. Zachowaj obecny stan (także uszkodzony) — przyda się do analizy.
mkdir -p /opt/szup/backups/przed-przywroceniem
mv szup.db /opt/szup/backups/przed-przywroceniem/szup-$(date +%F-%H%M%S).db

# 3. Usuń pliki dziennika STAREJ bazy. Pozostawione -wal/-shm zostałyby
#    nałożone na przywróconą kopię i mogłyby ją uszkodzić.
rm -f szup.db-wal szup.db-shm szup.db-journal

# 4. Przywróć wybraną kopię (codzienną szup-… albo przedwdrożeniową
#    szup-predeploy-…) i sprawdź jej spójność.
cp /opt/szup/backups/szup-RRRR-MM-DD-GGMMSS.db szup.db
chmod 600 szup.db
sqlite3 szup.db "PRAGMA integrity_check;"     # oczekiwany wynik: ok

# 5. Klucze — gdy serwer jest nowy albo klucze zginęły / różnią się od tych
#    z chwili wykonania kopii. Najpierw obejrzyj zawartość archiwum.
tar -tzf /opt/szup/backups/szup-keys-RRRR-MM-DD-GGMMSS.tar.gz
tar -xzpf /opt/szup/backups/szup-keys-RRRR-MM-DD-GGMMSS.tar.gz -C /
chmod 600 /opt/szup/data/*.key /opt/szup/.env

# 6. Uruchom usługę i sprawdź, czy odpowiada.
systemctl start szup
curl -fsS http://127.0.0.1:8003/api/health
```

Uwagi:
- Kopia może być starsza od kodu: brakujące kolumny i tabele dołożą migracje
  przy starcie. Kopii **nowszej** niż kod (po wycofaniu wdrożenia) nie
  przywracamy bez wycofania także kodu do wersji, z którą ją zrobiono.
- Po przywróceniu wszystko, co zapisano po wykonaniu kopii (wnioski, kroki
  obiegu, wpisy audytu), trzeba odtworzyć ręcznie. Wpisz przywrócenie do
  rejestru incydentów (`incident_response.md`).
- Gdy przywracasz kopię na innym serwerze, przenieś **wszystkie** klucze
  (archiwum `szup-keys-*` albo wartości `SZUP_WORKFLOW_SECRET` /
  `SZUP_SECRET_KEY` z `.env`). Nie uruchamiaj usługi bez nich: aplikacja
  wygeneruje nowe `workflow_secret.key` / `secret.key`, a historia obiegu
  przestanie się weryfikować, zaś hasła SMTP/LDAP — odszyfrowywać.
- Po przywróceniu sprawdź weryfikację podpisów obiegu na kilku starszych
  wnioskach — błąd weryfikacji wszystkich oznacza niewłaściwy sekret obiegu.

## RTO / RPO

- **RPO (Recovery Point Objective)**: 24 godziny przy codziennej kopii;
  przy wdrożeniu — stan sprzed wdrożenia.
- **RTO (Recovery Time Objective)**: < 30 minut (procedura wyżej).

## Rotacja klucza Fernet

1. Wygeneruj nowy klucz: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. W `/opt/szup/.env` ustaw stary klucz jako `SZUP_SECRET_KEY_OLD`, a nowy jako `SZUP_SECRET_KEY`.
3. Uruchom w katalogu backendu, z tymi samymi zmiennymi:
   `cd /opt/szup/backend && set -a && . /opt/szup/.env && set +a && /opt/szup/venv/bin/python -m tools.rotate_fernet`
4. Zrestartuj usługę, usuń `SZUP_SECRET_KEY_OLD` i zrób nową kopię kluczy
   (`/usr/local/sbin/szup-backup`) — starsze archiwa `szup-keys-*` mają stary klucz,
   pasujący tylko do kopii bazy z tego samego dnia.

## Podstawa prawna

NIS2 Art. 21 ust. 2 lit. c — ciągłość działania i zarządzanie kopiami zapasowymi.
KSC Art. 14 — wymagania dotyczące zarządzania ryzykiem.
