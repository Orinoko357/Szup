-- Migration 005: Permissions and reviews

CREATE TABLE uprawnienia (
  id                    SERIAL PRIMARY KEY,
  tenant_id             INT          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pracownik_id          INT          NOT NULL REFERENCES pracownicy(id) ON DELETE CASCADE,
  system_id             INT          NOT NULL REFERENCES systemy_it(id) ON DELETE CASCADE,
  modul_id              INT          REFERENCES modul_systemu(id) ON DELETE SET NULL,
  zakres_id             INT          NOT NULL REFERENCES zakres_uprawnien(id) ON DELETE CASCADE,
  wniosek_id            INT          REFERENCES wnioski(id) ON DELETE SET NULL,
  aktywne               BOOLEAN      NOT NULL DEFAULT TRUE,
  nadane_bezposrednio   BOOLEAN      NOT NULL DEFAULT FALSE,
  data_od               DATE         NOT NULL DEFAULT CURRENT_DATE,
  data_do               DATE,
  nadane_przez          INT          NOT NULL REFERENCES uzytkownicy(id) ON DELETE RESTRICT,
  data_cofniecia        TIMESTAMPTZ,
  cofniete_przez        INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL,
  powod_cofniecia       TEXT,
  wymaga_przegladu      BOOLEAN      NOT NULL DEFAULT FALSE,
  data_ostatniego_przegladu DATE,
  wynik_przegladu       VARCHAR(20)  CHECK (wynik_przegladu IN ('POZOSTAW','COFNIJ','ZMODYFIKUJ'))
);

CREATE TABLE przeglady (
  id                SERIAL PRIMARY KEY,
  tenant_id         INT          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  typ               VARCHAR(20)  NOT NULL CHECK (typ IN ('CYKLICZNY','DORAZNY','ODEJSCIE')),
  status            VARCHAR(20)  NOT NULL DEFAULT 'W_TOKU'
                    CHECK (status IN ('W_TOKU','ZAKOŃCZONY','ANULOWANY')),
  inicjujacy_id     INT          NOT NULL REFERENCES uzytkownicy(id) ON DELETE RESTRICT,
  data_rozpoczecia  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  data_zakonczenia  TIMESTAMPTZ,
  uwagi             TEXT
);

CREATE TABLE pozycje_przegladu (
  id              SERIAL PRIMARY KEY,
  przeglad_id     INT          NOT NULL REFERENCES przeglady(id) ON DELETE CASCADE,
  uprawnienie_id  INT          NOT NULL REFERENCES uprawnienia(id) ON DELETE CASCADE,
  pracownik_id    INT          NOT NULL REFERENCES pracownicy(id) ON DELETE CASCADE,
  decyzja         VARCHAR(20)  CHECK (decyzja IN ('POZOSTAW','COFNIJ','ZMODYFIKUJ')),
  uzasadnienie    TEXT,
  data_decyzji    TIMESTAMPTZ,
  decydent_id     INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL
);

-- Indexes
CREATE INDEX idx_uprawnienia_tenant ON uprawnienia(tenant_id);
CREATE INDEX idx_uprawnienia_pracownik ON uprawnienia(pracownik_id);
CREATE INDEX idx_uprawnienia_system ON uprawnienia(system_id);
CREATE INDEX idx_uprawnienia_aktywne ON uprawnienia(aktywne, wymaga_przegladu);
CREATE INDEX idx_przeglady_tenant ON przeglady(tenant_id);
CREATE INDEX idx_pozycje_przegladu_przeglad ON pozycje_przegladu(przeglad_id);
