import { useEffect, useState } from 'react'
import { UserPen, Check } from 'lucide-react'
import { myNameChanges, createNameChange, errorMessage } from '../api'
import { getCurrentUser } from '../roles'
import Modal from './ui/Modal'
import { fmtDate } from '../serverTime'
import { NAME_CHANGE_STATUS } from '../labels'
import { toast } from './ui/feedback'

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

  const me = getCurrentUser()
  const currentName = me.full_name || me.username || ''
  const [loadErr, setLoadErr] = useState(null)

  async function load() {
    setLoadErr(null)
    try { setRows((await myNameChanges()).data) }
    catch (ex) { setLoadErr(errorMessage(ex, 'Nie udało się wczytać zgłoszeń zmiany nazwiska')) }
  }
  useEffect(() => { load() }, [])

  const hasPending = rows.some(r => r.status === 'pending')

  async function submit() {
    if (name.trim().length < 3) { setErr('Podaj nowe imię i nazwisko.'); return }
    setBusy(true); setErr(null)
    try {
      await createNameChange({ requested_full_name: name.trim() })
      setOpen(false); setName('')
      toast('Wysłano zgłoszenie zmiany nazwiska do IT.')
      load()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się wysłać zgłoszenia'))
    } finally { setBusy(false) }
  }

  return (
    <section aria-label="Zmiana nazwiska" className="card" style={{ marginBottom: 18, padding: 0, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '14px 18px',
                    borderBottom: rows.length > 0 ? '1px solid var(--color-border)' : 'none' }}>
        <span aria-hidden="true" style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--bg-secondary)',
                                          color: 'var(--color-heading)', display: 'grid', placeItems: 'center' }}>
          <UserPen size={16} />
        </span>
        <div style={{ flex: '1 1 240px' }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: 'var(--color-heading)' }}>Zmiana nazwiska</h2>
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

      {loadErr && (
        <div className="alert alert--error" role="alert" style={{ margin: 14 }}>{loadErr}</div>
      )}
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
                  <span className={`badge ${NAME_CHANGE_STATUS[r.status]?.badge || 'badge--neutral'}`}>
                    {NAME_CHANGE_STATUS[r.status]?.label || r.status}
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
        <Modal title="Zgłoszenie zmiany nazwiska" onClose={() => !busy && setOpen(false)} width={520}
               footer={<>
                 <button className="btn btn--ghost" onClick={() => setOpen(false)} disabled={busy}>Anuluj</button>
                 <button className="btn btn--action" onClick={submit} disabled={busy}>
                   <Check size={14} /> {busy ? 'Wysyłanie…' : 'Wyślij zgłoszenie'}
                 </button>
               </>}>
          {err && <div className="alert alert--error mb-4">{err}</div>}
          <div className="form-group">
            <label className="form-label" htmlFor="nc-new-name">Nowe imię i nazwisko *</label>
            <input id="nc-new-name" className="form-control" autoFocus value={name}
                   onChange={e => setName(e.target.value)}
                   placeholder="np. Joanna Nowak" />
          </div>
          <div className="form-hint">
            Zgłoszenie trafia bezpośrednio do IT. Zmianę nazwiska wprowadzi
            pracownik IT; może przy okazji zmienić Twój login (wtedy trzeba
            zalogować się nowym loginem).
          </div>
        </Modal>
      )}
    </section>
  )
}
