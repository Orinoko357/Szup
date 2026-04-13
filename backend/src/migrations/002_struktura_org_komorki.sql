-- Migration 002: Organizational structure

CREATE TABLE struktura_org (
  id            SERIAL PRIMARY KEY,
  tenant_id     INT          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  nazwa         VARCHAR(200) NOT NULL,
  typ_wezla     VARCHAR(50)  NOT NULL DEFAULT 'WYDZIAL',
  nadrzedny_id  INT REFERENCES struktura_org(id) ON DELETE SET NULL,
  kolejnosc     INT          NOT NULL DEFAULT 0,
  aktywna       BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE komorki_org (
  id              SERIAL PRIMARY KEY,
  tenant_id       INT          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  struktura_org_id INT         REFERENCES struktura_org(id) ON DELETE SET NULL,
  nazwa           VARCHAR(200) NOT NULL,
  kod             VARCHAR(50),
  aktywna         BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE pracownicy (
  id                SERIAL PRIMARY KEY,
  uzytkownik_id     INT          NOT NULL UNIQUE REFERENCES uzytkownicy(id) ON DELETE CASCADE,
  tenant_id         INT          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  komorka_id        INT          REFERENCES komorki_org(id) ON DELETE SET NULL,
  stanowisko        VARCHAR(200),
  data_zatrudnienia DATE,
  data_zwolnienia   DATE,
  aktywny           BOOLEAN      NOT NULL DEFAULT TRUE,
  przelozony_id     INT          REFERENCES pracownicy(id) ON DELETE SET NULL
);

-- IT systems and dictionaries
CREATE TABLE systemy_it (
  id                  SERIAL PRIMARY KEY,
  tenant_id           INT          REFERENCES tenants(id) ON DELETE CASCADE,
  nazwa               VARCHAR(200) NOT NULL,
  opis                TEXT,
  wlasciciel          VARCHAR(200),
  poziom_krytycznosci VARCHAR(20)  NOT NULL DEFAULT 'SREDNI'
                      CHECK (poziom_krytycznosci IN ('NISKI','SREDNI','WYSOKI','KRYTYCZNY')),
  aktywny             BOOLEAN      NOT NULL DEFAULT TRUE,
  data_dodania        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  dodany_przez        INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL
);

CREATE TABLE modul_systemu (
  id        SERIAL PRIMARY KEY,
  system_id INT          NOT NULL REFERENCES systemy_it(id) ON DELETE CASCADE,
  nazwa     VARCHAR(200) NOT NULL,
  opis      TEXT,
  aktywny   BOOLEAN      NOT NULL DEFAULT TRUE
);

CREATE TABLE zakres_uprawnien (
  id              SERIAL PRIMARY KEY,
  system_id       INT          NOT NULL REFERENCES systemy_it(id) ON DELETE CASCADE,
  modul_id        INT          REFERENCES modul_systemu(id) ON DELETE CASCADE,
  nazwa           VARCHAR(200) NOT NULL,
  opis            TEXT,
  uprzywilejowany BOOLEAN      NOT NULL DEFAULT FALSE
);

-- Indexes
CREATE INDEX idx_struktura_org_tenant ON struktura_org(tenant_id);
CREATE INDEX idx_struktura_org_nadrzedny ON struktura_org(nadrzedny_id);
CREATE INDEX idx_komorki_org_tenant ON komorki_org(tenant_id);
CREATE INDEX idx_komorki_org_struktura ON komorki_org(struktura_org_id);
CREATE INDEX idx_pracownicy_tenant ON pracownicy(tenant_id);
CREATE INDEX idx_pracownicy_komorka ON pracownicy(komorka_id);
CREATE INDEX idx_pracownicy_przelozony ON pracownicy(przelozony_id);
CREATE INDEX idx_systemy_it_tenant ON systemy_it(tenant_id);
CREATE INDEX idx_modul_system ON modul_systemu(system_id);
CREATE INDEX idx_zakres_system ON zakres_uprawnien(system_id);
