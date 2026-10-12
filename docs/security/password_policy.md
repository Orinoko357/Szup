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

- **5 nieudanych prób** logowania → blokada konta na **15 minut**
- Blokada rejestrowana jako `SecurityEvent` o wadze `high`
- Odblokowanie możliwe przez administratora lub automatycznie po upływie czasu

## Rate limiting

- Maksymalnie **10 prób logowania na 60 sekund** z jednego adresu IP
- Przekroczenie → kod HTTP 429

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
