import { Fragment, useEffect, useRef, useState } from 'react'
import {
  Plus, Trash2, KeyRound, Unlock, Ban, Building2, Check, X,
  ChevronRight, ChevronDown, FolderTree, Users as UsersIcon, UserCog,
} from 'lucide-react'
import {
  listUsers, createUser, updateUser, deleteUser, resetUserPassword, unlockUser,
  listAllDepartments, listActiveUnits, autoAssignManagers,
} from '../api'
import { LdapUsersImportModal } from './Units'
import { serverTs, serverNow, fmtDate } from '../serverTime'

// Etykieta komórki: „Nazwa · Jednostka" jeśli znamy jednostkę.
function deptLabel(d) {
  if (!d) return ''
  return d.unit_name ? `${d.name} · ${d.unit_name}` : d.name
}


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
                     autoFocus = false, placeholder = '— brak (nieprzypisany) —' }) {
  const [open, setOpen] = useState(false)
  const [q, setQ]       = useState('')
  const [hi, setHi]     = useState(0)
  const wrapRef = useRef(null)
  const listRef = useRef(null)

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
      if (wrapRef.current && !wrapRef.current.contains(e.target)) { setOpen(false); setQ('') }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const norm = s => (s || '').toString().toLowerCase()
  const query = q.trim().toLowerCase()
  const filtered = depts.filter(d => !query || norm(fullStr(d)).includes(query))

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

  function pick(opt) {
    onChange(opt._clear ? '' : String(opt.id))
    setOpen(false); setQ(''); setHi(0)
  }

  function onKey(e) {
    if (!open) {
      if (e.key === 'ArrowDown' || e.key === 'Enter') { setOpen(true); setHi(0) }
      return
    }
    if (e.key === 'ArrowDown')      { e.preventDefault(); setHi(h => Math.min(h + 1, options.length - 1)) }
    else if (e.key === 'ArrowUp')   { e.preventDefault(); setHi(h => Math.max(h - 1, 0)) }
    else if (e.key === 'Enter')     { e.preventDefault(); if (options[hi]) pick(options[hi]) }
    else if (e.key === 'Escape')    { e.preventDefault(); setOpen(false); setQ('') }
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
  })

  return (
    <div ref={wrapRef} style={{ position: 'relative', minWidth: 240 }}>
      <input
        className={className}
        style={{ fontSize: 13 }}
        autoFocus={autoFocus}
        value={open ? q : label}
        placeholder={label || placeholder}
        onFocus={() => { setOpen(true); setHi(0) }}
        onChange={e => { setQ(e.target.value); setOpen(true); setHi(0) }}
        onKeyDown={onKey}
      />
      {open && (
        <div ref={listRef} style={{
          position: 'absolute', zIndex: 40, top: '100%', left: 0, right: 0, marginTop: 2,
          minWidth: 300, maxHeight: 300, overflowY: 'auto', background: 'var(--bg-primary)',
          border: '1px solid var(--color-border)', borderRadius: 6,
          boxShadow: '0 8px 24px rgba(0,0,0,.14)',
        }}>
          <div data-idx={0}
               onMouseDown={e => { e.preventDefault(); pick({ _clear: true }) }}
               onMouseEnter={() => setHi(0)}
               style={{ ...rowStyle(0), color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
            {placeholder}
          </div>

          {groups.map(g => (
            <div key={g.name + (g.items[0]?.id ?? '')}>
              <div style={{
                position: 'sticky', top: 0, zIndex: 1,
                padding: '4px 10px', fontSize: 11, fontWeight: 700,
                letterSpacing: '.03em', textTransform: 'uppercase',
                color: 'var(--color-navy)', background: 'var(--bg-secondary)',
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
                  <div key={d.id} data-idx={idx}
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
            <div style={{ padding: '6px 10px', fontSize: 12, color: 'var(--color-text-muted)' }}>
              Brak komórek pasujących do „{q.trim()}”.
            </div>
          )}
        </div>
      )}
    </div>
  )
}

const ROLES = [
  { value: 'superadmin', label: 'Superadmin',    badge: 'badge--error',   superadminOnly: true },
  { value: 'admin',      label: 'Admin',         badge: 'badge--warning' },
  { value: 'hr',         label: 'HR',            badge: 'badge--info'    },
  { value: 'manager',    label: 'Kierownik',     badge: 'badge--info'    },
  { value: 'it_staff',   label: 'Pracownik IT',  badge: 'badge--success' },
  { value: 'viewer',     label: 'Podgląd',       badge: 'badge--neutral' },
]

const ROLE_META = Object.fromEntries(ROLES.map(r => [r.value, r]))

function currentUserRoles() {
  try { return JSON.parse(localStorage.getItem('szup_user'))?.roles || [] }
  catch { return [] }
}
const isSuperadmin = () => currentUserRoles().includes('superadmin')

// Jakie role może przypisywać zalogowany użytkownik
const assignableRoles = () => isSuperadmin() ? ROLES : ROLES.filter(r => !r.superadminOnly)

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

  // Przypisanie kierowników komórek wg stanowiska z AD (kierownik/dyrektor/naczelnik).
  // Stanowiska pobierają się przy imporcie użytkowników z AD.
  async function runAutoManagers() {
    if (!confirm('Przypisać kierowników komórek na podstawie stanowiska z AD '
      + '(„kierownik", „dyrektor", „naczelnik")?\n\n'
      + 'Uzupełnione zostaną tylko komórki BEZ kierownika; przy kilku kandydatach '
      + 'komórka zostaje do ręcznej decyzji. Najpierw zaimportuj użytkowników z AD '
      + '(stanowiska pobierają się przy imporcie).')) return
    setAutoBusy(true)
    try {
      const r = await autoAssignManagers({})
      const d = r.data
      alert(`Przypisano: ${d.assigned}\n`
        + `Pominięto (mają już kierownika): ${d.skipped_has_manager}\n`
        + `Niejednoznaczne (kilku kandydatów): ${d.ambiguous}\n`
        + `Bez kandydata: ${d.no_candidate}`
        + (d.details.length ? `\n\n${d.details.join('\n')}` : ''))
      load()
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Nie udało się przypisać kierowników')
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
    setLoading(true)
    try {
      const [rU, rD, rUn] = await Promise.all([
        listUsers(),
        listAllDepartments().catch(() => ({ data: [] })),
        listActiveUnits().catch(() => ({ data: [] })),
      ])
      setUsers(rU.data); setDepts(rD.data); setUnits(rUn.data)
    }
    finally { setLoading(false) }
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
          <div className="page-header__title">Użytkownicy</div>
          <div className="page-header__sub">Zarządzanie kontami i rolami w systemie SZUP</div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <select
            className="form-control"
            style={{ maxWidth: 260, fontSize: 13 }}
            value={filterUnit}
            onChange={e => setFilterUnit(e.target.value)}
            title="Pokaż użytkowników z wybranej jednostki"
          >
            <option value="">Wszystkie jednostki</option>
            {units.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
          <button className="btn btn--ghost btn--sm"
                  onClick={() => collapsed.size > 0 ? setCollapsed(new Set()) : collapseAll()}
                  title="Zwiń lub rozwiń wszystkie sekcje">
            <FolderTree size={14} /> {collapsed.size > 0 ? 'Rozwiń wszystko' : 'Zwiń wszystko'}
          </button>
          <button className="btn btn--ghost btn--sm" onClick={runAutoManagers} disabled={autoBusy}
                  title="Przypisz kierowników komórek wg stanowiska z AD (kierownik/dyrektor/naczelnik)">
            <UserCog size={13} /> {autoBusy ? 'Przypisywanie…' : 'Kierownicy wg stanowiska'}
          </button>
          <button className="btn btn--action btn--sm" onClick={() => setShowLdapUsersImport(true)}>
            <UsersIcon size={13} /> Importuj z AD
          </button>
          <button className="btn btn--action btn--sm" onClick={() => setShowAdd(v => !v)}>
            <Plus size={13} /> Nowy użytkownik
          </button>
        </div>
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

      {loading ? (
        <div className="card"><div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div></div>
      ) : visibleUsers.length === 0 ? (
        <div className="card">
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>
            {users.length === 0 ? 'Brak użytkowników' : 'Brak użytkowników przypisanych do tej jednostki.'}
          </div>
        </div>
      ) : (
        // Akordeon per JEDNOSTKA — spójnie z zakładką „Jednostki".
        <div>
          {userGroups.map(g => {
            const uKey = `u:${g.key}`
            const unitOpen = !collapsed.has(uKey)
            return (
              <div className="accordion-item" key={`g-${g.key}`}>
                <button type="button" className={`accordion-trigger${unitOpen ? ' open' : ''}`}
                        onClick={() => toggleCollapse(uKey)}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <Building2 size={15} style={{
                      color: g.key === '_none' ? 'var(--color-text-muted)' : 'var(--color-navy)', flexShrink: 0 }} />
                    <span style={{ fontWeight: 700, fontSize: 14,
                                   color: g.key === '_none' ? 'var(--color-text-muted)' : 'var(--color-navy)' }}>
                      {g.name}
                    </span>
                    <span className="badge badge--neutral" style={{ fontSize: 10 }}>{g.count}</span>
                  </div>
                  {unitOpen ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                </button>

                {unitOpen && (
                  <div className="accordion-content" style={{ padding: 0 }}>
                    <table className="data-table" style={{ margin: 0 }}>
                      <thead>
                        <tr>
                          <th>Login</th><th>Imię i nazwisko</th><th>E-mail</th><th>Rola</th>
                          <th>Komórka organizacyjna</th><th>Jednostki (kadry)</th><th>Typ</th>
                          <th>Status</th><th>Ostatnia zmiana hasła</th><th></th>
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
                                <td colSpan={10} onClick={() => toggleCollapse(dKey)}
                                    style={{
                                      padding: '7px 12px 7px 24px', cursor: 'pointer', userSelect: 'none',
                                      background: 'var(--bg-secondary)',
                                    }}>
                                  <span style={{
                                    display: 'inline-flex', alignItems: 'center', gap: 7,
                                    fontSize: 13, fontWeight: 700, color: 'var(--color-text)',
                                  }}>
                                    {deptOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                    {d.label}
                                    <span className="badge badge--neutral" style={{ fontSize: 10 }}>
                                      {d.users.length}
                                    </span>
                                  </span>
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
              </div>
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
      if (r.data?.warning) alert(r.data.warning)
      setEditDept(false); onChanged()
    } catch (ex) { alert(ex.response?.data?.detail || 'Błąd przypisania komórki') }
  }

  function toggleRole(rv) {
    setSelectedRoles(prev =>
      prev.includes(rv) ? prev.filter(r => r !== rv) : [...prev, rv]
    )
  }

  async function saveRoles() {
    if (!selectedRoles.length) { alert('Wybierz co najmniej jedną rolę'); return }
    try {
      const r = await updateUser(u.id, { roles: selectedRoles })
      if (r.data?.warning) alert(r.data.warning)
      setEditRoles(false); onChanged()
    }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd zmiany roli') }
  }

  async function toggleActive() {
    try { await updateUser(u.id, { is_active: !u.is_active }); onChanged() }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd') }
  }

  async function handleReset() {
    const pw = prompt(
      `Nowe hasło dla ${u.username}.\nMin. 12 znaków, 3 z 4 klas (małe/WIELKIE/cyfry/specjalne).\nUżytkownik będzie musiał je zmienić.`
    )
    if (!pw) return
    try { await resetUserPassword(u.id, pw); onChanged() }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd resetowania hasła') }
  }

  async function handleUnlock() {
    try { await unlockUser(u.id); onChanged() }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd') }
  }

  async function handleDelete() {
    if (!confirm(`Usunąć konto "${u.username}"?`)) return
    try { await deleteUser(u.id); onChanged() }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd usuwania') }
  }

  return (
    <tr>
      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{u.username}</td>
      <td style={{ fontWeight: 600 }}>{u.full_name || '—'}</td>
      <td style={{ fontSize: 12 }}>
        {u.email
          ? <a href={`mailto:${u.email}`} style={{ color: 'var(--color-primary)', textDecoration: 'none' }}>{u.email}</a>
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
            <button className="btn btn--primary btn--sm" onClick={saveRoles}>OK</button>
            <button className="btn btn--ghost btn--sm" onClick={() => { setEditRoles(false); setSelectedRoles(u.roles || [u.role]) }}>×</button>
          </div>
        ) : (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, cursor: 'pointer' }}
               onClick={() => setEditRoles(true)} title="Kliknij aby zmienić role">
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
          </div>
        )}
      </td>
      <td>
        {editDept ? (
          <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
            <DeptCombo depts={depts} units={units} value={deptId} onChange={setDeptId}
                       className="input input--sm" autoFocus />
            <button className="btn btn--primary btn--sm" onClick={saveDept} title="Zapisz"><Check size={12} /></button>
            <button className="btn btn--ghost btn--sm"
                    onClick={() => { setEditDept(false); setDeptId(u.department_id || '') }} title="Anuluj"><X size={12} /></button>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', fontSize: 12 }}
               onClick={() => setEditDept(true)} title="Kliknij aby przypisać komórkę">
            <Building2 size={13} style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
            {u.department_name
              ? <span>{u.department_name}</span>
              : <span style={{ color: 'var(--color-text-muted)', fontStyle: 'italic' }}>nieprzypisany</span>}
          </div>
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
        <button className="btn btn--ghost btn--sm" onClick={toggleActive}
                title={u.is_active ? 'Dezaktywuj' : 'Aktywuj'}>
          <Ban size={12} style={{ color: u.is_active ? 'var(--color-warning)' : 'var(--color-success)' }} />
        </button>
        {u.auth_type === 'local' && (
          <button className="btn btn--ghost btn--sm" style={{ marginLeft: 4 }}
                  onClick={handleReset} title="Resetuj hasło">
            <KeyRound size={12} />
          </button>
        )}
        {isLocked && (
          <button className="btn btn--ghost btn--sm" style={{ marginLeft: 4 }}
                  onClick={handleUnlock} title="Odblokuj konto">
            <Unlock size={12} style={{ color: 'var(--color-warning)' }} />
          </button>
        )}
        {!(u.roles || [u.role]).includes('superadmin') && (
          <button className="btn btn--danger btn--sm" style={{ marginLeft: 4 }}
                  onClick={handleDelete}>
            <Trash2 size={12} />
          </button>
        )}
      </td>
    </tr>
  )
}

// Modal przypisania jednostek obsługiwanych do pracownika kadr.
function UnitsAssignModal({ user: u, units = [], initial = [], onClose, onSaved }) {
  const [ids, setIds] = useState(initial)
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
      setErr(ex.response?.data?.detail || 'Nie udało się zapisać jednostek'); setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal modal--sm">
        <div className="modal__header">
          <span className="modal__title">
            <Building2 size={15} style={{ marginRight: 8, verticalAlign: 'middle' }} />
            Jednostki obsługiwane — {u.full_name || u.username}
          </span>
          <button className="modal__close" onClick={onClose}>×</button>
        </div>
        <div className="modal__body">
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 12 }}>
            Zaznacz jednostki, które ten pracownik kadr obsługuje. W formularzach
            „Nowy pracownik" i „Ustanie stosunku pracy" zobaczy wyłącznie te jednostki.
            Brak zaznaczenia = nie zobaczy żadnej.
          </p>
          <div style={{
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
          {err && <div className="alert alert--error" style={{ marginTop: 10 }}>{err}</div>}
        </div>
        <div className="modal__footer">
          <button className="btn btn--ghost" onClick={onClose} disabled={busy}>Anuluj</button>
          <button className="btn btn--primary" onClick={save} disabled={busy}>
            <Check size={14} /> {busy ? 'Zapisywanie…' : `Zapisz (${ids.length})`}
          </button>
        </div>
      </div>
    </div>
  )
}


function AddUserCard({ depts = [], units = [], onAdded, onCancel }) {
  const [form, setForm] = useState({ username: '', full_name: '', email: '', password: '', auth_type: 'local', department_id: '' })
  const [selectedRoles, setSelectedRoles] = useState(['admin'])
  const [unitIds, setUnitIds] = useState([])
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

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
      if (r.data?.warning) alert(r.data.warning)
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
          <div className="form-group">
            <label className="form-label">Login *</label>
            <input className="form-control" required value={form.username} onChange={e => set('username', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Imię i nazwisko</label>
            <input className="form-control" value={form.full_name} onChange={e => set('full_name', e.target.value)} />
          </div>
        </div>
        <div className="form-row">
          <div className="form-group" style={{ flexBasis: '100%' }}>
            <label className="form-label">E-mail</label>
            <input className="form-control" type="email" value={form.email}
                   onChange={e => set('email', e.target.value)}
                   placeholder="np. j.kowalski@wodzislaw-slaski.pl" />
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              Adres do powiadomień. Konta z AD/LDAP zwykle mają go zaciąganego
              automatycznie — uzupełnij zwłaszcza dla kont lokalnych.
            </div>
          </div>
        </div>
        <div className="form-row">
          <div className="form-group" style={{ flexBasis: '100%' }}>
            <label className="form-label">Role</label>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 }}>
              {assignableRoles().map(r => (
                <label key={r.value} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 13, cursor: 'pointer' }}>
                  <input type="checkbox" checked={selectedRoles.includes(r.value)}
                         onChange={() => toggleRole(r.value)} />
                  <span className={`badge ${r.badge}`} style={{ fontSize: 10 }}>{r.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Komórka organizacyjna</label>
            <DeptCombo depts={depts} units={units} value={form.department_id}
                       onChange={v => set('department_id', v)}
                       placeholder="— brak (można przypisać później) —" />
          </div>
        </div>

        {/* Zakres kadr — jednostki, które ten pracownik HR obsługuje */}
        {isHr && (
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Jednostki obsługiwane przez kadry *</label>
              <div style={{
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
          <div className="form-group">
            <label className="form-label">Typ konta</label>
            <select className="form-control" value={form.auth_type} onChange={e => set('auth_type', e.target.value)}>
              <option value="local">Lokalne</option>
              <option value="ldap">AD/LDAP</option>
            </select>
          </div>
          {form.auth_type === 'local' && (
            <div className="form-group">
              <label className="form-label">Hasło *</label>
              <input className="form-control" type="password" required value={form.password}
                     onChange={e => set('password', e.target.value)} autoComplete="new-password" />
            </div>
          )}
        </div>
        {err && <div className="alert alert--error mb-4">{err}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel}>Anuluj</button>
          <button type="submit" className="btn btn--primary btn--sm" disabled={busy}>
            {busy ? 'Tworzenie…' : 'Utwórz konto'}
          </button>
        </div>
      </form>
    </div>
  )
}
