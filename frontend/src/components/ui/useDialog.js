import { useEffect, useRef, useState } from 'react'

/**
 * Wspólna obsługa okna dialogowego — używana przez ui/Modal oraz okna
 * o własnym układzie (np. PermissionGroupModal):
 *  - fokus początkowy: element z [data-autofocus] / autoFocus, inaczej samo okno,
 *  - pułapka fokusu (Tab / Shift+Tab nie wychodzą poza okno),
 *  - Escape zamyka (gdy closable), tylko najwyższe z nakładających się okien,
 *  - blokada przewijania dokumentu pod oknem,
 *  - po zamknięciu fokus wraca na element, który okno otworzył.
 * Zwraca ref do podpięcia pod element z role="dialog" (powinien mieć tabIndex={-1}).
 */
const FOCUSABLE = [
  'a[href]', 'area[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])', 'textarea:not([disabled])', 'iframe', 'summary',
  '[tabindex]:not([tabindex="-1"])', '[contenteditable="true"]',
].join(',')

const stack = []          // otwarte okna (najwyższe na końcu)
let scrollLocks = 0

/** Blokada przewijania `body` z licznikiem (szuflada menu + okna). */
export function lockScroll() {
  scrollLocks += 1
  if (scrollLocks === 1) document.body.classList.add('is-scroll-locked')
  let released = false
  return () => {
    if (released) return
    released = true
    scrollLocks = Math.max(0, scrollLocks - 1)
    if (scrollLocks === 0) document.body.classList.remove('is-scroll-locked')
  }
}

export function focusableIn(root) {
  if (!root) return []
  return Array.from(root.querySelectorAll(FOCUSABLE))
    .filter(el => el.getClientRects().length > 0 && !el.closest('[inert]'))
}

export default function useDialog({ onClose, closable = true } = {}) {
  const ref = useRef(null)
  // Najnowsze wartości bez ponownego montowania efektu.
  const opts = useRef({ onClose, closable })
  opts.current = { onClose, closable }
  // Element, który otworzył okno — zapamiętany już przy PIERWSZYM renderze.
  // W efekcie byłoby za późno: React wykonuje `autoFocus` w fazie commit, przed
  // efektami, więc document.activeElement wskazywałby już przycisk w oknie
  // (po zamknięciu nieistniejący) i fokus lądowałby na <body>.
  const [opener] = useState(() => (typeof document !== 'undefined' ? document.activeElement : null))

  useEffect(() => {
    const node = ref.current
    const prev = opener
    const token = {}
    stack.push(token)
    const unlock = lockScroll()

    if (node && !node.contains(document.activeElement)) {
      const auto = node.querySelector('[data-autofocus]')
      ;(auto || node).focus({ preventScroll: true })
    }

    function onKey(e) {
      if (stack[stack.length - 1] !== token || !ref.current) return
      if (e.key === 'Escape') {
        if (opts.current.closable) { e.stopPropagation(); e.preventDefault(); opts.current.onClose?.() }
        return
      }
      if (e.key !== 'Tab') return
      const items = focusableIn(ref.current)
      if (items.length === 0) { e.preventDefault(); ref.current.focus(); return }
      const first = items[0]
      const last = items[items.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === first || !ref.current.contains(active))) {
        e.preventDefault(); last.focus()
      } else if (!e.shiftKey && (active === last || !ref.current.contains(active))) {
        e.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', onKey)

    return () => {
      document.removeEventListener('keydown', onKey)
      const i = stack.indexOf(token)
      if (i >= 0) stack.splice(i, 1)
      unlock()
      if (prev && prev !== document.body && prev.isConnected && typeof prev.focus === 'function') {
        prev.focus({ preventScroll: true })
      }
    }
  }, [])

  return ref
}
