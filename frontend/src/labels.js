import { serverNow } from './serverTime'

// v3.1 — JEDEN słownik etykiet dla całej aplikacji (statusy, kroki, rodzaje,
// istotność, role). Wcześniej ten sam status miał różne nazwy na różnych
// ekranach („Oczekuje na IT” / „Realizacja IT” / „Do realizacji”).

const REQUEST_STATUS = {
  pending_selection: { label: 'Wybór uprawnień',       badge: 'badge--warning' },
  pending_manager:   { label: 'Akceptacja kierownika', badge: 'badge--warning' },
  pending_it:        { label: 'Realizacja IT',         badge: 'badge--info' },
  completed:         { label: 'Zrealizowany',          badge: 'badge--success' },
  rejected:          { label: 'Odrzucony',             badge: 'badge--error' },
}
export const statusLabel = (s) => REQUEST_STATUS[s]?.label || s || '—'
export const statusBadge = (s) => REQUEST_STATUS[s]?.badge || 'badge--neutral'

export const NODE_LABEL = {
  select_permissions:     'Wybór uprawnień',
  manager_approve:        'Akceptacja kierownika',
  higher_manager_approve: 'Akceptacja wyższa',
  it_execute:             'Realizacja IT',
}
export const nodeLabel = (n, fallback) => NODE_LABEL[n] || fallback || n || '—'

// Kto wykonuje dany krok obiegu (historia wniosku, „krok pominięty”).
// Jedna nazwa wyższego stopnia: krok „Akceptacja wyższa”, wykonawca
// „kierownik nadrzędny” (nie „kierownik wyższego rzędu”).
export const NODE_WHO = {
  select_permissions:     'Kierownik',
  manager_approve:        'Kierownik',
  higher_manager_approve: 'Kierownik nadrzędny',
  it_execute:             'IT',
}

// Kroki obiegu wykonywane przez kierownika (wybór uprawnień / akceptacje).
export const MANAGER_NODES = ['select_permissions', 'manager_approve', 'higher_manager_approve']

const KIND_LABEL = { grant: 'Zatrudnienie', revoke: 'Odejście', change: 'Zmiana' }
// v3.11: odebranie wygenerowane przez system (usunięcie grupy, likwidacja komórki)
// to nie „Odejście” — backend oznacza je flagą is_system.
export const kindLabel = (k, isSystem = false) =>
  (isSystem && k === 'revoke') ? 'Odebranie systemowe' : (KIND_LABEL[k || 'grant'] || k)

export const NAME_CHANGE_STATUS = {
  pending:  { label: 'Oczekuje na IT', badge: 'badge--warning' },
  done:     { label: 'Zrealizowana',   badge: 'badge--success' },
  rejected: { label: 'Odrzucona',      badge: 'badge--error' },
}

export const SEVERITY_LABEL = { low: 'niska', medium: 'średnia', high: 'wysoka', critical: 'krytyczna' }

export const ROLE_META = {
  superadmin: { label: 'superadmin',    badge: 'badge--error' },
  admin:      { label: 'administrator', badge: 'badge--warning' },
  it_staff:   { label: 'IT',            badge: 'badge--success' },
  manager:    { label: 'kierownik',     badge: 'badge--info' },
  hr:         { label: 'kadry',         badge: 'badge--info' },
  viewer:     { label: 'przeglądający', badge: 'badge--neutral' },
}
export const ROLE_LABEL = Object.fromEntries(Object.entries(ROLE_META).map(([k, v]) => [k, v.label]))

// Kolor odznaki kroku obiegu (pulpit, listy).
export const NODE_TONE = {
  select_permissions:     'badge--warning',
  manager_approve:        'badge--warning',
  higher_manager_approve: 'badge--warning',
  it_execute:             'badge--info',
}

/** „X dni” od daty (Date) — do „czeka od”. */
export function daysSince(date, now = serverNow()) {
  if (!date) return null
  return Math.max(0, Math.floor((now - date) / 86400000))
}
export function waitText(days) {
  if (days == null) return '—'
  if (days === 0) return 'dziś'
  return days === 1 ? '1 dzień' : `${days} dni`
}

/** Polska odmiana liczebnika: plural(1,'wpis','wpisy','wpisów') → „wpis”,
 *  2–4 (poza 12–14) → „wpisy”, reszta → „wpisów”. Zwraca samą formę. */
export function plural(n, one, few, many) {
  const a = Math.abs(Number(n) || 0)
  if (a === 1) return one
  const d = a % 10, h = a % 100
  return d >= 2 && d <= 4 && (h < 12 || h > 14) ? few : many
}
/** „N formy” — liczba z odmienionym rzeczownikiem. */
export const countLabel = (n, one, few, many) => `${n} ${plural(n, one, few, many)}`

// Typy zdarzeń bezpieczeństwa (backend: services/security_events.emit) —
// czytelna nazwa; nieznany typ pokazujemy surowo (kod zostaje w podpowiedzi).
export const SECURITY_EVENT_LABEL = {
  'auth.lockout':                         'Blokada konta po nieudanych logowaniach',
  'auth.domain_login_local_account':      'Logowanie domenowe na konto lokalne',
  'auth.test_mode_login':                 'Logowanie w trybie testowym',
  'auth.test_mode_blocked':               'Zablokowane logowanie w trybie testowym',
  'auth.test_mode_privileged_blocked':    'Zablokowane logowanie konta uprzywilejowanego (tryb testowy)',
  'sso.foreign_realm':                    'SSO: konto z obcej domeny',
  'sso.no_proxy_secret':                  'SSO: brak sekretu serwera pośredniczącego',
  'sso.untrusted_proxy':                  'SSO: niezaufany serwer pośredniczący',
  'ldap.infra_error':                     'Błąd połączenia z AD / LDAP',
  'user.roles_granted':                   'Nadanie ról uprzywilejowanych',
  'user.password_reset':                  'Reset hasła użytkownika',
  'user.login_changed':                   'Zmiana loginu użytkownika',
  'superadmin.confirm_denied':            'Nieudane potwierdzenie hasłem (superadmin)',
  'structure.post_assigned':              'Przypisanie stanowiska w strukturze',
  'department.force_deleted':             'Usunięcie komórki przez superadmina',
  'permission_group.deleted_held':        'Usunięcie przyznanej grupy uprawnień',
  'request.worker_linked':                'Dowiązanie konta do wniosku',
  'request_type.template_changed':        'Zmiana szablonu obiegu typu wniosku',
  'workflow_template.graph_changed':      'Zmiana schematu obiegu',
  'audit.triggers_missing':               'Brak zabezpieczeń dziennika (triggery)',
  'audit.purged':                         'Wyczyszczono dziennik zdarzeń',
  'security.purged':                      'Wyczyszczono zdarzenia bezpieczeństwa',
  'audit.purge_failed':                   'Nieudane czyszczenie dziennika zdarzeń',
  'security.purge_failed':                'Nieudane czyszczenie zdarzeń bezpieczeństwa',
  'settings.test_mode':                   'Zmiana trybu testowego',
  'settings.factory_reset':               'Przywrócenie ustawień fabrycznych',
  'settings.factory_reset_denied':        'Odmowa przywrócenia ustawień fabrycznych',
  'settings.ldap':                        'Zmiana ustawień LDAP',
  'settings.smtp':                        'Zmiana ustawień poczty',
  'settings.sso':                         'Zmiana ustawień SSO',
}
export const securityEventLabel = (t) => SECURITY_EVENT_LABEL[t] || t || '—'
