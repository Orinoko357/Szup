# Changelog — SZUP

Wszystkie istotne zmiany w projekcie są dokumentowane w tym pliku.
Format: [Keep a Changelog](https://keepachangelog.com/pl/1.0.0/).
Wersjonowanie: [Semantic Versioning](https://semver.org/lang/pl/).

## [Unreleased]

## [3.9.1] — 2026-10-23

### Naprawiono
- Samoprzydział przez późne dowiązanie konta: wniosku złożonego bez wskazania
  konta nie można dowiązać (przy realizacji ani później) do konta osoby, która
  go złożyła, wybrała w nim uprawnienia albo przejęła, jeśli nie zatwierdziła go
  inna osoba na akceptacji wyższej. Wniosek „dla siebie” trzeba złożyć ze
  wskazaniem konta — wtedy trafia do przełożonego.
- Uprawnienie usunięte przez superadmina (lub wygaszone) nie może zostać ponownie
  nadane: ani w nowym wniosku, ani przy wyborze lub wersji roboczej wniosku w toku;
  pozycje odmówione nie wracają do zaznaczenia.

## [3.9.0] — 2026-10-23

Decyzje właściciela systemu: role, superadmin, kadry, AD.

### Zmieniono
- **Rola HR zlikwidowana.** Kadry to członkowie komórki kadrowej (flaga „komórka
  kadrowa”), z zakresem wszystkich jednostek. Migracja usuwa rolę „hr” z kont
  i zapisuje w dzienniku listę osób, które straciły funkcję kadr (nie należą
  do komórki kadrowej) — przypisz je do takiej komórki.
- **Administrator i superadmin tylko konfigurują.** Zmiany nazwisk i dowiązywanie
  kont wykonuje wyłącznie IT (rola it_staff). Superadmin nie składa wniosków,
  nie wykonuje kroków obiegu, nie pełni funkcji w strukturze i nie łączy roli
  z rolami operacyjnymi (wyjątek: akceptacja wniosku dyrektora jednostki dla
  siebie, gdy nad nim nikogo nie ma).
- **Akceptacja wyższa zaliczana automatycznie,** gdy wybór wysłał przełożony
  uprawniony do niej (po przejęciu albo przy wniosku złożonym przez przełożonego);
  krok jest widoczny w historii.
- **Szyfrowanie połączenia z AD zalecane, nie wymagane** — lista kontrolna pokazuje
  zalecenie zamiast błędu.

### Dodano (superadmin)
- Czyszczenie dziennika zdarzeń i zdarzeń bezpieczeństwa: hasło, powód, jedna
  transakcja z przywróceniem ochrony; ślad czyszczenia jest nieusuwalny.
- Usuwanie dowolnej komórki z powodem: komórka bez historii jest usuwana,
  z historią — archiwizowana (pracownicy odpięci, podkomórki przepięte wyżej,
  wnioski w toku odrzucone z podanym powodem).
- Usuwanie przyznanej grupy uprawnień z powodem: posiadaczom uprawnienia są
  odbierane (wnioski odebrania w historii), zdarzenie w dzienniku.

### Bezpieczeństwo
- Eksporty CSV (rejestr, migawki, dziennik) neutralizują formuły arkusza.

## [3.8.0] — 2026-10-23

Poprawki po gruntownym audycie 3.7 (wysokie i średnie) oraz akceptacja
przełożonego dla wniosku kierownika o uprawnienia dla siebie.

### Bezpieczeństwo
- Sesja rozpoznawana po identyfikatorze konta (nie po loginie); zmiana loginu
  unieważnia sesje. **Po wdrożeniu wszyscy logują się ponownie.**
- Zmiana nazwiska: zakaz rozpatrzenia własnego wniosku, zajętość loginu bez
  względu na wielkość liter, zmiana loginu konta admina tylko przez superadmina,
  zdarzenie bezpieczeństwa i e-mail do pracownika.
- Konta z rolą admin/superadmin (reset hasła, odblokowanie, wyłączenie, usunięcie,
  role) zarządza wyłącznie superadmin.
- Realizacja IT z loginem AD: te same zasady co dowiązanie konta (nie własne konto,
  ta sama komórka, bez przepinania wniosku na inną osobę, bez komórki kadrowej).
- IT nie może odmówić pozycji odebrania (ustanie zawsze odbiera uprawnienia).
- LDAPS/STARTTLS z weryfikacją certyfikatu (plik CA w Ustawieniach). Istniejąca
  instalacja działa jak dotąd (bez weryfikacji, połączenie bez szyfrowania jawnie
  dozwolone) — lista kontrolna ostrzega do czasu konfiguracji. Nowe instalacje:
  bezpieczne domyślnie.
- Szablon obiegu musi mieć etap kierownika i realizację IT; zmiany szablonów
  i ich przypisania do typów wniosków są zdarzeniem bezpieczeństwa.
- Import z AD nie reaktywuje kont wyłączonych w SZUP; wyłączenie kierownika
  powiadamia nowego odpowiedzialnego.
- Zależności bez znanych podatności (axios, react-router, python-multipart,
  python-jose, fastapi), limity rozmiaru importu i parametrów list, uprawnienia
  plików (UMask 0077, klucze 0600), rsync z właścicielem root.

### Obieg
- Wniosek kierownika (lub zastępcy) o uprawnienia dla siebie wymaga akceptacji
  przełożonego także w komórce jednostopniowej.
- Wersja robocza nie wycieka do IT i administratora, gdy komórka straci kierownika.
- Ustanie: pozycje uzupełniane wszystkimi uprawnieniami pracownika, jedno aktywne
  ustanie na osobę, potwierdzenie realizacji wniosku po ustaniu.
- Odrzucenie wymaga uzasadnienia; IT nie odrzuci wniosku po częściowej realizacji.
- „Struktura” pokazuje faktyczne uprawnienia (bez odebranych i odmówionych).
- Stare wnioski bez obiegu wracają na listy IT i administratora.
- Import struktury z AD nie przenosi komórek między jednostkami i nie tworzy pętli.
- Walidacja oświadczenia (data, nazwisko); błędy zapisu dziennika są logowane.

### Interfejs
- Wybór komórki w Kartotece z klawiatury (combobox ARIA).
- Nagłówek i tabele zadań przy szerokości 900–1200 px (przyklejona kolumna akcji).
- Błąd wczytania zamiast mylącej „pustej listy”, z „Spróbuj ponownie”.
- Kontrastowa ramka fokusu w jasnym motywie; błędy akcji odczytywane przez czytniki.
- Nowe pola LDAP (weryfikacja certyfikatu, plik CA, STARTTLS, zgoda na brak szyfrowania).

## [3.7.0] — 2026-10-23

Poprawki po audycie 3.5: logika obiegu i bezpieczeństwo.

### Zmieniono
- Kierownik lub zastępca komórki nie zatwierdza akceptacji wyższej własnej komórki,
  nawet gdy pełni funkcję w komórce nadrzędnej (wyjątek: dyrektor jednostki).
- Zmiany struktury w trakcie obiegu (kierownik, komórka nadrzędna, zastępcy,
  dyrektor jednostki, import z AD) zwalniają nieważne przejęcia z wpisem w historii
  i powiadamiają nowego odpowiedzialnego.
- Nikt nie dostaje maila o kroku, który sam właśnie przekazał.
- Role admin/superadmin nadaje i odbiera wyłącznie superadmin; zdarzenia
  bezpieczeństwa wysokiej i krytycznej wagi zamyka tylko superadmin.
- Zmiana serwera lub konta usługowego LDAP czyści zapisane hasło bind.
- `deploy.sh`: kopie przed wdrożeniem z prefiksem `szup-predeploy-` (nie usuwają
  nocnych kopii), ochrona `data/`, `.env`, `*.db`, kluczy przy rsync, obsługa
  `SZUP_DB_URL`, przerwanie, gdy katalog danych leży w `backend/`.
- Kopie zapasowe obejmują klucze (podpisy obiegu, szyfrowanie haseł, sesje) —
  `docs/security/backup_and_dr.md`, README.

### Naprawiono
- Akceptacja kierownika po wyborze nie kasuje notatki z wyboru.
- Odrzucenie przez przejmującego powiadamia kierownika komórki; notatka robocza
  nie trafia po odrzuceniu do IT ani administratora.
- „Oddaj” z zapisem warunkowym (bez nadpisania równoczesnego przejęcia).
- Dowiązanie konta przez IT: nie do własnego konta, tylko konto tej samej komórki
  lub bez komórki; bez nadawania komórki kadrowej kontom tworzonym automatycznie.
- Wygasłe przejęcie nie jest pokazywane po wysłaniu wniosku.

## [3.6.0] — 2026-10-23

Poprawki po audycie 3.5: reset, interfejs, porządki.

### Naprawiono
- Reset fabryczny: czyści historię wniosków (`requestevent`) i wszystkie zależne
  tabele; błąd na dowolnej tabeli przerywa całość bez zmian (wcześniej reset
  zgłaszał sukces, zostawiając wnioski, konta i strukturę). Zależności zakresów
  sprawdzane przed czyszczeniem. To samo w `tools/reset_data.py` (jedna transakcja).
- Ramka fokusu w drzewie komórek Kartoteki (regresja 3.5) i w zakładkach.
- Podtytuł kroku wyboru zgodny z przyciskiem „Wyślij do…”.
- Wymuszona zmiana hasła: przycisk „Wyloguj” i powód w oknie.
- Krok „akceptacja kierownika” w szablonie: „Zapisz roboczy”, zachowana notatka,
  odmowa pozycji tylko przy akceptacji wyższej.
- Telefon: węższa przyklejona kolumna akcji w tabelach zadań.

### Zmieniono
- Lista wniosków: dodatkowe zabezpieczenie widoczności, gdy krok obiegu nie jest
  jeszcze uzupełniony; migracje przerywają start przy nieudanym ALTER.
- Jeden pomocnik „aktualny krok wniosku” zamiast 7 kopii; podzielona funkcja akcji obiegu.
- Testy: 252 (m.in. realizacja i odmowa pozycji, wyścig przejęcia, migracje,
  równoważność filtrów widoczności, reset na danych); bez wątków w tle między testami.

## [3.5.0] — 2026-10-22

Poprawki po audycie 3.4.

### Dodano
- „Oddaj” — przełożony może zwolnić przejęty wniosek; historia wniosku pokazuje
  zapis roboczy, przejęcie i oddanie.
- Kopia bazy i sprawdzenie usługi (`/api/health`) w `deploy.sh`; procedura
  przywracania kopii w README i `docs/security/backup_and_dr.md`.
- Dziennik zdarzeń: zmiany użytkowników, ról, haseł, kierowników, zastępców
  i szablonów obiegu.

### Zmieniono
- Przejęcie obowiązuje tylko, gdy przejmujący jest aktywny i nadal jest
  przełożonym; przełożony wyżej może przejąć ponownie; dezaktywacja zwalnia przejęcia.
- Przełożony składający wniosek dla podległej komórki od razu go prowadzi.
- Napis „Wyślij do akceptacji / realizacji” wynika z faktycznego kolejnego kroku.
- Ustawienia SMTP tylko dla superadmina; zmiana serwera lub użytkownika czyści hasło;
  logowanie SMTP bez TLS jest odrzucane.
- Wymagania testowe przeniesione do `requirements-dev.txt`; testy ok. 7× szybsze.

### Naprawiono
- IT nie widzi już wniosków roboczych przez przypisanie / dowiązanie konta.
- Listy IT i administratora nie są skracane przez ukryte wnioski.
- Wniosek z jednostką niezgodną z komórką jest odrzucany.
- Kierownik wyłączony w AD zwalnia stanowiska; nieaktywni kierownicy nie są adresatami.
- Notatka z wersji roboczej nie trafia do IT; pusta wersja robocza wymaga potwierdzenia.
- Ręczna migawka nie blokuje nocnej; spójne konto usługowe LDAP.
- Interfejs: powrót fokusu po zamknięciu okien, tabele zadań i strona
  „Bezpieczeństwo” na telefonie, przełącznik motywu w nagłówku na wąskich ekranach.

## [3.4.0] — 2026-10-22

Wnioski robocze i przejmowanie przez przełożonego.

### Dodano
- Krok wyboru uprawnień i nowy wniosek kierownika: przyciski „Anuluj”,
  „Zapisz roboczy”, „Wyślij do akceptacji” / „Wyślij do realizacji”.
  Wybór trafia do bazy dopiero przy zapisie roboczym albo wysłaniu.
- Wniosek na etapie kierownika komórki (z własnym kierownikiem) jest widoczny
  tylko dla tego kierownika i zastępców, składającego i superadmina — IT,
  administrator i inni zobaczą go dopiero po wysłaniu.
- Przełożony (kierownik wyższego rzędu, dyrektor jednostki) widzi takie wnioski
  w sekcji „W przygotowaniu w podległych komórkach”, może je podejrzeć
  i kliknąć „Przejmij” — dopiero wtedy obsługa należy do niego; kierownik
  komórki dostaje e-mail i przy próbie działania komunikat o przejęciu.

### Zmieniono
- Przełożony nie wykonuje już kroku kierownika w komórce z własnym kierownikiem
  bez przejęcia wniosku. Komórki bez kierownika i samodzielne stanowiska — bez zmian.

## [3.3.0] — 2026-10-22

Poprawki po audycie 3.2: bezpieczeństwo logowania, logika obiegu, dostępność
interfejsu i porządki w kodzie.

### Usunięto
- Usuwanie wpisów audit logu i zdarzeń bezpieczeństwa (dodane w 3.2) — dziennik
  znów jest wyłącznie do odczytu (append-only, triggery w bazie).
- Martwy kod: wyłączony obieg papierowy PDF/EZD (bramka podpisu, endpointy
  `workflow/pdf` i `workflow/ezd-confirm`, generator PDF), pole `ribbon`, nieużywane
  endpointy (`/requests/my-scope`, `/requests/stats/summary`, `/requests/{id}/pdf`,
  `/units/{id}/departments`, `/systems/active`, `/workflow-templates/node-types`,
  `/auth/logout-all`), `require_hr`, nieużywane importy i eksporty. Kolumny w bazie
  zostają (bez migracji destrukcyjnych).

### Bezpieczeństwo
- Logowanie AD i SSO tylko dla kont domenowych (konto lokalne, także superadmin,
  nie dostanie tokenu przez `/login/ldap` ani SSO).
- SSO: obowiązkowy sekret proxy (`SZUP_SSO_PROXY_SECRET`) i sprawdzenie realmu.
- Normalizacja loginu (bez rozróżniania wielkości liter); konta wyłączone w AD
  są dezaktywowane.
- Adres klienta z ostatniego przeskoku `X-Forwarded-For` (lokalne proxy).
- Blokada konta po nieudanych próbach nie zrywa już trwających sesji.
- Wymuszona zmiana hasła (pierwsze logowanie / hasło wygasłe) egzekwowana w backendzie.
- Administrator nie nada sobie wyższych uprawnień; ustawienia LDAP tylko dla
  superadmina; zmiany ustawień zapisywane w audycie.

### Naprawiono
- Realizacja IT najpierw waliduje, potem zapisuje (bez częściowych zmian przy błędzie).
- Typ wniosku jest wymagany; jedna reguła zakresu przełożonego w całym systemie.
- Role w interfejsie odświeżane z `/auth/me`.
- Akceptacja wyższa bez adresata w strukturze trafia do dyrektora jednostki;
  powiadomienia także do zastępców.
- Bez zbędnego e-maila o wyborze uprawnień, gdy składający od razu je wybrał;
  pusty wybór uprawnień nie czyści pozycji wniosku.
- E-maile wysyłane po zapisie zmian przez ograniczoną pulę wątków (błędy w logach).

### Zmieniono
- Edytor szablonów obiegu bezpiecznie wczytuje uszkodzony graf.
- Tryb ciemny: przyciski i kolor stanu „wybrany” (`--color-selected`).
- Szuflada menu i okna dialogowe: pułapka i zwrot fokusu; etykiety pól i obsługa
  klawiatury; czytelne błędy logowania; nazwa „Dziennik zdarzeń”.
- Strony ładowane leniwie — pakiet startowy mniejszy o ok. 50%.
- Porządki: nowe i naprawione testy, wspólne zdejmowanie triggerów audytu,
  przypięte zakresy zależności, kopia bazy w `deploy/deploy.sh` przed wdrożeniem.

## [3.2.0] — 2026-10-22

Porządki po audycie 3.1 (spójność, logika, czystość) + nowe funkcje administratora.

### Dodano
- Usuwanie wpisów audit logu i zdarzeń bezpieczeństwa przez administratora
  (wszystkie / starsze niż data / wg filtra / tylko rozwiązane), z potwierdzeniem
  hasłem i „USUŃ”; ślad operacji zostaje w logu. Świadome odstępstwo od „append-only”.
- „Przejdź” przy komórkach bez kierownika otwiera Jednostki z filtrem
  `?filter=no_manager` (tylko komórki bez kierownika).
- Menu w szufladzie na telefonie (poniżej 900 px), formularze w jednej kolumnie.
- Ostrzeżenie „Porzucić zmiany?” przy wyjściu z niezapisanego wniosku/formularza.

### Naprawiono
- Przełożony / dyrektor jednostki może załadować uprawnienia pracownika podległej
  komórki (wcześniej 403 blokowało wybór uprawnień).
- „Do obsługi” ładuje tylko wnioski w toku (bez limitu 200 najnowszych); „Otwórz”
  dociąga wniosek spoza listy; wyszukiwarka otwiera wniosek także na stronie „Wnioski”.
- „Kopiuj od współpracownika” nie odbiera obecnych uprawnień i pomija wycofane.
- Godziny w historii i przy pozycjach wniosku (UTC → czas lokalny).
- E-maile wysyłane dopiero po zapisie zmian (nie przy wycofanej operacji);
  powiadomienia etapów także do zastępców; adresat akceptacji wyższej spójny z „Czeka na”.
- Twórca widzi swój wniosek także spoza zakresu kierowniczego.
- Ustawienia: błąd wczytania blokuje zapis (nie nadpisze konfiguracji wartościami domyślnymi).
- Tryb ciemny: odznaki rodzaju wniosku, etapy obiegu, pozostałe twarde kolory.
- Lista kontrolna: rzetelniejsze sprawdzenia i szybsze zapytania.

### Zmieniono
- Wspólne komponenty: przełącznik filtrów, okno dialogowe, pole formularza,
  potwierdzenia i komunikaty błędów (błędy walidacji czytelne zamiast „[object Object]”).
- Tytuły stron zgodne z menu, jeden słownik ról, etykiety pól powiązane z polami.
- Usunięty martwy kod i nieużywane style; zależność `reactflow`.

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
