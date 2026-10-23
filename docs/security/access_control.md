# Kontrola dostępu — SZUP

Stan na wersję 3.10. Model: RBAC z rozdziałem obowiązków („Wariant A”) oraz
uprawnieniami wynikającymi ze struktury organizacyjnej (kierownik, zastępca,
przełożony, dyrektor jednostki).

## Role

| Rola | Opis | Zakres |
|------|------|--------|
| `superadmin` | Break-glass (konto konfiguracyjne) | Podgląd wszystkiego, także wniosków na etapie roboczym. **Nie działa w obiegu** (nie wybiera, nie akceptuje, nie realizuje, nie przejmuje, nie rozpatruje zmian nazwisk) — z jednym wyjątkiem rezerwowym (zob. „Rezerwa superadmina”) — i nie łączy się z rolami operacyjnymi `manager` / `it_staff` (400 przy zapisie konta; `/settings/health` ostrzega o kontach sprzed tej zmiany). Jedyny, który zmienia ustawienia LDAP/AD i SMTP, wykonuje operacje nieodwracalne (zob. „Operacje superadmina”), nadaje i odbiera role `admin` i `superadmin`, zarządza kontami z tymi rolami i zamyka zdarzenia bezpieczeństwa *high* / *critical* (poza śladami własnych operacji nieodwracalnych). |
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

Zdolność kadrowa nie jest rolą, ale jej nadanie jest widoczne w zdarzeniach
bezpieczeństwa (od 3.10): wejście konta do komórki kadrowej — przy zakładaniu
konta, edycji (zmiana komórki) i imporcie z AD — to zdarzenie
`user.hr_capability_granted` (*medium*, `details.target_user_id`, `via`:
`create` / `update` / `ldap_import`); przejście między dwiema komórkami
kadrowymi zdarzenia nie daje. Oznaczenie komórki jako kadrowej też jest
zdarzeniem bezpieczeństwa (`department.hr_flag_changed`, medium). Reset hasła członka komórki kadrowej to
`user.password_reset` *high*.

Administrator, który sam należy do komórki kadrowej, ma zdolność kadrową
i może składać wnioski jak kadry — przypisanie go do takiej komórki jest
zawsze widoczne jako `user.hr_capability_granted`, a własnej komórki
administrator nie zmienia (ani w edycji konta, ani importem z AD).

### Ograniczenia administratora (ochrona przed samoeskalacją)

Administrator (nie superadmin):
- nie nadaje ani nie odbiera ról `admin` i `superadmin` (także przy zakładaniu konta);
- nie zarządza **kontami z rolą `admin` lub `superadmin`** (poza własnym, w granicach
  niżej): nie edytuje ich (także ról operacyjnych i aktywności), nie resetuje
  hasła, nie odblokowuje, nie dezaktywuje ani nie usuwa — robi to superadmin.
  Import z AD pomija takie konta, gdy uruchamia go administrator;
- nie zmienia własnych ról ani własnej komórki (import z AD nie zmienia
  komórki konta, które import uruchamia — dotyczy też superadmina);
- nie przypisuje siebie jako kierownika komórki, kierownika jednostki ani zastępcy;
- nie oznacza własnej komórki jako kadrowej;
- nie zmienia ustawień LDAP/AD ani SMTP (serwer uwierzytelniający, konto
  usługowe, hasło konta pocztowego);
- nie zamyka zdarzeń bezpieczeństwa, które dotyczą jego konta (jako sprawcy,
  konta docelowego `details.target_user_id` albo osoby powołanej na stanowisko
  `details.new_user_id`), ani żadnych zdarzeń *high* / *critical* — te zamyka
  wyłącznie superadmin.

Superadmin zamyka każde zdarzenie poza śladem własnej operacji nieodwracalnej
(`audit.purged`, `security.purged`, `settings.factory_reset`,
`department.force_deleted`, `permission_group.deleted_held`, w których jest
sprawcą lub kontem docelowym) — takie zdarzenie zamyka **inny** superadmin.

Zdarzenia bezpieczeństwa (i wpisy w audit logu) powstają m.in. przy:

| Zdarzenie | Waga |
|---|---|
| nadanie roli `manager`, `it_staff` (`user.roles_granted`) | *medium* |
| nadanie roli `admin` / `superadmin` (`user.roles_granted`) | *high* |
| wejście konta do komórki kadrowej (`user.hr_capability_granted`) | *medium* |
| oznaczenie komórki jako kadrowej | *medium* |
| reset hasła konta z rolą operacyjną lub administracyjną albo członka komórki kadrowej (`user.password_reset`) | *high* |
| zmiana loginu przy zmianie nazwiska (`user.login_changed`, z wynikiem weryfikacji w AD) | *high* |
| objęcie stanowiska w strukturze (`structure.post_assigned`) | *medium* |
| zmiana szablonu obiegu albo szablonu przypisanego do typu wniosku | *high* |
| dowiązanie konta do zrealizowanego wniosku | *medium* |
| zmiana ustawień LDAP / SMTP | *high* |
| nieudane potwierdzenie hasłem operacji superadmina (`superadmin.confirm_denied`) albo resetu fabrycznego (`settings.factory_reset_denied`) | *high*; próba wyczerpująca limit — *critical* |
| błędne obecne hasło przy zmianie hasła (`auth.password_change_denied`) | *medium* (konto admin/superadmin: *high*); próba wyczerpująca limit — o stopień wyżej |
| czyszczenie dziennika zdarzeń / zdarzeń bezpieczeństwa (`audit.purged` / `security.purged`) | *critical* |
| nieudane czyszczenie (`audit.purge_failed` / `security.purge_failed`) | *high* (bez triggerów — *critical*) |
| usunięcie (archiwizacja) komórki (`department.force_deleted`) | *high* |
| usunięcie posiadanej grupy uprawnień (`permission_group.deleted_held`) | *high* |
| reset fabryczny (`settings.factory_reset`) | *critical* |
| brak triggerów append-only po czyszczeniu lub resecie (`audit.triggers_missing`) | *critical* |
| blokada konta po błędnych logowaniach (`auth.lockout`) | *high* |

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

Administrator bez roli operacyjnej nie wykonuje żadnego kroku. Superadmin —
tylko w sytuacji rezerwowej opisanej niżej.

### Automatyczna akceptacja wyższa

Akceptacja wyższa jest zaliczana automatycznie (krok widoczny w historii),
gdy krok kierownika komórki wysłał ktoś, kto sam może wykonać akceptację
wyższą: przełożony po przejęciu wniosku albo przy wniosku złożonym dla
podległej komórki, kierownik wyżej działający w komórce bez kierownika,
dyrektor jednostki (`services/workflow.py: auto_higher_approval`). Nigdy dla
wniosku „dla siebie” ani gdy krok wysłał kierownik lub zastępca samej komórki
(wyjątek: dyrektor jednostki, o ile może wykonać akceptację wyższą).

### Rezerwa superadmina

Superadmin może wykonać krok kierownika albo akceptację wyższą wyłącznie
wtedy, gdy w strukturze nie ma nikogo, kto mógłby go wykonać
(`superadmin_acts`): np. akceptacja wyższa wniosku „dla siebie” kierownika,
nad którym nie ma przełożonego (dyrektor jednostki kierujący komórką), albo
krok bez żadnej osoby uprawnionej (ta sama osoba kieruje komórką i komórką
nadrzędną, a jednostka nie ma dyrektora). Superadmin nie działa we własnym
wniosku. Taki stan to sygnał do uporządkowania struktury — lista kontrolna
(`/settings/health`) go zgłasza.

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
- **konto AD** (od 3.10): nowy login jest sprawdzany w AD kontem usługowym —
  musi należeć do tego samego obiektu co konto SZUP (zgodny `objectGUID`,
  zapisywany przy imporcie, a gdy go brak — DN zapisany przy imporcie).
  Login innej osoby, login nieistniejący lub wyłączony w AD, brak zapisanej
  tożsamości AD, wyłączone LDAP albo brak połączenia z AD → odmowa zmiany
  loginu (403/400 z wyjaśnieniem); wniosek można zrealizować bez zmiany
  loginu. Kolejność dla IT: najpierw zmiana loginu w AD, potem realizacja
  wniosku w SZUP;
- nowe imię i nazwisko: 3–100 znaków, jedna linia, bez znaków sterujących;
- zmiana loginu unieważnia dotychczasowe sesje konta i jest zdarzeniem
  *high*; pracownik dostaje e-mail o rozpatrzeniu wniosku.

## Składanie wniosków

- **Kadry** (komórka kadrowa): dla wszystkich jednostek.
- **Kierownik** (bez zdolności kadrowej): dla komórek ze swojego zakresu.
- Komórka wniosku musi należeć do wskazanej jednostki.
- Superadmin: nie składa wniosków. Administrator bez roli `manager` i spoza
  komórki kadrowej: nie składa wniosków (tylko konfiguracja systemu);
  administrator w komórce kadrowej składa je jako kadry (zob. „Kadry”).

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
- **Ochrona**: limit 10 **nieudanych** prób logowania na minutę z jednego
  adresu (udane logowania się nie liczą — od 3.10), blokada konta po
  5 nieudanych próbach na 15 minut (bez zrywania trwających sesji).
- **Potwierdzenie hasłem z zalogowanej sesji** (obecne hasło przy zmianie
  hasła, czyszczenie dzienników, usunięcie komórki, usunięcie posiadanej
  grupy, reset fabryczny): jeden wspólny licznik nieudanych prób per konto,
  zapisany w bazie (tabela `passwordconfirmfailure`, przetrwa restart). Po
  5 nieudanych próbach w ciągu 15 minut każda kolejna próba — także
  z poprawnym hasłem — dostaje 429. Każda nieudana próba jest zdarzeniem
  bezpieczeństwa; udane potwierdzenie zeruje licznik.
- **Sesja**: JWT HS256, ważność 8 godzin. Token wskazuje konto po **ID**
  (`uid`), a login (`sub`) musi być zgodny z bieżącym loginem konta — stary
  token nie przechodzi na inne konto po zmianie loginu ani po usunięciu konta
  i założeniu nowego pod tym samym loginem. Tokeny bez `uid` są odrzucane.
  Unieważnianie: lista `jti` (wylogowanie — tylko ten token) i
  `tokens_valid_from` (zmiana lub reset hasła — także narzędziem
  `tools/reset_password.py` — i zmiana loginu: wszystkie tokeny wydane przed
  bieżącą sekundą). Token z nieprawidłowym podpisem, wygasły albo bez `uid`
  daje 401.
- **Pola kont**: login, imię i nazwisko, e-mail — najwyżej 200 znaków, bez
  znaków sterujących (NUL, CR/LF, tabulator); inaczej 400.

## Import z AD

- Importowane są tylko osoby z jednostek powiązanych ze strukturą z AD; nowe
  konta dostają rolę `viewer`, role nadaje się w aplikacji.
- Konto wyłączone w AD: istniejące konto domenowe zostaje dezaktywowane,
  a jego stanowiska i przejęcia zwolnione; nowe nie jest tworzone.
- Import **nie reaktywuje** konta wyłączonego w SZUP (np. przy podejrzeniu
  przejęcia), nawet gdy w AD jest aktywne — wynik importu podaje liczbę
  pominiętych reaktywacji; reaktywacja tylko ręcznie. Zmiany danych
  (nazwisko, e-mail, komórka, stanowisko) trafiają do audit logu.
- Przeniesienie osoby do innej komórki (zmiana OU w AD) zwalnia jej
  stanowiska w dawnej komórce (kierownik, zastępca), a kierownik obejmuje
  wolne stanowisko nowej komórki (`org_sync.after_department_change`).
  Wejście do komórki kadrowej to zdarzenie `user.hr_capability_granted`.
- Import nie zmienia komórki konta, które go uruchamia (także superadmina).
- OU przypisana kilku komórkom naraz jest niejednoznaczna: osobom z niej import
  komórki nie zmienia (komunikat w wyniku). Komórki zarchiwizowane nie biorą
  udziału w mapowaniu.
- Import zapisuje `objectGUID` konta (weryfikacja zmiany loginu).
- Konta, których AD nie zwróciło, **nie** są dezaktywowane automatycznie —
  pusty wynik bywa skutkiem złego zakresu wyszukiwania lub uprawnień konta
  usługowego. Takie konta dezaktywuje administrator ręcznie.

## Audyt

Audit log jest append-only (triggery w bazie) i dostępny dla administratora.
Jedyny wyjątek to czyszczenie przez superadmina (niżej) — wyłącznie wpisów
starszych niż 24 miesiące.
Poza ogólnym wpisem każdego żądania zmieniającego dane zapisujemy zdarzenia:
- kont: utworzenie, zmiana ról, komórki i aktywności (stara i nowa
  wartość), usunięcie zniesionej roli `hr` przy migracji, reset hasła przez
  administratora, import, aktualizacja i dezaktywacja z AD (ze zwolnionymi
  stanowiskami), zmiana nazwiska i loginu;
- struktury: zmiana kierownika komórki i jednostki, dodanie i usunięcie zastępcy;
- szablonów obiegu: utworzenie, zmiana, usunięcie;
- ustawień LDAP/SMTP i resetu fabrycznego (bez haseł, także zaszyfrowanych).

Zmiana hosta lub użytkownika SMTP bez podania nowego hasła usuwa zapisane
hasło. To samo dotyczy hasła konta usługowego LDAP przy zmianie hosta, portu,
LDAPS / STARTTLS, weryfikacji certyfikatu, pliku CA, bind DN albo Base DN.

## Operacje superadmina (nieodwracalne)

Każda wymaga potwierdzenia hasłem (wspólny limit prób — zob.
„Uwierzytelnianie”) i zostawia zdarzenie bezpieczeństwa, którego wykonawca
sam nie zamyka.

- **Czyszczenie dziennika zdarzeń / zdarzeń bezpieczeństwa**
  (`POST /api/audit/purge`, `POST /api/security/purge`; treść:
  `password`, `reason` 10–1000 znaków, `before` RRRR-MM-DD):
  - usuwa wyłącznie wpisy starsze niż `before`; `before` nie może być
    późniejsze niż dziś minus **24 miesiące** (retencja NIS2/KSC) ani
    z przyszłości — inaczej 400. Trybu „wszystko” nie ma (od 3.10;
    `mode: "all"` → 400). Data bez strefy oznacza północ czasu polskiego;
  - ślady czyszczeń i resetów fabrycznych (`audit.purged`, `security.purged`,
    `settings.factory_reset`) nie są usuwane nigdy;
  - zdjęcie i ponowne założenie triggerów, DELETE i ślad (wpis audytu +
    zdarzenie *critical* z powodem, granicą, liczbą usuniętych wpisów i ich
    rozkładem na typy) w **jednej transakcji** (`BEGIN IMMEDIATE`) — błąd na
    dowolnym etapie wycofuje całość, nie ma czyszczenia bez śladu.
- **Usunięcie komórki** (`force-delete`, z powodem): komórka bez historii jest
  usuwana, z historią — archiwizowana (pracownicy odpięci, podkomórki
  przepięte wyżej, wnioski w toku odrzucone z podanym powodem). Zlikwidowana
  komórka nie przyjmuje kont ani wniosków. Zdarzenie
  `department.force_deleted` (*high*).
- **Usunięcie posiadanej grupy uprawnień** (z powodem i hasłem): posiadaczom
  uprawnienia są odbierane (systemowe wnioski odebrania w historii).
  Zdarzenie `permission_group.deleted_held` (*high*).
- **Reset fabryczny** (fraza `RESET` i hasło): konto wykonującego zostaje;
  `wipe_audit` czyści dziennik i zdarzenia bezpieczeństwa **z wyjątkiem**
  śladów czyszczeń i wcześniejszych resetów. Ślad resetu
  (`settings.factory_reset`, *critical*, z zakresem i liczbą usuniętych
  wierszy) powstaje w tej samej transakcji co czyszczenie.

Ślady w tabeli `securityevent` chronią triggery
`securityevent_trace_no_update` / `securityevent_trace_no_delete` (zakładane
przy każdym starcie): wiersza śladu nie da się usunąć ani zmienić — wolno go
tylko zamknąć (kolumny `resolved_*`). Narzędzie `tools/reset_data.py` też
zostawia ślady.

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
