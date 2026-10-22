# Klasyfikacja danych — SZUP

## Kategorie danych przetwarzanych przez SZUP

### Dane osobowe (RODO)

| Dane | Cel | Podstawa prawna | Retencja |
|------|-----|-----------------|----------|
| Imię i nazwisko pracownika | Identyfikacja we wnioskach | Art. 6 ust. 1 lit. c RODO (obowiązek prawny) | Czas trwania wniosku + 5 lat |
| E-mail, telefon pracownika | Powiadomienia o statusie wniosku | Art. 6 ust. 1 lit. c RODO | Czas trwania wniosku + 5 lat |
| Stanowisko pracownika | Kontekst wniosku | Art. 6 ust. 1 lit. c RODO | Czas trwania wniosku + 5 lat |
| Login i hasło (bcrypt) | Uwierzytelnianie | Art. 6 ust. 1 lit. b RODO | Czas trwania konta |
| Adres IP w logach | Bezpieczeństwo/audit | Art. 6 ust. 1 lit. f RODO | 24 miesiące |

### Dane operacyjne

| Dane | Klasyfikacja | Lokalizacja |
|------|-------------|-------------|
| Hasło SMTP | Poufne | `/opt/szup/data/szup.db` (zaszyfrowane Fernet) |
| Hasło konta LDAP | Poufne | `/opt/szup/data/szup.db` (zaszyfrowane Fernet) |
| Klucz Fernet | Ściśle poufne | `/opt/szup/.env` |
| Klucz JWT | Ściśle poufne | `/opt/szup/data/jwt_secret.key` (0600) |
| Audit log | Wewnętrzne | `/opt/szup/data/szup.db` (append-only) |

## Zasady ochrony danych

1. **Minimalizacja**: zbierane są tylko dane niezbędne do obsługi wniosków
2. **Szyfrowanie w spoczynku**: sekrety szyfrowane Fernet, baza SQLite na zaszyfrowanym systemie plików (jeśli wymagane)
3. **Szyfrowanie w transmisji**: HTTPS (TLS) wymagane w produkcji (HSTS)
4. **Kontrola dostępu**: dane pracownika widoczne tylko dla HR, kierownika wydziału i IT
5. **Retencja audit logu**: 24 miesiące (wymóg KSC), tabela append-only

## Prawa podmiotów danych

Żądania realizacji praw (dostęp, sprostowanie, usunięcie) należy kierować do administratora danych.
Audit log jest append-only — triggery w bazie blokują UPDATE/DELETE, a aplikacja nie udostępnia usuwania wpisów. Wyczyszczenie logu jest możliwe wyłącznie przy przywróceniu ustawień fabrycznych (superadmin) albo narzędziem `tools/reset_data.py` uruchamianym na serwerze — z zachowaniem procedury audytu.

## Podstawa prawna

RODO Art. 5 — zasady przetwarzania danych osobowych.
RODO Art. 25 — privacy by design and by default.
KSC Art. 14 — ochrona informacji.
