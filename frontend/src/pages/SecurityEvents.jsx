import { useEffect, useState } from 'react'
import { AlertTriangle, Check, RefreshCw } from 'lucide-react'
import { listSecurityEvents, securityEventsSummary, resolveSecurityEvent } from '../api'
import { fmtDateTime } from '../serverTime'
import { toast, promptDialog } from '../components/ui/feedback'
import { SEVERITY_LABEL } from '../labels'

const SEV_COLOR = {
  low:      'var(--color-text-muted)',
  medium:   'var(--color-info)',
  high:     'var(--color-warning)',
  critical: 'var(--color-error)',
}
// v3.0: polski opis istotności obok klucza z backendu.
// Odznaka istotności (tło / tekst) — zgodna z paletą odznak.
const SEV_BADGE = {
  low:      ['var(--color-neutral-bg)', 'var(--color-neutral-text)'],
  medium:   ['var(--color-info-bg)',    'var(--color-info-text)'],
  high:     ['var(--color-warning-bg)', 'var(--color-warning-text)'],
  critical: ['var(--color-error-bg)',   'var(--color-error-text)'],
}
const tileStyle = (top) => ({
  background: 'var(--color-card)', border: '1px solid var(--color-border)', borderTop: `3px solid ${top}`,
  borderRadius: 10, padding: '12px 14px',
})
const TILE_LBL = { display: 'block', fontSize: 11, fontWeight: 700, letterSpacing: '.07em',
                   textTransform: 'uppercase', color: 'var(--color-text-muted)' }
const TILE_VAL = { display: 'block', fontSize: 28, fontWeight: 800, color: 'var(--color-heading)', lineHeight: 1.25 }

export default function SecurityEvents() {
  const [rows, setRows] = useState([])
  const [sum, setSum] = useState(null)
  const [onlyOpen, setOnlyOpen] = useState(true)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  async function load() {
    setLoading(true); setErr(null)
    try {
      const params = {}
      if (onlyOpen) params.resolved = false
      const [a, s] = await Promise.all([listSecurityEvents(params), securityEventsSummary()])
      setRows(a.data)
      setSum(s.data)
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd odczytu')
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
    catch (ex) { toast(ex.response?.data?.detail || 'Błąd', { tone: 'error' }) }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Zdarzenia bezpieczeństwa</div>
          <div className="page-header__sub">
            Istotne zdarzenia wymagające reakcji (NIS2 / KSC). Po obsłużeniu zaznacz jako zakończone.
          </div>
        </div>
      </div>

      {sum && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 10, marginBottom: 18 }}>
          <div style={tileStyle('var(--color-navy)')}>
            <span style={TILE_LBL}>Otwarte</span>
            <span style={TILE_VAL}>{sum.open_total}</span>
            <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>wymagają reakcji</span>
          </div>
          {Object.entries(sum.open_by_severity || {}).map(([sev, n]) => (
            <div key={sev} style={tileStyle(SEV_COLOR[sev])}>
              <span style={TILE_LBL}>{sev}</span>
              <span style={TILE_VAL}>{n}</span>
              <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>{SEVERITY_LABEL[sev] || ''}</span>
            </div>
          ))}
        </div>
      )}

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <section aria-label="Zdarzenia" className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, padding: '10px 18px',
                      borderBottom: '1px solid var(--color-border)' }}>
          <label className="form-check" style={{ minHeight: 44, fontSize: 14 }}>
            <input type="checkbox" checked={onlyOpen} onChange={e => setOnlyOpen(e.target.checked)}
                   style={{ width: 18, height: 18 }} />
            Tylko nierozwiązane
          </label>
          <div style={{ flex: 1 }} />
          <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
            <RefreshCw size={13} /> Odśwież
          </button>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ minWidth: 1000 }}>
            <thead>
              <tr>
                <th>Data</th><th>Typ</th><th>Istotność</th><th>Opis</th><th>IP</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={7} style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>Brak zdarzeń</td></tr>
              )}
              {rows.map(r => {
                const sb = SEV_BADGE[r.severity] || SEV_BADGE.low
                return (
                  <tr key={r.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, whiteSpace: 'nowrap' }}>
                      {fmtDateTime(r.created_at)}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-heading)' }}>{r.event_type}</td>
                    <td>
                      <span className="badge" style={{ background: sb[0], color: sb[1] }}>
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
                      {!r.resolved_at && (
                        <button className="btn btn--ghost btn--sm" onClick={() => resolve(r.id)}
                                title="Oznacz jako rozwiązane" aria-label="Oznacz jako rozwiązane"
                                style={{ color: 'var(--color-success-text)' }}>
                          <Check size={15} />
                        </button>
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
