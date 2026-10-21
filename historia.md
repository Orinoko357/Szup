# Historia pracy nad SZUP — eksport rozmowy (handoff do Claude Cloud)

> Dokument przenoszący kontekst pracy nad **SZUP (System Zarządzania Uprawnieniami IT)**
> do dalszej pracy w Claude (cloud). Zawiera: opis projektu, architekturę, zasady wdrożenia,
> pełną chronologię poleceń użytkownika (od najstarszego do najnowszego), opis wykonanych
> zmian, pułapki techniczne oraz stan bieżący. Wszystko po polsku, zgodnie z UI aplikacji.

Repozytorium: **https://github.com/Orinoko357/Szup** (prywatne, konto `Orinoko357`)
Autor / właściciel: mateuszk@tuta.io
Ostatni commit w chwili eksportu: `25a1553` — *Ustanie: pokaż pracowników także z podkomórek wybranego węzła*

---

## 1. Czym jest SZUP

**SZUP — System Zarządzania Uprawnieniami IT** dla Urzędu Miasta Wodzisławia Śląskiego (rodzina
aplikacji „WODS"). Zgodny z NIS2 / KSC / RODO. Obsługuje pełny obieg wniosków o nadanie/odebranie
uprawnień do systemów dziedzinowych, zatrudnianie i zwalnianie pracowników, rejestr nadanych
uprawnień, import struktury organizacyjnej i użytkowników z Active Directory, SSO Kerberos.

### Stos technologiczny
- **Backend:** FastAPI + SQLModel + SQLite, uvicorn na porcie **8003**, usługa systemd `szup`.
- **Frontend:** React 19 + Vite, budowany do `frontend/dist/`, serwowany przez Apache2.
- **UI:** w całości po polsku.
- **Auth:** JWT HS256; `get_current_user` ładuje usera z bazy, sprawdzenia ról (`has_role`)
  czytają role z BAZY, nie z tokena.

### Serwer produkcyjny
- **LOCAL-WWW1** (172.16.3.201).
- Checkout gita: `/root/szup-deploy` → rsync do `/opt/szup`.
- Webroot: `/var/www/szup.intranet.wods.pl`.
- Adres: `https://szup.intranet.wods.pl`.

---

## 2. Architektura i konwencje (KLUCZOWE — przeczytaj przed zmianami)

### 2.1. `dist` jest WERSJONOWANY
`frontend/dist/` jest **usunięty z `.gitignore`** i commitowany razem ze źródłami.
Powód: `deploy.sh` na serwerze **tylko kopiuje** `dist` (serwer nie ma node/npm, nie buduje).
Jeśli `dist` nie trafi do gita, `git pull` nie zaktualizuje interfejsu — to był największy,
powtarzający się problem wdrożeniowy.

**Każda zmiana frontu wymaga:**
```bash
cd frontend && npm run build
git add -A        # obejmuje dist
git commit ... && git push
```

### 2.2. Migracje bazy (SQLite)
Każda **nowa kolumna** wymaga krotki w `simple_migrations` w `backend/database.py`, **zawsze z
DEFAULT**, oraz koalescencji NULL w schemacie odczytu. Pułapka: bez DEFAULT + bez koalescencji
GET pada i UI jest puste. Migracje wykonują się przy starcie aplikacji.

### 2.3. Sprawdzanie kompilacji / budowania
- Backend: `python -m py_compile <pliki>` (Python 3.13:
  `C:/Users/mkozielski/AppData/Local/Programs/Python/Python313/python.exe`).
- Frontend: `cd frontend && npm run build 2>&1 | grep -E 'built in|error|Error'`.

### 2.4. Wdrożenie na serwerze
```bash
cd /root/szup-deploy && git pull && ./deploy/deploy.sh
```
`deploy.sh`: `rsync -a --delete backend/`, `rsync -a --delete frontend/dist/ → webroot`,
restart usługi `szup`. Potem w przeglądarce **Ctrl+F5**.

**Używaj WYŁĄCZNIE gita na `/root/szup-deploy`** (nigdy WinSCP — powoduje konflikty).

**Odzyskiwanie serwera po konflikcie `git pull`:**
```bash
cd /root/szup-deploy
git fetch origin && git reset --hard origin/main
git clean -fdx frontend/dist   # usuń nieśledzony stary dist
./deploy/deploy.sh
```
Bezpieczne — `data/`, `.env`, `*.db`, keytab są w `.gitignore`, nie są ruszane.
Jeśli `deploy.sh` zgłasza „Brak dostępu": `chmod +x deploy/*.sh`.

### 2.5. Role i uprawnienia pomocnicze
- `user_is_hr(session, user)` = `has_role(hr/superadmin)` LUB `department.is_hr` (komórka „kadry").
- `_effective_roles(...)` w `auth.py` dokleja rolę `hr` do ODPOWIEDZI (nie do JWT) dla członków
  komórek kadrowych — żeby frontend pokazał Kartotekę.
- Obieg: `getRequestWorkflow(requestId)` zwraca `data.steps`
  `[{step_index, node_type, action, actor_name, created_at, comment}]`, `data.ribbon`,
  `data.current_node`, `data.status`.

### 2.6. Preferencja użytkownika dot. trybu pracy
**Użytkownik testuje sam.** Po zmianach NIE uruchamiaj serwerów ani przeglądarki —
maksymalnie `py_compile` / `npm run build`. Po każdej zmianie w aplikacjach WODS dopisuj
instrukcję wdrożenia (git pull + deploy.sh).

---

## 3. SSO Kerberos (wdrożone)
- SSO oparte na kodzie z `dbac`. Wspólne konto AD `ad_connect_intranet` + wspólny keytab
  `/etc/apache2/intranet.keytab` dla aplikacji intranetowych na LOCAL-WWW1 (m.in. wods-auth).
- Dodano SPN `HTTP/szup.intranet.wods.pl` do konta `ad_connect_intranet`
  (`setspn -S` nie zmienia klucza konta, więc keytab NIE wymagał regeneracji).
- Certyfikat wildcard `*.intranet.wods.pl` pokrywa `szup`.
- **Pułapka:** realne nazwy plików certyfikatu na LOCAL-WWW1 różnią się od tych w przykładowym
  `dbac-apache.conf` (myślniki vs kropki) — poprawne:
  `intranet.wods.pl-fullchain.pem`. Przy każdej nowej apce zweryfikuj ścieżki.
- Flaga SSO domyślnie WYŁĄCZONA.
- **Uwaga eksploatacyjna:** regeneracja wspólnego keytaba = okno serwisowe intranetu
  (dotyka też innych apek korzystających ze wspólnego konta).

---

## 4. Chronologia pracy — polecenia użytkownika (od najstarszego do najnowszego)

Poniżej wszystkie polecenia użytkownika w kolejności, wraz z opisem reakcji.

### Faza A — obieg i realizacja wniosków
1. **„Szybki fix, trzeba dodać zapisywanie odmów…"** → zapis odmów per pozycja w bazie.
2. **„W sensie przed załatwieniem całego wniosku."** → doprecyzowanie: zapis przed zamknięciem wniosku.
3. **„Nie zrestartowałem. Dlatego nie działało. Chcę byś pozwolił też na częściowe i wieloetapowe
   realizowanie wniosku przez IT…"** → etapowa realizacja: per pozycja „Zrobione"/„Odmów"
   zapisywane w bazie przed zamknięciem.
4. **„Odmowę per pozycja już masz, ale nie zapisujesz w bazie na bieżąco… Dodaj też… po najechaniu
   nazwa użytkownika który to wykonał wraz z datą i godziną."** → tooltip z użytkownikiem i datą/godziną
   realizacji/odmowy.
5. **„Wypchnij najnowszą wersję do github."** → commit + push.
6. **„Scal branche, jeśli jest ich kilka"** + odpowiedź **„Usuń stary branch (Zalecane)"** →
   usunięto nieaktualny branch `claude/build-permissions-system`, `main` ustawiony jako domyślny.

### Faza B — struktura uprawnień
7. **„Dodaj możliwość dodawania podgrup do grupy uprawnień."** → poziom Program → Grupa → Podgrupa →
   Uprawnienie; masowe przypisanie do podgrupy. Pola `subgroup_name`, `subgroup_order`.
8. **„Jak dodać podgrupę do istniejących grup?"** → wyjaśnienie + obsługa masowego przypisania.
9. **„Dodaj checkbox + doprecyzowanie, albo coś takiego."** → nowy typ kontrolki
   „Checkbox + doprecyzowanie" (`input_prompt`).

### Faza C — panel kierownika i rejestr
10. **„Dla kierownika powinno być coś takiego, że: Wnioski do obsługi… Wnioski do realizacji…
    Moje wnioski — bardzo nieczytelne"** oraz doprecyzowania → zakładki **„Wnioski do obsługi"** +
    **„Moje wnioski"**; usunięto zbędną zakładkę „Do realizacji".
11. **„W rejestrze uprawnień mogą się pojawiać rzeczy wyłącznie zrealizowane przez IT"** +
    **„Tylko te, które zostały zrobione…"** → Rejestr uprawnień pokazuje WYŁĄCZNIE pozycje
    faktycznie zrealizowane (fulfilled), nie wszystkie z wniosków.
12. **„Czy jeśli wniosek został odrzucony jakaś pozycja, to czy osoba dostanie powiadomienie
    mailem?…"** + wybór **„Lista odmów w mailu końcowym"** → w mailu końcowym do wnioskodawcy
    lista odmówionych pozycji.

### Faza D — import z AD i ujednolicenie UI
13. **„Dodaj jeszcze możliwość przy imporcie użytkowników zaznaczania jednostek najwyższego rzędu…"**
    → wybór jednostek najwyższego rzędu do importu.
14. **„Mamy jednostki i mamy użytkownicy… Ujednolić to… przenieś opcję importu użytkowników z AD do
    użytkowników…"** → import użytkowników z AD przeniesiony do zakładki Użytkownicy; spójny układ.
15. **„Akordeon w użytkownikach ma wyglądać jak w jednostkach. Dodaj też opcję oznaczenia jakiejś
    komórki jako 'kadry'…"** → `is_hr` na komórce; członkowie komórki kadrowej dostają zdolność HR
    bez roli per osoba.
16. **„Zrób commit."**
17. **„Wygląd się różni, wolałbym, żeby użytkownicy wyglądali tak jak jednostki… I by z automatu było
    zwinięte."** → ujednolicony akordeon, domyślnie zwinięty.
18. **„Coś jest rozpierdolone, w jednostkach mam zaznaczony dział kadry, a użytkownicy… nie mają
    oznaczonego HR. Trzeba to ujednolicić."** + **„Ujednolić to proszę."** → `user_is_hr` używane we
    wszystkich punktach wejścia HR; spójne oznaczenie HR.

### Faza E — formularze kadrowe
19. **„Do poprawki w oknie kadrowym: Stanowisko musi być obowiązkowe, Data zatrudnienia od,
    Wybranie komórki organizacyjnej powinno być wygodniejsze… wyszukiwarka… Przy ustaniu… też data
    do której dana osoba pracuje, niech można osobę znaleźć po nazwisku."** → wymagane Stanowisko,
    `employment_from`, `work_until`; wyszukiwarka komórki (combobox); wyszukiwanie pracownika po nazwisku.
20. **„Wdróż następną turę."**
21. **„A czy mamy lepszy i czytelniejszy wygląd w kadrach przy ustaniu stosunku pracy i zatrudnianiu
    nowych?"**
22. **„W Nowym pracowniku niech się wyszukuje komórkę organizacyjną"** → combobox DeptSearchSelect.
23. **„Zrób mi w folderze wspólnym skrypt bat…"** → (przerwane) **„Chodziło mi o folder główny"**;
    później użytkownik usunął bat.
24. **„A zrobiłeś commit na serwer?"** + wklejone wyjścia konfliktu `git pull` na serwerze →
    naprawione przez `git clean -fd && git reset --hard origin/main && ./deploy/deploy.sh`.
25. **„Nadal się to brzydko wyświetla, wywal tego bata"** → usunięto skrypt bat.

### Faza F — pełnoekranowe, spójne widoki wg projektu PDF
26. **„Lepiej, niech to wygląda estetyczniej… żeby to było wycentrowane, na całym ekranie.
    Analogicznie wniosek IT do realizacji czy wniosek kierownika o uprawnienia, niech to wszystko
    jest spójne i estetyczne."**
27. **Przerobienie IT „Realizacja" i wniosku kierownika z modali na widoki pełnoekranowe** (jak Kartoteka).
28. **„[PDF] SZUP — widoki wniosków.pdf. Tutaj masz nowe projekty widoków wniosków. Wdróż to dla
    każdego wniosku w systemie, tak aby to jednolicie wyglądało."** → wspólny szkielet
    `RequestView.jsx` (nagłówek + stepper 5 kroków + podsumowanie + historia) dla wszystkich wniosków.
29. **„Wdroży się to bez problemu, nie będzie jaj jak ostatnio?"** → potwierdzenie bezpieczeństwa wdrożenia.
30. **„1. Tak zaciągnij do obecnych wniosków. 2. Listy wybierane, ich wygląd się różni. Przy
    komórkach organizacyjnych, uprawnieniach itp. Na projekcie jest to estetyczniejsze, doszlifuj to."**
    → (1) realna oś czasu HISTORIA; (2) dopracowanie list wyboru wg makiety.

### Faza G — dopracowanie list i widoku ustania (ostatnia tura)
31. **[zrzut] „To nie wygląda jak na zrzucie"** (picker komórki) → picker komórki: wiersz
    „nazwa (pogrubiona) + ścieżka mono", ikona lupy.
32. **[zrzut] „Nie wyświetla pracowników."** (ustanie stosunku pracy) → dwukolumnowy wybór ze
    struktury: lewa kolumna KOMÓRKA (drzewo), prawa PRACOWNICY (karty radio).
33. **[zrzut] „Nie wyświetla pracowników."** (PM — węzeł nadrzędny) → endpoint zwraca pracowników
    komórki ORAZ jej poddrzewa; wniosek zapisuje rzeczywistą komórkę pracownika.
34. **„Dodaj na repo w github obszerne MD z eksportem tej rozmowy jako historia.md… Chcę przenieść
    do Claude pracę nad tym."** → ten dokument.

---

## 5. Najważniejsze pliki

### Frontend
- `frontend/src/components/RequestView.jsx` — wspólny szkielet widoku wniosku:
  `RequestViewShell` (nagłówek + stepper + 2 kolumny: karta + sidebar PODSUMOWANIE/HISTORIA),
  `Section`, `buildWorkflowSteps`, `KindBadge`, `RequestStepper`. `HistoryBox` pobiera realne
  kroki obiegu przez `getRequestWorkflow(historyRequestId)`.
- `frontend/src/pages/HR.jsx` — Kartoteka: `RequestFormView` (nowy pracownik), `TerminationFormView`
  (ustanie). `DeptSearchSelect` (combobox komórki), `DepartmentPicker` (drzewo, tryb `flush`).
  Dwukolumnowy wybór ze struktury w ustaniu.
- `frontend/src/pages/IT.jsx` — realizacja wniosków (pełnoekranowy `RequestModal` w `RequestViewShell`),
  etapowe „Zrobione/Odmów", `historyRequestId`.
- `frontend/src/pages/Manager.jsx` — panel kierownika: „Wnioski do obsługi" + „Moje wnioski",
  „Wybór uprawnień" z zakładkami filtrów (Wszystkie/Posiadane/Tylko zmiany·N) + szukajką systemu.
- `frontend/src/pages/MyTeam.jsx` — „Moi pracownicy", wniosek o uprawnienia.
- `frontend/src/components/ItemFields.jsx` — `SystemBlock` (z akcentem lewego paska), `PermGroupSection`
  (zwijana grupa, licznik, „Zaznacz wszystkie"), `AdminPermRow`, `groupPerms`, `subgroupPerms`, `PermInput`.
- `frontend/src/components/PermissionChanges.jsx` — `permChangeState`, `changeStyle`, `changeTextStyle`,
  `ChangeBadge` („+ nadanie" / „− odebranie" / „posiada").

### Backend
- `backend/models.py` — `Department.is_hr/description`, `Unit.description`,
  `AccessRequest.employment_from/work_until`, `SystemPermission.subgroup_name/subgroup_order/input_prompt`,
  `RequestItem.fulfilled/denied`, `NotificationTemplate`.
- `backend/database.py` — `simple_migrations` dla powyższych (z DEFAULT).
- `backend/routers/units.py` — import struktury z AD z opisem OU; schematy Unit/Department (description, is_hr).
- `backend/routers/users.py` — `/users/search` (diakrytyko-niewrażliwe), `/users/by-department/{id}`
  (pracownicy komórki + poddrzewa, z `department_id/department_name`), import użytkowników z AD.
- `backend/routers/requests.py` — tworzenie/serializacja wniosków; `employment_from/work_until`;
  `_get_items` z `subgroup_name/denied_at/fulfilled`.
- `backend/services/ldap_service.py` — `fetch_ou_structure` (ou + description).
- `backend/services/notifications.py` — rejestr `EVENTS` szablonów maili + `render()`.

---

## 6. Pułapki i rozwiązane problemy
- **Frontend nie aktualizował się po wdrożeniu** → `dist` był w `.gitignore`. Rozwiązane:
  wersjonowanie `dist` + build przy każdej zmianie.
- **Konflikt `git pull` na serwerze** (lokalne modyfikacje + nieśledzone pliki) →
  `git clean -fd && git reset --hard origin/main && ./deploy/deploy.sh`.
- **`deploy.sh` „Brak dostępu"** → `chmod +x deploy/*.sh`.
- **Import opisów OU „nic nie dodało"** → opis przekazywany przez podgląd→import (payload),
  nie przez niepewny re-fetch.
- **Wyszukiwanie pracownika źle działało** → diakrytyki; `_fold()` (unicodedata + ł→l),
  dopasowanie bez ogonków.
- **Cert zepsuł Apache** → poprawne nazwy plików certu (`intranet.wods.pl-fullchain.pem`).
- **Błędy JSX przy konwersji na pełnoekranowe** → brakujące `</Section>`, fragmenty `<>` dla
  rodzeństwa `DeclarationModal`.
- **Pusta lista pracowników przy węźle nadrzędnym (PM)** → endpoint agreguje poddrzewo.
- **Pułapka NULL w nowej kolumnie** → migracja z DEFAULT + koalescencja w read-schemacie.

---

## 7. Stan bieżący (na moment eksportu)
- Wszystkie widoki wniosków używają wspólnego szkieletu `RequestView.jsx`.
- HISTORIA w złożonych wnioskach pokazuje realną oś czasu kroków obiegu.
- Listy wyboru dopracowane wg makiety: picker komórki (nazwa + ścieżka mono + lupa), odznaki zmian,
  kolorowe akcenty bloków systemów, zakładki filtrów + szukajka w „Wyborze uprawnień".
- Ustanie stosunku pracy: dwukolumnowy wybór ze struktury (KOMÓRKA ↔ PRACOWNICY), z agregacją poddrzewa.
- Build frontu przechodzi, backend kompiluje się, wszystko wypchnięte na `main`.

### Co można robić dalej (otwarte wątki / sugestie)
- Dopracować prawą kolumnę PRACOWNICY wg makiety (karty z podtytułem stanowisko·login — obecnie
  login·komórka·e-mail; backend nie ma pola „stanowisko" dla usera).
- Rozważyć filtr „Tylko zmiany" i szukajkę również w pozostałych widokach list, jeśli potrzebne.
- Ewentualne wdrożenie SSO (flaga domyślnie OFF) — wymaga okna serwisowego przy keytabie.

---

## 8. Jak kontynuować pracę w Claude (cloud)
1. Repo: `https://github.com/Orinoko357/Szup`, branch `main`.
2. Przy KAŻDEJ zmianie frontu: `cd frontend && npm run build`, potem `git add -A` (obejmuje `dist`),
   commit, push.
3. Wdrożenie na LOCAL-WWW1: `cd /root/szup-deploy && git pull && ./deploy/deploy.sh`, potem Ctrl+F5.
4. Nowe kolumny: migracja w `backend/database.py` z DEFAULT + koalescencja NULL w read-schemacie.
5. Użytkownik testuje sam — nie uruchamiaj serwerów/przeglądarki; ograniczaj się do kompilacji/budowania.
6. Po każdej zmianie dopisuj zwięzłą instrukcję wdrożenia.
