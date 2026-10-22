import { useEffect, useState } from 'react'
import {
  Play, ListChecks, UserCheck, Crown, Wrench, Flag,
  CheckCircle2, Circle, MinusCircle, XCircle, Loader2, GitBranch,
} from 'lucide-react'
import {
  getRequestWorkflow, workflowAction,
  listActiveSystems, listPermissions, getRequest,
} from '../api'

const NODE_ICONS = {
  start: Play,
  select_permissions: ListChecks,
  manager_approve: UserCheck,
  higher_manager_approve: Crown,
  it_execute: Wrench,
  end: Flag,
}

const STATE_STYLES = {
  done:    { color: 'var(--color-success)',    icon: CheckCircle2, bg: 'var(--color-success-bg)' },
  current: { color: 'var(--color-heading)',       icon: Loader2,      bg: 'var(--color-warning-bg)' },
  pending: { color: 'var(--color-text-muted)', icon: Circle,       bg: 'var(--bg-secondary)' },
  skipped: { color: 'var(--color-text-muted)', icon: MinusCircle,  bg: 'var(--bg-secondary)' },
}

/**
 * Pasek postępu obiegu + panel akcji bieżącego węzła.
 *
 * Bez podpisu papierowego — decyzje zatwierdza się bezpośrednio:
 *  - select_permissions: kierownik wybiera uprawnienia i zatwierdza (jeden krok),
 *  - manager_approve / higher_manager_approve: „Zatwierdź",
 *  - it_execute: login AD + „Zrealizowano".
 * Odrzucenie dostępne na każdym kroku.
 */
/**
 * showActions — czy ribbon ma sam renderować panel akcji bieżącego węzła.
 * W scalonych widokach (Panel IT / Wnioski do obsługi) akcję obsługuje modal
 * nadrzędny, więc przekazujemy showActions={false}, żeby nie dublować
 * formularzy (np. dwa pola „Login AD").
 */
export default function WorkflowRibbon({ requestId, unitId, onChange, showActions = true }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)

  async function reload() {
    setLoading(true); setErr(null)
    try {
      const r = await getRequestWorkflow(requestId)
      setData(r.data)
    } catch (ex) { setErr(ex.response?.data?.detail || 'Błąd pobierania obiegu') }
    finally { setLoading(false) }
  }
  useEffect(() => { reload() }, [requestId])

  async function submit(action, extra = {}) {
    try {
      await workflowAction(requestId, { action, ...extra })
      await reload()
      onChange?.()
    } catch (ex) { alert(ex.response?.data?.detail || 'Błąd akcji') }
  }

  if (loading) return <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Ładowanie obiegu…</div>
  if (err) return <div className="alert alert--error">{err}</div>
  if (!data || !data.workflow_enabled) {
    return (
      <div style={{ padding: 8, fontSize: 12, color: 'var(--color-text-muted)' }}>
        <GitBranch size={12} style={{ verticalAlign: 'middle', marginRight: 4 }} />
        Ten wniosek nie ma podpiętego obiegu (starszy wniosek — bez workflow).
      </div>
    )
  }

  return (
    <div>
      <RibbonBar ribbon={data.ribbon} />

      {showActions && data.status === 'active' && data.current_node && (
        <ActionPanel data={data} requestId={requestId} unitId={unitId} onSubmit={submit} />
      )}

      {data.status === 'completed' && (
        <div style={{ marginTop: 12, padding: 10, color: 'var(--color-success)',
                      background: 'var(--color-success-bg)', borderRadius: 4, fontSize: 13 }}>
          <CheckCircle2 size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          Obieg zakończony pomyślnie.
        </div>
      )}
      {data.status === 'rejected' && (
        <div style={{ marginTop: 12, padding: 10, color: 'var(--color-error-text)',
                      background: 'var(--color-error-bg)', borderRadius: 4, fontSize: 13 }}>
          <XCircle size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          Wniosek odrzucony.
        </div>
      )}

      {data.steps?.length > 0 && (
        <details style={{ marginTop: 12 }}>
          <summary style={{ cursor: 'pointer', fontSize: 12, color: 'var(--color-text-muted)' }}>
            Historia kroków ({data.steps.length}) — ślad audytowy
          </summary>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {data.steps.map(s => (
              <div key={s.step_index} style={{
                padding: 8, background: 'var(--bg-secondary)', borderRadius: 4, fontSize: 12,
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-text-muted)' }}>
                    #{s.step_index}
                  </span>
                  <strong>{s.node_type}</strong>
                  <span className={`badge badge--${
                    s.action === 'approve' || s.action === 'execute' || s.action === 'select' ? 'success' :
                    s.action === 'reject' ? 'error' : 'neutral'
                  }`} style={{ fontSize: 10 }}>
                    {s.action}
                  </span>
                  {s.actor_name && (
                    <span style={{ color: 'var(--color-text-muted)' }}>{s.actor_name}</span>
                  )}
                  <span style={{ fontSize: 10, color: 'var(--color-text-muted)', marginLeft: 'auto' }}>
                    {new Date(s.created_at).toLocaleString('pl-PL')}
                  </span>
                </div>
                {s.comment && <div style={{ marginTop: 4, fontSize: 11 }}>{s.comment}</div>}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

function RibbonBar({ ribbon }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 4, overflowX: 'auto',
                  padding: 8, background: 'var(--bg-secondary)', borderRadius: 6 }}>
      {ribbon.map((n, idx) => {
        const st = STATE_STYLES[n.state] || STATE_STYLES.pending
        const NodeIcon = NODE_ICONS[n.type] || GitBranch
        const StateIcon = st.icon
        return (
          <div key={n.id} style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
            <div style={{
              padding: '6px 10px', border: `1px solid ${st.color}`, borderRadius: 4,
              background: st.bg, color: st.color, minWidth: 130, textAlign: 'center',
              opacity: n.state === 'skipped' ? 0.5 : 1,
            }}
            title={`${n.type} · ${n.state}`}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                <NodeIcon size={11} />
                <StateIcon size={11} className={n.state === 'current' ? 'spin' : ''} />
              </div>
              <div style={{ fontSize: 10, fontWeight: 700, marginTop: 2,
                            textDecoration: n.state === 'skipped' ? 'line-through' : 'none' }}>
                {n.label}
              </div>
            </div>
            {idx < ribbon.length - 1 && (
              <span style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>→</span>
            )}
          </div>
        )
      })}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Panel akcji dla bieżącego węzła (bez podpisu)
// ---------------------------------------------------------------------------
function ActionPanel({ data, requestId, unitId, onSubmit }) {
  const node = data.current_node
  const NodeIcon = NODE_ICONS[node.type] || GitBranch

  return (
    <div style={{ marginTop: 12, padding: 14, background: 'var(--color-warning-bg)',
                  borderRadius: 4, border: '1px solid var(--color-border)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <NodeIcon size={16} style={{ color: 'var(--color-heading)' }} />
        <strong style={{ fontSize: 13 }}>Bieżący krok: {node.label || node.type}</strong>
      </div>

      {node.type === 'select_permissions' && (
        <SelectPanel requestId={requestId} unitId={unitId} onSubmit={onSubmit} />
      )}
      {(node.type === 'manager_approve' || node.type === 'higher_manager_approve') && (
        <ApprovePanel onSubmit={onSubmit} />
      )}
      {node.type === 'it_execute' && (
        <ExecutePanel onSubmit={onSubmit} />
      )}
      {!['select_permissions', 'manager_approve', 'higher_manager_approve', 'it_execute'].includes(node.type) && (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          Ten krok nie wymaga akcji — silnik przejdzie dalej automatycznie.
        </div>
      )}
    </div>
  )
}

// Wybór uprawnień = zatwierdzenie (jeden krok). Kierownik zaznacza uprawnienia
// i klika „Zatwierdź wybór".
function SelectPanel({ requestId, unitId, onSubmit }) {
  const [systems, setSystems] = useState([])
  const [permsBySys, setPermsBySys] = useState({})
  const [picked, setPicked] = useState(() => new Set())   // "sysId:permId"
  const [comment, setComment] = useState('')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let alive = true
    async function load() {
      setLoading(true)
      try {
        const rSys = await listActiveSystems(unitId ? { unit_id: unitId } : {})
        const sys = rSys.data || []
        const permsArr = await Promise.all(
          sys.map(s => listPermissions(s.id).then(r => [s.id, r.data]).catch(() => [s.id, []]))
        )
        // Wstępne zaznaczenie z uprawnień już zapisanych na wniosku (podpowiedź HR).
        let pre = new Set()
        try {
          const rReq = await getRequest(requestId)
          for (const it of (rReq.data.items || [])) pre.add(`${it.system_id}:${it.permission_id}`)
        } catch { /* brak — start pusty */ }
        if (!alive) return
        setSystems(sys)
        setPermsBySys(Object.fromEntries(permsArr))
        setPicked(pre)
      } finally { if (alive) setLoading(false) }
    }
    load()
    return () => { alive = false }
  }, [requestId, unitId])

  function toggle(sysId, permId) {
    const key = `${sysId}:${permId}`
    setPicked(s => {
      const n = new Set(s); n.has(key) ? n.delete(key) : n.add(key); return n
    })
  }

  async function confirmSelection() {
    if (picked.size === 0) {
      if (!confirm('Nie zaznaczono żadnego uprawnienia — wniosek przejdzie dalej bez uprawnień. Kontynuować?')) return
    }
    setBusy(true)
    try {
      const items = [...picked].map(k => {
        const [system_id, permission_id] = k.split(':').map(Number)
        return { system_id, permission_id }
      })
      await onSubmit('select', { items, comment: comment || null })
    } finally { setBusy(false) }
  }

  if (loading) return <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Ładowanie uprawnień…</div>

  return (
    <div>
      <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 8 }}>
        Zaznacz uprawnienia dla pracownika. Zatwierdzenie wyboru jest jednocześnie akceptacją kierownika.
      </div>
      <div style={{ maxHeight: 'min(56vh, 520px)', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 14,
                    background: 'var(--bg-primary)', border: '1px solid var(--color-border)',
                    borderRadius: 4, padding: 12 }}>
        {systems.length === 0 && (
          <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
            Brak oprogramowania dostępnego dla tej jednostki.
          </div>
        )}
        {systems.map(sys => {
          const perms = permsBySys[sys.id] || []
          return (
            <div key={sys.id}>
              <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--color-heading)', marginBottom: 6 }}>
                {sys.name}
                {sys.access_only && (
                  <span className="badge badge--neutral" style={{ fontSize: 10, marginLeft: 6 }}>dostęp</span>
                )}
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, paddingLeft: 10 }}>
                {perms.map(p => {
                  const key = `${sys.id}:${p.id}`
                  return (
                    <label key={p.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14 }}>
                      <input type="checkbox" checked={picked.has(key)}
                             style={{ width: 16, height: 16, flexShrink: 0 }}
                             onChange={() => toggle(sys.id, p.id)} />
                      {p.permission_name}
                    </label>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      <textarea className="input input--sm" rows={2} placeholder="Komentarz (opcjonalny)"
                value={comment} onChange={e => setComment(e.target.value)}
                style={{ width: '100%', marginTop: 10, marginBottom: 8 }} />
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn btn--action btn--sm" disabled={busy} onClick={confirmSelection}>
          <CheckCircle2 size={12} /> Zatwierdź wybór
        </button>
        <button className="btn btn--ghost btn--sm" disabled={busy}
                onClick={() => onSubmit('reject', { comment: comment || null })}
                style={{ color: 'var(--color-danger)' }}>
          <XCircle size={12} /> Odrzuć wniosek
        </button>
      </div>
    </div>
  )
}

function ApprovePanel({ onSubmit }) {
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState(false)
  async function act(action) {
    setBusy(true)
    try { await onSubmit(action, { comment: comment || null }); setComment('') }
    finally { setBusy(false) }
  }
  return (
    <div>
      <textarea className="input input--sm" rows={2} placeholder="Komentarz (opcjonalny)"
                value={comment} onChange={e => setComment(e.target.value)}
                style={{ width: '100%', marginBottom: 8 }} />
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn btn--action btn--sm" disabled={busy} onClick={() => act('approve')}>
          <CheckCircle2 size={12} /> Zatwierdź
        </button>
        <button className="btn btn--ghost btn--sm" disabled={busy} onClick={() => act('reject')}
                style={{ color: 'var(--color-danger)' }}>
          <XCircle size={12} /> Odrzuć wniosek
        </button>
      </div>
    </div>
  )
}

function ExecutePanel({ onSubmit }) {
  const [comment, setComment] = useState('')
  const [adUsername, setAdUsername] = useState('')
  const [busy, setBusy] = useState(false)
  async function act(action) {
    setBusy(true)
    try {
      const extra = { comment: comment || null }
      if (action === 'execute') extra.ad_username = adUsername.trim() || null
      await onSubmit(action, extra)
      setComment(''); setAdUsername('')
    } finally { setBusy(false) }
  }
  return (
    <div>
      <label style={{ display: 'block', fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
        Login AD pracownika (sAMAccountName):
      </label>
      <input className="input input--sm" placeholder="np. jkowalski"
             style={{ width: '100%', marginBottom: 8 }}
             value={adUsername} onChange={e => setAdUsername(e.target.value)} />
      <textarea className="input input--sm" rows={2} placeholder="Komentarz (opcjonalny)"
                value={comment} onChange={e => setComment(e.target.value)}
                style={{ width: '100%', marginBottom: 8 }} />
      <div style={{ display: 'flex', gap: 8 }}>
        <button className="btn btn--action btn--sm" disabled={busy} onClick={() => act('execute')}>
          <CheckCircle2 size={12} /> Zrealizowano
        </button>
        <button className="btn btn--ghost btn--sm" disabled={busy} onClick={() => act('reject')}
                style={{ color: 'var(--color-danger)' }}>
          <XCircle size={12} /> Odrzuć wniosek
        </button>
      </div>
    </div>
  )
}
