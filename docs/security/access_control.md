# Kontrola dostępu — SZUP

Stan na wersję 3.9. Model: RBAC z rozdziałem obowiązków („Wariant A”) oraz
uprawnieniami wynikającymi ze struktury organizacyjnej (kierownik, zastępca,
przełożony, dyrektor jednostki).

## Role

| Rola | Opis | Zakres |
|------|------|--------|
| `superadmin` | Break-glass (konto konfiguracyjne) | Podgląd wszystkiego, także wniosków na etapie roboczym. **Nie działa w obiegu** (nie wybiera, nie akceptuje, nie realizuje, nie przejmuje, nie rozpatruje zmian nazwiska) i nie łączy się z rolami operacyjnymi `manager` / `it_staff` (400 przy zapisie konta; `/settings/health` ostrzega o kontach sprzed tej zmiany). Jedyny, który zmienia ustawienia LDAP/AD i SMTP, wykonuje reset fabryczny, nadaje i odbiera role `admin` i `superadmin`, zarządza kontami z tymi rolami i zamyka zdarzenia bezpieczeństwa *high* / *critical*. |
| `admin` | Konfiguracja systemu | Użytkownicy, struktura, rejestr oprogramowania, szablony obiegu, powiadomienia, dziennik zdarzeń. **Nie działa w obiegu** (nie wybiera, nie akceptuje, nie realizuje) i nie widzi wniosków na etapie roboczym kierownika. |
| `manager` | Kierownik / zastępca / dyrektor jednostki | Kroki kierownicze obiegu i wnioski dla pracowników w swoim zakresie (zob. „Struktura”). Rola nadawana i zdejmowana automatycznie razem ze stanowiskiem w strukturze. |
| `it_staff` | Pracownik IT | Realizacja wniosków (krok `it_execute`), rejestr oprogramowania, dowiązanie konta do wniosku, rozpatrywanie zmian nazwisk (te dwie operacje — wyłącznie z rolą `it_staff`, bramka `require_it_operator`). Nie widzi wniosków na etapie roboczym. |
| `viewer` | Pracownik | Podgląd własnych uprawnień i własnych wniosków. |

Osoba może mieć kilka ról. Administrator, który ma też działać operacyjnie,
dostaje właściwą rolę operacyjną (`manager`, `it_staff`) — sama rola
`admin` nie daje dostępu do paneli operacyjnych. Superadmin ról operacyjnych
nie dostaje — do pracy w obiegu służy osobne konto.

### Kadry — komórka kadrowa (bez roli)

Roli `hr` nie ma (od 3.9; nadanie jej zwraca 400). Pracownikiem kadr jest
każdy członek komórki oznaczonej jako kadrowa (`Department.is_hr`, „komórka
kadrowa”) — `services/permissions.py: user_is_hr`. Kadry obsługują
**wszystkie jednostki** (wyszukiwanie pracowników, lista pracowników komórki,
składanie wniosków); dawne „Jednostki obsługiwane” (`UserUnit`) zostają
w bazie tylko do odczytu i niczego nie ograniczają. Front dostaje efektywną
rolę `hr` w odpowiedzi logowania i `/auth/me` (role konta + `hr` dla członka
komórki kadrowej); w bazie i w tokenie jej nie ma.

Migracja przy starcie usuwa `hr` z ról wszystkich kont, zapisuje w audit logu
wpis `user.hr_role_removed` (lista loginów i tych, którzy stracili zdolność
kadrową, bo nie są w komórce kadrowej) i ostrzega w logu aplikacji.

### Ograniczenia administratora (ochrona przed samoeskalacją)

Administrator (nie superadmin):
- nie nadaje ani nie odbiera ról `admin` i `superadmin` (także przy zakładaniu konta);
- nie zarządza **kontami z rolą `admin` lub `superadmin`** (poza własnym, w granicach
  niżej): nie edytuje ich (także ról operacyjnych i aktywności), nie resetuje
  hasła, nie odblokowuje, nie dezaktywuje ani nie usuwa — robi to superadmin.
  Import z AD pomija takie konta, gdy uruchamia go administrator;
- nie zmienia własnych ról ani własnej komórki;
- nie przypisuje siebie jako kierownika komórki, kierownika jednostki ani zastępcy;
- nie oznacza własnej komórki jako kadrowej;
- nie zmienia ustawień LDAP/AD ani SMTP (serwer uwierzytelniający, konto
  usługowe, hasło konta pocztowego);
- nie zamyka zdarzeń bezpieczeństwa, które dotyczą jego konta (jako sprawcy
  albo konta docelowego, `details.target_user_id`), ani żadnych zdarzeń
  *high* / *critical* — te zamyka wyłącznie superadmin.

Zdarzenia bezpieczeństwa (i wpisy w audit logu) powstają m.in. przy:

| Zdarzenie | Waga |
|---|---|
| nadanie roli `manager`, `it_staff` | *medium* |
| nadanie roli `admin` / `superadmin` | *high* |
| reset hasła konta z rolą operacyjną lub administracyjną (`user.password_reset`) | *high* |
| zmiana loginu przy zmianie nazwiska (`user.login_changed`) | *high* |
| objęcie stanowiska w strukturze (`structure.post_assigned`) | *medium* |
| zmiana szablonu obiegu albo szablonu przypisanego do typu wniosku | *high* |
| dowiązanie konta do zrealizowanego wniosku | *medium* |
| zmiana ustawień LDAP / SMTP | *high* |

Każde z nich powstaje także wtedy, gdy administrator działa na koncie, które
sam założył.

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
  i przejęcia wniosków tej osoby. Osoba, która przez to staje się
  odpowiedzialna za krok wniosku w toku, dostaje powiadomienie (stan „przed”
  jest zapamiętywany, zanim konto zostanie wyłączone).

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
| `higher_manager_approve` | Kierownik lub zastępca komórki nadrzędnej albo przełożony wyżej (w tym dyrektor jednostki). Kierownik lub zastępca **samej komórki wniosku** nie zatwierdza (nawet gdy kieruje też komórką nadrzędną) — wyjątek: dyrektor jednostki. | jw. |
| `it_execute` | Rola `it_staff`. | Rola `it_staff`. |

Superadmin i administrator bez roli operacyjnej nie wykonują żadnego kroku.

Rozdział obowiązków przy wniosku „dla siebie” (pracownik wniosku = osoba
działająca na kroku): nikt nie zatwierdza akceptacji wyższej własnego wniosku
(także dyrektor jednostki), a gdy kierownik wybiera uprawnienia dla siebie
w komórce jednostopniowej, akceptacja wyższa **nie jest pomijana** — wniosek
zatwierdza przełożony.
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
- superadmin (tylko do odczytu).

IT, administrator i pozostali kierownicy nie widzą takiego wniosku na liście
ani w szczegółach, dopóki kierownik go nie wyśle.

### Przejęcie przez przełożonego

Przełożony (nie kierownik ani zastępca samej komórki) może kliknąć „Przejmij”.
Od tej chwili krok kierownika komórki wykonuje tylko on, a kierownik komórki
dostaje e-mail i komunikat o przejęciu. Zasady:
- przejęcie jest możliwe tylko na etapie roboczym; zapis jest warunkowy
  (dwóch przełożonych naraz → drugi dostaje 409);
- przełożony stojący wyżej niż obecny przejmujący może przejąć wniosek ponownie;
- tylko przejmujący może przejęcie oddać („Oddaj”);
- przejęcie wygasa samo, gdy przejmujący zostanie dezaktywowany albo przestanie
  być przełożonym tej komórki — wtedy kierownik komórki odzyskuje wniosek;
- każda zmiana struktury (kierownik lub zastępca komórki, kierownik jednostki,
  podległość komórek, dezaktywacja, odebranie roli) przelicza wnioski w toku
  w dotkniętym poddrzewie: nieważne przejęcia są automatycznie zwalniane
  (wpis „oddanie” z aktorem „SZUP (automatycznie)” i powodem), a nowy
  odpowiedzialny za krok dostaje powiadomienie;
- przejęcie, oddanie i zapis roboczy są widoczne w historii wniosku.

## Widoczność wniosków

| Kto | Lista i szczegóły |
|-----|-------------------|
| superadmin | Wszystkie. |
| admin, it_staff | Wszystkie poza wnioskami na etapie roboczym kierownika komórki. |
| manager | Wnioski komórek ze swojego zakresu (bezpośrednie, podległe, z akceptacją wyższą, cała jednostka dyrektora); własne spoza zakresu — w widoku „Moje wnioski” i w szczegółach. Etap roboczy obcych komórek — ukryty. |
| kadry (komórka kadrowa), viewer | Wnioski, które sami złożyli. |

Twórca zawsze widzi swój wniosek. Regułę etapu roboczego definiuje jedno
miejsce — `services/workflow.py: manager_stage_visibility` (szczegóły wniosku);
lista stosuje jej odpowiednik już w zapytaniu SQL
(`manager_stage_hidden_clause`, kolumna `AccessRequest.current_node_type`), więc
stronicowanie liczy tylko widoczne wiersze. Zgodność obu wersji sprawdza test
równoważności. Wniosek w toku z pustym `current_node_type` (np. nieudany
backfill po migracji) lista ukrywa w komórkach z etapem roboczym, a start
aplikacji ostrzega o takich wnioskach w logu.

## Dowiązanie konta pracownika (IT)

Konto AD dowiązuje się do wniosku przy realizacji (`execute` z `ad_username`)
albo później (`link-worker`). Obie ścieżki mają te same reguły:
- nie wolno dowiązać wniosku do własnego konta (403);
- istniejące konto musi należeć do komórki wniosku albo nie mieć komórki (409);
  komórki istniejącemu kontu się nie uzupełnia, a nowe konto nie dostaje
  komórki kadrowej (to nadałoby zdolność HR);
- dowiązania już ustawionego nie można zmienić na inne konto (409);
- dowiązanie do wniosku zrealizowanego to zdarzenie bezpieczeństwa *medium*.

## Zmiana nazwiska i loginu

Pracownik zgłasza zmianę nazwiska dla siebie; realizuje ją wyłącznie IT
(rola `it_staff`; admin i superadmin mają podgląd kolejki, rozpatrują tylko
z rolą `it_staff`), opcjonalnie zmieniając login:
- nikt nie rozpatruje własnego wniosku (403);
- loginu konta z rolą `admin` / `superadmin` w tym obiegu się nie zmienia
  (realizacja tylko ze zmianą nazwiska);
- zajętość loginu sprawdzana bez względu na wielkość liter (jak przy
  logowaniu AD/SSO); konto AD dostaje login znormalizowany i poprawny
  dla domeny;
- zmiana loginu unieważnia dotychczasowe sesje konta i jest zdarzeniem
  *high*; pracownik dostaje e-mail o rozpatrzeniu wniosku.

## Składanie wniosków

- **Kadry** (komórka kadrowa): dla wszystkich jednostek.
- **Kierownik** (bez zdolności kadrowej): dla komórek ze swojego zakresu.
- Komórka wniosku musi należeć do wskazanej jednostki.
- Superadmin i administrator: nie składają wniosków (tylko konfiguracja systemu).

## Uwierzytelnianie

- **Konto lokalne**: login i hasło (bcrypt), polityka siły hasła, wymuszona
  zmiana hasła przy pierwszym logowaniu i po resecie przez administratora
  (egzekwowana w backendzie), wygasanie haseł (admin 90 dni, pozostali 180).
- **AD/LDAP**: konto domenowe (`auth_type=ldap`). Konto lokalne — także
  superadmin — nie zaloguje się przez LDAP ani SSO. Login normalizowany
  (małe litery, bez domeny), więc jedno konto AD = jedno konto w aplikacji.
  Puste hasło jest odrzucane przed wysłaniem do AD. Szyfrowanie połączenia
  z AD jest **zalecane, ale nie wymagane**: LDAPS albo STARTTLS z weryfikacją
  certyfikatu serwera (`tls_verify`, plik CA `ca_cert_file`, minimum TLS 1.2).
  Zwykły LDAP (bez TLS) działa — hasła idą wtedy otwartym tekstem, a
  `/settings/health` pokazuje rekomendację (`level: "recommendation"`) przy
  LDAP bez TLS lub bez weryfikacji certyfikatu.
- **SSO (Kerberos)**: Apache (`mod_auth_gssapi`) przekazuje login z sekretem
  `SZUP_SSO_PROXY_SECRET`; backend sprawdza sekret i realm, a token wydaje
  przez jednorazowy, krótko ważny kod (`/auth/sso-exchange`).
- **Ochrona**: limit 10 prób na minutę z jednego adresu, blokada konta po
  5 nieudanych próbach na 15 minut (bez zrywania trwających sesji).
- **Sesja**: JWT HS256, ważność 8 godzin. Token wskazuje konto po **ID**
  (`uid`), a login (`sub`) musi być zgodny z bieżącym loginem konta — stary
  token nie przechodzi na inne konto po zmianie loginu ani po usunięciu konta
  i założeniu nowego pod tym samym loginem. Tokeny bez `uid` są odrzucane.
  Unieważnianie: lista `jti` (wylogowanie) i `tokens_valid_from` (zmiana lub
  reset hasła, zmiana loginu).

## Import z AD

- Importowane są tylko osoby z jednostek powiązanych ze strukturą z AD; nowe
  konta dostają rolę `viewer`, role nadaje się w aplikacji.
- Konto wyłączone w AD: istniejące konto domenowe zostaje dezaktywowane,
  a jego stanowiska i przejęcia zwolnione; nowe nie jest tworzone.
- Import **nie reaktywuje** konta wyłączonego w SZUP (np. przy podejrzeniu
  przejęcia), nawet gdy w AD jest aktywne — wynik importu podaje liczbę
  pominiętych reaktywacji; reaktywacja tylko ręcznie. Zmiany danych
  (nazwisko, e-mail, komórka, stanowisko) trafiają do audit logu.
- Konta, których AD nie zwróciło, **nie** są dezaktywowane automatycznie —
  pusty wynik bywa skutkiem złego zakresu wyszukiwania lub uprawnień konta
  usługowego. Takie konta dezaktywuje administrator ręcznie.

## Audyt

Audit log jest append-only (triggery w bazie) i dostępny dla administratora.
Poza ogólnym wpisem każdego żądania zmieniającego dane zapisujemy zdarzenia:
- kont: utworzenie, zmiana ról, komórki i aktywności (stara i nowa
  wartość), usunięcie zniesionej roli `hr` przy migracji, reset hasła przez administratora, import, aktualizacja
  i dezaktywacja z AD, zmiana nazwiska i loginu;
- struktury: zmiana kierownika komórki i jednostki, dodanie i usunięcie zastępcy;
- szablonów obiegu: utworzenie, zmiana, usunięcie;
- ustawień LDAP/SMTP i resetu fabrycznego (bez haseł, także zaszyfrowanych).

Zmiana hosta lub użytkownika SMTP bez podania nowego hasła usuwa zapisane
hasło. To samo dotyczy hasła konta usługowego LDAP przy zmianie hosta, portu,
LDAPS / STARTTLS, weryfikacji certyfikatu, pliku CA, bind DN albo Base DN. Reset fabryczny wymaga potwierdzenia hasłem (limit 5 nieudanych prób
na 15 minut, każda porażka to zdarzenie bezpieczeństwa).

## Zasada minimalnych uprawnień

- Nowe konto dostaje najniższą rolę (`viewer`); role operacyjne nadaje
  administrator, a rolę `manager` — struktura (objęcie stanowiska).
- Role nie są pobierane z grup AD — zawsze ustala je aplikacja.
- Przegląd uprawnień: rejestr i nocne migawki uprawnień.

## Eksport CSV

Komórki eksportów CSV, które zaczynają się (także po początkowych spacjach)
od `=`, `+`, `-`, `@`, tabulatora lub CR, dostają prefiks `'` — arkusz nie
wykona ich jako formuły (`services/csv_utils.py: csv_safe`).

## Podstawa prawna

NIS2 Art. 21 ust. 2 lit. i — zarządzanie dostępem i uwierzytelnianiem.
RODO Art. 25 — privacy by design, minimalizacja danych.
