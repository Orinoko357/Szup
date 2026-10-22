import { useEffect, useState } from 'react'
import { listSystems, listPermissions } from '../api'
import PermInput, {
  permInput, splitAdminPerm, AdminPermRow,
  groupPerms, subgroupPerms, isPermVisible, PermGroupSection, SystemBlock, isScopeGated,
} from './ItemFields'

/**
 * Dokładanie uprawnień przez IT na etapie realizacji wniosku.
 *
 * Świadomie PROSTSZY od pickera kierownika (Manager.jsx / MyTeam.jsx): tam
 * obowiązuje model „stanu docelowego" (held / picked / toGrant / toRevoke /
 * scopeChanged), bo kierownik nadaje i odbiera. IT wyłącznie DOKŁADA pozycje
 * wymagane technicznie i nigdy nie rusza tego, co zatwierdził kierownik —
 * dlatego wystarczy zwykłe zaznaczanie, bez wyliczania różnic.
 *
 * Pozycje już obecne na wniosku (`excludeKeys`) są ukryte, żeby nie dało się
 * ich zdublować (backend i tak by odmówił).
 */
export default function AddPermissionsPicker({
  unitId, excludeKeys, picked, fieldValues, onTogglePerm, onFieldChange, onLoaded,
}) {
  const [systems, setSystems]       = useState([])
  const [permsBySys, setPermsBySys] = useState({})
  const [loading, setLoading]       = useState(true)
  // Szukajka per grupa uprawnień: klucz „system_id|grupa" → fraza.
  const [groupQuery, setGroupQuery] = useState({})
  // Programy „scope-gated" aktywowane przez IT (zaznaczony sam program).
  const [openSys, setOpenSys] = useState(() => new Set())
  const [err, setErr]               = useState(null)

  function toggleScope(s, perms) {
    const sid = s.id
    const active = openSys.has(sid) || perms.some(p => picked.has(`${sid}:${p.id}`))
    if (active) {
      perms.forEach(p => { if (picked.has(`${sid}:${p.id}`)) onTogglePerm(sid, p.id) })
      setOpenSys(prev => { const n = new Set(prev); n.delete(sid); return n })
    } else {
      setOpenSys(prev => { const n = new Set(prev); n.add(sid); return n })
    }
  }

  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const sys = await listSystems({ unit_id: unitId, active_only: true })
        const active = sys.data
        const results = await Promise.all(active.map(s => listPermissions(s.id)))
        if (!alive) return
        const byId = {}
        results.forEach((res, i) => { byId[active[i].id] = res.data })
        setSystems(active)
        setPermsBySys(byId)
        // Rodzic potrzebuje definicji uprawnień do walidacji przed wysyłką
        // (m.in. rozpoznania pozycji administracyjnych).
        onLoaded?.(active, byId)
      } catch {
        if (alive) setErr('Nie udało się pobrać listy uprawnień')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [unitId])

  if (loading) return <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>Ładowanie uprawnień…</div>
  if (err) return <div className="alert alert--error" style={{ fontSize: 12 }}>{err}</div>

  // Odfiltruj to, co już jest na wniosku; system znika, gdy nie zostaje nic.
  const rows = systems.map(s => {
    const perms = (permsBySys[s.id] || []).filter(
      p => !excludeKeys.has(`${s.id}:${p.id}`)
    )
    return { s, perms }
  }).filter(({ perms }) => perms.length > 0)

  if (rows.length === 0) {
    return (
      <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
        Wszystkie dostępne uprawnienia są już na tym wniosku.
      </div>
    )
  }

  return (
    <div style={{
      maxHeight: 'min(34vh, 300px)', overflowY: 'auto',
      border: '1px solid var(--color-border)', borderRadius: 6,
      padding: 10, background: 'var(--bg-secondary)',
    }}>
      {rows.map(({ s, perms }) => {
        const { main, admin } = splitAdminPerm(perms)
        const adminKey = admin ? `${s.id}:${admin.id}` : null
        // „Tylko dostęp" = jedna pozycja na cały program.
        if (s.access_only) {
          // Pozycja główna może być już na wniosku (odfiltrowana) — zostają
          // wtedy same „super uprawnienia", więc nazwę systemu pokazujemy
          // osobnym nagłówkiem, żeby checkbox nie wisiał bez kontekstu.
          const p = main[0]
          const key = p ? `${s.id}:${p.id}` : null
          return (
            <SystemBlock
              key={s.id} name={s.name} compact
              // Pozycja główna bywa już na wniosku (odfiltrowana) — zostają
              // wtedy same „super uprawnienia" i nie ma czego zaznaczać
              // w nagłówku, ale nazwa programu musi zostać dla kontekstu.
              checked={p ? picked.has(key) : false}
              onToggle={() => p && onTogglePerm(s.id, p.id)}
              badges={p ? (
                <span className="badge badge--info" style={{ fontSize: 11 }}>dostęp</span>
              ) : null}
            >
              <AdminPermRow
                perm={admin} checked={picked.has(adminKey)} indent={0}
                onToggle={() => onTogglePerm(s.id, admin.id)}
                disabled={!!key && !picked.has(key) && !(adminKey && picked.has(adminKey))}
              />
            </SystemBlock>
          )
        }
        const allKeys = main.map(x => `${s.id}:${x.id}`)
        const selHere = allKeys.filter(k => picked.has(k)).length
        // Zaznacz/odznacz zestaw kluczy hurtem — do „zaznacz wszystkie" per grupa.
        const toggleGroup = (keys) => {
          const allOn = keys.length > 0 && keys.every(k => picked.has(k))
          keys.forEach(k => {
            const [sid, pid] = k.split(':').map(Number)
            if (allOn || !picked.has(k)) onTogglePerm(sid, pid)
          })
        }
        const gated = isScopeGated(s)
        const anySel = selHere > 0 || (adminKey && picked.has(adminKey))
        const active = !gated || openSys.has(s.id) || anySel
        return (
          <SystemBlock
            key={s.id} name={s.name} compact
            showCheckbox={gated}
            checked={active}
            onToggle={() => toggleScope(s, [...main, ...(admin ? [admin] : [])])}
            locked={gated && !active}
            lockedHint={gated && !active
              ? 'Zaznacz program, aby wybrać zakres uprawnień.' : null}
            badges={<>
              {selHere > 0 && (
                <span className="badge badge--success" style={{ fontSize: 11 }}>
                  wybrano: {selHere}
                </span>
              )}
              {gated && active && !anySel && (
                <span className="badge badge--warning" style={{ fontSize: 11 }}>
                  wybierz zakres
                </span>
              )}
            </>}
          >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {groupPerms(main).map(({ group, items }) => {
                const gkey = `${s.id}|${group}`
                const q = (groupQuery[gkey] || '').toLowerCase()
                const visible = items
                  .filter(p => isPermVisible(p, `${s.id}:${p.id}`, null, picked))
                  .filter(p => !q || p.permission_name.toLowerCase().includes(q))
                return (
                  <PermGroupSection
                    key={gkey} group={group} count={items.length} compact
                    selectedCount={items.filter(p => picked.has(`${s.id}:${p.id}`)).length}
                    query={groupQuery[gkey] || ''}
                    onQuery={v => setGroupQuery(x => ({ ...x, [gkey]: v }))}
                    onToggleAll={() => toggleGroup(visible.map(p => `${s.id}:${p.id}`))}
                  >
                  {subgroupPerms(visible).map(({ subgroup, items: subItems }) => (
                    <div key={subgroup || '_nosub'}>
                      {subgroup && (
                        <div style={{
                          fontSize: 11, fontStyle: 'italic', color: 'var(--color-text-muted)',
                          margin: '4px 0 2px 2px', letterSpacing: '.02em',
                        }}>
                          ↳ {subgroup}
                        </div>
                      )}
                      {subItems.map(p => {
                        const key = `${s.id}:${p.id}`
                        return (
                          <div key={p.id} style={subgroup ? { marginLeft: 12 } : undefined}>
                            <label style={{
                              display: 'flex', alignItems: 'center', gap: 8,
                              fontSize: 12, cursor: 'pointer',
                            }}>
                              <input type="checkbox" checked={picked.has(key)}
                                     onChange={() => onTogglePerm(s.id, p.id)} />
                              <span>{p.permission_name}</span>
                              {p.description && (
                                <span style={{ color: 'var(--color-text-muted)' }}>— {p.description}</span>
                              )}
                            </label>
                            <PermInput
                              input={permInput(p)} name={p.permission_name} compact
                              show={picked.has(key)}
                              values={fieldValues[key] || {}}
                              onChange={(label, v) => onFieldChange(key, label, v)}
                            />
                          </div>
                        )
                      })}
                    </div>
                  ))}
                  </PermGroupSection>
                )
              })}
              <AdminPermRow
                perm={admin} checked={picked.has(adminKey)} indent={0}
                onToggle={() => onTogglePerm(s.id, admin.id)}
                disabled={!(selHere > 0 || (gated && openSys.has(s.id)))
                          && !(adminKey && picked.has(adminKey))}
              />
            </div>
          </SystemBlock>
        )
      })}
    </div>
  )
}
