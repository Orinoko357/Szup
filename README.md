# SZUP — System Zarządzania Uprawnieniami w Systemach Teleinformatycznych

System do zarządzania uprawnieniami w grupie jednostek samorządu terytorialnego (JST) działających w modelu wspólnej obsługi (art. 10a ustawy o samorządzie gminnym). Spełnia wymagania art. 21 dyrektywy NIS2.

---

## 1. Wymagania systemowe

| Składnik | Minimalna wersja |
|---|---|
| Ubuntu Server | 22.04 LTS |
| Node.js | 20 LTS |
| PostgreSQL | 15+ |
| Nginx | 1.18+ |
| PM2 | 5+ |
| RAM | 2 GB |
| CPU | 2 rdzenie |
| Dysk | 20 GB (+ miejsce na PDF) |

```bash
# Instalacja zależności (Ubuntu 22.04)
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs postgresql nginx
sudo npm install -g pm2
```

---

## 2. Instalacja i konfiguracja

### 2.1 Klonowanie repozytorium

```bash
sudo mkdir -p /home/szup/app
sudo chown $USER:$USER /home/szup/app
cd /home/szup/app
git clone <url_repozytorium> .
```

### 2.2 Konfiguracja bazy danych

```bash
sudo -u postgres psql <<EOF
CREATE USER szup_user WITH PASSWORD 'zmien_na_bezpieczne_haslo';
CREATE DATABASE szup_db OWNER szup_user;
GRANT ALL PRIVILEGES ON DATABASE szup_db TO szup_user;
EOF
```

### 2.3 Zmienne środowiskowe

```bash
cd /home/szup/app/backend
cp .env.example .env
nano .env
```

Wymagane zmienne do uzupełnienia:

```env
DATABASE_URL=postgresql://szup_user:haslo@localhost:5432/szup_db
JWT_SECRET=minimum_64_losowych_znakow_hex
JWT_REFRESH_SECRET=inny_minimum_64_losowych_znakow_hex
LDAP_ENCRYPTION_KEY=32_bajty_hex_do_szyfrowania_hasel_ldap
PDF_STORAGE_PATH=/var/lib/szup/pdf
ALLOWED_ORIGIN=https://twojadomena.pl
NODE_ENV=production
PORT=3001
SCHEDULER_ENABLED=true
```

Generowanie kluczy:
```bash
node -e "console.log(require('crypto').randomBytes(64).toString('hex'))"
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
```

### 2.4 Uruchomienie instalacji

```bash
cd /home/szup/app
bash start.sh prod
```

Skrypt wykona:
1. Instalację pakietów npm
2. Build frontendu React → `backend/public/`
3. Uruchomienie migracji SQL (001–008)
4. Start aplikacji przez PM2 (tryb cluster, 2 instancje)

---

## 3. Inicjalizacja konta SUPERADMIN

Po pierwszym uruchomieniu utwórz konto administratora:

```bash
cd /home/szup/app/backend
node scripts/init-superadmin.js
```

Wymagania hasła: min. 16 znaków, wielkie i małe litery, cyfra, znak specjalny.

Opcjonalnie załaduj dane testowe (środowisko deweloperskie):
```bash
node scripts/seed.js
```

---

## 4. Konfiguracja Nginx

```bash
# Skopiuj konfigurację
sudo cp /home/szup/app/nginx.conf /etc/nginx/sites-available/szup
sudo ln -s /etc/nginx/sites-available/szup /etc/nginx/sites-enabled/szup
sudo rm -f /etc/nginx/sites-enabled/default

# Edytuj domenę i ścieżki certyfikatu w pliku
sudo nano /etc/nginx/sites-available/szup

# Testuj i przeładuj
sudo nginx -t
sudo systemctl reload nginx
```

Certyfikat SSL (Let's Encrypt):
```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d twojadomena.pl
```

---

## 5. Struktura katalogów

```
Szup/
├── backend/
│   ├── src/
│   │   ├── config/          # db, logger, jwt, crypto, ldap
│   │   ├── middleware/       # auth, roleGuard, tenantGuard, auditLogger, rateLimiter
│   │   ├── migrations/       # 001–008 pliki SQL + runner
│   │   ├── routes/           # auth, wnioski, workflow, uprawnienia, przeglady, rejestry, ...
│   │   └── services/         # workflowService, pdfService, schedulerService, excelService, ...
│   ├── public/               # zbudowany frontend (generowany przez start.sh)
│   ├── scripts/
│   │   ├── init-superadmin.js
│   │   └── seed.js
│   ├── server.js
│   ├── package.json
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── api/              # axios z interceptorem refresh
│   │   ├── components/       # Nav, WorkflowVisualizer, WorkflowDndEditor
│   │   ├── hooks/            # useAuth, usePowiadomienia
│   │   └── pages/            # auth, dashboard, wnioski, pracownicy, uprawnienia,
│   │                         # przeglady, rejestry, admin, workflow
│   ├── vite.config.js
│   └── package.json
├── ecosystem.config.js       # PM2 konfiguracja
├── nginx.conf                # Nginx konfiguracja
├── start.sh                  # Skrypt instalacji i uruchomienia
└── README.md
```

---

## 6. Role użytkowników

| Rola | Uprawnienia |
|---|---|
| `SUPERADMIN` | Pełny dostęp, zarządzanie konfiguracją, wszystkie jednostki |
| `IT_ADMIN` | Zarządzanie systemami IT, realizacja wniosków, rejestry, wszystkie jednostki |
| `KADRY` | Zarządzanie pracownikami, wgląd do uprawnień, eksport |
| `KIEROWNIK` | Zatwierdzanie wniosków w swojej jednostce |
| `PRACOWNIK` | Składanie wniosków, przeglądanie własnych uprawnień |

---

## 7. Obsługa wielodomenowego LDAP

System obsługuje jednoczesne uwierzytelnianie przez wiele domen Active Directory:

1. W panelu Admin → Domeny LDAP dodaj domenę z danymi service account
2. Hasło service account jest szyfrowane AES-256-GCM (klucz z `LDAP_ENCRYPTION_KEY`)
3. Użytkownicy logują się na stronie `/login` wybierając domenę lub używając loginu lokalnego
4. Konto lokalne (login/hasło w bazie danych) służy do awaryjnego dostępu SUPERADMIN

Wymagany atrybut LDAP: `sAMAccountName` (login Windows) lub inny skonfigurowany filtrem `user_filter`.

---

## 8. Harmonogram zadań automatycznych (cron)

Scheduler (`src/services/schedulerService.js`) uruchamia się automatycznie razem z backendem gdy `SCHEDULER_ENABLED=true`.

| Zadanie | Harmonogram | Opis |
|---|---|---|
| Przypomnienia | Co godzinę | Wysyła powiadomienia dla wniosków w terminie |
| Eskalacje | Co godzinę | Powiadamia przełożonego po przekroczeniu `eskalacja_dni` |
| Przegląd NIS2 | Codziennie 02:00 | Flaguje uprawnienia wymagające przeglądu cyklicznego |
| Reset numeracji | Codziennie 00:05 | Resetuje licznik wniosków (jeśli skonfigurowano ROK/MIESIAC) |

---

## 9. Eksport i dokumentacja

### PDF
Każdy zatwierdzony wniosek generuje dokument PDF zawierający:
- Dane pracownika i jednostki
- Listę żądanych uprawnień z oznaczeniem kont uprzywilejowanych
- Historię zatwierdzeń z datami i osobami decydującymi
- Sekcję podpisu kwalifikowanego

Pliki przechowywane w `PDF_STORAGE_PATH/{tenant_id}/{numer}.pdf`.

### XLSX / CSV
Dostępny eksport dla wszystkich rejestrów:
- Rejestr uprawnień (`/api/uprawnienia?format=xlsx`)
- Rejestr systemów IT (`/api/rejestry/systemy?format=xlsx`)
- Rejestr przeglądów NIS2
- Dziennik audytowy

CSV generowany z BOM UTF-8 i separatorem średnika (kompatybilny z polskim Microsoft Excel).

---

## 10. Utrzymanie i monitoring

### Komendy PM2
```bash
pm2 status                  # Status procesów
pm2 logs szup-backend       # Logi w czasie rzeczywistym
pm2 reload szup-backend     # Graceful reload (zero downtime)
pm2 stop szup-backend       # Zatrzymanie
pm2 startup                 # Autostart po restarcie serwera
```

### Logi aplikacji
- PM2 stdout: `/var/log/szup/pm2-out.log`
- PM2 stderr: `/var/log/szup/pm2-error.log`
- Winston app log: `backend/logs/app-YYYY-MM-DD.log` (rotacja 30 dni)
- Nginx access: `/var/log/nginx/szup_access.log`
- Nginx error: `/var/log/nginx/szup_error.log`

### Backup bazy danych
```bash
# Przykładowy cron backup (crontab -e)
0 3 * * * pg_dump -U szup_user szup_db | gzip > /backup/szup_$(date +%Y%m%d).sql.gz
find /backup -name "szup_*.sql.gz" -mtime +30 -delete
```

### Aktualizacja aplikacji
```bash
cd /home/szup/app
git pull origin main
bash start.sh prod
```

---

## Licencja

System tworzony na zamówienie dla jednostek samorządu terytorialnego. Wszelkie prawa zastrzeżone.
