/**
 * serverTime.js — czas zawsze z serwera, nie z przeglądarki.
 *
 * Problem: backend zwraca naiwne UTC (datetime.utcnow()), a przeglądarka
 * parsuje "2024-01-01T10:00:00" bez 'Z' jako czas LOKALNY — co daje błędne
 * wyniki na maszynach w strefach innych niż UTC.
 * Drugi problem: zegar klienta może być rozsynchronizowany z serwerem.
 *
 * API:
 *   syncServerTime()   — wywołaj raz po zalogowaniu; oblicza offset klient↔serwer
 *   serverNow()        — aktualna chwila wg serwera (używaj zamiast new Date())
 *   serverTs(str)      — parsuje timestamp z backendu jako UTC → Date
 *   fmtDate(str)       — dd.mm.rrrr
 *   fmtDateTime(str)   — dd.mm.rrrr, hh:mm:ss
 */

let _offsetMs = 0   // server_epoch_ms − client_epoch_ms

export async function syncServerTime() {
  try {
    const t0 = Date.now()
    const r  = await fetch('/api/auth/server-time')
    const t1 = Date.now()
    const { epoch_ms } = await r.json()
    // Przybliżenie czasu serwera w chwili odpowiedzi = punkt środkowy RTT
    _offsetMs = epoch_ms - Math.round((t0 + t1) / 2)
  } catch {
    _offsetMs = 0   // fallback — używaj zegara klienta
  }
}

/** Aktualny czas wg serwera. */
export function serverNow() {
  return new Date(Date.now() + _offsetMs)
}

/**
 * Parsuje timestamp z backendu jako UTC.
 * Backend zwraca naiwne UTC (bez 'Z') — dorzucamy 'Z' żeby
 * przeglądarka nie traktowała go jako czas lokalny.
 */
export function serverTs(ts) {
  if (!ts) return null
  const s = String(ts)
  return new Date(s.endsWith('Z') || /[+-]\d{2}:\d{2}$/.test(s) ? s : s + 'Z')
}

const OPT_DATE     = { day: '2-digit', month: '2-digit', year: 'numeric' }
const OPT_DATETIME = { day: '2-digit', month: '2-digit', year: 'numeric',
                       hour: '2-digit', minute: '2-digit', second: '2-digit' }

/** Formatuje datę jako dd.mm.rrrr */
export function fmtDate(ts) {
  const d = serverTs(ts)
  return d ? d.toLocaleDateString('pl-PL', OPT_DATE) : '—'
}

/** Formatuje datę i czas jako dd.mm.rrrr, hh:mm:ss */
export function fmtDateTime(ts) {
  const d = serverTs(ts)
  return d ? d.toLocaleString('pl-PL', OPT_DATETIME) : '—'
}

/** dd.mm.rrrr, hh:mm (bez sekund) — dla historii i pozycji wniosku. */
export function fmtDateTimeShort(ts) {
  const d = serverTs(ts)
  return d ? d.toLocaleString('pl-PL', { day: '2-digit', month: '2-digit', year: 'numeric',
                                          hour: '2-digit', minute: '2-digit' }) : ''
}
