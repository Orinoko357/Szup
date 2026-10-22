import { useEffect, useRef, useState } from 'react'
import { promptDialog } from './ui/feedback'

/**
 * Kontrolka doprecyzowująca POJEDYNCZE uprawnienie na wniosku.
 *
 * Uprawnienia dzielą się na dwa rodzaje i oba stoją na jednej liście:
 *   - z importu z systemu dziedzinowego → zwykły checkbox (`input.type === 'none'`),
 *   - dodane ręcznie przez IT → checkbox + lista wyboru albo pole do wpisania.
 *
 * Kontrolka pojawia się dopiero po ZAZNACZENIU uprawnienia — także przy
 * pozycji już posiadanej, żeby dało się zmienić samą wartość bez odbierania
 * i nadawania od nowa. Przy pozycjach odbieranych nie ma jej wcale.
 */
export default function PermInput({ input, name, show, values, onChange, compact = false }) {
  const type = input?.type || 'none'
  if (!show || type === 'none') return null
  const fs = compact ? 12 : 13
  const opts = input?.options || []
  const val = values?.[name] ?? ''
  const set = v => onChange(name, v)

  return (
    <div style={{
      marginLeft: compact ? 20 : 26, marginTop: 4, marginBottom: 6,
      padding: compact ? '6px 8px' : '8px 10px', border: '1px solid var(--color-border)',
      background: 'var(--color-card)', borderRadius: 6,
    }}>
      {/* Co wpisać/wybrać — najpierw podpowiedź (prompt), potem ewentualny opis. */}
      {input?.prompt && (
        <div style={{ fontSize: 12, color: 'var(--color-heading)', fontWeight: 600, marginBottom: 3 }}>
          {input.prompt}
        </div>
      )}
      {input?.description && input.description !== input.prompt && (
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 3 }}>
          {input.description}
        </div>
      )}
      {type === 'multiselect' ? (
        <MultiSelect options={opts} value={val} onChange={set} fontSize={fs} />
      ) : type === 'radio' ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px' }}>
          {opts.map(o => (
            <label key={o} style={{
              display: 'flex', alignItems: 'center', gap: 5,
              fontSize: fs, cursor: 'pointer', userSelect: 'none',
            }}>
              <input type="radio" checked={val === o} onChange={() => set(o)} />
              {o}
            </label>
          ))}
        </div>
      ) : type === 'select' ? (
        <select className="form-control" style={{ fontSize: fs }}
                value={val} onChange={e => set(e.target.value)}>
          <option value="">— wybierz —</option>
          {opts.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      ) : type === 'textarea' ? (
        <textarea className="form-control" style={{ fontSize: fs, minHeight: 60 }}
                  placeholder={input?.prompt || ''}
                  value={val} onChange={e => set(e.target.value)} />
      ) : (
        <input className="form-control" style={{ fontSize: fs }}
               placeholder={input?.prompt || ''}
               value={val} onChange={e => set(e.target.value)} />
      )}
    </div>
  )
}


/**
 * Kafel oprogramowania na wniosku — wspólna oprawa dla OBU sposobów
 * opisania uprawnień: listy predefiniowanej i pól wnioskodawcy.
 *
 * Dzięki temu kierownik widzi zawsze to samo: ramkę z nazwą programu,
 * checkboxem i sekcjami w środku. Różnica jest tylko w tym, co robi
 * checkbox w nagłówku:
 *   - program opisany polami → zaznacza sam program (to jest pozycja wniosku),
 *   - program z listą uprawnień → zaznacza/odznacza wszystkie jego pozycje
 *     (stan pośredni, gdy część jest wybrana). NIE tworzy osobnej pozycji
 *     „dostęp do programu" — inaczej zmieniłoby to znaczenie wniosku.
 */
export function SystemBlock({
  name, badges, description, checked, indeterminate = false, onToggle,
  headerStyle, compact = false, showCheckbox = true, children,
  locked = false, lockedHint = null, accent = null,
}) {
  const box = useRef(null)
  useEffect(() => {
    if (box.current) box.current.indeterminate = indeterminate && !checked
  }, [indeterminate, checked])

  // Akcent (v3.0, wg projektu): wewnętrzny pasek po lewej + kolor obramowania —
  // zielony dla nadania, czerwony dla odebrania, granatowy dla zaznaczonego programu.
  const accentStyle = accent === 'grant'
    ? { borderColor: 'var(--color-success)', boxShadow: 'inset 3px 0 0 var(--color-success)' }
    : accent === 'revoke'
    ? { borderColor: 'var(--color-error)', boxShadow: 'inset 3px 0 0 var(--color-error)', background: 'var(--color-error-bg)' }
    : (checked || indeterminate)
    ? { boxShadow: 'inset 3px 0 0 var(--color-heading)' }
    : {}

  // Program z listą uprawnień NIE ma zbiorczego checkboxa — zaznaczanie jest
  // per grupa. Checkbox nagłówka zostaje tylko tam, gdzie sam program jest
  // pojedynczą pozycją wniosku („tylko dostęp" / pola wnioskodawcy).
  const Header = showCheckbox ? 'label' : 'div'
  return (
    <div style={{
      border: '1px solid var(--color-border-strong, var(--color-border))', borderRadius: 8, overflow: 'hidden',
      marginBottom: 10, background: 'var(--color-card)', ...accentStyle,
    }}>
      <Header style={{
        display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10,
        cursor: showCheckbox ? 'pointer' : 'default',
        padding: compact ? '9px 12px 9px 16px' : '12px 14px 12px 18px',
        fontWeight: 700, fontSize: compact ? 13 : 14, ...headerStyle,
      }}>
        {showCheckbox && (
          <input ref={box} type="checkbox" checked={checked} onChange={onToggle}
                 style={{ width: 18, height: 18, flexShrink: 0, accentColor: 'var(--color-heading)' }} />
        )}
        <span style={{ color: 'var(--color-text)' }}>{name}</span>
        <span style={{ flex: 1 }} />
        {badges}
      </Header>
      {description && (
        <div style={{
          fontSize: 12, color: 'var(--color-text-muted)',
          padding: compact ? '0 12px 6px 44px' : '0 14px 8px 46px', marginTop: -4,
        }}>
          {description}
        </div>
      )}
      <div style={{ padding: compact ? '0 12px 10px 16px' : '0 14px 12px 18px' }}>
        {locked && lockedHint && (
          <div style={{
            fontSize: 12, color: 'var(--color-text-muted)', fontStyle: 'italic',
            padding: '2px 0 6px',
          }}>
            {lockedHint}
          </div>
        )}
        <div style={locked ? {
          opacity: 0.45, pointerEvents: 'none', filter: 'grayscale(0.4)', userSelect: 'none',
        } : undefined}>
          {children}
        </div>
      </div>
    </div>
  )
}

/**
 * Lista wielokrotnego wyboru — checkboxy zamiast `<select multiple>`, bo to
 * czytelniejsze i nie wymaga trzymania Ctrl przy klikaniu.
 *
 * Wartość jest tekstem rozdzielonym przecinkami (tak samo jak w bazie), więc
 * pole zachowuje się jak każde inne z punktu widzenia formularza i walidacji.
 */
function MultiSelect({ options, value, onChange, fontSize }) {
  const picked = String(value || '')
    .split(',').map(s => s.trim()).filter(Boolean)

  function toggle(opt) {
    const next = picked.includes(opt)
      ? picked.filter(p => p !== opt)
      // Kolejność zgodna z definicją pola — niezależna od kolejności klikania.
      : options.filter(o => o === opt || picked.includes(o))
    onChange(next.join(', '))
  }

  if (options.length === 0) {
    return <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
      Brak zdefiniowanych opcji.
    </div>
  }
  return (
    <div style={{
      display: 'flex', flexWrap: 'wrap', gap: '4px 14px',
      border: '1px solid var(--color-border)', borderRadius: 4,
      padding: '6px 8px', background: 'var(--color-card)',
    }}>
      {options.map(o => (
        <label key={o} style={{
          display: 'flex', alignItems: 'center', gap: 5,
          fontSize, cursor: 'pointer', userSelect: 'none',
        }}>
          <input type="checkbox" checked={picked.includes(o)}
                 onChange={() => toggle(o)} />
          {o}
        </label>
      ))}
    </div>
  )
}


/**
 * Rozdziel listę uprawnień systemu na zwykłe pozycje i „super uprawnienia".
 *
 * Pozycja administratora jest utrzymywana automatycznie przy KAŻDYM
 * oprogramowaniu (o ile nie odznaczono jej w rejestrze), więc nie może być
 * mieszana ze zwykłą listą — w systemach „tylko dostęp" i opisywanych polami
 * lista ma dokładnie jedną pozycję i admin dopisałby się jako druga, myląca.
 *
 * Rozpoznajemy po fladze z API (`is_admin_option`), nie po polskiej nazwie.
 */
export function splitAdminPerm(perms) {
  const list = Array.isArray(perms) ? perms : []
  return {
    main: list.filter(p => !p.is_admin_option),
    admin: list.find(p => p.is_admin_option) || null,
  }
}

/**
 * Checkbox „Uprawnienia administratora" — wspólny dla wszystkich ścieżek
 * wyboru zakresu, żeby wyglądał i zachowywał się wszędzie tak samo.
 */
export function AdminPermRow({ perm, checked, onToggle, indent = 20, extra = null,
                               disabled = false }) {
  if (!perm) return null
  return (
    <label style={{
      display: 'flex', alignItems: 'center', gap: 10, fontSize: 13, minHeight: 34,
      cursor: disabled ? 'not-allowed' : 'pointer', marginLeft: indent, marginTop: 3,
      opacity: disabled ? 0.45 : 1,
    }} title={disabled
      ? 'Najpierw zaznacz program, aby móc wybrać uprawnienia administratora'
      : 'Pełne uprawnienia administracyjne — nadawaj tylko, gdy to konieczne'}>
      <input type="checkbox" checked={checked} disabled={disabled}
             onChange={disabled ? undefined : onToggle} />
      <span style={{ color: 'var(--color-error-text)', fontWeight: 600 }}>
        {perm.permission_name}
      </span>
      {extra}
    </label>
  )
}


/**
 * Podział uprawnień systemu na grupy (np. „Rejestry opłat").
 *
 * Programy dziedzinowe potrafią mieć setki pozycji zaimportowanych z kilku
 * list — bez podziału na sekcje wybór uprawnień jest nie do przejścia.
 * Pozycje bez grupy (dodane ręcznie) idą pierwsze, pod pustą nazwą.
 */
export function groupPerms(perms) {
  const map = new Map()
  const orderOf = new Map()   // grupa → ustawiona kolejność (group_order)
  for (const p of (perms || [])) {
    const g = p.group_name || ''
    if (!map.has(g)) map.set(g, [])
    map.get(g).push(p)
    const go = p.group_order
    if (go != null && (!orderOf.has(g) || go < orderOf.get(g))) orderOf.set(g, go)
  }
  return [...map.entries()]
    .sort(([a], [b]) => {
      // Pozycje bez grupy zawsze na górze.
      if (a === '') return -1
      if (b === '') return 1
      // Grupy z ustawioną kolejnością wg group_order; reszta alfabetycznie za nimi.
      const oa = orderOf.has(a) ? orderOf.get(a) : Infinity
      const ob = orderOf.has(b) ? orderOf.get(b) : Infinity
      if (oa !== ob) return oa - ob
      return a.localeCompare(b, 'pl')
    })
    .map(([group, items]) => ({ group, items }))
}

/**
 * Podział pozycji JEDNEJ grupy na podgrupy (drugi poziom sekcji).
 * Pozycje bez podgrupy idą pierwsze, pod pustą nazwą; dalej podgrupy wg
 * `subgroup_order`, a reszta alfabetycznie. Zwraca [{ subgroup, items }].
 */
export function subgroupPerms(perms) {
  const map = new Map()
  const orderOf = new Map()
  for (const p of (perms || [])) {
    const sg = p.subgroup_name || ''
    if (!map.has(sg)) map.set(sg, [])
    map.get(sg).push(p)
    const so = p.subgroup_order
    if (so != null && (!orderOf.has(sg) || so < orderOf.get(sg))) orderOf.set(sg, so)
  }
  return [...map.entries()]
    .sort(([a], [b]) => {
      if (a === '') return -1
      if (b === '') return 1
      const oa = orderOf.has(a) ? orderOf.get(a) : Infinity
      const ob = orderOf.has(b) ? orderOf.get(b) : Infinity
      if (oa !== ob) return oa - ob
      return a.localeCompare(b, 'pl')
    })
    .map(([subgroup, items]) => ({ subgroup, items }))
}

/**
 * Lista unikalnych nazw podgrup w zestawie pozycji (do podpowiedzi `datalist`).
 */
export function subgroupNames(perms) {
  const set = new Set()
  for (const p of (perms || [])) {
    const sg = (p.subgroup_name || '').trim()
    if (sg) set.add(sg)
  }
  return [...set].sort((a, b) => a.localeCompare(b, 'pl'))
}

/**
 * Czy pozycję pokazać wnioskodawcy. Wygaszone (wycofane ze źródła) znikają
 * z wyboru — CHYBA że pracownik je posiada albo są zaznaczone na wniosku.
 * Bez tego posiadane uprawnienie zniknęłoby z ekranu i wyglądałoby na odbierane.
 */
export function isPermVisible(p, key, held, picked) {
  if (p.is_active !== false) return true
  return Boolean(held?.has?.(key) || picked?.has?.(key))
}

/**
 * Zwijana sekcja grupy uprawnień: nagłówek z licznikiem zaznaczonych,
 * szukajka w obrębie grupy i zaznaczanie hurtem widocznych pozycji.
 *
 * Rozwija się sama, gdy zawiera zaznaczone pozycje — inaczej kierownik
 * nie zobaczyłby, że wniosek już coś z tej grupy obejmuje.
 */
export function PermGroupSection({
  group, count, selectedCount, children, onToggleAll, compact = false,
  query, onQuery, searchable = true,
}) {
  const [open, setOpen] = useState(selectedCount > 0)
  const wasSelected = useRef(selectedCount > 0)
  useEffect(() => {
    if (selectedCount > 0 && !wasSelected.current) setOpen(true)
    wasSelected.current = selectedCount > 0
  }, [selectedCount])

  // Pojedyncza grupa bez nazwy = program bez importu. Nie ma czego zwijać.
  if (!group && count <= 12) return children

  const fs = compact ? 12 : 13
  return (
    <div style={{
      borderRadius: 6, marginBottom: 6, background: 'var(--color-table-head)',
    }}>
      <div style={{
        display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, padding: '4px 10px',
        userSelect: 'none',
      }}>
        <button type="button" aria-expanded={open} onClick={() => setOpen(v => !v)}
                style={{
                  minHeight: 36, display: 'inline-flex', alignItems: 'center', gap: 6,
                  border: 0, background: 'transparent', padding: 0, cursor: 'pointer',
                  font: 'inherit', fontSize: fs, fontWeight: 700, color: 'var(--color-text)',
                }}>
          <span aria-hidden="true" style={{ width: 12, color: 'var(--color-text-muted)' }}>{open ? '▾' : '▸'}</span>
          {group || 'Uprawnienia'}
          <span style={{ padding: '0 7px', borderRadius: 9, fontSize: 11, fontWeight: 700,
                         background: 'var(--color-neutral-bg)', color: 'var(--color-neutral-text)' }}>{count}</span>
        </button>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          {selectedCount > 0 ? `zaznaczone: ${selectedCount}` : 'brak'}
        </span>
        {/* Zaznacz/odznacz WSZYSTKIE w tej grupie (nie w całym programie). */}
        {onToggleAll && count > 1 && (
          <button type="button" className="btn btn--ghost btn--sm"
                  style={{ fontSize: 12, minHeight: 32 }}
                  onClick={e => { e.stopPropagation(); setOpen(true); onToggleAll() }}>
            {selectedCount >= count ? 'Odznacz wszystkie' : 'Zaznacz wszystkie'}
          </button>
        )}
      </div>
      {open && (
        <div style={{ padding: '2px 10px 10px 32px' }}>
          {searchable && count > 12 && (
            <div style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
              <input className="form-control" style={{ fontSize: fs, flex: 1 }}
                     placeholder="Szukaj w grupie…"
                     value={query} onChange={e => onQuery(e.target.value)} />
            </div>
          )}
          {children}
        </div>
      )}
    </div>
  )
}


/**
 * Nazwy systemów, dla których wśród `keys` znalazły się uprawnienia
 * administracyjne. `permsBySys`: { system_id: [uprawnienia] }.
 */
export function adminGrantNames(keys, systems, permsBySys) {
  const names = []
  for (const k of keys) {
    const [sid, pid] = String(k).split(':').map(Number)
    const p = (permsBySys[sid] || []).find(x => x.id === pid)
    if (!p?.is_admin_option) continue
    names.push(systems.find(s => s.id === sid)?.name || `system #${sid}`)
  }
  return [...new Set(names)]
}

/**
 * Twarde potwierdzenie nadania uprawnień administracyjnych.
 *
 * Świadomie NIE jest to zwykłe „OK/Anuluj" — konto administracyjne w systemie
 * dziedzinowym to najpoważniejsze uprawnienie, jakie urząd nadaje, więc
 * wymagamy przepisania słowa. To wyklucza przypadkowe wysłanie wniosku
 * (np. odruchowe kliknięcie w potwierdzenie).
 *
 * Zwraca (asynchronicznie) `true` tylko po wpisaniu POTWIERDZAM i zatwierdzeniu.
 * v3.1: zamiast systemowego `window.prompt` — okno aplikacji (promptDialog).
 */
export async function confirmAdminRights(names) {
  if (names.length === 0) return true
  const answer = await promptDialog({
    title: 'Uprawnienia administracyjne',
    message: 'Próbujesz wysłać wniosek o uprawnienia administracyjne dla:\n\n'
      + names.map(n => `  • ${n}`).join('\n')
      + '\n\nTo najpoważniejsze uprawnienie w systemie dziedzinowym. Aby potwierdzić, wpisz POTWIERDZAM.',
    label: 'Potwierdzenie',
    requiredText: 'POTWIERDZAM',
    confirmLabel: 'Potwierdzam i wysyłam',
    danger: true,
  })
  return (answer || '').trim().toUpperCase() === 'POTWIERDZAM'
}

/** Komunikat po nieudanym/anulowanym potwierdzeniu — jeden dla całej aplikacji. */
export const ADMIN_CONFIRM_ABORTED =
  'Nie potwierdzono uprawnień administracyjnych — wniosek nie został wysłany. '
  + 'Aby kontynuować, wpisz POTWIERDZAM, albo odznacz te uprawnienia.'

/**
 * Czy program wymaga świadomego wyboru zakresu: flaga `require_scope` z rejestru,
 * dla programów z listą poduprawnień (nie „tylko dostęp"). Taki program jest na
 * wniosku domyślnie wyszarzony — trzeba zaznaczyć sam program, a potem wybrać
 * co najmniej jedno uprawnienie.
 */
export function isScopeGated(system) {
  return Boolean(system?.require_scope) && !system?.access_only
}

/**
 * Programy „scope-gated", które wnioskodawca AKTYWOWAŁ (zaznaczył sam program),
 * ale nie wybrał w nich żadnego uprawnienia. Zwraca nazwy — do zablokowania
 * wysyłki z czytelnym komunikatem.
 *
 * `openIds` — Set id systemów rozwiniętych przez wnioskodawcę.
 * `picked`  — Set kluczy „system_id:permission_id".
 * `permsBySys` — { system_id: [uprawnienia] }.
 */
export function missingScopeSystems(systems, openIds, picked, permsBySys = {}) {
  const out = []
  for (const s of (systems || [])) {
    if (!isScopeGated(s) || !openIds?.has?.(s.id)) continue
    // Dowolne zaznaczenie (uprawnienie zwykłe LUB administratora) liczy się jako
    // wybrany zakres — chodzi tylko o to, by program nie był pusty.
    const perms = permsBySys[s.id] || []
    const anyPicked = perms.some(p => picked.has(`${s.id}:${p.id}`))
    if (!anyPicked) out.push(s.name)
  }
  return out
}

/** Definicja kontrolki uprawnienia w formacie zwracanym przez API. */
export function permInput(p) {
  return {
    type: p?.input_type || 'none',
    options: p?.options || [],
    required: Boolean(p?.input_required),
    description: p?.description || null,
    // Podpowiedź „co wpisać" przy polu (ustawiana per uprawnienie w rejestrze).
    prompt: p?.input_prompt || null,
  }
}

/**
 * Uprawnienia wymagające uzupełnienia, a nie uzupełnione — dla zestawu
 * kluczy „system_id:permission_id". Zwraca etykiety „Program — Uprawnienie"
 * (backend waliduje to samo, ale lepiej powiedzieć od razu).
 */
export function missingRequiredFields(keys, systems, fieldValues, permsBySys = {}) {
  const miss = []
  for (const k of keys) {
    const [sid, pid] = k.split(':').map(Number)
    const p = (permsBySys[sid] || []).find(x => x.id === pid)
    if (!p?.input_required || (p.input_type || 'none') === 'none') continue
    const v = (fieldValues[k] || {})[p.permission_name]
    if (!v || !String(v).trim()) {
      const sys = systems.find(x => x.id === sid)
      miss.push(`${sys?.name || ''} — ${p.permission_name}`)
    }
  }
  return miss
}
