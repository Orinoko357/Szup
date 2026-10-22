import { useEffect, useRef, useState } from 'react'
import { CheckCircle, AlertTriangle, Info, X } from 'lucide-react'

/**
 * Wspólne powiadomienia i okna dialogowe (v3.1) — zamiast systemowych
 * alert / confirm / prompt. Wywoływane z dowolnego miejsca (także spoza
 * komponentów), np.:
 *   toast('Zapisano')                         // tone: success|error|info|warning
 *   if (await confirmDialog({ title, message, confirmLabel, danger })) …
 *   const txt = await promptDialog({ title, message, label, requiredText })
 * <FeedbackHost /> montujemy raz (main.jsx).
 */
let _push = null      // (toast) => void
let _open = null      // (dialog) => void

export function toast(message, opts = {}) {
  const t = { id: Math.random().toString(36).slice(2), message, tone: opts.tone || 'success',
              timeout: opts.timeout ?? (opts.tone === 'error' ? 7000 : 4000) }
  if (_push) _push(t)
  else window.alert(message)   // awaryjnie, gdyby host nie był zamontowany
}

export function confirmDialog({ title = 'Potwierdź', message = '', confirmLabel = 'Potwierdź',
                                cancelLabel = 'Anuluj', danger = false } = {}) {
  return new Promise(resolve => {
    if (!_open) { resolve(window.confirm(message || title)); return }
    _open({ kind: 'confirm', title, message, confirmLabel, cancelLabel, danger, resolve })
  })
}

/** Zwraca wpisany tekst albo null (Anuluj). `requiredText` — przycisk aktywny
 *  dopiero po wpisaniu dokładnie tego tekstu (np. „POTWIERDZAM”). */
export function promptDialog({ title = 'Podaj wartość', message = '', label = '', placeholder = '',
                               defaultValue = '', requiredText = null, type = 'text', multiline = false,
                               confirmLabel = 'Zatwierdź', cancelLabel = 'Anuluj', danger = false } = {}) {
  return new Promise(resolve => {
    if (!_open) { resolve(window.prompt(message || title, defaultValue)); return }
    _open({ kind: 'prompt', title, message, label, placeholder, defaultValue, requiredText, type,
            multiline, confirmLabel, cancelLabel, danger, resolve })
  })
}

/** Wspólne potwierdzenie (zastępuje kopie `ask()` w stronach). Dla operacji
 *  niszczących/ryzykownych przekaż danger:true i konkretny czasownik
 *  (np. confirmLabel: 'Usuń konto', 'Włącz tryb testowy'). */
export function ask(message, { title = 'Potwierdź', confirmLabel = 'Potwierdź', danger = false } = {}) {
  return confirmDialog({ title, message, confirmLabel, danger })
}

const TONE = {
  success: { icon: CheckCircle,   fg: 'var(--color-success)', bg: 'var(--color-success-bg)' },
  error:   { icon: AlertTriangle, fg: 'var(--color-error)',   bg: 'var(--color-error-bg)' },
  warning: { icon: AlertTriangle, fg: 'var(--color-warning)', bg: 'var(--color-warning-bg)' },
  info:    { icon: Info,          fg: 'var(--color-info)',    bg: 'var(--color-info-bg)' },
}

export function FeedbackHost() {
  const [toasts, setToasts] = useState([])
  const [dialog, setDialog] = useState(null)
  const [value, setValue] = useState('')
  const inputRef = useRef(null)

  useEffect(() => {
    _push = (t) => {
      setToasts(list => [...list.slice(-3), t])
      setTimeout(() => setToasts(list => list.filter(x => x.id !== t.id)), t.timeout)
    }
    _open = (d) => { setValue(d.defaultValue || ''); setDialog(d) }
    return () => { _push = null; _open = null }
  }, [])

  useEffect(() => { if (dialog?.kind === 'prompt') setTimeout(() => inputRef.current?.focus(), 30) }, [dialog])

  function close(result) {
    dialog?.resolve(result)
    setDialog(null)
  }
  const canConfirm = dialog?.kind !== 'prompt' || !dialog.requiredText
    || value.trim() === dialog.requiredText

  return (
    <>
      <div aria-live="polite" style={{
        position: 'fixed', right: 16, bottom: 16, zIndex: 3000, display: 'flex',
        flexDirection: 'column', gap: 8, maxWidth: 'min(420px, calc(100vw - 32px))',
      }}>
        {toasts.map(t => {
          const T = TONE[t.tone] || TONE.info
          const Icon = T.icon
          return (
            <div key={t.id} role={t.tone === 'error' ? 'alert' : 'status'} style={{
              display: 'flex', alignItems: 'flex-start', gap: 10, padding: '12px 14px',
              background: 'var(--color-card)', color: 'var(--color-text)',
              border: '1px solid var(--color-border)', borderRadius: 10,
              boxShadow: '0 8px 24px rgba(13,20,36,.18)', fontSize: 14, lineHeight: 1.4,
            }}>
              <span aria-hidden="true" style={{ width: 26, height: 26, flexShrink: 0, borderRadius: '50%',
                display: 'grid', placeItems: 'center', background: T.bg, color: T.fg }}>
                <Icon size={15} />
              </span>
              <span style={{ flex: 1, whiteSpace: 'pre-line' }}>{t.message}</span>
              <button type="button" aria-label="Zamknij powiadomienie"
                      onClick={() => setToasts(list => list.filter(x => x.id !== t.id))}
                      style={{ border: 0, background: 'transparent', color: 'var(--color-text-muted)',
                               cursor: 'pointer', padding: 2 }}>
                <X size={14} />
              </button>
            </div>
          )
        })}
      </div>

      {dialog && (
        <div role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) close(dialog.kind === 'confirm' ? false : null) }}
             style={{ position: 'fixed', inset: 0, zIndex: 2900, background: 'rgba(13,20,36,.5)',
                      display: 'grid', placeItems: 'center', padding: 16 }}>
          <div role="dialog" aria-modal="true" aria-labelledby="fb-title"
               onKeyDown={e => { if (e.key === 'Escape') close(dialog.kind === 'confirm' ? false : null) }}
               style={{ width: '100%', maxWidth: 480, background: 'var(--color-card)', color: 'var(--color-text)',
                        border: '1px solid var(--color-border)', borderRadius: 10,
                        boxShadow: '0 16px 40px rgba(13,20,36,.3)' }}>
            <div style={{ padding: '18px 20px 0' }}>
              <h2 id="fb-title" style={{ margin: 0, fontSize: 18, fontWeight: 800,
                    color: dialog.danger ? 'var(--color-error)' : 'var(--color-heading)' }}>{dialog.title}</h2>
              {dialog.message && (
                <p style={{ margin: '8px 0 0', fontSize: 14, lineHeight: 1.5, whiteSpace: 'pre-line',
                            color: 'var(--color-text)' }}>{dialog.message}</p>
              )}
            </div>
            <form onSubmit={e => { e.preventDefault(); if (canConfirm) close(dialog.kind === 'confirm' ? true : value) }}>
              {dialog.kind === 'prompt' && (
                <div style={{ padding: '14px 20px 0' }}>
                  {dialog.label && <label htmlFor="fb-input" className="form-label">{dialog.label}</label>}
                  {dialog.multiline ? (
                    <textarea id="fb-input" ref={inputRef} className="form-control" rows={3}
                              placeholder={dialog.placeholder} value={value}
                              onChange={e => setValue(e.target.value)} />
                  ) : (
                    <input id="fb-input" ref={inputRef} className="form-control" type={dialog.type}
                           placeholder={dialog.placeholder || dialog.requiredText || ''} value={value}
                           autoComplete="off" onChange={e => setValue(e.target.value)} />
                  )}
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, flexWrap: 'wrap',
                            padding: '18px 20px 18px' }}>
                <button type="button" className="btn btn--ghost" autoFocus={dialog.kind === 'confirm'}
                        onClick={() => close(dialog.kind === 'confirm' ? false : null)}>{dialog.cancelLabel}</button>
                <button type="submit" disabled={!canConfirm}
                        className={`btn ${dialog.danger ? 'btn--danger' : 'btn--action'}`}>{dialog.confirmLabel}</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  )
}
