import { useEffect, useState } from 'react'
import { UserPen, X, Check } from 'lucide-react'
import { myNameChanges, createNameChange } from '../api'
import { fmtDate } from '../serverTime'

const STATUS = {
  pending:  ['badge--warning', 'oczekuje na IT'],
  done:     ['badge--success', 'zrealizowany'],
  rejected: ['badge--error', 'odrzucony'],
}

/**
 * Samoobsługowe zgłoszenie zmiany nazwiska (pracownik → IT). Widoczne w
 * „Moich uprawnieniach", bo dostępne dla każdego zalogowanego. Trafia wprost
 * do IT — bez akceptacji kierownika.
 */
export default function MyNameChanges() {
  const [rows, setRows] = useState([])
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  const currentName = (() => {
    try {
      const u = JSON.parse(localStorage.getItem('szup_user') || '{}')
      return u.full_name || u.username || ''
    } catch { return '' }
  })()

  async function load() {
    try { setRows((await myNameChanges()).data) } catch { /* ignore */ }
  }
  useEffect(() => { load() }, [])

  const hasPending = rows.some(r => r.status === 'pending')

  async function submit() {
    if (name.trim().length < 3) { setErr('Podaj nowe imię i nazwisko.'); return }
    setBusy(true); setErr(null)
    try {
      await createNameChange({ requested_full_name: name.trim() })
      setOpen(false); setName('')
      load()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się wysłać zgłoszenia')
    } finally { setBusy(false) }
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <UserPen size={16} style={{ color: 'var(--color-gold)' }} />
        <div style={{ fontWeight: 600 }}>Zmiana nazwiska</div>
        <div style={{ fontSize: 12.5, color: 'var(--color-text-muted)' }}>
          Obecnie: <strong style={{ color: 'var(--color-text)' }}>{currentName}</strong>
        </div>
        <button className="btn btn--action btn--sm" style={{ marginLeft: 'auto' }}
                disabled={hasPending}
                onClick={() => { setName(currentName); setOpen(true) }}
                title={hasPending ? 'Masz już oczekujące zgłoszenie' : ''}>
          <UserPen size={13} /> Zgłoś zmianę nazwiska
        </button>
      </div>

      {rows.length > 0 && (
        <table className="data-table" style={{ marginTop: 12 }}>
          <thead>
            <tr><th>Zgłoszono</th><th>Nowe imię i nazwisko</th><th>Status</th><th>Uwagi IT</th></tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id}>
                <td style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{fmtDate(r.created_at)}</td>
                <td>{r.requested_full_name}</td>
                <td>
                  <span className={`badge ${STATUS[r.status]?.[0] || 'badge--neutral'}`}>
                    {STATUS[r.status]?.[1] || r.status}
                  </span>
                  {r.username_changed && (
                    <span className="badge badge--info" style={{ fontSize: 9, marginLeft: 6 }}
                          title={`Login zmieniony: ${r.old_username} → ${r.new_username}`}>
                      login: {r.new_username}
                    </span>
                  )}
                </td>
                <td style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{r.it_comment || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {open && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setOpen(false)}>
          <div className="modal" style={{ maxWidth: 520, width: '92vw' }}>
            <div className="modal__header">
              <div><UserPen size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} /> Zgłoszenie zmiany nazwiska</div>
              <button className="btn btn--ghost btn--sm" onClick={() => setOpen(false)}><X size={14} /></button>
            </div>
            <div className="modal__body">
              {err && <div className="alert alert--error mb-4">{err}</div>}
              <div className="form-group">
                <label className="form-label">Nowe imię i nazwisko *</label>
                <input className="form-control" autoFocus value={name}
                       onChange={e => setName(e.target.value)}
                       placeholder="np. Joanna Nowak" />
              </div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                Zgłoszenie trafia bezpośrednio do IT. Zmianę nazwiska wprowadzi
                pracownik IT; może przy okazji zmienić Twój login (wtedy trzeba
                zalogować się nowym loginem).
              </div>
            </div>
            <div className="modal__footer" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn btn--ghost btn--sm" onClick={() => setOpen(false)} disabled={busy}>Anuluj</button>
              <button className="btn btn--primary btn--sm" onClick={submit} disabled={busy}>
                <Check size={13} /> {busy ? 'Wysyłanie…' : 'Wyślij zgłoszenie'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
