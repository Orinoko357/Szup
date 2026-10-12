import { useEffect, useMemo, useState } from 'react'
import { FilePlus, UserMinus, ChevronDown, ChevronRight, Building2, Check } from 'lucide-react'
import { listRequests, createRequest, listActiveDepts, listActiveUnits, listRequestTypes, usersByDepartment } from '../api'
import { fmtDate } from '../serverTime'

const KIND_BADGE = { grant: 'badge--info', revoke: 'badge--warning' }
const KIND_LABEL = { grant: 'Zatrudnienie', revoke: 'Ustanie stosunku pracy' }

const STATUS_LABELS = {
  pending_selection: 'Wybór uprawnień',
  pending_manager:   'Oczekuje na kierownika',
  pending_it:        'Oczekuje na IT',
  completed:         'Zrealizowane',
  rejected:          'Odrzucone',
}

const STATUS_BADGE = {
  pending_selection: 'badge--warning',
  pending_manager:   'badge--warning',
  pending_it:        'badge--info',
  completed:         'badge--success',
  rejected:          'badge--error',
}

export default function HR() {
  const [requests, setRequests] = useState([])
  const [loading, setLoading]   = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [showTermination, setShowTermination] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const r = await listRequests()
      setRequests(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Kartoteka</div>
          <div className="page-header__sub">Zgłoś zatrudnienie nowego pracownika lub ustanie stosunku pracy</div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn--action" onClick={() => setShowForm(true)}>
            <FilePlus size={15} />
            Nowy pracownik
          </button>
          <button className="btn btn--ghost" onClick={() => setShowTermination(true)}>
            <UserMinus size={15} />
            Ustanie stosunku pracy
          </button>
        </div>
      </div>

      <div className="card">
        <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-navy)', marginBottom: 16 }}>
          Moje zgłoszenia
        </div>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>
        ) : requests.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)' }}>Brak zgłoszeń</div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>#</th><th>Pracownik</th><th>Rodzaj</th><th>Stanowisko</th><th>Status</th><th>Data</th>
              </tr>
            </thead>
            <tbody>
              {requests.map(r => {
                const kind = r.kind || 'grant'
                return (
                  <tr key={r.id}>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.id}</td>
                    <td style={{ fontWeight: 600 }}>{r.worker_name}</td>
                    <td>
                      <span className={`badge ${KIND_BADGE[kind] || 'badge--neutral'}`} style={{ fontSize: 11 }}>
                        {KIND_LABEL[kind] || kind}
                      </span>
                    </td>
                    <td style={{ color: 'var(--color-text-muted)' }}>{r.worker_position || '—'}</td>
                    <td><span className={`badge ${STATUS_BADGE[r.status] || 'badge--neutral'}`}>
                      {STATUS_LABELS[r.status] || r.status}
                    </span></td>
                    <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                      {fmtDate(r.created_at)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      {showForm && (
        <RequestFormModal onClose={() => setShowForm(false)} onCreated={() => { setShowForm(false); load() }} />
      )}
      {showTermination && (
        <TerminationFormModal onClose={() => setShowTermination(false)} onCreated={() => { setShowTermination(false); load() }} />
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Formularz: imię, nazwisko, stanowisko, wydział (picker harmonijkowy)
// ---------------------------------------------------------------------------

function RequestFormModal({ onClose, onCreated }) {
  const [units, setUnits] = useState([])
  const [depts, setDepts] = useState([])

  const [firstName, setFirstName]     = useState('')
  const [lastName, setLastName]       = useState('')
  const [position, setPosition]       = useState('')
  const [deptId, setDeptId]           = useState(null)
  const [requestTypes, setRequestTypes] = useState([])
  const [requestTypeId, setRequestTypeId] = useState(null)

  const [err, setErr]   = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([listActiveUnits(), listActiveDepts(), listRequestTypes({ is_active: true })])
      .then(([u, d, t]) => {
        setUnits(u.data); setDepts(d.data); setRequestTypes(t.data)
        // HR zawsze składa wniosek „nowy pracownik" — bez wyboru rodzaju.
        const emp = t.data.find(x => x.code === 'NEW_EMP') || t.data[0]
        if (emp) setRequestTypeId(emp.id)
      })
      .catch(() => {})
  }, [])

  const selectedDept = useMemo(
    () => depts.find(d => d.id === deptId) || null,
    [deptId, depts]
  )
  const selectedUnit = useMemo(
    () => selectedDept ? units.find(u => u.id === selectedDept.unit_id) : null,
    [selectedDept, units]
  )

  async function submit(e) {
    e.preventDefault()
    setErr(null)

    const workerName = `${firstName.trim()} ${lastName.trim()}`.trim()
    if (!workerName) { setErr('Podaj imię i nazwisko'); return }
    if (!selectedDept) { setErr('Wybierz miejsce pracy'); return }

    setBusy(true)
    try {
      await createRequest({
        worker_name:     workerName,
        worker_position: position || null,
        unit_id:         selectedDept.unit_id,
        department_id:   selectedDept.id,
        items:           [],
        request_type_id: requestTypeId || null,
      })
      onCreated()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd zapisu zgłoszenia')
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 620 }}>
        <div className="modal__header">
          <span className="modal__title">
            <FilePlus size={15} style={{ marginRight: 8, verticalAlign: 'middle' }} />
            Nowy pracownik
          </span>
          <button className="modal__close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={submit} className="modal__body">
          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Imię *</label>
              <input className="form-control" required autoFocus
                     value={firstName} onChange={e => setFirstName(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Nazwisko *</label>
              <input className="form-control" required
                     value={lastName} onChange={e => setLastName(e.target.value)} />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">Stanowisko</label>
            <input className="form-control" value={position}
                   onChange={e => setPosition(e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Miejsce pracy *</label>
            {selectedDept && (
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 6 }}>
                Wybrany: <strong style={{ color: 'var(--color-navy)' }}>
                  {selectedUnit?.name || '?'} › {selectedDept.name}
                </strong>
              </div>
            )}
            <DepartmentPicker
              units={units}
              depts={depts}
              selectedId={deptId}
              onSelect={setDeptId}
            />
          </div>

          {err && <div className="alert alert--error mt-4">{err}</div>}
        </form>
        <div className="modal__footer">
          <button type="button" className="btn btn--ghost" onClick={onClose}>Anuluj</button>
          <button className="btn btn--action" disabled={busy}
                  onClick={() => document.querySelector('.modal form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))}>
            {busy ? 'Zapisywanie…' : 'Zapisz pracownika'}
          </button>
        </div>
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Formularz: ustanie stosunku pracy — wybór komórki → pracownik z listy
// ---------------------------------------------------------------------------

function TerminationFormModal({ onClose, onCreated }) {
  const [units, setUnits] = useState([])
  const [depts, setDepts] = useState([])
  const [requestTypeId, setRequestTypeId] = useState(null)

  const [deptId, setDeptId]   = useState(null)
  const [workers, setWorkers] = useState([])
  const [loadingWorkers, setLoadingWorkers] = useState(false)
  const [workerId, setWorkerId] = useState(null)

  const [err, setErr]   = useState(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    Promise.all([listActiveUnits(), listActiveDepts(), listRequestTypes({ is_active: true })])
      .then(([u, d, t]) => {
        setUnits(u.data); setDepts(d.data)
        if (t.data.length > 0) setRequestTypeId(t.data[0].id)
      })
      .catch(() => {})
  }, [])

  const selectedDept = useMemo(() => depts.find(d => d.id === deptId) || null, [deptId, depts])
  const selectedUnit = useMemo(
    () => selectedDept ? units.find(u => u.id === selectedDept.unit_id) : null,
    [selectedDept, units]
  )
  const selectedWorker = useMemo(() => workers.find(w => w.id === workerId) || null, [workerId, workers])

  // Po wyborze komórki pobierz jej pracowników.
  useEffect(() => {
    setWorkers([]); setWorkerId(null)
    if (!deptId) return
    setLoadingWorkers(true)
    usersByDepartment(deptId)
      .then(r => setWorkers(r.data))
      .catch(() => setWorkers([]))
      .finally(() => setLoadingWorkers(false))
  }, [deptId])

  async function submit(e) {
    e.preventDefault()
    setErr(null)
    if (!selectedDept) { setErr('Wybierz komórkę organizacyjną'); return }
    if (!selectedWorker) { setErr('Wybierz pracownika'); return }

    setBusy(true)
    try {
      await createRequest({
        kind:            'revoke',
        worker_name:     selectedWorker.full_name || selectedWorker.username,
        worker_user_id:  selectedWorker.id,
        unit_id:         selectedDept.unit_id,
        department_id:   selectedDept.id,
        items:           [],
        request_type_id: requestTypeId || null,
      })
      onCreated()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd zapisu zgłoszenia')
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 620 }}>
        <div className="modal__header">
          <span className="modal__title">
            <UserMinus size={15} style={{ marginRight: 8, verticalAlign: 'middle' }} />
            Ustanie stosunku pracy
          </span>
          <button className="modal__close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={submit} className="modal__body">
          <p style={{ color: 'var(--color-text-muted)', fontSize: 13, marginBottom: 16 }}>
            Wskaż komórkę i pracownika, którego stosunek pracy ustaje. Wniosek trafi
            do kierownika, który wybierze uprawnienia do odebrania, a następnie do IT.
          </p>

          <div className="form-group">
            <label className="form-label">Komórka organizacyjna *</label>
            {selectedDept && (
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 6 }}>
                Wybrana: <strong style={{ color: 'var(--color-navy)' }}>
                  {selectedUnit?.name || '?'} › {selectedDept.name}
                </strong>
              </div>
            )}
            <DepartmentPicker units={units} depts={depts} selectedId={deptId} onSelect={setDeptId} />
          </div>

          <div className="form-group">
            <label className="form-label">Pracownik *</label>
            {!deptId ? (
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                Najpierw wybierz komórkę powyżej.
              </div>
            ) : loadingWorkers ? (
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Ładowanie pracowników…</div>
            ) : workers.length === 0 ? (
              <div className="alert alert--warning" style={{ fontSize: 12 }}>
                Brak aktywnych pracowników przypisanych do tej komórki.
              </div>
            ) : (
              <select className="form-control" value={workerId || ''}
                      onChange={e => setWorkerId(Number(e.target.value) || null)} required>
                <option value="">— wybierz pracownika —</option>
                {workers.map(w => (
                  <option key={w.id} value={w.id}>
                    {w.full_name || w.username}{w.username ? ` (${w.username})` : ''}
                  </option>
                ))}
              </select>
            )}
          </div>

          {err && <div className="alert alert--error mt-4">{err}</div>}
        </form>
        <div className="modal__footer">
          <button type="button" className="btn btn--ghost" onClick={onClose}>Anuluj</button>
          <button className="btn btn--action" disabled={busy || !workerId}
                  onClick={() => document.querySelector('.modal form')?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))}>
            {busy ? 'Zapisywanie…' : 'Zgłoś ustanie'}
          </button>
        </div>
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Picker: jednostka (akordeon) → wydziały w drzewie (akordeon per gałąź)
// ---------------------------------------------------------------------------

function DepartmentPicker({ units, depts, selectedId, onSelect }) {
  // Grupowanie wydziałów po unit_id i parent_dept_id
  const deptsByUnit = useMemo(() => {
    const m = new Map()
    for (const d of depts) {
      if (!m.has(d.unit_id)) m.set(d.unit_id, [])
      m.get(d.unit_id).push(d)
    }
    return m
  }, [depts])

  function buildTree(unitId) {
    const list = deptsByUnit.get(unitId) || []
    const byParent = new Map()
    for (const d of list) {
      const key = d.parent_dept_id ?? null
      if (!byParent.has(key)) byParent.set(key, [])
      byParent.get(key).push(d)
    }
    for (const arr of byParent.values()) arr.sort((a, b) => a.name.localeCompare(b.name))
    return byParent
  }

  // Auto-rozwiń gałąź prowadzącą do aktualnie wybranego wydziału
  const expandedPath = useMemo(() => {
    const set = new Set()
    if (!selectedId) return set
    const byId = new Map(depts.map(d => [d.id, d]))
    let d = byId.get(selectedId)
    if (d) {
      set.add(`unit-${d.unit_id}`)
      let p = d.parent_dept_id
      while (p != null) {
        set.add(`dept-${p}`)
        p = byId.get(p)?.parent_dept_id ?? null
      }
    }
    return set
  }, [selectedId, depts])

  return (
    <div style={{ border: '1px solid var(--color-border)', borderRadius: 6, maxHeight: 300, overflowY: 'auto', background: 'var(--bg-secondary)' }}>
      {units.length === 0 && (
        <div style={{ padding: 12, fontSize: 12, color: 'var(--color-text-muted)' }}>
          Brak jednostek — poproś administratora o zaimportowanie struktury z AD.
        </div>
      )}
      {units.map(u => {
        const byParent = buildTree(u.id)
        const hasAny = (byParent.get(null) || []).length > 0
        return (
          <UnitNode
            key={u.id}
            unit={u}
            byParent={byParent}
            hasAny={hasAny}
            selectedId={selectedId}
            onSelect={onSelect}
            initiallyOpen={expandedPath.has(`unit-${u.id}`)}
            expandedPath={expandedPath}
          />
        )
      })}
    </div>
  )
}

function UnitNode({ unit, byParent, hasAny, selectedId, onSelect, initiallyOpen, expandedPath }) {
  const [open, setOpen] = useState(initiallyOpen)
  useEffect(() => { if (initiallyOpen) setOpen(true) }, [initiallyOpen])

  const roots = byParent.get(null) || []

  return (
    <div style={{ borderBottom: '1px solid var(--color-border)' }}>
      <button
        type="button"
        onClick={() => hasAny && setOpen(v => !v)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', gap: 8,
          padding: '10px 12px', background: 'transparent', border: 'none',
          cursor: hasAny ? 'pointer' : 'default', textAlign: 'left',
          color: 'var(--color-navy)', fontWeight: 700, fontSize: 13,
        }}
      >
        {hasAny
          ? (open ? <ChevronDown size={14} /> : <ChevronRight size={14} />)
          : <span style={{ width: 14 }} />}
        <Building2 size={14} style={{ color: 'var(--color-text-muted)' }} />
        <span style={{ flex: 1 }}>{unit.name}</span>
        {!hasAny && <span style={{ fontSize: 11, color: 'var(--color-text-muted)', fontWeight: 400 }}>(brak wydziałów)</span>}
      </button>
      {open && hasAny && (
        <div style={{ paddingBottom: 4 }}>
          {roots.map(d => (
            <DeptNode
              key={d.id}
              dept={d}
              byParent={byParent}
              depth={1}
              selectedId={selectedId}
              onSelect={onSelect}
              expandedPath={expandedPath}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function DeptNode({ dept, byParent, depth, selectedId, onSelect, expandedPath }) {
  const kids = byParent.get(dept.id) || []
  const hasKids = kids.length > 0
  const [open, setOpen] = useState(expandedPath.has(`dept-${dept.id}`))
  useEffect(() => {
    if (expandedPath.has(`dept-${dept.id}`)) setOpen(true)
  }, [expandedPath, dept.id])

  const isSelected = selectedId === dept.id

  return (
    <div>
      <div
        onClick={() => onSelect(dept.id)}
        style={{
          display: 'flex', alignItems: 'center', gap: 6,
          padding: '6px 12px 6px',
          paddingLeft: 12 + depth * 18,
          cursor: 'pointer',
          background: isSelected ? 'var(--color-gold-soft, rgba(196, 162, 88, 0.18))' : 'transparent',
          fontSize: 13, fontWeight: isSelected ? 600 : 400,
          color: isSelected ? 'var(--color-navy)' : 'inherit',
        }}
        onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--bg-hover, rgba(0,0,0,0.04))' }}
        onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}
      >
        {hasKids ? (
          <button
            type="button"
            onClick={e => { e.stopPropagation(); setOpen(v => !v) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: 'var(--color-text-muted)', display: 'inline-flex' }}
            aria-label={open ? 'Zwiń' : 'Rozwiń'}
          >
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
        ) : (
          <span style={{ width: 12 }} />
        )}
        <span style={{ flex: 1 }}>{dept.name}</span>
        {isSelected && <Check size={13} style={{ color: 'var(--color-navy)' }} />}
      </div>
      {hasKids && open && kids.map(c => (
        <DeptNode
          key={c.id}
          dept={c}
          byParent={byParent}
          depth={depth + 1}
          selectedId={selectedId}
          onSelect={onSelect}
          expandedPath={expandedPath}
        />
      ))}
    </div>
  )
}
