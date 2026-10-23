import { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import Structure from './Structure'
import { Users, RefreshCw, FilePlus, Search, ListChecks, Send, Save, ChevronDown, ChevronRight } from 'lucide-react'
import {
  listMyWorkers, listSystems, listPermissions, createRequest, listRequestTypes, errorMessage,
} from '../api'
import {
  permChangeState, changeStyle, ChangeBadge,
} from '../components/PermissionChanges'
import DeclarationModal, { declarationRequired } from '../components/DeclarationModal'
import RequestViewShell, {
  buildWorkflowSteps, Section, WorkerCard, deptFull, useReturnFocus,
} from '../components/RequestView'
import { toast, confirmDialog } from '../components/ui/feedback'
import { ReviewDialog, describeKeys, diffSelection } from '../components/ChangeSummary'
import CopyFromColleague, { buildCopiedSelection } from '../components/CopyFromColleague'
import PermInput, {
  permInput, missingRequiredFields, splitAdminPerm, AdminPermRow,
  adminGrantNames, confirmAdminRights, ADMIN_CONFIRM_ABORTED,
  groupPerms, subgroupPerms, isPermVisible, PermGroupSection, SystemBlock,
  isScopeGated, missingScopeSystems,
} from '../components/ItemFields'

// Zakładki (wzorzec WAI-ARIA „tabs”): strzałki lewo/prawo, Home/End
// przechodzą między zakładkami i od razu je aktywują.
function onTablistKeyDown(e) {
  const tabs = Array.from(e.currentTarget.querySelectorAll('[role="tab"]'))
  const i = tabs.indexOf(e.target)
  if (i < 0) return
  const next = e.key === 'ArrowRight' ? (i + 1) % tabs.length
    : e.key === 'ArrowLeft' ? (i - 1 + tabs.length) % tabs.length
    : e.key === 'Home' ? 0
    : e.key === 'End' ? tabs.length - 1
    : null
  if (next == null) return
  e.preventDefault()
  tabs[next].focus()
  tabs[next].click()
}

// v3.0 — „Moi pracownicy” ma dwie zakładki: Pracownicy (lista + wnioski)
// oraz Struktura (drzewo komórek w zakresie kierownika).
export default function MyTeam() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'structure' ? 'structure' : 'workers'
  const SUB = {
    workers: 'Pracownicy, którymi kierujesz — możesz dla nich występować o nadanie lub zmianę uprawnień',
    structure: 'Podgląd wydziałów podrzędnych, ich kierowników i pracowników wraz z nadanymi uprawnieniami',
  }
  const renderHeader = (onRefresh, loading) => (
    <>
      <div className="page-header">
        <div>
          <h1 className="page-header__title">Moi pracownicy</h1>
          <div className="page-header__sub">{SUB[tab]}</div>
        </div>
        <button className="btn btn--ghost" onClick={onRefresh} disabled={loading}>
          <RefreshCw size={14} /> Odśwież
        </button>
      </div>
      <div className="tabs" role="tablist" aria-label="Widok" style={{ marginTop: 0 }}
           onKeyDown={onTablistKeyDown}>
        {[['workers', 'Pracownicy'], ['structure', 'Struktura']].map(([id, label]) => (
          <button key={id} role="tab" aria-selected={tab === id} tabIndex={tab === id ? 0 : -1}
                  className={`tab-btn${tab === id ? ' active' : ''}`}
                  onClick={() => setParams(id === 'structure' ? { tab: 'structure' } : {})}>
            {label}
          </button>
        ))}
      </div>
    </>
  )
  return tab === 'structure'
    ? <Structure renderHeader={renderHeader} />
    : <WorkersTab renderHeader={renderHeader} />
}

const NO_TYPE_MSG = 'Brak aktywnego typu wniosku — wysłanie jest zablokowane. Poproś administratora o włączenie typu wniosku.'

function WorkersTab({ renderHeader }) {
  const [workers, setWorkers] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState(null)
  // ?q= — wejście z wyszukiwarki globalnej (Ctrl+K) od razu filtruje listę.
  const [params] = useSearchParams()
  const [search, setSearch]   = useState(() => params.get('q') || '')
  // Ponowne wyszukanie z Ctrl+K, gdy jesteśmy już na tej stronie.
  useEffect(() => { const q = params.get('q'); if (q != null) setSearch(q) }, [params])
  const [requestFor, setRequestFor] = useState(null)
  const [expanded, setExpanded] = useState(() => new Set())

  function toggleExpand(id) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  async function load() {
    setLoading(true); setErr(null)
    try {
      const r = await listMyWorkers()
      setWorkers(r.data)
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się pobrać listy pracowników'))
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return workers
    return workers.filter(w =>
      [w.full_name, w.username, w.email, w.department_name, w.department_description, w.unit_name]
        .some(v => (v || '').toLowerCase().includes(q))
    )
  }, [workers, search])

  // Po zamknięciu formularza fokus wraca na „Nowy wniosek” w wierszu pracownika.
  useReturnFocus(requestFor ? requestFor.id : null, !loading)

  // Otwarty formularz wniosku = pełnoekranowy widok (zamiast listy).
  if (requestFor) {
    return <NewRequestModal worker={requestFor}
                            onClose={() => setRequestFor(null)}
                            onDone={() => { setRequestFor(null); load() }} />
  }

  return (
    <div>
      {renderHeader(load, loading)}

      {err && <div className="alert alert--error mb-4">{err}</div>}

      {/* v3.0: wyszukiwarka w nagłówku karty listy (wg projektu). */}
      <section aria-label="Pracownicy" className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--color-border)' }}>
          <div style={{ position: 'relative', maxWidth: 420 }}>
            <Search size={15} aria-hidden="true" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
            <input
              type="search"
              className="form-input"
              aria-label="Szukaj pracownika"
              style={{ paddingLeft: 36, minHeight: 44, borderRadius: 8, fontSize: 14 }}
              placeholder="Szukaj: imię, login, e-mail, wydział…"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
        </div>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 18 }}>Ładowanie…</div>
        ) : workers.length === 0 ? (
          <div style={{ padding: 18 }}>
            <div style={{ fontWeight: 700 }}>
              <Users size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} aria-hidden="true" />
              Brak pracowników w Twoim zakresie.
            </div>
            <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 4 }}>
              Poproś administratora o przypisanie Cię jako kierownika komórki w „Jednostkach”
              albo o przypisanie pracowników do Twojej komórki.
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 18 }}>
            <Search size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} aria-hidden="true" />
            Brak wyników dla „{search}”. Spróbuj nazwiska, loginu albo nazwy komórki.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ minWidth: 1000 }}>
            <thead>
              <tr>
                <th>Imię i nazwisko</th>
                <th>Login</th>
                <th>E-mail</th>
                <th>Wydział</th>
                <th>Jednostka</th>
                <th>Posiadane uprawnienia</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(w => {
                const perms = w.permissions || []
                const open  = expanded.has(w.id)
                return [
                  <tr key={w.id} style={w.is_self ? { background: 'var(--bg-secondary)' } : undefined}>
                    <td style={{ fontWeight: 700 }}>
                      {w.full_name || '—'}
                      {w.is_self && (
                        <span title="Możesz złożyć wniosek sam dla siebie" style={{
                          marginLeft: 8, padding: '1px 7px', borderRadius: 4, fontSize: 11, fontWeight: 800,
                          background: 'var(--color-info-bg)', color: 'var(--color-info-text)',
                        }}>
                          Ja
                        </span>
                      )}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--color-text-muted)' }}>{w.username}</td>
                    <td style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>{w.email || '—'}</td>
                    <td>{deptFull(w.department_name, w.department_description)}</td>
                    <td style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>{w.unit_name || '—'}</td>
                    <td>
                      {perms.length === 0 ? (
                        <span style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>brak</span>
                      ) : (
                        <button
                          type="button"
                          className="btn btn--ghost btn--sm"
                          aria-expanded={open}
                          style={{ minHeight: 36, fontSize: 13 }}
                          onClick={() => toggleExpand(w.id)}
                          title={open ? 'Zwiń' : 'Pokaż uprawnienia'}
                        >
                          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                          Uprawnienia
                          <span className="tab-count">{perms.length}</span>
                        </button>
                      )}
                    </td>
                    <td style={{ textAlign: 'right' }}>
                      <button className="btn btn--action btn--sm" style={{ minHeight: 36 }} onClick={() => setRequestFor(w)}
                              data-return-focus={w.id}>
                        <FilePlus size={13} /> Nowy wniosek
                      </button>
                    </td>
                  </tr>,
                  open && perms.length > 0 && (
                    <tr key={`${w.id}-perms`}>
                      <td colSpan={7}>
                        <div style={{ padding: '4px 0 6px' }}>
                          <div className="form-label" style={{ marginBottom: 6 }}>
                            Aktualnie posiadane uprawnienia
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                            {perms.map(p => (
                              <span key={`${p.system_id}:${p.permission_id}`}
                                    style={{
                                      fontSize: 13, padding: '4px 10px',
                                      border: '1px solid var(--color-border)',
                                      borderRadius: 6,
                                      background: 'var(--bg-secondary)',
                                    }}>
                                <strong style={{ color: 'var(--color-heading)' }}>{p.system_name}</strong>
                                <span style={{ color: 'var(--color-text-muted)' }}> › </span>
                                {p.permission_name}
                              </span>
                            ))}
                          </div>
                        </div>
                      </td>
                    </tr>
                  ),
                ]
              })}
            </tbody>
          </table>
          </div>
        )}
      </section>
    </div>
  )
}


function NewRequestModal({ worker: w, onClose, onDone }) {
  // Uprawnienia, które pracownik już posiada — wstępnie zaznaczone
  // (wniosek o zmianę = modyfikacja obecnego stanu).
  const held = useMemo(
    () => new Set((w.permissions || []).map(p => `${p.system_id}:${p.permission_id}`)),
    [w.permissions]
  )
  const [systems, setSystems]       = useState([])
  const [permsBySys, setPermsBySys] = useState({})
  const [picked, setPicked]         = useState(() => new Set(held))
  // Uprawnienia wpisywane przez wnioskodawcę: "sid:pid" → { pole: wartość }
  const [fieldValues, setFieldValues] = useState({})
  // Zakres, który pracownik ma OBECNIE — by wykryć zmianę samego zakresu.
  const [heldValues, setHeldValues] = useState({})
  const [comment, setComment]       = useState('')
  const [busy, setBusy]             = useState(false)
  const [err, setErr]               = useState(null)
  const [loading, setLoading]       = useState(true)
  // Migawka zaznaczenia po załadowaniu — do ostrzeżenia o niezapisanych zmianach.
  const initialSel = useRef(null)
  const selKey = () => JSON.stringify([[...picked].sort(), fieldValues])
  useEffect(() => { if (!loading) initialSel.current = selKey() }, [loading])
  const [requestTypeId, setRequestTypeId] = useState(null)
  // Oświadczenie wnioskującego (428-driven): treść + pozycje do ponowienia.
  const [declText, setDeclText] = useState('')
  const [declItems, setDeclItems] = useState(null)

  useEffect(() => {
    (async () => {
      try {
        // Systemy przefiltrowane po jednostce pracownika — backend zwróci
        // tylko te oznaczone jako „wszystkie jednostki" lub przypisane do tej
        // konkretnej jednostki.
        const [sys, types] = await Promise.all([
          listSystems({ unit_id: w.unit_id, active_only: true }),
          listRequestTypes({ is_active: true }),
        ])
        const active = sys.data
        setSystems(active)
        const byId = {}
        const results = await Promise.all(active.map(s => listPermissions(s.id)))
        results.forEach((res, i) => { byId[active[i].id] = res.data })
        setPermsBySys(byId)

        // Programy oznaczone „domyślnie zaznaczone" — dokładamy te pozycje,
        // których pracownik jeszcze nie ma. Kierownik może je odznaczyć.
        const defaults = []
        for (const s of active.filter(x => x.default_checked)) {
          for (const p of (byId[s.id] || [])) {
            // Uprawnienia administracyjne NIGDY nie są zaznaczane z automatu —
            // muszą być zawsze świadomą decyzją wnioskodawcy.
            if (p.is_admin_option) continue
            const key = `${s.id}:${p.id}`
            if (!held.has(key)) defaults.push(key)
          }
        }
        if (defaults.length) {
          setPicked(prev => {
            const n = new Set(prev)
            defaults.forEach(k => n.add(k))
            return n
          })
        }

        // Pola wpisywane przez wnioskodawcę: najpierw wartości domyślne
        // z definicji oprogramowania, potem OBECNY zakres pracownika.
        const fv = {}
        const hv = {}
        for (const p of (w.permissions || [])) {
          const k = `${p.system_id}:${p.permission_id}`
          if (p.custom_values && Object.keys(p.custom_values).length) {
            hv[k] = { ...p.custom_values }
            fv[k] = { ...(fv[k] || {}), ...p.custom_values }
          }
        }
        setHeldValues(hv)
        setFieldValues(fv)
        // Wniosek o zmianę uprawnień → typ MODIFY (fallback: pierwszy aktywny).
        const t = types.data.find(x => x.code === 'MODIFY') || types.data[0]
        if (t) setRequestTypeId(t.id)
      } catch (ex) {
        setErr(errorMessage(ex, 'Nie udało się pobrać listy uprawnień'))
      } finally {
        setLoading(false)
      }
    })()
  }, [w.unit_id])

  // Stan docelowy → dyf względem tego, co pracownik ma obecnie (wspólny helper).
  const { toGrant, toRevoke, scopeChanged } = useMemo(
    () => diffSelection(picked, held, permsBySys, fieldValues, heldValues),
    [picked, held, permsBySys, fieldValues, heldValues])

  const noChange = toGrant.length === 0 && toRevoke.length === 0 && scopeChanged.length === 0

  function togglePerm(systemId, permId) {
    const key = `${systemId}:${permId}`
    setPicked(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  // Programy „scope-gated" aktywowane przez wnioskodawcę (zaznaczony sam program).
  const [openSys, setOpenSys] = useState(() => new Set())
  function toggleScope(s) {
    const sid = s.id
    const perms = permsBySys[sid] || []
    const active = openSys.has(sid) || perms.some(p => picked.has(`${sid}:${p.id}`))
    if (active) {
      setPicked(prev => {
        const next = new Set(prev)
        perms.forEach(p => next.delete(`${sid}:${p.id}`))
        return next
      })
      setOpenSys(prev => { const n = new Set(prev); n.delete(sid); return n })
    } else {
      setOpenSys(prev => { const n = new Set(prev); n.add(sid); return n })
    }
  }

  // Szukajka per grupa uprawnień: klucz „system_id|grupa" → fraza.
  const [groupQuery, setGroupQuery] = useState({})

  /** Zaznacz/odznacz hurtem widoczne pozycje grupy (przy setkach uprawnień). */
  function toggleMany(keys) {
    if (keys.length === 0) return
    setPicked(prev => {
      const next = new Set(prev)
      const allOn = keys.every(k => next.has(k))
      keys.forEach(k => (allOn ? next.delete(k) : next.add(k)))
      return next
    })
  }

  function setFieldValue(key, label, val) {
    setFieldValues(prev => ({ ...prev, [key]: { ...(prev[key] || {}), [label]: val } }))
  }

  // Wspólny język zmian (ten sam co u kierownika i w IT).
  const permState  = (key) => permChangeState(key, held, picked)
  const stateStyle = changeStyle

  // „Anuluj” / „Wróć” — pytamy tylko, gdy coś zmieniono względem stanu po załadowaniu.
  async function guardedClose() {
    const dirty = comment.trim() !== ''
      || (initialSel.current != null && initialSel.current !== selKey())
    if (dirty && !(await confirmDialog({
      title: 'Porzucić zmiany?',
      message: 'Zaznaczone uprawnienia i komentarz nie zostały wysłane i zostaną utracone.',
      confirmLabel: 'Porzuć zmiany', danger: true,
    }))) return
    onClose()
  }

  async function submit() {
    // Bez typu wniosku backend odrzuca zgłoszenie (400) — nie wysyłamy.
    if (!requestTypeId) { setErr(NO_TYPE_MSG); return }
    if (noChange) {
      setErr('Nic nie zmieniono — zaznacz nowe uprawnienia lub odznacz te do odebrania')
      return
    }
    // Pola obowiązkowe muszą być wypełnione (backend waliduje to samo).
    const miss = missingRequiredFields([...toGrant, ...scopeChanged], systems,
                                       fieldValues, permsBySys)
    if (miss.length) {
      setErr('Uzupełnij pola obowiązkowe: ' + miss.join('; '))
      return
    }
    // Nadanie uprawnień administracyjnych wymaga twardego potwierdzenia.
    // Sprawdzamy PRZED `setBusy`, bo `prompt` blokuje interfejs.
    const noScope = missingScopeSystems(systems, openSys, picked, permsBySys)
    if (noScope.length) {
      setErr('Zaznaczono program bez wybranego zakresu uprawnień: '
             + noScope.join(', ') + '. Wybierz co najmniej jedno uprawnienie albo odznacz program.')
      return
    }
    // v3.1 — najpierw krok PODSUMOWANIA; wysłanie dopiero z okna.
    setErr(null)
    setReviewOpen(true)
  }

  const [reviewOpen, setReviewOpen] = useState(false)
  async function confirmFromReview() {
    // Nadanie uprawnień administracyjnych wymaga twardego potwierdzenia.
    const admins = adminGrantNames([...toGrant, ...scopeChanged], systems, permsBySys)
    if (!(await confirmAdminRights(admins))) { setErr(ADMIN_CONFIRM_ABORTED); setReviewOpen(false); return }

    setBusy(true); setErr(null)
    await sendRequest(selectionItems())
  }

  // Pozycje wniosku ze stanu docelowego: zaznaczone-nowe → nadanie,
  // odznaczone-posiadane → odebranie, posiadane ze zmienionym zakresem →
  // ponowne nadanie z nowym zakresem.
  function selectionItems() {
    const mk = (k, kind) => {
      const [sid, pid] = k.split(':').map(Number)
      const item = { system_id: sid, permission_id: pid, kind }
      if (kind === 'grant') {
        const vals = fieldValues[k]
        if (vals && Object.keys(vals).length) item.custom_values = vals
      }
      return item
    }
    return [
      ...toGrant.map(k => mk(k, 'grant')),
      ...scopeChanged.map(k => mk(k, 'grant')),
      ...toRevoke.map(k => mk(k, 'revoke')),
    ]
  }

  // Wspólna treść zgłoszenia (wysłanie i wersja robocza).
  function requestBody(items) {
    return {
      kind:            'change',
      worker_name:     w.full_name || w.username,
      worker_email:    w.email || null,
      worker_position: null,
      worker_user_id:  w.id,
      unit_id:         w.unit_id,
      department_id:   w.department_id,
      items,
      request_type_id: requestTypeId,
    }
  }

  // „Zapisz roboczy" — zapis bez wysyłania: bez podsumowania i bez oświadczenia
  // (to zbierane jest dopiero przy wysłaniu). Wniosek czeka w „Do obsługi”.
  async function saveDraft() {
    if (!requestTypeId) { setErr(NO_TYPE_MSG); return }
    setBusy(true); setErr(null)
    try {
      const res = await createRequest({ ...requestBody(selectionItems()), draft: true })
      toast(res?.data?.id ? `Zapisano wersję roboczą wniosku #${res.data.id}.` : 'Zapisano wersję roboczą wniosku.')
      onDone()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się zapisać wersji roboczej'))
      setBusy(false)
    }
  }

  // Wyślij wniosek; `declaration` dokładane po zebraniu w modalu. W 1-stopniu
  // auto-select ląduje wprost na IT — backend zażąda oświadczenia (428), wtedy
  // pokazujemy modal i ponawiamy z podpisem.
  async function sendRequest(items, declaration = null) {
    const body = requestBody(items)
    if (declaration) body.declaration = declaration
    try {
      const res = await createRequest(body)
      setReviewOpen(false)
      toast(`Wniosek${res?.data?.id ? ` #${res.data.id}` : ''} dla ${w.full_name || w.username} został wysłany.`)
      onDone()
    } catch (ex) {
      setReviewOpen(false)
      const declText428 = declarationRequired(ex)
      if (declText428 != null) {
        setDeclText(declText428)
        setDeclItems(items)
        setBusy(false)
        return
      }
      setErr(errorMessage(ex, 'Nie udało się złożyć wniosku'))
      setBusy(false)
    }
  }

  // Kopiowanie uprawnień od współpracownika → nowy stan docelowy.
  function copyFrom(perms) {
    // `held` — odznaczone posiadane to zaplanowane odebrania; kopiowanie ich nie cofa.
    const res = buildCopiedSelection(perms, permsBySys, picked, fieldValues, { held })
    setPicked(res.keys)
    setFieldValues(res.values)
    return { count: res.added, skippedAdmin: res.skippedAdmin,
             skippedUnavailable: res.skippedUnavailable, skippedRevoke: res.skippedRevoke }
  }

  // Dokąd trafi wniosek po wysłaniu — ta sama etykieta na przycisku i w podsumowaniu.
  // Reguła jak w backendzie (landing_node_type): komórka dwustopniowa → akceptacja
  // wyższa dla KAŻDEGO rodzaju wniosku; inaczej wprost do realizacji przez IT.
  const sendLabel = w.requires_higher_approval ? 'Wyślij do akceptacji' : 'Wyślij do realizacji'
  const destText = w.requires_higher_approval
    ? 'do akceptacji kierownika nadrzędnego, a potem do realizacji przez IT'
    : 'bezpośrednio do realizacji przez IT'

  const _steps = buildWorkflowSteps({
    sent: true, nodeType: 'select_permissions',
    requiresHigher: !!w.requires_higher_approval, kind: 'grant',
  })
  const _summary = [
    { label: 'Pracownik', value: w.full_name || w.username },
    { label: 'Komórka', value: `${w.department_name || '—'} · ${w.unit_name || '—'}` },
    { label: 'Zmiany', value: `+${toGrant.length + scopeChanged.length} / −${toRevoke.length}` },
    { label: 'Akceptacja', value: w.requires_higher_approval ? 'wymagana' : 'nie wymagana' },
  ]

  return (
    <>
    <RequestViewShell
      icon={ListChecks} kind="change" kindLabel="Zmiana"
      statusText="Nowy wniosek · nie wysłany"
      title={`Wniosek o uprawnienia — ${w.full_name || w.username}`}
      subtitle={`Zaznacz stan docelowy uprawnień — po wysłaniu wniosek trafi ${destText}.`}
      backLabel="← Wróć do moich pracowników" onBack={guardedClose}
      steps={_steps} summary={_summary} history={[]}
      footerLeft={<><strong style={{ color: 'var(--color-success-text)' }}>+{toGrant.length + scopeChanged.length}</strong> nadania
        {' · '}<strong style={{ color: 'var(--color-error-text)' }}>−{toRevoke.length}</strong> odebrania</>}
      footerActions={<>
        <button className="btn btn--ghost" onClick={guardedClose} disabled={busy}>Anuluj</button>
        <button className="btn btn--ghost" onClick={saveDraft} disabled={busy || loading || noChange || !requestTypeId}
                title={!loading && !requestTypeId ? NO_TYPE_MSG
                  : noChange ? 'Brak zmian do zapisania' : 'Zapisz bez wysyłania — wrócisz do wniosku później'}>
          <Save size={14} /> Zapisz roboczy
        </button>
        <button className="btn btn--success" onClick={submit} disabled={busy || loading || noChange || !requestTypeId}
                title={!loading && !requestTypeId ? NO_TYPE_MSG : undefined}>
          <Send size={14} /> {sendLabel}
        </button>
      </>}>
          <Section n={1} title="Pracownik">
            <WorkerCard name={w.full_name || w.username}
              sub={[w.username, w.email].filter(Boolean).join(' · ') || null}
              cols={[
                { label: 'Wydział', value: deptFull(w.department_name, w.department_description) },
                { label: 'Jednostka', value: w.unit_name },
                { label: 'Stanowisko', value: w.title },
              ]} />
          </Section>

          <Section n={2} title="Uprawnienia — stan docelowy">
          <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 10 }}>
            Zaznaczone i oznaczone <span className="badge badge--neutral" style={{ fontSize: 11 }}>posiada</span>{' '}
            to uprawnienia, które pracownik ma obecnie. To <strong>stan docelowy</strong>:
            zaznacz dodatkowe, aby je <strong>nadać</strong>; odznacz posiadane, aby je <strong>odebrać</strong>.
          </div>
          {!loading && systems.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <CopyFromColleague excludeUserId={w.id} onCopy={copyFrom} disabled={busy} />
            </div>
          )}
          {loading ? (
            <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie uprawnień…</div>
          ) : systems.length === 0 ? (
            <div className="alert alert--warning">
              Brak zdefiniowanych systemów — poproś administratora o konfigurację.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column' }}>
              {systems.map(s => {
                const perms = permsBySys[s.id] || []
                // „Tylko dostęp" = jedna pozycja na cały program.
                const { main, admin } = splitAdminPerm(perms)
                const adminKey = admin ? `${s.id}:${admin.id}` : null
                if (s.access_only) {
                  const p = main[0]
                  if (!p) return null
                  const key = `${s.id}:${p.id}`
                  return (
                    <SystemBlock
                      key={s.id} name={s.name} description={s.description} compact
                      checked={picked.has(key)}
                      onToggle={() => togglePerm(s.id, p.id)}
                      accent={permState(key)}
                      headerStyle={{
                        textDecoration: permState(key) === 'revoke' ? 'line-through' : 'none',
                      }}
                      badges={<>
                        <span className="badge badge--info" style={{ fontSize: 11 }}>
                          dostęp
                        </span>
                        {s.default_checked && (
                          <span className="badge badge--warning" style={{ fontSize: 11 }}
                                title="Zaznaczone automatycznie — możesz odznaczyć">
                            domyślne
                          </span>
                        )}
                        <ChangeBadge st={permState(key)} />
                      </>}
                    >
                      <AdminPermRow
                        perm={admin} checked={picked.has(adminKey)} indent={0}
                        onToggle={() => togglePerm(s.id, admin.id)}
                        extra={<ChangeBadge st={permState(adminKey)} />}
                        disabled={!picked.has(key) && !(adminKey && picked.has(adminKey))}
                      />
                    </SystemBlock>
                  )
                }
                // Program z listą uprawnień. Domyślnie bez zbiorczego checkboxa;
                // przy require_scope dokładamy checkbox nagłówka i wyszarzenie.
                const allKeys = main.map(x => `${s.id}:${x.id}`)
                const selHere = allKeys.filter(k => picked.has(k)).length
                const gated = isScopeGated(s)
                const anySel = selHere > 0 || (adminKey && picked.has(adminKey))
                const active = !gated || openSys.has(s.id) || anySel
                return (
                  <SystemBlock
                    key={s.id} name={s.name} description={s.description} compact
                    showCheckbox={gated}
                    checked={active}
                    onToggle={() => toggleScope(s)}
                    locked={gated && !active}
                    lockedHint={gated && !active
                      ? 'Zaznacz program, aby wybrać zakres uprawnień.' : null}
                    badges={<>
                      {selHere > 0 && (
                        <span className="badge badge--success" style={{ fontSize: 11 }}>
                          wybrano: {selHere}
                        </span>
                      )}
                      {gated && active && !anySel && (
                        <span className="badge badge--warning" style={{ fontSize: 11 }}
                              title="Wybierz co najmniej jedno uprawnienie">
                          wybierz zakres
                        </span>
                      )}
                    </>}
                  >
                    {main.length === 0 && !admin ? (
                      <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        (brak zdefiniowanych uprawnień)
                      </div>
                    ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginLeft: 8 }}>
                        {groupPerms(main).map(({ group, items }) => {
                          const gkey = `${s.id}|${group}`
                          const q = (groupQuery[gkey] || '').toLowerCase()
                          const visible = items
                            .filter(p => isPermVisible(p, `${s.id}:${p.id}`, held, picked))
                            .filter(p => !q || p.permission_name.toLowerCase().includes(q))
                          const selCount = items.filter(
                            p => picked.has(`${s.id}:${p.id}`)).length
                          return (
                            <PermGroupSection
                              key={gkey} group={group} count={items.length} compact
                              selectedCount={selCount}
                              query={groupQuery[gkey] || ''}
                              onQuery={v => setGroupQuery(x => ({ ...x, [gkey]: v }))}
                              onToggleAll={() => toggleMany(visible.map(p => `${s.id}:${p.id}`))}
                            >
                              {visible.length === 0 && (
                                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                                  Brak pozycji pasujących do wyszukiwania.
                                </div>
                              )}
                              {subgroupPerms(visible).map(({ subgroup, items: subItems }) => (
                                <div key={subgroup || '_nosub'}>
                                  {subgroup && (
                                    <div style={{
                                      fontSize: 11, fontStyle: 'italic', letterSpacing: '.02em',
                                      color: 'var(--color-text-muted)', margin: '4px 0 2px 2px',
                                    }}>
                                      ↳ {subgroup}
                                    </div>
                                  )}
                                  {subItems.map(p => {
                          const key = `${s.id}:${p.id}`
                          return (
                            <div key={p.id} style={subgroup ? { marginLeft: 12 } : undefined}>
                            <label style={{
                              display: 'flex', alignItems: 'center', gap: 6, fontSize: 12,
                              cursor: 'pointer', ...stateStyle(permState(key)),
                            }}>
                              <input
                                type="checkbox"
                                checked={picked.has(key)}
                                onChange={() => togglePerm(s.id, p.id)}
                              />
                              <span style={{
                                textDecoration: permState(key) === 'revoke' ? 'line-through' : 'none',
                                color: permState(key) === 'revoke' ? 'var(--color-error-text)' : 'inherit',
                              }}>{p.permission_name}</span>
                              <ChangeBadge st={permState(key)} />
                              {p.is_active === false && (
                                <span className="badge badge--warning" style={{ fontSize: 11 }}
                                      title="Pozycja wycofana w systemie źródłowym">
                                  wycofane
                                </span>
                              )}
                              {p.description && <span style={{ color: 'var(--color-text-muted)' }}>— {p.description}</span>}
                            </label>
                            <PermInput
                              input={permInput(p)} name={p.permission_name} compact
                              show={picked.has(key)}
                              values={fieldValues[key] || {}}
                              onChange={(label, v) => setFieldValue(key, label, v)}
                            />
                            </div>
                          )
                                  })}
                                </div>
                              ))}
                            </PermGroupSection>
                          )
                        })}
                        <AdminPermRow
                          perm={admin} checked={picked.has(adminKey)} indent={0}
                          onToggle={() => togglePerm(s.id, admin.id)}
                          extra={<ChangeBadge st={permState(adminKey)} />}
                          disabled={!(selHere > 0 || (gated && openSys.has(s.id)))
                                    && !(adminKey && picked.has(adminKey))}
                        />
                      </div>
                    )}
                  </SystemBlock>
                )
              })}
            </div>
          )}

          {/* Podsumowanie: co wniosek faktycznie zmieni */}
          {!loading && (
            <div role="status" className={`alert ${noChange ? 'alert--info' : 'alert--success'}`}
                 style={{ fontSize: 13, marginTop: 12, border: 'none', borderRadius: 8, padding: '10px 14px' }}>
              {noChange ? (
                <>Brak zmian względem obecnego stanu — zaznacz nowe uprawnienia lub odznacz posiadane.</>
              ) : (
                <>
                  Wniosek o zmianę:{' '}
                  {toGrant.length > 0 && <><strong>{toGrant.length}</strong> do nadania</>}
                  {toGrant.length > 0 && toRevoke.length > 0 && ' · '}
                  {toRevoke.length > 0 && <><strong>{toRevoke.length}</strong> do odebrania</>}
                </>
              )}
            </div>
          )}

          </Section>

          <Section n={3} title="Uwagi" note="opcjonalne">
            <div className="form-group" style={{ marginBottom: 0 }}>
              <label className="form-label" htmlFor="myteam-comment">Komentarz · uzasadnienie wniosku</label>
              <textarea id="myteam-comment" className="form-control" style={{ minHeight: 70 }}
                        value={comment} onChange={e => setComment(e.target.value)}
                        placeholder="Uzasadnienie / kontekst wniosku" />
            </div>
          </Section>

          {!loading && !requestTypeId && !err && (
            <div className="alert alert--error" role="alert">{NO_TYPE_MSG}</div>
          )}
          {err && <div className="alert alert--error">{err}</div>}
    </RequestViewShell>

      <ReviewDialog
        open={reviewOpen}
        workerName={w.full_name || w.username}
        grants={describeKeys([...toGrant, ...scopeChanged], systems, permsBySys, fieldValues)}
        revokes={describeKeys(toRevoke, systems, permsBySys)}
        target={w.requires_higher_approval
          ? 'Po wysłaniu wniosek trafi do akceptacji kierownika nadrzędnego, potem do IT.'
          : 'Po wysłaniu wniosek trafi do realizacji przez IT.'}
        confirmLabel={sendLabel}
        busy={busy}
        onBack={() => setReviewOpen(false)}
        onConfirm={confirmFromReview}
      />

      {declItems && (
        <DeclarationModal
          text={declText}
          busy={busy}
          onClose={() => { setDeclItems(null); setBusy(false) }}
          onConfirm={(declaration) => {
            setBusy(true)
            const items = declItems
            setDeclItems(null)
            sendRequest(items, declaration)
          }}
        />
      )}
    </>
  )
}
