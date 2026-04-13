-- Migration 006: NIS2 registers - incidents

CREATE TABLE rejestr_incydentow (
  id                  SERIAL PRIMARY KEY,
  tenant_id           INT          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  tytul               VARCHAR(300) NOT NULL,
  opis                TEXT,
  typ                 VARCHAR(50)  NOT NULL DEFAULT 'INNE'
                      CHECK (typ IN ('NIEAUTORYZOWANY_DOSTEP','NADUZYCIE_UPRAWNIEN','INNE')),
  poziom              VARCHAR(20)  NOT NULL DEFAULT 'SREDNI'
                      CHECK (poziom IN ('NISKI','SREDNI','WYSOKI','KRYTYCZNY')),
  status              VARCHAR(20)  NOT NULL DEFAULT 'OTWARTY'
                      CHECK (status IN ('OTWARTY','W_TRAKCIE','ZAMKNIETY')),
  zglaszajacy_id      INT          NOT NULL REFERENCES uzytkownicy(id) ON DELETE RESTRICT,
  data_zgloszenia     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  data_zamkniecia     TIMESTAMPTZ,
  dzialania_naprawcze TEXT,
  dotyczy_nis2        BOOLEAN      NOT NULL DEFAULT FALSE
);

-- Indexes
CREATE INDEX idx_incydenty_tenant ON rejestr_incydentow(tenant_id);
CREATE INDEX idx_incydenty_status ON rejestr_incydentow(status);
CREATE INDEX idx_incydenty_data ON rejestr_incydentow(data_zgloszenia);
