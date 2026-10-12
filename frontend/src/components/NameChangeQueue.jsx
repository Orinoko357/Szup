import { useEffect, useState } from 'react'
import { RefreshCw, UserPen, Check, X } from 'lucide-react'
import { listNameChanges, resolveNameChange } from '../api'
import { fmtDate } from '../serverTime'

const STATUS = {
  pending:  ['badge--warning', 'oczekuje'],
  done:     ['badge--success', 'zrealizowany'],
  rejected: ['badge--error', 'odrzucony'],
}

/** Kolejka wniosków o zmianę nazwiska dla IT — realizacja lub odrzucenie. */
export default function NameChangeQueue() {
  const [filter, setFilter] = useState('pending')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(null)     // wniosek do realizacji

  async function load() {
    setLoading(true)
    try { setRows((await listNameChanges(filter === 'all' ? '' : filter)).data) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [filter])  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <div className="tabs" style={{ marginTop: 0 }}>
        {[['pending', 'Oczekujące'], ['all', 'Wszystkie']].map(([v, l]) => (
          <button key={v} className={`tab-btn${filter === v ? ' active' : ''}`}
                  onClick={() => setFilter(v)}>{l}</button>
        ))}
        <button className="btn btn--ghost btn--sm" style={{ marginLeft: 'auto' }}
                onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Odśwież
        </button>
      </div>
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>Ładowanie…</div>
        ) : rows.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>Brak wniosków.</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr><th>Zgłoszono</th><th>Pracownik (login)</th><th>Obecne</th>
                <th>Nowe imię i nazwisko</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {rows.map(r => (
                <tr key={r.id}>
                  <td style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{fmtDate(r.created_at)}</td>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.username}</td>
                  <td>{r.current_full_name || '—'}</td>
                  <td style={{ fontWeight: 600 }}>{r.requested_full_name}</td>
                  <td>
                    <span className={`badge ${STATUS[r.status]?.[0] || 'badge--neutral'}`}>
                      {STATUS[r.status]?.[1] || r.status}
                    </span>
                    {r.username_changed && (
                      <span className="badge badge--info" style={{ fontSize: 9, marginLeft: 6 }}>
                        login → {r.new_username}
                      </span>
                    )}
                  </td>
                  <td>
                    {r.status === 'pending' ? (
                      <button className="btn btn--success btn--sm" onClick={() => setOpen(r)}>
                        <UserPen size={13} /> Rozpatrz
                      </button>
                    ) : (
                      <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        {r.resolved_by_name || ''}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {open && (
        <ResolveModal req={open} onClose={() => setOpen(null)}
                      onDone={() => { setOpen(null); load() }} />
      )}
    </>
  )
}


function ResolveModal({ req, onClose, onDone }) {
  const [changeLogin, setChangeLogin] = useState(false)
  const [newLogin, setNewLogin] = useState(req.username || '')
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  async function act(action) {
    setBusy(true); setErr(null)
    try {
      await resolveNameChange(req.id, {
        action,
        comment: comment.trim() || null,
        new_username: action === 'apply' && changeLogin ? newLogin.trim() : null,
      })
      onDone()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd operacji'); setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 560, width: '92vw' }}>
        <div className="modal__header">
          <div><UserPen size={16} style={{ verticalAlign: 'middle', marginRight: 6 }} /> Zmiana nazwiska — {req.username}</div>
          <button className="btn btn--ghost btn--sm" onClick={onClose}><X size={14} /></button>
        </div>
        <div className="modal__body">
          {err && <div className="alert alert--error mb-4">{err}</div>}
          <div style={{ fontSize: 13, marginBottom: 12 }}>
            <div><strong>Obecnie:</strong> {req.current_full_name || '—'}</div>
            <div><strong>Nowe:</strong> {req.requested_full_name}</div>
          </div>

          <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer', marginBottom: 8 }}>
            <input type="checkbox" checked={changeLogin} onChange={e => setChangeLogin(e.target.checked)} />
            Zmień też login użytkownika (opcjonalnie)
          </label>
          {changeLogin && (
            <div className="form-group">
              <label className="form-label">Nowy login</label>
              <input className="form-control" value={newLogin}
                     onChange={e => setNewLogin(e.target.value)} placeholder="np. jnowak" />
              <div style={{ fontSize: 11, color: 'var(--color-error)', marginTop: 4 }}>
                Po zmianie loginu pracownik będzie się logował nowym loginem
                (bieżąca sesja zostanie wylogowana).
              </div>
            </div>
          )}

          <div className="form-group">
            <label className="form-label">Komentarz (opcjonalnie)</label>
            <input className="form-control" value={comment} onChange={e => setComment(e.target.value)} />
          </div>
        </div>
        <div className="modal__footer" style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn--ghost btn--sm" onClick={onClose} disabled={busy}>Anuluj</button>
          <button className="btn btn--danger btn--sm" onClick={() => act('reject')} disabled={busy}>
            <X size={13} /> Odrzuć
          </button>
          <button className="btn btn--success btn--sm" onClick={() => act('apply')} disabled={busy}>
            <Check size={13} /> {busy ? 'Zapisywanie…' : 'Zmień nazwisko'}
          </button>
        </div>
      </div>
    </div>
  )
}
