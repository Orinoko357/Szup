# SZUP — System Zarządzania Uprawnieniami IT

Aplikacja do wnioskowania o uprawnienia w systemach dziedzinowych, ich
akceptacji w obiegu i realizacji przez IT — z pełną ewidencją, zgodna z
wymaganiami NIS2 / KSC / RODO. Wdrożona dla Urzędu Miasta Wodzisławia Śląskiego.

Część rodziny aplikacji **WODS** (wspólna architektura: FastAPI + React +
SQLite + Apache, logowanie AD/LDAP, obieg wniosków, audyt append-only).

---

## Najważniejsze funkcje

- **Obieg wniosków** o nadanie / odebranie / zmianę uprawnień: wybór uprawnień →
  akceptacja (1‑ lub 2‑stopniowa) → realizacja przez IT. Każdy krok w śladzie audytowym.
- **Odmowa pojedynczej pozycji** (z komentarzem) przez kierownika nadrzędnego lub IT.
- **Struktura organizacyjna**: jednostki i komórki z hierarchią podległości, kierownik
  jednostki (podgląd + wnioskowanie), samodzielne stanowiska (podlegają kierownikowi wyżej).
- **Rejestr oprogramowania** i uprawnień: grupy uprawnień, kontrolki per uprawnienie
  (lista / pole), wymóg wyboru zakresu, kopiowanie grup między programami.
- **Import z plików** (CSV / TSV / Excel / PDF / wklejka) oraz **import struktury i
  użytkowników z AD** (drzewo OU, stanowiska, automatyczne przypisanie kierowników).
- **Oświadczenie wnioskującego** wymagane przy kierowaniu do realizacji.
- **Rejestr nadanych uprawnień** + **nocne migawki** (stan uprawnień wszystkich osób,
  retencja ≥ 5 lat).
- **Powiadomienia e‑mail** (SMTP), opcjonalnie w imieniu osoby wywołującej zdarzenie.
- **Logowanie**: konto lokalne, AD/LDAP oraz **SSO (Kerberos/Negotiate)**.
- **Bezpieczeństwo**: audyt append-only, rate‑limit i lockout logowania, polityka haseł,
  sekrety szyfrowane Fernet, nagłówki CSP/HSTS, zdarzenia bezpieczeństwa.

---

## Stack

| Warstwa | Technologie |
|---|---|
| Backend | Python 3.11+, FastAPI, SQLModel (Pydantic v2 + SQLAlchemy), SQLite, python‑jose (JWT HS256), passlib/bcrypt, cryptography (Fernet), ldap3 |
| Frontend | React 19, Vite, React Router, axios, lucide‑react (bez TypeScript, bez Tailwind — ręczny CSS) |
| Uruchomienie | uvicorn jako usługa systemd (port 8003), Apache2 jako reverse proxy + serwer plików statycznych |

---

## Struktura katalogów

```
szup/
├── backend/            # FastAPI: main.py, database.py, models.py, routers/, services/, tools/, tests/
├── frontend/           # React + Vite: src/ (pages, components, api.js), dist/ (build)
├── deploy/             # setup.sh, deploy.sh, enable-sso.sh, szup.service, szup-apache.conf
├── docs/               # dokumentacja, w tym docs/security/ (polityki NIS2/KSC)
├── CHANGELOG.md
├── SECURITY.md
└── README.md
```

---

## Uruchomienie lokalne (dev)

Wymagania: Python 3.11+, Node 18+.

**Backend** (port 8003):
```bash
cd backend
python -m venv .venv
. .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8003
```

**Frontend** (port 5173, proxy `/api` → `127.0.0.1:8003`):
```bash
cd frontend
npm ci
npm run dev
```

Przy pierwszym uruchomieniu aplikacja poprosi o utworzenie konta **superadmina**
(ekran „Setup"). Baza SQLite tworzy się sama w katalogu danych.

---

## Wdrożenie produkcyjne (Debian/Ubuntu + Apache)

Frontend budujemy lokalnie, całość przenosimy na serwer (np. WinSCP), skrypty
uruchamiamy jako `root`.

```bash
# 1) lokalnie
cd frontend && npm ci && npm run build

# 2) na serwerze — pierwsza instalacja
cd /root/szup
chmod +x deploy/*.sh
./deploy/setup.sh                 # venv + usługa systemd + kopiowanie
cp deploy/szup-apache.conf /etc/apache2/sites-available/szup.conf
a2enmod proxy proxy_http rewrite headers ssl
a2ensite szup && systemctl reload apache2

# 3) kolejne aktualizacje
cd /root/szup && ./deploy/deploy.sh
```

`deploy.sh` przed aktualizacją robi kopię bazy do `/opt/szup/backups/`
(`sqlite3 .backup`, a bez `sqlite3` — `cp`; zostaje 10 najnowszych). Nieudana
kopia przerywa wdrożenie.

Nowe tabele tworzą się przy starcie (`create_all`); nowe kolumny dokładane są
idempotentnie w `database.py` (migracje ręczne, bez Alembica). Po wdrożeniu z
migracją **wymagany restart** usługi (`systemctl restart szup`).

### SSO (Kerberos/Negotiate)

Opcjonalne, domyślnie wyłączone. Konfiguracja Apache (`mod_auth_gssapi`) +
keytab opisana w `deploy/enable-sso.sh`; włącznik w aplikacji: Ustawienia →
Active Directory / LDAP.

---

## Zmienne środowiskowe

Konfigurowane przez `EnvironmentFile`/`Environment` usługi systemd (sekrety
produkcyjne **nigdy** w repo).

| Zmienna | Opis |
|---|---|
| `SZUP_SECRET_KEY` | Klucz Fernet do szyfrowania sekretów w bazie (SMTP/LDAP). **Wymagany.** |
| `SZUP_SECRET_KEY_OLD` | Poprzedni klucz Fernet na czas rotacji (`python -m tools.rotate_fernet`). |
| `SZUP_DATA_DIR` | Katalog danych (domyślnie `/opt/szup/data`); tu leży `szup.db` i klucz JWT `jwt_secret.key` (generowany przy pierwszym starcie). |
| `SZUP_DB_URL` | Opcjonalne nadpisanie URL bazy. |
| `SZUP_CORS_ORIGINS` | Dozwolone originy CORS (dev). |
| `SZUP_ALLOW_TEST_MODE` | `1` dopuszcza tryb testowy (logowanie bez hasła) — tylko dev/staging. |
| `SZUP_SSO_PROXY_SECRET` | Sekret współdzielony Apache ↔ backend dla SSO — **wymagany** przy włączonym SSO (bez niego backend odrzuca logowanie SSO). |
| `SZUP_HELPDESK_EMAIL`, `SZUP_APP_URL` | Adres helpdesku i URL aplikacji w powiadomieniach. |
| `SZUP_SNAPSHOTS` | `0` wyłącza wbudowany harmonogram nocnych migawek. |

Klucz Fernet generujesz: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

---

## Role

`superadmin` (konfiguracja, break‑glass) · `admin` (konfiguracja systemu) ·
`hr` (składanie wniosków dla jednostek) · `manager` (kierownik komórki/jednostki)
· `it_staff` (realizacja wniosków) · `viewer` (podgląd własnych uprawnień).

Wariant A — czysty rozdział obowiązków: administrator konfiguruje, IT realizuje;
panele operacyjne nie są dostępne dla samego admina.

---

## Bezpieczeństwo i zgodność

- **Audyt append‑only** (`auditlog`, triggery `BEFORE UPDATE/DELETE`), retencja ≥ 24 mies.
- **Logowanie**: rate‑limit (10/60 s/IP), lockout (5 prób → 15 min), polityka haseł,
  rewokacja JWT (jti + `tokens_valid_from`), wymuszona zmiana hasła.
- **Sekrety** szyfrowane Fernet (rotacja MultiFernet); nigdy nie zwracane przez API.
- **Nagłówki** CSP, HSTS, X‑Frame‑Options; `X‑Request‑ID` w odpowiedziach.
- Kopie zapasowe bazy i **osobno** klucza Fernet — patrz `docs/security/backup_and_dr.md`.
- Zgłaszanie podatności: `SECURITY.md`. Polityki NIS2/KSC: `docs/security/`.

---

## Kopie zapasowe

Baza to jeden plik SQLite (`$SZUP_DATA_DIR/szup.db`). Kopia „na gorąco":
```bash
sqlite3 /opt/szup/data/szup.db ".backup '/opt/szup/backups/szup-$(date +%F-%H%M%S).db'"
```
Klucz Fernet (`SZUP_SECRET_KEY`) trzymaj w kopii **osobno** — bez niego nie
odszyfrujesz haseł SMTP/LDAP.

---

Projekt wewnętrzny Urzędu Miasta Wodzisławia Śląskiego.
