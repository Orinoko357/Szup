/**
 * Spójny język wizualny zmian uprawnień — używany WSZĘDZIE, gdzie pokazujemy
 * lub wybieramy uprawnienia we wniosku (kierownik, kierownik nadrzędny, IT,
 * „Moi pracownicy"). Jedno źródło prawdy, żeby nadanie i odebranie zawsze
 * wyglądały tak samo:
 *
 *   nadanie    → zielony, znak „+”, etykieta „Do nadania”
 *   odebranie  → czerwony, przekreślenie, znak „−”, etykieta „Do odebrania”
 *   posiada    → szary badge „posiada” (bez zmian)
 */

export function splitItems(items = []) {
  const grants  = items.filter(it => (it.kind || 'grant') !== 'revoke')
  const revokes = items.filter(it => (it.kind || 'grant') === 'revoke')
  return { grants, revokes }
}

// --- Widok pozycji wniosku pogrupowany po kierunku --------------------------
// `deny` (opcjonalne) włącza tryb ODMOWY pojedynczych pozycji (kierownik
// nadrzędny / IT): { can, map, toggle, setComment }, gdzie `map` to
// { [item_id]: komentarz } aktualnie odmawianych pozycji.
export default function PermissionChanges({ items = [], emptyText = 'Brak', deny }) {
  const { grants, revokes } = splitItems(items)
  if (items.length === 0) {
    return <div style={{ color: 'var(--color-text-muted)' }}>{emptyText}</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {grants.length  > 0 && <Group kind="grant"  items={grants} deny={deny} />}
      {revokes.length > 0 && <Group kind="revoke" items={revokes} />}
    </div>
  )
}

// Pozycje → hierarchia Program → Grupa uprawnień → Uprawnienie.
function groupBySystemAndGroup(items) {
  const sysMap = new Map()   // system_name → Map(group_name → items[])
  for (const it of items) {
    const sn = it.system_name || '—'
    if (!sysMap.has(sn)) sysMap.set(sn, new Map())
    const gm = sysMap.get(sn)
    const gn = it.group_name || ''      // '' = bez grupy
    if (!gm.has(gn)) gm.set(gn, [])
    gm.get(gn).push(it)
  }
  return [...sysMap.entries()]
    .sort(([a], [b]) => a.localeCompare(b, 'pl'))
    .map(([system_name, gm]) => ({
      system_name,
      groups: [...gm.entries()]
        .sort(([a], [b]) => (a === '' ? -1 : b === '' ? 1 : a.localeCompare(b, 'pl')))
        .map(([group_name, gitems]) => ({ group_name, items: gitems })),
    }))
}

function PermRow({ it, isRevoke, deny }) {
  const cv = it.custom_values && typeof it.custom_values === 'object'
    ? Object.entries(it.custom_values).filter(([, v]) => v)
    : []
  // Pozycja już odmówiona (zapisana w bazie).
  const persistedDenied = !!it.denied
  // Czy można odmówić TERAZ (tryb akcji): tylko nadania, które nie są jeszcze odmówione.
  const canDenyNow = deny?.can && !isRevoke && !persistedDenied && it.id != null
  const denyingNow = deny?.map && Object.prototype.hasOwnProperty.call(deny.map, it.id)
  const struck = isRevoke || persistedDenied || denyingNow
  return (
    <div style={{ padding: '5px 12px 5px 40px', fontSize: 14,
                  borderTop: '0.5px solid var(--color-border)',
                  background: (persistedDenied || denyingNow) ? 'var(--color-error-bg)' : 'transparent' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={{ textDecoration: struck ? 'line-through' : 'none',
                       color: (persistedDenied || denyingNow) ? 'var(--color-error-text)' : 'inherit' }}>
          {it.permission_name}
        </span>
        {it.added_by_name && (
          <span className="badge badge--warning"
                style={{ fontSize: 10, textDecoration: 'none' }}
                title={`Dodane przez IT: ${it.added_by_name}`}>
            dodane przez IT
          </span>
        )}
        {persistedDenied && (
          <span className="badge badge--error" style={{ fontSize: 10, textDecoration: 'none' }}
                title={it.denied_by_name ? `Odmówił: ${it.denied_by_name}` : undefined}>
            odmówiono
          </span>
        )}
        {canDenyNow && (
          <button type="button" className="btn btn--ghost btn--sm"
                  style={{ fontSize: 11, marginLeft: 'auto' }}
                  onClick={() => deny.toggle(it.id)}>
            Odmów
          </button>
        )}
        {denyingNow && (
          <button type="button" className="btn btn--ghost btn--sm"
                  style={{ fontSize: 11, marginLeft: 'auto' }}
                  onClick={() => deny.toggle(it.id)}>
            Cofnij odmowę
          </button>
        )}
      </div>
      {/* Komentarz do odmowy — zapisany (read-only) albo wpisywany teraz. */}
      {persistedDenied && it.deny_comment && (
        <div style={{ fontSize: 11, color: 'var(--color-error-text)', marginTop: 3 }}>
          Powód odmowy: {it.deny_comment}
        </div>
      )}
      {denyingNow && (
        <input className="form-control" style={{ fontSize: 12, marginTop: 4 }}
               placeholder="Powód odmowy (opcjonalnie)"
               value={deny.map[it.id] || ''}
               onChange={e => deny.setComment(it.id, e.target.value)} />
      )}
      {cv.length > 0 && !struck && (
        <div style={{ marginTop: 4, textDecoration: 'none' }}>
          {cv.map(([k, v]) => (
            <div key={k} style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
              <span style={{ fontWeight: 600 }}>{k}:</span>{' '}
              <span style={{ whiteSpace: 'pre-wrap' }}>{v}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Group({ kind, items, deny }) {
  const isRevoke = kind === 'revoke'
  const color = isRevoke ? 'var(--color-error)'    : 'var(--color-success)'
  const bg    = isRevoke ? 'var(--color-error-bg)' : 'var(--color-success-bg)'
  const label = isRevoke ? 'Do odebrania' : 'Do nadania'
  const sign  = isRevoke ? '−' : '+'
  const systems = groupBySystemAndGroup(items)
  return (
    <div style={{
      border: `1px solid ${color}`, borderLeftWidth: 3,
      borderRadius: 'var(--radius-control)', overflow: 'hidden',
    }}>
      <div style={{ background: bg, padding: '6px 10px', fontWeight: 700, fontSize: 12, color }}>
        {sign} {label} ({items.length})
      </div>
      {/* Pasma nagłówków: program (mocne) → grupa uprawnień (jaśniejsze, wcięte)
          → uprawnienia (wiersze z wcięciem). */}
      {systems.map(sys => (
        <div key={sys.system_name}>
          <div style={{
            background: 'var(--bg-secondary)', padding: '7px 12px',
            fontWeight: 700, fontSize: 13, color: 'var(--color-navy)',
            borderTop: '1px solid var(--color-border)',
          }}>
            {sys.system_name}
          </div>
          {sys.groups.map(g => (
            <div key={g.group_name || '_nogrp'}>
              {g.group_name && (
                <div style={{
                  padding: '4px 12px 4px 26px', fontSize: 11,
                  textTransform: 'uppercase', letterSpacing: '.03em',
                  color: 'var(--color-text-muted)', background: 'var(--bg-primary)',
                  borderTop: '0.5px solid var(--color-border)',
                }}>
                  {g.group_name}
                </div>
              )}
              {g.items.map(it => (
                <PermRow key={it.id ?? `${it.system_id}:${it.permission_id}`}
                         it={it} isRevoke={isRevoke} deny={deny} />
              ))}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

// --- Pickery „stanu docelowego” (MyTeam, krok wyboru u kierownika) ----------
// held = co pracownik ma OBECNIE, picked = stan docelowy zaznaczony w formularzu.

export function permChangeState(key, held, picked) {
  const h = held.has(key), p = picked.has(key)
  if (h && p) return 'kept'      // posiada i zostaje
  if (h && !p) return 'revoke'   // odznaczone posiadane → DO ODEBRANIA
  if (!h && p) return 'grant'    // zaznaczone nowe      → DO NADANIA
  return 'none'
}

export function changeStyle(st) {
  if (st === 'revoke') return {
    background: 'var(--color-error-bg)',
    borderLeft: '3px solid var(--color-error)',
    padding: '3px 6px', borderRadius: 4,
  }
  if (st === 'grant') return {
    background: 'var(--color-success-bg)',
    borderLeft: '3px solid var(--color-success)',
    padding: '3px 6px', borderRadius: 4,
  }
  return {}
}

export function changeTextStyle(st) {
  if (st === 'revoke') return {
    textDecoration: 'line-through',
    color: 'var(--color-error-text)',
  }
  return {}
}

export function ChangeBadge({ st }) {
  if (st === 'revoke') return <span className="badge badge--error"   style={{ fontSize: 9 }}>DO ODEBRANIA</span>
  if (st === 'grant')  return <span className="badge badge--success" style={{ fontSize: 9 }}>DO NADANIA</span>
  if (st === 'kept')   return <span className="badge badge--neutral" style={{ fontSize: 9 }}>posiada</span>
  return null
}
