import { useEffect, useState } from 'react'
import { ShieldCheck, RefreshCw, FileText } from 'lucide-react'
import { getMyPermissions } from '../api'
import { fmtDate } from '../serverTime'
import MyNameChanges from '../components/MyNameChanges'

export default function MyPermissions() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState(null)

  async function load() {
    setLoading(true); setErr(null)
    try {
      const r = await getMyPermissions()
      setData(r.data)
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się pobrać listy uprawnień')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const perms = data?.permissions || []
  const reqs  = data?.requests    || []

  // Grupowanie per system
  const bySystem = {}
  for (const p of perms) {
    const k = p.system_name || '—'
    if (!bySystem[k]) bySystem[k] = []
    bySystem[k].push(p)
  }
  const systems = Object.keys(bySystem).sort()

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Moje uprawnienia</div>
          <div className="page-header__sub">
            Uprawnienia nadane na podstawie zrealizowanych wniosków
          </div>
        </div>
        <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Odśwież
        </button>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <MyNameChanges />

      <div className="card" style={{ marginBottom: 16 }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>
        ) : perms.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 12 }}>
            <ShieldCheck size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Nie masz żadnych uprawnień nadanych wnioskiem w tym systemie.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {systems.map(sn => (
              <div key={sn}>
                <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-navy)', marginBottom: 8 }}>
                  {sn}
                </div>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th style={{ width: '30%' }}>Uprawnienie</th>
                      <th>Opis</th>
                      <th style={{ width: 160 }}>Nadano</th>
                      <th style={{ width: 100 }}>Wniosek</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bySystem[sn].map(p => (
                      <tr key={`${p.system_id}:${p.permission_id}:${p.request_id}`}>
                        <td style={{ fontWeight: 600 }}>{p.permission_name}</td>
                        <td style={{ color: 'var(--color-text-muted)' }}>
                          {p.description || '—'}
                        </td>
                        <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                          {fmtDate(p.granted_at)}
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                          #{p.request_id}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
        )}
      </div>

      {reqs.length > 0 && (
        <div className="card">
          <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-navy)', marginBottom: 12 }}>
            <FileText size={13} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Historia zrealizowanych wniosków
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 80 }}>Wniosek</th>
                <th style={{ width: 160 }}>Złożono</th>
                <th style={{ width: 160 }}>Zrealizowano</th>
                <th>Uprawnienia</th>
              </tr>
            </thead>
            <tbody>
              {reqs.map(r => (
                <tr key={r.id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>#{r.id}</td>
                  <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                    {fmtDate(r.created_at)}
                  </td>
                  <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                    {r.completed_at ? fmtDate(r.completed_at) : '—'}
                  </td>
                  <td>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {r.items.map((it, i) => (
                        <span key={i} className="badge badge--info" style={{ fontSize: 10 }}>
                          {it.system_name}: {it.permission_name}
                        </span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
