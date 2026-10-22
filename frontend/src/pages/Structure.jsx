import { useEffect, useState } from 'react'
import {
  Network, RefreshCw, ChevronRight, ChevronDown,
  Building2, User, ShieldCheck, Users, Crown,
} from 'lucide-react'
import { getMySubtree } from '../api'
import { fmtDate } from '../serverTime'
import { KindBadge, kindMeta } from './Units'

export default function Structure({ renderHeader }) {
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
      {renderHeader ? renderHeader(load, loading) : (
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
      )}

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <section aria-label="Struktura" className="card" style={{ padding: 12 }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>
        ) : roots.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>
            <Network size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Brak wydziałów w Twoim zakresie
          </div>
        ) : (
          <div role="tree" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {roots.map(d => (
              <DeptNode key={d.id} dept={d} depth={0} defaultOpen />
            ))}
          </div>
        )}
      </section>
    </div>
  )
}

function DeptNode({ dept: d, depth, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen)
  const hasChildren = (d.children || []).length > 0
  const hasWorkers  = (d.workers  || []).length > 0

  return (
    <div role="treeitem" aria-expanded={open} style={{ marginLeft: depth > 0 ? 24 : 0 }}>
      <div
        role="button" tabIndex={0}
        onClick={() => setOpen(v => !v)}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setOpen(v => !v) } }}
        style={{
          display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, minHeight: 48,
          padding: '4px 12px', boxSizing: 'border-box',
          background: 'var(--bg-secondary)', borderRadius: 8, cursor: 'pointer',
          border: '1px solid var(--color-border)',
        }}>
        {hasChildren || hasWorkers
          ? (open ? <ChevronDown size={14} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />
                  : <ChevronRight size={14} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />)
          : <span style={{ width: 14, display: 'inline-block' }} />}
        {(() => {
          const meta = kindMeta(d.kind)
          const Icon = meta.icon || Building2
          return <Icon size={17} aria-hidden="true" style={{ color: 'var(--color-heading)' }} />
        })()}
        <strong style={{ fontSize: 14, color: 'var(--color-heading)' }}>{d.name}</strong>
        <KindBadge kind={d.kind} />
        {d.requires_higher_approval && (
          <span className="badge badge--warning" style={{ fontSize: 11, fontWeight: 700 }}>
            2-stopniowy
          </span>
        )}
        <span style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
          · {d.unit_name || '—'}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
          {d.manager ? (
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--color-text-muted)' }}>
              <Crown size={15} aria-hidden="true" style={{ color: 'var(--color-gold-dark)' }} />
              {d.manager.full_name || d.manager.username}
            </span>
          ) : (
            <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              (brak kierownika)
            </span>
          )}
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--color-text-muted)' }}>
            <Users size={15} aria-hidden="true" />
            {(d.workers || []).length}
          </span>
        </div>
      </div>

      {open && (
        <div style={{ marginTop: 6, marginLeft: 24 }}>
          {hasWorkers && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 6 }}>
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
    <div>
      <div
        role={hasPerms ? 'button' : undefined} tabIndex={hasPerms ? 0 : undefined}
        aria-expanded={hasPerms ? expanded : undefined}
        onClick={() => hasPerms && setExpanded(v => !v)}
        onKeyDown={e => { if (hasPerms && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); setExpanded(v => !v) } }}
        style={{
          display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8, minHeight: 40,
          padding: '2px 12px', borderRadius: 6, cursor: hasPerms ? 'pointer' : 'default',
        }}>
        {hasPerms
          ? (expanded ? <ChevronDown size={12} aria-hidden="true" /> : <ChevronRight size={12} aria-hidden="true" />)
          : <span style={{ width: 12, display: 'inline-block' }} />}
        {w.is_manager_here
          ? <Crown size={15} aria-hidden="true" style={{ color: 'var(--color-gold-dark)' }} />
          : <User size={15} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />}
        <span style={{ fontWeight: w.is_manager_here ? 700 : 600, fontSize: 14 }}>
          {w.full_name || w.username}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-text-muted)' }}>
          {w.username}
        </span>
        {w.email && (
          <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
            · {w.email}
          </span>
        )}
        <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, color: 'var(--color-text-muted)' }}>
          <ShieldCheck size={14} aria-hidden="true" />
          {w.permissions.length} upr.
        </span>
      </div>

      {expanded && hasPerms && (
        <div style={{ padding: '4px 12px 10px 35px', display: 'flex', flexDirection: 'column', gap: 6 }}>
          {systemNames.map(sn => (
            <div key={sn} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6, fontSize: 13 }}>
              <strong style={{ minWidth: 190, color: 'var(--color-heading)' }}>{sn}</strong>
              {bySystem[sn].map(p => (
                <span key={`${p.system_id}:${p.permission_id}:${p.request_id}`}
                      className="badge badge--info"
                      title={`Nadano: ${fmtDate(p.granted_at)} (wniosek #${p.request_id})`}
                      style={{ fontSize: 12 }}>
                  {p.permission_name}
                </span>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
