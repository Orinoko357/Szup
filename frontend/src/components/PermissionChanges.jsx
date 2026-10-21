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

// Data+godzina do tooltipów (kto i kiedy odmówił / zrealizował pozycję).
function fmtDT(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d)) return ''
  return d.toLocaleString('pl-PL', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

// Tekst tooltipa badge'a: „Osoba — 12.10.2026, 14:30".
function actorTitle(name, iso) {
  const dt = fmtDT(iso)
  if (name && dt) return `${name} — ${dt}`
  return name || dt || undefined
}

export function splitItems(items = []) {
  const grants  = items.filter(it => (it.kind || 'grant') !== 'revoke')
  const revokes = items.filter(it => (it.kind || 'grant') === 'revoke')
  return { grants, revokes }
}

// --- Widok pozycji wniosku pogrupowany po kierunku --------------------------
// `deny` (opcjonalne) włącza tryb ODMOWY pojedynczych pozycji (kierownik
// nadrzędny / IT): { can, map, toggle, setComment, save, remove, busyId }.
//   map     — { [item_id]: komentarz } pozycji z OTWARTYM szkicem odmowy
//   save(id)   — zapisuje odmowę OD RAZU (POST .../deny), bez kończenia wniosku
//   remove(id) — cofa zapisaną odmowę (POST .../deny { denied:false })
//   busyId  — id pozycji aktualnie zapisywanej (blokuje przyciski)
export default function PermissionChanges({ items = [], emptyText = 'Brak', deny, fulfill }) {
  const { grants, revokes } = splitItems(items)
  if (items.length === 0) {
    return <div style={{ color: 'var(--color-text-muted)' }}>{emptyText}</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {grants.length  > 0 && <Group kind="grant"  items={grants} deny={deny} fulfill={fulfill} />}
      {revokes.length > 0 && <Group kind="revoke" items={revokes} />}
    </div>
  )
}

// Podział pozycji grupy na podgrupy (bez podgrupy = '' na początku).
function splitSubgroups(items) {
  const sm = new Map()
  for (const it of items) {
    const sg = it.subgroup_name || ''
    if (!sm.has(sg)) sm.set(sg, [])
    sm.get(sg).push(it)
  }
  return [...sm.entries()]
    .sort(([a], [b]) => (a === '' ? -1 : b === '' ? 1 : a.localeCompare(b, 'pl')))
    .map(([subgroup_name, sitems]) => ({ subgroup_name, items: sitems }))
}

// Pozycje → hierarchia Program → Grupa uprawnień → Podgrupa → Uprawnienie.
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
        .map(([group_name, gitems]) => ({ group_name, subgroups: splitSubgroups(gitems) })),
    }))
}

function PermRow({ it, isRevoke, deny, fulfill }) {
  const cv = it.custom_values && typeof it.custom_values === 'object'
    ? Object.entries(it.custom_values).filter(([, v]) => v)
    : []
  // Pozycja już odmówiona / zrealizowana (zapisana w bazie).
  const persistedDenied = !!it.denied
  const persistedFulfilled = !!it.fulfilled && !persistedDenied
  // Czy można odmówić TERAZ (tryb akcji): tylko nadania, nieodmówione i niezrealizowane.
  const canDenyNow = deny?.can && !isRevoke && !persistedDenied && !persistedFulfilled && it.id != null
  const denyingNow = deny?.map && Object.prototype.hasOwnProperty.call(deny.map, it.id)
  const canFulfill = fulfill?.can && !isRevoke && it.id != null && typeof fulfill?.set === 'function'
  const busy = (deny?.busyId ?? fulfill?.busyId) === it.id
  const canSave = typeof deny?.save === 'function'       // natychmiastowy zapis dostępny
  const canUndo = typeof deny?.remove === 'function'
  const struck = isRevoke || persistedDenied || denyingNow
  const rowBg = persistedFulfilled ? 'var(--color-success-bg)'
    : (persistedDenied || denyingNow) ? 'var(--color-error-bg)' : 'transparent'
  return (
    <div style={{ padding: '5px 12px 5px 40px', fontSize: 14,
                  borderTop: '0.5px solid var(--color-border)', background: rowBg }}>
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
                title={actorTitle(it.denied_by_name, it.denied_at)}>
            odmówiono
          </span>
        )}
        {persistedFulfilled && (
          <span className="badge badge--success" style={{ fontSize: 10, textDecoration: 'none' }}
                title={actorTitle(it.fulfilled_by_name, it.fulfilled_at)}>
            zrealizowano
          </span>
        )}
        {/* Przyciski akcji — po prawej. */}
        <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6 }}>
          {persistedFulfilled && canFulfill && (
            <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
                    style={{ fontSize: 11 }} onClick={() => fulfill.set(it.id, false)}>
              {busy ? 'Cofam…' : 'Cofnij'}
            </button>
          )}
          {canFulfill && !persistedFulfilled && !persistedDenied && !denyingNow && (
            <button type="button" className="btn btn--success btn--sm" disabled={busy}
                    style={{ fontSize: 11 }} onClick={() => fulfill.set(it.id, true)}>
              {busy ? 'Zapisuję…' : '✓ Zrobione'}
            </button>
          )}
          {persistedDenied && canUndo && (
            <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
                    style={{ fontSize: 11 }} onClick={() => deny.remove(it.id)}>
              {busy ? 'Cofam…' : 'Cofnij odmowę'}
            </button>
          )}
          {canDenyNow && !denyingNow && (
            <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
                    style={{ fontSize: 11 }} onClick={() => deny.toggle(it.id)}>
              Odmów
            </button>
          )}
        </span>
      </div>
      {/* Komentarz do odmowy — zapisany (read-only) albo wpisywany teraz. */}
      {persistedDenied && it.deny_comment && (
        <div style={{ fontSize: 11, color: 'var(--color-error-text)', marginTop: 3 }}>
          Powód odmowy: {it.deny_comment}
        </div>
      )}
      {denyingNow && (
        <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', gap: 6 }}>
          <input className="form-control" style={{ fontSize: 12 }}
                 placeholder="Powód odmowy (opcjonalnie)" autoFocus disabled={busy}
                 value={deny.map[it.id] || ''}
                 onChange={e => deny.setComment(it.id, e.target.value)}
                 onKeyDown={e => { if (e.key === 'Enter' && canSave && !busy) deny.save(it.id) }} />
          {canSave ? (
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" className="btn btn--danger btn--sm" disabled={busy}
                      style={{ fontSize: 11 }} onClick={() => deny.save(it.id)}>
                {busy ? 'Zapisuję…' : 'Zapisz odmowę'}
              </button>
              <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
                      style={{ fontSize: 11 }} onClick={() => deny.toggle(it.id)}>
                Anuluj
              </button>
            </div>
          ) : (
            // Tryb zgodności: brak natychmiastowego zapisu → odmowa poleci z całą akcją.
            <button type="button" className="btn btn--ghost btn--sm"
                    style={{ fontSize: 11, alignSelf: 'flex-start' }}
                    onClick={() => deny.toggle(it.id)}>
              Cofnij odmowę
            </button>
          )}
        </div>
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

function Group({ kind, items, deny, fulfill }) {
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
              {g.subgroups.map(sg => (
                <div key={sg.subgroup_name || '_nosub'}>
                  {sg.subgroup_name && (
                    <div style={{
                      padding: '3px 12px 3px 40px', fontSize: 10.5,
                      letterSpacing: '.02em', fontStyle: 'italic',
                      color: 'var(--color-text-muted)', background: 'var(--bg-primary)',
                      borderTop: '0.5px solid var(--color-border)',
                    }}>
                      ↳ {sg.subgroup_name}
                    </div>
                  )}
                  {sg.items.map(it => (
                    <PermRow key={it.id ?? `${it.system_id}:${it.permission_id}`}
                             it={it} isRevoke={isRevoke} deny={deny} fulfill={fulfill} />
                  ))}
                </div>
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
  if (st === 'revoke') return <span className="badge badge--error"   style={{ fontSize: 10 }}>− odebranie</span>
  if (st === 'grant')  return <span className="badge badge--success" style={{ fontSize: 10 }}>+ nadanie</span>
  if (st === 'kept')   return <span className="badge badge--neutral" style={{ fontSize: 10 }}>posiada</span>
  return null
}
