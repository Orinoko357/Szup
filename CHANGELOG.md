# Changelog — SZUP

Wszystkie istotne zmiany w projekcie są dokumentowane w tym pliku.
Format: [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/).
Wersjonowanie: [Semantic Versioning](https://semver.org/lang/pl/).

## [Unreleased]

## [3.1.0] — 2026-10-22

Intuicyjność wg analizy UX: prowadzenie od zadania, jeden język, mniej zgadywania.

### Dodano
- Linki w e-mailach prowadzą wprost do wniosku (makro `{request_url}`).
- „Czeka na: kto · od kiedy” (liczone od wejścia na bieżący etap) — pulpit, listy,
  nagłówek wniosku, Kartoteka („Gdzie teraz”).
- Wybór uprawnień: stały pasek zmian i krok „Sprawdź przed wysłaniem”.
- „Skopiuj uprawnienia od współpracownika” (Moi pracownicy, wybór uprawnień kierownika).
- IT: filtr Wszystkie / Moje / Nieprzypisane, skróty klawiaturowe (Z, O, ↑↓),
  po realizacji automatycznie następny wniosek.
- Wyszukiwarka globalna Ctrl+K (osoby i wnioski, zależnie od roli).
- Lista kontrolna konfiguracji i sygnały jakości danych na pulpicie administratora
  (GET /api/settings/health).
- „Twój kierownik” w Moich uprawnieniach; „Co stanie się dalej” i komunikat do
  skopiowania w Kartotece; etykiety perspektywy („jako kierownik” / „jako IT”).
- Powiadomienia (toasty) i okna dialogowe zamiast systemowych alert/confirm/prompt
  (w tym potwierdzenie POTWIERDZAM).
- E-mail przy odrzuceniu wniosku (do zgłaszającego i kierownika wybierającego).

### Zmieniono
- Jeden słownik statusów, kroków i rodzajów (w tym „Zmiana”) dla wszystkich ekranów.
- Pulpit: lista sortowana od najdłużej czekających, do 50 pozycji.
- Widok wniosku na telefonie z przyciskami akcji przyklejonymi u dołu.

### Naprawiono
- Tryb ciemny: nagłówki i akcenty (granat na granacie) — zmienna `--color-heading`.
- Link „Otwórz” z pulpitu nie otwiera wniosku ponownie / w złej zakładce.
- Pozycje do odebrania znów przekreślone; błąd SSO jako błąd; liczniki zakładek
  odświeżane; „Administracja” rozwija się na swoich ekranach; usunięty martwy kod.

## [3.0.0] — 2026-10-22

Nowy wygląd interfejsu wg projektu „SZUP — modułowy pulpit” (wersja 3.0).
Wyłącznie frontend — bez zmian w logice, API i bazie danych.

### Zmieniono
- Pasek boczny tylko do nawigacji (bez liczników): grupy PRACA, REJESTRY,
  ADMINISTRACJA (zwijana, rozwinięta na swoich ekranach) i MOJE.
- Pulpit pokazuje wyłącznie sprawy czekające na reakcję: alerty „Wymaga uwagi”
  (umowy serwisowe; otwarte zdarzenia bezpieczeństwa dla admina), kafelki kolejek
  działające jako filtr, lista od najdłużej czekających („Otwórz” prowadzi
  wprost do wniosku), stan „Wszystko załatwione”.
- „Wnioski” i „Do realizacji” połączone w jedną stronę /requests z zakładkami
  Do obsługi · Moje wnioski · Realizacja IT · Zmiany nazwiska (wg ról).
  Stare adresy /manager, /it, /it?tab=names przekierowują.
- „Moja struktura” jest zakładką „Moich pracowników” (/structure przekierowuje).
- Kartoteka: filtr W toku / Zakończone / Wszystkie i wyszukiwarka; lista pokazuje
  wyłącznie własne zgłoszenia (wcześniej osoby z dodatkową rolą widziały cudze).
- Rodzaj wniosku w tabelach jako odznaka ZATRUDNIENIE / ODEJŚCIE.
- Styl: zaokrąglone karty, większe nagłówki stron, zakładki ze złotym
  podkreśleniem i licznikami, polskie nazwy istotności zdarzeń.

- Wszystkie ekrany przepisane wizualnie 1:1 wg projektu 3.0: logowanie i pierwsze
  uruchomienie, górna belka i zmiana hasła, widoki i listy wniosków, Kartoteka,
  Moi pracownicy / Struktura, Moje uprawnienia, rejestry (uprawnienia, migawki,
  oprogramowanie, dostawcy), administracja (jednostki, użytkownicy, szablony obiegu,
  typy wniosków, audit log, bezpieczeństwo, ustawienia) oraz okna dialogowe.
  Bez lewych pasków-akcentów; przyciski i pola 44 px; tryb ciemny zachowany.

### Naprawiono
- Literówka w podtytule „Powiadomienia e-mail” w Ustawieniach.

## [1.0.0] — 2025-04-17

### Dodano
- Pierwsza wersja systemu SZUP przepisana jako aplikacja rodziny WODS
- Backend: FastAPI + SQLModel + SQLite, port 8003
- Autoryzacja JWT HS256 z revocation (jti blacklist + tokens_valid_from)
- 6 ról: superadmin, admin, hr, manager, it_staff, viewer
- Workflow wniosków: pending_manager → pending_it → completed/rejected
- Powiadomienia e-mail na każdym etapie workflow
- Opcjonalne logowanie przez AD/LDAP
- Audit log append-only z retencją 24 miesięcy (NIS2/KSC)
- Zdarzenia bezpieczeństwa (SecurityEvents) z 4 poziomami wagi
- Rate limiting 10 prób/60s/IP + lockout 5 prób → 15 min
- Polityka haseł: min 12 znaków, 3 z 4 klas, rotacja 90/180 dni
- Panel IT: zarządzanie systemami IT i słownikiem uprawnień
- Panel HR: składanie wniosków z dynamicznym wyborem systemu/uprawnienia
- Panel Kierownik: akceptacja/odrzucenie z komentarzem
- Panel Jednostki: CRUD jednostek i wydziałów z przypisaniem kierownika
- Panel Użytkownicy: CRUD kont z zarządzaniem rolami
- Dark mode z persystencją w localStorage
- Deploy: systemd unit (szup.service), Apache VirtualHost (szup-apache.conf)
- Dokumentacja bezpieczeństwa NIS2/KSC (docs/security/)
