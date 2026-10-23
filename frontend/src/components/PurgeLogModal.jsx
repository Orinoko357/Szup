import { useId, useState } from 'react'
import { Trash2 } from 'lucide-react'
import Modal from './ui/Modal'
import { toast } from './ui/feedback'
import { errorMessage } from '../api'

const CONFIRM_WORD = 'USUŃ'
const MIN_REASON = 10

/** Liczba usuniętych wpisów z odpowiedzi backendu (nazwa pola bywa różna). */
function deletedCount(data) {
  if (!data || typeof data !== 'object') return 0
  for (const k of ['deleted', 'deleted_count', 'purged', 'count', 'removed']) {
    if (typeof data[k] === 'number') return data[k]
  }
  return 0
}

/**
 * Superadmin: czyszczenie dziennika (zdarzeń / bezpieczeństwa). Tryb „starsze
 * niż data” albo „wszystko”, obowiązkowy powód (≥ 10 znaków), hasło i wpisanie
 * słowa USUŃ. `purge(data)` — funkcja API (purgeAudit / purgeSecurity).
 * Samo czyszczenie zostaje zapisane w dzienniku i nie da się go usunąć.
 */
export default function PurgeLogModal({ title, what, purge, onClose, onDone }) {
  const fid = useId()
  const [mode, setMode]         = useState('before')
  const [before, setBefore]     = useState('')
  const [reason, setReason]     = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [busy, setBusy]         = useState(false)
  const [err, setErr]           = useState(null)

  const reasonOk = reason.trim().length >= MIN_REASON
  const canSubmit = !busy && reasonOk && password.length > 0
    && confirm.trim() === CONFIRM_WORD && (mode === 'all' || !!before)

  async function submit(e) {
    e?.preventDefault()
    if (!canSubmit) return
    setBusy(true); setErr(null)
    try {
      const r = await purge({
        password, reason: reason.trim(), mode,
        before: mode === 'before' ? before : null,   // data ISO (RRRR-MM-DD)
      })
      toast(`Usunięto ${deletedCount(r.data)} wpisów`)
      onDone?.()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się wyczyścić wpisów'))
      setBusy(false)
    }
  }

  return (
    <Modal title={title} onClose={onClose} closable={!busy} width={560} onSubmit={submit}
           describedBy={`${fid}-note`}
           footer={<>
             <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>Anuluj</button>
             <button type="submit" className="btn btn--danger" disabled={!canSubmit}>
               <Trash2 size={14} aria-hidden="true" /> {busy ? 'Usuwanie…' : 'Usuń wpisy'}
             </button>
           </>}>
      <div id={`${fid}-note`} className="alert alert--warning" style={{ marginTop: 0 }}>
        Operacja jest nieodwracalna. Samo czyszczenie zostanie zapisane
        w dzienniku (kto, kiedy, powód, zakres) — tego wpisu nie da się usunąć.
      </div>

      <fieldset className="form-group" style={{ border: 0, padding: 0, margin: '0 0 12px' }}>
        <legend className="form-label">Zakres — {what}</legend>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer', minHeight: 32 }}>
          <input type="radio" name={`${fid}-mode`} value="before" checked={mode === 'before'}
                 onChange={() => setMode('before')} />
          Starsze niż data
          <input type="date" className="form-control" style={{ maxWidth: 180 }}
                 aria-label="Usuń wpisy starsze niż" value={before} disabled={mode !== 'before'}
                 onChange={e => setBefore(e.target.value)} required={mode === 'before'} />
        </label>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer', minHeight: 32 }}>
          <input type="radio" name={`${fid}-mode`} value="all" checked={mode === 'all'}
                 onChange={() => setMode('all')} />
          Wszystko
        </label>
      </fieldset>

      <div className="form-group">
        <label className="form-label" htmlFor={`${fid}-reason`}>Powód *</label>
        <textarea id={`${fid}-reason`} className="form-control" rows={3} required data-autofocus
                  value={reason} onChange={e => setReason(e.target.value)}
                  placeholder="np. upływ okresu retencji zgodnie z polityką…" />
        <div className="form-hint">
          Co najmniej {MIN_REASON} znaków{reason && !reasonOk ? ` (brakuje ${MIN_REASON - reason.trim().length})` : ''}.
        </div>
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor={`${fid}-pw`}>Twoje hasło *</label>
        <input id={`${fid}-pw`} className="form-control" type="password" required
               autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} />
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor={`${fid}-confirm`}>
          Wpisz <strong>{CONFIRM_WORD}</strong>, aby potwierdzić *
        </label>
        <input id={`${fid}-confirm`} className="form-control" required autoComplete="off"
               value={confirm} onChange={e => setConfirm(e.target.value)} />
      </div>
      {err && <div className="alert alert--error" role="alert">{err}</div>}
    </Modal>
  )
}
