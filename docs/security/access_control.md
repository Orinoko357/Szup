# Kontrola dostępu — SZUP

## Model ról

SZUP stosuje model RBAC (Role-Based Access Control) z następującymi rolami:

| Rola | Opis | Zakres dostępu |
|------|------|----------------|
| `superadmin` | Administrator systemu | Pełny dostęp do wszystkich funkcji |
| `admin` | Administrator aplikacji | Jak superadmin, bez możliwości tworzenia superadminów |
| `hr` | Pracownik HR / kadry | Składanie wniosków o uprawnienia |
| `manager` | Kierownik wydziału | Akceptacja wniosków dla swoich wydziałów |
| `it_staff` | Pracownik IT | Realizacja zatwierdzonych wniosków, zarządzanie systemami IT |
| `viewer` | Obserwator | Tylko podgląd dashboardu |

## Przepływ wniosków (workflow)

```
HR składa wniosek
    ↓
pending_manager — kierownik zatwierdza lub odrzuca
    ↓ (zatwierdzony)
pending_it — pracownik IT realizuje
    ↓
completed
```

Kierownik może zatwierdzić tylko wnioski dotyczące wydziałów, gdzie jest przypisany jako kierownik (`manager_user_id`).

## Filtrowanie danych według roli

- **HR**: widzi tylko wnioski złożone przez siebie (`created_by_id`)
- **Manager**: widzi wnioski dotyczące swoich wydziałów
- **IT/Admin**: widzi wszystkie wnioski

## Zasada minimalnych uprawnień

- Każdy użytkownik otrzymuje najniższą rolę niezbędną do wykonywania zadań
- Role przypisywane przez administratora w panelu Users
- Brak automatycznego nadawania ról z AD/LDAP — rola zawsze ustalana ręcznie w aplikacji

## Uwierzytelnianie

- Lokalne: login + hasło (bcrypt)
- LDAP/AD (opcjonalne): konto domenowe, rola ustalana w SZUP
- JWT HS256, ważność 8 godzin
- Revocation: blacklista jti + tokens_valid_from (logout-all)

## Podstawa prawna

NIS2 Art. 21 ust. 2 lit. i — zarządzanie dostępem i uwierzytelnianiem.
RODO Art. 25 — privacy by design, minimalizacja danych.
