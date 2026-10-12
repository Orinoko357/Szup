import { useEffect, useState } from 'react'
import { X, Check, ShieldAlert } from 'lucide-react'
import { getDeclarationText } from '../api'

/**
 * Oświadczenie wnioskującego — pokazywane w chwili, gdy akcja kieruje wniosek
 * do realizacji IT i wniosek nadaje uprawnienia.
 *
 * Osoba potwierdza treść (RODO/NIS2/KSC), wpisując imię i nazwisko oraz datę.
 * Zwraca przez `onConfirm({ declared_by_name, declared_date })`. Backend jest
 * twardą bramką (428) — modal tylko zbiera podpis; jeśli się nie pokaże,
 * żądanie i tak zostanie odbite.
 *
 * `text` można podać z góry (np. z odpowiedzi 428); gdy brak — pobieramy
 * aktualną treść z `/settings/declaration-text`.
 */
/** Imię i nazwisko zalogowanego użytkownika (z tokena w localStorage). */
function currentUserName() {
  try {
    const u = JSON.parse(localStorage.getItem('szup_user') || '{}')
    return u.full_name || u.username || ''
  } catch { return '' }
}

export default function DeclarationModal({
  text: textProp, defaultName, busy = false, onConfirm, onClose,
}) {
  const [text, setText] = useState(textProp || '')
  const [loading, setLoading] = useState(!textProp)
  // Domyślnie podpisuje osoba, która wywołała okno — z możliwością poprawy.
  const [name, setName] = useState(defaultName || currentUserName())
  // Dziś, w formacie RRRR-MM-DD (wartość <input type="date">).
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))

  useEffect(() => {
    if (textProp) return
    let alive = true
    getDeclarationText()
      .then(r => { if (alive) setText(r.data.declaration_text || '') })
      .catch(() => { if (alive) setText('Nie udało się pobrać treści oświadczenia.') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [textProp])

  const ready = name.trim() && date.trim()

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 760, width: '92vw' }}>
        <div className="modal__header">
          <div>
            <ShieldAlert size={16} style={{ verticalAlign: 'middle', marginRight: 6, color: 'var(--color-gold)' }} />
            Oświadczenie wnioskującego
          </div>
          <button className="btn btn--ghost btn--sm" onClick={onClose} disabled={busy}>
            <X size={14} />
          </button>
        </div>

        <div className="modal__body" style={{ maxHeight: '70vh', overflowY: 'auto' }}>
          <div style={{
            fontSize: 12.5, lineHeight: 1.55, whiteSpace: 'pre-wrap',
            border: '1px solid var(--color-border)', borderRadius: 6,
            padding: '12px 14px', background: 'var(--bg-secondary)',
            color: 'var(--color-text)',
          }}>
            {loading ? 'Ładowanie treści…' : text}
          </div>

          <div className="form-row" style={{ marginTop: 14 }}>
            <div className="form-group" style={{ flex: 2 }}>
              <label className="form-label">Imię i nazwisko *</label>
              <input className="form-control" value={name} autoFocus
                     onChange={e => setName(e.target.value)}
                     placeholder="np. Jan Kowalski" />
            </div>
            <div className="form-group" style={{ flex: 1 }}>
              <label className="form-label">Data *</label>
              <input className="form-control" type="date"
                     value={date} onChange={e => setDate(e.target.value)} />
            </div>
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
            Wpisanie danych i zatwierdzenie jest równoznaczne ze złożeniem
            powyższego oświadczenia. Zostanie ono trwale zapisane i powiązane
            z wnioskiem oraz pracownikiem.
          </div>
        </div>

        <div className="modal__footer" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn--ghost btn--sm" onClick={onClose} disabled={busy}>
            Anuluj
          </button>
          <button className="btn btn--primary btn--sm" disabled={!ready || busy}
                  onClick={() => onConfirm({
                    declared_by_name: name.trim(), declared_date: date.trim(),
                  })}>
            <Check size={13} /> {busy ? 'Wysyłanie…' : 'Oświadczam i wysyłam'}
          </button>
        </div>
      </div>
    </div>
  )
}
