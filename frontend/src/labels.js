import { serverNow } from './serverTime'

// v3.1 — JEDEN słownik etykiet dla całej aplikacji (statusy, kroki, rodzaje,
// istotność, role). Wcześniej ten sam status miał różne nazwy na różnych
// ekranach („Oczekuje na IT” / „Realizacja IT” / „Do realizacji”).

export const REQUEST_STATUS = {
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

export const KIND_LABEL = { grant: 'Zatrudnienie', revoke: 'Odejście', change: 'Zmiana' }
export const kindLabel = (k) => KIND_LABEL[k || 'grant'] || k

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
