import { useEffect, useRef } from 'react'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { focusIfLost, PAGE_HEADING } from './focus'

/**
 * Wspólne komunikaty błędów (v3.8).
 *
 *  <ErrorAlert>{err}</ErrorAlert>
 *    — błąd po akcji użytkownika (zapis, wysyłka). role="alert", więc czytnik
 *      ekranu ogłasza go od razu, choć fokus zostaje na klikniętym przycisku.
 *      Bez treści nic nie renderuje — można pisać <ErrorAlert>{err}</ErrorAlert>
 *      zamiast {err && …}.
 *
 *  <LoadError message={err} onRetry={load} />
 *    — nie udało się wczytać listy/strony. Pokazujemy ją ZAMIAST stanu pustej
 *      listy („Brak …”), który po błędzie wprowadzałby w błąd (np. zachęcał do
 *      utworzenia duplikatu). Z przyciskiem „Spróbuj ponownie”.
 *      v3.10: gdy po „Spróbuj ponownie” karta znika (razem z przyciskiem, na
 *      którym był fokus), fokus przechodzi na `focusAfter` (ref / element /
 *      selektor) — domyślnie h1 strony — zamiast spaść na <body> (WCAG 2.4.3).
 */
export function ErrorAlert({ children, className = '', style, id }) {
  if (children == null || children === false || children === '') return null
  return (
    <div id={id} role="alert" className={`alert alert--error ${className}`.trim()} style={style}>
      {children}
    </div>
  )
}

export function LoadError({ message, onRetry, busy = false, title = 'Nie udało się wczytać danych',
                            card = false, style, focusAfter = PAGE_HEADING }) {
  const retried = useRef(false)
  const target = useRef(focusAfter)
  target.current = focusAfter
  useEffect(() => () => {
    if (retried.current) focusIfLost(target.current)
  }, [])
  // Ponowienie nieudane (karta została, przycisk był chwilowo wyłączony) —
  // fokus wraca na „Spróbuj ponownie”.
  const btn = useRef(null)
  useEffect(() => {
    if (!busy && retried.current) focusIfLost(btn, null)
  }, [busy])
  function retry() {
    retried.current = true
    onRetry?.()
  }
  const body = (
    <div role="alert" className="load-error" style={style}>
      <span aria-hidden="true" className="load-error__icon"><AlertTriangle size={18} /></span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="load-error__title">{title}</div>
        {message && <div className="load-error__msg">{message}</div>}
        <div className="load-error__hint">
          Lista może być niepełna — nie wprowadzaj zmian na jej podstawie, dopóki się nie wczyta.
        </div>
      </div>
      {onRetry && (
        <button ref={btn} type="button" className="btn btn--ghost btn--sm" onClick={retry} disabled={busy}
                style={{ flexShrink: 0 }}>
          <RefreshCw size={14} aria-hidden="true" /> Spróbuj ponownie
        </button>
      )}
    </div>
  )
  return card ? <div className="card" style={{ padding: 0, overflow: 'hidden' }}>{body}</div> : body
}

export default LoadError
