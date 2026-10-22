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
