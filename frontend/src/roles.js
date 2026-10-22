// Role zalogowanego użytkownika (z sesji w localStorage). Zawiera role
// efektywne — np. „hr” doklejone przez backend członkom komórki kadrowej.
export function getUserRoles() {
  try {
    const u = JSON.parse(localStorage.getItem('szup_user') || '{}')
    return Array.isArray(u.roles) ? u.roles : (u.role ? [u.role] : [])
  } catch { return [] }
}

/** Dane zalogowanego użytkownika z sesji (username, full_name, roles…). */
export function getCurrentUser() {
  try { return JSON.parse(localStorage.getItem('szup_user') || '{}') || {} } catch { return {} }
}

export const hasAnyRole = (roles, wanted) => wanted.some(r => roles.includes(r))

/** Zaktualizuj dane sesji (scalenie z zapisanymi) i powiadom App o zmianie
 *  (zdarzenie „szup:user” — przerysowanie tras, belki i strażników ról). */
export function updateCurrentUser(patch) {
  try {
    const next = { ...getCurrentUser(), ...patch }
    localStorage.setItem('szup_user', JSON.stringify(next))
  } catch { /* zablokowany storage — zostaje stan z pamięci strony */ }
  window.dispatchEvent(new Event('szup:user'))
}

/** Wyczyść sesję (token + dane użytkownika). Jedno miejsce dla wylogowania,
 *  wygaśnięcia sesji (401), bezczynności i zmiany hasła. */
export function clearSession() {
  try {
    localStorage.removeItem('szup_token')
    localStorage.removeItem('szup_user')
  } catch { /* zablokowany storage — nic do czyszczenia */ }
}
