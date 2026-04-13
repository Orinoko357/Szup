-- Migration 001: Core tables - tenants, users, auth

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Tenants (units)
CREATE TABLE tenants (
  id            SERIAL PRIMARY KEY,
  nazwa         VARCHAR(200) NOT NULL,
  skrot         VARCHAR(20)  NOT NULL UNIQUE,
  regon         VARCHAR(14),
  nip           VARCHAR(13),
  aktywny       BOOLEAN      NOT NULL DEFAULT TRUE,
  data_utworzenia TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  dni_do_przegladu INT        NOT NULL DEFAULT 365
);

-- Users
CREATE TABLE uzytkownicy (
  id            SERIAL PRIMARY KEY,
  tenant_id     INT REFERENCES tenants(id) ON DELETE SET NULL,
  username      VARCHAR(100) NOT NULL UNIQUE,
  imie          VARCHAR(100) NOT NULL,
  nazwisko      VARCHAR(100) NOT NULL,
  email         VARCHAR(200) NOT NULL UNIQUE,
  rola          VARCHAR(20)  NOT NULL CHECK (rola IN ('SUPERADMIN','IT_ADMIN','KADRY','KIEROWNIK','PRACOWNIK')),
  hash_hasla    TEXT,
  aktywny       BOOLEAN      NOT NULL DEFAULT TRUE,
  data_utworzenia TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ostatnie_logowanie TIMESTAMPTZ,
  wymagaj_zmiany_hasla BOOLEAN NOT NULL DEFAULT FALSE,
  nieudane_logowania INT NOT NULL DEFAULT 0,
  zablokowany_do TIMESTAMPTZ
);

-- Refresh tokens
CREATE TABLE refresh_tokens (
  id            SERIAL PRIMARY KEY,
  user_id       INT          NOT NULL REFERENCES uzytkownicy(id) ON DELETE CASCADE,
  token_hash    TEXT         NOT NULL UNIQUE,
  odwolany      BOOLEAN      NOT NULL DEFAULT FALSE,
  data_utworzenia TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  wygasa        TIMESTAMPTZ  NOT NULL
);

-- LDAP domains
CREATE TABLE ldap_domeny (
  id              SERIAL PRIMARY KEY,
  nazwa           VARCHAR(200) NOT NULL,
  domena          VARCHAR(200) NOT NULL,
  ldap_url        VARCHAR(500) NOT NULL,
  base_dn         TEXT         NOT NULL,
  bind_dn         TEXT         NOT NULL,
  bind_password_enc TEXT       NOT NULL,
  user_filter     TEXT         NOT NULL DEFAULT '(&(objectClass=user)(sAMAccountName=%s))',
  attr_email      VARCHAR(100) NOT NULL DEFAULT 'mail',
  attr_firstname  VARCHAR(100) NOT NULL DEFAULT 'givenName',
  attr_lastname   VARCHAR(100) NOT NULL DEFAULT 'sn',
  attr_username   VARCHAR(100) NOT NULL DEFAULT 'sAMAccountName',
  tls             BOOLEAN      NOT NULL DEFAULT FALSE,
  tls_ca_cert     TEXT,
  aktywna         BOOLEAN      NOT NULL DEFAULT TRUE,
  kolejnosc       INT          NOT NULL DEFAULT 0
);

-- Platform configuration
CREATE TABLE konfiguracja_platformy (
  id      SERIAL PRIMARY KEY,
  klucz   VARCHAR(200) NOT NULL UNIQUE,
  wartosc TEXT,
  opis    TEXT
);

-- Numbering configuration
CREATE TABLE konfiguracja_numeracji (
  id                  SERIAL PRIMARY KEY,
  format_szablonu     VARCHAR(200) NOT NULL DEFAULT '{PREFIX}.{SEQ}.{YEAR}',
  prefix              VARCHAR(50)  NOT NULL DEFAULT 'INF',
  szerokosc_sekwencji INT          NOT NULL DEFAULT 4,
  reset_co            VARCHAR(10)  NOT NULL DEFAULT 'ROK' CHECK (reset_co IN ('ROK','MIESIAC')),
  ostatni_numer       INT          NOT NULL DEFAULT 0,
  ostatni_reset       DATE         NOT NULL DEFAULT CURRENT_DATE
);

-- Notifications
CREATE TABLE powiadomienia (
  id              SERIAL PRIMARY KEY,
  user_id         INT          NOT NULL REFERENCES uzytkownicy(id) ON DELETE CASCADE,
  typ             VARCHAR(50)  NOT NULL,
  tresc           TEXT         NOT NULL,
  link            TEXT,
  przeczytane     BOOLEAN      NOT NULL DEFAULT FALSE,
  data_utworzenia TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_uzytkownicy_tenant ON uzytkownicy(tenant_id);
CREATE INDEX idx_uzytkownicy_rola ON uzytkownicy(rola);
CREATE INDEX idx_uzytkownicy_email ON uzytkownicy(email);
CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX idx_powiadomienia_user ON powiadomienia(user_id, przeczytane);

INSERT INTO konfiguracja_numeracji (format_szablonu, prefix, szerokosc_sekwencji, reset_co, ostatni_numer, ostatni_reset)
VALUES ('{PREFIX}.{SEQ}.{YEAR}', 'INF', 4, 'ROK', 0, CURRENT_DATE);
