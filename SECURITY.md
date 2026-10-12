# Polityka bezpieczeństwa — SZUP

## Zgłaszanie podatności

Jeśli odkryłeś podatność bezpieczeństwa w systemie SZUP, prosimy o odpowiedzialne zgłoszenie:

**E-mail**: mateuszk@tuta.io  
**Temat**: [SZUP SECURITY] Opis podatności

Prosimy o **nieujawnianie podatności publicznie** do czasu jej naprawienia.

## Oczekiwany czas reakcji

- Potwierdzenie otrzymania zgłoszenia: **48 godzin**
- Ocena wagi i plan naprawy: **7 dni roboczych**
- Naprawa krytycznych podatności: **14 dni**

## Zakres

System SZUP obejmuje:
- Backend API (FastAPI, port 8003)
- Frontend (React SPA)
- Baza danych SQLite (`/opt/szup/data/szup.db`)

## Środki bezpieczeństwa

Szczegóły w `docs/security/`:
- `password_policy.md` — polityka haseł
- `access_control.md` — kontrola dostępu i role
- `incident_response.md` — reagowanie na incydenty
- `backup_and_dr.md` — backup i ciągłość działania
- `data_classification.md` — klasyfikacja danych

## Zgodność

System spełnia wymagania:
- NIS2 (Dyrektywa UE 2022/2555)
- KSC (Ustawa o Krajowym Systemie Cyberbezpieczeństwa)
- RODO (Rozporządzenie UE 2016/679)
