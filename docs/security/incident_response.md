# Reagowanie na incydenty — SZUP

## Klasyfikacja zdarzeń bezpieczeństwa

| Waga | Przykłady | Czas reakcji |
|------|-----------|--------------|
| `low` | Nieudane logowanie (< 5 prób) | 72 godziny |
| `medium` | Wielokrotne błędy z nowego IP | 24 godziny |
| `high` | Blokada konta, podejrzane logowanie | 4 godziny |
| `critical` | Potencjalne naruszenie danych | Natychmiast |

## Monitorowanie

Zdarzenia bezpieczeństwa dostępne w panelu SZUP → Bezpieczeństwo (rola admin/superadmin).

Automatycznie rejestrowane:
- Nieudane logowania
- Blokady kont (po 5 nieudanych próbach)
- Przekroczenia rate-limitu
- Działania administracyjne

## Procedura obsługi incydentu

1. **Wykrycie**: panel Bezpieczeństwo lub logi `/opt/szup/logs/app.log`
2. **Ocena**: ustal wagę i zakres na podstawie `SecurityEvent`
3. **Izolacja**: w razie potrzeby dezaktywuj konto (Users → Dezaktywuj)
4. **Analiza**: audit log (`/audit`) zawiera pełny ślad działań
5. **Raportowanie**: zdarzenia `high`/`critical` zgłaszane do CERT Polska w ciągu 24h (KSC)
6. **Zamknięcie**: oznacz zdarzenie jako rozwiązane w panelu Bezpieczeństwo

## Eskalacja

- Zdarzenia `critical` → natychmiastowe powiadomienie kierownika IT i administratora systemu
- Naruszenie danych osobowych → powiadomienie UODO w ciągu 72 godzin (RODO Art. 33)

## Podstawa prawna

NIS2 Art. 21 ust. 2 lit. b — obsługa incydentów.
KSC Art. 11 — zgłaszanie incydentów.
RODO Art. 33-34 — zgłaszanie naruszeń ochrony danych.
