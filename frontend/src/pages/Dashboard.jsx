import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  RefreshCw, ListChecks, CheckSquare, Wrench, AlertTriangle, Truck, UserPen,
} from 'lucide-react'
import { workflowDashboard, vendorContractAlerts } from '../api'
import { deptFull } from '../components/RequestView'

/**
 * Pulpit obiegu wniosków — spersonalizowany widok kolejek zalogowanego
 * użytkownika:
 *  - kafelki KPI tylko dla kolejek, które dotyczą jego roli
 *    (flagi show_* z backendu — kierownik I stopnia NIE widzi akceptacji
 *    ani realizacji),
 *  - lista wniosków czekających na moje działanie.
 * Dane z GET /api/requests/dashboard.
 */
export default function Dashboard() {
  const [data, setData]       = useState(null)
  const [alerts, setAlerts]   = useState(null)   // umowy serwisowe (tylko IT/admin)
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState(null)

  // Endpoint alertów jest za `require_it_staff` — pytamy tylko, gdy rola pasuje,
  // żeby kierownikowi nie generować 403 przy każdym wejściu na pulpit.
  const canSeeContracts = (() => {
    try {
      const u = JSON.parse(localStorage.getItem('szup_user') || '{}')
      const roles = Array.isArray(u.roles) ? u.roles : (u.role ? [u.role] : [])
      return ['it_staff', 'admin', 'superadmin'].some(r => roles.includes(r))
    } catch { return false }
  })()

  async function load() {
    setLoading(true); setErr(null)
    try {
      // Awaria alertów nie może wywrócić pulpitu — stąd .catch(() => null).
      const [r, a] = await Promise.all([
        workflowDashboard(),
        canSeeContracts ? vendorContractAlerts().catch(() => null) : Promise.resolve(null),
      ])
      setData(r.data)
      setAlerts(a?.data || null)
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się załadować pulpitu')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const kpis = useMemo(() => data ? [
    data.show_prepare && {
      to: '/manager', icon: ListChecks, variant: 'summary-card--orange',
      value: data.pending_prepare_count, label: 'Uprawnienia do przypisania',
    },
    data.show_approve && {
      to: '/manager', icon: CheckSquare, variant: 'summary-card--gold',
      value: data.pending_approve_count, label: 'Wnioski do akceptacji',
    },
    data.show_execute && {
      to: '/it', icon: Wrench, variant: 'summary-card--blue',
      value: data.pending_execute_count, label: 'Wnioski do realizacji',
    },
    data.show_execute && {
      to: '/it?tab=names', icon: UserPen, variant: 'summary-card--blue',
      value: data.pending_names_count, label: 'Zmiany nazwiska do realizacji',
    },
  ].filter(Boolean) : [], [data])

  const list = data?.pending_approvals_list || []

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Pulpit</div>
          <div className="page-header__sub">
            Wnioski o uprawnienia czekające na Twoje działanie
          </div>
        </div>
        <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Odśwież
        </button>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      {/* Umowy serwisowe — widoczne dla IT/admina. Wygasłe na czerwono,
          wygasające (≤30 dni) na pomarańczowo, żeby był czas zareagować. */}
      {alerts?.expired_count > 0 && (
        <Link to="/vendors" className="alert alert--error mb-4"
              style={{ display: 'block', textDecoration: 'none', fontSize: 13 }}>
          <AlertTriangle size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          <strong>Wygasłe umowy serwisowe: {alerts.expired_count}</strong>
          {' — '}{alerts.expired.map(v => v.vendor_name).join(', ')}
        </Link>
      )}
      {alerts?.expiring_count > 0 && (
        <Link to="/vendors" className="alert-banner alert-banner--warning mb-4"
              style={{ display: 'block', textDecoration: 'none', fontSize: 13,
                       padding: '10px 14px', borderRadius: 6 }}>
          <Truck size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          <strong>Umowy serwisowe kończą się wkrótce: {alerts.expiring_count}</strong>
          {' — '}
          {alerts.expiring.map(v => `${v.vendor_name} (za ${v.days_left} dni)`).join(', ')}
        </Link>
      )}

      {/* Kafelki KPI kolejek */}
      {kpis.length > 0 && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(210px, 1fr))',
          gap: 16, marginBottom: 20,
        }}>
          {kpis.map((k, idx) => {
            const Icon = k.icon
            return (
              <Link key={idx} to={k.to} className={`summary-card ${k.variant}`}
                    style={{ textDecoration: 'none', display: 'block' }}>
                <div className="summary-card__label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Icon size={13} />
                  {k.label}
                </div>
                <div className="summary-card__value">{k.value ?? 0}</div>
              </Link>
            )
          })}
        </div>
      )}

      {/* Lista wniosków czekających na działanie użytkownika */}
      <div className="card">
          <div style={{
            padding: '14px 18px', borderBottom: '1px solid var(--color-border)',
            fontWeight: 700, fontSize: 15, color: 'var(--color-navy)',
          }}>
            Wnioski do obsługi
          </div>
          {loading ? (
            <div className="text-muted" style={{ padding: 16 }}>Ładowanie…</div>
          ) : list.length === 0 ? (
            <div className="text-muted" style={{ padding: 16 }}>
              Brak wniosków czekających na Twoje działanie.
            </div>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th><th>Pracownik</th><th>Komórka</th><th>Krok</th><th></th>
                </tr>
              </thead>
              <tbody>
                {list.map(p => (
                  <tr key={p.request_id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{p.request_id}</td>
                    <td style={{ fontWeight: 600 }}>{p.worker_name}</td>
                    <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{deptFull(p.dept_name, p.dept_description)}</td>
                    <td>
                      <span className="badge badge--warning" style={{ fontSize: 11 }}>
                        {p.node_label}
                      </span>
                    </td>
                    <td>
                      <Link className="btn btn--action btn--sm"
                            to={p.node_type === 'it_execute' ? '/it' : '/manager'}>
                        Otwórz
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
  )
}
