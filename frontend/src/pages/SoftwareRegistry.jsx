import { Fragment, useEffect, useState } from 'react'
import {
  Package, Plus, Trash2, RefreshCw, Edit2, Save, X,
  Building2, ShieldCheck, KeyRound, Copy, Truck, FileSpreadsheet, ListPlus,
  ArrowUp, ArrowDown,
} from 'lucide-react'
import {
  listSystems, createSystem, updateSystem, deleteSystem,
  listPermissions, createPermission, updatePermission, deletePermission,
  copySystemPermissions, setSystemDefaultPermissions,
  listActiveUnits, listVendors,
  setPermissionGroupState, renamePermissionGroup, deletePermissionGroup,
  setPermissionGroupOrder, assignPermissionSubgroup,
} from '../api'
import PermissionImportModal from '../components/PermissionImportModal'
import PermissionGroupModal from '../components/PermissionGroupModal'
import CopyGroupModal from '../components/CopyGroupModal'
import { groupPerms, subgroupPerms, subgroupNames } from '../components/ItemFields'

/**
 * Rejestr oprogramowania — osobna zakładka dla IT / admin.
 *
 * Umożliwia:
 *  - dodawanie / edycję / usuwanie systemów IT (oprogramowania),
 *  - oznaczenie systemu jako „dostęp bez dodatkowych uprawnień"
 *    (access_only) — wtedy uprawnień nie definiujemy,
 *  - przypisanie systemu do jednostek organizacyjnych (z opcją
 *    „dostępny we wszystkich jednostkach").
 */
/**
 * Sposób wyboru pojedynczego uprawnienia. „Brak" = zwykły checkbox, czyli to,
 * co dostajemy z importu; pozostałe typy dokładają przy uprawnieniu listę
 * albo pole wypełniane przez wnioskującego kierownika.
 */
const INPUT_TYPES = [
  ['none', 'Zwykły checkbox (bez doprecyzowania)'],
  ['text', 'Checkbox + doprecyzowanie (jedna linia)'],
  ['textarea', 'Checkbox + doprecyzowanie (wiele linii)'],
  ['radio', 'Jeden wariant z listy (opcje widoczne)'],
  ['select', 'Jeden wariant z listy (rozwijana)'],
]
// „multiselect" nie jest już do wyboru przy pojedynczym uprawnieniu — wybór
// WIELU wariantów to po prostu grupa uprawnień (przycisk „Nowa grupa").
// Etykieta zostaje, żeby opisać pozycje sprzed tej zmiany.
const INPUT_TYPE_LABELS = {
  ...Object.fromEntries(INPUT_TYPES),
  multiselect: 'Wielokrotny wybór',
}
// Krótkie etykiety na badge przy pozycji (pełne nazwy z listy są za długie).
const INPUT_BADGE_LABELS = {
  text: 'doprecyzowanie',
  textarea: 'doprecyzowanie',
  radio: 'wybór z listy',
  select: 'wybór z listy',
  multiselect: 'wielokrotny wybór',
}
const INPUT_OPTION_TYPES = ['radio', 'select', 'multiselect']

/** Opcje wpisywane po jednej w wierszu → lista bez pustych i duplikatów. */
function splitOptions(text) {
  const out = []
  for (const line of String(text || '').replace(/\r/g, '').split('\n')) {
    const v = line.trim()
    if (v && !out.includes(v)) out.push(v)
  }
  return out
}


/**
 * Wspólne pola kontrolki uprawnienia (sposób wyboru + opcje + wymagalność).
 * Używane i przy dodawaniu, i przy edycji pozycji — jedna definicja, żeby oba
 * przepływy zachowywały się identycznie.
 */
function PermControlFields({ type, setType, options, setOptions, required, setRequired,
                             prompt = '', setPrompt }) {
  return (
    <>
      <div className="form-group" style={{ margin: 0, minWidth: 190 }}>
        <label className="form-label">Sposób wyboru</label>
        <select className="form-control" value={type} onChange={e => setType(e.target.value)}>
          {INPUT_TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </div>
      {type !== 'none' && (
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start',
                      flexWrap: 'wrap', width: '100%' }}>
          {INPUT_OPTION_TYPES.includes(type) && (
            <div className="form-group" style={{ margin: 0, flex: 1, minWidth: 240 }}>
              <label className="form-label">Opcje do wyboru (jedna w wierszu)</label>
              <textarea className="form-control" style={{ minHeight: 60, fontSize: 13 }}
                        value={options} onChange={e => setOptions(e.target.value)}
                        placeholder={['Odczyt', 'Zapis', 'Administracja'].join('\n')} />
            </div>
          )}
          {/* Podpowiedź pokazywana wnioskującemu po zaznaczeniu uprawnienia. */}
          {setPrompt && (
            <div className="form-group" style={{ margin: 0, flex: 1, minWidth: 220 }}>
              <label className="form-label">Podpowiedź (co wpisać/wybrać)</label>
              <input className="form-control" style={{ fontSize: 13 }}
                     value={prompt} onChange={e => setPrompt(e.target.value)}
                     placeholder={type === 'text' ? 'np. Podaj login AD (jan.kowalski)'
                       : type === 'textarea' ? 'np. Wpisz rejestry/moduły do udostępnienia'
                       : 'np. Wybierz poziom dostępu'} />
            </div>
          )}
          <label style={{ display: 'flex', alignItems: 'center', gap: 6,
                          fontSize: 13, cursor: 'pointer', marginTop: 4 }}>
            <input type="checkbox" checked={required}
                   onChange={e => setRequired(e.target.checked)} />
            Wypełnienie obowiązkowe
          </label>
        </div>
      )}
    </>
  )
}


/** Wiersz uprawnienia: podgląd + edycja w miejscu (nazwa, opis, grupa, kontrolka). */
function PermRow({ p, onChanged, selected = false, onToggleSel }) {
  const [editing, setEditing]   = useState(false)
  const [name, setName]         = useState(p.permission_name)
  const [desc, setDesc]         = useState(p.description || '')
  const [type, setType]         = useState(p.input_type && p.input_type !== 'none' ? p.input_type : 'none')
  const [opts, setOpts]         = useState((p.options || []).join('\n'))
  const [required, setRequired] = useState(!!p.input_required)
  const [group, setGroup]       = useState(p.group_name || '')
  const [subgroup, setSubgroup] = useState(p.subgroup_name || '')
  const [prompt, setPrompt]     = useState(p.input_prompt || '')
  const [busy, setBusy]         = useState(false)

  function cancel() {
    setName(p.permission_name); setDesc(p.description || '')
    setType(p.input_type && p.input_type !== 'none' ? p.input_type : 'none')
    setOpts((p.options || []).join('\n')); setRequired(!!p.input_required)
    setGroup(p.group_name || ''); setSubgroup(p.subgroup_name || '')
    setPrompt(p.input_prompt || ''); setEditing(false)
  }

  async function save() {
    if (!name.trim()) { alert('Podaj nazwę uprawnienia.'); return }
    setBusy(true)
    try {
      await updatePermission(p.id, {
        permission_name: name.trim(),
        description: desc.trim(),
        group_name: group.trim(),
        subgroup_name: subgroup.trim(),
        input_type: type,
        options: INPUT_OPTION_TYPES.includes(type) ? splitOptions(opts) : [],
        input_required: required,
        input_prompt: type !== 'none' ? prompt.trim() : '',
      })
      setEditing(false); onChanged()
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Nie udało się zapisać zmian')
    } finally { setBusy(false) }
  }

  async function del() {
    if (!confirm('Usunąć uprawnienie?')) return
    try { await deletePermission(p.id); onChanged() }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd') }
  }

  if (editing) {
    return (
      <tr>
        <td colSpan={3} style={{ background: 'var(--bg-secondary)' }}>
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap',
                        alignItems: 'flex-end', padding: '6px 2px' }}>
            <div className="form-group" style={{ margin: 0, flex: 1, minWidth: 170 }}>
              <label className="form-label">Nazwa uprawnienia</label>
              <input className="form-control" value={name} autoFocus
                     onChange={e => setName(e.target.value)} />
            </div>
            <div className="form-group" style={{ margin: 0, flex: 1, minWidth: 150 }}>
              <label className="form-label">Opis</label>
              <input className="form-control" value={desc}
                     onChange={e => setDesc(e.target.value)} />
            </div>
            <div className="form-group" style={{ margin: 0, minWidth: 160 }}>
              <label className="form-label">Grupa</label>
              <input className="form-control" list="szup-perm-groups" value={group}
                     onChange={e => setGroup(e.target.value)} placeholder="bez grupy" />
            </div>
            <div className="form-group" style={{ margin: 0, minWidth: 160 }}>
              <label className="form-label">Podgrupa</label>
              <input className="form-control" list="szup-perm-subgroups" value={subgroup}
                     onChange={e => setSubgroup(e.target.value)} placeholder="bez podgrupy" />
            </div>
            <PermControlFields type={type} setType={setType} options={opts} setOptions={setOpts}
                               required={required} setRequired={setRequired}
                               prompt={prompt} setPrompt={setPrompt} />
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="btn btn--primary btn--sm" onClick={save} disabled={busy}>
                <Save size={12} /> Zapisz
              </button>
              <button className="btn btn--ghost btn--sm" onClick={cancel} disabled={busy}>
                Anuluj
              </button>
            </div>
          </div>
        </td>
      </tr>
    )
  }

  return (
    <tr style={{ opacity: p.is_active === false ? 0.5 : 1,
                 background: selected ? 'var(--color-success-bg)' : undefined }}>
      <td style={{ fontWeight: 600 }}>
        {onToggleSel && !p.is_admin_option && (
          <input type="checkbox" checked={selected} onChange={onToggleSel}
                 style={{ width: 17, height: 17, marginRight: 10, verticalAlign: 'middle', accentColor: 'var(--color-navy)' }}
                 aria-label="Zaznacz pozycję" title="Zaznacz do operacji masowej" />
        )}
        <span style={{ fontWeight: 600 }}>{p.permission_name}</span>
        {p.is_active === false && (
          <span className="badge badge--warning" style={{ fontSize: 11, fontWeight: 700, marginLeft: 6 }}>
            wycofane
          </span>
        )}
        {p.input_type && p.input_type !== 'none' && (
          <span className="badge" style={{ fontSize: 11, fontWeight: 700, marginLeft: 6, borderRadius: 4,
                                           background: '#FEF3DC', color: '#8A6D1B' }}
                title={INPUT_TYPE_LABELS[p.input_type] || p.input_type}>
            {INPUT_BADGE_LABELS[p.input_type] || p.input_type}
            {(p.options || []).length > 0 && ` (${p.options.length})`}
            {p.input_required && ' • wymagane'}
          </span>
        )}
      </td>
      <td style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>{p.description || '—'}</td>
      <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
        <button className="btn btn--ghost btn--sm" onClick={() => setEditing(true)} title="Edytuj" aria-label="Edytuj"
                style={{ width: 32, padding: 0, justifyContent: 'center', marginRight: 4 }}>
          <Edit2 size={13} />
        </button>
        <button className="btn btn--ghost btn--sm" onClick={del} title="Usuń" aria-label="Usuń"
                style={{ width: 32, padding: 0, justifyContent: 'center', color: 'var(--color-error-text)', borderColor: 'var(--color-error)' }}>
          <Trash2 size={13} />
        </button>
      </td>
    </tr>
  )
}


/** Inline dodawanie uprawnienia WEWNĄTRZ grupy (albo bez grupy), opcjonalnie
 *  do podgrupy. `subgroup` prefilluje pole podgrupy (przy „dodaj do podgrupy"),
 *  `label` nadpisuje tekst przycisku. */
function GroupAddPerm({ systemId, group, subgroup = '', label, onAdded }) {
  const [open, setOpen]         = useState(false)
  const [name, setName]         = useState('')
  const [desc, setDesc]         = useState('')
  const [sub, setSub]           = useState(subgroup)
  const [type, setType]         = useState('none')
  const [opts, setOpts]         = useState('')
  const [required, setRequired] = useState(false)
  const [prompt, setPrompt]     = useState('')
  const [busy, setBusy]         = useState(false)

  async function submit(e) {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    try {
      await createPermission(systemId, {
        permission_name: name.trim(),
        description: desc.trim() || null,
        group_name: group || null,
        subgroup_name: sub.trim() || null,
        input_type: type,
        options: INPUT_OPTION_TYPES.includes(type) ? splitOptions(opts) : [],
        input_required: required,
        input_prompt: type !== 'none' ? (prompt.trim() || null) : null,
      })
      // Zostawiamy formularz otwarty — po dodaniu jednej pozycji zwykle dokłada
      // się kolejne z tej samej grupy/podgrupy; czyścimy tylko nazwę/opis/opcje.
      setName(''); setDesc(''); setType('none'); setOpts(''); setRequired(false); setPrompt('')
      onAdded()
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Błąd zapisu')
    } finally { setBusy(false) }
  }

  if (!open) {
    return (
      <button className="btn btn--ghost btn--sm" style={{ minHeight: 36, borderStyle: 'dashed' }}
              onClick={() => setOpen(true)}>
        <Plus size={12} /> {label || `Dodaj uprawnienie${group ? ` do „${group}"` : ''}`}
      </button>
    )
  }

  return (
    <form onSubmit={submit} style={{
      width: '100%', padding: 10,
      border: '1px dashed var(--color-input-border)', borderRadius: 8,
      background: 'var(--bg-secondary)',
    }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div className="form-group" style={{ margin: 0, flex: 1, minWidth: 180 }}>
          <label className="form-label">
            Nowe uprawnienie{group ? ` w grupie „${group}"` : ' (bez grupy)'}
          </label>
          <input className="form-control" value={name} autoFocus
                 onChange={e => setName(e.target.value)}
                 placeholder="np. Odczyt, 008 Krakowiaczek…" />
        </div>
        <div className="form-group" style={{ margin: 0, flex: 1, minWidth: 150 }}>
          <label className="form-label">Opis</label>
          <input className="form-control" value={desc} onChange={e => setDesc(e.target.value)} />
        </div>
        <div className="form-group" style={{ margin: 0, minWidth: 150 }}>
          <label className="form-label">Podgrupa (opcjonalnie)</label>
          <input className="form-control" list="szup-perm-subgroups" value={sub}
                 onChange={e => setSub(e.target.value)} placeholder="bez podgrupy" />
        </div>
        <PermControlFields type={type} setType={setType} options={opts} setOptions={setOpts}
                           required={required} setRequired={setRequired}
                           prompt={prompt} setPrompt={setPrompt} />
        <div style={{ display: 'flex', gap: 6 }}>
          <button type="submit" className="btn btn--primary btn--sm" disabled={busy}>
            <Plus size={12} /> Dodaj
          </button>
          <button type="button" className="btn btn--ghost btn--sm"
                  onClick={() => setOpen(false)} disabled={busy}>
            Zamknij
          </button>
        </div>
      </div>
    </form>
  )
}


/** Pasek operacji masowej: przypisz zaznaczone uprawnienia do podgrupy. */
function BulkSubgroupBar({ systemId, selectedIds, onDone }) {
  const [sub, setSub]   = useState('')
  const [busy, setBusy] = useState(false)
  async function apply(clear) {
    setBusy(true)
    try {
      await assignPermissionSubgroup(systemId, selectedIds, clear ? '' : sub.trim())
      setSub(''); onDone()
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Nie udało się przypisać podgrupy')
    } finally { setBusy(false) }
  }
  return (
    <div style={{
      display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap',
      background: 'var(--color-success-bg)', border: '1px solid var(--color-success)',
      borderRadius: 8, padding: '8px 12px', margin: '0 12px 8px',
    }}>
      <strong style={{ fontSize: 13 }}>Zaznaczono: {selectedIds.length}</strong>
      <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>→ przypisz do podgrupy:</span>
      <input className="form-control" list="szup-perm-subgroups"
             style={{ maxWidth: 220, fontSize: 13 }} value={sub}
             onChange={e => setSub(e.target.value)}
             placeholder="nazwa podgrupy"
             onKeyDown={e => { if (e.key === 'Enter' && sub.trim() && !busy) apply(false) }} />
      <button className="btn btn--primary btn--sm" disabled={busy || !sub.trim()}
              onClick={() => apply(false)}>
        <ListPlus size={12} /> Przypisz
      </button>
      <button className="btn btn--ghost btn--sm" disabled={busy}
              onClick={() => apply(true)} title="Wyjmij zaznaczone z podgrupy">
        Wyjmij z podgrupy
      </button>
    </div>
  )
}


/**
 * Nagłówek sekcji w wykazie oprogramowania. Wykaz nie jest już jedną płaską
 * listą — programy grupujemy: osobno dla każdej jednostki oraz osobno
 * „ogólnodostępne" (dostępne we wszystkich jednostkach).
 */
function SoftwareGroup({ title, subtitle, count, tone = 'unit', children }) {
  const color = tone === 'general' ? 'var(--color-navy)'
    : tone === 'orphan' ? 'var(--color-error)'
    : 'var(--color-text)'
  const Icon = tone === 'unit' ? Building2 : Package
  return (
    <div>
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: 10,
        margin: '4px 0 10px', flexWrap: 'wrap',
      }}>
        <Icon size={15} aria-hidden="true" style={{ color, alignSelf: 'center' }} />
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 800, color }}>{title}</h2>
        <span className="badge badge--neutral" style={{ fontSize: 12, fontWeight: 800 }}>{count}</span>
        {subtitle && (
          <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>{subtitle}</span>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {children}
      </div>
    </div>
  )
}

export default function SoftwareRegistry() {
  const [systems, setSystems] = useState([])
  const [units,   setUnits]   = useState([])
  const [vendors, setVendors] = useState([])
  const [loading, setLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)
  const [filterUnit, setFilterUnit] = useState('')   // '' = wszystkie jednostki
  const [onlyUnconfigured, setOnlyUnconfigured] = useState(false)
  const [onlyNoVendor, setOnlyNoVendor] = useState(false)
  const [selected, setSelected] = useState(() => new Set())   // id zaznaczonych
  const [bulkSource, setBulkSource] = useState('')            // źródło do kopiowania
  const [bulkVendor, setBulkVendor] = useState('')            // dostawca do przypisania
  const [bulkBusy, setBulkBusy] = useState(false)

  // Filtrujemy WIDOK, a nie pobrane dane — dzięki temu lista źródeł do
  // kopiowania uprawnień nadal obejmuje wszystkie programy.
  // Program „dostępny we wszystkich jednostkach" pasuje do każdej jednostki.
  const matchesUnit = s =>
    !filterUnit || s.all_units || (s.unit_ids || []).includes(Number(filterUnit))

  // Program NIESKONFIGUROWANY: ani „tylko dostęp", ani żadnego uprawnienia —
  // nie da się o niego złożyć sensownego wniosku.
  const unconfigured = s => !s.access_only && !(s.permission_count > 0)

  const unconfiguredCount = systems.filter(unconfigured).length
  const noVendorCount = systems.filter(s => !s.vendor_id).length
  const visibleSystems = systems.filter(
    s => matchesUnit(s)
      && (!onlyUnconfigured || unconfigured(s))
      && (!onlyNoVendor || !s.vendor_id)
  )

  // Widok pogrupowany: NIE pokazujemy jednej płaskiej listy wszystkich
  // programów. Każda jednostka dostaje własną sekcję (programy do niej
  // przypisane), a programy „dostępne we wszystkich jednostkach" trafiają do
  // osobnej sekcji „Ogólnodostępne". Sieroty (bez jednostki i bez flagi
  // all_units) pokazujemy osobno, żeby nie zniknęły z zarządzania.
  const passExtra = s =>
    (!onlyUnconfigured || unconfigured(s)) && (!onlyNoVendor || !s.vendor_id)
  // Nieaktywne oprogramowanie ląduje na dole listy (sort stabilny — reszta
  // zachowuje dotychczasową kolejność).
  const byActive = arr =>
    [...arr].sort((a, b) => (a.is_active === false ? 1 : 0) - (b.is_active === false ? 1 : 0))
  const unitSections = units
    .filter(u => !filterUnit || u.id === Number(filterUnit))
    .map(u => ({
      unit: u,
      items: byActive(systems.filter(
        s => !s.all_units && (s.unit_ids || []).includes(u.id) && passExtra(s))),
    }))
    .filter(g => g.items.length > 0)
  const generalSystems = byActive(systems.filter(s => s.all_units && passExtra(s)))
  const orphanSystems = filterUnit
    ? []
    : byActive(systems.filter(
        s => !s.all_units && (s.unit_ids || []).length === 0 && passExtra(s)))

  async function load() {
    setLoading(true)
    try {
      const [rSys, rUnits, rVend] = await Promise.all([
        listSystems(), listActiveUnits(),
        listVendors().catch(() => ({ data: [] })),
      ])
      setSystems(rSys.data)
      setUnits(rUnits.data)
      setVendors(rVend.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  // --- zaznaczanie i operacje zbiorcze -------------------------------------

  function toggleSel(id) {
    setSelected(prev => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }
  // „Zaznacz wszystkie" działa na WIDOCZNYCH (po filtrze) programach.
  const allVisibleSelected = visibleSystems.length > 0
    && visibleSystems.every(s => selected.has(s.id))
  function toggleSelectAll() {
    setSelected(prev => {
      const n = new Set(prev)
      if (allVisibleSelected) visibleSystems.forEach(s => n.delete(s.id))
      else visibleSystems.forEach(s => n.add(s.id))
      return n
    })
  }

  // Kandydaci na źródło kopiowania: programy z gotową listą uprawnień.
  const bulkSources = systems.filter(x => !x.access_only && x.permission_count > 0)

  /**
   * Wykonaj operację na wszystkich zaznaczonych. Idziemy po jednym, żeby
   * błąd jednego programu (np. uprawnienia użyte we wnioskach) nie przerwał
   * całej reszty — zbieramy wynik i pokazujemy podsumowanie.
   */
  async function runBulk(label, fn, warning =
    'Obecna definicja uprawnień tych programów zostanie zastąpiona.') {
    const targets = systems.filter(s => selected.has(s.id))
    if (targets.length === 0) return
    if (!confirm(
      `${label} dla ${targets.length} zaznaczonych programów?\n\n${warning}`
    )) return

    setBulkBusy(true)
    const ok = [], failed = []
    for (const s of targets) {
      try {
        await fn(s)
        ok.push(s.name)
      } catch (ex) {
        failed.push(`${s.name}: ${ex.response?.data?.detail || 'błąd'}`)
      }
    }
    setBulkBusy(false)
    setSelected(new Set())
    await load()

    alert(
      `Zmieniono: ${ok.length}` + (ok.length ? `\n  • ${ok.join('\n  • ')}` : '') +
      (failed.length
        ? `\n\nPominięto: ${failed.length}\n  • ${failed.join('\n  • ')}`
        : '')
    )
  }

  const bulkDefault = () =>
    runBulk('Ustawić domyślną definicję uprawnień',
            s => setSystemDefaultPermissions(s.id))

  const bulkAccessOnly = () =>
    runBulk('Ustawić tryb „dostęp bez dodatkowych uprawnień"',
            s => updateSystem(s.id, { access_only: true }))

  const bulkRequireScope = (on) =>
    runBulk(
      on ? 'Włączyć wymóg wyboru zakresu uprawnień' : 'Wyłączyć wymóg wyboru zakresu uprawnień',
      s => updateSystem(s.id, { require_scope: on }),
      on
        ? 'Na wniosku te programy będą domyślnie wyszarzone — trzeba zaznaczyć program '
          + 'i wybrać co najmniej jedno uprawnienie. Uprawnienia bez zmian.'
        : 'Programy nie będą już wymuszać wyboru zakresu. Uprawnienia bez zmian.',
    )

  /**
   * Masowe przypisanie producenta. Wartość „0" oznacza „usuń przypisanie" —
   * pusty `select` znaczy „nie wybrano" i przycisk jest wtedy nieaktywny,
   * więc te dwa stany trzeba rozróżnić.
   */
  const bulkAssignVendor = () => {
    if (bulkVendor === '') return
    const vid = Number(bulkVendor) || null
    const v = vendors.find(x => x.id === vid)
    runBulk(
      vid ? `Przypisać dostawcę „${v?.name}"` : 'Usunąć przypisanie dostawcy',
      s => updateSystem(s.id, { vendor_id: vid }),
      vid
        ? 'Dotychczasowy dostawca tych programów zostanie zastąpiony. ' +
          'Uprawnienia pozostaną bez zmian.'
        : 'Programy zostaną odpięte od dostawcy. Uprawnienia bez zmian.',
    )
  }

  const bulkCopy = () => {
    const src = systems.find(x => x.id === Number(bulkSource))
    if (!src) return
    runBulk(`Skopiować uprawnienia z „${src.name}"`,
            s => s.id === src.id
              ? Promise.resolve()          // nie kopiuj programu w samego siebie
              : copySystemPermissions(s.id, src.id))
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Oprogramowanie</div>
          <div className="page-header__sub">
            Systemy IT, ich uprawnienia i dostępność dla jednostek organizacyjnych
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="btn btn--ghost" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
          <button className="btn btn--action" onClick={() => setShowAdd(v => !v)}>
            <Plus size={14} /> Dodaj oprogramowanie
          </button>
        </div>
      </div>

      {/* Filtry (v3.0: osobny rząd pod nagłówkiem, wg projektu) */}
      <section aria-label="Filtry" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 14, marginBottom: 16 }}>
          <select
            className="form-control"
            aria-label="Jednostka"
            style={{ width: 'auto', maxWidth: 300, minHeight: 44 }}
            value={filterUnit}
            onChange={e => setFilterUnit(e.target.value)}
            title="Pokaż oprogramowanie dostępne w wybranej jednostce"
          >
            <option value="">Wszystkie jednostki (pogrupowane)</option>
            {units.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
          <label style={{
            display: 'inline-flex', alignItems: 'center', gap: 8, minHeight: 44, fontSize: 14,
            cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
          }} title="Programy bez trybu „tylko dostęp”, bez pól wnioskodawcy i bez listy uprawnień">
            <input type="checkbox" checked={onlyUnconfigured} style={{ width: 18, height: 18, accentColor: 'var(--color-navy)' }}
                   onChange={e => setOnlyUnconfigured(e.target.checked)} />
            Bez uprawnień
            {unconfiguredCount > 0 && (
              <span className="badge badge--warning" style={{ fontSize: 12, fontWeight: 800 }}>
                {unconfiguredCount}
              </span>
            )}
          </label>
          <label style={{
            display: 'inline-flex', alignItems: 'center', gap: 8, minHeight: 44, fontSize: 14,
            cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap',
          }} title="Programy bez przypisanego producenta — zaznacz je i przypisz zbiorczo">
            <input type="checkbox" checked={onlyNoVendor} style={{ width: 18, height: 18, accentColor: 'var(--color-navy)' }}
                   onChange={e => setOnlyNoVendor(e.target.checked)} />
            Bez dostawcy
            {noVendorCount > 0 && (
              <span className="badge badge--neutral" style={{ fontSize: 12, fontWeight: 800 }}>
                {noVendorCount}
              </span>
            )}
          </label>
          {!(filterUnit || onlyUnconfigured || onlyNoVendor) && !loading && (
            <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              Pokazano {visibleSystems.length} z {systems.length}
            </span>
          )}
      </section>

      {(filterUnit || onlyUnconfigured || onlyNoVendor) && !loading && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 12, flexWrap: 'wrap',
        }}>
          <Building2 size={13} />
          <span>
            Pokazano {visibleSystems.length} z {systems.length}
            {filterUnit && (
              <> · jednostka <strong>{units.find(u => u.id === Number(filterUnit))?.name}</strong>
              {' '}(z programami dostępnymi we wszystkich jednostkach)</>
            )}
            {onlyUnconfigured && <> · tylko <strong>bez ustawionych uprawnień</strong></>}
            {onlyNoVendor && <> · tylko <strong>bez dostawcy</strong></>}
          </span>
          <button className="btn btn--ghost btn--sm"
                  onClick={() => {
                    setFilterUnit(''); setOnlyUnconfigured(false); setOnlyNoVendor(false)
                  }}>
            <X size={12} /> Wyczyść filtry
          </button>
        </div>
      )}

      {showAdd && (
        <AddSystemForm
          units={units}
          vendors={vendors}
          allSystems={systems}
          onCancel={() => setShowAdd(false)}
          onSaved={() => { setShowAdd(false); load() }}
        />
      )}

      {/* Pasek zaznaczania / operacji zbiorczych */}
      {!loading && visibleSystems.length > 0 && (
        <section className="card" aria-label="Akcje zbiorcze" style={{
          padding: '12px 16px', marginBottom: 16,
          display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', fontSize: 14,
          borderColor: selected.size > 0 ? 'var(--color-navy)' : undefined,
        }}>
          <label style={{
            display: 'inline-flex', alignItems: 'center', gap: 8, minHeight: 40,
            fontSize: 14, cursor: 'pointer', userSelect: 'none',
          }}>
            <input type="checkbox" checked={allVisibleSelected} onChange={toggleSelectAll}
                   style={{ width: 18, height: 18, accentColor: 'var(--color-navy)' }} />
            {selected.size > 0
              ? <strong>Zaznaczono: {selected.size}</strong>
              : <span style={{ color: 'var(--color-text-muted)' }}>Zaznacz wszystkie</span>}
          </label>

          {selected.size > 0 && (
            <>
              <button className="btn btn--primary btn--sm"
                      onClick={bulkDefault} disabled={bulkBusy}>
                <ShieldCheck size={13} /> {bulkBusy ? 'Ustawianie…' : 'Ustaw domyślne'}
              </button>

              <button className="btn btn--ghost btn--sm"
                      onClick={bulkAccessOnly} disabled={bulkBusy}
                      title="Wniosek będzie zawierał tylko pozycję „Dostęp” — bez pól i bez listy uprawnień">
                <KeyRound size={13} /> Tylko dostęp
              </button>

              <button className="btn btn--ghost btn--sm"
                      onClick={() => bulkRequireScope(true)} disabled={bulkBusy}
                      title="Na wniosku trzeba będzie zaznaczyć program i wybrać co najmniej jedno uprawnienie">
                <ShieldCheck size={13} /> Wymagaj zakresu
              </button>
              <button className="btn btn--ghost btn--sm"
                      onClick={() => bulkRequireScope(false)} disabled={bulkBusy}
                      title="Zdejmij wymóg wyboru zakresu">
                <X size={13} /> Bez wymogu
              </button>

              <span style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>albo</span>

              <select className="form-control" style={{ maxWidth: 300, fontSize: 13 }}
                      value={bulkSource} onChange={e => setBulkSource(e.target.value)}
                      disabled={bulkBusy}>
                <option value="">— skopiuj uprawnienia z… —</option>
                {bulkSources.map(x => (
                  <option key={x.id} value={x.id}>
                    {x.name} ({x.permission_count} uprawnień)
                  </option>
                ))}
              </select>
              <button className="btn btn--ghost btn--sm"
                      onClick={bulkCopy} disabled={bulkBusy || !bulkSource}>
                <Copy size={13} /> Skopiuj
              </button>

              <span style={{ flexBasis: '100%', height: 0 }} />

              <span style={{ fontWeight: 600, fontSize: 14 }}>
                Producent:
              </span>
              <select className="form-control" style={{ maxWidth: 300, fontSize: 13 }}
                      value={bulkVendor} onChange={e => setBulkVendor(e.target.value)}
                      disabled={bulkBusy}>
                <option value="">— przypisz dostawcę… —</option>
                {vendors.map(v => (
                  <option key={v.id} value={v.id}>
                    {v.name}{v.city ? ` (${v.city})` : ''}
                  </option>
                ))}
                <option value="0">— usuń przypisanie —</option>
              </select>
              <button className="btn btn--ghost btn--sm"
                      onClick={bulkAssignVendor}
                      disabled={bulkBusy || bulkVendor === ''}>
                <Truck size={13} /> Przypisz
              </button>

              <button className="btn btn--sm"
                      style={{ background: 'transparent', border: 0, color: 'var(--color-navy)', textDecoration: 'underline', fontWeight: 600 }}
                      onClick={() => setSelected(new Set())} disabled={bulkBusy}>
                Odznacz
              </button>
            </>
          )}
        </section>
      )}

      {loading ? (
        <div className="card" style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>
      ) : systems.length === 0 ? (
        <div className="card" style={{ color: 'var(--color-text-muted)', padding: 16 }}>
          <Package size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          Brak zarejestrowanego oprogramowania.
        </div>
      ) : visibleSystems.length === 0 ? (
        <div className="card" style={{ color: 'var(--color-text-muted)', padding: 16 }}>
          <Package size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          {onlyUnconfigured
            ? 'Wszystkie programy mają już ustawione uprawnienia.'
            : 'Żadne oprogramowanie nie jest przypisane do tej jednostki.'}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {/* Ogólnodostępne — na samej górze (domyślnie). */}
          {generalSystems.length > 0 && (
            <SoftwareGroup title="Ogólnodostępne" tone="general" count={generalSystems.length}
                           subtitle="dostępne we wszystkich jednostkach">
              {generalSystems.map(s => (
                <SystemRow key={s.id} system={s} units={units} vendors={vendors} allSystems={systems}
                           selected={selected.has(s.id)} onToggleSelect={() => toggleSel(s.id)}
                           onReload={load} />
              ))}
            </SoftwareGroup>
          )}

          {orphanSystems.length > 0 && (
            <SoftwareGroup title="Bez przypisania do jednostki" tone="orphan"
                           count={orphanSystems.length}
                           subtitle="nieprzypisane — ustaw jednostkę lub „wszystkie jednostki” w edycji">
              {orphanSystems.map(s => (
                <SystemRow key={s.id} system={s} units={units} vendors={vendors} allSystems={systems}
                           selected={selected.has(s.id)} onToggleSelect={() => toggleSel(s.id)}
                           onReload={load} />
              ))}
            </SoftwareGroup>
          )}

          {/* Jednostki (pogrupowane) — na samym dole. */}
          {unitSections.map(({ unit, items }) => (
            <SoftwareGroup key={`u${unit.id}`} title={unit.name} count={items.length}>
              {items.map(s => (
                <SystemRow key={s.id} system={s} units={units} vendors={vendors} allSystems={systems}
                           selected={selected.has(s.id)} onToggleSelect={() => toggleSel(s.id)}
                           onReload={load} />
              ))}
            </SoftwareGroup>
          ))}
        </div>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Formularz „Dodaj oprogramowanie"
// ---------------------------------------------------------------------------
function AddSystemForm({ units, vendors = [], allSystems = [], onCancel, onSaved }) {
  const [name, setName]         = useState('')
  const [desc, setDesc]         = useState('')
  const [accessOnly, setAO]     = useState(false)
  const [allUnits,   setAU]     = useState(true)
  const [unitIds,    setUnitIds]= useState([])
  const [displayOrder, setDisplayOrder] = useState('')
  const [defaultChecked, setDefaultChecked] = useState(false)
  const [adminOption, setAdminOption] = useState(true)
  // Domyślnie WŁĄCZONE dla programów z listą uprawnień (poza „tylko dostęp") —
  // standardem jest świadomy wybór zakresu.
  const [requireScope, setRequireScope] = useState(true)
  const [vendorId, setVendorId] = useState('')
  const [copyFrom, setCopyFrom] = useState('')
  const [err, setErr]           = useState(null)
  const [saving, setSaving]     = useState(false)

  // Programy, z których można przejąć gotową listę uprawnień.
  const copySources = allSystems.filter(x => !x.access_only && x.permission_count > 0)

  function toggleUnit(id) {
    setUnitIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  async function submit(e) {
    e.preventDefault(); setErr(null); setSaving(true)
    try {
      const r = await createSystem({
        name: name.trim(),
        description: desc.trim() || null,
        access_only: accessOnly,
        all_units: allUnits,
        unit_ids: allUnits ? [] : unitIds,
        display_order: displayOrder === '' ? null : Number(displayOrder),
        default_checked: defaultChecked,
        admin_option: adminOption,
        require_scope: requireScope,
        vendor_id: vendorId ? Number(vendorId) : null,
      })
      if (copyFrom && r.data?.id) {
        await copySystemPermissions(r.data.id, Number(copyFrom))
      }
      onSaved()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd zapisu')
    } finally { setSaving(false) }
  }

  return (
    <div className="card mb-4" style={{ border: '2px solid var(--color-navy)' }}>
      <form onSubmit={submit}>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Nazwa oprogramowania *</label>
            <input className="form-control" required value={name}
                   onChange={e => setName(e.target.value)} autoFocus />
          </div>
          <div className="form-group">
            <label className="form-label">Opis</label>
            <input className="form-control" value={desc}
                   onChange={e => setDesc(e.target.value)} />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" checked={accessOnly}
                     onChange={e => setAO(e.target.checked)} />
              <KeyRound size={14} /> Dostęp bez dodatkowych uprawnień
            </label>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
              Wniosek będzie zawierał tylko pozycję „Dostęp" — bez definiowania
              szczegółowych uprawnień.
            </div>
          </div>
          <div className="form-group">
            <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input type="checkbox" checked={allUnits}
                     onChange={e => setAU(e.target.checked)} />
              <Building2 size={14} /> Dostępne we wszystkich jednostkach
            </label>
          </div>
        </div>

        {!allUnits && (
          <div className="form-group">
            <label className="form-label">Wybierz jednostki</label>
            <UnitsPicker units={units} selected={unitIds} onToggle={toggleUnit} />
          </div>
        )}

        <VendorField vendors={vendors} value={vendorId} onChange={setVendorId} />

        <RequestListingFields
          order={displayOrder} onOrder={setDisplayOrder}
          checked={defaultChecked} onChecked={setDefaultChecked}
        />

        <AdminOptionField checked={adminOption} onChecked={setAdminOption} />

        {!accessOnly && (
          <ScopeRequiredField checked={requireScope} onChecked={setRequireScope} />
        )}

        {copySources.length > 0 && (
          <div className="form-group">
            <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Copy size={13} /> Kopiuj uprawnienia z innego oprogramowania
            </label>
            <select className="form-control" style={{ maxWidth: 420 }}
                    value={copyFrom} onChange={e => setCopyFrom(e.target.value)}>
              <option value="">— nie kopiuj —</option>
              {copySources.map(x => (
                <option key={x.id} value={x.id}>
                  {x.name} ({x.permission_count} uprawnień)
                </option>
              ))}
            </select>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              Uprawnienia zostaną skopiowane po zapisaniu — razem z listami
              wyboru i polami, jeśli źródło je ma.
            </div>
          </div>
        )}

        {err && <div className="alert alert--error mb-4">{err}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel}>
            <X size={13} /> Anuluj
          </button>
          <button type="submit" className="btn btn--primary btn--sm" disabled={saving}>
            <Save size={13} /> Zapisz
          </button>
        </div>
      </form>
    </div>
  )
}


/**
 * Wspólny fragment obu formularzy programu: pozycja na wniosku + domyślne
 * zaznaczenie. Wydzielony, żeby „Dodaj" i „Edytuj" nie rozjechały się z czasem
 * (tak jak rozjechały się pickery uprawnień w Manager/MyTeam).
 */
/**
 * Wybór dostawcy ze słownika — wspólny dla „Dodaj" i „Edytuj", z tego samego
 * powodu co RequestListingFields poniżej (żeby oba formularze się nie rozjechały).
 */
function VendorField({ vendors, value, onChange }) {
  return (
    <div className="form-group">
      <label className="form-label">Dostawca / producent</label>
      <select className="form-control" style={{ maxWidth: 420 }}
              value={value} onChange={e => onChange(e.target.value)}>
        <option value="">— nie przypisano —</option>
        {vendors.map(v => (
          <option key={v.id} value={v.id}>
            {v.name}{v.city ? ` (${v.city})` : ''}
          </option>
        ))}
      </select>
      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
        {vendors.length === 0
          ? 'Słownik dostawców jest pusty — dodaj dostawcę w zakładce „Dostawcy oprogramowania".'
          : 'Lista pochodzi ze słownika „Dostawcy oprogramowania".'}
      </div>
    </div>
  )
}


/**
 * „Super uprawnienia" — pozycja utrzymywana przez system przy każdym programie
 * (backend dopisuje/usuwa syntetyczne uprawnienie). Domyślnie włączona, bo
 * praktycznie każdy system ma konto administracyjne; odznaczamy tam, gdzie
 * takiego poziomu nie ma w ogóle.
 */
function AdminOptionField({ checked, onChecked }) {
  return (
    <div className="form-group">
      <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input type="checkbox" checked={checked}
               onChange={e => onChecked(e.target.checked)} />
        <ShieldCheck size={14} /> Można wnioskować o uprawnienia administratora
      </label>
      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
        Dodaje na wniosku osobną pozycję „Uprawnienia administratora" —
        niezależnie od pozostałych uprawnień i pól. Odznacz, jeśli ten program
        nie ma poziomu administracyjnego.
      </div>
    </div>
  )
}


function ScopeRequiredField({ checked, onChecked }) {
  return (
    <div className="form-group">
      <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input type="checkbox" checked={checked}
               onChange={e => onChecked(e.target.checked)} />
        <ShieldCheck size={14} /> Wymagaj wyboru zakresu uprawnień
      </label>
      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
        Na wniosku ten program jest domyślnie <strong>wyszarzony</strong> —
        trzeba najpierw zaznaczyć sam program, a po zaznaczeniu wybrać
        <strong> co najmniej jedno uprawnienie</strong> (zakres). Dotyczy programów
        z listą poduprawnień; dla „tylko dostęp" nie ma znaczenia.
      </div>
    </div>
  )
}


function RequestListingFields({ order, onOrder, checked, onChecked }) {
  return (
    <div className="form-row">
      <div className="form-group">
        <label className="form-label">Nr na wniosku</label>
        <input className="form-control" type="number" min={1} step={1}
               style={{ maxWidth: 140 }}
               value={order} onChange={e => onOrder(e.target.value)}
               placeholder="np. 1" />
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
          Puste — program pokaże się alfabetycznie, za ponumerowanymi.
        </div>
      </div>
      <div className="form-group">
        <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={checked}
                 onChange={e => onChecked(e.target.checked)} />
          <ShieldCheck size={14} /> Domyślnie zaznaczone na wniosku
        </label>
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
          Pozycja będzie zaznaczona z góry; wnioskodawca może ją odznaczyć.
          Pola wymagane (np. zakres) i tak trzeba uzupełnić.
        </div>
      </div>
    </div>
  )
}


function UnitsPicker({ units, selected, onToggle }) {
  if (units.length === 0) {
    return (
      <div style={{ color: 'var(--color-text-muted)', fontSize: 12, padding: 8 }}>
        Brak zdefiniowanych jednostek.
      </div>
    )
  }
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))',
      gap: 6, maxHeight: 220, overflowY: 'auto',
      border: '1px solid var(--color-border)', borderRadius: 6, padding: 8,
    }}>
      {units.map(u => (
        <label key={u.id} style={{
          display: 'flex', alignItems: 'center', gap: 6, cursor: 'pointer',
          padding: '4px 6px', fontSize: 13,
        }}>
          <input type="checkbox" checked={selected.includes(u.id)}
                 onChange={() => onToggle(u.id)} />
          <span>{u.name}</span>
          {u.code && (
            <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
              ({u.code})
            </span>
          )}
        </label>
      ))}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Edytor pól własnych — dowolne metadane oprogramowania
// (nazwa pola + opis/definicja co wpisać + wartość).
// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// Karta systemu — z inline edycją i zarządzaniem uprawnieniami
// ---------------------------------------------------------------------------
function SystemRow({ system: s, units, vendors = [], allSystems = [], selected = false,
                     onToggleSelect, onReload }) {
  const [editing, setEditing] = useState(false)
  const [open, setOpen]       = useState(false)
  const [settingDefault, setSettingDefault] = useState(false)

  // „Ustaw domyślne" ma sens tylko tam, gdzie definicji jeszcze nie ma —
  // programy wprowadzone bez poziomów uprawnień. Przy istniejącej liście
  // uprawnień backend i tak by odmówił (ochrona historii wniosków).
  const canSetDefault = !s.access_only && !(s.permission_count > 0)

  async function applyDefault() {
    if (!confirm(
      `Ustawić domyślną definicję uprawnień dla „${s.name}"?\n\n` +
      'Wnioskodawca (kierownik) będzie wpisywał „Zakres uprawnień" — ' +
      'pole opisowe, obowiązkowe.'
    )) return
    setSettingDefault(true)
    try {
      const r = await setSystemDefaultPermissions(s.id)
      alert('Ustawiono domyślną definicję uprawnień.\n\n'
            + (r.data.details || []).join('\n'))
      onReload()
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Nie udało się ustawić')
    } finally { setSettingDefault(false) }
  }

  const unitNames = (s.unit_ids || [])
    .map(id => units.find(u => u.id === id)?.name)
    .filter(Boolean)

  async function toggleActive() {
    await updateSystem(s.id, { is_active: !s.is_active })
    onReload()
  }

  async function del() {
    if (!confirm(`Usunąć oprogramowanie „${s.name}"?`)) return
    try {
      await deleteSystem(s.id)
      onReload()
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Nie można usunąć')
    }
  }

  return (
    <section className="card" aria-label={s.name} style={{
      padding: 0, overflow: 'hidden',
      // v3.0: zaznaczenie — granatowa ramka (bez lewego paska).
      borderColor: selected ? 'var(--color-navy)' : undefined,
      // Nieaktywne oprogramowanie — lekko wyszarzone (ląduje też na dole listy).
      opacity: s.is_active === false ? 0.55 : 1,
    }}>
      <div style={{
        display: 'flex', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12,
        padding: '14px 16px',
      }}>
        <input type="checkbox" checked={selected} onChange={onToggleSelect}
               title="Zaznacz do operacji zbiorczej" aria-label={`Zaznacz ${s.name}`}
               style={{ width: 18, height: 18, marginTop: 8, flexShrink: 0, cursor: 'pointer', accentColor: 'var(--color-navy)' }} />
        <span aria-hidden="true" style={{
          width: 34, height: 34, borderRadius: 8, flexShrink: 0, background: 'var(--bg-secondary)',
          color: 'var(--color-navy)', display: 'grid', placeItems: 'center',
        }}>
          <Package size={17} />
        </span>
        <div style={{ flex: '1 1 320px', minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <strong style={{ fontSize: 15, color: 'var(--color-navy)' }}>{s.name}</strong>
            {/* Pozycja na wniosku — widoczna bez wchodzenia w edycję. */}
            {s.display_order != null && (
              <span className="badge badge--neutral"
                    style={{ fontSize: 11, borderRadius: 4, fontFamily: 'var(--font-mono)' }}
                    title="Pozycja na liście wniosku">
                #{s.display_order}
              </span>
            )}
            {s.default_checked && (
              <span className="badge badge--warning" style={{ fontSize: 11, fontWeight: 700 }}
                    title="Zaznaczone z góry na każdym wniosku">
                domyślne
              </span>
            )}
            {s.vendor_name && (
              <span className="badge badge--info" style={{ fontSize: 11, fontWeight: 700 }}
                    title="Dostawca ze słownika">
                {s.vendor_name}
              </span>
            )}
            {!s.is_active && (
              <span className="badge badge--neutral" style={{ fontSize: 11, fontWeight: 700 }}>nieaktywny</span>
            )}
            {s.access_only && (
              <span className="badge badge--info" style={{ fontSize: 11, fontWeight: 700 }}>
                <KeyRound size={10} style={{ verticalAlign: 'middle' }} /> tylko dostęp
              </span>
            )}
            {s.all_units ? (
              <span className="badge badge--success" style={{ fontSize: 11, fontWeight: 700 }}>
                <Building2 size={10} style={{ verticalAlign: 'middle' }} /> wszystkie jednostki
              </span>
            ) : (
              <span className="badge badge--warning" style={{ fontSize: 11, fontWeight: 700 }}>
                <Building2 size={10} style={{ verticalAlign: 'middle' }} /> {unitNames.length} jednostek
              </span>
            )}
          </div>
          {s.description && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 13, marginTop: 4 }}>
              {s.description}
            </div>
          )}
          {!s.all_units && unitNames.length > 0 && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 13, marginTop: 4 }}>
              Jednostki: {unitNames.join(', ')}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <button className="btn btn--ghost btn--sm" onClick={() => setOpen(o => !o)} aria-expanded={open}
                  style={open ? { minHeight: 36, borderColor: 'var(--color-navy)', background: 'var(--color-warning-bg)', fontWeight: 700 } : { minHeight: 36 }}>
            {open ? '▲' : '▼'} {s.access_only ? 'Szczegóły' : 'Uprawnienia'}
          </button>
          <button className="btn btn--ghost btn--sm" onClick={() => setEditing(e => !e)}>
            <Edit2 size={12} /> Edytuj
          </button>
          {canSetDefault && (
            <button className="btn btn--ghost btn--sm"
                    onClick={applyDefault} disabled={settingDefault}
                    title="Ustaw domyślną definicję: „Zakres uprawnień” (pole opisowe, obowiązkowe)">
              <ShieldCheck size={12} /> {settingDefault ? 'Ustawianie…' : 'Ustaw domyślne'}
            </button>
          )}
          <button className="btn btn--ghost btn--sm" onClick={toggleActive}>
            {s.is_active ? 'Dezaktywuj' : 'Aktywuj'}
          </button>
          <button className="btn btn--ghost btn--sm" onClick={del} aria-label="Usuń" title="Usuń"
                  style={{ minHeight: 36, width: 36, padding: 0, justifyContent: 'center',
                           color: 'var(--color-error-text)', borderColor: 'var(--color-error)' }}>
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {editing && (
        <div style={{ padding: '0 16px 16px' }}>
          <EditSystemForm
            system={s}
            units={units}
            vendors={vendors}
            onCancel={() => setEditing(false)}
            onSaved={() => { setEditing(false); onReload() }}
          />
        </div>
      )}

      {open && (
        <div style={{ padding: '14px 16px', borderTop: '1px solid var(--color-border)', background: 'var(--color-table-head)' }}>
          <PermissionsPanel system={s} />
        </div>
      )}
    </section>
  )
}


function EditSystemForm({ system: s, units, vendors = [], onCancel, onSaved }) {
  const [name, setName]     = useState(s.name)
  const [desc, setDesc]     = useState(s.description || '')
  const [accessOnly, setAO] = useState(!!s.access_only)
  const [allUnits, setAU]   = useState(!!s.all_units)
  const [unitIds, setUnitIds] = useState(s.unit_ids || [])
  const [displayOrder, setDisplayOrder] = useState(
    s.display_order == null ? '' : String(s.display_order)
  )
  const [defaultChecked, setDefaultChecked] = useState(!!s.default_checked)
  const [adminOption, setAdminOption] = useState(s.admin_option !== false)
  const [requireScope, setRequireScope] = useState(!!s.require_scope)
  const [vendorId, setVendorId] = useState(s.vendor_id == null ? '' : String(s.vendor_id))
  const [err, setErr]       = useState(null)
  const [saving, setSaving] = useState(false)

  function toggleUnit(id) {
    setUnitIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  async function submit(e) {
    e.preventDefault(); setErr(null); setSaving(true)
    try {
      const payload = {
        name: name.trim(),
        description: desc.trim() || null,
        access_only: accessOnly,
        all_units: allUnits,
        display_order: displayOrder === '' ? null : Number(displayOrder),
        default_checked: defaultChecked,
        admin_option: adminOption,
        require_scope: requireScope,
        vendor_id: vendorId ? Number(vendorId) : null,
      }
      if (!allUnits) payload.unit_ids = unitIds
      await updateSystem(s.id, payload)
      onSaved()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd zapisu')
    } finally { setSaving(false) }
  }

  return (
    <form onSubmit={submit} style={{
      background: 'var(--color-bg-subtle)', padding: 12, borderRadius: 6,
      marginTop: 8,
    }}>
      <div className="form-row">
        <div className="form-group">
          <label className="form-label">Nazwa *</label>
          <input className="form-control" required value={name}
                 onChange={e => setName(e.target.value)} />
        </div>
        <div className="form-group">
          <label className="form-label">Opis</label>
          <input className="form-control" value={desc}
                 onChange={e => setDesc(e.target.value)} />
        </div>
      </div>
      <div className="form-row">
        <div className="form-group">
          <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input type="checkbox" checked={accessOnly}
                   onChange={e => setAO(e.target.checked)} />
            <KeyRound size={14} /> Dostęp bez dodatkowych uprawnień
          </label>
        </div>
        <div className="form-group">
          <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input type="checkbox" checked={allUnits}
                   onChange={e => setAU(e.target.checked)} />
            <Building2 size={14} /> Dostępne we wszystkich jednostkach
          </label>
        </div>
      </div>
      {!allUnits && (
        <div className="form-group">
          <label className="form-label">Wybierz jednostki</label>
          <UnitsPicker units={units} selected={unitIds} onToggle={toggleUnit} />
        </div>
      )}
      <VendorField vendors={vendors} value={vendorId} onChange={setVendorId} />
      <RequestListingFields
        order={displayOrder} onOrder={setDisplayOrder}
        checked={defaultChecked} onChecked={setDefaultChecked}
      />
      <AdminOptionField checked={adminOption} onChecked={setAdminOption} />
      {!accessOnly && (
        <ScopeRequiredField checked={requireScope} onChecked={setRequireScope} />
      )}
      {err && <div className="alert alert--error mb-4">{err}</div>}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel}>
          <X size={13} /> Anuluj
        </button>
        <button type="submit" className="btn btn--primary btn--sm" disabled={saving}>
          <Save size={13} /> Zapisz
        </button>
      </div>
    </form>
  )
}


function PermissionsPanel({ system: s }) {
  const [perms, setPerms]     = useState([])
  const [loading, setLoading] = useState(true)
  const [permQuery, setPermQuery] = useState('')
  const [showImport, setShowImport] = useState(false)
  const [showGroup, setShowGroup] = useState(false)
  const [showCopyGroup, setShowCopyGroup] = useState(false)
  const [renaming, setRenaming] = useState(null)      // nazwa grupy w edycji
  const [renameValue, setRenameValue] = useState('')
  // Zaznaczone uprawnienia do operacji masowej (przypisanie podgrupy).
  const [selPerms, setSelPerms] = useState(() => new Set())
  const toggleSel = (id) => setSelPerms(prev => {
    const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n
  })
  const clearSel = () => setSelPerms(new Set())

  async function load() {
    setLoading(true)
    try { const r = await listPermissions(s.id); setPerms(r.data) }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [s.id])

  // Pozycja administratora nie należy do listy edytowalnej — system utrzymuje
  // ją sam wg flagi `admin_option`, więc pokazujemy tylko notkę.
  const adminNote = s.admin_option !== false ? (
    <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 8 }}>
      <ShieldCheck size={13} style={{ verticalAlign: 'middle', marginRight: 6 }} />
      Dodatkowo na wniosku dostępna jest pozycja
      <strong> „Uprawnienia administratora"</strong> — dodawana automatycznie.
      Wyłączysz ją w edycji oprogramowania.
    </div>
  ) : null

  if (s.access_only) {
    return (
      <div style={{ color: 'var(--color-text-muted)', fontSize: 12, padding: '12px 0' }}>
        <ShieldCheck size={13} style={{ verticalAlign: 'middle', marginRight: 6 }} />
        System oznaczony jako „dostęp bez dodatkowych uprawnień" — wniosek
        zawiera tylko pozycję „Dostęp". Aby dodawać szczegółowe uprawnienia,
        wyłącz ten tryb w edycji systemu.
        {adminNote}
      </div>
    )
  }

  // Uprawnienia opisywane przez wnioskodawcę — lista predefiniowana jest
  // wtedy zbędna: to kierownik wpisuje we wniosku, czego pracownik potrzebuje.
  const ownPerms = perms.filter(p => !p.is_admin_option)
  // Przy setkach zaimportowanych pozycji tabela bez szukajki jest nie do przejścia.
  const q = permQuery.trim().toLowerCase()
  const matches = p => !q
    || p.permission_name.toLowerCase().includes(q)
    || (p.description || '').toLowerCase().includes(q)
  const groups = groupPerms(ownPerms)

  async function toggleGroup(group, active) {
    try {
      await setPermissionGroupState(s.id, group, active)
      load()
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Błąd')
    }
  }

  async function renameGroup(group) {
    const name = renameValue.trim()
    if (!name || name === group) { setRenaming(null); return }
    try {
      await renamePermissionGroup(s.id, group, name)
      setRenaming(null)
      load()
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Nie udało się zmienić nazwy grupy')
    }
  }

  // Przestawianie kolejności GRUP (↑/↓). Budujemy pełną listę nazw grup po
  // przestawieniu i wysyłamy — backend nadaje im kolejne numery.
  async function moveGroup(group, dir) {
    const names = groups.map(g => g.group).filter(Boolean)
    const i = names.indexOf(group)
    const j = i + dir
    if (i < 0 || j < 0 || j >= names.length) return
    ;[names[i], names[j]] = [names[j], names[i]]
    try { await setPermissionGroupOrder(s.id, names); load() }
    catch (ex) { alert(ex.response?.data?.detail || 'Nie udało się zmienić kolejności grup') }
  }

  async function removeGroup(group, count) {
    if (!confirm(
      `Usunąć grupę „${group}" (${count} pozycji)?\n\n`
      + 'Uprawnienia użyte już we wnioskach nie zostaną usunięte — '
      + 'zostaną wygaszone, żeby nie zerwać ewidencji.'
    )) return
    try {
      const r = await deletePermissionGroup(s.id, group)
      load()
      if (r.data.skipped > 0) {
        alert(`Usunięto: ${r.data.deactivated}\n`
              + `Zachowano (użyte we wnioskach): ${r.data.skipped}`)
      }
    } catch (ex) {
      alert(ex.response?.data?.detail || 'Błąd')
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {loading ? (
        <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>
      ) : (
        <>
          <div style={{
            display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
          }}>
            <button className="btn btn--action btn--sm" onClick={() => setShowGroup(true)}>
              <ListPlus size={13} /> Nowa grupa uprawnień
            </button>
            <button className="btn btn--ghost btn--sm" onClick={() => setShowImport(true)}>
              <FileSpreadsheet size={13} /> Importuj z pliku
            </button>
            <button className="btn btn--ghost btn--sm" onClick={() => setShowCopyGroup(true)}>
              <Copy size={13} /> Kopiuj grupę z programu
            </button>
            {ownPerms.length > 12 && (
              <input className="form-control" style={{ flex: '1 1 200px', fontSize: 13 }}
                     aria-label="Szukaj w uprawnieniach" type="search"
                     placeholder="Szukaj w uprawnieniach…"
                     value={permQuery} onChange={e => setPermQuery(e.target.value)} />
            )}
            <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
              pozycji: {ownPerms.length}
            </span>
          </div>

          {/* Nazwy grup do podpowiedzi przy edycji / przenoszeniu pozycji. */}
          <datalist id="szup-perm-groups">
            {groups.map(g => g.group).filter(Boolean).map(g => (
              <option key={g} value={g} />
            ))}
          </datalist>
          {/* Nazwy podgrup do podpowiedzi. */}
          <datalist id="szup-perm-subgroups">
            {subgroupNames(ownPerms).map(sg => <option key={sg} value={sg} />)}
          </datalist>

          {ownPerms.length === 0 ? (
            <div style={{
              color: 'var(--color-text-muted)', fontSize: 13,
              border: '1px dashed var(--color-border)', borderRadius: 6,
              padding: 14, marginBottom: 12,
            }}>
              Brak uprawnień dla tego systemu. Zacznij od
              <strong> „Nowa grupa uprawnień"</strong> — pozycje dodaje się zawsze
              wewnątrz grupy (albo zaimportuj gotową listę z pliku).
            </div>
          ) : (
            groups.map(({ group, items }) => {
              const shown = items.filter(matches)
              const activeCount = items.filter(p => p.is_active !== false).length
              const namedGroups = groups.map(g => g.group).filter(Boolean)
              const gi = namedGroups.indexOf(group)
              const selIdsInGroup = items.filter(p => selPerms.has(p.id)).map(p => p.id)
              const allShownSel = shown.length > 0 && shown.every(p => selPerms.has(p.id))
              const toggleAllInGroup = () => setSelPerms(prev => {
                const n = new Set(prev)
                shown.forEach(p => allShownSel ? n.delete(p.id) : n.add(p.id))
                return n
              })
              return (
                <div key={group || '_'} style={{
                  background: 'var(--color-card)',
                  border: '1px solid var(--color-border)', borderRadius: 8,
                  overflow: 'hidden',
                }}>
                  {group ? (
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 6,
                      padding: '8px 12px', borderBottom: '1px solid var(--color-border)', flexWrap: 'wrap',
                    }}>
                      {renaming === group ? (
                        <>
                          <input className="form-control" autoFocus
                                 style={{ maxWidth: 340, fontSize: 13 }}
                                 value={renameValue}
                                 onChange={e => setRenameValue(e.target.value)}
                                 onKeyDown={e => {
                                   if (e.key === 'Enter') renameGroup(group)
                                   if (e.key === 'Escape') setRenaming(null)
                                 }} />
                          <button className="btn btn--primary btn--sm"
                                  onClick={() => renameGroup(group)}>
                            <Save size={12} /> Zapisz
                          </button>
                          <button className="btn btn--ghost btn--sm"
                                  onClick={() => setRenaming(null)}>
                            Anuluj
                          </button>
                        </>
                      ) : (
                        <>
                          <strong style={{ color: 'var(--color-navy)', fontSize: 14 }}>{group}</strong>
                          <span className="badge badge--neutral" style={{ fontSize: 11, fontWeight: 800 }}>
                            {items.length}
                          </span>
                          {activeCount === 0 && (
                            <span className="badge badge--warning" style={{ fontSize: 10 }}>
                              cała grupa wygaszona
                            </span>
                          )}
                          {namedGroups.length > 1 && (
                            <>
                              <button className="btn btn--ghost btn--sm" title="W górę" aria-label="W górę"
                                      disabled={gi <= 0}
                                      onClick={() => moveGroup(group, -1)}>
                                <ArrowUp size={13} />
                              </button>
                              <button className="btn btn--ghost btn--sm" title="W dół" aria-label="W dół"
                                      disabled={gi >= namedGroups.length - 1}
                                      onClick={() => moveGroup(group, 1)}>
                                <ArrowDown size={13} />
                              </button>
                            </>
                          )}
                          <span style={{ flex: 1 }} />
                          <button className="btn btn--ghost btn--sm"
                                  onClick={() => { setRenaming(group); setRenameValue(group) }}>
                            <Edit2 size={12} /> Zmień nazwę
                          </button>
                          <button className="btn btn--ghost btn--sm"
                                  onClick={() => toggleGroup(group, activeCount === 0)}>
                            {activeCount === 0 ? 'Przywróć grupę' : 'Wygaś grupę'}
                          </button>
                          <button className="btn btn--ghost btn--sm"
                                  style={{ color: 'var(--color-error-text)', borderColor: 'var(--color-error)' }}
                                  onClick={() => removeGroup(group, items.length)}>
                            <Trash2 size={12} /> Usuń grupę
                          </button>
                        </>
                      )}
                    </div>
                  ) : (
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
                      padding: '8px 12px', borderBottom: '1px solid var(--color-border)',
                    }}>
                      <strong style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>Bez grupy</strong>
                      <span className="badge badge--neutral" style={{ fontSize: 10 }}>{items.length}</span>
                      <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        — pozycje bez grupy; w edycji możesz przypisać je do grupy
                      </span>
                    </div>
                  )}

                  {shown.length > 0 && (
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center',
                                  flexWrap: 'wrap', padding: '8px 12px' }}>
                      <button className="btn btn--sm"
                              style={{ background: 'transparent', border: 0, padding: 0, color: 'var(--color-navy)', textDecoration: 'underline', fontWeight: 600, fontSize: 13 }}
                              onClick={toggleAllInGroup}>
                        {allShownSel ? 'Odznacz wszystkie' : 'Zaznacz wszystkie'}
                      </button>
                      <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                        — zaznacz pozycje, aby masowo przypisać je do podgrupy
                      </span>
                    </div>
                  )}
                  {selIdsInGroup.length > 0 && (
                    <BulkSubgroupBar systemId={s.id} selectedIds={selIdsInGroup}
                                     onDone={() => { clearSel(); load() }} />
                  )}

                  {shown.length === 0 ? (
                    <div style={{ fontSize: 13, color: 'var(--color-text-muted)', padding: '8px 12px' }}>
                      Brak pozycji pasujących do wyszukiwania.
                    </div>
                  ) : (
                    <div style={{ overflowX: 'auto' }}>
                    <table className="data-table" style={{ minWidth: 640 }}>
                      <thead>
                        <tr>
                          <th style={{ width: '35%' }}>Uprawnienie</th>
                          <th>Opis</th>
                          <th style={{ width: 90 }}></th>
                        </tr>
                      </thead>
                      <tbody>
                        {/* Drugi poziom sekcji: podgrupy wewnątrz grupy. Pozycje bez
                            podgrupy idą pierwsze (bez pod-nagłówka). */}
                        {subgroupPerms(shown).map(({ subgroup, items: subItems }) => (
                          <Fragment key={subgroup || '_nosub'}>
                            {subgroup && (
                              <tr>
                                <td colSpan={3} style={{
                                  background: 'var(--bg-secondary)', padding: '6px 12px',
                                  fontSize: 12, textTransform: 'uppercase', letterSpacing: '.06em',
                                  color: 'var(--color-text-muted)', fontWeight: 700,
                                }}>
                                  ↳ {subgroup}
                                  <span className="badge badge--neutral"
                                        style={{ fontSize: 9, marginLeft: 6 }}>
                                    {subItems.length}
                                  </span>
                                </td>
                              </tr>
                            )}
                            {subItems.map(p => (
                              <PermRow key={p.id} p={p} onChanged={load}
                                       selected={selPerms.has(p.id)}
                                       onToggleSel={() => toggleSel(p.id)} />
                            ))}
                          </Fragment>
                        ))}
                      </tbody>
                    </table>
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', padding: '10px 12px' }}>
                    <GroupAddPerm systemId={s.id} group={group} onAdded={load} />
                    {subgroupPerms(items).filter(x => x.subgroup).map(({ subgroup }) => (
                      <GroupAddPerm key={subgroup} systemId={s.id} group={group}
                                    subgroup={subgroup} label={`Dodaj do „${subgroup}"`}
                                    onAdded={load} />
                    ))}
                  </div>
                </div>
              )
            })
          )}

          <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            Każde uprawnienie należy do grupy — pozycje dodajesz przyciskiem
            „Dodaj uprawnienie" wewnątrz grupy, a nową grupę zakładasz przyciskiem
            „Nowa grupa uprawnień". „Zwykły checkbox" to pozycja bez doprecyzowania
            (tak wygląda import); pozostałe typy dokładają listę albo pole
            wypełniane przez kierownika. <strong>Edycja</strong> (ołówek) pozwala
            zmienić nazwę, opis, sposób wyboru oraz przenieść pozycję do innej grupy.
          </div>
          {adminNote}
          {showImport && (
            <PermissionImportModal
              system={s}
              onClose={() => setShowImport(false)}
              onDone={() => { setShowImport(false); load() }}
            />
          )}
          {showGroup && (
            <PermissionGroupModal
              system={s}
              existingGroups={groups.map(g => g.group).filter(Boolean)}
              onClose={() => setShowGroup(false)}
              onDone={() => { setShowGroup(false); load() }}
            />
          )}
          {showCopyGroup && (
            <CopyGroupModal
              system={s}
              existingGroups={groups.map(g => g.group).filter(Boolean)}
              onClose={() => setShowCopyGroup(false)}
              onDone={() => { setShowCopyGroup(false); load() }}
            />
          )}
        </>
      )}
    </div>
  )
}
