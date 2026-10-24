import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { RefreshCw, CheckCircle } from 'lucide-react'
import { workflowDashboard, vendorContractAlerts, securityEventsSummary, errorMessage } from '../api'
import { serverNow, serverTs, fmtDateTime } from '../serverTime'
import { deptFull } from '../components/RequestView'
import { workRoles, hasAnyRole } from '../roles'
import { nodeLabel, daysSince, waitText, NODE_TONE, SEVERITY_LABEL } from '../labels'
import AdminChecklist from '../components/AdminChecklist'
import { LoadError } from '../components/ui/LoadState'

/**
 * Pulpit (v3.0) — WYŁĄCZNIE sprawy czekające na reakcję użytkownika:
 *  - „Wymaga uwagi”: alerty tylko, gdy coś jest nie tak (umowy serwisowe —
 *    IT/admin; otwarte zdarzenia bezpieczeństwa — admin),
 *  - kafelki kolejek (flagi show_* z backendu) — działają jako filtr listy,
 *  - lista spraw od najdłużej czekającej, „Otwórz” prowadzi wprost do wniosku.
 * Bez skrótów do stron z paska bocznego (nic się nie dubluje z nawigacją).
 * Dane: GET /api/requests/dashboard (+ istniejące endpointy alertów).
 */
// „Czeka” = czas na BIEŻĄCYM etapie (step_since), awaryjnie od złożenia wniosku.
function waitsLabel(p) {
  const d = serverTs(p.step_since || p.created_at)
  if (!d) return { text: '—', late: false, title: '' }
  const days = daysSince(d, serverNow())
  return {
    text: waitText(days), late: days >= 7,
    title: `${p.step_since ? 'na tym etapie od' : 'od złożenia'} ${fmtDateTime(p.step_since || p.created_at)}`,
  }
}
const sinceTs = (p) => serverTs(p.step_since || p.created_at) || 0

export default function Dashboard() {
  // Superadmin: tylko konfiguracja (lista kontrolna, alerty) — bez kolejek pracy.
  const roles = workRoles()
  // Endpointy alertów mają własne wymagania ról — pytamy tylko, gdy rola pasuje,
  // żeby nie generować 403 przy każdym wejściu na pulpit.
  const canSeeContracts = hasAnyRole(roles, ['it_staff', 'admin', 'superadmin'])
  const canSeeSecurity  = hasAnyRole(roles, ['admin', 'superadmin'])
  const adminOnly = !hasAnyRole(roles, ['manager', 'it_staff'])
  const isAdmin = hasAnyRole(roles, ['admin', 'superadmin'])
  const isSuperadmin = roles.includes('superadmin')
  // Kilka ról operacyjnych → przy każdej sprawie pokazujemy perspektywę.
  const multiRole = hasAnyRole(roles, ['manager']) && hasAnyRole(roles, ['it_staff'])

  const [data, setData]         = useState(null)
  const [contracts, setContracts] = useState(null)
  const [security, setSecurity] = useState(null)
  const [loading, setLoading]   = useState(true)
  const [err, setErr]           = useState(null)
  const [filter, setFilter]     = useState(null)

  async function load() {
    setLoading(true); setErr(null)
    try {
      // Awaria alertów nie może wywrócić pulpitu — stąd .catch(() => null).
      const [r, c, s] = await Promise.all([
        workflowDashboard(),
        canSeeContracts ? vendorContractAlerts().catch(() => null) : Promise.resolve(null),
        canSeeSecurity  ? securityEventsSummary().catch(() => null) : Promise.resolve(null),
      ])
      setData(r.data)
      setContracts(c?.data || null)
      setSecurity(s?.data || null)
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się załadować pulpitu'))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const alerts = useMemo(() => {
    const out = []
    if (contracts?.expired_count > 0) out.push({
      tone: 'err', to: '/vendors', link: 'Dostawcy',
      title: `Wygasłe umowy serwisowe: ${contracts.expired_count}`,
      text: contracts.expired.map(v => v.vendor_name).join(', '),
    })
    if (contracts?.expiring_count > 0) out.push({
      tone: 'warn', to: '/vendors', link: 'Dostawcy',
      title: `Umowy serwisowe kończą się wkrótce: ${contracts.expiring_count}`,
      text: contracts.expiring.map(v => `${v.vendor_name} (za ${v.days_left} dni)`).join(', '),
    })
    if (security?.open_total > 0) {
      const sev = security.open_by_severity || {}
      const serious = (sev.critical || 0) + (sev.high || 0)
      out.push({
        tone: serious > 0 ? 'err' : 'warn', to: '/security', link: 'Bezpieczeństwo',
        title: `Otwarte zdarzenia bezpieczeństwa: ${security.open_total}`,
        text: serious > 0
          ? `w tym o istotności ${SEVERITY_LABEL.high}/${SEVERITY_LABEL.critical}: ${serious}`
          : 'do przejrzenia',
      })
    }
    return out
  }, [contracts, security])

  // Kafelki kolejek — tylko te, które dotyczą roli (flagi show_* z backendu).
  // Superadmin (rezerwa): kafelki liczone także z samej listy — backend sprzed 3.11
  // nie ustawiał show_prepare, a lista zawierała już wnioski z etapu kierownika (W1/N3).
  const tiles = useMemo(() => {
    if (!data) return []
    const lst = data.pending_approvals_list || []
    const countOf = (nodes) => lst.filter(p => nodes.includes(p.node_type)).length
    const saPrepare = isSuperadmin ? Math.max(data.pending_prepare_count || 0, countOf(['select_permissions'])) : 0
    const saApprove = isSuperadmin ? Math.max(data.pending_approve_count || 0, countOf(['manager_approve', 'higher_manager_approve'])) : 0
    return [
    (data.show_prepare || saPrepare > 0) && { id: 'prepare', label: 'Uprawnienia do przypisania',
      count: isSuperadmin ? saPrepare : data.pending_prepare_count },
    (data.show_approve || saApprove > 0) && { id: 'approve', label: 'Wnioski do akceptacji',
      count: isSuperadmin ? saApprove : data.pending_approve_count },
    data.show_execute && { id: 'execute', label: 'Wnioski do realizacji',     count: data.pending_execute_count },
    // Zmiany nazwiska realizuje wyłącznie IT (nie admin/superadmin).
    data.show_execute && roles.includes('it_staff')
      && { id: 'names',   label: 'Zmiany nazwiska do realizacji', count: data.pending_names_count },
    ].filter(Boolean)
  }, [data])

  const FILTER_NODES = {
    prepare: ['select_permissions'],
    approve: ['manager_approve', 'higher_manager_approve'],
    execute: ['it_execute'],
  }
  const list = useMemo(() => {
    const all = [...(data?.pending_approvals_list || [])]
      .sort((a, b) => sinceTs(a) - sinceTs(b))
    if (!filter || filter === 'names') return filter === 'names' ? [] : all
    return all.filter(p => FILTER_NODES[filter].includes(p.node_type))
  }, [data, filter])

  const totalWaiting = (data?.pending_approvals_count || 0)
    + (roles.includes('it_staff') ? (data?.pending_names_count || 0) : 0)
  // Backend zwraca najwyżej 50 najdłużej czekających — gdy spraw jest więcej,
  // mówimy o tym wprost i odsyłamy do pełnej listy.
  const serverShown = data?.pending_approvals_list?.length || 0
  const truncated = (data?.pending_approvals_count || 0) > serverShown
  const activeTile = tiles.find(t => t.id === filter)
  const tileHidden = activeTile && filter !== 'names' && (activeTile.count || 0) > list.length
  const fullTab = filter === 'execute' ? 'it'
    : (filter === 'prepare' || filter === 'approve') ? 'handle'
    : (data?.show_execute && !data?.show_prepare ? 'it' : 'handle')
  const hasQueue = tiles.length > 0
    || (isSuperadmin && (data?.pending_approvals_list?.length || 0) > 0)

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header__title">Pulpit</h1>
          <div className="page-header__sub">Sprawy czekające na Twoje działanie</div>
        </div>
        <button className="btn btn--ghost" style={{ minHeight: 44, fontSize: 14, background: 'var(--color-card)' }}
                onClick={load} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'spin' : ''} /> Odśwież
        </button>
      </div>

      {err && <LoadError message={err} onRetry={load} busy={loading} style={{ marginBottom: 16 }} />}

      {/* Wymaga uwagi — pojawia się tylko, gdy coś jest nie tak. */}
      {alerts.length > 0 && (
        <section aria-label="Wymaga uwagi" className="card" style={{ padding: '4px 18px', marginBottom: 18 }}>
          {alerts.map((a, i) => (
            <div key={i} style={{
              display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, minHeight: 48, padding: '6px 0',
              borderBottom: i < alerts.length - 1 ? '1px solid var(--color-border)' : 'none',
            }}>
              <span aria-hidden="true" style={{
                width: 24, height: 24, flexShrink: 0, borderRadius: '50%', display: 'grid', placeItems: 'center',
                fontSize: 13, fontWeight: 800,
                background: a.tone === 'err' ? 'var(--color-error-bg)' : 'var(--color-warning-bg)',
                color: a.tone === 'err' ? 'var(--color-error-text)' : 'var(--color-warning-text)',
              }}>!</span>
              <span style={{ flex: '1 1 280px', fontSize: 14 }}>
                <strong>{a.title}</strong>
                <span style={{ color: 'var(--color-text-muted)' }}> — {a.text}</span>
              </span>
              <Link to={a.to} style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-gold-dark)', textDecoration: 'none' }}>
                {a.link} →
              </Link>
            </div>
          ))}
        </section>
      )}

      {isAdmin && <AdminChecklist />}

      {!hasQueue && !loading && !err && hasAnyRole(roles, ['manager']) && !hasAnyRole(roles, ['it_staff']) && (
        <div className="card" style={{ fontSize: 14, marginBottom: 18 }}>
          <strong style={{ color: 'var(--color-heading)' }}>Brak kolejki do obsługi.</strong>
          <span style={{ color: 'var(--color-text-muted)' }}>
            {' '}Nie masz przypisanych komórek — poproś administratora o przypisanie w „Jednostkach”.
          </span>
        </div>
      )}

      {hasQueue && (
        <section aria-label="Czeka na Ciebie" className="card" style={{ padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '16px 18px 6px', display: 'grid',
                        gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 10 }}>
            {tiles.map(t => {
              const active = filter === t.id
              return (
                <button key={t.id} type="button" aria-pressed={active}
                        onClick={() => setFilter(active ? null : t.id)}
                        style={{
                          textAlign: 'left', padding: '12px 14px', borderRadius: 8, cursor: 'pointer',
                          font: 'inherit', color: 'inherit',
                          background: active ? 'var(--color-warning-bg)' : 'var(--color-card)',
                          border: active ? '2px solid var(--color-heading)' : '1px solid var(--color-input-border)',
                        }}>
                  <span style={{ display: 'block', fontSize: 11, fontWeight: 700, letterSpacing: '.07em',
                                 textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>{t.label}</span>
                  <span style={{ display: 'block', fontSize: 28, fontWeight: 800, lineHeight: 1.25,
                                 color: 'var(--color-heading)' }}>{t.count ?? 0}</span>
                </button>
              )
            })}
          </div>

          {loading ? (
            <div className="text-muted" style={{ padding: 18 }}>Ładowanie…</div>
          ) : filter === 'names' ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10,
                          padding: '14px 18px', borderTop: '1px solid var(--color-border)', fontSize: 14 }}>
              <span style={{ flex: 1 }}>Zmiany nazwiska mają osobną kolejkę.</span>
              <Link className="btn btn--action btn--sm" to="/requests?tab=names">Przejdź do kolejki</Link>
            </div>
          ) : totalWaiting === 0 ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '24px 18px',
                          borderTop: '1px solid var(--color-border)' }}>
              <CheckCircle size={28} color="var(--color-success)" aria-hidden="true" />
              <span style={{ fontSize: 15 }}>
                <strong>Wszystko załatwione.</strong>
                <span style={{ color: 'var(--color-text-muted)' }}> Nic nie czeka na Twoje działanie.</span>
              </span>
            </div>
          ) : list.length === 0 ? (
            <div className="text-muted" style={{ padding: 18, borderTop: '1px solid var(--color-border)' }}>
              Brak spraw w tej kategorii.
            </div>
          ) : (
            <div style={{ overflowX: 'auto', paddingTop: 8 }}>
              <table className="data-table" style={{ minWidth: 760 }}>
                <thead>
                  <tr><th>#</th><th>Pracownik</th><th>Komórka</th><th>Krok</th><th>Czeka</th><th></th></tr>
                </thead>
                <tbody>
                  {list.map(p => {
                    const w = waitsLabel(p)
                    const tab = p.node_type === 'it_execute' ? 'it' : 'handle'
                    return (
                      <tr key={p.request_id}>
                        <td style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--color-text-muted)' }}>{p.request_id}</td>
                        <td style={{ fontWeight: 700 }}>{p.worker_name}</td>
                        <td>
                          {/* wg projektu: kod pogrubiony + pełna nazwa wyszarzona */}
                          <strong style={{ color: 'var(--color-heading)' }}>{p.dept_name || '—'}</strong>
                          {deptFull(p.dept_name, p.dept_description).includes(' · ') && (
                            <span style={{ color: 'var(--color-text-muted)' }}> · {p.dept_description}</span>
                          )}
                        </td>
                        <td>
                          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
                            <span className={`badge ${NODE_TONE[p.node_type] || 'badge--neutral'}`} style={{ fontSize: 12, fontWeight: 700 }}>
                              {nodeLabel(p.node_type, p.node_label)}
                            </span>
                            {multiRole && (
                              <span className="badge badge--neutral" style={{ fontSize: 11 }}>
                                {p.node_type === 'it_execute' ? 'jako IT' : 'jako kierownik'}
                              </span>
                            )}
                          </div>
                          {p.waiting_for && (
                            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 3 }}>
                              Czeka na: {p.waiting_for}
                            </div>
                          )}
                        </td>
                        <td title={w.title} style={{ fontSize: 13, fontWeight: w.late ? 700 : 400,
                                     color: w.late ? 'var(--color-error-text)' : 'var(--color-text-muted)' }}>
                          {w.text}
                        </td>
                        <td style={{ textAlign: 'right' }}>
                          {/* Superadmin nie ma strony „Wnioski” — osobny widok wniosku
                              (podgląd, akcje tylko przy can_act). */}
                          <Link className="btn btn--action btn--sm" style={{ minHeight: 36, fontSize: 13, fontWeight: 700 }}
                                to={isSuperadmin ? `/requests/view/${p.request_id}` : `/requests?tab=${tab}&open=${p.request_id}`}
                                aria-label={`Otwórz wniosek #${p.request_id} — ${p.worker_name || 'pracownik'}`}>
                            Otwórz
                          </Link>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div style={{ padding: '10px 18px 14px', fontSize: 12, color: 'var(--color-text-muted)' }}>
            {(truncated || tileHidden) ? (
              <>
                Pokazano {list.length} z {activeTile && filter !== 'names' ? activeTile.count : data.pending_approvals_count}
                {' '}(najdłużej czekające){isSuperadmin ? '.' : <>
                {' '}— pełna lista w{' '}
                <Link to={`/requests?tab=${fullTab}`} style={{ color: 'var(--color-gold-dark)', fontWeight: 700 }}>
                  „Wnioskach”
                </Link>.</>}
              </>
            ) : isSuperadmin
              ? 'Najdłużej czekające najpierw · tylko wnioski, na których superadmin może działać awaryjnie.'
              : 'Najdłużej czekające najpierw · pełne listy w „Wnioskach”.'}
          </div>
        </section>
      )}

      {adminOnly && !loading && (
        <div className="card" style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>
          {isSuperadmin ? (
            <>
              Superadmin to konto awaryjne — konfiguruje system i nie obsługuje wniosków
              (robią to kierownicy i IT). Wyjątek: wniosek, którego w strukturze nie ma kto
              obsłużyć — wybór uprawnień w komórce bez kierownika i zastępców albo akceptacja
              wyższa bez osoby uprawnionej. Taki wniosek pojawi się powyżej i można go otworzyć;
              oświadczenie zostanie zapisane z adnotacją „działając awaryjnie jako superadmin”.
            </>
          ) : (
            <>
              Administrator konfiguruje system — wnioski obsługują kierownicy i IT.
              Tu pojawiają się tylko sprawy wymagające reakcji administratora.
            </>
          )}
        </div>
      )}
    </div>
  )
}
