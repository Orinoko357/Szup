-- Migration 008: Audit log + final constraints + REVOKE

CREATE TABLE audit_log (
  id              BIGSERIAL    PRIMARY KEY,
  tenant_id       INT          REFERENCES tenants(id) ON DELETE SET NULL,
  user_id         INT          REFERENCES uzytkownicy(id) ON DELETE SET NULL,
  username        VARCHAR(100),
  rola            VARCHAR(20),
  akcja           VARCHAR(100) NOT NULL,
  tabela_docelowa VARCHAR(100),
  rekord_id       BIGINT,
  stare_dane      JSONB,
  nowe_dane       JSONB,
  ip_adres        INET,
  user_agent      TEXT,
  timestamp       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_log_tenant_ts ON audit_log(tenant_id, timestamp DESC);
CREATE INDEX idx_audit_log_tabela_rekord ON audit_log(tabela_docelowa, rekord_id);
CREATE INDEX idx_audit_log_user ON audit_log(user_id);
CREATE INDEX idx_audit_log_akcja ON audit_log(akcja);
CREATE INDEX idx_audit_log_ts ON audit_log(timestamp DESC);

-- Additional performance indexes
CREATE INDEX idx_wnioski_etapy_sched ON wnioski_etapy(status, data_przypisania, data_przypomnienia);
CREATE INDEX idx_uprawnienia_przeglad_sched ON uprawnienia(aktywne, data_ostatniego_przegladu, wymaga_przegladu);

-- REVOKE on audit_log: prevent app_user from modifying audit records
-- (Run as superuser/postgres after creating app_user)
-- REVOKE UPDATE, DELETE ON audit_log FROM app_user;

-- Create app_user if running as superuser
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    -- app_user will be created by the setup script
    NULL;
  END IF;
END$$;
