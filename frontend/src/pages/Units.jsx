import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Plus, Trash2, Edit2, ChevronDown, ChevronRight, Building2, Download,
  FolderTree, Layers, User as UserIcon, UserCog, Save, ShieldAlert,
} from 'lucide-react'
import {
  listUnits, createUnit, updateUnit, deleteUnit,
  listAllDepartments, createDepartment, updateDepartment, deleteDepartment,
  listUsers, ldapPreviewUnits, ldapImportUnits,
  ldapPreviewUsers, ldapImportUsers,
  listDeputies, addDeputy, updateDeputy, deleteDeputy,
  dedupeDepartments, forceDeleteDepartment,
 errorMessage} from '../api'
import { getUserRoles } from '../roles'
import { toast, ask } from '../components/ui/feedback'
import Modal from '../components/ui/Modal'
import { ErrorAlert, LoadError } from '../components/ui/LoadState'
import { focusTarget } from '../components/ui/focus'
import { countLabel } from '../labels'


// Rola „HR” zniesiona — funkcję kadr wyznacza wyłącznie flaga komórki (is_hr).
const HR_DEPT_HINT = 'Członkowie komórki kadrowej pełnią funkcję kadr dla wszystkich jednostek'

// Typy węzłów struktury organizacyjnej (zsynchronizowane z backend: models.DEPARTMENT_KINDS)
const DEPT_KINDS = [
  { value: 'department', label: 'Wydział / Dział',       icon: FolderTree, badge: 'badge--info' },
  { value: 'section',    label: 'Referat',               icon: Layers,     badge: 'badge--neutral' },
  { value: 'standalone', label: 'Samodzielne stanowisko', icon: UserIcon,  badge: 'badge--warning' },
]

export function kindMeta(kind) {
  return DEPT_KINDS.find(k => k.value === kind) || DEPT_KINDS[0]
}

// Mały badge z ikoną i etykietą rodzaju komórki (wydział / referat / stanowisko).
export function DeptKindBadge({ kind }) {
  const meta = kindMeta(kind)
  const Icon = meta.icon
  return (
    <span className={`badge ${meta.badge}`} style={{ fontSize: 10, whiteSpace: 'nowrap' }}>
      <Icon size={10} style={{ verticalAlign: 'middle', marginRight: 3 }} />
      {meta.label}
    </span>
  )
}

export default function Units() {
  const [units, setUnits] = useState([])
  const [depts, setDepts] = useState([])
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showLdapImport, setShowLdapImport] = useState(false)
  const [loadErr, setLoadErr] = useState(null)

  async function load() {
    setLoading(true); setLoadErr(null)
    try {
      const [u, d, us] = await Promise.all([listUnits(), listAllDepartments(), listUsers()])
      setUnits(u.data)
      setDepts(d.data)
      setUsers(us.data)
    } catch (ex) {
      setLoadErr(errorMessage(ex, 'Nie udało się wczytać struktury organizacyjnej'))
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  // ?filter=no_manager — tylko komórki bez kierownika (aktywne, nie-samodzielne);
  // link z listy kontrolnej administratora. Reaguje też na zmianę adresu.
  const [searchParams, setSearchParams] = useSearchParams()
  const noMgrFilter = searchParams.get('filter') === 'no_manager'
  const noMgrIds = new Set(depts
    .filter(d => d.is_active !== false && d.kind !== 'standalone' && !d.manager_user_id)
    .map(d => d.id))
  const clearFilter = () => {
    const p = new URLSearchParams(searchParams); p.delete('filter'); setSearchParams(p)
  }
  const shownUnits = noMgrFilter
    ? units.filter(u => depts.some(d => d.unit_id === u.id && noMgrIds.has(d.id)))
    : units

  const [dedupeBusy, setDedupeBusy] = useState(false)
  async function runDedupe() {
    if (!await ask('Usunąć zduplikowane komórki (np. po ponownym imporcie)?\n\n'
      + 'Usunięte zostaną WYŁĄCZNIE kopie BEZ danych — bez przypisanych pracowników, '
      + 'wniosków i bez ustawionego kierownika. Rekord z danymi zawsze zostaje.', { title: 'Potwierdź operację', confirmLabel: 'Usuń duplikaty', danger: true })) return
    setDedupeBusy(true)
    try {
      const r = await dedupeDepartments()
      const d = r.data
      toast(`Usunięto duplikatów: ${d.deleted}\n`
        + `Grup z duplikatami: ${d.clusters_found}`
        + (d.details.length ? `\n\n${d.details.join('\n')}` : ''))
      load()
    } catch (ex) {
      toast(errorMessage(ex, 'Nie udało się usunąć duplikatów'), { tone: 'error' })
    } finally { setDedupeBusy(false) }
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header__title">Jednostki</h1>
          <div className="page-header__sub">Struktura organizacyjna — jednostki i podległe wydziały</div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className="btn btn--ghost" onClick={runDedupe} disabled={dedupeBusy}
                  title="Usuń zduplikowane komórki powstałe przy ponownym imporcie struktury">
            <Trash2 size={14} /> {dedupeBusy ? 'Czyszczenie…' : 'Usuń duplikaty'}
          </button>
          <button type="button" className="btn btn--action" onClick={() => setShowLdapImport(true)}>
            <Download size={14} /> Importuj strukturę z AD
          </button>
        </div>
      </div>

      {showLdapImport && (
        <LdapImportModal onClose={() => { setShowLdapImport(false); load() }} />
      )}
      {loadErr && <LoadError message={loadErr} onRetry={load} busy={loading} style={{ marginBottom: 16 }} />}
      {loading && units.length === 0 ? (
        <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>
      ) : (
        // Spinner tylko przy PIERWSZYM ładowaniu. Przy odświeżeniu (po zapisie)
        // zostawiamy akordeony zamontowane — inaczej traciłyby stan rozwinięcia
        // i cała struktura by się zwijała.
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {!loading && !loadErr && units.length === 0 && (
            <div className="card" style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>
              <strong style={{ color: 'var(--color-text)' }}>Brak jednostek.</strong>{' '}
              Zaimportuj strukturę z AD przyciskiem „Importuj strukturę z AD” powyżej albo dodaj jednostkę ręcznie poniżej.
            </div>
          )}
          {noMgrFilter && (
            <div className="card" role="status" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center',
                                                         gap: 10, padding: '12px 18px' }}>
              <span style={{ flex: 1, fontSize: 14 }}>
                Filtr: <strong>komórki bez kierownika</strong> ({noMgrIds.size})
              </span>
              <button type="button" className="btn btn--ghost btn--sm" onClick={clearFilter}>Pokaż wszystkie</button>
            </div>
          )}
          {noMgrFilter && !loading && noMgrIds.size === 0 && (
            <div className="card" style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>
              Wszystkie aktywne komórki mają przypisanego kierownika.
            </div>
          )}
          {shownUnits.map(u => (
            <UnitAccordion key={`${u.id}-${noMgrFilter ? 'f' : 'a'}`} unit={u}
              depts={depts.filter(d => d.unit_id === u.id)}
              users={users}
              onlyDeptIds={noMgrFilter ? noMgrIds : null}
              onChanged={load} />
          ))}
          <AddUnitCard onAdded={load} />
        </div>
      )}
    </div>
  )
}

function UnitAccordion({ unit: u, depts, users, onChanged, onlyDeptIds = null }) {
  // Przy filtrze („bez kierownika”) jednostka startuje rozwinięta.
  const [open, setOpen] = useState(!!onlyDeptIds)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(u.name)
  const [err, setErr] = useState(null)
  const [mgrBusy, setMgrBusy] = useState(false)
  const headRef = useRef(null)

  // Po usunięciu / zarchiwizowaniu komórki (wiersz znika razem z przyciskiem)
  // fokus wraca na nagłówek tej jednostki, a nie spada na <body> (WCAG 2.4.3).
  async function afterDeptRemoved() {
    try { await onChanged() } finally {
      requestAnimationFrame(() => focusTarget(headRef))
    }
  }

  async function saveUnit(e) {
    e.preventDefault(); setErr(null)
    try {
      await updateUnit(u.id, { name })
      setEditing(false); onChanged()
    } catch (ex) { setErr(errorMessage(ex, 'Nie udało się zapisać jednostki')) }
  }

  async function saveUnitManager(val) {
    setMgrBusy(true)
    try {
      await updateUnit(u.id, { manager_user_id: val ? Number(val) : null })
      onChanged()
    } catch (ex) { toast(errorMessage(ex, 'Nie udało się ustawić kierownika jednostki'), { tone: 'error' }) }
    finally { setMgrBusy(false) }
  }

  async function delUnit() {
    if (!await ask(`Usunąć jednostkę "${u.name}"? Usunięte zostaną też powiązane wydziały.`, { title: 'Potwierdź operację', confirmLabel: 'Usuń jednostkę', danger: true })) return
    try { await deleteUnit(u.id); onChanged(); toast(`Usunięto jednostkę „${u.name}”`) }
    catch (ex) { toast(errorMessage(ex, 'Błąd usuwania'), { tone: 'error' }) }
  }

  // v3.0 — jednostka jako karta: nagłówek (rozwiń/zwiń) + osobne przyciski
  // edycji/usuwania, pasek kierownika jednostki, tabela wydziałów.
  const ICONBTN = { width: 44, height: 44, padding: 0, display: 'grid', placeItems: 'center', border: 0 }
  return (
    <section aria-label={`Jednostka ${u.name}`} style={{ background: 'var(--color-card)', border: '1px solid var(--color-border)',
                                                         borderRadius: 10, overflow: 'hidden' }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, padding: '6px 8px 6px 18px',
                    minHeight: 56, borderBottom: open ? '1px solid var(--color-border)' : 0 }}>
        <h2 style={{ margin: 0, flex: '1 1 300px', minWidth: 0, font: 'inherit' }}>
        <button type="button" ref={headRef} aria-expanded={open} onClick={() => setOpen(v => !v)}
                style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, width: '100%', minHeight: 44,
                         border: 0, background: 'transparent', font: 'inherit', color: 'inherit', cursor: 'pointer',
                         textAlign: 'left', padding: 0 }}>
          {open ? <ChevronDown size={18} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />
                : <ChevronRight size={18} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />}
          <Building2 size={18} aria-hidden="true" style={{ color: 'var(--color-heading)', flexShrink: 0 }} />
          <strong style={{ fontSize: 16, color: 'var(--color-heading)' }}>{u.name}</strong>
          <span className="badge badge--neutral">{countLabel(depts.length, 'wydział', 'wydziały', 'wydziałów')}</span>
          {u.description && (
            <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>— {u.description}</span>
          )}
        </button>
        </h2>
        <button type="button" className="btn btn--ghost" style={ICONBTN} aria-label={`Edytuj jednostkę ${u.name}`} title="Edytuj jednostkę"
                onClick={() => { setEditing(v => !v); setOpen(true) }}>
          <Edit2 size={16} />
        </button>
        <button type="button" className="btn btn--ghost" style={{ ...ICONBTN, color: 'var(--color-error-text)' }}
                aria-label={`Usuń jednostkę ${u.name}`} title="Usuń jednostkę" onClick={delUnit}>
          <Trash2 size={16} />
        </button>
      </div>

      {open && (
        <div>
          {editing && (
            <form onSubmit={saveUnit} style={{ display: 'flex', flexWrap: 'wrap', gap: 8, padding: '14px 18px',
                                               alignItems: 'flex-end', borderBottom: '1px solid var(--color-border)' }}>
              <div className="form-group" style={{ margin: 0, flex: '1 1 260px' }}>
                <label className="form-label" htmlFor={`unit-name-${u.id}`}>Nazwa jednostki</label>
                <input id={`unit-name-${u.id}`} className="form-control" required value={name} onChange={e => setName(e.target.value)} />
              </div>
              <button type="button" className="btn btn--ghost" onClick={() => { setEditing(false); setName(u.name) }}>Anuluj</button>
              <button type="submit" className="btn btn--primary">Zapisz</button>
              <ErrorAlert>{err}</ErrorAlert>
            </form>
          )}

          <div style={{
            display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', padding: '12px 18px',
            background: 'var(--bg-secondary)', borderBottom: '1px solid var(--color-border)',
          }}>
            <label style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, fontWeight: 700,
                            color: 'var(--color-heading)' }}>
              Kierownik jednostki:
              <select className="form-control" style={{ maxWidth: 320, fontSize: 14, fontWeight: 400 }}
                      value={u.manager_user_id || ''} disabled={mgrBusy}
                      onChange={e => saveUnitManager(e.target.value)}>
                <option value="">— brak —</option>
                <ManagerOptions users={users} unitDeptIds={depts.map(x => x.id)}
                                currentId={u.manager_user_id} />
              </select>
            </label>
            <span style={{ flex: '1 1 360px', fontSize: 12, color: 'var(--color-text-muted)' }}>
              Widzi uprawnienia wszystkich pracowników jednostki i może dla nich
              składać wnioski (bez akceptacji — ta zostaje przy kierownikach komórek).
            </span>
          </div>

          {/* Kolumna akcji przyklejona do prawej (jak listy zadań) — przy ~1024 px
              edycja / zastępcy / usuwanie są w zasięgu bez przewijania w poziomie. */}
          <div className="task-table-wrap">
            <table className="data-table task-table" style={{ minWidth: 1000 }}>
              <thead><tr><th>Nazwa</th><th>Typ</th><th>Kierownik</th><th>Aktywny</th><th title="Wymaga zatwierdzenia kierownika wydziału nadrzędnego">Wyższa akcept.</th><th title={HR_DEPT_HINT}>Kadry</th><th><span className="sr-only">Akcje</span></th></tr></thead>
              <tbody>
                {flattenDeptTree(depts).filter(({ dept: d }) => !onlyDeptIds || onlyDeptIds.has(d.id)).map(({ dept: d, depth }) => (
                  <DeptRow key={d.id} dept={d} depth={depth} users={users}
                           unitId={u.id} unitDepts={depts} onChanged={onChanged}
                           onRemoved={afterDeptRemoved} />
                ))}
                {depts.length === 0 && (
                  <tr><td colSpan={7} style={{ color: 'var(--color-text-muted)', padding: '10px 18px' }}>Brak wydziałów</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div style={{ padding: '14px 18px', borderTop: '1px solid var(--color-border)', background: 'var(--bg-secondary)' }}>
            <div className="form-hint" style={{ marginTop: 0, marginBottom: 10 }}>
              Kolumna „Kadry”: {HR_DEPT_HINT}. Funkcji kadr nie nadaje się już per osoba.
            </div>
            <AddDeptForm unitId={u.id} users={users} unitDepts={depts} onAdded={onChanged} />
          </div>
        </div>
      )}
    </section>
  )
}

// Sortuje wydziały danej jednostki w kolejności drzewa (pre-order) i podaje głębokość.
// Kandydaci na kierownika / zastępcę: NAJPIERW osoby z danej komórki,
// potem z tej samej jednostki — bez reszty systemu. Obecnie przypisana osoba
// spoza jednostki zostaje na liście, żeby wybór nie „znikał”.
function ManagerOptions({ users, deptId = null, unitDeptIds = [], currentId = null, exclude = [] }) {
  const unitSet = new Set(unitDeptIds)
  const skip = new Set(exclude.filter(Boolean).map(Number))
  const active = users.filter(u => u.is_active !== false && !skip.has(u.id))
  const lbl = u => `${u.full_name || u.username}`
    + (u.title ? ` — ${u.title}` : '')
    + (u.is_manager_title ? ' ★' : '')
  const byName = (a, b) => (a.full_name || a.username).localeCompare(b.full_name || b.username, 'pl')
  const byMgr = (a, b) => (b.is_manager_title ? 1 : 0) - (a.is_manager_title ? 1 : 0) || byName(a, b)
  const here = deptId ? active.filter(u => u.department_id === deptId).sort(byMgr) : []
  const inUnit = active.filter(u => u.department_id !== deptId && unitSet.has(u.department_id)).sort(byMgr)
  const cur = currentId ? users.find(u => u.id === Number(currentId)) : null
  const curOutside = cur && !here.includes(cur) && !inUnit.includes(cur)
  return (
    <>
      {here.length > 0 && (
        <optgroup label="Z tej komórki">
          {here.map(u => <option key={u.id} value={u.id}>{lbl(u)}</option>)}
        </optgroup>
      )}
      {inUnit.length > 0 && (
        <optgroup label="Z tej jednostki">
          {inUnit.map(u => <option key={u.id} value={u.id}>{lbl(u)}</option>)}
        </optgroup>
      )}
      {curOutside && (
        <optgroup label="Obecnie przypisany (spoza jednostki)">
          <option value={cur.id}>{lbl(cur)}</option>
        </optgroup>
      )}
    </>
  )
}

function flattenDeptTree(depts) {
  const byParent = new Map()
  for (const d of depts) {
    const key = d.parent_dept_id ?? null
    if (!byParent.has(key)) byParent.set(key, [])
    byParent.get(key).push(d)
  }
  for (const arr of byParent.values()) arr.sort((a, b) => a.name.localeCompare(b.name))
  const ids = new Set(depts.map(d => d.id))
  const out = []
  function visit(parentId, depth) {
    const kids = byParent.get(parentId) || []
    for (const d of kids) { out.push({ dept: d, depth }); visit(d.id, depth + 1) }
  }
  visit(null, 0)
  // Sieroty (rodzic istnieje, ale spoza tej jednostki — nie powinno się zdarzyć, ale
  // zabezpiecz widok przed ukryciem wydziałów):
  for (const d of depts) {
    if (d.parent_dept_id != null && !ids.has(d.parent_dept_id) && !out.find(x => x.dept.id === d.id)) {
      out.push({ dept: d, depth: 0 })
    }
  }
  return out
}


// Zbiera zbiór id potomków (wraz z samym węzłem) — żeby wykluczyć je z
// listy wyboru nowego rodzica (nie można zejść pod siebie).
function collectDescendants(depts, rootId) {
  const children = new Map()
  for (const d of depts) {
    const k = d.parent_dept_id ?? null
    if (!children.has(k)) children.set(k, [])
    children.get(k).push(d)
  }
  const out = new Set([rootId])
  const stack = [rootId]
  while (stack.length) {
    const cur = stack.pop()
    for (const kid of children.get(cur) || []) {
      if (!out.has(kid.id)) { out.add(kid.id); stack.push(kid.id) }
    }
  }
  return out
}


function DeptRow({ dept: d, depth = 0, users, unitId, unitDepts, onChanged, onRemoved }) {
  const [editing, setEditing] = useState(false)
  const [deputiesOpen, setDeputiesOpen] = useState(false)
  const [forceOpen, setForceOpen] = useState(false)
  const superadmin = getUserRoles().includes('superadmin')
  const [name, setName]       = useState(d.name)
  const [kind, setKind]       = useState(d.kind || 'department')
  const [parentId, setParentId] = useState(d.parent_dept_id || '')
  const [managerId, setManagerId] = useState(d.manager_user_id || '')
  const [isActive, setIsActive]   = useState(d.is_active)
  const [higher, setHigher]       = useState(!!d.requires_higher_approval)
  const [isHr, setIsHr]           = useState(!!d.is_hr)

  async function save() {
    try {
      await updateDepartment(d.id, {
        name,
        kind,
        parent_dept_id: parentId ? Number(parentId) : null,
        manager_user_id: managerId ? Number(managerId) : null,
        is_active: isActive,
        requires_higher_approval: higher,
        is_hr: isHr,
      })
      setEditing(false); onChanged()
    } catch (ex) { toast(errorMessage(ex, 'Nie udało się zapisać komórki'), { tone: 'error' }) }
  }

  async function del() {
    if (!await ask(`Usunąć "${d.name}"?`, { title: 'Potwierdź operację', confirmLabel: 'Usuń komórkę', danger: true })) return
    try { await deleteDepartment(d.id); toast(`Usunięto „${d.name}”`); (onRemoved || onChanged)() }
    catch (ex) { toast(errorMessage(ex, 'Błąd usuwania'), { tone: 'error' }) }
  }

  const indentPx = depth * 18

  if (editing) {
    // Kandydaci na rodzica: węzły z tej samej jednostki, wykluczając siebie i potomków.
    const exclude = collectDescendants(unitDepts, d.id)
    const parentCandidates = flattenDeptTree(unitDepts)
      .filter(({ dept: x }) => !exclude.has(x.id))

    return (
      <tr>
        <td style={{ paddingLeft: `calc(10px + ${indentPx}px)` }}>
          <input className="form-control" style={{ fontSize: 12, marginBottom: 4 }}
                 aria-label={`Nazwa komórki ${d.name}`}
                 value={name} onChange={e => setName(e.target.value)} />
          <select className="form-control" style={{ fontSize: 11 }}
                  aria-label={`Węzeł nadrzędny komórki ${d.name}`}
                  value={parentId} onChange={e => setParentId(e.target.value)}
                  title="Węzeł nadrzędny w strukturze">
            <option value="">— bezpośrednio pod jednostką —</option>
            {parentCandidates.map(({ dept: x, depth: xd }) => (
              <option key={x.id} value={x.id}>
                {'\u00A0'.repeat(xd * 2)}{x.name} ({kindMeta(x.kind).label})
              </option>
            ))}
          </select>
        </td>
        <td>
          <select className="form-control" style={{ fontSize: 12 }}
                  aria-label={`Typ komórki ${d.name}`}
                  value={kind} onChange={e => setKind(e.target.value)}>
            {DEPT_KINDS.map(k => (
              <option key={k.value} value={k.value}>{k.label}</option>
            ))}
          </select>
        </td>
        <td>
          {kind === 'standalone' ? (
            <span style={{ fontSize: 11, color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
              — podlega kierownikowi wyżej —
            </span>
          ) : (
          <select className="form-control" style={{ fontSize: 12 }}
                  aria-label={`Kierownik komórki ${d.name}`}
                  value={managerId} onChange={e => setManagerId(e.target.value)}
                  title="★ = stanowisko kierownicze (z AD). Najpierw osoby z tej komórki, potem z jednostki.">
            <option value="">— brak —</option>
            <ManagerOptions users={users} deptId={d.id}
                            unitDeptIds={(unitDepts || []).map(x => x.id)} currentId={managerId} />
          </select>
          )}
        </td>
        <td>
          <input type="checkbox" checked={isActive} onChange={e => setIsActive(e.target.checked)}
                 aria-label={`Komórka ${d.name} aktywna`} />
        </td>
        <td>
          <input type="checkbox" checked={higher} onChange={e => setHigher(e.target.checked)}
                 aria-label={`Komórka ${d.name}: wymaga akceptacji kierownika nadrzędnego`}
                 title="Wnioski wymagają zatwierdzenia kierownika wydziału nadrzędnego (tryb 2-stopniowy)" />
        </td>
        <td>
          <input type="checkbox" checked={isHr} onChange={e => setIsHr(e.target.checked)}
                 aria-label={`Komórka ${d.name}: komórka kadrowa`}
                 title={HR_DEPT_HINT} />
        </td>
        <td style={{ whiteSpace: 'nowrap' }}>
          <button type="button" className="btn btn--primary btn--sm" onClick={save}>Zapisz</button>
          <button type="button" className="btn btn--ghost btn--sm" style={{ marginLeft: 4 }}
                  onClick={() => {
                    setEditing(false); setName(d.name); setKind(d.kind || 'department')
                    setParentId(d.parent_dept_id || ''); setManagerId(d.manager_user_id||'')
                    setIsActive(d.is_active); setHigher(!!d.requires_higher_approval)
                    setIsHr(!!d.is_hr)
                  }}>Anuluj</button>
        </td>
      </tr>
    )
  }

  const managerUser = users.find(u => u.id === d.manager_user_id)
  return (
    <tr>
      <td style={{ paddingLeft: `calc(14px + ${indentPx}px)` }}>
        <span style={{ display: 'block', fontWeight: 700, color: 'var(--color-heading)' }}>
          {depth > 0 && <span style={{ color: 'var(--color-text-muted)', marginRight: 6 }}>↳</span>}
          {d.name}
        </span>
        {d.description && (
          <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)', fontWeight: 400 }}>
            {d.description}
          </span>
        )}
      </td>
      <td><DeptKindBadge kind={d.kind || 'department'} /></td>
      <td style={{ color: 'var(--color-text-muted)' }}>
        {d.kind === 'standalone'
          ? <span style={{ fontStyle: 'italic' }} title="Samodzielne stanowisko — podlega kierownikowi wyżej w strukturze">podlega wyżej</span>
          : (managerUser ? (managerUser.full_name || managerUser.username) : '—')}
      </td>
      <td>
        {d.is_active
          ? <span className="badge badge--success">aktywny</span>
          : <span className="badge badge--neutral">nieaktywny</span>}
      </td>
      <td>
        {d.requires_higher_approval
          ? <span className="badge badge--info" title="Wnioski wymagają akceptacji kierownika wydziału nadrzędnego">2-stopniowo</span>
          : <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>—</span>}
      </td>
      <td>
        {d.is_hr
          ? <span className="badge badge--warning" title={HR_DEPT_HINT}>kadry</span>
          : <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>—</span>}
      </td>
      <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
        <button type="button" className="btn btn--ghost btn--sm" style={{ border: 0 }} onClick={() => setEditing(true)}
                title="Edytuj" aria-label={`Edytuj komórkę ${d.name}`}><Edit2 size={15} aria-hidden="true" /></button>
        <button type="button" className="btn btn--ghost btn--sm" style={{ border: 0 }}
                onClick={() => setDeputiesOpen(true)} title="Zastępcy kierownika" aria-label={`Zastępcy kierownika komórki ${d.name}`}>
          <UserCog size={15} aria-hidden="true" />
        </button>
        <button type="button" className="btn btn--ghost btn--sm" style={{ border: 0, color: 'var(--color-error-text)' }} onClick={del}
                title="Usuń pustą komórkę (bez pracowników, podkomórek i wniosków)"
                aria-label={`Usuń komórkę ${d.name}`}><Trash2 size={15} aria-hidden="true" /></button>
        {superadmin && (
          // Kompaktowo (ikona) — tekstowy przycisk poszerzał kolumnę akcji o ~170 px.
          // Różnica względem zwykłego „Usuń” w podpowiedzi i nazwie dostępnej.
          <button type="button" className="btn btn--ghost btn--sm" style={{ border: 0, color: 'var(--color-error-text)' }}
                  onClick={() => setForceOpen(true)}
                  title="Usuń komórkę (superadmin) — także z pracownikami, podkomórkami i wnioskami; z hasłem i powodem"
                  aria-label={`Usuń komórkę (superadmin): ${d.name}`}>
            <ShieldAlert size={15} aria-hidden="true" />
          </button>
        )}
      </td>
      {forceOpen && (
        <ForceDeleteDeptModal dept={d} onClose={() => setForceOpen(false)}
                              onDone={() => { setForceOpen(false); (onRemoved || onChanged)() }} />
      )}
      {deputiesOpen && (
        <DeputiesModal dept={d} users={users} unitDepts={unitDepts}
                       onClose={() => setDeputiesOpen(false)}
                       onChanged={onChanged} />
      )}
    </tr>
  )
}

// Czytelne podsumowanie odpowiedzi force-delete (DepartmentForceDeleteOut):
// { mode: "deleted"|"archived", department_id, detached_users, detached_user_ids?,
//   removed_deputies, reparented_department_ids, rejected_request_ids, … }.
// department_id / mode / message nie trafiają na listę; nieznane pola pomijamy
// (zamiast pokazywać surowe klucze API).
const FORCE_DELETE_COUNTS = [
  // [etykieta, klucze (pierwszy obecny wygrywa)]
  ['Odpięci pracownicy',   ['detached_users', 'detached_user_ids', 'users_detached']],
  ['Usunięci zastępcy',    ['removed_deputies', 'deputies_removed']],
  ['Przepięte podkomórki', ['reparented_department_ids', 'children_moved', 'moved_children']],
]
const REJECTED_KEYS = ['rejected_request_ids', 'rejected_requests', 'requests_rejected']
const asCount = v => (typeof v === 'number' ? v : Array.isArray(v) ? v.length : null)

function forceDeleteSummary(data) {
  if (!data || typeof data !== 'object') return []
  const out = []
  for (const [label, keys] of FORCE_DELETE_COUNTS) {
    const k = keys.find(x => asCount(data[x]) != null)
    if (k) out.push(`${label}: ${asCount(data[k])}`)
  }
  const rk = REJECTED_KEYS.find(x => asCount(data[x]) != null)
  if (rk) {
    const v = data[rk]
    const ids = Array.isArray(v) ? v.filter(x => x != null) : []
    out.push(`Odrzucone wnioski: ${asCount(v)}${ids.length ? ` (${ids.map(i => `#${i}`).join(', ')})` : ''}`)
  }
  return out
}
const isArchived = data => data?.mode === 'archived' || data?.archived === true

/** Superadmin: usunięcie komórki mimo powiązań (POST …/force-delete). */
function ForceDeleteDeptModal({ dept: d, onClose, onDone }) {
  const [reason, setReason]     = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy]         = useState(false)
  const [err, setErr]           = useState(null)
  const [result, setResult]     = useState(null)
  const pwRef = useRef(null)
  const canSubmit = reason.trim().length > 0 && password.length > 0 && !busy

  async function submit(e) {
    e?.preventDefault()
    if (!canSubmit) return
    setBusy(true); setErr(null)
    try {
      const r = await forceDeleteDepartment(d.id, { reason: reason.trim(), password })
      const data = r.data || {}
      setResult(data)
      toast(isArchived(data)
        ? `Zarchiwizowano komórkę „${d.name}” (ma historię)`
        : `Usunięto komórkę „${d.name}”`)
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się usunąć komórki'))
      // Fokus zostaje w oknie — na polu hasła, zaznaczonym do poprawy.
      requestAnimationFrame(() => { pwRef.current?.focus(); pwRef.current?.select() })
    } finally { setBusy(false) }
  }

  if (result) {
    const lines = forceDeleteSummary(result)
    const archived = isArchived(result)
    // key: nowe okno (nie ponowne użycie formularza) — useDialog ustawia fokus
    // na „Zamknij”, zamiast zostawić go na zniszczonym przycisku wysyłki.
    return (
      <Modal key="result" title={`${archived ? 'Zarchiwizowano komórkę (ma historię)' : 'Usunięto komórkę'} — ${d.name}`}
             onClose={onDone} width={520}
             footer={<button type="button" className="btn btn--primary" data-autofocus onClick={onDone}>Zamknij</button>}>
        {archived && (
          <p style={{ marginTop: 0 }}>
            Komórka ma historię (wnioski, uprawnienia), więc zamiast usunięcia została zarchiwizowana
            i nie jest już widoczna w strukturze.
          </p>
        )}
        {result.message && <p style={{ marginTop: 0 }}>{result.message}</p>}
        {lines.length > 0 ? (
          <ul style={{ margin: 0, paddingLeft: 20, fontSize: 14 }}>
            {lines.map(l => <li key={l}>{l}</li>)}
          </ul>
        ) : !result.message && <p style={{ margin: 0 }}>Operacja zakończona.</p>}
      </Modal>
    )
  }

  return (
    <Modal key="form" title={`Usuń komórkę (superadmin) — ${d.name}`} onClose={onClose} closable={!busy} width={560}
           onSubmit={submit}
           footer={<>
             <button type="button" className="btn btn--ghost" onClick={onClose} disabled={busy}>Anuluj</button>
             {/* aria-disabled zamiast disabled — przycisk nie gubi fokusu podczas wysyłki. */}
             <button type="submit" className="btn btn--danger" aria-disabled={!canSubmit}>
               <Trash2 size={14} aria-hidden="true" /> {busy ? 'Usuwanie…' : 'Usuń komórkę'}
             </button>
           </>}>
      <div className="alert alert--warning" style={{ marginTop: 0 }}>
        <strong>Skutki operacji:</strong>
        <ul style={{ margin: '6px 0 0', paddingLeft: 20 }}>
          <li>pracownicy komórki zostaną odpięci (bez komórki),</li>
          <li>podkomórki zostaną przepięte poziom wyżej,</li>
          <li>wnioski w toku zostaną odrzucone,</li>
          <li>komórka z historią (wnioski, uprawnienia) zostanie zarchiwizowana zamiast usunięta.</li>
        </ul>
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor={`fd-reason-${d.id}`}>Powód *</label>
        <textarea id={`fd-reason-${d.id}`} className="form-control" rows={3} required data-autofocus
                  value={reason} onChange={e => setReason(e.target.value)}
                  placeholder="np. likwidacja komórki zarządzeniem nr …" />
      </div>
      <div className="form-group">
        <label className="form-label" htmlFor={`fd-pw-${d.id}`}>Twoje hasło *</label>
        <input id={`fd-pw-${d.id}`} ref={pwRef} className="form-control" type="password" required
               autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} />
        <div className="form-hint">Operacja zostanie zapisana w dzienniku zdarzeń.</div>
      </div>
      {err && <div className="alert alert--error" role="alert">{err}</div>}
    </Modal>
  )
}

function AddDeptForm({ unitId, users, unitDepts, onAdded }) {
  const [name, setName]         = useState('')
  const [kind, setKind]         = useState('department')
  const [parentId, setParentId] = useState('')
  const [managerId, setManagerId] = useState('')
  const [err, setErr] = useState(null)

  async function submit(e) {
    e.preventDefault(); setErr(null)
    try {
      await createDepartment({
        name,
        unit_id: unitId,
        kind,
        parent_dept_id: parentId ? Number(parentId) : null,
        manager_user_id: managerId ? Number(managerId) : null,
      })
      setName(''); setKind('department'); setParentId(''); setManagerId('')
      onAdded()
    } catch (ex) { setErr(errorMessage(ex, 'Nie udało się dodać komórki')) }
  }

  const parentCandidates = flattenDeptTree(unitDepts || [])

  return (
    <form onSubmit={submit} style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
      <div className="form-group" style={{ margin: 0, flex: 2, minWidth: 160 }}>
        <label className="form-label" htmlFor={`ad-name-${unitId}`}>Nowy węzeł</label>
        <input id={`ad-name-${unitId}`} className="form-control" required value={name}
               onChange={e => setName(e.target.value)}
               placeholder="Nazwa (np. Wydział Finansów, Referat Księgowości, Pełnomocnik ds. …)" />
      </div>
      <div className="form-group" style={{ margin: 0, flex: 1, minWidth: 160 }}>
        <label className="form-label" htmlFor={`ad-kind-${unitId}`}>Typ</label>
        <select id={`ad-kind-${unitId}`} className="form-control" value={kind} onChange={e => setKind(e.target.value)}>
          {DEPT_KINDS.map(k => (
            <option key={k.value} value={k.value}>{k.label}</option>
          ))}
        </select>
      </div>
      <div className="form-group" style={{ margin: 0, flex: 2, minWidth: 180 }}>
        <label className="form-label" htmlFor={`ad-parent-${unitId}`}>Węzeł nadrzędny</label>
        <select id={`ad-parent-${unitId}`} className="form-control" value={parentId}
                onChange={e => setParentId(e.target.value)}>
          <option value="">— bezpośrednio pod jednostką —</option>
          {parentCandidates.map(({ dept: x, depth: xd }) => (
            <option key={x.id} value={x.id}>
              {'\u00A0'.repeat(xd * 2)}{x.name} ({kindMeta(x.kind).label})
            </option>
          ))}
        </select>
      </div>
      <div className="form-group" style={{ margin: 0, flex: 2, minWidth: 160 }}>
        <label className="form-label" htmlFor={`ad-mgr-${unitId}`}>Kierownik</label>
        {kind === 'standalone' ? (
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', fontStyle: 'italic', paddingTop: 8 }}>
            — podlega kierownikowi wyżej —
          </div>
        ) : (
          <select id={`ad-mgr-${unitId}`} className="form-control" value={managerId} onChange={e => setManagerId(e.target.value)}>
            <option value="">— brak —</option>
            <ManagerOptions users={users} unitDeptIds={(unitDepts || []).map(x => x.id)}
                            currentId={managerId} />
          </select>
        )}
      </div>
      <button type="submit" className="btn btn--primary" style={{ marginBottom: 0 }}>
        <Plus size={14} /> Dodaj
      </button>
      <ErrorAlert style={{ width: '100%' }}>{err}</ErrorAlert>
    </form>
  )
}

function AddUnitCard({ onAdded }) {
  const [show, setShow] = useState(false)
  const [name, setName] = useState('')
  const [err, setErr] = useState(null)

  async function submit(e) {
    e.preventDefault(); setErr(null)
    try {
      await createUnit({ name })
      setName(''); setShow(false); onAdded()
    } catch (ex) { setErr(errorMessage(ex, 'Nie udało się dodać jednostki')) }
  }

  if (!show) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 16px', borderRadius: 10,
                    border: '1px dashed var(--color-input-border)', background: 'var(--color-card)' }}>
        <span style={{ flex: 1, fontSize: 14, color: 'var(--color-text-muted)' }}>
          Nowa jednostka organizacyjna (poziom 1 struktury).
        </span>
        <button type="button" className="btn btn--action" onClick={() => setShow(true)}>
          <Plus size={14} /> Dodaj jednostkę
        </button>
      </div>
    )
  }

  return (
    <div className="card" style={{ borderTop: '3px solid var(--color-gold)' }}>
      <form onSubmit={submit}>
        <div className="form-group">
          <label className="form-label" htmlFor="unit-new-name">Nazwa jednostki *</label>
          <input id="unit-new-name" className="form-control" required value={name} onChange={e => setName(e.target.value)} />
        </div>
        <ErrorAlert className="mb-4">{err}</ErrorAlert>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn--ghost" onClick={() => setShow(false)}>Anuluj</button>
          <button type="submit" className="btn btn--primary">Zapisz</button>
        </div>
      </form>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Import struktury z Active Directory
// ---------------------------------------------------------------------------

function DeptTreeNode({ node, depth, selected, onToggle, deptMap, onMapDept, deptOptions }) {
  const [open, setOpen] = useState(true)
  const hasKids = node.children && node.children.length > 0
  const mappedId = deptMap[node.dn] || ''
  return (
    <div>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer', userSelect: 'none', fontSize: 13 }}>
        {hasKids ? (
          <button
            type="button"
            onClick={e => { e.preventDefault(); setOpen(v => !v) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, display: 'inline-flex', color: 'var(--color-text-muted)' }}
            aria-label={`${open ? 'Zwiń' : 'Rozwiń'}: ${node.name}`} aria-expanded={open}
          >
            {open ? <ChevronDown size={12} aria-hidden="true" /> : <ChevronRight size={12} aria-hidden="true" />}
          </button>
        ) : (
          <span style={{ display: 'inline-block', width: 12 }} />
        )}
        <input
          type="checkbox"
          checked={!!selected[node.dn] || !!mappedId}
          disabled={!!mappedId}
          aria-label={`Importuj: ${node.name}`}
          onChange={() => onToggle(node, true)}
        />
        <span>{node.name}</span>
        {mappedId ? (
          <span className="badge badge--info" style={{ fontSize: 10 }}>mapowany</span>
        ) : (
          <span className={`badge ${node.status === 'new' ? 'badge--info' : 'badge--neutral'}`} style={{ fontSize: 10 }}>
            {node.status === 'new' ? 'nowy' : 'już istnieje'}
          </span>
        )}
        <select
          value={mappedId}
          onChange={e => onMapDept(node.dn, e.target.value ? Number(e.target.value) : null)}
          onClick={e => e.preventDefault()}
          className="form-control"
          style={{ fontSize: 11, padding: '1px 4px', width: 'auto', maxWidth: 220, marginLeft: 'auto' }}
          aria-label={`Mapuj „${node.name}” na istniejący wydział`}
          title="Mapuj na istniejący wydział"
        >
          <option value="">— mapuj na istniejący —</option>
          {deptOptions.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
        </select>
      </label>
      {hasKids && open && (
        <div style={{ marginLeft: 18, marginTop: 3, display: 'flex', flexDirection: 'column', gap: 3 }}>
          {node.children.map(c => (
            <DeptTreeNode key={c.dn} node={c} depth={depth + 1} selected={selected} onToggle={onToggle}
                          deptMap={deptMap} onMapDept={onMapDept} deptOptions={deptOptions} />
          ))}
        </div>
      )}
    </div>
  )
}


function LdapImportModal({ onClose }) {
  const [searchBase, setSearchBase] = useState('')
  const [step, setStep]             = useState('input')   // 'input' | 'preview' | 'importing' | 'done'
  const [preview, setPreview]       = useState([])
  const [selected, setSelected]     = useState({})        // keyed by DN
  const [unitMap, setUnitMap]       = useState({})        // unit DN → istniejący unit_id
  const [deptMap, setDeptMap]       = useState({})        // dept DN → istniejący dept_id
  const [unitOptions, setUnitOptions] = useState([])      // {id,label} istniejących jednostek
  const [deptOptions, setDeptOptions] = useState([])      // {id,label} istniejących wydziałów
  const [busy, setBusy]             = useState(false)
  const [err, setErr]               = useState(null)
  const [result, setResult]         = useState(null)

  // Pobierz istniejące jednostki/wydziały do mapowania ręcznego.
  useEffect(() => {
    let alive = true
    Promise.all([listUnits(), listAllDepartments()]).then(([u, d]) => {
      if (!alive) return
      const unitName = {}
      u.data.forEach(x => { unitName[x.id] = x.name })
      setUnitOptions(u.data.map(x => ({ id: x.id, label: x.name })))
      setDeptOptions(d.data.map(x => ({
        id: x.id,
        label: `${unitName[x.unit_id] ? unitName[x.unit_id] + ' › ' : ''}${x.name}`,
      })))
    }).catch(ex => {
      if (alive) toast(errorMessage(ex, 'Nie udało się wczytać listy jednostek do mapowania'), { tone: 'warning' })
    })
    return () => { alive = false }
  }, [])

  function mapUnit(dn, id) { setUnitMap(prev => ({ ...prev, [dn]: id })) }
  function mapDept(dn, id) { setDeptMap(prev => ({ ...prev, [dn]: id })) }

  // ------ drzewo: helpers ------

  function walkDepts(nodes, fn) {
    for (const n of nodes) { fn(n); walkDepts(n.children || [], fn) }
  }

  function countNodes(nodes) {
    let c = 0
    walkDepts(nodes, () => c++)
    return c
  }

  function countNew(nodes) {
    let c = 0
    walkDepts(nodes, n => { if (n.status === 'new') c++ })
    return c
  }

  function initSelected(data) {
    // Zaznaczamy WSZYSTKO (nowe i istniejące) — import jest idempotentny:
    // istniejące komórki PRZENIESIE pod właściwego rodzica (zaczyta podległości),
    // nowe utworzy, duplikatów nie zrobi. Użytkownik może odznaczyć.
    const s = {}
    for (const unit of data) {
      s[unit.dn] = true
      walkDepts(unit.departments, n => { s[n.dn] = true })
    }
    return s
  }

  function selectAllNew() { setSelected(initSelected(preview)) }
  function deselectAll() {
    const s = {}
    for (const unit of preview) {
      s[unit.dn] = false
      walkDepts(unit.departments, n => { s[n.dn] = false })
    }
    setSelected(s)
  }

  function toggleNode(node, cascade) {
    setSelected(prev => {
      const next = !prev[node.dn]
      const s = { ...prev, [node.dn]: next }
      if (cascade && next) {
        // zaznacz wszystkie nowe potomki
        walkDepts(node.children || [], c => { if (c.status === 'new') s[c.dn] = true })
        if (node.departments) walkDepts(node.departments, c => { if (c.status === 'new') s[c.dn] = true })
      }
      return s
    })
  }

  function countSelected() {
    return Object.values(selected).filter(Boolean).length
  }

  // Zbuduj zagnieżdżoną listę wydziałów do importu; jeśli któreś dziecko
  // jest zaznaczone, trzeba włączyć rodzica (idempotentne: backend pominie istniejące).
  function collectDepts(nodes) {
    const out = []
    for (const n of nodes) {
      const kids = collectDepts(n.children || [])
      const mapId = deptMap[n.dn] || null
      // Dołączamy, gdy: zaznaczone / zmapowane / ma zaznaczone dzieci, ALBO gdy
      // istnieje i ma opis z AD (żeby synchronizacja dociagnela opis bez
      // wymuszania recznego zaznaczania istniejacych komorek).
      const syncDesc = n.status === 'exists' && !!n.description
      if (selected[n.dn] || mapId || kids.length > 0 || syncDesc) {
        out.push({ name: n.name, dn: n.dn, description: n.description ?? null, map_to_dept_id: mapId, children: kids })
      }
    }
    return out
  }

  // ------ fetch preview ------

  async function fetchPreview() {
    setBusy(true); setErr(null)
    try {
      const r = await ldapPreviewUnits(searchBase || null)
      if (!r.data.length) { setErr('Nie znaleziono żadnych jednostek organizacyjnych pod podanym DN.'); setBusy(false); return }
      setPreview(r.data)
      setSelected(initSelected(r.data))
      setStep('preview')
    } catch (ex) {
      setErr(errorMessage(ex, 'Błąd połączenia z LDAP'))
    } finally { setBusy(false) }
  }

  // ------ import ------

  async function doImport() {
    setBusy(true); setErr(null); setStep('importing')
    const items = []
    for (const unit of preview) {
      const depts = collectDepts(unit.departments)
      const mapId = unitMap[unit.dn] || null
      const syncUnitDesc = unit.status === 'exists' && !!unit.description
      if (selected[unit.dn] || mapId || depts.length > 0 || syncUnitDesc) {
        items.push({ unit_name: unit.name, unit_dn: unit.dn, description: unit.description ?? null, map_to_unit_id: mapId, departments: depts })
      }
    }
    try {
      const r = await ldapImportUnits(items)
      setResult(r.data)
      setStep('done')
    } catch (ex) {
      setErr(errorMessage(ex, 'Błąd importu'))
      setStep('preview')
    } finally { setBusy(false) }
  }

  // ------ render ------

  const newCount   = preview.reduce((n, u) => n + (u.status === 'new' ? 1 : 0) + countNew(u.departments), 0)
  const totalCount = preview.reduce((n, u) => n + 1 + countNodes(u.departments), 0)

  return (
    // Wspólne ui/Modal (pułapka fokusu, Escape, zwrot fokusu, blokada przewijania).
    <Modal title={'Import struktury z Active Directory'} onClose={onClose} width={680}>

      {/* Krok 1 — podaj search base */}
      {(step === 'input' || step === 'preview') && (
        <div style={{ marginBottom: 16 }}>
          <div className="form-group" style={{ marginBottom: 8 }}>
            <label className="form-label" htmlFor="ldap-units-base">Baza wyszukiwania (Search Base DN)</label>
            <input id="ldap-units-base"
              className="form-control"
              placeholder="np. OU=Organizacja,DC=firma,DC=local"
              value={searchBase}
              onChange={e => setSearchBase(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !busy && fetchPreview()}
            />
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              Puste pole — zostanie użyte Base DN z konfiguracji LDAP.
              Poziom 1 OUs → jednostki, głębsze poziomy → drzewo wydziałów.
            </div>
          </div>
          <button type="button" className="btn btn--primary btn--sm" onClick={fetchPreview} disabled={busy}>
            {busy ? 'Pobieranie…' : 'Pobierz strukturę z AD'}
          </button>
        </div>
      )}

      <ErrorAlert style={{ marginBottom: 12 }}>{err}</ErrorAlert>

      {/* Krok 2 — podgląd */}
      {step === 'preview' && preview.length > 0 && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
            <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              Znaleziono {totalCount} elementów ({newCount} nowych)
            </span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button type="button" className="btn btn--ghost btn--sm" onClick={selectAllNew}>Zaznacz wszystko</button>
              <button type="button" className="btn btn--ghost btn--sm" onClick={deselectAll}>Odznacz wszystkie</button>
            </div>
          </div>

          <div style={{ maxHeight: 380, overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: 6, padding: '8px 12px' }}>
            {preview.map(unit => (
              <div key={unit.dn} style={{ marginBottom: 10 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', userSelect: 'none' }}>
                  <input
                    type="checkbox"
                    checked={!!selected[unit.dn] || !!unitMap[unit.dn]}
                    disabled={!!unitMap[unit.dn]}
                    onChange={() => toggleNode(unit, true)}
                  />
                  <Building2 size={13} style={{ color: 'var(--color-heading)', flexShrink: 0 }} />
                  <span style={{ fontWeight: 700, fontSize: 13 }}>{unit.name}</span>
                  {unitMap[unit.dn] ? (
                    <span className="badge badge--info" style={{ fontSize: 10 }}>mapowana</span>
                  ) : (
                    <span className={`badge ${unit.status === 'new' ? 'badge--success' : 'badge--neutral'}`} style={{ fontSize: 10 }}>
                      {unit.status === 'new' ? 'nowa' : 'już istnieje'}
                    </span>
                  )}
                  <select
                    value={unitMap[unit.dn] || ''}
                    onChange={e => mapUnit(unit.dn, e.target.value ? Number(e.target.value) : null)}
                    onClick={e => e.preventDefault()}
                    className="form-control"
                    style={{ fontSize: 11, padding: '1px 4px', width: 'auto', maxWidth: 220, marginLeft: 'auto' }}
                    title="Mapuj na istniejącą jednostkę"
                  >
                    <option value="">— mapuj na istniejącą —</option>
                    {unitOptions.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
                  </select>
                </label>

                {unit.departments.length > 0 && (
                  <div style={{ marginLeft: 20, marginTop: 4, display: 'flex', flexDirection: 'column', gap: 3 }}>
                    {unit.departments.map(dept => (
                      <DeptTreeNode
                        key={dept.dn}
                        node={dept}
                        depth={0}
                        selected={selected}
                        onToggle={toggleNode}
                        deptMap={deptMap}
                        onMapDept={mapDept}
                        deptOptions={deptOptions}
                      />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
            <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>Anuluj</button>
            <button
              className="btn btn--primary btn--sm"
              onClick={doImport}
              disabled={busy || countSelected() === 0}
            >
              Importuj zaznaczone ({countSelected()})
            </button>
          </div>
        </>
      )}

      {/* Krok 3 — wynik */}
      {step === 'done' && result && (
        <>
          <div className="alert alert--success" style={{ marginBottom: 14 }}>
            Import zakończony: utworzono <strong>{result.units_created}</strong> jednostek
            i <strong>{result.departments_created}</strong> wydziałów.
            {(result.units_skipped + result.departments_skipped) > 0 && (
              <span> Pominięto {result.units_skipped + result.departments_skipped} istniejących.</span>
            )}
          </div>
          <div style={{ maxHeight: 260, overflowY: 'auto', fontSize: 12, fontFamily: 'var(--font-mono)', background: 'var(--bg-secondary)', borderRadius: 6, padding: '10px 14px', color: 'var(--color-text-muted)' }}>
            {result.details.map((line, i) => <div key={i}>{line}</div>)}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
            <button type="button" className="btn btn--primary btn--sm" onClick={onClose}>Zamknij</button>
          </div>
        </>
      )}

    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Import użytkowników z Active Directory
// ---------------------------------------------------------------------------

export function LdapUsersImportModal({ onClose }) {
  const [searchBase, setSearchBase] = useState('')
  const [step, setStep]             = useState('input')
  const [users, setUsers]           = useState([])
  const [selected, setSelected]     = useState({})   // username → bool
  const [busy, setBusy]             = useState(false)
  const [err, setErr]               = useState(null)
  const [result, setResult]         = useState(null)
  const [query, setQuery]           = useState('')
  // Wybór jednostek najwyższego rzędu do pobrania (null = wszystkie, ustawiane po podglądzie).
  const [selectedUnits, setSelectedUnits] = useState(null)   // Set<number> | null (klucz: unit_id, 0 = bez jednostki)

  function importable(u) {
    // Importowalny = w powiązanej strukturze OU, nie w konflikcie, aktywny w AD, nie duplikat.
    return u.in_structure && u.status !== 'conflict' && u.is_enabled_in_ad && !u.duplicate
  }

  function initSelected(data) {
    const s = {}
    for (const u of data) s[u.username] = importable(u)
    return s
  }

  async function fetchPreview() {
    setBusy(true); setErr(null)
    try {
      const r = await ldapPreviewUsers(searchBase || null)
      if (!r.data.length) { setErr('Nie znaleziono użytkowników pod podanym DN.'); setBusy(false); return }
      setUsers(r.data)
      setSelected(initSelected(r.data))
      // Domyślnie zaznacz wszystkie jednostki najwyższego rzędu obecne w podglądzie.
      setSelectedUnits(new Set(
        r.data.filter(u => u.in_structure).map(u => u.unit_id ?? 0)))
      setStep('preview')
    } catch (ex) {
      setErr(errorMessage(ex, 'Błąd połączenia z LDAP'))
    } finally { setBusy(false) }
  }

  async function doImport() {
    setBusy(true); setErr(null); setStep('importing')
    const usernames = users
      .filter(u => selected[u.username] && importable(u) && inSelectedUnit(u))
      .map(u => u.username)
    try {
      const r = await ldapImportUsers(usernames, searchBase || null)
      setResult(r.data)
      setStep('done')
    } catch (ex) {
      setErr(errorMessage(ex, 'Błąd importu'))
      setStep('preview')
    } finally { setBusy(false) }
  }

  function toggle(username) {
    setSelected(prev => ({ ...prev, [username]: !prev[username] }))
  }

  function toggleUnit(key) {
    setSelectedUnits(prev => {
      const n = new Set(prev || [])
      n.has(key) ? n.delete(key) : n.add(key)
      return n
    })
  }

  function selectAllMapped() {
    setSelected(prev => {
      const s = { ...prev }
      for (const u of visibleUsers) s[u.username] = importable(u)
      return s
    })
  }

  function deselectAll() {
    setSelected(prev => {
      const s = { ...prev }
      for (const u of visibleUsers) s[u.username] = false
      return s
    })
  }

  // Sort: OU (unit → department) → pełna nazwa, z filtrowaniem po frazie.
  function ouKey(u) {
    return `${(u.unit_name || '\uffff').toLowerCase()}\u0001${(u.department_name || '\uffff').toLowerCase()}`
  }
  // Czy użytkownik jest w zaznaczonej jednostce najwyższego rzędu.
  const inSelectedUnit = u => !selectedUnits || selectedUnits.has(u.unit_id ?? 0)

  // Jednostki najwyższego rzędu obecne w podglądzie — do checkboxów wyboru.
  const unitChoices = (() => {
    const m = new Map()
    for (const u of users) {
      if (!u.in_structure) continue
      const k = u.unit_id ?? 0
      if (!m.has(k)) m.set(k, { key: k, label: u.unit_name || '(bez jednostki nadrzędnej)', count: 0 })
      m.get(k).count++
    }
    return [...m.values()].sort((a, b) => a.label.localeCompare(b.label, 'pl'))
  })()

  const q = query.trim().toLowerCase()
  const visibleUsers = users
    // Pokazujemy tylko osoby z powiązanych jednostek organizacyjnych —
    // pozostałych nie da się zaimportować, więc nie zaśmiecamy nimi listy.
    .filter(u => u.in_structure)
    .filter(inSelectedUnit)
    .filter(u => {
      if (!q) return true
      return (
        (u.username && u.username.toLowerCase().includes(q)) ||
        (u.full_name && u.full_name.toLowerCase().includes(q)) ||
        (u.email && u.email.toLowerCase().includes(q)) ||
        (u.unit_name && u.unit_name.toLowerCase().includes(q)) ||
        (u.department_name && u.department_name.toLowerCase().includes(q))
      )
    })
    .slice()
    .sort((a, b) => {
      const ka = ouKey(a), kb = ouKey(b)
      if (ka !== kb) return ka < kb ? -1 : 1
      const na = (a.full_name || a.username || '').toLowerCase()
      const nb = (b.full_name || b.username || '').toLowerCase()
      return na < nb ? -1 : na > nb ? 1 : 0
    })

  // Liczba realnie importowalnych zaznaczonych (z uwzględnieniem wyboru jednostek).
  const selectedCount = users.filter(
    u => selected[u.username] && importable(u) && inSelectedUnit(u)).length
  const inStructure   = users.filter(u => u.in_structure)
  const outOfStruct   = users.length - inStructure.length
  const conflicts     = inStructure.filter(u => u.status === 'conflict').length
  const noDept        = inStructure.filter(u => !u.department_id && u.status !== 'conflict').length
  const disabledCnt   = inStructure.filter(u => !u.is_enabled_in_ad).length
  const duplicateCnt  = inStructure.filter(u => u.duplicate).length

  return (
    // Wspólne ui/Modal (pułapka fokusu, Escape, zwrot fokusu, blokada przewijania).
    <Modal title={'Import użytkowników z Active Directory'} onClose={onClose} width={820}>

      {(step === 'input' || step === 'preview') && (
        <div style={{ marginBottom: 16 }}>
          <div className="form-group" style={{ marginBottom: 8 }}>
            <label className="form-label" htmlFor="ldap-users-base">Baza wyszukiwania (Search Base DN)</label>
            <input id="ldap-users-base"
              className="form-control"
              placeholder="np. OU=Organizacja,DC=firma,DC=local"
              value={searchBase}
              onChange={e => setSearchBase(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && !busy && fetchPreview()}
            />
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              <strong>Najpierw zaimportuj strukturę</strong> (jednostki organizacyjne) z AD.
              Importujemy wyłącznie osoby z powiązanych jednostek — reszta jest pomijana.
              Bez pobranej struktury import użytkowników jest zablokowany.
            </div>
          </div>
          <button type="button" className="btn btn--primary btn--sm" onClick={fetchPreview} disabled={busy}>
            {busy ? 'Pobieranie…' : 'Pobierz użytkowników z AD'}
          </button>
        </div>
      )}

      <ErrorAlert style={{ marginBottom: 12 }}>{err}</ErrorAlert>

      {step === 'preview' && users.length > 0 && (
        <>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
              W powiązanych jednostkach: {inStructure.length}
              {query && <> · pokazano {visibleUsers.length}</>}
              {outOfStruct > 0 && <> · <strong>{outOfStruct}</strong> poza powiązaną strukturą (ukryte, nie do importu)</>}
              {conflicts > 0 && <> · <span style={{ color: 'var(--color-danger)' }}>{conflicts} konflikt(ów) z kontami lokalnymi</span></>}
              {noDept > 0  && <> · {noDept} bez konkretnego wydziału</>}
              {disabledCnt > 0 && <> · {disabledCnt} wyłączonych w AD (pomijane)</>}
              {duplicateCnt > 0 && <> · {duplicateCnt} duplikat(ów) loginu (pomijane)</>}
            </span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button type="button" className="btn btn--ghost btn--sm" onClick={selectAllMapped}>Zaznacz zmapowanych</button>
              <button type="button" className="btn btn--ghost btn--sm" onClick={deselectAll}>Odznacz wszystkich</button>
            </div>
          </div>

          {unitChoices.length > 0 && (
            <div style={{ border: '1px solid var(--border-color)', borderRadius: 6,
                          padding: '8px 10px', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 6 }}>
                <strong style={{ fontSize: 12 }}>Jednostki najwyższego rzędu do pobrania:</strong>
                <button type="button" className="btn btn--ghost btn--sm" style={{ fontSize: 11 }}
                        onClick={() => setSelectedUnits(new Set(unitChoices.map(c => c.key)))}>
                  wszystkie
                </button>
                <button type="button" className="btn btn--ghost btn--sm" style={{ fontSize: 11 }}
                        onClick={() => setSelectedUnits(new Set())}>
                  żadne
                </button>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 16px' }}>
                {unitChoices.map(c => (
                  <label key={c.key} style={{ display: 'flex', alignItems: 'center', gap: 6,
                                               fontSize: 12, cursor: 'pointer' }}>
                    <input type="checkbox"
                           checked={!selectedUnits || selectedUnits.has(c.key)}
                           onChange={() => toggleUnit(c.key)} />
                    {c.label}
                    <span className="badge badge--neutral" style={{ fontSize: 9 }}>{c.count}</span>
                  </label>
                ))}
              </div>
            </div>
          )}

          <div style={{ marginBottom: 8 }}>
            <input
              className="form-control"
              style={{ fontSize: 12 }}
              placeholder="Szukaj po nazwisku, loginie, e-mailu lub wydziale…"
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
          </div>

          <div style={{ maxHeight: 420, overflowY: 'auto', border: '1px solid var(--border-color)', borderRadius: 6 }}>
            <table className="data-table" style={{ fontSize: 12, margin: 0 }}>
              <thead>
                <tr>
                  <th style={{ width: 30 }}></th>
                  <th>Użytkownik</th>
                  <th>Email</th>
                  <th>Wydział (z AD)</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const rows = []
                  let lastKey = null
                  for (const u of visibleUsers) {
                    const key = ouKey(u)
                    if (key !== lastKey) {
                      const label = u.department_name
                        ? `${u.unit_name ? u.unit_name + ' › ' : ''}${u.department_name}`
                        : (u.unit_name ? `${u.unit_name} (bez wydziału)` : '— bez przypisania —')
                      rows.push(
                        <tr key={`grp-${key}`} style={{ background: 'var(--bg-secondary)' }}>
                          <td colSpan={5} style={{ fontWeight: 700, color: 'var(--color-heading)', padding: '4px 10px' }}>
                            {label}
                          </td>
                        </tr>
                      )
                      lastKey = key
                    }
                    const disabled = u.status === 'conflict' || !u.is_enabled_in_ad || u.duplicate
                    rows.push(
                      <tr key={u.username} style={disabled ? { opacity: 0.55 } : undefined}>
                        <td>
                          <input
                            type="checkbox"
                            checked={!!selected[u.username]}
                            disabled={disabled}
                            onChange={() => toggle(u.username)}
                          />
                        </td>
                        <td>
                          <div style={{ fontWeight: 600 }}>{u.full_name || u.username}</div>
                          <div style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>{u.username}</div>
                        </td>
                        <td style={{ color: 'var(--color-text-muted)' }}>{u.email || '—'}</td>
                        <td>
                          {u.department_name
                            ? <>
                                {u.unit_name && <span style={{ color: 'var(--color-text-muted)' }}>{u.unit_name} › </span>}
                                {u.department_name}
                              </>
                            : u.unit_name
                              ? <span style={{ color: 'var(--color-text-muted)' }}>{u.unit_name} (bez wydziału)</span>
                              : <span style={{ color: 'var(--color-text-muted)' }}>— brak —</span>}
                        </td>
                        <td>
                          {u.status === 'new' && <span className="badge badge--success" style={{ fontSize: 10 }}>nowy</span>}
                          {u.status === 'exists_ldap' && <span className="badge badge--neutral" style={{ fontSize: 10 }}>aktualizacja</span>}
                          {u.status === 'conflict' && <span className="badge badge--error" style={{ fontSize: 10 }}>konflikt lokalny</span>}
                          {!u.is_enabled_in_ad && <span className="badge badge--neutral" style={{ fontSize: 10, marginLeft: 4 }}>wyłączony w AD</span>}
                          {u.duplicate && <span className="badge badge--warning" style={{ fontSize: 10, marginLeft: 4 }}>duplikat loginu</span>}
                        </td>
                      </tr>
                    )
                  }
                  if (rows.length === 0) {
                    rows.push(
                      <tr key="empty"><td colSpan={5} style={{ color: 'var(--color-text-muted)', padding: '10px 12px' }}>
                        Brak pasujących użytkowników.
                      </td></tr>
                    )
                  }
                  return rows
                })()}
              </tbody>
            </table>
          </div>

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
            <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>Anuluj</button>
            <button
              className="btn btn--primary btn--sm"
              onClick={doImport}
              disabled={busy || selectedCount === 0}
            >
              Importuj zaznaczonych ({selectedCount})
            </button>
          </div>
        </>
      )}

      {step === 'done' && result && (
        <>
          <div className="alert alert--success" style={{ marginBottom: 14 }}>
            Import zakończony: utworzono <strong>{result.created}</strong>,
            zaktualizowano <strong>{result.updated}</strong>.
            {result.conflicts > 0 && <> Konfliktów: {result.conflicts}.</>}
            {result.skipped > 0 && <> Pominięto: {result.skipped}.</>}
          </div>
          <div style={{ maxHeight: 260, overflowY: 'auto', fontSize: 12, fontFamily: 'var(--font-mono)', background: 'var(--bg-secondary)', borderRadius: 6, padding: '10px 14px', color: 'var(--color-text-muted)' }}>
            {result.details.map((line, i) => <div key={i}>{line}</div>)}
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 14 }}>
            <button type="button" className="btn btn--primary btn--sm" onClick={onClose}>Zamknij</button>
          </div>
        </>
      )}

    </Modal>
  )
}

// ---------------------------------------------------------------------------
// Modal zarządzania zastępcami kierownika komórki
// ---------------------------------------------------------------------------
function DeputiesModal({ dept, users, unitDepts = [], onClose, onChanged }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [addUserId, setAddUserId] = useState('')
  const [addLabel, setAddLabel] = useState('')
  const [busy, setBusy] = useState(false)

  async function load() {
    setLoading(true); setErr(null)
    try {
      const r = await listDeputies(dept.id)
      setRows(r.data)
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się załadować listy zastępców'))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [dept.id])

  const alreadyIds = new Set(rows.map(r => r.user_id).concat([dept.manager_user_id].filter(Boolean)))

  async function onAdd() {
    if (!addUserId) return
    setBusy(true); setErr(null)
    try {
      await addDeputy(dept.id, {
        user_id: Number(addUserId),
        role_label: addLabel.trim() || null,
      })
      setAddUserId(''); setAddLabel('')
      await load(); onChanged?.()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się dodać zastępcy'))
    } finally { setBusy(false) }
  }

  async function onEditLabel(row, newLabel) {
    try {
      await updateDeputy(row.id, { user_id: row.user_id, role_label: newLabel })
      await load(); onChanged?.()
    } catch (ex) { toast(errorMessage(ex, 'Nie udało się zapisać zmiany'), { tone: 'error' }) }
  }

  async function onDelete(row) {
    if (!await ask('Odebrać uprawnienia zastępcy: ' + row.user_name + '?', { title: 'Potwierdź operację', confirmLabel: 'Odbierz uprawnienia', danger: true })) return
    try {
      await deleteDeputy(row.id)
      await load(); onChanged?.()
      toast(`Odebrano uprawnienia zastępcy: ${row.user_name}`)
    } catch (ex) { toast(errorMessage(ex, 'Nie udało się zapisać zmiany'), { tone: 'error' }) }
  }

  return (
    <td colSpan={999} style={{ padding: 0, background: 'transparent' }}>
      <Modal title={`Zastępcy w komórce „${dept.name}”`} onClose={onClose} width={620}>
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>
            Osoby z pełnymi uprawnieniami kierownika tej komórki (obok głównego kierownika).
            Mogą akceptować wnioski, wybierać uprawnienia i widzieć pracowników.
          </div>

          {err && <div className="alert alert--error mb-4" role="alert">{err}</div>}

          <div style={{ margin: '12px 0', padding: 10,
                        background: 'var(--bg-secondary)', borderRadius: 6 }}>
            <div style={{ fontSize: 11, fontWeight: 700, marginBottom: 6, color: 'var(--color-text-muted)' }}>
              Dodaj zastępcę
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr auto', gap: 6 }}>
              <select className="input input--sm" value={addUserId} aria-label="Osoba"
                      onChange={e => setAddUserId(e.target.value)}>
                <option value="">— wybierz osobę —</option>
                <ManagerOptions users={users} deptId={dept.id}
                                unitDeptIds={unitDepts.map(x => x.id)} exclude={[...alreadyIds]} />
              </select>
              <input className="input input--sm" value={addLabel} aria-label="Funkcja"
                     onChange={e => setAddLabel(e.target.value)}
                     placeholder="Funkcja (np. Zastępca, Koordynator IT)" />
              <button type="button" className="btn btn--action btn--sm" onClick={onAdd} disabled={busy || !addUserId}>
                <Plus size={12} /> Dodaj
              </button>
            </div>
          </div>

          <div style={{ overflowX: 'auto' }}>
          <table className="table" style={{ minWidth: 440 }}>
            <thead>
              <tr><th>Osoba</th><th>Funkcja</th><th><span className="sr-only">Akcje</span></th></tr>
            </thead>
            <tbody>
              {loading && <tr><td colSpan={3} style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</td></tr>}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={3} style={{ color: 'var(--color-text-muted)', padding: 12 }}>
                  Brak zastępców — obieg wniosków obsługuje wyłącznie główny kierownik.
                </td></tr>
              )}
              {rows.map(r => (
                <DeputyRow key={r.id} row={r}
                           onEditLabel={onEditLabel}
                           onDelete={onDelete} />
              ))}
            </tbody>
          </table>
          </div>
      </Modal>
    </td>
  )
}

function DeputyRow({ row, onEditLabel, onDelete }) {
  const [label, setLabel] = useState(row.role_label || '')
  const [dirty, setDirty] = useState(false)
  return (
    <tr>
      <td>
        <div style={{ fontWeight: 600 }}>{row.user_name}</div>
        {row.user_username && (
          <div style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--color-text-muted)' }}>
            {row.user_username}
          </div>
        )}
      </td>
      <td>
        <input className="input input--sm"
               aria-label={`Funkcja zastępcy ${row.user_name}`}
               value={label}
               onChange={e => { setLabel(e.target.value); setDirty(true) }}
               placeholder="—" />
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
        {dirty && (
          <button type="button" className="btn btn--action btn--sm"
                  aria-label={`Zapisz funkcję zastępcy ${row.user_name}`} title="Zapisz etykietę"
                  onClick={() => { onEditLabel(row, label.trim() || null); setDirty(false) }}>
            <Save size={14} aria-hidden="true" />
          </button>
        )}
        <button type="button" className="btn btn--danger btn--sm" style={{ marginLeft: 4 }}
                aria-label={`Odbierz uprawnienia zastępcy ${row.user_name}`} title="Odbierz uprawnienia zastępcy"
                onClick={() => onDelete(row)}>
          <Trash2 size={12} aria-hidden="true" />
        </button>
      </td>
    </tr>
  )
}
