import { useState } from 'react'
import { Trash2 } from 'lucide-react'
import Modal from './ui/Modal'
import Field from './ui/Field'
import { toast } from './ui/feedback'
import { errorMessage } from '../api'

/**
 * Okno usuwania wpisów logu (audit log / zdarzenia bezpieczeństwa).
 * modes: [{ value, label, hint, needsDate? }]; onDelete({ mode, before, password }) → { deleted, remaining }.
 * Wymaga hasła i wpisania „USUŃ”. Operacja jest nieodwracalna; jej ślad
 * (kto, kiedy, ile) zapisuje backend w audit logu.
 */
export default function DeleteLogsModal({ title, what, modes, onDelete, onClose, onDone }) {
  const [mode, setMode] = useState(modes[0].value)
  const [before, setBefore] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const cur = modes.find(m => m.value === mode)
  const ready = password && confirm.trim() === 'USUŃ' && (!cur?.needsDate || before)

  async function submit(e) {
    e.preventDefault()
    if (!ready) return
    setBusy(true); setErr(null)
    try {
      const r = await onDelete({ mode, before: before || null, password })
      toast(`Usunięto ${r.data.deleted} ${what}. Pozostało: ${r.data.remaining}.`)
      onDone?.()
      onClose()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się usunąć wpisów'))
      setBusy(false)
    }
  }

  return (
    <Modal title={title} onClose={onClose} width={520}
           footer={<>
             <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>Anuluj</button>
             <button type="submit" form="delete-logs-form" className="btn btn--danger" disabled={!ready || busy}>
               <Trash2 size={14} aria-hidden="true" /> {busy ? 'Usuwanie…' : 'Usuń trwale'}
             </button>
           </>}>
      <form id="delete-logs-form" onSubmit={submit}>
        <div className="alert alert--error" style={{ marginBottom: 16 }}>
          Operacja jest <strong>nieodwracalna</strong>. Usunięte wpisy znikną z systemu
          (także z eksportów). W logu zostanie wyłącznie informacja, kto i kiedy je usunął.
        </div>
        <fieldset style={{ border: 0, padding: 0, margin: '0 0 14px' }}>
          <legend className="form-label">Zakres</legend>
          {modes.map(m => (
            <label key={m.value} style={{ display: 'flex', gap: 10, alignItems: 'flex-start', padding: '6px 0', cursor: 'pointer' }}>
              <input type="radio" name="delete-mode" value={m.value} checked={mode === m.value}
                     onChange={() => setMode(m.value)} style={{ marginTop: 3 }} />
              <span>
                <span style={{ fontWeight: 700 }}>{m.label}</span>
                {m.hint && <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>{m.hint}</span>}
              </span>
            </label>
          ))}
        </fieldset>
        {cur?.needsDate && (
          <Field label="Usuń wpisy starsze niż" required>
            <input type="date" className="form-control" value={before} onChange={e => setBefore(e.target.value)} />
          </Field>
        )}
        <Field label="Twoje hasło" required hint="Konto domenowe — hasło do AD.">
          <input type="password" className="form-control" autoComplete="current-password"
                 value={password} onChange={e => setPassword(e.target.value)} />
        </Field>
        <Field label="Wpisz USUŃ, aby potwierdzić" required>
          <input className="form-control" autoComplete="off" placeholder="USUŃ"
                 value={confirm} onChange={e => setConfirm(e.target.value)} />
        </Field>
        {err && <div className="alert alert--error">{err}</div>}
      </form>
    </Modal>
  )
}
