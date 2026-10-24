# Polityka haseł — SZUP

## Wymagania złożoności

- Minimalna długość: **12 znaków**
- Co najmniej **3 z 4** klas znaków: małe litery, wielkie litery, cyfry, znaki specjalne
- Weryfikacja przy tworzeniu konta, logowaniu i zmianie hasła

## Ważność haseł

| Rola | Maksymalny wiek hasła |
|------|-----------------------|
| superadmin, admin | 90 dni |
| pozostałe role | 180 dni |

Po przekroczeniu limitu użytkownik jest zmuszony do zmiany hasła przy kolejnym logowaniu (`must_change_password = true`).

## Blokada konta

- **5 nieudanych prób hasła w 15 minut** → blokada logowania dla pary
  konto + adres IP na **15 minut** (HTTP 423); logowanie z innego adresu działa
- Do tego samego limitu liczą się nieudane potwierdzenia hasłem w sesji
  (zmiana hasła, operacje superadmina, reset fabryczny) — po przekroczeniu
  HTTP 429. Próba jest zapisywana przed weryfikacją hasła, więc równoległe
  żądania nie omijają limitu
- Blokada rejestrowana jako `SecurityEvent` o wadze `high` (dla superadmina
  `critical`)
- Odblokowanie: administrator, reset hasła, `tools/reset_password.py` albo
  automatycznie po upływie czasu

## Rate limiting

- Maksymalnie **10 nieudanych prób logowania na 60 sekund** z jednego adresu IP
  (udane logowania się nie liczą)
- Przekroczenie → kod HTTP 429

## Bezczynność

- Sesja wygasa po **30 minutach** bez aktywności — egzekwuje to serwer
  (HTTP 401), nie tylko przeglądarka

## Przechowywanie haseł

- Hasła hashowane algorytmem **bcrypt** (rounds=12)
- Nigdy nie przechowywane w plaintext
- Sekrety zewnętrzne (SMTP, LDAP) szyfrowane **Fernet** (AES-128-CBC + HMAC-SHA256)

## Zmiana hasła

- Każdy użytkownik może zmienić swoje hasło przez panel (Header → Zmień hasło)
- Administrator może zresetować hasło dowolnego użytkownika (Users → Reset hasła)
- Po resecie hasła flaga `must_change_password = true` — użytkownik musi zmienić hasło przy kolejnym logowaniu

## Podstawa prawna

NIS2 Art. 21 ust. 2 lit. i — polityki i procedury dotyczące uwierzytelniania.
KSC Art. 14 — wymagania dotyczące zarządzania dostępem.
