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

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Audit log</div>
          <div className="page-header__sub">
            Ślad zdarzeń w systemie (NIS2 / KSC). Tabela jest append-only — wpisów nie można zmieniać ani usuwać.
          </div>
        </div>
      </div>

      {stats && (
        <div style={{ display: 'flex', gap: 16, marginBottom: 16, fontSize: 12, color: 'var(--color-text-muted)' }}>
          <div>Wpisów: <strong>{stats.total_entries}</strong></div>
          {stats.oldest && <div>Najstarszy: <strong>{fmtDateTime(stats.oldest)}</strong></div>}
          {stats.newest && <div>Najnowszy: <strong>{fmtDateTime(stats.newest)}</strong></div>}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', marginBottom: 12, flexWrap: 'wrap' }}>
        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label">Użytkownik</label>
          <input className="form-control" value={filters.username} onChange={e => setF('username', e.target.value)} />
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label">Akcja (prefiks)</label>
          <input className="form-control" placeholder="np. login." value={filters.action} onChange={e => setF('action', e.target.value)} />
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label">Od</label>
          <input type="datetime-local" className="form-control" value={filters.since} onChange={e => setF('since', e.target.value)} />
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label">Do</label>
          <input type="datetime-local" className="form-control" value={filters.until} onChange={e => setF('until', e.target.value)} />
        </div>
        <button className="btn btn--primary btn--sm" onClick={load} disabled={loading}>
          <Filter size={13} /> Filtruj
        </button>
        <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
          <RefreshCw size={13} /> Odśwież
        </button>
        <button className="btn btn--ghost btn--sm" onClick={downloadCsv}>
          <Download size={13} /> Eksport CSV
        </button>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <div className="card">
        <table className="data-table">
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
            {rows.map(r => (
              <tr key={r.id}>
                <td style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                  {fmtDateTime(r.timestamp)}
                </td>
                <td>{r.username || <span style={{ color: 'var(--color-text-muted)' }}>—</span>}</td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{r.action}</td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {r.method} {r.path}
                </td>
                <td>{r.status_code || ''}</td>
                <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{r.ip || ''}</td>
                <td style={{ fontSize: 11, maxWidth: 340, overflow: 'hidden', textOverflow: 'ellipsis' }}
                    title={r.details || ''}>
                  {r.details || ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
