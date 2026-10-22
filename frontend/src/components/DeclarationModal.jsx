import { useEffect, useState } from 'react'
import { ShieldAlert } from 'lucide-react'
import { getDeclarationText } from '../api'
import { getCurrentUser } from '../roles'
import Modal from './ui/Modal'

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
/** Imię i nazwisko zalogowanego użytkownika (z sesji). */
function currentUserName() {
  const u = getCurrentUser()
  return u.full_name || u.username || ''
}

/** Dzisiejsza data LOKALNA w formacie RRRR-MM-DD (toISOString dawałby datę UTC —
 *  między północą a 1–2 w nocy wczorajszą). */
function localToday() {
  const d = new Date()
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export default function DeclarationModal({
  text: textProp, defaultName, busy = false, onConfirm, onClose,
}) {
  const [text, setText] = useState(textProp || '')
  const [loading, setLoading] = useState(!textProp)
  // Domyślnie podpisuje osoba, która wywołała okno — z możliwością poprawy.
  const [name, setName] = useState(defaultName || currentUserName())
  // Dziś, w formacie RRRR-MM-DD (wartość <input type="date">).
  const [date, setDate] = useState(localToday)

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

  const title = (
    <span style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <span aria-hidden="true" style={{ width: 38, height: 38, flex: 'none', borderRadius: 10, background: 'var(--color-warning-bg)',
                                        color: 'var(--color-gold-dark)', display: 'grid', placeItems: 'center' }}>
        <ShieldAlert size={20} />
      </span>
      Oświadczenie wnioskującego
    </span>
  )

  // Wspólne ui/Modal (pułapka fokusu, Escape, zwrot fokusu, blokada przewijania).
  return (
    <Modal title={title} onClose={onClose} closable={!busy} width={640} describedBy="decl-text"
           footer={<>
             <button type="button" className="btn btn--ghost" style={btn} onClick={onClose} disabled={busy}>
               Anuluj
             </button>
             <button type="button" className="btn btn--success" style={btn} disabled={!ready || busy}
                     onClick={() => onConfirm({
                       declared_by_name: name.trim(), declared_date: date.trim(),
                     })}>
               {busy ? 'Wysyłanie…' : 'Oświadczam i wysyłam'}
             </button>
           </>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div id="decl-text" tabIndex={0} aria-label="Treść oświadczenia" style={{
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
    </Modal>
  )
}
