# Kontrola dostępu — SZUP

Stan na wersję 3.5. Model: RBAC z rozdziałem obowiązków („Wariant A”) oraz
uprawnieniami wynikającymi ze struktury organizacyjnej (kierownik, zastępca,
przełożony, dyrektor jednostki).

## Role

| Rola | Opis | Zakres |
|------|------|--------|
| `superadmin` | Break-glass | Wszystko, także kroki obiegu i wnioski na etapie roboczym. Jedyny, który zmienia ustawienia LDAP/AD i SMTP, wykonuje reset fabryczny i nadaje rolę `superadmin`. |
| `admin` | Konfiguracja systemu | Użytkownicy, struktura, rejestr oprogramowania, szablony obiegu, powiadomienia, dziennik zdarzeń. **Nie działa w obiegu** (nie wybiera, nie akceptuje, nie realizuje) i nie widzi wniosków na etapie roboczym kierownika. |
| `hr` | Kadry | Składa wnioski dla jednostek przypisanych mu w „Jednostkach obsługiwanych”. Ten sam zakres ma każdy pracownik komórki oznaczonej jako kadrowa (`is_hr`). |
| `manager` | Kierownik / zastępca / dyrektor jednostki | Kroki kierownicze obiegu i wnioski dla pracowników w swoim zakresie (zob. „Struktura”). Rola nadawana i zdejmowana automatycznie razem ze stanowiskiem w strukturze. |
| `it_staff` | Pracownik IT | Realizacja wniosków (krok `it_execute`), rejestr oprogramowania. Nie widzi wniosków na etapie roboczym. |
| `viewer` | Pracownik | Podgląd własnych uprawnień i własnych wniosków. |

Osoba może mieć kilka ról. Administrator, który ma też działać operacyjnie,
dostaje właściwą rolę operacyjną (`manager`, `it_staff`, `hr`) — sama rola
`admin` nie daje dostępu do paneli operacyjnych.

### Ograniczenia administratora (ochrona przed samoeskalacją)

Administrator (nie superadmin):
- nie zarządza kontami `superadmin` i nie nadaje tej roli;
- nie zmienia własnych ról, własnej komórki ani własnych jednostek kadrowych;
- nie przypisuje siebie jako kierownika komórki, kierownika jednostki ani zastępcy;
- nie oznacza własnej komórki jako kadrowej;
- nie zmienia ustawień LDAP/AD ani SMTP (serwer uwierzytelniający, konto
  usługowe, hasło konta pocztowego);
- nie zamyka zdarzeń bezpieczeństwa, które dotyczą jego konta.

Każde nadanie ról `manager`, `it_staff`, `hr` (zdarzenie bezpieczeństwa
*medium*) oraz `admin`/`superadmin` (*high*) i każde objęcie stanowiska
w strukturze trafia do zdarzeń bezpieczeństwa i audit logu — także wtedy, gdy
robi to administrator na koncie, które sam założył.

## Struktura: kierownik, zastępca, przełożony

- **Kierownik komórki** (`Department.manager_user_id`) i jego **zastępcy**
  (`DepartmentDeputy`) mają te same uprawnienia w swojej komórce.
- **Przełożony** komórki to kierownik lub zastępca dowolnej komórki wyżej
  w drzewie oraz **dyrektor jednostki** (`Unit.manager_user_id`).
- **Samodzielne stanowisko** (`kind=standalone`) i komórka bez aktywnego
  kierownika podlegają najbliższemu kierownikowi wyżej — on wykonuje ich kroki.
- Zakres kierownika (lista „Moi pracownicy”, wyszukiwarka, podgląd uprawnień
  pracownika, składanie wniosków) to jego komórki, ich poddrzewo i wszystkie
  komórki jednostki, którą kieruje. Podgląd nie oznacza prawa do działania
  w obiegu — o tym decydują reguły niżej.
- Dezaktywacja konta (ręcznie albo przez import z AD, gdy konto jest wyłączone
  w AD) i odebranie roli `manager` zwalniają stanowiska w strukturze
  i przejęcia wniosków tej osoby.

## Obieg wniosku

Wniosek ma rodzaj: nadanie, odebranie albo zmiana. Szablon obiegu (graf
konfigurowany przez administratora) składa się z kroków:

```
start
  ↓
select_permissions      — kierownik komórki wybiera systemy i uprawnienia
  ↓                       (wersja robocza: „Zapisz roboczy” / „Wyślij”)
manager_approve         — akceptacja kierownika komórki (gdy w szablonie)
  ↓
higher_manager_approve  — akceptacja wyższa; pomijana, gdy komórka nie ma
  ↓                       flagi „wymaga akceptacji wyższej”
it_execute              — realizacja przez IT (etapowo, z możliwością odmowy pozycji)
  ↓
end
```

Kto może wykonać krok (`services/workflow.py: can_act`):

| Krok | Komórka z własnym kierownikiem | Samodzielne stanowisko / komórka bez kierownika |
|------|------|------|
| `select_permissions`, `manager_approve` | Kierownik lub zastępca komórki. Po **przejęciu** — wyłącznie przejmujący przełożony. Inny przełożony widzi wniosek tylko do odczytu. | Najbliższy kierownik wyżej, jego zastępca albo dowolny przełożony. |
| `higher_manager_approve` | Kierownik lub zastępca komórki nadrzędnej albo przełożony wyżej (w tym dyrektor jednostki). | jw. |
| `it_execute` | Rola `it_staff`. | Rola `it_staff`. |

Superadmin może wykonać każdy krok. Administrator bez roli operacyjnej — żadnego.
Każdy wykonany krok jest podpisany (łańcuch skrótów SHA-256 z sekretem
`SZUP_WORKFLOW_SECRET`);
`/requests/{id}/workflow/verify` sprawdza integralność łańcucha.
Nadanie uprawnień kierowane do IT wymaga oświadczenia wnioskującego.

### Etap roboczy kierownika komórki

Gdy wniosek stoi na kroku `select_permissions` lub `manager_approve` komórki,
która ma własnego, aktywnego kierownika, jest **wersją roboczą** kierownika.
Widzą go wyłącznie:
- kierownik komórki i jego zastępcy,
- twórca wniosku (np. kadry),
- przełożeni (tylko do odczytu, dopóki nie przejmą wniosku),
- superadmin.

IT, administrator i pozostali kierownicy nie widzą takiego wniosku na liście
ani w szczegółach, dopóki kierownik go nie wyśle.

### Przejęcie przez przełożonego

Przełożony (nie kierownik ani zastępca samej komórki) może kliknąć „Przejmij”.
Od tej chwili krok kierownika komórki wykonuje tylko on, a kierownik komórki
dostaje e-mail i komunikat o przejęciu. Zasady:
- przejęcie jest możliwe tylko na etapie roboczym; zapis jest warunkowy
  (dwóch przełożonych naraz → drugi dostaje 409);
- przełożony stojący wyżej niż obecny przejmujący może przejąć wniosek ponownie;
- przejmujący albo superadmin może przejęcie oddać („Oddaj”);
- przejęcie wygasa samo, gdy przejmujący zostanie dezaktywowany albo przestanie
  być przełożonym tej komórki — wtedy kierownik komórki odzyskuje wniosek;
- przejęcie, oddanie i zapis roboczy są widoczne w historii wniosku.

## Widoczność wniosków

| Kto | Lista i szczegóły |
|-----|-------------------|
| superadmin | Wszystkie. |
| admin, it_staff | Wszystkie poza wnioskami na etapie roboczym kierownika komórki. |
| manager | Wnioski komórek ze swojego zakresu (bezpośrednie, podległe, z akceptacją wyższą, cała jednostka dyrektora); własne spoza zakresu — w widoku „Moje wnioski” i w szczegółach. Etap roboczy obcych komórek — ukryty. |
| hr, viewer | Wnioski, które sami złożyli. |

Twórca zawsze widzi swój wniosek. Regułę etapu roboczego definiuje jedno
miejsce — `services/workflow.py: manager_stage_visibility` (szczegóły wniosku);
lista stosuje jej odpowiednik już w zapytaniu SQL
(`manager_stage_hidden_clause`, kolumna `AccessRequest.current_node_type`), więc
stronicowanie liczy tylko widoczne wiersze. Zgodność obu wersji sprawdza test
równoważności. Wniosek w toku z pustym `current_node_type` (np. nieudany
backfill po migracji) lista ukrywa w komórkach z etapem roboczym, a start
aplikacji ostrzega o takich wnioskach w logu.

## Składanie wniosków

- **Kadry**: tylko dla jednostek przypisanych w „Jednostkach obsługiwanych”.
- **Kierownik** (bez zdolności kadrowej): dla komórek ze swojego zakresu.
- Komórka wniosku musi należeć do wskazanej jednostki.
- Superadmin: bez ograniczeń.

## Uwierzytelnianie

- **Konto lokalne**: login i hasło (bcrypt), polityka siły hasła, wymuszona
  zmiana hasła przy pierwszym logowaniu i po resecie przez administratora
  (egzekwowana w backendzie), wygasanie haseł (admin 90 dni, pozostali 180).
- **AD/LDAP**: konto domenowe (`auth_type=ldap`). Konto lokalne — także
  superadmin — nie zaloguje się przez LDAP ani SSO. Login normalizowany
  (małe litery, bez domeny), więc jedno konto AD = jedno konto w aplikacji.
  Puste hasło jest odrzucane przed wysłaniem do AD.
- **SSO (Kerberos)**: Apache (`mod_auth_gssapi`) przekazuje login z sekretem
  `SZUP_SSO_PROXY_SECRET`; backend sprawdza sekret i realm, a token wydaje
  przez jednorazowy, krótko ważny kod (`/auth/sso-exchange`).
- **Ochrona**: limit 10 prób na minutę z jednego adresu, blokada konta po
  5 nieudanych próbach na 15 minut (bez zrywania trwających sesji).
- **Sesja**: JWT HS256, ważność 8 godzin; unieważnianie przez listę `jti`
  (wylogowanie) i `tokens_valid_from` (zmiana lub reset hasła).

## Import z AD

- Importowane są tylko osoby z jednostek powiązanych ze strukturą z AD; nowe
  konta dostają rolę `viewer`, role nadaje się w aplikacji.
- Konto wyłączone w AD: istniejące konto domenowe zostaje dezaktywowane,
  a jego stanowiska i przejęcia zwolnione; nowe nie jest tworzone.
- Konta, których AD nie zwróciło, **nie** są dezaktywowane automatycznie —
  pusty wynik bywa skutkiem złego zakresu wyszukiwania lub uprawnień konta
  usługowego. Takie konta dezaktywuje administrator ręcznie.

## Audyt

Audit log jest append-only (triggery w bazie) i dostępny dla administratora.
Poza ogólnym wpisem każdego żądania zmieniającego dane zapisujemy zdarzenia:
- kont: utworzenie, zmiana ról, komórki, jednostek i aktywności (stara i nowa
  wartość), reset hasła przez administratora, import i dezaktywacja z AD;
- struktury: zmiana kierownika komórki i jednostki, dodanie i usunięcie zastępcy;
- szablonów obiegu: utworzenie, zmiana, usunięcie;
- ustawień LDAP/SMTP i resetu fabrycznego (bez haseł, także zaszyfrowanych).

Zmiana hosta lub użytkownika SMTP bez podania nowego hasła usuwa zapisane
hasło. Reset fabryczny wymaga potwierdzenia hasłem (limit 5 nieudanych prób
na 15 minut, każda porażka to zdarzenie bezpieczeństwa).

## Zasada minimalnych uprawnień

- Nowe konto dostaje najniższą rolę (`viewer`); role operacyjne nadaje
  administrator, a rolę `manager` — struktura (objęcie stanowiska).
- Role nie są pobierane z grup AD — zawsze ustala je aplikacja.
- Przegląd uprawnień: rejestr i nocne migawki uprawnień.

## Podstawa prawna

NIS2 Art. 21 ust. 2 lit. i — zarządzanie dostępem i uwierzytelnianiem.
RODO Art. 25 — privacy by design, minimalizacja danych.
