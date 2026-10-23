import { useId } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import useDialog from './useDialog'

/** Wspólne okno dialogowe: role="dialog" z nazwą z tytułu, pułapka fokusu,
 *  Escape zamyka (gdy closable), blokada przewijania strony, zwrot fokusu po
 *  zamknięciu (ui/useDialog). Biały nagłówek z tytułem i przyciskiem „Zamknij”,
 *  opcjonalna stopka. Pole z atrybutem data-autofocus dostaje fokus na starcie.
 *  `onSubmit` — treść i stopka owinięte w <form> (Enter zatwierdza).
 *  Renderowane przez portal w <body> (v3.10) — okno otwierane z wiersza tabeli
 *  nie trafia do <tr> (poprawny DOM i kontekst dla czytników ekranu). */
export default function Modal({ title, onClose, children, footer, width = 560, closable = true,
                                describedBy, onSubmit, className = '' }) {
  const titleId = useId()
  const ref = useDialog({ onClose, closable })
  const Wrap = onSubmit ? 'form' : 'div'
  const dialog = (
    <div className="modal-overlay" role="presentation"
         onMouseDown={e => { if (closable && e.target === e.currentTarget) onClose?.() }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={describedBy}
           tabIndex={-1} className={`ui-modal ${className}`.trim()} style={{ maxWidth: width }}>
        <div className="ui-modal__header">
          <h2 id={titleId} className="ui-modal__title">{title}</h2>
          {closable && (
            <button type="button" className="ui-modal__close" aria-label="Zamknij" onClick={onClose}>
              <X size={18} aria-hidden="true" />
            </button>
          )}
        </div>
        <Wrap className="ui-modal__content" onSubmit={onSubmit}>
          <div className="ui-modal__body">{children}</div>
          {footer && <div className="ui-modal__footer">{footer}</div>}
        </Wrap>
      </div>
    </div>
  )
  if (typeof document === 'undefined' || !document.body) return dialog
  return createPortal(dialog, document.body)
}
