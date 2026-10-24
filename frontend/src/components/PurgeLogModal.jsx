import { useId, useRef, useState } from 'react'
import { Trash2 } from 'lucide-react'
import Modal from './ui/Modal'
import { toast } from './ui/feedback'
import { errorMessage } from '../api'
import { serverNow, fmtDateTime, serverTs } from '../serverTime'
import { countLabel } from '../labels'

const CONFIRM_WORD = 'USUŃ'
const MIN_REASON = 10
// Okres przechowywania dziennika (NIS2 / KSC): wpisów z ostatnich 24 miesięcy nie
// można usunąć — backend odrzuca `before` późniejsze niż dziś − 24 miesiące (400).
const RETENTION_MONTHS = 24

/** Liczba usuniętych wpisów z odpowiedzi backendu (nazwa pola bywa różna). */
function deletedCount(data) {
  if (!data || typeof data !== 'object') return 0
  for (const k of ['deleted', 'deleted_count', 'purged', 'count', 'removed']) {
    if (typeof data[k] === 'number') return data[k]
  }
  return 0
}

/** RRRR-MM-DD → dd.mm.rrrr (bez przeliczania stref). */
const fmtDay = (iso) => (iso ? iso.split('-').reverse().join('.') : '—')

/** Data RRRR-MM-DD (lokalna) = dziś − RETENTION_MONTHS miesięcy. */
function retentionCutoff() {
  const d = serverNow()
  const day = d.getDate()
  d.setDate(1)
  d.setMonth(d.getMonth() - RETENTION_MONTHS)
  // 29–31 dnia miesiąca: ostatni dzień miesiąca docelowego, nie „przeskok” dalej.
  const last = new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate()
  d.setDate(Math.min(day, last))
  const pad = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/**
 * Superadmin: czyszczenie dziennika (zdarzeń / bezpieczeństwa). Usuwa WYŁĄCZNIE
 * wpisy starsze niż wybrana data, a ta nie może być późniejsza niż
 * dziś − 24 miesiące (okres przechowywania). Obowiązkowy powód (≥ 10 znaków),
 * hasło i wpisanie słowa USUŃ. `purge(data)` — funkcja API (purgeAudit /
 * purgeSecurity). `stats` (opcjonalnie) — { total_entries, oldest } z auditStats.
 * Samo czyszczenie zostaje zapisane w dzienniku i nie da się go usunąć.
 */
export default function PurgeLogModal({ title, what, purge, onClose, onDone, stats = null }) {
  const fid = useId()
  const cutoff = retentionCutoff()
  const [before, setBefore]     = useState(cutoff)
  const [reason, setReason]     = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [busy, setBusy]         = useState(false)
  const [err, setErr]           = useState(null)
  const pwRef = useRef(null)

  const reasonOk  = reason.trim().length >= MIN_REASON
  const dateOk    = !!before && before <= cutoff
  const confirmOk = confirm.trim() === CONFIRM_WORD
  // Brakujące warunki — podpowiedź pod przyciskiem (aria-describedby), żeby
  // nieaktywny przycisk nie był zagadką (np. „usun” zamiast „USUŃ”).
  const missing = []
  if (!before) missing.push('wybierz datę')
  else if (!dateOk) missing.push(`data nie może być późniejsza niż ${fmtDay(cutoff)}`)
  if (!reasonOk) missing.push(`podaj powód (co najmniej ${MIN_REASON} znaków)`)
  if (!password) missing.push('wpisz swoje hasło')
  if (!confirmOk) missing.push(`wpisz dokładnie ${CONFIRM_WORD} (wielkimi literami, z „Ś”)`)
  const canSubmit = !busy && missing.length === 0

  const oldestTs = stats?.oldest ? serverTs(stats.oldest) : null
  const nothingOld = oldestTs && dateOk && oldestTs >= new Date(`${before}T00:00:00`)

  async function submit(e) {
    e?.preventDefault()
    if (!canSubmit) return
    setBusy(true); setErr(null)
    try {
      const r = await purge({
        password, reason: reason.trim(), mode: 'before',
        before,   // data ISO (RRRR-MM-DD), ≤ dziś − 24 miesiące
      })
      const n = deletedCount(r.data)
      toast(n > 0 ? `Usunięto ${countLabel(n, 'wpis', 'wpisy', 'wpisów')}` : 'Brak wpisów do usunięcia')
      onDone?.()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się wyczyścić wpisów'))
      setBusy(false)
      // Fokus zostaje w oknie: na polu hasła (najczęstszy błąd), zaznaczonym do poprawy.
      requestAnimationFrame(() => { pwRef.current?.focus(); pwRef.current?.select() })
    }
  }

  const hintId = `${fid}-missing`
  return (
    <Modal title={title} onClose={onClose} closable={!busy} width={560} onSubmit={submit}
           describedBy={`${fid}-note`}
           footer={<>
             <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>Anuluj</button>
             {/* aria-disabled zamiast disabled: przycisk nie gubi fokusu podczas wysyłki ani po błędzie. */}
             <button type="submit" className="btn btn--danger" aria-disabled={!canSubmit}
                     aria-describedby={missing.length ? hintId : undefined}>
               <Trash2 size={14} aria-hidden="true" /> {busy ? 'Usuwanie…' : 'Usuń wpisy'}
             </button>
             {missing.length > 0 && !busy && (
               <div id={hintId} className="form-hint" style={{ flexBasis: '100%', textAlign: 'right', margin: 0 }}>
                 Aby usunąć: {missing.join('; ')}.
               </div>
             )}
           </>}>
      <div id={`${fid}-note`} className="alert alert--warning" style={{ marginTop: 0, marginBottom: 16 }}>
        Operacja jest nieodwracalna. Usunąć można wyłącznie wpisy starsze niż {RETENTION_MONTHS} miesiące
        — to minimalny okres przechowywania dziennika (NIS2 / KSC). Samo czyszczenie zostanie zapisane
        w dzienniku (kto, kiedy, powód, zakres) — tego wpisu nie da się usunąć.
      </div>

      {stats && (stats.total_entries != null || stats.oldest) && (
        <p style={{ margin: '0 0 12px', fontSize: 13, color: 'var(--color-text-muted)' }}>
          {stats.total_entries != null && <>W dzienniku: <strong style={{ color: 'var(--color-text)' }}>
            {countLabel(stats.total_entries, 'wpis', 'wpisy', 'wpisów')}</strong></>}
          {stats.oldest && <>{stats.total_entries != null ? ' · ' : ''}najstarszy: <strong style={{ color: 'var(--color-text)' }}>
            {fmtDateTime(stats.oldest)}</strong></>}
          {nothingOld && <> — brak wpisów starszych niż wybrana data, nic nie zostanie usunięte.</>}
        </p>
      )}

      <div className="form-group">
        <label className="form-label" htmlFor={`${fid}-before`}>Zakres — {what} starsze niż *</label>
        <input id={`${fid}-before`} type="date" className="form-control" style={{ maxWidth: 200 }}
               value={before} max={cutoff} required aria-describedby={`${fid}-before-hint`}
               onChange={e => setBefore(e.target.value)} />
        <div id={`${fid}-before-hint`} className="form-hint">
          Najpóźniej {fmtDay(cutoff)} (dziś − {RETENTION_MONTHS} miesiące). Wpisy z tego dnia i nowsze zostają.
        </div>
      </div>

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
        <input id={`${fid}-pw`} ref={pwRef} className="form-control" type="password" required
               autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} />
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor={`${fid}-confirm`}>
          Wpisz <strong>{CONFIRM_WORD}</strong>, aby potwierdzić *
        </label>
        <input id={`${fid}-confirm`} className="form-control" required autoComplete="off"
               aria-describedby={`${fid}-confirm-hint`}
               value={confirm} onChange={e => setConfirm(e.target.value)} />
        <div id={`${fid}-confirm-hint`} className="form-hint">
          Wielkimi literami, z polskim znakiem „Ś”{confirm && !confirmOk ? ' — wpisane słowo się nie zgadza' : ''}.
        </div>
      </div>
      {err && <div className="alert alert--error" role="alert">{err}</div>}
    </Modal>
  )
}
