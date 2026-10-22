import { useEffect, useMemo, useRef, useState } from 'react'
import { FilePlus, UserMinus, ChevronDown, ChevronRight, Check, Search, Info, Lock, Copy, X } from 'lucide-react'
import { listRequests, createRequest, listActiveDepts, listActiveUnits, listRequestTypes, usersByDepartment, searchUsers } from '../api'
import { fmtDate, serverTs, serverNow } from '../serverTime'
import { statusLabel, statusBadge, kindLabel, daysSince, waitText } from '../labels'
import { toast } from '../components/ui/feedback'
import RequestViewShell, { Section, buildWorkflowSteps, KindBadge } from '../components/RequestView'


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
      <span><strong style={{ color: 'var(--color-heading)' }}>{unit || '?'}</strong> › {dept}</span>
    </div>
  )
}

// v3.0 — wspólne style formularzy kadrowych (wg projektu).
const FIELD_GRID  = { display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: '14px 16px' }
const FIELD_INPUT = { minHeight: 44, borderRadius: 8, fontSize: 14 }
const NOTE_BOX = {
  display: 'flex', alignItems: 'flex-start', gap: 10, marginTop: 14, padding: '12px 14px',
  borderRadius: 8, background: 'var(--bg-secondary)', border: '1px solid var(--color-border)',
  fontSize: 13, color: 'var(--color-text-muted)',
}

// „Co stanie się dalej” — formularze kadrowe są używane rzadko, więc
// przypominamy, jak idzie obieg po wysłaniu (v3.1).
function NextSteps({ revoke = false }) {
  const steps = [
    revoke ? 'Kierownik komórki wskaże uprawnienia do odebrania.' : 'Kierownik komórki wybierze uprawnienia.',
    'Jeśli komórka tego wymaga — akceptacja kierownika wyższego rzędu.',
    revoke ? 'IT odbierze dostępy w systemach.' : 'IT zrealizuje uprawnienia w systemach.',
    'Dostaniesz potwierdzenie e-mailem, a status zobaczysz w Kartotece.',
  ]
  return (
    <section aria-label="Co stanie się dalej" style={{
      marginTop: 4, padding: '14px 16px', borderRadius: 8,
      background: 'var(--bg-secondary)', border: '1px solid var(--color-border)',
    }}>
      <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--color-heading)', marginBottom: 8 }}>
        Co stanie się dalej
      </div>
      <ol style={{ margin: 0, paddingLeft: 20, fontSize: 13, lineHeight: 1.6, color: 'var(--color-text)' }}>
        {steps.map((t, i) => <li key={i}>{t}</li>)}
      </ol>
    </section>
  )
}

// Gotowa wiadomość do skopiowania po zgłoszeniu nowego pracownika.
function CopyMessageDialog({ info, onClose }) {
  const text = [
    `Zgłoszono zatrudnienie w SZUP (wniosek #${info.id ?? '—'}):`,
    `Pracownik: ${info.name}`,
    `Stanowisko: ${info.position}`,
    `Komórka: ${info.dept}`,
    `Data zatrudnienia od: ${info.from || 'nie podano'}`,
    '',
    'Uprawnienia do systemów wskaże kierownik komórki w SZUP; po akceptacji zrealizuje je Biuro Informatyki.',
  ].join('\n')
  async function copy() {
    try {
      await navigator.clipboard.writeText(text)
      toast('Skopiowano wiadomość do schowka.')
    } catch {
      toast('Nie udało się skopiować — zaznacz tekst i skopiuj ręcznie.', { tone: 'error' })
    }
  }
  return (
    <div role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}
         style={{ position: 'fixed', inset: 0, zIndex: 2500, background: 'rgba(13,20,36,.5)',
                  display: 'grid', placeItems: 'center', padding: 16 }}>
      <div role="dialog" aria-modal="true" aria-labelledby="hr-copy-title"
           onKeyDown={e => { if (e.key === 'Escape') onClose() }}
           style={{ width: '100%', maxWidth: 560, background: 'var(--color-card)', color: 'var(--color-text)',
                    border: '1px solid var(--color-border)', borderRadius: 10, boxShadow: '0 16px 40px rgba(13,20,36,.3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 12px 12px 20px',
                      borderBottom: '1px solid var(--color-border)' }}>
          <h2 id="hr-copy-title" style={{ margin: 0, flex: 1, fontSize: 18, fontWeight: 800, color: 'var(--color-heading)' }}>
            Zgłoszenie wysłane
          </h2>
          <button type="button" aria-label="Zamknij" onClick={onClose}
                  style={{ width: 44, height: 44, display: 'grid', placeItems: 'center', border: 0,
                           background: 'transparent', color: 'var(--color-text-muted)', cursor: 'pointer' }}>
            <X size={18} />
          </button>
        </div>
        <div style={{ padding: '16px 20px' }}>
          <p style={{ margin: '0 0 10px', fontSize: 14 }}>
            Możesz przekazać tę informację kierownikowi komórki lub nowemu pracownikowi:
          </p>
          <textarea readOnly value={text} rows={8} className="form-control" aria-label="Treść wiadomości"
                    onFocus={e => e.target.select()}
                    style={{ width: '100%', boxSizing: 'border-box', fontSize: 13, lineHeight: 1.5 }} />
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, padding: '0 20px 18px' }}>
          <button type="button" className="btn btn--ghost" onClick={onClose}>Zamknij</button>
          <button type="button" className="btn btn--action" autoFocus onClick={copy}>
            <Copy size={15} aria-hidden="true" /> Kopiuj
          </button>
        </div>
      </div>
    </div>
  )
}

export default function HR() {
  const [requests, setRequests] = useState([])
  const [loading, setLoading]   = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [showTermination, setShowTermination] = useState(false)
  const [view, setView]         = useState('all')    // open | done | all
  const [created, setCreated]   = useState(null)     // dane do wiadomości po zgłoszeniu
  const [q, setQ]               = useState('')

  async function load() {
    setLoading(true)
    try {
      // scope=mine — wyłącznie zgłoszenia tej osoby (bez tego osoba z dodatkową
      // rolą IT/admin/kierownik dostawała pod „Moje zgłoszenia” cudze wnioski).
      const r = await listRequests({ scope: 'mine' })
      setRequests(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const DONE = ['completed', 'rejected']
  const counts = {
    open: requests.filter(r => !DONE.includes(r.status)).length,
    done: requests.filter(r => DONE.includes(r.status)).length,
    all: requests.length,
  }
  const shown = requests
    .filter(r => view === 'all' || (view === 'done') === DONE.includes(r.status))
    .filter(r => !q.trim() || (r.worker_name || '').toLowerCase().includes(q.trim().toLowerCase()))

  // Formularze jako PEŁNOEKRANOWE widoki (nie małe modale) — spójny układ.
  if (showForm) {
    return <RequestFormView onCancel={() => setShowForm(false)}
                            onCreated={(info) => { setShowForm(false); setCreated(info || null); load() }} />
  }
  if (showTermination) {
    return <TerminationFormView onCancel={() => setShowTermination(false)}
                                onCreated={() => { setShowTermination(false); load() }} />
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Kartoteka</div>
          <div className="page-header__sub">Zgłoś zatrudnienie nowego pracownika lub ustanie stosunku pracy</div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          <button className="btn btn--action" style={{ minHeight: 44, fontSize: 14 }} onClick={() => setShowForm(true)}>
            <FilePlus size={16} />
            Nowy pracownik
          </button>
          <button className="btn btn--ghost" style={{ minHeight: 44, fontSize: 14, background: 'var(--color-card)' }}
                  onClick={() => setShowTermination(true)}>
            <UserMinus size={16} />
            Ustanie stosunku pracy
          </button>
        </div>
      </div>

      <section aria-label="Moje zgłoszenia" className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12,
                      padding: '14px 18px', borderBottom: '1px solid var(--color-border)' }}>
          <h2 style={{ margin: 0, flex: '1 1 200px', fontSize: 16, fontWeight: 800, color: 'var(--color-heading)' }}>
            Moje zgłoszenia
          </h2>
          <div role="group" aria-label="Filtr statusu" style={{
            display: 'inline-flex', padding: 3, borderRadius: 8,
            background: 'var(--bg-secondary)', border: '1px solid var(--color-border)',
          }}>
            {[['open', 'W toku'], ['done', 'Zakończone'], ['all', 'Wszystkie']].map(([id, label]) => (
              <button key={id} type="button" aria-pressed={view === id} onClick={() => setView(id)}
                      style={{
                        minHeight: 36, padding: '0 14px', border: 0, borderRadius: 6, cursor: 'pointer',
                        font: 'inherit', fontSize: 13, fontWeight: view === id ? 700 : 600,
                        background: view === id ? 'var(--color-navy)' : 'transparent',
                        color: view === id ? '#fff' : 'var(--color-heading)',
                      }}>
                {label} ({counts[id]})
              </button>
            ))}
          </div>
          <label style={{ position: 'relative', display: 'block', flex: '0 1 280px' }}>
            <span className="sr-only" style={{ position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)' }}>
              Szukaj pracownika
            </span>
            <Search size={15} aria-hidden="true" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
            <input type="search" className="form-input" style={{ minHeight: 44, paddingLeft: 36 }}
                   placeholder="Szukaj pracownika…" value={q} onChange={e => setQ(e.target.value)} />
          </label>
        </div>
        {loading ? (
          <div style={{ padding: '20px 18px', color: 'var(--color-text-muted)' }}>Ładowanie…</div>
        ) : shown.length === 0 ? (
          <div style={{ padding: '20px 18px', fontSize: 14, color: 'var(--color-text-muted)' }}>Brak zgłoszeń</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table" style={{ minWidth: 760 }}>
              <thead>
                <tr>
                  <th>#</th><th>Pracownik</th><th>Rodzaj</th><th>Stanowisko</th><th>Status</th><th>Data</th>
                </tr>
              </thead>
              <tbody>
                {shown.map(r => {
                  const kind = r.kind || 'grant'
                  return (
                    <tr key={r.id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--color-text-muted)' }}>{r.id}</td>
                      <td style={{ fontWeight: 700 }}>{r.worker_name}</td>
                      <td>
                        <KindBadge kind={kind} label={kindLabel(kind)} />
                      </td>
                      <td style={{ color: 'var(--color-text-muted)' }}>{r.worker_position || '—'}</td>
                      <td>
                        <span className={`badge ${statusBadge(r.status)}`}>{statusLabel(r.status)}</span>
                        {!DONE.includes(r.status) && (r.waiting_for || r.step_since) && (
                          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>
                            Gdzie teraz: {r.waiting_for || '—'}
                            {r.step_since && <> · od {waitText(daysSince(serverTs(r.step_since), serverNow()))}</>}
                          </div>
                        )}
                      </td>
                      <td style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
                        {fmtDate(r.created_at)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {created && <CopyMessageDialog info={created} onClose={() => setCreated(null)} />}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Wspólny layout pełnoekranowego formularza kadrowego (spójny dla obu).
// ---------------------------------------------------------------------------
function HRFormPage({ icon: Icon, title, subtitle, onCancel, onSubmit,
                     submitLabel, busy, canSubmit = true, children }) {
  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {Icon && <Icon size={18} style={{ color: 'var(--color-heading)' }} />}
            {title}
          </div>
          {subtitle && <div className="page-header__sub">{subtitle}</div>}
        </div>
        <button type="button" className="btn btn--ghost" onClick={onCancel}>← Wróć do kartoteki</button>
      </div>
      <form onSubmit={onSubmit} className="card" style={{ maxWidth: 860, margin: '0 auto', width: '100%' }}>
        {children}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 20,
                      borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
          <button type="button" className="btn btn--ghost" onClick={onCancel}>Anuluj</button>
          <button type="submit" className="btn btn--action" disabled={busy || !canSubmit}>
            {busy ? 'Zapisywanie…' : submitLabel}
          </button>
        </div>
      </form>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Formularz: imię, nazwisko, stanowisko, wydział (picker harmonijkowy)
// ---------------------------------------------------------------------------

function RequestFormView({ onCancel, onCreated }) {
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
      const res = await createRequest({
        worker_name:     workerName,
        worker_position: position.trim(),
        employment_from: startDate || null,
        unit_id:         selectedDept.unit_id,
        department_id:   selectedDept.id,
        items:           [],
        request_type_id: requestTypeId || null,
      })
      toast(`Wysłano zgłoszenie zatrudnienia: ${workerName}. Trafi teraz do kierownika komórki.`)
      onCreated({
        id: res?.data?.id, name: workerName, position: position.trim(),
        dept: `${selectedUnit?.name ? selectedUnit.name + ' › ' : ''}${selectedDept.name}`
              + (selectedDept.description ? ` (${selectedDept.description})` : ''),
        from: startDate,
      })
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd zapisu zgłoszenia')
      setBusy(false)
    }
  }

  const workerName = `${firstName.trim()} ${lastName.trim()}`.trim()
  const steps = buildWorkflowSteps({
    sent: false, kind: 'grant',
    requiresHigher: !!selectedDept?.requires_higher_approval,
  })
  const summary = [
    { label: 'Pracownik', value: workerName || '—' },
    { label: 'Stanowisko', value: position.trim() || '—' },
    { label: 'Komórka', value: selectedDept ? `${selectedUnit?.name || '?'} · ${selectedDept.name}` : '—' },
    { label: 'Od dnia', value: startDate || '—' },
  ]

  return (
    <RequestViewShell icon={FilePlus} kind="grant" kindLabel="Zatrudnienie"
                      statusText="Nowy wniosek · nie wysłany" title="Nowy pracownik"
                      subtitle="Zgłoszenie zatrudnienia — po wysłaniu trafi do kierownika komórki, a potem do IT."
                      backLabel="← Wróć do kartoteki" onBack={onCancel}
                      steps={steps} summary={summary} history={[]}
                      footerLeft="* pola wymagane"
                      footerActions={<>
                        <button type="button" className="btn btn--ghost" onClick={onCancel}>Anuluj</button>
                        <button type="button" className="btn btn--action" onClick={submit} disabled={busy}>
                          {busy ? 'Zapisywanie…' : 'Wyślij do kierownika →'}
                        </button>
                      </>}>
      <Section n={1} title="Dane pracownika">
        <div style={FIELD_GRID}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="hr-first">Imię *</label>
            <input id="hr-first" className="form-control" style={FIELD_INPUT} required autoFocus
                   value={firstName} onChange={e => setFirstName(e.target.value)} />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="hr-last">Nazwisko *</label>
            <input id="hr-last" className="form-control" style={FIELD_INPUT} required
                   value={lastName} onChange={e => setLastName(e.target.value)} />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="hr-pos">Stanowisko *</label>
            <input id="hr-pos" className="form-control" style={FIELD_INPUT} required value={position}
                   onChange={e => setPosition(e.target.value)}
                   placeholder="np. Podinspektor" />
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="hr-from">Data zatrudnienia od</label>
            <input id="hr-from" className="form-control" style={FIELD_INPUT} type="date" value={startDate}
                   onChange={e => setStartDate(e.target.value)} />
          </div>
        </div>
      </Section>

      <Section n={2} title="Miejsce pracy *">
        <div className="form-label">Komórka organizacyjna *</div>
        <DeptSearchSelect units={units} depts={depts} value={deptId} onChange={setDeptId} />
        <div style={NOTE_BOX}>
          <Info size={16} aria-hidden="true" style={{ flexShrink: 0, marginTop: 1 }} />
          <span>
            Wniosek trafi do kierownika wybranej komórki
            {selectedDept?.manager_name
              ? <>: <strong style={{ color: 'var(--color-text)' }}>{selectedDept.manager_name}</strong></>
              : ''}
            . Uprawnienia wskaże on, nie kadry.
          </span>
        </div>
      </Section>

      <NextSteps />

      {err && <div className="alert alert--error mt-4">{err}</div>}
    </RequestViewShell>
  )
}


// ---------------------------------------------------------------------------
// Formularz: ustanie stosunku pracy — wybór komórki → pracownik z listy
// ---------------------------------------------------------------------------

function TerminationFormView({ onCancel, onCreated }) {
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
        ? (() => {
            // Pracownik może siedzieć w podkomórce wybranego węzła — zapisz jego
            // RZECZYWISTĄ komórkę, nie zaznaczony węzeł nadrzędny.
            const realDept = depts.find(d => d.id === selectedWorker.department_id) || selectedDept
            const realUnit = units.find(u => u.id === realDept.unit_id) || selectedUnit
            return { id: selectedWorker.id, name: selectedWorker.full_name || selectedWorker.username,
                     unit_id: realDept.unit_id, department_id: realDept.id,
                     unit_name: realUnit?.name, department_name: realDept.name }
          })()
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
      toast(`Wysłano zgłoszenie odejścia: ${effWorker.name}. Trafi teraz do kierownika komórki.`)
      onCreated()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd zapisu zgłoszenia')
      setBusy(false)
    }
  }

  const summary = [
    { label: 'Pracownik', value: effWorker?.name || '—' },
    { label: 'Komórka', value: effWorker ? `${effWorker.unit_name || '?'} · ${effWorker.department_name || '—'}` : '—' },
    { label: 'Ostatni dzień', value: workUntil || '—' },
  ]
  const steps = buildWorkflowSteps({
    sent: false, kind: 'revoke',
    requiresHigher: !!selectedDept?.requires_higher_approval,
  })

  return (
    <RequestViewShell icon={UserMinus} kind="revoke" kindLabel="Odejście"
                      statusText="Nowy wniosek · nie wysłany" title="Ustanie stosunku pracy"
                      subtitle="Zgłoszenie odejścia — trafi do kierownika komórki, potem do IT."
                      backLabel="← Wróć do kartoteki" onBack={onCancel}
                      steps={steps} summary={summary} history={[]}
                      footerLeft="* pola wymagane"
                      footerActions={<>
                        <button type="button" className="btn btn--ghost" onClick={onCancel}>Anuluj</button>
                        <button type="button" className="btn btn--action" onClick={submit} disabled={busy || !effWorker}>
                          {busy ? 'Zapisywanie…' : 'Wyślij do kierownika →'}
                        </button>
                      </>}>
      <Section n={1} title="Pracownik">
          {/* Wyszukiwanie po nazwisku — najszybsza droga. */}
          <div className="form-group">
            <label className="form-label" htmlFor="hr-term-search">Znajdź po nazwisku lub loginie</label>
            {picked ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                            minHeight: 52, padding: '6px 12px', border: '2px solid var(--color-navy)',
                            background: 'var(--bg-secondary)', borderRadius: 8 }}>
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
                <div style={{ position: 'relative' }}>
                  <Search size={15} aria-hidden="true" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
                  <input id="hr-term-search" type="search" className="form-control" value={search} autoFocus
                         style={{ ...FIELD_INPUT, paddingLeft: 36 }}
                         placeholder="Wpisz co najmniej 2 znaki nazwiska…"
                         onChange={e => setSearch(e.target.value)} />
                </div>
                {searching && <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>Szukam…</div>}
                {results.length > 0 && (
                  <div style={{ border: '1px solid var(--color-input-border)', borderRadius: 8, marginTop: 6, padding: 4,
                                maxHeight: 240, overflowY: 'auto', background: 'var(--color-card)',
                                boxShadow: '0 6px 18px rgba(27, 42, 74, .08)' }}>
                    {results.map(r => (
                      <div key={r.id} onClick={() => pickFromSearch(r)}
                           style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer',
                                    minHeight: 44, padding: '0 12px', borderRadius: 6, fontSize: 14 }}
                           onMouseEnter={e => e.currentTarget.style.background = 'var(--bg-hover, rgba(0,0,0,0.04))'}
                           onMouseLeave={e => e.currentTarget.style.background = 'transparent'}>
                        <span style={{ fontWeight: 700, color: 'var(--color-heading)' }}>{r.full_name || r.username}</span>
                        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                          {[r.title, r.username].filter(Boolean).join(' · ')}
                        </span>
                        <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--color-text-muted)' }}>
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

          {/* Alternatywnie: dwukolumnowy wybór ze struktury (jak w projekcie):
              lewa kolumna — drzewo komórek, prawa — pracownicy jako karty. */}
          {!picked && (
            <>
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '16px 0 12px' }}>
                <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
                <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--color-text-muted)', textTransform: 'uppercase', letterSpacing: '.08em' }}>
                  albo wybierz ze struktury
                </span>
                <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
              </div>

              <div style={{
                display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                gap: 0, border: '1px solid var(--color-input-border)', borderRadius: 8, overflow: 'hidden',
              }}>
                {/* Lewa kolumna — drzewo komórek */}
                <div style={{ borderRight: '1px solid var(--color-border)', minWidth: 0 }}>
                  <div style={{
                    fontSize: 11, fontWeight: 700, letterSpacing: '.08em', color: 'var(--color-text-muted)',
                    padding: '9px 14px', borderBottom: '1px solid var(--color-border)',
                    background: 'var(--color-table-head)',
                  }}>
                    KOMÓRKA
                  </div>
                  <div style={{ maxHeight: 340, overflowY: 'auto' }}>
                    <DepartmentPicker units={units} depts={depts} selectedId={deptId}
                                      onSelect={setDeptId} flush />
                  </div>
                </div>

                {/* Prawa kolumna — pracownicy wybranej komórki */}
                <div style={{ minWidth: 0 }}>
                  <div style={{
                    fontSize: 11, fontWeight: 700, letterSpacing: '.08em', color: 'var(--color-text-muted)',
                    padding: '9px 14px', borderBottom: '1px solid var(--color-border)',
                    background: 'var(--color-table-head)',
                    whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                  }}>
                    PRACOWNICY{selectedDept
                      ? ` · ${selectedUnit?.name ? selectedUnit.name + ' › ' : ''}${selectedDept.name}`
                      : ''}
                  </div>
                  <div style={{ maxHeight: 360, overflowY: 'auto', padding: 10 }}>
                    {!deptId ? (
                      <div style={{ fontSize: 12, color: 'var(--color-text-muted)', padding: '8px 4px' }}>
                        Wybierz komórkę po lewej, aby zobaczyć pracowników.
                      </div>
                    ) : loadingWorkers ? (
                      <div style={{ fontSize: 12, color: 'var(--color-text-muted)', padding: '8px 4px' }}>Ładowanie pracowników…</div>
                    ) : workers.length === 0 ? (
                      <div className="alert alert--warning" style={{ fontSize: 12 }}>
                        Brak aktywnych pracowników przypisanych do tej komórki.
                      </div>
                    ) : (
                      <div role="radiogroup" aria-label="Wybierz pracownika" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                        {workers.map(w => {
                          const sel = workerId === w.id
                          return (
                            <label key={w.id} style={{
                              display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer',
                              minHeight: 52, padding: '6px 12px', borderRadius: 8, fontSize: 14,
                              boxSizing: 'border-box',
                              border: sel ? '2px solid var(--color-navy)' : '1px solid var(--color-input-border)',
                              background: sel ? 'var(--bg-secondary)' : 'var(--color-card)',
                            }}>
                              <input type="radio" name="term-worker" checked={sel}
                                     style={{ flexShrink: 0, width: 18, height: 18, margin: 0, accentColor: 'var(--color-navy)' }}
                                     onChange={() => setWorkerId(w.id)} />
                              <span style={{ minWidth: 0 }}>
                                <span style={{ display: 'block', fontWeight: 700, color: 'var(--color-heading)' }}>
                                  {w.full_name || w.username}
                                </span>
                                <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)',
                                               whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                  {/* wg makiety: „stanowisko · login” (+ podkomórka, gdy inna niż wybrana) */}
                                  {[w.title, w.username].filter(Boolean).join(' · ') || '—'}
                                  {w.department_name && w.department_name !== selectedDept?.name
                                    ? ` · ${w.department_name}` : ''}
                                </span>
                              </span>
                            </label>
                          )
                        })}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}

      </Section>

      <Section n={2} title="Termin">
          <div style={{ ...FIELD_GRID, gap: 16, alignItems: 'end' }}>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label" htmlFor="hr-until">Ostatni dzień pracy *</label>
              <input id="hr-until" className="form-control" type="date" style={FIELD_INPUT}
                     value={workUntil} onChange={e => setWorkUntil(e.target.value)} />
            </div>
            <div style={{ ...NOTE_BOX, marginTop: 0, alignItems: 'center', minHeight: 44, padding: '0 14px', boxSizing: 'border-box' }}>
              <Lock size={15} aria-hidden="true" style={{ flexShrink: 0 }} />
              Blokada dostępów od następnego dnia.
            </div>
          </div>

          {err && <div className="alert alert--error mt-4">{err}</div>}
      </Section>

      <NextSteps revoke />
    </RequestViewShell>
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
      // Dopasowanie po ŚCIEŻCE (nazwa + jednostka) ORAZ po OPISIE z AD.
      .filter(x => !q || x.path.toLowerCase().includes(q)
                   || (x.d.description || '').toLowerCase().includes(q))
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
        minHeight: 44, padding: '4px 6px 4px 12px', borderRadius: 8, boxSizing: 'border-box',
        background: 'var(--color-success-bg)', border: '1px solid var(--color-success)', fontSize: 14,
      }}>
        <Check size={14} style={{ color: 'var(--color-success)' }} />
        <span>{pathStr(selected)}</span>
        <button type="button" className="btn btn--ghost btn--sm" style={{ marginLeft: 'auto' }}
                onClick={() => { setOpen(true); setQuery('') }}>Zmień</button>
      </div>
    )
  }

  return (
    <div ref={wrapRef}>
      <div style={{ position: 'relative' }}>
        <Search size={15} aria-hidden="true" style={{
          position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)',
          color: 'var(--color-text-muted)', pointerEvents: 'none',
        }} />
        <input type="search" className="form-control" value={query} aria-label="Komórka organizacyjna"
               style={{ ...FIELD_INPUT, paddingLeft: 36,
                        ...(open ? { border: '2px solid var(--color-navy)' } : {}) }}
               placeholder="Wpisz fragment nazwy komórki lub jednostki…"
               onFocus={() => setOpen(true)} onChange={e => { setQuery(e.target.value); setOpen(true) }} />
      </div>
      {open && (
        <div role="listbox" aria-label="Pasujące komórki" style={{
          marginTop: 6, padding: 4,
          border: '1px solid var(--color-input-border)', borderRadius: 8, background: 'var(--color-card)',
          maxHeight: 280, overflowY: 'auto', boxShadow: '0 6px 18px rgba(27, 42, 74, .08)',
        }}>
          {matches.length === 0 ? (
            <div style={{ padding: 12, fontSize: 13, color: 'var(--color-text-muted)' }}>
              Brak komórek pasujących do „{query}".
            </div>
          ) : matches.map(({ d, path }) => {
            const isSel = d.id === value
            return (
              <div key={d.id} role="option" aria-selected={isSel}
                   onClick={() => { onChange(d.id); setOpen(false); setQuery('') }}
                   style={{
                     display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer',
                     minHeight: 44, padding: '0 12px', fontSize: 14, borderRadius: 6,
                     background: isSel ? 'var(--bg-secondary)' : 'transparent',
                   }}
                   onMouseEnter={e => { if (!isSel) e.currentTarget.style.background = 'var(--bg-secondary)' }}
                   onMouseLeave={e => { if (!isSel) e.currentTarget.style.background = 'transparent' }}>
                {/* wg projektu: „KOD · pełna nazwa” + ścieżka (mono) po prawej */}
                <span style={{ flex: 1, minWidth: 0 }}>
                  <strong style={{ color: 'var(--color-heading)' }}>{d.name}</strong>
                  {d.description && <span style={{ color: 'var(--color-text)' }}> · {d.description}</span>}
                </span>
                <span style={{
                  flexShrink: 0, fontSize: 12, fontFamily: 'var(--font-mono, monospace)',
                  color: 'var(--color-text-muted)',
                }}>
                  {path}
                </span>
                {isSel && <Check size={14} style={{ color: 'var(--color-heading)', flexShrink: 0 }} />}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function DepartmentPicker({ units, depts, selectedId, onSelect, flush = false }) {
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
        .filter(x => x.path.toLowerCase().includes(q)
                     || (x.d.description || '').toLowerCase().includes(q))
        .sort((a, b) => a.path.localeCompare(b.path, 'pl'))
        .slice(0, 100)
    : null

  return (
    <div style={flush ? {} : { border: '1px solid var(--color-border)', borderRadius: 8, background: 'var(--bg-secondary)', overflow: 'hidden' }}>
      <div style={{ padding: '10px 10px 4px', background: 'var(--color-card)' }}>
        <input type="search" className="form-control" style={{ minHeight: 40, borderRadius: 8, fontSize: 14 }}
               placeholder="Szukaj komórki…" aria-label="Szukaj komórki"
               value={query} onChange={e => setQuery(e.target.value)} />
      </div>
      <div role="tree" aria-label="Struktura" style={{ padding: '4px 6px 10px',
                    ...(flush ? {} : { maxHeight: 'min(48vh, 420px)', overflowY: 'auto' }) }}>
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
              <div key={d.id} role="treeitem" aria-selected={isSelected} onClick={() => onSelect(d.id)}
                   style={{ ...treeRow(isSelected, false), paddingLeft: 10 }}
                   onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--bg-secondary)' }}
                   onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}>
                <span style={{ flex: 1 }}>{path}</span>
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

// Wiersz drzewa komórek (v3.0, wg projektu): 36 px, zaokrąglony, wybrany = granat.
function treeRow(selected, isUnit) {
  return {
    display: 'flex', alignItems: 'center', gap: 6, minHeight: 36, paddingRight: 10,
    borderRadius: 6, cursor: 'pointer', fontSize: 14, boxSizing: 'border-box',
    background: selected ? 'var(--color-navy)' : 'transparent',
    color: selected ? '#fff' : (isUnit ? 'var(--color-heading)' : 'var(--color-text)'),
    fontWeight: selected || isUnit ? 700 : 400,
  }
}

function UnitNode({ unit, byParent, hasAny, selectedId, onSelect, initiallyOpen, expandedPath }) {
  const [open, setOpen] = useState(initiallyOpen)
  useEffect(() => { if (initiallyOpen) setOpen(true) }, [initiallyOpen])

  const roots = byParent.get(null) || []

  return (
    <div>
      <button
        type="button"
        aria-expanded={hasAny ? open : undefined}
        onClick={() => hasAny && setOpen(v => !v)}
        style={{
          ...treeRow(false, true), width: '100%', paddingLeft: 10,
          border: 'none', textAlign: 'left', font: 'inherit', fontSize: 14, fontWeight: 700,
          cursor: hasAny ? 'pointer' : 'default',
        }}
      >
        {hasAny
          ? (open ? <ChevronDown size={13} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />
                  : <ChevronRight size={13} aria-hidden="true" style={{ color: 'var(--color-text-muted)' }} />)
          : <span style={{ width: 13 }} />}
        <span style={{ flex: 1 }}>{unit.name}</span>
        {!hasAny && <span style={{ fontSize: 12, color: 'var(--color-text-muted)', fontWeight: 400 }}>(brak wydziałów)</span>}
      </button>
      {open && hasAny && (
        <div>
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
        role="treeitem" aria-selected={isSelected}
        onClick={() => onSelect(dept.id)}
        style={{ ...treeRow(isSelected, false), paddingLeft: 10 + depth * 22 }}
        onMouseEnter={e => { if (!isSelected) e.currentTarget.style.background = 'var(--bg-secondary)' }}
        onMouseLeave={e => { if (!isSelected) e.currentTarget.style.background = 'transparent' }}
      >
        {hasKids ? (
          <button
            type="button"
            onClick={e => { e.stopPropagation(); setOpen(v => !v) }}
            style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0, color: isSelected ? '#fff' : 'var(--color-text-muted)', display: 'inline-flex' }}
            aria-label={open ? 'Zwiń' : 'Rozwiń'}
          >
            {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          </button>
        ) : (
          <span style={{ width: 12 }} />
        )}
        <span style={{ flex: 1 }}>{dept.name}</span>
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
