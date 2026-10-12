import { useEffect, useState } from 'react'
import {
  Network, RefreshCw, ChevronRight, ChevronDown,
  Building2, User, ShieldCheck, Users, Crown,
} from 'lucide-react'
import { getMySubtree } from '../api'
import { fmtDate } from '../serverTime'
import { KindBadge, kindMeta } from './Units'

export default function Structure() {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState(null)

  async function load() {
    setLoading(true); setErr(null)
    try {
      const r = await getMySubtree()
      setData(r.data)
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się pobrać struktury')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const roots = data?.roots || []

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Moja struktura</div>
          <div className="page-header__sub">
            Podgląd wydziałów podrzędnych, ich kierowników i pracowników wraz
            z nadanymi uprawnieniami
          </div>
        </div>
        <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Odśwież
        </button>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <div className="card">
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>
        ) : roots.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>
            <Network size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Brak wydziałów w Twoim zakresie
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {roots.map(d => (
              <DeptNode key={d.id} dept={d} depth={0} defaultOpen />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function DeptNode({ dept: d, depth, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const hasChildren = (d.children || []).length > 0
  const hasWorkers  = (d.workers  || []).length > 0

  return (
    <div style={{
      marginLeft: depth * 14,
      borderLeft: depth > 0 ? '2px solid var(--color-border)' : 'none',
      paddingLeft: depth > 0 ? 12 : 0,
    }}>
      <div
        onClick={() => setOpen(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px',
          background: 'var(--bg-secondary)', borderRadius: 6, cursor: 'pointer',
          border: '1px solid var(--color-border)',
        }}>
        {hasChildren || hasWorkers
          ? (open ? <ChevronDown size={14} /> : <ChevronRight size={14} />)
          : <span style={{ width: 14, display: 'inline-block' }} />}
        {(() => {
          const meta = kindMeta(d.kind)
          const Icon = meta.icon || Building2
          return <Icon size={15} style={{ color: 'var(--color-navy)' }} />
        })()}
        <strong style={{ fontSize: 13 }}>{d.name}</strong>
        <KindBadge kind={d.kind} />
        {d.requires_higher_approval && (
          <span className="badge badge--warning" style={{ fontSize: 10 }}>
            2-stopniowy
          </span>
        )}
        <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
          · {d.unit_name || '—'}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          {d.manager ? (
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
              <Crown size={12} style={{ verticalAlign: 'middle', marginRight: 4, color: 'var(--color-gold)' }} />
              {d.manager.full_name || d.manager.username}
            </span>
          ) : (
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
              (brak kierownika)
            </span>
          )}
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            <Users size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
            {(d.workers || []).length}
          </span>
        </div>
      </div>

      {open && (
        <div style={{ marginTop: 6, marginLeft: 20 }}>
          {hasWorkers && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
              {d.workers.map(w => (
                <WorkerRow key={w.id} worker={w} />
              ))}
            </div>
          )}
          {hasChildren && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {d.children.map(c => (
                <DeptNode key={c.id} dept={c} depth={depth + 1} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function WorkerRow({ worker: w }) {
  const [expanded, setExpanded] = useState(false)
  const hasPerms = (w.permissions || []).length > 0

  // grupowanie per system dla czytelności
  const bySystem = {}
  for (const p of (w.permissions || [])) {
    const k = p.system_name || '—'
    if (!bySystem[k]) bySystem[k] = []
    bySystem[k].push(p)
  }
  const systemNames = Object.keys(bySystem).sort()

  return (
    <div style={{
      border: '1px solid var(--color-border)', borderRadius: 6,
      background: 'var(--bg-primary, var(--bg-secondary))',
      padding: '6px 10px',
    }}>
      <div
        onClick={() => hasPerms && setExpanded(v => !v)}
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          cursor: hasPerms ? 'pointer' : 'default',
        }}>
        {hasPerms
          ? (expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />)
          : <span style={{ width: 12, display: 'inline-block' }} />}
        {w.is_manager_here
          ? <Crown size={13} style={{ color: 'var(--color-gold)' }} />
          : <User size={13} style={{ color: 'var(--color-text-muted)' }} />}
        <span style={{ fontWeight: w.is_manager_here ? 700 : 500, fontSize: 12 }}>
          {w.full_name || w.username}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-muted)' }}>
          {w.username}
        </span>
        {w.email && (
          <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
            · {w.email}
          </span>
        )}
        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--color-text-muted)' }}>
          <ShieldCheck size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
          {w.permissions.length} upr.
        </span>
      </div>

      {expanded && hasPerms && (
        <div style={{ marginTop: 6, marginLeft: 22, display: 'flex', flexDirection: 'column', gap: 4 }}>
          {systemNames.map(sn => (
            <div key={sn}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-navy)' }}>
                {sn}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginLeft: 8, marginTop: 2 }}>
                {bySystem[sn].map(p => (
                  <span key={`${p.system_id}:${p.permission_id}:${p.request_id}`}
                        className="badge badge--info"
                        title={`Nadano: ${fmtDate(p.granted_at)} (wniosek #${p.request_id})`}
                        style={{ fontSize: 10 }}>
                    {p.permission_name}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
