import { useEffect, useMemo, useRef, useState } from 'react'
import { FilePlus, UserMinus, ChevronDown, ChevronRight, Building2, Check } from 'lucide-react'
import { listRequests, createRequest, listActiveDepts, listActiveUnits, listRequestTypes, usersByDepartment, searchUsers } from '../api'
import { fmtDate } from '../serverTime'

const KIND_BADGE = { grant: 'badge--info', revoke: 'badge--warning' }
const KIND_LABEL = { grant: 'Zatrudnienie', revoke: 'Ustanie stosunku pracy' }

// Mały nagłówek sekcji w oknach kadrowych — spójny, czytelny podział.
function SectionLabel({ children }) {
  return (
    <div style={{
      fontSize: 11, fontWeight: 700, letterSpacing: '.04em', textTransform: 'uppercase',
      color: 'var(--color-text-muted)', margin: '2px 0 8px',
    }}>
      {children}
    </div>
  )
}

// Zielony chip z wybraną komórką (jednostka › komórka).
function SelectedPlace({ unit, dept }) {
  return (
    <div style={{
      display: 'inline-flex', alignItems: 'center', gap: 8, marginBottom: 8,
      padding: '6px 12px', borderRadius: 999,
      background: 'var(--color-success-bg)', border: '1px solid var(--color-success)',
      fontSize: 13,
    }}>
      <Check size={14} style={{ color: 'var(--color-success)' }} />
      <span><strong style={{ color: 'var(--color-navy)' }}>{unit || '?'}</strong> › {dept}</span>
    </div>
  )
}

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
  const [startDate, setStartDate]     = useState('')   // data zatrudnienia od
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
    if (!position.trim()) { setErr('Podaj stanowisko'); return }
    if (!selectedDept) { setErr('Wybierz miejsce pracy'); return }

    setBusy(true)
    try {
      await createRequest({
        worker_name:     workerName,
        worker_position: position.trim(),
        employment_from: startDate || null,
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
      <div className="modal" style={{ maxWidth: 'min(96vw, 760px)', width: '100%' }}>
        <div className="modal__header">
          <span className="modal__title">
            <FilePlus size={15} style={{ marginRight: 8, verticalAlign: 'middle' }} />
            Nowy pracownik
          </span>
          <button className="modal__close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={submit} className="modal__body"
              style={{ minHeight: 'min(72vh, 560px)' }}>
          <p style={{ color: 'var(--color-text-muted)', fontSize: 13, marginBottom: 16 }}>
            Zgłoś nowego pracownika. Wniosek trafi do kierownika jego komórki, który wybierze
            uprawnienia, a następnie do IT.
          </p>
          <SectionLabel>Dane pracownika</SectionLabel>
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

          <div className="form-row">
            <div className="form-group">
              <label className="form-label">Stanowisko *</label>
              <input className="form-control" required value={position}
                     onChange={e => setPosition(e.target.value)}
                     placeholder="np. Podinspektor" />
            </div>
            <div className="form-group">
              <label className="form-label">Data zatrudnienia od</label>
              <input className="form-control" type="date" value={startDate}
                     onChange={e => setStartDate(e.target.value)} />
            </div>
          </div>
          <div style={{ height: 6 }} />
          <SectionLabel>Miejsce pracy *</SectionLabel>
          <DeptSearchSelect units={units} depts={depts} value={deptId} onChange={setDeptId} />

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

  // Wyszukiwanie pracownika po nazwisku (ponad komórkami).
  const [search, setSearch]   = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [picked, setPicked]   = useState(null)   // wybrany z wyszukiwarki (pełne dane)

  const [workUntil, setWorkUntil] = useState('')   // ostatni dzień pracy
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

  // Debounced wyszukiwanie po nazwisku/loginie.
  useEffect(() => {
    const q = search.trim()
    if (q.length < 2) { setResults([]); return }
    setSearching(true)
    const t = setTimeout(() => {
      searchUsers(q)
        .then(r => setResults(r.data))
        .catch(() => setResults([]))
        .finally(() => setSearching(false))
    }, 250)
    return () => clearTimeout(t)
  }, [search])

  const selectedDept = useMemo(() => depts.find(d => d.id === deptId) || null, [deptId, depts])
  const selectedUnit = useMemo(
    () => selectedDept ? units.find(u => u.id === selectedDept.unit_id) : null,
    [selectedDept, units]
  )
  const selectedWorker = useMemo(() => workers.find(w => w.id === workerId) || null, [workerId, workers])

  // Po wyborze komórki (ścieżka ręczna) pobierz jej pracowników.
  useEffect(() => {
    setWorkers([]); setWorkerId(null)
    if (!deptId) return
    setLoadingWorkers(true)
    usersByDepartment(deptId)
      .then(r => setWorkers(r.data))
      .catch(() => setWorkers([]))
      .finally(() => setLoadingWorkers(false))
  }, [deptId])

  // Wybór z wyszukiwarki — ustawia pracownika i jego komórkę; czyści ścieżkę ręczną.
  function pickFromSearch(r) {
    setPicked(r)
    setSearch(''); setResults([])
    setDeptId(null); setWorkerId(null)
  }

  // Efektywny pracownik/komórka do zapisu: z wyszukiwarki albo z picker-a.
  const effWorker = picked
    ? { id: picked.id, name: picked.full_name || picked.username,
        unit_id: picked.unit_id, department_id: picked.department_id,
        unit_name: picked.unit_name, department_name: picked.department_name }
    : (selectedWorker && selectedDept
        ? { id: selectedWorker.id, name: selectedWorker.full_name || selectedWorker.username,
            unit_id: selectedDept.unit_id, department_id: selectedDept.id,
            unit_name: selectedUnit?.name, department_name: selectedDept.name }
        : null)

  async function submit(e) {
    e.preventDefault()
    setErr(null)
    if (!effWorker) { setErr('Wskaż pracownika (wyszukaj po nazwisku albo wybierz z komórki)'); return }
    if (!effWorker.department_id) { setErr('Nie udało się ustalić komórki pracownika'); return }

    setBusy(true)
    try {
      await createRequest({
        kind:            'revoke',
        worker_name:     effWorker.name,
        worker_user_id:  effWorker.id,
        work_until:      workUntil || null,
        unit_id:         effWorker.unit_id,
        department_id:   effWorker.department_id,
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
      <div className="modal" style={{ maxWidth: 'min(94vw, 680px)', width: '100%' }}>
        <div className="modal__header">
          <span className="modal__title">
            <UserMinus size={15} style={{ marginRight: 8, verticalAlign: 'middle' }} />
            Ustanie stosunku pracy
          </span>
          <button className="modal__close" onClick={onClose}>×</button>
        </div>
        <form onSubmit={submit} className="modal__body">
          <p style={{ color: 'var(--color-text-muted)', fontSize: 13, marginBottom: 16 }}>
            Wskaż pracownika, którego stosunek pracy ustaje. Wniosek trafi do kierownika,
            który wybierze uprawnienia do odebrania, a następnie do IT.
          </p>

          <SectionLabel>Pracownik</SectionLabel>
          {/* Wyszukiwanie po nazwisku — najszybsza droga. */}
          <div className="form-group">
            <label className="form-label">Znajdź po nazwisku lub loginie</label>
            {picked ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                            padding: '9px 12px', border: '1px solid var(--color-success)',
                            background: 'var(--color-success-bg)', borderRadius: 6 }}>
                <strong>{picked.full_name || picked.username}</strong>
                <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  {picked.username ? `(${picked.username}) · ` : ''}
                  {picked.unit_name ? `${picked.unit_name} › ` : ''}{picked.department_name || '—'}
                </span>
                <button type="button" className="btn btn--ghost btn--sm" style={{ marginLeft: 'auto' }}
                        onClick={() => setPicked(null)}>Zmień</button>
              </div>
            ) : (
              <>
                <input className="form-control" value={search} autoFocus
                       placeholder="Wpisz co najmniej 2 znaki nazwiska…"
                       onChange={e => setSearch(e.target.value)} />
                {searching && <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>Szukam…</div>}
                {results.length > 0 && (
                  <div style={{ border: '1px solid var(--color-border)', borderRadius: 6, marginTop: 6,
                                maxHeight: 220, overflowY: 'auto', background: 'var(--bg-secondary)' }}>
                    {results.map(r => (
                      <div key={r.id} onClick={() => pickFromSearch(r)}
                           style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                                    padding: '8px 12px', borderBottom: '1px solid var(--color-border)', fontSize: 13 }}
                           onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover, rgba(0,0,0,0.04))'}
                           onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                        <span style={{ fontWeight: 600 }}>{r.full_name || r.username}</span>
                        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                          {r.username ? `(${r.username})` : ''}
                        </span>
                        <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--color-text-muted)' }}>
                          {r.unit_name ? `${r.unit_name} › ` : ''}{r.department_name || '—'}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                {search.trim().length >= 2 && !searching && results.length === 0 && (
                  <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>
                    Brak wyników — spróbuj inaczej albo wybierz z komórki poniżej.
                  </div>
                )}
              </>
            )}
          </div>

          {/* Alternatywnie: wybór komórki → pracownik z listy. */}
          {!picked && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '6px 0 12px' }}>
                <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '.04em' }}>
                  albo wybierz z komórki
                </span>
                <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
              </div>
              <div className="form-group">
                <label className="form-label">Komórka organizacyjna</label>
                {selectedDept && (
                  <SelectedPlace unit={selectedUnit?.name} dept={selectedDept.name} />
                )}
                <DepartmentPicker units={units} depts={depts} selectedId={deptId} onSelect={setDeptId} />
              </div>

              <div className="form-group">
                <label className="form-label">Pracownik</label>
                {!deptId ? (
                  <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                    Najpierw wybierz komórkę powyżej (albo użyj wyszukiwarki).
                  </div>
                ) : loadingWorkers ? (
                  <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Ładowanie pracowników…</div>
                ) : workers.length === 0 ? (
                  <div className="alert alert--warning" style={{ fontSize: 12 }}>
                    Brak aktywnych pracowników przypisanych do tej komórki.
                  </div>
                ) : (
                  <select className="form-control" value={workerId || ''}
                          onChange={e => setWorkerId(Number(e.target.value) || null)}>
                    <option value="">— wybierz pracownika —</option>
                    {workers.map(w => (
                      <option key={w.id} value={w.id}>
                        {w.full_name || w.username}{w.username ? ` (${w.username})` : ''}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            </>
          )}

          <div style={{ height: 6 }} />
          <SectionLabel>Termin</SectionLabel>
          <div className="form-group">
            <label className="form-label">Data do której pracuje (ostatni dzień pracy)</label>
            <input className="form-control" type="date" style={{ maxWidth: 220 }}
                   value={workUntil} onChange={e => setWorkUntil(e.target.value)} />
          </div>

          {err && <div className="alert alert--error mt-4">{err}</div>}
        </form>
        <div className="modal__footer">
          <button type="button" className="btn btn--ghost" onClick={onClose}>Anuluj</button>
          <button className="btn btn--action" disabled={busy || !effWorker}
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

// Combobox z wyszukiwaniem komórki organizacyjnej: wpisz fragment → lista
// pasujących komórek z pełną ścieżką „Jednostka › … › Komórka" → wybierz.
function DeptSearchSelect({ units, depts, value, onChange }) {
  const [open, setOpen]   = useState(false)
  const [query, setQuery] = useState('')
  const wrapRef = useRef(null)

  const byId = useMemo(() => new Map(depts.map(d => [d.id, d])), [depts])
  const unitById = useMemo(() => new Map(units.map(u => [u.id, u])), [units])
  function pathStr(d) {
    const names = []; const seen = new Set(); let cur = d
    while (cur && !seen.has(cur.id)) { seen.add(cur.id); names.unshift(cur.name); cur = cur.parent_dept_id ? byId.get(cur.parent_dept_id) : null }
    const un = unitById.get(d.unit_id)?.name
    return (un ? un + ' › ' : '') + names.join(' › ')
  }

  const selected = depts.find(d => d.id === value) || null
  const q = query.trim().toLowerCase()
  const matches = useMemo(() => (
    depts.map(d => ({ d, path: pathStr(d) }))
      .filter(x => !q || x.path.toLowerCase().includes(q))
      .sort((a, b) => a.path.localeCompare(b.path, 'pl'))
      .slice(0, 60)
  ), [depts, q, units])

  useEffect(() => {
    function onDoc(e) { if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  // Wybrana komórka (i nie edytujemy) → zielony chip z „Zmień".
  if (selected && !open) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
        padding: '8px 12px', borderRadius: 6,
        background: 'var(--color-success-bg)', border: '1px solid var(--color-success)', fontSize: 13,
      }}>
        <Check size={14} style={{ color: 'var(--color-success)' }} />
        <span>{pathStr(selected)}</span>
        <button type="button" className="btn btn--ghost btn--sm" style={{ marginLeft: 'auto' }}
                onClick={() => { setOpen(true); setQuery('') }}>Zmień</button>
      </div>
    )
  }

  return (
    <div ref={wrapRef} style={{ position: 'relative' }}>
      <input className="form-control" value={query}
             placeholder="Wpisz fragment nazwy komórki lub jednostki…"
             onFocus={() => setOpen(true)} onChange={e => { setQuery(e.target.value); setOpen(true) }} />
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 20, marginTop: 4,
          border: '1px solid var(--color-border)', borderRadius: 8, background: 'var(--color-card)',
          boxShadow: 'var(--shadow-modal, 0 8px 24px rgba(0,0,0,0.18))',
          maxHeight: 'min(46vh, 360px)', overflowY: 'auto',
        }}>
          {matches.length === 0 ? (
            <div style={{ padding: 12, fontSize: 13, color: 'var(--color-text-muted)' }}>
              Brak komórek pasujących do „{query}".
            </div>
          ) : matches.map(({ d, path }) => {
            const isSel = d.id === value
            return (
              <div key={d.id}
                   onClick={() => { onChange(d.id); setOpen(false); setQuery('') }}
                   style={{
                     display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                     padding: '8px 12px', fontSize: 13, borderBottom: '1px solid var(--color-border)',
                     background: isSel ? 'var(--color-gold-soft, rgba(196,162,88,0.18))' : 'transparent',
                   }}
                   onMouseEnter={e => { if (!isSel) e.currentTarget.style.background = 'var(--bg-hover, rgba(0,0,0,0.04))' }}
                   onMouseLeave={e => { if (!isSel) e.currentTarget.style.background = 'transparent' }}>
                <Building2 size={14} style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
                <span style={{ flex: 1 }}>{path}</span>
                {isSel && <Check size={14} style={{ color: 'var(--color-navy)' }} />}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

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

  // --- Wyszukiwarka komórek (po nazwie / ścieżce / jednostce) --------------
  const [query, setQuery] = useState('')
  const byId = useMemo(() => new Map(depts.map(d => [d.id, d])), [depts])
  const unitById = useMemo(() => new Map(units.map(u => [u.id, u])), [units])
  function pathStr(d) {
    const names = []; const seen = new Set(); let cur = d
    while (cur && !seen.has(cur.id)) { seen.add(cur.id); names.unshift(cur.name); cur = cur.parent_dept_id ? byId.get(cur.parent_dept_id) : null }
    const un = unitById.get(d.unit_id)?.name
    return (un ? un + ' › ' : '') + names.join(' › ')
  }
  const q = query.trim().toLowerCase()
  const matches = q
    ? depts
        .map(d => ({ d, path: pathStr(d) }))
        .filter(x => x.path.toLowerCase().includes(q))
        .sort((a, b) => a.path.localeCompare(b.path, 'pl'))
        .slice(0, 100)
    : null

  return (
    <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, background: 'var(--bg-secondary)', overflow: 'hidden' }}>
      <div style={{ padding: 8, borderBottom: '1px solid var(--color-border)', background: 'var(--color-card)' }}>
        <input className="form-control" style={{ fontSize: 13 }}
               placeholder="Szukaj komórki (nazwa, jednostka, ścieżka)…"
               value={query} onChange={e => setQuery(e.target.value)} />
      </div>
      <div style={{ maxHeight: 'min(48vh, 420px)', overflowY: 'auto' }}>
        {units.length === 0 && (
          <div style={{ padding: 12, fontSize: 12, color: 'var(--color-text-muted)' }}>
            Brak jednostek — poproś administratora o zaimportowanie struktury z AD.
          </div>
        )}

        {matches ? (
          matches.length === 0 ? (
            <div style={{ padding: 12, fontSize: 13, color: 'var(--color-text-muted)' }}>
              Brak komórek pasujących do „{query}".
            </div>
          ) : matches.map(({ d, path }) => {
            const isSelected = selectedId === d.id
            return (
              <div key={d.id} onClick={() => onSelect(d.id)}
                   style={{
                     display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer',
                     padding: '9px 12px', fontSize: 13,
                     borderBottom: '1px solid var(--color-border)',
                     background: isSelected ? 'var(--color-gold-soft, rgba(196,162,88,0.18))' : 'transparent',
                     fontWeight: isSelected ? 600 : 400,
                   }}
                   onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--bg-hover, rgba(0,0,0,0.04))' }}
                   onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}>
                <Building2 size={14} style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
                <span style={{ flex: 1 }}>{path}</span>
                {isSelected && <Check size={14} style={{ color: 'var(--color-navy)' }} />}
              </div>
            )
          })
        ) : (
          units.map(u => {
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
          })
        )}
      </div>
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
