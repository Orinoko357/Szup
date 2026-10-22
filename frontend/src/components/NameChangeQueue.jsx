import { useEffect, useState } from 'react'
import { RefreshCw, UserPen, X } from 'lucide-react'
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
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        {/* Filtr jako przełącznik segmentowy (wg projektu). */}
        <div role="group" aria-label="Filtr" style={{ display: 'inline-flex', padding: 3, gap: 2, borderRadius: 8,
                                                      background: 'var(--color-neutral-bg)' }}>
          {[['pending', 'Oczekujące'], ['all', 'Wszystkie']].map(([v, l]) => (
            <button key={v} type="button" aria-pressed={filter === v} onClick={() => setFilter(v)}
                    style={{
                      minHeight: 36, padding: '0 14px', border: 0, borderRadius: 6, cursor: 'pointer',
                      font: 'inherit', fontSize: 13, fontWeight: filter === v ? 700 : 600,
                      background: filter === v ? 'var(--color-card)' : 'transparent',
                      color: filter === v ? 'var(--color-navy)' : 'var(--color-text-muted)',
                    }}>{l}</button>
          ))}
        </div>
        <button className="btn btn--ghost btn--sm" style={{ marginLeft: 'auto' }}
                onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Odśwież
        </button>
      </div>
      <div className="card" style={{ padding: 0, overflowX: 'auto' }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 18 }}>Ładowanie…</div>
        ) : rows.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 18 }}>Brak wniosków.</div>
        ) : (
          <table className="data-table" style={{ minWidth: 860 }}>
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
                      <span className="badge badge--info" style={{ fontSize: 11, marginLeft: 6 }}>
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

  const field = { minHeight: 44, padding: '0 12px', border: '1px solid var(--color-input-border)',
                  borderRadius: 8, font: 'inherit', fontSize: 14, fontWeight: 400,
                  background: 'var(--color-card)', color: 'var(--color-text)' }
  const lbl = { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 700 }
  const btn = { minHeight: 44, fontSize: 14, padding: '0 16px', borderRadius: 8 }
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <section role="dialog" aria-modal="true" aria-label="Zmiana nazwiska" style={{
        position: 'relative', width: '92vw', maxWidth: 520, background: 'var(--color-card)',
        borderRadius: 10, boxShadow: '0 20px 50px rgba(15, 23, 42, .3)', overflow: 'hidden',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 10px 14px 22px',
                      borderBottom: '1px solid var(--color-border)' }}>
          <h2 style={{ margin: 0, flex: 1, fontSize: 17, fontWeight: 800, color: 'var(--color-heading)' }}>
            Zmiana nazwiska — {req.username}
          </h2>
          <button type="button" aria-label="Zamknij" onClick={onClose}
                  style={{ width: 44, height: 44, display: 'grid', placeItems: 'center', border: 0,
                           borderRadius: 8, background: 'transparent', color: 'var(--color-text-muted)', cursor: 'pointer' }}>
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <div style={{ padding: '18px 22px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {err && <div className="alert alert--error">{err}</div>}
          <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: '90px 1fr', gap: '6px 12px',
                       padding: '12px 14px', borderRadius: 8, background: 'var(--bg-secondary)', fontSize: 14 }}>
            <dt style={{ color: 'var(--color-text-muted)' }}>Obecnie:</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>{req.current_full_name || '—'}</dd>
            <dt style={{ color: 'var(--color-text-muted)' }}>Nowe:</dt>
            <dd style={{ margin: 0, fontWeight: 800, color: 'var(--color-heading)' }}>{req.requested_full_name}</dd>
          </dl>

          <label style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 44, fontSize: 14, cursor: 'pointer' }}>
            <input type="checkbox" checked={changeLogin} onChange={e => setChangeLogin(e.target.checked)}
                   style={{ width: 18, height: 18, margin: 0, accentColor: 'var(--color-navy)' }} />
            Zmień też login użytkownika (opcjonalnie)
          </label>
          {changeLogin && (
            <label style={lbl}>
              Nowy login
              <input style={field} value={newLogin}
                     onChange={e => setNewLogin(e.target.value)} placeholder="np. jnowak" />
              <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-error-text)' }}>
                Po zmianie loginu pracownik będzie się logował nowym loginem
                (bieżąca sesja zostanie wylogowana).
              </span>
            </label>
          )}

          <label style={lbl}>
            Komentarz (opcjonalnie)
            <textarea rows={3} style={{ ...field, minHeight: 0, padding: '10px 12px', resize: 'vertical' }}
                      value={comment} onChange={e => setComment(e.target.value)} />
          </label>

          <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'flex-end', gap: 8,
                        borderTop: '1px solid var(--color-border)', marginTop: 4, paddingTop: 14 }}>
            <button type="button" className="btn btn--ghost" style={btn} onClick={onClose} disabled={busy}>Anuluj</button>
            <button type="button" className="btn btn--danger" style={btn} onClick={() => act('reject')} disabled={busy}>
              Odrzuć
            </button>
            <button type="button" className="btn btn--success" style={btn} onClick={() => act('apply')} disabled={busy}>
              {busy ? 'Zapisywanie…' : 'Zmień nazwisko'}
            </button>
          </div>
        </div>
      </section>
    </div>
  )
}
