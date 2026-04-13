-- Migration 004: Applications (wnioski) and stages (etapy)

CREATE TABLE wnioski (
  id                      SERIAL PRIMARY KEY,
  numer                   VARCHAR(50)  UNIQUE,
  tenant_id               INT          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  pracownik_id            INT          NOT NULL REFERENCES pracownicy(id) ON DELETE CASCADE,
  inicjujacy_id           INT          NOT NULL REFERENCES pracownicy(id) ON DELETE CASCADE,
  szablon_id              INT          REFERENCES workflow_szablony(id) ON DELETE SET NULL,
  status                  VARCHAR(20)  NOT NULL DEFAULT 'SZKIC'
                          CHECK (status IN ('SZKIC','W_TOKU','WYMAGA_POPRAWY','OCZEKUJE_IT','ZREALIZOWANY','ODRZUCONY')),
  aktualny_etap_kolejnosc INT,
  uwagi_inicjujacego      TEXT,
  uwagi_it                TEXT,
  odrzucil_id             INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL,
  data_odrzucenia         TIMESTAMPTZ,
  powod_odrzucenia        TEXT,
  pdf_sciezka             TEXT,
  pdf_wygenerowany_przez  INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL,
  pdf_data_generowania    TIMESTAMPTZ,
  zrealizowal_it_id       INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL,
  data_realizacji         TIMESTAMPTZ,
  uwagi_realizacji        TEXT,
  data_utworzenia         TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  data_ostatniej_zmiany   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE pozycje_wniosku (
  id                    SERIAL PRIMARY KEY,
  wniosek_id            INT          NOT NULL REFERENCES wnioski(id) ON DELETE CASCADE,
  system_id             INT          NOT NULL REFERENCES systemy_it(id) ON DELETE CASCADE,
  modul_id              INT          REFERENCES modul_systemu(id) ON DELETE SET NULL,
  zakres_id             INT          NOT NULL REFERENCES zakres_uprawnien(id) ON DELETE CASCADE,
  uzasadnienie          TEXT,
  dodana_przez          INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL,
  zmodyfikowana_przez   INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL,
  data_modyfikacji      TIMESTAMPTZ
);

CREATE TABLE wnioski_etapy (
  id                      SERIAL PRIMARY KEY,
  wniosek_id              INT          NOT NULL REFERENCES wnioski(id) ON DELETE CASCADE,
  kolejnosc               INT          NOT NULL,
  nazwa                   VARCHAR(200),
  zatwierdzajacy_id       INT          REFERENCES pracownicy(id) ON DELETE SET NULL,
  opcjonalny              BOOLEAN      NOT NULL DEFAULT FALSE,
  opis_warunku_pominiecia TEXT,
  przypomnienie_dni       INT          NOT NULL DEFAULT 3,
  eskalacja_dni           INT          NOT NULL DEFAULT 7,
  status                  VARCHAR(20)  NOT NULL DEFAULT 'OCZEKUJE'
                          CHECK (status IN ('OCZEKUJE','ZATWIERDZONY','ODRZUCONY','ODESŁANY','POMINIĘTY')),
  pominiety               BOOLEAN      NOT NULL DEFAULT FALSE,
  powod_pominiecia        TEXT,
  data_przypisania        TIMESTAMPTZ  DEFAULT NOW(),
  data_akcji              TIMESTAMPTZ,
  data_przypomnienia      TIMESTAMPTZ,
  data_eskalacji          TIMESTAMPTZ,
  eskalacja_do            INT          REFERENCES pracownicy(id) ON DELETE SET NULL,
  komentarz               TEXT,
  UNIQUE(wniosek_id, kolejnosc)
);

-- Indexes
CREATE INDEX idx_wnioski_tenant ON wnioski(tenant_id);
CREATE INDEX idx_wnioski_pracownik ON wnioski(pracownik_id);
CREATE INDEX idx_wnioski_inicjujacy ON wnioski(inicjujacy_id);
CREATE INDEX idx_wnioski_status ON wnioski(status);
CREATE INDEX idx_pozycje_wniosku_wniosek ON pozycje_wniosku(wniosek_id);
CREATE INDEX idx_wnioski_etapy_wniosek ON wnioski_etapy(wniosek_id);
CREATE INDEX idx_wnioski_etapy_zatwierdzajacy ON wnioski_etapy(zatwierdzajacy_id, status);
