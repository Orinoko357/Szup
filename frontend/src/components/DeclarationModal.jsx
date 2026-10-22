import { useEffect, useState } from 'react'
import { X, ShieldAlert } from 'lucide-react'
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

  const field = { minHeight: 44, boxSizing: 'border-box', padding: '0 12px', width: '100%',
                  border: '1px solid var(--color-input-border)', borderRadius: 8, font: 'inherit',
                  fontSize: 14, fontWeight: 400, letterSpacing: 0,
                  background: 'var(--color-card)', color: 'var(--color-text)' }
  const lbl = { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, fontWeight: 700,
                letterSpacing: '.07em', textTransform: 'uppercase', color: 'var(--color-text-muted)' }
  const btn = { minHeight: 44, fontSize: 14, padding: '0 16px', borderRadius: 8 }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div role="dialog" aria-modal="true" aria-labelledby="decl-title" style={{
        width: '92vw', maxWidth: 640, background: 'var(--color-card)', borderRadius: 12,
        overflow: 'hidden', boxShadow: '0 20px 50px rgba(0, 0, 0, 0.25)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '18px 22px',
                      borderBottom: '1px solid var(--color-border)' }}>
          <span aria-hidden="true" style={{ width: 38, height: 38, borderRadius: 10, background: '#FEF3DC',
                                            color: 'var(--color-gold-dark)', display: 'grid', placeItems: 'center' }}>
            <ShieldAlert size={20} />
          </span>
          <h2 id="decl-title" style={{ margin: 0, flex: 1, fontSize: 18, fontWeight: 800, color: 'var(--color-navy)' }}>
            Oświadczenie wnioskującego
          </h2>
          <button type="button" aria-label="Zamknij" onClick={onClose} disabled={busy}
                  style={{ width: 44, height: 44, display: 'grid', placeItems: 'center', border: 0,
                           borderRadius: 8, background: 'transparent', color: 'var(--color-text-muted)', cursor: 'pointer' }}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>

        <div style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 14,
                      maxHeight: '70vh', overflowY: 'auto' }}>
          <div tabIndex={0} style={{
            maxHeight: 240, overflowY: 'auto', fontSize: 14, lineHeight: 1.6, whiteSpace: 'pre-wrap',
            border: '1px solid var(--color-border)', borderRadius: 8,
            padding: '14px 16px', background: 'var(--bg-secondary)', color: 'var(--color-text)',
          }}>
            {loading ? 'Ładowanie treści…' : text}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 12 }}>
            <label style={lbl}>
              Imię i nazwisko *
              <input style={field} value={name} autoFocus required
                     onChange={e => setName(e.target.value)}
                     placeholder="np. Jan Kowalski" />
            </label>
            <label style={lbl}>
              Data *
              <input style={field} type="date" required
                     value={date} onChange={e => setDate(e.target.value)} />
            </label>
          </div>
          <p style={{ margin: 0, fontSize: 12, color: 'var(--color-text-muted)' }}>
            Wpisanie danych i zatwierdzenie jest równoznaczne ze złożeniem
            powyższego oświadczenia. Zostanie ono trwale zapisane i powiązane
            z wnioskiem oraz pracownikiem.
          </p>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 10, padding: '14px 22px',
                      borderTop: '1px solid var(--color-border)', background: 'var(--bg-secondary)' }}>
          <button type="button" className="btn btn--ghost" style={btn} onClick={onClose} disabled={busy}>
            Anuluj
          </button>
          <button type="button" className="btn btn--success" style={btn} disabled={!ready || busy}
                  onClick={() => onConfirm({
                    declared_by_name: name.trim(), declared_date: date.trim(),
                  })}>
            {busy ? 'Wysyłanie…' : 'Oświadczam i wysyłam'}
          </button>
        </div>
      </div>
    </div>
  )
}
