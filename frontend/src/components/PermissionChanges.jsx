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

import { useEffect, useRef } from 'react'
import { Check } from 'lucide-react'
import { fmtDateTimeShort as fmtDT } from '../serverTime'

// Tekst tooltipa badge'a: „Osoba — 12.10.2026, 14:30".
function actorTitle(name, iso) {
  const dt = fmtDT(iso)
  if (name && dt) return `${name} — ${dt}`
  return name || dt || undefined
}

function splitItems(items = []) {
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
export default function PermissionChanges({ items = [], emptyText = 'Brak', deny, fulfill, focusId }) {
  const { grants, revokes } = splitItems(items)
  if (items.length === 0) {
    return <div style={{ color: 'var(--color-text-muted)' }}>{emptyText}</div>
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {grants.length  > 0 && <Group kind="grant"  items={grants} deny={deny} fulfill={fulfill} focusId={focusId} />}
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

// v3.11 (Ś3): po „Zrobione” / „Cofnij” / „Cofnij odmowę” kliknięty przycisk znika
// (zastępuje go przycisk przeciwny) — fokus przechodzi na przycisk w tym samym wierszu,
// zamiast spaść na <body>. Przyciski w trakcie zapisu są aria-disabled (nie disabled),
// więc fokus nie ginie także w trakcie żądania.
const ROW_ACTIONS = ['undo', 'done', 'undo-deny', 'deny']

function PermRow({ it, isRevoke, deny, fulfill, crumb, focused }) {
  const rowRef = useRef(null)
  const pendingFocus = useRef(false)
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
  // Pozycje DO ODEBRANIA są przekreślone (jak przed v3.0), a ich wartości dodatkowe ukryte.
  const struck = isRevoke || persistedDenied || denyingNow
  const undecided = canFulfill && !persistedFulfilled && !persistedDenied && !denyingNow
  // Po zmianie stanu wiersza: jeśli fokus był na przycisku tego wiersza (zniknął),
  // ustaw go na pierwszym dostępnym przycisku akcji tego wiersza.
  useEffect(() => {
    if (!pendingFocus.current || busy) return
    const root = rowRef.current
    if (!root) return
    const a = document.activeElement
    const lost = !a || a === document.body || !a.isConnected
    if (!lost && root.contains(a)) { pendingFocus.current = false; return }
    if (!lost) { pendingFocus.current = false; return }
    for (const name of ROW_ACTIONS) {
      const b = root.querySelector(`[data-act="${name}"]`)
      if (b) { b.focus(); break }
    }
    pendingFocus.current = false
  }, [persistedFulfilled, persistedDenied, busy])
  // Kliknięcie w trakcie zapisu ignorujemy (aria-disabled zamiast disabled).
  const act = (fn) => () => { if (busy) return; pendingFocus.current = true; fn() }
  const busyProps = busy ? { 'aria-disabled': 'true' } : {}
  const rowBg = persistedFulfilled ? 'var(--color-success-bg)'
    : (persistedDenied || denyingNow || isRevoke) ? 'var(--color-error-bg)' : 'transparent'
  const btn = { minHeight: 38, fontSize: 13 }
  return (
    <div data-item-id={it.id ?? undefined} ref={rowRef}
         style={{ padding: '12px 14px', fontSize: 14,
                  borderTop: '1px solid var(--color-border)', background: rowBg,
                  // Fokus skrótów klawiaturowych (IT): wyraźna ramka wewnętrzna.
                  boxShadow: focused ? 'inset 0 0 0 2px var(--color-heading)' : 'none' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ flex: '1 1 240px', minWidth: 0 }}>
          {crumb && (
            <span style={{ display: 'block', fontSize: 11, fontWeight: 700, letterSpacing: '.07em',
                           textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
              {crumb}
            </span>
          )}
          <span style={{ display: 'block', fontWeight: 600,
                         textDecoration: struck ? 'line-through' : 'none',
                         color: struck ? 'var(--color-error-text)' : 'inherit' }}>
            {it.permission_name}
          </span>
          {persistedFulfilled && (it.fulfilled_by_name || it.fulfilled_at) && (
            <span style={{ display: 'block', fontSize: 12, color: 'var(--color-success-text)' }}>
              Zrobione{it.fulfilled_by_name ? ` · ${it.fulfilled_by_name}` : ''}{it.fulfilled_at ? ` · ${fmtDT(it.fulfilled_at)}` : ''}
            </span>
          )}
        </span>
        {it.added_by_name && (
          <span className="badge badge--warning"
                title={`Dodane przez IT: ${it.added_by_name}`}>
            dodane przez IT
          </span>
        )}
        {undecided && <span className="badge badge--neutral">bez decyzji</span>}
        {persistedDenied && (
          <span className="badge" style={{ background: 'var(--color-error)', color: '#fff' }}
                title={actorTitle(it.denied_by_name, it.denied_at)}>
            odmówiono
          </span>
        )}
        {persistedFulfilled && (
          <span className="badge" style={{ background: 'var(--color-success)', color: '#fff' }}
                title={actorTitle(it.fulfilled_by_name, it.fulfilled_at)}>
            <Check size={11} aria-hidden="true" style={{ verticalAlign: '-1px', marginRight: 3 }} />zrealizowano
          </span>
        )}
        {/* Przyciski akcji — po prawej. */}
        {persistedFulfilled && canFulfill && (
          <button type="button" className="btn btn--ghost btn--sm" data-act="undo" {...busyProps}
                  style={btn} onClick={act(() => fulfill.set(it.id, false))}
                  aria-label={`Cofnij realizację: ${it.permission_name}`}>
            {busy ? 'Cofam…' : 'Cofnij'}
          </button>
        )}
        {undecided && (
          <button type="button" className="btn btn--success btn--sm" data-act="done" {...busyProps}
                  style={btn} onClick={act(() => fulfill.set(it.id, true))}
                  aria-label={`Oznacz jako zrobione: ${it.permission_name}`}>
            {busy ? 'Zapisuję…' : <><Check size={14} aria-hidden="true" /> Zrobione</>}
          </button>
        )}
        {persistedDenied && canUndo && (
          <button type="button" className="btn btn--ghost btn--sm" data-act="undo-deny" {...busyProps}
                  style={btn} onClick={act(() => deny.remove(it.id))}
                  aria-label={`Cofnij odmowę: ${it.permission_name}`}>
            {busy ? 'Cofam…' : 'Cofnij odmowę'}
          </button>
        )}
        {canDenyNow && !denyingNow && (
          <button type="button" className="btn btn--ghost btn--sm" data-act="deny" {...busyProps}
                  style={btn} onClick={act(() => deny.toggle(it.id))}
                  aria-label={`Odmów: ${it.permission_name}`}>
            Odmów
          </button>
        )}
      </div>
      {/* Komentarz do odmowy — zapisany (read-only) albo wpisywany teraz. */}
      {persistedDenied && it.deny_comment && (
        <div style={{ marginTop: 8, padding: '8px 12px', borderRadius: 6, fontSize: 13,
                      background: 'var(--color-card)', border: '1px solid var(--color-error)' }}>
          <strong style={{ color: 'var(--color-error-text)' }}>Powód odmowy:</strong> {it.deny_comment}
        </div>
      )}
      {denyingNow && (
        <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
          <input className="form-control" style={{ fontSize: 13, flex: '1 1 260px' }}
                 placeholder="Powód odmowy (opcjonalnie)" autoFocus disabled={busy}
                 aria-label="Powód odmowy"
                 value={deny.map[it.id] || ''}
                 onChange={e => deny.setComment(it.id, e.target.value)}
                 onKeyDown={e => { if (e.key === 'Enter' && canSave && !busy) deny.save(it.id) }} />
          {canSave ? (
            <>
              <button type="button" className="btn btn--danger btn--sm" {...busyProps}
                      style={btn} onClick={act(() => deny.save(it.id))}>
                {busy ? 'Zapisuję…' : 'Zapisz odmowę'}
              </button>
              <button type="button" className="btn btn--ghost btn--sm" disabled={busy}
                      style={btn} onClick={() => deny.toggle(it.id)}>
                Anuluj
              </button>
            </>
          ) : (
            // Tryb zgodności: brak natychmiastowego zapisu → odmowa poleci z całą akcją.
            <button type="button" className="btn btn--ghost btn--sm"
                    style={btn} onClick={() => deny.toggle(it.id)}>
              Cofnij odmowę
            </button>
          )}
        </div>
      )}
      {cv.length > 0 && !struck && (
        <div style={{ marginTop: 4 }}>
          {cv.map(([k, v]) => (
            <div key={k} style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
              <span style={{ fontWeight: 600 }}>{k}:</span>{' '}
              <span style={{ whiteSpace: 'pre-wrap' }}>{v}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function Group({ kind, items, deny, fulfill, focusId }) {
  const isRevoke = kind === 'revoke'
  const color = isRevoke ? 'var(--color-error)'      : 'var(--color-success)'
  const text  = isRevoke ? 'var(--color-error-text)' : 'var(--color-success-text)'
  const bg    = isRevoke ? 'var(--color-error-bg)'   : 'var(--color-success-bg)'
  const label = isRevoke ? 'Do odebrania' : 'Do nadania'
  const sign  = isRevoke ? '−' : '+'
  const systems = groupBySystemAndGroup(items)
  // v3.0 (wg projektu): pasmo kierunku, a w wierszu nad nazwą uprawnienia
  // ścieżka „PROGRAM · GRUPA · PODGRUPA” zamiast osobnych pasm nagłówków.
  return (
    <div style={{ border: `1px solid ${color}`, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 14px',
                    background: bg, color: text, fontWeight: 800, fontSize: 13 }}>
        <span aria-hidden="true" style={{ width: 18, height: 18, borderRadius: 4, background: color,
                                          color: '#fff', display: 'grid', placeItems: 'center' }}>{sign}</span>
        {label} · {items.length}
      </div>
      {systems.map(sys => sys.groups.map(g => g.subgroups.map(sg => sg.items.map(it => (
        <PermRow key={it.id ?? `${it.system_id}:${it.permission_id}`}
                 it={it} isRevoke={isRevoke} deny={deny} fulfill={fulfill}
                 focused={focusId != null && focusId === it.id}
                 crumb={[sys.system_name, g.group_name, sg.subgroup_name].filter(Boolean).join(' · ')} />
      )))))}
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
    padding: '3px 6px', borderRadius: 4,
  }
  if (st === 'grant') return {
    background: 'var(--color-success-bg)',
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
  if (st === 'revoke') return <span className="badge badge--error"   style={{ fontSize: 11 }}>− odebranie</span>
  if (st === 'grant')  return <span className="badge badge--success" style={{ fontSize: 11 }}>+ nadanie</span>
  if (st === 'kept')   return <span className="badge badge--neutral" style={{ fontSize: 11 }}>posiada</span>
  return null
}
