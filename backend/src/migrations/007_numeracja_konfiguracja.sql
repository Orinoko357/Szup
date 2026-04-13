-- Migration 007: Numbering and configuration updates (already created in 001, just indexes)

-- Add indexes for better query performance on numbering
CREATE INDEX IF NOT EXISTS idx_konfiguracja_numeracji_id ON konfiguracja_numeracji(id);

-- Platform config defaults
INSERT INTO konfiguracja_platformy (klucz, wartosc, opis) VALUES
  ('app_name', 'System Zarządzania Uprawnieniami', 'Nazwa aplikacji'),
  ('app_version', '1.0.0', 'Wersja aplikacji'),
  ('nis2_enabled', 'true', 'Włączenie funkcji NIS2'),
  ('max_failed_logins', '5', 'Maksymalna liczba nieudanych logowań'),
  ('lockout_minutes', '15', 'Czas blokady konta w minutach'),
  ('session_timeout_hours', '8', 'Czas wygaśnięcia sesji w godzinach')
ON CONFLICT (klucz) DO NOTHING;
