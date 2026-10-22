import { useEffect, useState } from 'react'
import { AlertTriangle, Check, RefreshCw } from 'lucide-react'
import { listSecurityEvents, securityEventsSummary, resolveSecurityEvent } from '../api'
import { fmtDateTime } from '../serverTime'

const SEV_COLOR = {
  low:      'var(--color-text-muted)',
  medium:   'var(--color-info)',
  high:     'var(--color-warning)',
  critical: 'var(--color-error)',
}
// v3.0: polski opis istotności obok klucza z backendu.
const SEV_PL = { low: 'niska', medium: 'średnia', high: 'wysoka', critical: 'krytyczna' }

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
    const note = prompt('Notatka do rozwiązania (opcjonalna):') ?? ''
    try { await resolveSecurityEvent(id, note); load() }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd') }
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
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          <div className="card" style={{ padding: 12, minWidth: 120 }}>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Otwarte</div>
            <div style={{ fontSize: 20, fontWeight: 700 }}>{sum.open_total}</div>
          </div>
          {Object.entries(sum.open_by_severity || {}).map(([sev, n]) => (
            <div key={sev} className="card" style={{ padding: 12, minWidth: 100 }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: SEV_COLOR[sev] }}>{SEV_PL[sev] || sev}</div>
              <div style={{ fontSize: 20, fontWeight: 700 }}>{n}</div>
            </div>
          ))}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <label className="form-check">
          <input type="checkbox" checked={onlyOpen} onChange={e => setOnlyOpen(e.target.checked)} />
          Tylko nierozwiązane
        </label>
        <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
          <RefreshCw size={13} /> Odśwież
        </button>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <div className="card">
        <table className="data-table">
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
            {rows.map(r => (
              <tr key={r.id}>
                <td style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                  {fmtDateTime(r.created_at)}
                </td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{r.event_type}</td>
                <td>
                  <span className="badge" style={{ background: SEV_COLOR[r.severity], color: 'white' }}>
                    {SEV_PL[r.severity] || r.severity}
                  </span>
                </td>
                <td>{r.summary}</td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{r.ip || '—'}</td>
                <td>
                  {r.resolved_at
                    ? <span className="badge badge--success">rozwiązane</span>
                    : <span className="badge badge--warning">otwarte</span>}
                </td>
                <td>
                  {!r.resolved_at && (
                    <button className="btn btn--ghost btn--sm" onClick={() => resolve(r.id)}
                            title="Oznacz jako rozwiązane">
                      <Check size={13} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
