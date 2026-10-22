import { useEffect, useId, useRef } from 'react'
import { X } from 'lucide-react'

/** Wspólne okno dialogowe: role="dialog", Escape zamyka, fokus na oknie,
 *  biały nagłówek z tytułem i przyciskiem „Zamknij”, opcjonalna stopka. */
export default function Modal({ title, onClose, children, footer, width = 560, closable = true }) {
  const titleId = useId()
  const ref = useRef(null)
  useEffect(() => {
    const prev = document.activeElement
    ref.current?.focus()
    return () => prev?.focus?.()
  }, [])
  return (
    <div className="modal-overlay" role="presentation"
         onMouseDown={e => { if (closable && e.target === e.currentTarget) onClose?.() }}>
      <div ref={ref} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}
           className="ui-modal" style={{ maxWidth: width }}
           onKeyDown={e => { if (closable && e.key === 'Escape') { e.stopPropagation(); onClose?.() } }}>
        <div className="ui-modal__header">
          <h2 id={titleId} className="ui-modal__title">{title}</h2>
          {closable && (
            <button type="button" className="ui-modal__close" aria-label="Zamknij" onClick={onClose}>
              <X size={18} aria-hidden="true" />
            </button>
          )}
        </div>
        <div className="ui-modal__body">{children}</div>
        {footer && <div className="ui-modal__footer">{footer}</div>}
      </div>
    </div>
  )
}
