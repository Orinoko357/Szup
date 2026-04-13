-- Migration 003: Workflow engine

CREATE TABLE workflow_szablony (
  id              SERIAL PRIMARY KEY,
  tenant_id       INT          NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  nazwa           VARCHAR(200) NOT NULL,
  opis            TEXT,
  aktywny         BOOLEAN      NOT NULL DEFAULT TRUE,
  data_utworzenia TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  utworzony_przez INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL
);

CREATE TABLE workflow_poziomy (
  id                      SERIAL PRIMARY KEY,
  szablon_id              INT          NOT NULL REFERENCES workflow_szablony(id) ON DELETE CASCADE,
  kolejnosc               INT          NOT NULL,
  nazwa                   VARCHAR(200),
  zatwierdzajacy_id       INT          REFERENCES pracownicy(id) ON DELETE SET NULL,
  opcjonalny              BOOLEAN      NOT NULL DEFAULT FALSE,
  opis_warunku_pominiecia TEXT,
  przypomnienie_dni       INT          NOT NULL DEFAULT 3,
  eskalacja_dni           INT          NOT NULL DEFAULT 7,
  UNIQUE(szablon_id, kolejnosc)
);

CREATE TABLE workflow_przypisania (
  id          SERIAL PRIMARY KEY,
  szablon_id  INT          NOT NULL REFERENCES workflow_szablony(id) ON DELETE CASCADE,
  typ         VARCHAR(20)  NOT NULL CHECK (typ IN ('KOMORKA','TENANT_DEFAULT')),
  komorka_id  INT          REFERENCES komorki_org(id) ON DELETE CASCADE,
  tenant_id   INT          REFERENCES tenants(id) ON DELETE CASCADE,
  CONSTRAINT uniq_komorka_przypisanie UNIQUE (komorka_id),
  CONSTRAINT uniq_tenant_default EXCLUDE USING btree (
    tenant_id WITH =
  ) WHERE (typ = 'TENANT_DEFAULT')
);

-- Indexes
CREATE INDEX idx_workflow_szablony_tenant ON workflow_szablony(tenant_id);
CREATE INDEX idx_workflow_poziomy_szablon ON workflow_poziomy(szablon_id);
CREATE INDEX idx_workflow_przypisania_komorka ON workflow_przypisania(komorka_id);
CREATE INDEX idx_workflow_przypisania_tenant ON workflow_przypisania(tenant_id);
