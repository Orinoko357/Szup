/**
 * Przenoszenie fokusu po akcjach, które usuwają z ekranu kliknięty element
 * (WCAG 2.4.3) — np. wysłany wiersz znika z listy, karta błędu znika po
 * „Spróbuj ponownie”, usunięta komórka / grupa. Bez tego fokus spada na <body>
 * i użytkownik klawiatury / czytnika ekranu traci miejsce na stronie.
 *
 *  focusTarget(t)      — ustaw fokus na elemencie (ref, element albo selektor CSS).
 *                        Element nieinteraktywny (h1, h2, region) dostaje tabIndex=-1.
 *  focusIfLost(t)      — j.w., ale dopiero w następnej klatce i tylko wtedy, gdy
 *                        fokus faktycznie zgubiono (jest na <body> / odpiętym węźle).
 *  PAGE_HEADING        — domyślny cel: nagłówek h1 bieżącej strony.
 */
export const PAGE_HEADING = 'main h1, h1'

function resolve(t) {
  if (!t) return null
  if (typeof t === 'string') return document.querySelector(t)
  if (typeof t === 'function') return resolve(t())
  if ('current' in t) return t.current
  return t
}

export function focusTarget(t) {
  if (typeof document === 'undefined') return false
  const el = resolve(t)
  if (!el || !el.isConnected || typeof el.focus !== 'function') return false
  if (!el.hasAttribute('tabindex') && el.tabIndex < 0) el.setAttribute('tabindex', '-1')
  el.focus({ preventScroll: false })
  return document.activeElement === el
}

export function focusLost() {
  const a = document.activeElement
  return !a || a === document.body || a === document.documentElement || !a.isConnected
}

export function focusIfLost(t, fallback = PAGE_HEADING) {
  if (typeof window === 'undefined') return
  const run = () => {
    if (!focusLost()) return
    if (!focusTarget(t) && fallback) focusTarget(fallback)
  }
  window.requestAnimationFrame(() => window.requestAnimationFrame(run))
}
