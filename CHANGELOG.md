# Changelog — SZUP

Wszystkie istotne zmiany w projekcie są dokumentowane w tym pliku.
Format: [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/).
Wersjonowanie: [Semantic Versioning](https://semver.org/lang/pl/).

## [Unreleased]

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
