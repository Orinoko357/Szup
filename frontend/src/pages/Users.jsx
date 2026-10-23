import { Fragment, useEffect, useId, useRef, useState } from 'react'
import {
  Plus, Trash2, KeyRound, Unlock, Ban, Building2, Check, X,
  ChevronRight, ChevronDown, FolderTree, Users as UsersIcon, UserCog, Lock,
} from 'lucide-react'
import {
  listUsers, createUser, updateUser, deleteUser, resetUserPassword, unlockUser,
  listAllDepartments, listActiveUnits, autoAssignManagers,
 errorMessage} from '../api'
import { LdapUsersImportModal } from './Units'
import { serverTs, serverNow, fmtDate } from '../serverTime'
import { toast, promptDialog, ask } from '../components/ui/feedback'
import { ROLE_META, ROLE_LABEL } from '../labels'
import { getUserRoles } from '../roles'
import Modal from '../components/ui/Modal'
import Field from '../components/ui/Field'
import { LoadError } from '../components/ui/LoadState'

/**
 * Wybór komórki organizacyjnej z WYSZUKIWANIEM i DRZEWEM.
 *
 * Przy kilkudziesięciu komórkach płaska lista natywnego <select> jest nie do
 * przejścia, a nazwy się powtarzają (np. „Dyrektor" w kilku jednostkach).
 * Dlatego:
 *  - podpowiedzi są pogrupowane po JEDNOSTCE (nagłówki jednostek na liście),
 *  - każda komórka pokazuje swoją ŚCIEŻKĘ w drzewie (np. „PM → SE → INF”),
 *    a etykieta wybranej pozycji zawiera też jednostkę („UM → PM → SE → INF”),
 *  - wpisanie fragmentu filtruje po całej ścieżce (jednostka + wszystkie
 *    poziomy + nazwa), a strzałki + Enter wybierają.
 * Wartość to `department_id` jako string ('' = nieprzypisany).
 */
function DeptCombo({ depts = [], units = [], value, onChange, className = 'form-control',
                     autoFocus = false, placeholder = '— brak (nieprzypisany) —',
                     id, 'aria-label': ariaLabel = 'Komórka organizacyjna' }) {
  // Wzorzec WAI-ARIA combobox + listbox: pole z role="combobox", lista z role="listbox",
  // podświetlona pozycja wskazywana przez aria-activedescendant (fokus zostaje w polu).
  const [open, setOpen] = useState(false)
  const [q, setQ]       = useState(null)   // null = nic nie wpisano (pole pokazuje wybraną wartość)
  const [hi, setHi]     = useState(0)
  const wrapRef = useRef(null)
  const listRef = useRef(null)
  const baseId  = useId()
  const listId  = `${baseId}-list`
  const optId   = i => `${baseId}-opt-${i}`

  const deptById = new Map(depts.map(d => [d.id, d]))
  const unitById = new Map(units.map(u => [u.id, u.name]))

  // Ścieżka komórki w drzewie (od korzenia do liścia), bez nazwy jednostki.
  function chainNames(d) {
    const out = []
    const seen = new Set()
    let cur = d
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id); out.unshift(cur.name)
      cur = cur.parent_dept_id ? deptById.get(cur.parent_dept_id) : null
    }
    return out
  }
  const unitName = d => unitById.get(d.unit_id) || ''
  const chainStr = d => chainNames(d).join(' → ')
  const fullStr  = d => {
    const u = unitName(d); const c = chainStr(d)
    return u ? `${u} → ${c}` : c
  }

  const selected = depts.find(d => String(d.id) === String(value))
  const label = selected ? fullStr(selected) : ''

  useEffect(() => {
    function onDoc(e) {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) { setOpen(false); setQ(null) }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const norm = s => (s || '').toString().toLowerCase()
  const query = (q || '').trim().toLowerCase()
  // Dopasowanie po pełnej ścieżce (nazwa + jednostka) ORAZ po opisie z AD.
  const filtered = depts.filter(d => !query
    || norm(fullStr(d)).includes(query) || norm(d.description).includes(query))

  // Grupowanie po jednostce; jednostki i komórki alfabetycznie po ścieżce.
  const gMap = new Map()
  for (const d of filtered) {
    if (!gMap.has(d.unit_id)) gMap.set(d.unit_id, { name: unitById.get(d.unit_id) || '—', items: [] })
    gMap.get(d.unit_id).items.push(d)
  }
  const groups = [...gMap.values()].sort((a, b) => a.name.localeCompare(b.name, 'pl'))
  for (const g of groups) g.items.sort((a, b) => chainStr(a).localeCompare(chainStr(b), 'pl'))

  // Płaska lista nawigowalna (nagłówki jednostek NIE są nawigowalne).
  const ordered = groups.flatMap(g => g.items)
  const options = [{ _clear: true }, ...ordered]
  const idxOf = new Map()
  options.forEach((o, i) => { if (!o._clear) idxOf.set(o, i) })
  // Na starcie podświetlona jest bieżąca wartość.
  const selectedIdx = () => Math.max(0, options.findIndex(o => !o._clear && String(o.id) === String(value)))

  function openList() { setOpen(true); setHi(selectedIdx()) }
  function close() { setOpen(false); setQ(null) }

  function pick(opt) {
    onChange(opt._clear ? '' : String(opt.id))
    close(); setHi(0)
  }

  function onKey(e) {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || (e.key === 'Enter' && !e.altKey)) {
        e.preventDefault(); openList()
      }
      return
    }
    if (e.key === 'ArrowDown')      { e.preventDefault(); setHi(h => Math.min(h + 1, options.length - 1)) }
    else if (e.key === 'ArrowUp')   { e.preventDefault(); setHi(h => Math.max(h - 1, 0)) }
    else if (e.key === 'Home' && q === null) { e.preventDefault(); setHi(0) }
    else if (e.key === 'End' && q === null)  { e.preventDefault(); setHi(options.length - 1) }
    else if (e.key === 'Enter')     { e.preventDefault(); if (options[hi]) pick(options[hi]) }
    // Escape zamyka tylko listę — nie całe okno, w którym leży pole.
    else if (e.key === 'Escape')    { e.preventDefault(); e.stopPropagation(); close() }
    else if (e.key === 'Tab')       { close() }
  }

  // Utrzymuj podświetloną pozycję w polu widzenia.
  useEffect(() => {
    const el = listRef.current?.querySelector(`[data-idx="${hi}"]`)
    if (el?.scrollIntoView) el.scrollIntoView({ block: 'nearest' })
  }, [hi, open])

  const rowStyle = (idx) => ({
    padding: '5px 10px', fontSize: 13, cursor: 'pointer',
    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
    background: idx === hi ? 'var(--bg-secondary)' : 'transparent',
    color: 'var(--color-text)',
    boxShadow: idx === hi ? 'inset 3px 0 0 var(--color-selected)' : 'none',
  })

  return (
    <div ref={wrapRef} style={{ position: 'relative', minWidth: 240 }}>
      <input
        id={id}
        className={className}
        style={{ fontSize: 13 }}
        role="combobox"
        aria-label={id ? undefined : ariaLabel}
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && options[hi] ? optId(hi) : undefined}
        autoComplete="off"
        autoFocus={autoFocus}
        value={q ?? label}
        placeholder={placeholder}
        onFocus={e => { openList(); e.target.select() }}
        onClick={() => { if (!open) openList() }}
        onChange={e => { setQ(e.target.value); setOpen(true); setHi(0) }}
        onKeyDown={onKey}
      />
      {open && (
        <div ref={listRef} id={listId} role="listbox" aria-label={ariaLabel} style={{
          position: 'absolute', zIndex: 40, top: '100%', left: 0, right: 0, marginTop: 2,
          minWidth: 300, maxHeight: 300, overflowY: 'auto', background: 'var(--bg-primary)',
          border: '1px solid var(--color-border)', borderRadius: 6,
          boxShadow: '0 8px 24px rgba(0,0,0,.14)',
        }}>
          <div data-idx={0} id={optId(0)} role="option" aria-selected={!selected}
               onMouseDown={e => { e.preventDefault(); pick({ _clear: true }) }}
               onMouseEnter={() => setHi(0)}
               style={{ ...rowStyle(0), color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
            {placeholder}
          </div>

          {groups.map(g => (
            <div key={g.name + (g.items[0]?.id ?? '')} role="group" aria-label={g.name}>
              <div role="presentation" style={{
                position: 'sticky', top: 0, zIndex: 1,
                padding: '4px 10px', fontSize: 11, fontWeight: 700,
                letterSpacing: '.03em', textTransform: 'uppercase',
                color: 'var(--color-heading)', background: 'var(--bg-secondary)',
                borderTop: '1px solid var(--color-border)',
              }}>
                {g.name}
              </div>
              {g.items.map(d => {
                const idx = idxOf.get(d)
                const chain = chainNames(d)
                const parents = chain.slice(0, -1)
                const leaf = chain[chain.length - 1]
                return (
                  <div key={d.id} data-idx={idx} id={optId(idx)} role="option"
                       aria-selected={selected?.id === d.id}
                       onMouseDown={e => { e.preventDefault(); pick(d) }}
                       onMouseEnter={() => setHi(idx)}
                       style={{ ...rowStyle(idx), paddingLeft: 14 + Math.max(0, parents.length) * 14 }}>
                    {parents.length > 0 && (
                      <span style={{ color: 'var(--color-text-muted)' }}>{parents.join(' → ')} → </span>
                    )}
                    <strong style={{ fontWeight: 600 }}>{leaf}</strong>
                  </div>
                )
              })}
            </div>
          ))}

          {filtered.length === 0 && (
            <div role="presentation" style={{ padding: '6px 10px', fontSize: 12, color: 'var(--color-text-muted)' }}>
              Brak komórek pasujących do „{(q || '').trim()}”.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// Etykiety i kolory ról wprost ze wspólnego słownika (labels.js) — te same,
// pisane tak samo jak w belce (bez lokalnej kopii ROLE_META).
// Role administracyjne nadaje i odbiera wyłącznie superadmin (backend odrzuca
// to samo — tu tylko nie pokazujemy opcji, których admin i tak nie zapisze).
const ADMIN_ROLES = ['superadmin', 'admin']
const ROLES = ['superadmin', 'admin', 'hr', 'manager', 'it_staff', 'viewer'].map(v => ({
  value: v, label: ROLE_LABEL[v] || v, badge: ROLE_META[v]?.badge || 'badge--neutral',
  superadminOnly: ADMIN_ROLES.includes(v),
}))

const isSuperadmin = () => getUserRoles().includes('superadmin')

// Jakie role może przypisywać zalogowany użytkownik
const assignableRoles = () => isSuperadmin() ? ROLES : ROLES.filter(r => !r.superadminOnly)

const ADMIN_ROLES_HINT = 'Role administracyjne (Administrator, Superadmin) nadaje i odbiera wyłącznie superadmin.'

/** Wyciąga czytelny komunikat błędu z odpowiedzi axiosa (FastAPI/Pydantic). */
function extractErr(ex) {
  if (!ex.response) {
    return ex.message ? `Błąd sieci: ${ex.message}` : 'Brak odpowiedzi z serwera (sprawdź połączenie)'
  }
  const d = ex.response.data?.detail
  if (typeof d === 'string') return d
  if (Array.isArray(d)) {
    // Pydantic 422 — lista obiektów {loc, msg, type}
    return d.map(e => `${(e.loc || []).slice(1).join('.') || 'pole'}: ${e.msg}`).join('; ')
  }
  if (d && typeof d === 'object') return JSON.stringify(d)
  return `HTTP ${ex.response.status} — ${ex.response.statusText || 'nieznany błąd serwera'}`
}

export default function Users() {
  const [users, setUsers] = useState([])
  const [depts, setDepts] = useState([])
  const [units, setUnits] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [filterUnit, setFilterUnit] = useState('')   // '' = wszystkie jednostki
  const [collapsed, setCollapsed] = useState(() => new Set())  // zwinięte sekcje
  const [showLdapUsersImport, setShowLdapUsersImport] = useState(false)
  const [autoBusy, setAutoBusy] = useState(false)
  const [loadErr, setLoadErr] = useState(null)

  // Przypisanie kierowników komórek wg stanowiska z AD (kierownik/dyrektor/naczelnik).
  // Stanowiska pobierają się przy imporcie użytkowników z AD.
  async function runAutoManagers() {
    if (!await ask('Przypisać kierowników komórek na podstawie stanowiska z AD '
      + '(„kierownik", „dyrektor", „naczelnik")?\n\n'
      + 'Uzupełnione zostaną tylko komórki BEZ kierownika; przy kilku kandydatach '
      + 'komórka zostaje do ręcznej decyzji. Najpierw zaimportuj użytkowników z AD '
      + '(stanowiska pobierają się przy imporcie).', { title: 'Potwierdź', confirmLabel: 'Przypisz kierowników' })) return
    setAutoBusy(true)
    try {
      const r = await autoAssignManagers({})
      const d = r.data
      toast(`Przypisano: ${d.assigned}\n`
        + `Pominięto (mają już kierownika): ${d.skipped_has_manager}\n`
        + `Niejednoznaczne (kilku kandydatów): ${d.ambiguous}\n`
        + `Bez kandydata: ${d.no_candidate}`
        + (d.details.length ? `\n\n${d.details.join('\n')}` : ''), { tone: 'info', timeout: 12000 })
      load()
    } catch (ex) {
      toast(errorMessage(ex, 'Nie udało się przypisać kierowników'), { tone: 'error' })
    } finally { setAutoBusy(false) }
  }

  function toggleCollapse(key) {
    setCollapsed(prev => {
      const n = new Set(prev)
      n.has(key) ? n.delete(key) : n.add(key)
      return n
    })
  }

  // Użytkownik należy do jednostki przez swoją komórkę organizacyjną.
  const unitOfDept = new Map(depts.map(d => [d.id, d.unit_id]))
  const visibleUsers = filterUnit
    ? users.filter(u => unitOfDept.get(u.department_id) === Number(filterUnit))
    : users

  // Podział listy DWUPOZIOMOWO: JEDNOSTKA → DZIAŁ (komórka pracownika).
  // Konta bez komórki (np. superadmin, świeże AD) trafiają do sekcji „Bez
  // jednostki". Dział opisujemy ścieżką w drzewie (np. „PM → SE → INF”), bo
  // same nazwy się powtarzają.
  const unitNameById = new Map(units.map(u => [u.id, u.name]))
  const deptById = new Map(depts.map(d => [d.id, d]))
  function deptChainStr(d) {
    const out = []; const seen = new Set(); let cur = d
    while (cur && !seen.has(cur.id)) {
      seen.add(cur.id); out.unshift(cur.name)
      cur = cur.parent_dept_id ? deptById.get(cur.parent_dept_id) : null
    }
    return out.join(' → ')
  }

  const userGroups = (() => {
    const uMap = new Map()   // unitKey -> { count, deptMap: Map(deptKey -> {label, users}) }
    for (const u of visibleUsers) {
      const dep = deptById.get(u.department_id)
      const uKey = dep?.unit_id ?? '_none'
      if (!uMap.has(uKey)) uMap.set(uKey, { count: 0, deptMap: new Map() })
      const grp = uMap.get(uKey); grp.count++
      const dKey = dep ? dep.id : '_nodept'
      if (!grp.deptMap.has(dKey)) {
        grp.deptMap.set(dKey, { label: dep ? deptChainStr(dep) : null, users: [] })
      }
      grp.deptMap.get(dKey).users.push(u)
    }
    return [...uMap.entries()]
      .map(([key, grp]) => ({
        key,
        name: key === '_none'
          ? 'Bez jednostki / nieprzypisani'
          : (unitNameById.get(key) || `Jednostka #${key}`),
        count: grp.count,
        depts: [...grp.deptMap.entries()]
          .map(([dKey, dg]) => ({ key: dKey, label: dg.label, users: dg.users }))
          .sort((a, b) => (a.label || '').localeCompare(b.label || '', 'pl')),
      }))
      .sort((a, b) =>
        a.key === '_none' ? 1 : b.key === '_none' ? -1 : a.name.localeCompare(b.name, 'pl'))
  })()

  function collapseAll() {
    const keys = new Set()
    for (const g of userGroups) {
      keys.add(`u:${g.key}`)
      for (const d of g.depts) if (d.label) keys.add(`d:${g.key}:${d.key}`)
    }
    setCollapsed(keys)
  }

  async function load() {
    setLoading(true); setLoadErr(null)
    try {
      // Słowniki komórek i jednostek są pomocnicze — ich błąd nie blokuje listy
      // kont, ale nie może przejść po cichu (puste filtry i grupowanie).
      const soft = (what) => (ex) => {
        toast(errorMessage(ex, `Nie udało się wczytać listy ${what}`) + ' — grupowanie i filtry mogą być niepełne.',
              { tone: 'warning' })
        return { data: [] }
      }
      const [rU, rD, rUn] = await Promise.all([
        listUsers(),
        listAllDepartments().catch(soft('komórek')),
        listActiveUnits().catch(soft('jednostek')),
      ])
      setUsers(rU.data); setDepts(rD.data); setUnits(rUn.data)
    } catch (ex) {
      setLoadErr(errorMessage(ex, 'Nie udało się wczytać listy użytkowników'))
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  // Domyślnie WSZYSTKIE jednostki zwinięte (jak w zakładce Jednostki) — ustawiane
  // raz, po pierwszym załadowaniu danych. Późniejsze odświeżenia nie resetują
  // tego, co użytkownik sam rozwinął.
  const didInitCollapse = useRef(false)
  useEffect(() => {
    if (!loading && !didInitCollapse.current && userGroups.length) {
      didInitCollapse.current = true
      setCollapsed(new Set(userGroups.map(g => `u:${g.key}`)))
    }
  }, [loading, userGroups])

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header__title">Użytkownicy</h1>
          <div className="page-header__sub">Zarządzanie kontami i rolami w systemie SZUP</div>
        </div>
        <button className="btn btn--action" onClick={() => setShowAdd(v => !v)}>
          <Plus size={14} /> Nowy użytkownik
        </button>
      </div>

      {/* v3.0 — pasek narzędzi: filtr jednostki + akcje masowe/importu. */}
      <div className="card" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10,
                                     padding: '12px 14px', marginBottom: 18 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, fontWeight: 600,
                        color: 'var(--color-text-muted)' }}>
          Jednostka
          <select
            className="form-control"
            style={{ maxWidth: 260, fontSize: 14 }}
            value={filterUnit}
            onChange={e => setFilterUnit(e.target.value)}
            title="Pokaż użytkowników z wybranej jednostki"
          >
            <option value="">Wszystkie jednostki</option>
            {units.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </label>
        <div style={{ flex: 1 }} />
        <button className="btn btn--ghost btn--sm"
                onClick={() => collapsed.size > 0 ? setCollapsed(new Set()) : collapseAll()}
                title="Zwiń lub rozwiń wszystkie sekcje">
          <FolderTree size={14} /> {collapsed.size > 0 ? 'Rozwiń wszystko' : 'Zwiń wszystko'}
        </button>
        <button className="btn btn--ghost btn--sm" onClick={runAutoManagers} disabled={autoBusy}
                title="Przypisz kierowników komórek wg stanowiska z AD (kierownik/dyrektor/naczelnik)">
          <UserCog size={14} /> {autoBusy ? 'Przypisywanie…' : 'Kierownicy wg stanowiska'}
        </button>
        <button className="btn btn--ghost btn--sm" onClick={() => setShowLdapUsersImport(true)}>
          <UsersIcon size={14} /> Importuj z AD
        </button>
      </div>

      {showLdapUsersImport && (
        <LdapUsersImportModal onClose={() => { setShowLdapUsersImport(false); load() }} />
      )}

      {filterUnit && !loading && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 10,
        }}>
          <Building2 size={13} />
          Pokazano {visibleUsers.length} z {users.length} — pracownicy jednostki
          {' '}<strong>{units.find(u => u.id === Number(filterUnit))?.name}</strong>.
          <button className="btn btn--ghost btn--sm" onClick={() => setFilterUnit('')}>
            <X size={12} /> Wyczyść filtr
          </button>
        </div>
      )}

      {showAdd && (
        <AddUserCard depts={depts} units={units}
                     onAdded={() => { setShowAdd(false); load() }} onCancel={() => setShowAdd(false)} />
      )}

      {loadErr && <LoadError message={loadErr} onRetry={load} busy={loading} style={{ marginBottom: 16 }} />}

      {loading ? (
        <div className="card"><div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div></div>
      ) : loadErr && users.length === 0 ? null : visibleUsers.length === 0 ? (
        <div className="card">
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>
            {users.length === 0
              ? 'Brak użytkowników. Zaimportuj konta z AD przyciskiem „Importuj z AD” albo dodaj konto przyciskiem „Nowy użytkownik”.'
              : 'Brak użytkowników przypisanych do tej jednostki.'}
          </div>
        </div>
      ) : (
        // Akordeon per JEDNOSTKA — spójnie z zakładką „Jednostki".
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {userGroups.map(g => {
            const uKey = `u:${g.key}`
            const unitOpen = !collapsed.has(uKey)
            return (
              <section key={`g-${g.key}`} aria-label={`Jednostka ${g.name}`}
                       style={{ background: 'var(--color-card)', border: '1px solid var(--color-border)',
                                borderRadius: 10, overflow: 'hidden' }}>
                <button type="button" aria-expanded={unitOpen} onClick={() => toggleCollapse(uKey)}
                        style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 10, minHeight: 52,
                                 padding: '0 18px', border: 0, borderBottom: unitOpen ? '1px solid var(--color-border)' : 0,
                                 background: 'var(--color-card)', font: 'inherit', color: 'inherit',
                                 cursor: 'pointer', textAlign: 'left' }}>
                  {unitOpen ? <ChevronDown size={18} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />
                            : <ChevronRight size={18} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />}
                  <Building2 size={17} aria-hidden="true" style={{
                    color: g.key === '_none' ? 'var(--color-text-muted)' : 'var(--color-heading)', flexShrink: 0 }} />
                  <strong style={{ fontSize: 16,
                                   color: g.key === '_none' ? 'var(--color-text-muted)' : 'var(--color-heading)' }}>
                    {g.name}
                  </strong>
                  <span className="badge badge--neutral">{g.count}</span>
                </button>

                {unitOpen && (
                  <div style={{ overflowX: 'auto' }}>
                    <table className="data-table" style={{ margin: 0, minWidth: 1300 }}>
                      <thead>
                        <tr>
                          <th>Login</th><th>Imię i nazwisko</th><th>E-mail</th><th>Rola</th>
                          <th>Komórka organizacyjna</th><th>Jednostki (kadry)</th><th>Typ</th>
                          <th>Status</th><th>Ostatnia zmiana hasła</th><th><span className="sr-only">Akcje</span></th>
                        </tr>
                      </thead>
                      <tbody>
                        {g.depts.map(d => {
                          // Sekcja bez działu (konta bez komórki) — bez nagłówka działu.
                          if (!d.label) {
                            return (
                              <Fragment key={`d-${g.key}-nodept`}>
                                {d.users.map(u => (
                                  <UserRow key={u.id} user={u} depts={depts} units={units} onChanged={load} />
                                ))}
                              </Fragment>
                            )
                          }
                          const dKey = `d:${g.key}:${d.key}`
                          const deptOpen = !collapsed.has(dKey)
                          return (
                            <Fragment key={`d-${g.key}-${d.key}`}>
                              <tr>
                                <td colSpan={10}
                                    style={{ padding: '4px 18px 4px 40px', background: 'var(--bg-secondary)' }}>
                                  {/* Przycisk zamiast klikalnej komórki — działa z klawiatury. */}
                                  <button type="button" aria-expanded={deptOpen}
                                          onClick={() => toggleCollapse(dKey)}
                                          style={{
                                            display: 'inline-flex', alignItems: 'center', gap: 8, minHeight: 36,
                                            padding: '0 6px', border: 0, borderRadius: 6, background: 'transparent',
                                            font: 'inherit', fontSize: 14, fontWeight: 700, color: 'var(--color-heading)',
                                            cursor: 'pointer', textAlign: 'left',
                                          }}>
                                    {deptOpen ? <ChevronDown size={16} aria-hidden="true" />
                                              : <ChevronRight size={16} aria-hidden="true" />}
                                    {d.label}
                                    <span className="badge badge--neutral" aria-label={`${d.users.length} kont`}>
                                      {d.users.length}
                                    </span>
                                  </button>
                                </td>
                              </tr>
                              {deptOpen && d.users.map(u => (
                                <UserRow key={u.id} user={u} depts={depts} units={units} onChanged={load} />
                              ))}
                            </Fragment>
                          )
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}

function UserRow({ user: u, depts = [], units = [], onChanged }) {
  const [editRoles, setEditRoles] = useState(false)
  const [selectedRoles, setSelectedRoles] = useState(u.roles || [u.role])
  const [editDept, setEditDept] = useState(false)
  const [deptId, setDeptId] = useState(u.department_id || '')
  const [editUnits, setEditUnits] = useState(false)

  const hasHrRole = (u.roles || [u.role]).includes('hr')
  // Zdolność HR z KOMÓRKI kadrowej (Department.is_hr) — bez roli per osoba.
  const deptHr = !!depts.find(d => d.id === u.department_id)?.is_hr
  const isLocked = u.locked_until && serverTs(u.locked_until) > serverNow()

  async function saveDept() {
    try {
      const r = await updateUser(u.id, { department_id: deptId ? Number(deptId) : null })
      // Backend może zwrócić informację (np. komórka ma już kierownika) —
      // zapis się udał, ale admin musi o tym wiedzieć.
      if (r.data?.warning) toast(r.data.warning, { tone: 'warning' })
      setEditDept(false); onChanged()
    } catch (ex) { toast(errorMessage(ex, 'Błąd przypisania komórki'), { tone: 'error' }) }
  }

  function toggleRole(rv) {
    setSelectedRoles(prev =>
      prev.includes(rv) ? prev.filter(r => r !== rv) : [...prev, rv]
    )
  }

  async function saveRoles() {
    if (!selectedRoles.length) { toast('Wybierz co najmniej jedną rolę', { tone: 'warning' }); return }
    try {
      const r = await updateUser(u.id, { roles: selectedRoles })
      if (r.data?.warning) toast(r.data.warning, { tone: 'warning' })
      setEditRoles(false); onChanged()
    }
    catch (ex) { toast(errorMessage(ex, 'Błąd zmiany roli'), { tone: 'error' }) }
  }

  async function toggleActive() {
    if (u.is_active && !await ask(
      `Dezaktywować konto „${u.username}”? Użytkownik nie zaloguje się do systemu.`,
      { title: 'Dezaktywacja konta', confirmLabel: 'Dezaktywuj konto', danger: true })) return
    try {
      await updateUser(u.id, { is_active: !u.is_active }); onChanged()
      toast(u.is_active ? `Dezaktywowano konto „${u.username}”` : `Aktywowano konto „${u.username}”`)
    }
    catch (ex) { toast(errorMessage(ex, 'Nie udało się zmienić statusu konta'), { tone: 'error' }) }
  }

  async function handleReset() {
    const pw = await promptDialog({
      title: `Reset hasła — ${u.username}`,
      message: 'Min. 12 znaków, 3 z 4 klas (małe/WIELKIE/cyfry/specjalne).\nUżytkownik będzie musiał je zmienić przy następnym logowaniu.',
      label: 'Nowe hasło', type: 'password', confirmLabel: 'Ustaw hasło',
    })
    if (!pw) return
    try { await resetUserPassword(u.id, pw); onChanged(); toast(`Hasło użytkownika ${u.username} zostało zresetowane`) }
    catch (ex) { toast(errorMessage(ex, 'Błąd resetowania hasła'), { tone: 'error' }) }
  }

  async function handleUnlock() {
    try { await unlockUser(u.id); onChanged(); toast(`Odblokowano konto „${u.username}”`) }
    catch (ex) { toast(errorMessage(ex, 'Nie udało się odblokować konta'), { tone: 'error' }) }
  }

  async function handleDelete() {
    if (!await ask(`Usunąć konto "${u.username}"?`, { title: 'Potwierdź operację', confirmLabel: 'Usuń konto', danger: true })) return
    try { await deleteUser(u.id); onChanged(); toast(`Usunięto konto „${u.username}”`) }
    catch (ex) { toast(errorMessage(ex, 'Błąd usuwania'), { tone: 'error' }) }
  }

  return (
    <tr>
      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{u.username}</td>
      <td style={{ fontWeight: 600 }}>{u.full_name || '—'}</td>
      <td style={{ fontSize: 12 }}>
        {u.email
          ? <a href={`mailto:${u.email}`} style={{ color: 'var(--color-info-text)', textDecoration: 'none' }}>{u.email}</a>
          : <span style={{ color: 'var(--color-text-muted)' }}>—</span>}
      </td>
      <td>
        {editRoles ? (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            {assignableRoles().map(r => (
              <label key={r.value} style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 12, cursor: 'pointer' }}>
                <input type="checkbox" checked={selectedRoles.includes(r.value)}
                       onChange={() => toggleRole(r.value)} />
                {r.label}
              </label>
            ))}
            {/* Admin nie widzi ról administracyjnych — posiadane przez konto
                zostają bez zmian (zapis wysyła je dalej w selectedRoles). */}
            {!isSuperadmin() && selectedRoles.filter(rv => ADMIN_ROLES.includes(rv)).map(rv => (
              <span key={rv} className={`badge ${ROLE_META[rv]?.badge || 'badge--neutral'}`}
                    style={{ fontSize: 10, opacity: 0.85, display: 'inline-flex', alignItems: 'center', gap: 3 }}
                    title={ADMIN_ROLES_HINT}>
                {ROLE_LABEL[rv] || rv} <Lock size={10} aria-hidden="true" />
                <span className="sr-only">— {ADMIN_ROLES_HINT}</span>
              </span>
            ))}
            <button type="button" className="btn btn--primary btn--sm" onClick={saveRoles}
                    aria-label={`Zapisz role użytkownika ${u.username}`}>Zapisz</button>
            <button type="button" className="btn btn--ghost btn--sm" aria-label="Anuluj zmianę ról"
                    onClick={() => { setEditRoles(false); setSelectedRoles(u.roles || [u.role]) }}>Anuluj</button>
          </div>
        ) : (
          <button type="button" style={{ display: 'flex', flexWrap: 'wrap', gap: 3, cursor: 'pointer', border: 0,
                                         background: 'transparent', padding: 4, font: 'inherit', color: 'inherit',
                                         textAlign: 'left', minHeight: 32 }}
               onClick={() => setEditRoles(true)} title="Kliknij, aby zmienić role"
               aria-label={`Zmień role użytkownika ${u.username}`}>
            {(u.roles || [u.role]).map(rv => {
              const m = ROLE_META[rv]
              return m ? (
                <span key={rv} className={`badge ${m.badge}`} style={{ fontSize: 10 }}>{m.label}</span>
              ) : null
            })}
            {/* Zdolność HR z komórki kadrowej — bez roli przypisanej per osoba. */}
            {deptHr && !hasHrRole && (
              <span className={`badge ${ROLE_META.hr?.badge || 'badge--info'}`}
                    style={{ fontSize: 10, opacity: 0.85 }}
                    title="Zdolność HR wynika z przynależności do komórki kadrowej (bez roli przypisanej per osoba)">
                HR (kadry)
              </span>
            )}
          </button>
        )}
      </td>
      <td>
        {editDept ? (
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <DeptCombo depts={depts} units={units} value={deptId} onChange={setDeptId}
                       className="input input--sm" autoFocus
                       aria-label={`Komórka organizacyjna użytkownika ${u.username}`} />
            <button type="button" className="btn btn--primary btn--sm" onClick={saveDept} title="Zapisz"
                    aria-label="Zapisz komórkę">Zapisz</button>
            <button type="button" className="btn btn--ghost btn--sm" aria-label="Anuluj zmianę komórki"
                    onClick={() => { setEditDept(false); setDeptId(u.department_id || '') }} title="Anuluj">Anuluj</button>
          </div>
        ) : (
          <button type="button" style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12,
                                         border: 0, background: 'transparent', padding: 4, font: 'inherit',
                                         color: 'inherit', textAlign: 'left', minHeight: 32 }}
               onClick={() => setEditDept(true)} title="Kliknij, aby przypisać komórkę"
               aria-label={`Zmień komórkę użytkownika ${u.username}`}>
            <Building2 size={13} aria-hidden="true" style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
            {u.department_name
              ? <span>{u.department_name}</span>
              : <span style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>nieprzypisany</span>}
          </button>
        )}
      </td>

      {/* Jednostki obsługiwane — przypisanie dotyczy ROLI HR. Komórka kadrowa
          (is_hr) daje dostęp do CAŁEJ struktury, więc tam nie przypisujemy. */}
      <td>
        {deptHr && !hasHrRole ? (
          <span style={{ color: 'var(--color-text-muted)', fontSize: 12, fontStyle: 'italic' }}
                title="Komórka kadrowa — dostęp do wszystkich jednostek">
            cała struktura (kadry)
          </span>
        ) : !hasHrRole ? (
          <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>—</span>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            {(u.unit_ids || []).length === 0 ? (
              <span style={{ color: 'var(--color-warning-text, var(--color-warning))', fontSize: 12, fontStyle: 'italic' }}>
                brak — nie zobaczy żadnej
              </span>
            ) : (
              (u.unit_ids || []).map(id => {
                const un = units.find(x => x.id === id)
                return <span key={id} className="badge badge--info" style={{ fontSize: 10 }}>{un ? un.name : id}</span>
              })
            )}
            <button className="btn btn--ghost btn--sm" onClick={() => setEditUnits(true)}>
              <Building2 size={12} /> Zmień
            </button>
          </div>
        )}
        {editUnits && (
          <UnitsAssignModal
            user={u} units={units} initial={u.unit_ids || []}
            onClose={() => setEditUnits(false)}
            onSaved={() => { setEditUnits(false); onChanged() }}
          />
        )}
      </td>

      <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
        {u.auth_type === 'ldap' ? 'AD/LDAP' : 'Lokalne'}
      </td>
      <td>
        {u.is_active
          ? <span className="badge badge--success" style={{ fontSize: 10 }}>aktywny</span>
          : <span className="badge badge--error" style={{ fontSize: 10 }}>nieaktywny</span>}
        {isLocked && <span className="badge badge--warning" style={{ fontSize: 10, marginLeft: 4 }}>zablokowany</span>}
      </td>
      <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
        {fmtDate(u.password_changed_at)}
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
        <button className="btn btn--ghost btn--sm" style={{ border: 0 }} onClick={toggleActive}
                title={u.is_active ? 'Dezaktywuj' : 'Aktywuj'} aria-label={u.is_active ? 'Dezaktywuj' : 'Aktywuj'}>
          <Ban size={15} style={{ color: u.is_active ? 'var(--color-warning)' : 'var(--color-success)' }} />
        </button>
        {u.auth_type === 'local' && (
          <button className="btn btn--ghost btn--sm" style={{ border: 0 }}
                  onClick={handleReset} title="Resetuj hasło" aria-label="Resetuj hasło">
            <KeyRound size={15} />
          </button>
        )}
        {isLocked && (
          <button className="btn btn--ghost btn--sm" style={{ border: 0 }}
                  onClick={handleUnlock} title="Odblokuj konto" aria-label="Odblokuj konto">
            <Unlock size={15} style={{ color: 'var(--color-warning)' }} />
          </button>
        )}
        {!(u.roles || [u.role]).includes('superadmin') && (
          <button className="btn btn--ghost btn--sm" style={{ border: 0, color: 'var(--color-error-text)' }}
                  onClick={handleDelete} title="Usuń" aria-label="Usuń">
            <Trash2 size={15} />
          </button>
        )}
      </td>
    </tr>
  )
}

// Modal przypisania jednostek obsługiwanych do pracownika kadr.
function UnitsAssignModal({ user: u, units = [], initial = [], onClose, onSaved }) {
  const [ids, setIds] = useState(initial)
  const hintId = useId()
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)

  function toggle(id) {
    setIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }
  async function save() {
    setBusy(true); setErr(null)
    try {
      await updateUser(u.id, { unit_ids: ids })
      onSaved()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się zapisać jednostek')); setBusy(false)
    }
  }

  // Wspólne ui/Modal (pułapka fokusu, Escape, zwrot fokusu, blokada przewijania).
  return (
    <Modal title={`Jednostki obsługiwane — ${u.full_name || u.username}`} onClose={onClose} width={520}
           describedBy={hintId}
           footer={<>
             <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>Anuluj</button>
             <button type="button" className="btn btn--primary" onClick={save} disabled={busy}>
               <Check size={14} aria-hidden="true" /> {busy ? 'Zapisywanie…' : `Zapisz (${ids.length})`}
             </button>
           </>}>
      <p id={hintId} style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 0, marginBottom: 12 }}>
        Zaznacz jednostki, które ten pracownik kadr obsługuje. W formularzach
        „Nowy pracownik" i „Ustanie stosunku pracy" zobaczy wyłącznie te jednostki.
        Brak zaznaczenia = nie zobaczy żadnej.
      </p>
      <div role="group" aria-label="Jednostki obsługiwane" style={{
        maxHeight: 300, overflowY: 'auto', border: '1px solid var(--color-border)',
        borderRadius: 4, padding: 10, background: 'var(--bg-secondary)',
      }}>
        {units.length === 0 && (
          <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Brak zdefiniowanych jednostek.</div>
        )}
        {units.map(un => (
          <label key={un.id} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer', padding: '4px 0' }}>
            <input type="checkbox" checked={ids.includes(un.id)}
                   style={{ width: 16, height: 16 }} onChange={() => toggle(un.id)} />
            {un.name}
          </label>
        ))}
      </div>
      {err && <div className="alert alert--error" role="alert" style={{ marginTop: 10 }}>{err}</div>}
    </Modal>
  )
}


function AddUserCard({ depts = [], units = [], onAdded, onCancel }) {
  const [form, setForm] = useState({ username: '', full_name: '', email: '', password: '', auth_type: 'local', department_id: '' })
  const [selectedRoles, setSelectedRoles] = useState(['admin'])
  const [unitIds, setUnitIds] = useState([])
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const formId = useId()

  const isHr = selectedRoles.includes('hr')

  function toggleRole(rv) {
    setSelectedRoles(prev =>
      prev.includes(rv) ? prev.filter(r => r !== rv) : [...prev, rv]
    )
  }
  function toggleUnit(id) {
    setUnitIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  async function submit(e) {
    e.preventDefault(); setErr(null)
    if (!selectedRoles.length) { setErr('Wybierz co najmniej jedną rolę'); return }
    setBusy(true)
    try {
      const r = await createUser({
        ...form, roles: selectedRoles,
        department_id: form.department_id ? Number(form.department_id) : null,
        unit_ids: isHr ? unitIds : [],
      })
      if (r.data?.warning) toast(r.data.warning, { tone: 'warning' })
      onAdded()
    } catch (ex) {
      setErr(extractErr(ex))
      setBusy(false)
    }
  }

  const set = (k, v) => setForm(f => ({ ...f, [k]: v }))

  return (
    <div className="card mb-4" style={{ borderTop: '3px solid var(--color-gold)' }}>
      <form onSubmit={submit}>
        <div className="form-row">
          <Field label="Login" required>
            <input className="form-control" required value={form.username} onChange={e => set('username', e.target.value)} />
          </Field>
          <Field label="Imię i nazwisko">
            <input className="form-control" value={form.full_name} onChange={e => set('full_name', e.target.value)} />
          </Field>
        </div>
        <div className="form-row">
          <Field label="E-mail" style={{ flexBasis: '100%' }}
                 hint="Adres do powiadomień. Konta z AD/LDAP zwykle mają go zaciąganego automatycznie — uzupełnij zwłaszcza dla kont lokalnych.">
            <input className="form-control" type="email" value={form.email}
                   onChange={e => set('email', e.target.value)}
                   placeholder="np. j.kowalski@wodzislaw-slaski.pl" />
          </Field>
        </div>
        <div className="form-row">
          <div className="form-group" style={{ flexBasis: '100%' }}>
            <div className="form-label" id={`${formId}-roles`}>Role</div>
            <div role="group" aria-labelledby={`${formId}-roles`} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
              {assignableRoles().map(r => (
                <label key={r.value} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, cursor: 'pointer' }}>
                  <input type="checkbox" checked={selectedRoles.includes(r.value)}
                         onChange={() => toggleRole(r.value)} />
                  <span className={`badge ${r.badge}`} style={{ fontSize: 10 }}>{r.label}</span>
                </label>
              ))}
            </div>
            {!isSuperadmin() && <div className="form-hint">{ADMIN_ROLES_HINT}</div>}
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label" htmlFor={`${formId}-dept`}>Komórka organizacyjna</label>
            <DeptCombo id={`${formId}-dept`} depts={depts} units={units} value={form.department_id}
                       onChange={v => set('department_id', v)}
                       placeholder="— brak (można przypisać później) —" />
          </div>
        </div>

        {/* Zakres kadr — jednostki, które ten pracownik HR obsługuje */}
        {isHr && (
          <div className="form-row">
            <div className="form-group">
              <div className="form-label" id={`${formId}-units`}>Jednostki obsługiwane przez kadry *</div>
              <div role="group" aria-labelledby={`${formId}-units`} style={{
                maxHeight: 160, overflowY: 'auto', border: '1px solid var(--color-border)',
                borderRadius: 4, padding: 8, background: 'var(--bg-secondary)',
              }}>
                {units.length === 0 && (
                  <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Brak jednostek</div>
                )}
                {units.map(un => (
                  <label key={un.id} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, cursor: 'pointer' }}>
                    <input type="checkbox" checked={unitIds.includes(un.id)}
                           onChange={() => toggleUnit(un.id)} />
                    {un.name}
                  </label>
                ))}
              </div>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                Pracownik kadr zobaczy w formularzach wyłącznie te jednostki. Brak zaznaczenia = nie zobaczy żadnej.
              </div>
            </div>
          </div>
        )}

        <div className="form-row">
          <Field label="Typ konta">
            <select className="form-control" value={form.auth_type} onChange={e => set('auth_type', e.target.value)}>
              <option value="local">Lokalne</option>
              <option value="ldap">AD/LDAP</option>
            </select>
          </Field>
          {form.auth_type === 'local' && (
            <Field label="Hasło" required>
              <input className="form-control" type="password" required value={form.password}
                     onChange={e => set('password', e.target.value)} autoComplete="new-password" />
            </Field>
          )}
        </div>
        {err && <div className="alert alert--error mb-4" role="alert">{err}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn--ghost" onClick={onCancel}>Anuluj</button>
          <button type="submit" className="btn btn--primary" disabled={busy}>
            {busy ? 'Tworzenie…' : 'Utwórz konto'}
          </button>
        </div>
      </form>
    </div>
  )
}
