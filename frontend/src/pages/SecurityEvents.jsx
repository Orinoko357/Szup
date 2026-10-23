import { useEffect, useState } from 'react'
import { Check, Lock, RefreshCw, Trash2 } from 'lucide-react'
import { listSecurityEvents, securityEventsSummary, resolveSecurityEvent, purgeSecurity, errorMessage } from '../api'
import PurgeLogModal from '../components/PurgeLogModal'
import { fmtDateTime } from '../serverTime'
import { toast, promptDialog } from '../components/ui/feedback'
import { SEVERITY_LABEL, SECURITY_EVENT_LABEL, securityEventLabel } from '../labels'
import { LoadError } from '../components/ui/LoadState'
import Segmented from '../components/ui/Segmented'
import { getUserRoles, getCurrentUser } from '../roles'

// Kolory istotności jako klasy z theme.css (.badge--sev-*, .stat-tile--sev-*)
// zamiast lokalnych słowników kolorów.
const SEVERITIES = ['low', 'medium', 'high', 'critical']
const sevKey = (sev) => (SEVERITIES.includes(sev) ? sev : 'low')
const TILE_LBL = { display: 'block', fontSize: 11, fontWeight: 700, letterSpacing: '.07em',
                   textTransform: 'uppercase', color: 'var(--color-text-muted)' }
// Zamykanie zdarzeń — te same reguły co w backendzie (routers/security.py):
// high/critical tylko superadmin; admin nie zamyka zdarzeń dotyczących jego konta.
const SUPERADMIN_ONLY_SEVERITIES = ['high', 'critical']

function resolveBlockReason(ev, isSuperadmin, myId) {
  if (isSuperadmin) return null
  if (SUPERADMIN_ONLY_SEVERITIES.includes(ev.severity)) {
    return 'Zdarzenie o wadze wysokiej lub krytycznej może zamknąć tylko superadmin'
  }
  let targetId = null
  try {
    const d = typeof ev.details === 'string' ? JSON.parse(ev.details) : ev.details
    targetId = d?.target_user_id ?? null
  } catch { /* nieczytelne szczegóły — decyduje backend */ }
  if (myId != null && (ev.user_id === myId || (targetId != null && Number(targetId) === myId))) {
    return 'Zdarzenie dotyczy Twojego konta — zamknie je inny administrator lub superadmin'
  }
  return null
}

const TILE_VAL = { display: 'block', fontSize: 28, fontWeight: 800, color: 'var(--color-heading)', lineHeight: 1.25 }

export default function SecurityEvents() {
  const [rows, setRows] = useState([])
  const [sum, setSum] = useState(null)
  const [onlyOpen, setOnlyOpen] = useState(true)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const isSuperadmin = getUserRoles().includes('superadmin')
  const myId = getCurrentUser().id ?? null
  const [purgeOpen, setPurgeOpen] = useState(false)

  async function load() {
    setLoading(true); setErr(null)
    try {
      const params = {}
      if (onlyOpen) params.resolved = false
      const [a, s] = await Promise.all([listSecurityEvents(params), securityEventsSummary()])
      setRows(a.data)
      setSum(s.data)
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się wczytać zdarzeń bezpieczeństwa'))
      setRows([]); setSum(null)   // bez „Brak zdarzeń” / zerowych kafelków po błędzie
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [onlyOpen])

  async function resolve(id) {
    const note = await promptDialog({
      title: 'Oznacz zdarzenie jako rozwiązane', label: 'Notatka do rozwiązania (opcjonalna)',
      multiline: true, confirmLabel: 'Oznacz jako rozwiązane',
    })
    if (note === null) return   // Anuluj
    try { await resolveSecurityEvent(id, note); load(); toast('Zdarzenie oznaczone jako rozwiązane') }
    catch (ex) { toast(errorMessage(ex, 'Nie udało się oznaczyć zdarzenia'), { tone: 'error' }) }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header__title">Bezpieczeństwo</h1>
          <div className="page-header__sub">
            Istotne zdarzenia wymagające reakcji (NIS2 / KSC). Po obsłużeniu zaznacz jako zakończone.
            {!isSuperadmin && ' Zdarzenia o wadze wysokiej i krytycznej zamyka superadmin.'}
          </div>
        </div>
        {isSuperadmin && (
          <button type="button" className="btn btn--ghost" style={{ color: 'var(--color-error-text)' }}
                  onClick={() => setPurgeOpen(true)}
                  title="Usuń zdarzenia bezpieczeństwa (tylko superadmin, z hasłem i powodem)">
            <Trash2 size={14} aria-hidden="true" /> Wyczyść…
          </button>
        )}
      </div>
      {purgeOpen && (
        <PurgeLogModal title="Wyczyść zdarzenia bezpieczeństwa" what="zdarzenia bezpieczeństwa"
                       purge={purgeSecurity} onClose={() => setPurgeOpen(false)}
                       onDone={() => { setPurgeOpen(false); load() }} />
      )}

      {sum && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 18 }}>
          <div className="stat-tile">
            <span style={TILE_LBL}>Otwarte</span>
            <span style={TILE_VAL}>{sum.open_total}</span>
            <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>wymagają reakcji</span>
          </div>
          {Object.entries(sum.open_by_severity || {}).map(([sev, n]) => (
            <div key={sev} className={`stat-tile stat-tile--sev-${sevKey(sev)}`}>
              <span style={TILE_LBL}>{SEVERITY_LABEL[sev] || sev}</span>
              <span style={TILE_VAL}>{n}</span>
              <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>istotność, otwarte</span>
            </div>
          ))}
        </div>
      )}

      {err && <LoadError message={err} onRetry={load} busy={loading} style={{ marginBottom: 16 }} />}

      <section aria-label="Zdarzenia" className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, padding: '10px 18px',
                      borderBottom: '1px solid var(--color-border)' }}>
          <Segmented ariaLabel="Filtr zdarzeń" value={onlyOpen ? 'open' : 'all'}
                     onChange={v => setOnlyOpen(v === 'open')}
                     options={[{ value: 'all', label: 'Wszystkie' }, { value: 'open', label: 'Nierozwiązane' }]} />
          <div style={{ flex: 1 }} />
          <button type="button" className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
            <RefreshCw size={13} /> Odśwież
          </button>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ minWidth: 1000 }}>
            <thead>
              <tr>
                <th>Data</th><th>Typ</th><th>Istotność</th><th>Opis</th><th>IP</th><th>Status</th><th><span className="sr-only">Akcje</span></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={7} style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</td></tr>
              )}
              {!loading && !err && rows.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>Brak zdarzeń</td></tr>
              )}
              {rows.map(r => {
                const blocked = r.resolved_at ? null : resolveBlockReason(r, isSuperadmin, myId)
                return (
                  <tr key={r.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, whiteSpace: 'nowrap' }}>
                      {fmtDateTime(r.created_at)}
                    </td>
                    <td style={{ fontSize: 13, color: 'var(--color-heading)' }} title={r.event_type || ''}>
                      {SECURITY_EVENT_LABEL[r.event_type] ? (
                        <>
                          <span style={{ display: 'block', fontWeight: 600 }}>{securityEventLabel(r.event_type)}</span>
                          <span style={{ display: 'block', fontFamily: 'var(--font-mono)', fontSize: 11,
                                         color: 'var(--color-text-muted)' }}>{r.event_type}</span>
                        </>
                      ) : (
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.event_type}</span>
                      )}
                    </td>
                    <td>
                      <span className={`badge badge--sev-${sevKey(r.severity)}`}>
                        {SEVERITY_LABEL[r.severity] || r.severity}
                      </span>
                    </td>
                    <td>{r.summary}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-text-muted)' }}>{r.ip || '—'}</td>
                    <td>
                      {r.resolved_at
                        ? <span className="badge badge--success">rozwiązane</span>
                        : <span className="badge badge--warning">otwarte</span>}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      {!r.resolved_at && !blocked && (
                        <button className="btn btn--ghost btn--sm" onClick={() => resolve(r.id)}
                                title="Oznacz jako rozwiązane"
                                aria-label={`Oznacz jako rozwiązane: ${securityEventLabel(r.event_type)}, ${fmtDateTime(r.created_at)}`}
                                style={{ color: 'var(--color-success-text)' }}>
                          <Check size={15} />
                        </button>
                      )}
                      {!r.resolved_at && blocked && (
                        <span title={blocked} role="img" aria-label={blocked}
                              style={{ display: 'inline-flex', padding: '0 8px', color: 'var(--color-text-muted)' }}>
                          <Lock size={14} aria-hidden="true" />
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
