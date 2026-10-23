import { AlertTriangle, RefreshCw } from 'lucide-react'

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
                            card = false, style }) {
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
        <button type="button" className="btn btn--ghost btn--sm" onClick={onRetry} disabled={busy}
                style={{ flexShrink: 0 }}>
          <RefreshCw size={14} aria-hidden="true" /> Spróbuj ponownie
        </button>
      )}
    </div>
  )
  return card ? <div className="card" style={{ padding: 0, overflow: 'hidden' }}>{body}</div> : body
}

export default LoadError
