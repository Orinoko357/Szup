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
- Audit log (retencja 24 miesiące)
- Zdarzenia bezpieczeństwa
- Konfiguracja (SMTP, LDAP, szablony powiadomień) — hasła zaszyfrowane kluczem Fernet

Obok bazy, w tym samym katalogu, leży `jwt_secret.key` (klucz podpisu sesji).
Jego utrata wyloguje wszystkich użytkowników, ale nie powoduje utraty danych —
przy starcie generuje się nowy.

Gdy SQLite pracuje w trybie WAL, część ostatnich zmian może być jeszcze
w plikach `szup.db-wal` i `szup.db-shm`. Dlatego **nie kopiujemy samego pliku
`szup.db` działającej bazy** (`cp`), tylko używamy `sqlite3 .backup`, które
tworzy spójną kopię „na gorąco” razem z zawartością dziennika.

## Kopie zapasowe

Wszystkie kopie trafiają do `/opt/szup/backups/` (katalog `700`, pliki `600`)
pod nazwą `szup-RRRR-MM-DD-GGMMSS.db`. Nazwa sortuje się chronologicznie,
więc retencję liczymy po nazwie, a nie po dacie modyfikacji pliku.

### Kopia przed każdym wdrożeniem

`deploy/deploy.sh` robi kopię przed podmianą kodu (migracje uruchamiają się
przy restarcie usługi) i zostawia 10 najnowszych. Nieudana albo pusta kopia
przerywa wdrożenie. Brak bazy przy istniejącej instalacji (np. zła ścieżka
`SZUP_DATA_DIR`) też przerywa wdrożenie.

### Codzienna kopia (cron)

```bash
# /etc/cron.d/szup-backup — codziennie o 2:15, kopie starsze niż 30 dni są usuwane
15 2 * * * root sqlite3 /opt/szup/data/szup.db ".backup '/opt/szup/backups/szup-$(date +\%F-\%H\%M\%S).db'" && chmod 600 /opt/szup/backups/szup-*.db && find /opt/szup/backups/ -name 'szup-*.db' -mtime +30 -delete
```

Wymaga pakietu `sqlite3` (`apt install sqlite3`). Katalog
`/opt/szup/backups/` warto dodatkowo kopiować poza serwer (kopia
systemowa / NAS), bo sam serwer jest pojedynczym punktem awarii.

### Backup klucza Fernet

Klucz szyfrowania (`SZUP_SECRET_KEY` z `/opt/szup/.env`) jest niezbędny do
odszyfrowania haseł SMTP i konta usługowego LDAP. Przechowuj go **osobno od
kopii bazy** (sejf, zaszyfrowane archiwum, menedżer haseł).

Utrata klucza = brak możliwości odszyfrowania sekretów; trzeba ponownie wpisać
hasło SMTP i hasło konta usługowego LDAP w Ustawieniach.

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

# 4. Przywróć wybraną kopię i sprawdź jej spójność.
cp /opt/szup/backups/szup-RRRR-MM-DD-GGMMSS.db szup.db
chmod 600 szup.db
sqlite3 szup.db "PRAGMA integrity_check;"     # oczekiwany wynik: ok

# 5. Uruchom usługę i sprawdź, czy odpowiada.
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
- Gdy przywracasz kopię z innego serwera, przenieś też `SZUP_SECRET_KEY`.

## RTO / RPO

- **RPO (Recovery Point Objective)**: 24 godziny przy codziennej kopii;
  przy wdrożeniu — stan sprzed wdrożenia.
- **RTO (Recovery Time Objective)**: < 30 minut (procedura wyżej).

## Rotacja klucza Fernet

1. Wygeneruj nowy klucz: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. W `/opt/szup/.env` ustaw stary klucz jako `SZUP_SECRET_KEY_OLD`, a nowy jako `SZUP_SECRET_KEY`.
3. Uruchom w katalogu backendu, z tymi samymi zmiennymi:
   `cd /opt/szup/backend && set -a && . /opt/szup/.env && set +a && /opt/szup/venv/bin/python -m tools.rotate_fernet`
4. Zrestartuj usługę, usuń `SZUP_SECRET_KEY_OLD` i zrób nową kopię klucza.

## Podstawa prawna

NIS2 Art. 21 ust. 2 lit. c — ciągłość działania i zarządzanie kopiami zapasowymi.
KSC Art. 14 — wymagania dotyczące zarządzania ryzykiem.
