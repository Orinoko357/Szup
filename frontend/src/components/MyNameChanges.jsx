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
    <section aria-label="Zmiana nazwiska" className="card" style={{ marginBottom: 18, padding: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '14px 18px',
                    borderBottom: rows.length > 0 ? '1px solid var(--color-border)' : 'none' }}>
        <span aria-hidden="true" style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--bg-secondary)',
                                          color: 'var(--color-navy)', display: 'grid', placeItems: 'center' }}>
          <UserPen size={16} />
        </span>
        <div style={{ flex: '1 1 240px' }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: 'var(--color-navy)' }}>Zmiana nazwiska</h2>
          <p style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--color-text-muted)' }}>
            Obecnie: <strong style={{ color: 'var(--color-text)' }}>{currentName}</strong>
          </p>
        </div>
        <button className="btn btn--ghost" style={{ minHeight: 44, fontSize: 14, fontWeight: 700, background: 'var(--color-card)' }}
                disabled={hasPending}
                onClick={() => { setName(currentName); setOpen(true) }}
                title={hasPending ? 'Masz już oczekujące zgłoszenie' : ''}>
          Zgłoś zmianę nazwiska
        </button>
      </div>

      {rows.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
        <table className="data-table" style={{ minWidth: 640 }}>
          <thead>
            <tr><th>Zgłoszono</th><th>Nowe imię i nazwisko</th><th>Status</th><th>Uwagi IT</th></tr>
          </thead>
          <tbody>
            {rows.map(r => (
              <tr key={r.id}>
                <td style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>{fmtDate(r.created_at)}</td>
                <td style={{ fontWeight: 700 }}>{r.requested_full_name}</td>
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
                <td style={{ color: 'var(--color-text-muted)' }}>{r.it_comment || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}

      {open && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setOpen(false)}>
          <div className="modal" style={{ maxWidth: 520, width: '92vw' }}>
            <div className="modal__header">
              <div><UserPen size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} /> Zgłoszenie zmiany nazwiska</div>
              <button className="btn btn--ghost btn--sm" aria-label="Zamknij" onClick={() => setOpen(false)}><X size={14} /></button>
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
    </section>
  )
}
