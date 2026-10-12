# Backup i ciągłość działania — SZUP

## Dane aplikacji

SZUP przechowuje dane w pliku SQLite: `/opt/szup/data/szup.db`

Zawartość bazy:
- Użytkownicy i ich role
- Jednostki i wydziały
- Systemy IT i słownik uprawnień
- Wnioski o uprawnienia (historia)
- Audit log (retencja 24 miesiące)
- Zdarzenia bezpieczeństwa
- Konfiguracja (SMTP, LDAP)

## Zalecana procedura backupu

### Codzienny backup bazy (cron)

```bash
# /etc/cron.d/szup-backup
0 2 * * * root cp /opt/szup/data/szup.db /opt/szup/data/szup.db.backup.$(date +\%Y\%m\%d) && find /opt/szup/data/ -name "szup.db.backup.*" -mtime +30 -delete
```

### Backup klucza Fernet

Klucz szyfrowania (`SZUP_SECRET_KEY` z `/opt/szup/.env`) jest niezbędny do odszyfrowania haseł SMTP/LDAP.
Przechowuj backup klucza **osobno od backupu bazy danych** (np. w sejfie lub zaszyfrowanym archiwum).

Utrata klucza = brak możliwości odszyfrowania sekretów (wymagana rekonfiguracja SMTP/LDAP).

## Przywracanie

```bash
# Zatrzymaj usługę
systemctl stop szup

# Przywróć bazę
cp /opt/szup/data/szup.db.backup.YYYYMMDD /opt/szup/data/szup.db

# Uruchom usługę
systemctl start szup
```

## RTO / RPO

- **RPO (Recovery Point Objective)**: 24 godziny (przy codziennym backupie)
- **RTO (Recovery Time Objective)**: < 30 minut (prosta procedura przywracania)

## Rotacja klucza Fernet

Przy rotacji klucza:
1. Wygeneruj nowy klucz: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. Ustaw stary klucz jako `SZUP_SECRET_KEY_OLD`, nowy jako `SZUP_SECRET_KEY` w `.env`
3. Uruchom: `python3 -m tools.rotate_fernet`
4. Zrestartuj usługę, usuń `SZUP_SECRET_KEY_OLD`

## Podstawa prawna

NIS2 Art. 21 ust. 2 lit. c — ciągłość działania i zarządzanie kopiami zapasowymi.
KSC Art. 14 — wymagania dotyczące zarządzania ryzykiem.
