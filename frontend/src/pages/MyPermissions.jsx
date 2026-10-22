import { useEffect, useState } from 'react'
import { ShieldCheck, RefreshCw } from 'lucide-react'
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
        <button className="btn btn--ghost" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Odśwież
        </button>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <MyNameChanges />

      <section aria-label="Uprawnienia" className="card" style={{ marginBottom: 18, padding: 0, overflow: 'hidden' }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: '16px 18px' }}>Ładowanie…</div>
        ) : perms.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: '16px 18px' }}>
            <ShieldCheck size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Nie masz żadnych uprawnień nadanych wnioskiem w tym systemie.
          </div>
        ) : (
          <div>
            {systems.map((sn, i) => (
              <div key={sn} style={{ borderBottom: i < systems.length - 1 ? '1px solid var(--color-border)' : 'none' }}>
                <h2 style={{ margin: 0, padding: '14px 18px 10px', fontSize: 15, fontWeight: 800, color: 'var(--color-heading)' }}>
                  {sn}
                </h2>
                <div style={{ overflowX: 'auto' }}>
                <table className="data-table" style={{ minWidth: 640 }}>
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
                        <td style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
                          {fmtDate(p.granted_at)}
                        </td>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--color-heading)' }}>
                          #{p.request_id}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {reqs.length > 0 && (
        <section aria-label="Historia zrealizowanych wniosków" className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <h2 style={{ margin: 0, padding: '14px 18px', fontSize: 16, fontWeight: 800, color: 'var(--color-heading)',
                       borderBottom: '1px solid var(--color-border)' }}>
            Historia zrealizowanych wniosków
          </h2>
          <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ minWidth: 700 }}>
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
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--color-heading)' }}>#{r.id}</td>
                  <td style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
                    {fmtDate(r.created_at)}
                  </td>
                  <td style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
                    {r.completed_at ? fmtDate(r.completed_at) : '—'}
                  </td>
                  <td>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                      {r.items.map((it, i) => (
                        <span key={i} className="badge badge--info" style={{ fontSize: 12 }}>
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
        </section>
      )}
    </div>
  )
}
