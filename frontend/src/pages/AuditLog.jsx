import { useEffect, useState } from 'react'
import { ScrollText, Download, RefreshCw, Filter } from 'lucide-react'
import { listAudit, auditStats, auditExportUrl } from '../api'
import { fmtDateTime } from '../serverTime'

export default function AuditLog() {
  const [rows, setRows] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [filters, setFilters] = useState({ username: '', action: '', since: '', until: '' })

  async function load() {
    setLoading(true); setErr(null)
    try {
      const params = { limit: 500 }
      if (filters.username) params.username = filters.username
      if (filters.action)   params.action   = filters.action
      if (filters.since)    params.since    = filters.since
      if (filters.until)    params.until    = filters.until
      const [a, s] = await Promise.all([listAudit(params), auditStats()])
      setRows(a.data)
      setStats(s.data)
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd odczytu audit logu')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  function downloadCsv() {
    const url = auditExportUrl(filters.since, filters.until)
    const token = localStorage.getItem('szup_token')
    fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.blob())
      .then(b => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(b)
        a.download = 'szup-audit.csv'
        a.click()
      })
  }

  const setF = (k, v) => setFilters(f => ({ ...f, [k]: v }))

  // v3.0 — układ wg projektu: nagłówek ze statystyką, karta filtrów, tabela.
  const LBL = { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, fontWeight: 700,
                letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--color-text-muted)' }
  const INP = { minHeight: 44, fontSize: 14, letterSpacing: 0, textTransform: 'none', fontWeight: 400 }
  const pill = (bg, fg) => ({ padding: '2px 8px', borderRadius: 10, fontFamily: 'var(--font-mono)',
                              fontSize: 12, fontWeight: 700, background: bg, color: fg })

  return (
    <div>
      <div className="page-header" style={{ marginBottom: 18 }}>
        <div>
          <div className="page-header__title">Audit log</div>
          <div className="page-header__sub">
            Ślad zdarzeń w systemie (NIS2 / KSC). Tabela jest append-only — wpisów nie można zmieniać ani usuwać.
          </div>
          {stats && (
            <div style={{ marginTop: 8, fontSize: 13, color: 'var(--color-text-muted)' }}>
              Wpisów: <strong style={{ color: 'var(--color-text)' }}>{stats.total_entries}</strong>
              {stats.oldest && <> · Najstarszy: <strong style={{ color: 'var(--color-text)' }}>{fmtDateTime(stats.oldest)}</strong></>}
              {stats.newest && <> · Najnowszy: <strong style={{ color: 'var(--color-text)' }}>{fmtDateTime(stats.newest)}</strong></>}
            </div>
          )}
        </div>
      </div>

      <form aria-label="Filtry" className="card" onSubmit={e => e.preventDefault()}
            style={{ padding: '16px 18px', marginBottom: 18, display: 'grid',
                     gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 12, alignItems: 'end' }}>
        <label style={LBL}>Użytkownik
          <input className="form-control" style={INP} value={filters.username} onChange={e => setF('username', e.target.value)} />
        </label>
        <label style={LBL}>Akcja (prefiks)
          <input className="form-control" style={INP} placeholder="np. login." value={filters.action} onChange={e => setF('action', e.target.value)} />
        </label>
        <label style={LBL}>Od
          <input type="datetime-local" className="form-control" style={INP} value={filters.since} onChange={e => setF('since', e.target.value)} />
        </label>
        <label style={LBL}>Do
          <input type="datetime-local" className="form-control" style={INP} value={filters.until} onChange={e => setF('until', e.target.value)} />
        </label>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, gridColumn: '1 / -1' }}>
          <button type="button" className="btn btn--primary" onClick={load} disabled={loading}>
            <Filter size={14} /> Filtruj
          </button>
          <button type="button" className="btn btn--ghost" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
          <div style={{ flex: 1 }} />
          <button type="button" className="btn btn--ghost" onClick={downloadCsv}>
            <Download size={14} /> Eksport CSV
          </button>
        </div>
      </form>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <section aria-label="Wpisy" className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ minWidth: 1080 }}>
            <thead>
              <tr>
                <th>Data</th><th>Użytkownik</th><th>Akcja</th><th>Ścieżka</th><th>Status</th><th>IP</th><th>Szczegóły</th>
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={7} style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={7} style={{ textAlign: 'center', color: 'var(--color-text-muted)' }}>Brak wpisów</td></tr>
              )}
              {rows.map(r => {
                const ok = r.status_code && r.status_code < 400
                return (
                  <tr key={r.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, whiteSpace: 'nowrap' }}>
                      {fmtDateTime(r.timestamp)}
                    </td>
                    <td style={{ fontWeight: 600 }}>{r.username || <span style={{ color: 'var(--color-text-muted)' }}>—</span>}</td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-navy)' }}>{r.action}</td>
                    <td style={{ maxWidth: 320 }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
                        {r.method && (
                          <span style={{ flexShrink: 0, padding: '1px 6px', borderRadius: 4, fontFamily: 'var(--font-mono)',
                                         fontSize: 11, fontWeight: 700, background: 'var(--color-neutral-bg)', color: 'var(--color-neutral-text)' }}>
                            {r.method}
                          </span>
                        )}
                        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, overflow: 'hidden',
                                       textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.path || ''}>
                          {r.path}
                        </span>
                      </span>
                    </td>
                    <td>
                      {r.status_code ? (
                        <span style={ok ? pill('var(--color-success-bg)', 'var(--color-success-text)')
                                        : pill('var(--color-warning-bg)', 'var(--color-warning-text)')}>
                          {r.status_code}
                        </span>
                      ) : ''}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-text-muted)' }}>{r.ip || ''}</td>
                    <td style={{ fontSize: 12, maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis',
                                 whiteSpace: 'nowrap', color: 'var(--color-text-muted)' }}
                        title={r.details || ''}>
                      {r.details || ''}
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
