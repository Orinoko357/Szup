import { useEffect, useRef, useState } from 'react'
import { RefreshCw, UserPen } from 'lucide-react'
import { listNameChanges, resolveNameChange, errorMessage } from '../api'
import { fmtDate } from '../serverTime'
import { NAME_CHANGE_STATUS } from '../labels'
import { toast } from './ui/feedback'
import Segmented from './ui/Segmented'
import Modal from './ui/Modal'
import { LoadError } from './ui/LoadState'
import { focusIfLost } from './ui/focus'

// Wspólny słownik statusów zmian nazwiska (labels.js).
const STATUS = Object.fromEntries(Object.entries(NAME_CHANGE_STATUS).map(([k, v]) => [k, [v.badge, v.label]]))

/** Kolejka wniosków o zmianę nazwiska dla IT — realizacja lub odrzucenie. */
export default function NameChangeQueue({ onChanged } = {}) {
  const [filter, setFilter] = useState('pending')
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(null)     // wniosek do realizacji
  const [err, setErr] = useState(null)
  const listRef = useRef(null)

  async function load() {
    setLoading(true); setErr(null)
    try { setRows((await listNameChanges(filter === 'all' ? '' : filter)).data) }
    catch (ex) { setRows([]); setErr(errorMessage(ex, 'Nie udało się pobrać zgłoszeń')) }
    finally { setLoading(false) }
  }
  // Po rozpatrzeniu wiersz znika z listy „Oczekujące” (razem z przyciskiem
  // „Rozpatrz”, na który wraca fokus z okna) — fokus na region listy.
  async function afterResolve() {
    await load()
    focusIfLost(listRef)
  }
  // load zależy wyłącznie od `filter` — efekt celowo bez `load` w zależnościach.
  useEffect(() => { load() }, [filter])

  return (
    <>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <Segmented ariaLabel="Filtr zgłoszeń" value={filter} onChange={setFilter}
                   options={[{ value: 'pending', label: 'Oczekujące' }, { value: 'all', label: 'Wszystkie' }]} />
        <button className="btn btn--ghost btn--sm" style={{ marginLeft: 'auto' }}
                onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Odśwież
        </button>
      </div>
      <section ref={listRef} tabIndex={-1} aria-label="Zgłoszenia zmiany nazwiska" className="card"
               style={{ padding: 0, overflowX: 'auto' }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 18 }}>Ładowanie…</div>
        ) : err ? (
          <LoadError message={err} onRetry={load} busy={loading} focusAfter={listRef} />
        ) : rows.length === 0 ? (
          <div style={{ padding: 18 }}>
            <div style={{ fontWeight: 700 }}>{filter === 'pending' ? 'Brak zgłoszeń do rozpatrzenia.' : 'Brak zgłoszeń.'}</div>
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 4 }}>
              Pracownicy zgłaszają zmianę nazwiska w „Moich uprawnieniach”.
            </div>
          </div>
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
                      <button type="button" className="btn btn--success btn--sm" onClick={() => setOpen(r)}
                              aria-label={`Rozpatrz zmianę nazwiska: ${r.username} → ${r.requested_full_name}`}>
                        <UserPen size={13} aria-hidden="true" /> Rozpatrz
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
      </section>

      {open && (
        <ResolveModal req={open} onClose={() => setOpen(null)}
                      onDone={() => { setOpen(null); afterResolve(); onChanged?.() }} />
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
      toast(action === 'apply'
        ? `Zmiana nazwiska rozpatrzona: ${req.requested_full_name}.`
        : `Odrzucono zgłoszenie zmiany nazwiska (${req.username}).`)
      onDone()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się rozpatrzyć zgłoszenia')); setBusy(false)
    }
  }

  const field = { minHeight: 44, padding: '0 12px', border: '1px solid var(--color-input-border)',
                  borderRadius: 8, font: 'inherit', fontSize: 14, fontWeight: 400,
                  background: 'var(--color-card)', color: 'var(--color-text)' }
  const lbl = { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 700 }
  const btn = { minHeight: 44, fontSize: 14, padding: '0 16px', borderRadius: 8 }
  // Wspólne ui/Modal (pułapka fokusu, Escape, zwrot fokusu, blokada przewijania).
  return (
    <Modal title={`Zmiana nazwiska — ${req.username}`} onClose={onClose} closable={!busy} width={520}
           footer={<>
             <button type="button" className="btn btn--ghost" style={btn} onClick={onClose} disabled={busy}>Anuluj</button>
             <button type="button" className="btn btn--danger" style={btn} onClick={() => act('reject')} disabled={busy}>
               Odrzuć
             </button>
             <button type="button" className="btn btn--success" style={btn} onClick={() => act('apply')} disabled={busy}>
               {busy ? 'Zapisywanie…' : 'Zmień nazwisko'}
             </button>
           </>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {err && <div className="alert alert--error" role="alert">{err}</div>}
        <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: '90px 1fr', gap: '6px 12px',
                     padding: '12px 14px', borderRadius: 8, background: 'var(--bg-secondary)', fontSize: 14 }}>
          <dt style={{ color: 'var(--color-text-muted)' }}>Obecnie:</dt>
          <dd style={{ margin: 0, fontWeight: 600 }}>{req.current_full_name || '—'}</dd>
          <dt style={{ color: 'var(--color-text-muted)' }}>Nowe:</dt>
          <dd style={{ margin: 0, fontWeight: 800, color: 'var(--color-heading)' }}>{req.requested_full_name}</dd>
        </dl>

        <label style={{ display: 'flex', alignItems: 'center', gap: 10, minHeight: 44, fontSize: 14, cursor: 'pointer' }}>
          <input type="checkbox" checked={changeLogin} onChange={e => setChangeLogin(e.target.checked)}
                 style={{ width: 18, height: 18, margin: 0, accentColor: 'var(--color-selected)' }} />
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
      </div>
    </Modal>
  )
}
