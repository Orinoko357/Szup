import { useEffect, useRef, useState } from 'react'
import { Wrench, RefreshCw, CheckCircle, Link2, UserPlus, Plus } from 'lucide-react'
import {
  listRequests, workflowAction, linkRequestWorker, listItStaff, assignRequest,
  listSystems, denyRequestItem, fulfillRequestItem, getRequest, getMe, errorMessage,
} from '../api'
import { fmtDate, serverTs } from '../serverTime'
import { getUserRoles } from '../roles'
import Segmented from '../components/ui/Segmented'
import RequestViewShell, {
  buildWorkflowSteps, Section, WorkerCard, deptFull, KindPill, perspectiveLabel, waitingText,
} from '../components/RequestView'
import PermissionChanges from '../components/PermissionChanges'
import AddPermissionsPicker from '../components/AddPermissionsPicker'
import { statusLabel, statusBadge, kindLabel, daysSince, waitText } from '../labels'

/** Kierownik IT = osoba mająca JEDNOCZEŚNIE rolę „manager" i „it_staff".
 *  TYLKO ona może przekazywać wnioski (admin/superadmin — nie).
 *  Może też zrealizować wniosek sama, bez przekazywania. */
function isItManager() {
  const roles = getUserRoles()
  return roles.includes('manager') && roles.includes('it_staff')
}
import { toast, confirmDialog } from '../components/ui/feedback'
import {
  missingRequiredFields, adminGrantNames, confirmAdminRights, ADMIN_CONFIRM_ABORTED,
} from '../components/ItemFields'

// Lista realizacji IT (zakładka „Realizacja IT” strony Wnioski).
export function RequestsTab({ onViewChange, openId, onOpenConsumed, onChanged }) {
  const [requests, setRequests] = useState([])
  const [loading, setLoading]   = useState(true)
  const [filter, setFilter]     = useState('pending_it')
  // v3.1 — szybki filtr kolejki: wszystkie / moje / nieprzypisane.
  const [who, setWho]           = useState('all')
  const [meId, setMeId]         = useState(null)
  useEffect(() => {
    getMe().then(r => setMeId(r.data?.id ?? null))
      .catch(ex => toast(errorMessage(ex, 'Nie udało się ustalić zalogowanego użytkownika — filtr „Moje” nie zadziała.'), { tone: 'warning' }))
  }, [])
  const [openReq, setOpenReq]   = useState(null)   // jeden wspólny widok: podgląd + realizacja
  const openedRef = useRef(false)

  async function load({ silent = false } = {}) {
    if (!silent) setLoading(true)
    try {
      const params = filter !== 'all' ? { status: filter } : {}
      const r = await listRequests(params)
      setRequests(r.data)
      // Po cichym odświeżeniu (np. po zapisie odmowy/realizacji pojedynczej
      // pozycji) zsynchronizuj też otwarty wniosek, żeby po zamknięciu i
      // ponownym otwarciu stan pozycji zgadzał się z bazą.
      setOpenReq(prev => (prev ? (r.data.find(x => x.id === prev.id) || prev) : prev))
      // Wejście z pulpitu: otwórz wskazany wniosek (jednorazowo); spoza
      // bieżącego filtra — dociągnij pojedynczo.
      if (openId && !openedRef.current) {
        openedRef.current = true
        const hit = r.data.find(x => x.id === Number(openId))
        if (hit) setOpenReq(hit)
        else getRequest(openId).then(x => setOpenReq(x.data))
          .catch(() => toast(`Wniosek #${openId} nie jest dostępny.`, { tone: 'info' }))
        onOpenConsumed?.()
      }
      return r.data
    } catch (ex) {
      toast(errorMessage(ex, 'Nie udało się pobrać wniosków'), { tone: 'error' })
      return []
    } finally { if (!silent) setLoading(false) }
  }

  useEffect(() => { load() }, [filter])
  useEffect(() => { onViewChange?.(!!openReq) }, [openReq])

  const matchWho = (x) => who === 'all' || filter !== 'pending_it'
    || (who === 'mine' ? (meId != null && x.assigned_to_user_id === meId) : !x.assigned_to_user_id)
  const shown = requests.filter(matchWho)
  const counts = {
    all: requests.length,
    mine: requests.filter(x => meId != null && x.assigned_to_user_id === meId).length,
    unassigned: requests.filter(x => !x.assigned_to_user_id).length,
  }

  // Po zakończeniu: przy realizacji od razu otwórz NASTĘPNY wniosek z kolejki.
  async function handleDone(result) {
    setOpenReq(null)
    onChanged?.()
    const data = await load().catch(() => [])
    if (result?.realizedId) {
      // Następny wniosek wybieramy ZAWSZE z kolejki „pending_it” — przy filtrze
      // „Wszystkie” lista zawiera tylko 200 najnowszych wniosków w ogóle,
      // więc najstarszy oczekujący mógłby zostać pominięty.
      let queue = data || []
      if (filter !== 'pending_it') {
        try { queue = (await listRequests({ status: 'pending_it' })).data || [] }
        catch (ex) {
          toast(errorMessage(ex, 'Nie udało się pobrać kolejki realizacji'), { tone: 'warning' })
          queue = []
        }
      }
      const next = queue
        .filter(x => x.status === 'pending_it' && x.id !== result.realizedId)
        .filter(matchWho)
        .sort((a, b) => (serverTs(a.step_since || a.created_at) || 0) - (serverTs(b.step_since || b.created_at) || 0))[0]
      if (next) {
        toast(`Zrealizowano #${result.realizedId} — otwieram następny (#${next.id}).`)
        setOpenReq(next)
      } else {
        toast(`Zrealizowano #${result.realizedId}. Kolejka realizacji jest pusta.`)
      }
    }
  }

  // Otwarty wniosek = pełnoekranowy widok (zamiast listy), spójnie z Kartoteką.
  if (openReq) {
    return <RequestModal key={openReq.id} request={openReq} onClose={() => setOpenReq(null)}
                         onDone={handleDone}
                         onRefresh={() => load({ silent: true })} />
  }

  return (
    <>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <Segmented ariaLabel="Filtr statusu" value={filter} onChange={setFilter}
                   options={[{ value: 'pending_it', label: statusLabel('pending_it') }, { value: 'all', label: 'Wszystkie' }]} />
        {filter === 'pending_it' && (
          <Segmented ariaLabel="Kto realizuje" value={who} onChange={setWho}
                     options={[
                       { value: 'all',        label: 'Wszystkie',     count: counts.all },
                       { value: 'mine',       label: 'Moje',          count: counts.mine },
                       { value: 'unassigned', label: 'Nieprzypisane', count: counts.unassigned },
                     ]} />
        )}
        <button className="btn btn--ghost btn--sm" style={{ marginLeft: 'auto' }}
                onClick={() => { load(); onChanged?.() }} disabled={loading}>
          <RefreshCw size={14} aria-hidden="true" /> Odśwież
        </button>
      </div>
      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {loading ? <div style={{ color: 'var(--color-text-muted)', padding: 18 }}>Ładowanie…</div> : shown.length === 0 ? (
          <div style={{ padding: 18 }}>
            <div style={{ fontWeight: 700 }}>
              {filter === 'pending_it'
                ? (who === 'mine' ? 'Nie masz przypisanych wniosków.' : who === 'unassigned' ? 'Brak nieprzypisanych wniosków.' : 'Kolejka realizacji jest pusta.')
                : 'Brak wniosków.'}
            </div>
            {filter === 'pending_it' && who !== 'all' && (
              <button type="button" className="btn btn--ghost btn--sm" style={{ marginTop: 8 }} onClick={() => setWho('all')}>
                Pokaż całą kolejkę
              </button>
            )}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
          <table className="data-table" style={{ minWidth: 1080 }}>
            <thead><tr><th>#</th><th>Pracownik</th><th>Wydział</th><th>Jednostka</th><th>Uprawnień</th><th>Status</th><th>Przypisany</th><th>Czeka</th><th></th></tr></thead>
            <tbody>
              {shown.map(r => (
                <tr key={r.id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.id}</td>
                  <td>
                    <div style={{ fontWeight: 700 }}>{r.worker_name}</div>
                    <KindPill kind={r.kind} />
                  </td>
                  <td>{deptFull(r.department_name, r.department_description)}</td>
                  <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{r.unit_name || '—'}</td>
                  <td>{r.items?.length||0}</td>
                  <td>
                    <span className={`badge ${statusBadge(r.status)}`}>{statusLabel(r.status)}</span>
                    {r.status !== 'pending_it' && waitingText(r) && (
                      <div style={{ fontSize: 12, color: 'var(--color-warning-text)', marginTop: 2 }}>{waitingText(r)}</div>
                    )}
                  </td>
                  <td style={{ fontSize: 12 }}>
                    {r.assigned_to_name
                      ? <span className="badge badge--info">{r.assigned_to_name}</span>
                      : <span style={{ color: 'var(--color-text-muted)' }}>nieprzypisany</span>}
                  </td>
                  <td style={{ fontSize: 12 }}>
                    {(() => {
                      const d = daysSince(serverTs(r.step_since || r.created_at))
                      return <span style={{ fontWeight: d >= 7 ? 700 : 400,
                                            color: d >= 7 ? 'var(--color-error-text)' : 'var(--color-text-muted)' }}>
                        {r.status === 'pending_it' ? waitText(d) : '—'}
                      </span>
                    })()}
                    <div style={{ color: 'var(--color-text-muted)' }}>złożono {fmtDate(r.created_at)}</div>
                  </td>
                  <td>
                    {r.status === 'pending_it' ? (
                      <button className="btn btn--success btn--sm" onClick={() => setOpenReq(r)}>
                        <CheckCircle size={13} /> {r.kind === 'revoke' ? 'Odbierz' : 'Zrealizuj'}
                      </button>
                    ) : (
                      <button className="btn btn--ghost btn--sm" onClick={() => setOpenReq(r)}>Podgląd</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </div>
    </>
  )
}

function _guessAdUsername(r) {
  // Najlepsze domyślne: część e-maila przed @, potem jeśli worker_name wygląda
  // jak login bez spacji — użyj go; fallback: pusto.
  const em = (r.worker_email || '').trim()
  if (em && em.includes('@')) return em.split('@')[0].toLowerCase()
  const wn = (r.worker_name || '').trim()
  if (wn && !wn.includes(' ')) return wn.toLowerCase()
  return ''
}

// Jeden wspólny widok wniosku dla IT: podgląd (dane, uprawnienia, obieg) oraz
// akcja właściwa dla statusu — realizacja/odebranie (pending_it) albo
// dowiązanie konta (completed bez worker_user_id).
function RequestModal({ request: r, onClose, onDone, onRefresh }) {
  const isRevoke   = r.kind === 'revoke'
  const canRealize = r.status === 'pending_it'
  const canLink    = r.status === 'completed' && !r.worker_user_id
  // Login AD potrzebny tylko wtedy, gdy wniosek nie jest jeszcze dowiązany do
  // konta pracownika (nowy pracownik). Przy zmianie/ustaniu konto już istnieje.
  const needsAd = !r.worker_user_id

  // Pozycje wniosku — PermissionChanges rozbija je po kierunku (nadanie/odebranie).
  // Trzymamy lokalną kopię, żeby po natychmiastowym zapisie odmowy odświeżyć
  // pojedynczą pozycję w miejscu (badge „odmówiono"), bez zamykania okna.
  const [items, setItems] = useState(r.items || [])
  useEffect(() => { setItems(r.items || []) }, [r.id])
  // Postęp realizacji etapowej — liczone po pozycjach NADANIA.
  const grantItems = items.filter(it => (it.kind || 'grant') !== 'revoke')
  const grantProgress = {
    total: grantItems.length,
    done: grantItems.filter(it => it.fulfilled && !it.denied).length,
    denied: grantItems.filter(it => it.denied).length,
    get pending() { return this.total - this.done - this.denied },
  }

  const isItManager = isItManager()
  const [comment, setComment]       = useState('')
  const [adUsername, setAdUsername] = useState(() => (needsAd ? _guessAdUsername(r) : ''))
  // Szkice odmów (otwarte pola komentarza): { [item_id]: komentarz }.
  const [denials, setDenials] = useState({})
  const [denyBusy, setDenyBusy] = useState(null)   // id pozycji aktualnie zapisywanej
  const toggleDeny = (id) => setDenials(prev => {
    const next = { ...prev }
    if (Object.prototype.hasOwnProperty.call(next, id)) delete next[id]
    else next[id] = ''
    return next
  })
  const setDenyComment = (id, v) => setDenials(prev => ({ ...prev, [id]: v }))
  // Zapisuje odmowę OD RAZU i aktualizuje pozycję na liście (potwierdzenie dla realizatora).
  async function saveDeny(id) {
    setDenyBusy(id); setErr(null)
    try {
      const res = await denyRequestItem(r.id, id, {
        denied: true, comment: (denials[id] || '').trim() || null,
      })
      const upd = res.data?.item
      if (upd) setItems(prev => prev.map(it => (it.id === id ? { ...it, ...upd } : it)))
      setDenials(prev => { const n = { ...prev }; delete n[id]; return n })
      onRefresh?.()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się zapisać odmowy'))
    } finally { setDenyBusy(null) }
  }
  async function removeDeny(id) {
    setDenyBusy(id); setErr(null)
    try {
      const res = await denyRequestItem(r.id, id, { denied: false })
      const upd = res.data?.item
      if (upd) setItems(prev => prev.map(it => (it.id === id ? { ...it, ...upd } : it)))
      onRefresh?.()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się cofnąć odmowy'))
    } finally { setDenyBusy(null) }
  }
  // Realizacja etapowa: odhaczenie / cofnięcie pojedynczej pozycji przez IT.
  async function setFulfill(id, done) {
    setDenyBusy(id); setErr(null)
    try {
      const res = await fulfillRequestItem(r.id, id, { fulfilled: done })
      const upd = res.data?.item
      if (upd) setItems(prev => prev.map(it => (it.id === id ? { ...it, ...upd } : it)))
      onRefresh?.()
    } catch (ex) {
      setErr(errorMessage(ex, done ? 'Nie udało się odhaczyć pozycji' : 'Nie udało się cofnąć realizacji'))
    } finally { setDenyBusy(null) }
  }
  const [busy, setBusy] = useState(false)
  const [err, setErr]   = useState(null)

  // Dokładanie uprawnień wymaganych technicznie (np. moduł potrzebuje
  // zależnego dostępu). Sekcja domyślnie zwinięta — realizacja bez zmian
  // ma pozostać jednym kliknięciem.
  const [showAdd, setShowAdd] = useState(false)
  const [addPicked, setAddPicked] = useState(() => new Set())
  const [addFieldValues, setAddFieldValues] = useState({})
  const [addSystems, setAddSystems] = useState([])   // do walidacji pól wymaganych
  const [addPerms, setAddPerms] = useState({})       // { system_id: [uprawnienia] }
  // Pozycje już na wniosku — nie da się ich dołożyć drugi raz.
  const existingKeys = new Set(items.map(i => `${i.system_id}:${i.permission_id}`))

  function toggleAddPerm(systemId, permId) {
    const key = `${systemId}:${permId}`
    setAddPicked(prev => {
      const n = new Set(prev)
      n.has(key) ? n.delete(key) : n.add(key)
      return n
    })
  }
  function setAddFieldValue(key, label, val) {
    setAddFieldValues(prev => ({ ...prev, [key]: { ...(prev[key] || {}), [label]: val } }))
  }

  // Nazwy programów do komunikatów walidacji przed wysyłką (picker ma własną
  // kopię do renderowania; definicje kontrolek przychodzą przez `onLoaded`).
  useEffect(() => {
    if (!showAdd || addSystems.length > 0) return
    listSystems({ unit_id: r.unit_id, active_only: true })
      .then(res => setAddSystems(res.data))
      .catch(ex => {
        setAddSystems([])
        toast(errorMessage(ex, 'Nie udało się pobrać listy programów'), { tone: 'warning' })
      })
  }, [showAdd, r.unit_id, addSystems.length])

  // Przekazanie wniosku pracownikowi IT (tylko kierownik IT / admin).
  const [itStaff, setItStaff]   = useState([])
  const [assignee, setAssignee] = useState(r.assigned_to_user_id || '')
  useEffect(() => {
    if (!isItManager || !canRealize) return
    listItStaff().then(res => setItStaff(res.data)).catch(ex => {
      setItStaff([])
      toast(errorMessage(ex, 'Nie udało się pobrać listy pracowników IT'), { tone: 'warning' })
    })
  }, [isItManager, canRealize])

  async function assign() {
    setBusy(true); setErr(null)
    try {
      await assignRequest(r.id, assignee ? Number(assignee) : null)
      const who = itStaff.find(u => String(u.id) === String(assignee))
      toast(assignee ? `Przekazano wniosek #${r.id}: ${who?.full_name || who?.username || 'pracownik IT'}.`
                     : `Wniosek #${r.id} jest teraz nieprzypisany.`)
      onDone()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się przekazać wniosku')); setBusy(false)
    }
  }

  async function realize() {
    const u = adUsername.trim()
    if (needsAd && !u) { setErr('Wpisz sAMAccountName pracownika (login AD)'); return }

    // Praca etapowa: jeśli zostały pozycje nadania ani nieodhaczone, ani
    // nieodmówione — upewnij się, że realizator chce zamknąć wniosek teraz.
    if (!isRevoke && grantProgress.pending > 0) {
      const ok = await confirmDialog({
        title: 'Zostały pozycje bez decyzji',
        message: `Pozostało ${grantProgress.pending} pozycji bez decyzji (nieodhaczonych i `
          + `nieodmówionych). Zamknąć wniosek teraz? Pozostałe zostaną oznaczone jako nadane.`,
        confirmLabel: 'Zamknij wniosek',
      })
      if (!ok) return
    }

    // Pozycje dołożone przez IT — zawsze „grant" (IT nie odbiera uprawnień).
    const addedKeys = [...addPicked]
    const added_items = addedKeys.map(k => {
      const [sid, pid] = k.split(':').map(Number)
      const item = { system_id: sid, permission_id: pid, kind: 'grant' }
      const vals = addFieldValues[k]
      if (vals && Object.keys(vals).length) item.custom_values = vals
      return item
    })

    if (added_items.length > 0) {
      // Te same reguły co u kierownika — backend waliduje niezależnie.
      const miss = missingRequiredFields(addedKeys, addSystems, addFieldValues, addPerms)
      if (miss.length) {
        setErr('Uzupełnij pola obowiązkowe: ' + miss.join('; ')); return
      }
      if (!comment.trim()) {
        setErr('Podaj uzasadnienie dodanych uprawnień.'); return
      }
      // Także IT musi twardo potwierdzić uprawnienia administracyjne —
      // dokładanie ich na etapie realizacji omija akceptację kierownika.
      const admins = adminGrantNames(addedKeys, addSystems, addPerms)
      if (!(await confirmAdminRights(admins))) { setErr(ADMIN_CONFIRM_ABORTED); return }
    }

    setBusy(true); setErr(null)
    try {
      const extra = { action: 'execute', comment }
      if (u) extra.ad_username = u
      if (added_items.length > 0) extra.added_items = added_items
      const ds = Object.entries(denials).map(([item_id, c]) => ({
        item_id: Number(item_id), comment: (c || '').trim() || null,
      }))
      if (ds.length) extra.denials = ds
      // Ochrona przed równoległą akcją — IT mutuje teraz pozycje wniosku.
      if (r.current_node_id) extra.expected_node_id = r.current_node_id
      await workflowAction(r.id, extra)
      onDone({ realizedId: r.id })
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się potwierdzić realizacji')); setBusy(false)
      if (ex.response?.status === 409) onRefresh?.()
    }
  }

  async function link() {
    const u = adUsername.trim()
    if (!u) { setErr('Wpisz sAMAccountName pracownika'); return }
    setBusy(true); setErr(null)
    try {
      await linkRequestWorker(r.id, u)
      toast(`Dowiązano konto ${u} do wniosku #${r.id}.`)
      onDone()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się dowiązać konta')); setBusy(false)
    }
  }

  // „Anuluj” / „Wróć” — decyzje „Zrobione/Odmów” zapisują się od razu; ostrzegamy
  // tylko o tym, co jeszcze NIE trafiło do bazy (komentarz, szkice odmów,
  // dołożone uprawnienia, wpisany login).
  async function guardedClose() {
    const dirty = comment.trim() !== '' || Object.keys(denials).length > 0 || addPicked.size > 0
      || (needsAd && adUsername.trim() !== _guessAdUsername(r))
    if (dirty && !(await confirmDialog({
      title: 'Porzucić zmiany?',
      message: 'Komentarz, rozpoczęte odmowy lub dołożone uprawnienia nie zostały zapisane i zostaną utracone. '
        + 'Decyzje „Zrobione” i zapisane odmowy pozostają.',
      confirmLabel: 'Porzuć zmiany', danger: true,
    }))) return
    onClose()
  }

  // v3.1 — skróty klawiaturowe realizacji: Z = zrobione, O = odmów,
  // ↓/J i ↑/K = następna/poprzednia pozycja. Kolejność jak na ekranie (DOM).
  const changesRef = useRef(null)
  const [focusId, setFocusId] = useState(null)
  const isUndecided = (it) => it && (it.kind || 'grant') !== 'revoke' && !it.fulfilled && !it.denied
  function orderedIds() {
    const els = changesRef.current ? changesRef.current.querySelectorAll('[data-item-id]') : []
    return [...els].map(el => Number(el.getAttribute('data-item-id')))
      .filter(id => items.some(it => it.id === id && (it.kind || 'grant') !== 'revoke'))
  }
  useEffect(() => {
    if (!canRealize) return
    // Startowy fokus: pierwsza pozycja bez decyzji.
    if (focusId == null || !items.some(it => it.id === focusId)) {
      const first = orderedIds().find(id => isUndecided(items.find(it => it.id === id)))
      if (first != null) setFocusId(first)
    }
  }, [items, canRealize])
  useEffect(() => {
    if (!canRealize) return
    function onKey(e) {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      const tag = (e.target?.tagName || '').toLowerCase()
      if (['input', 'textarea', 'select'].includes(tag) || e.target?.isContentEditable) return
      if (document.querySelector('[role="dialog"]')) return
      const ids = orderedIds()
      if (!ids.length) return
      const idx = Math.max(0, ids.indexOf(focusId))
      const key = e.key.toLowerCase()
      const move = (d) => {
        const n = ids[Math.min(ids.length - 1, Math.max(0, idx + d))]
        setFocusId(n)
        changesRef.current?.querySelector(`[data-item-id="${n}"]`)?.scrollIntoView({ block: 'nearest' })
      }
      if (key === 'arrowdown' || key === 'j') { e.preventDefault(); move(1) }
      else if (key === 'arrowup' || key === 'k') { e.preventDefault(); move(-1) }
      else if (key === 'z') {
        const it = items.find(x => x.id === focusId)
        if (isUndecided(it) && denyBusy == null) {
          e.preventDefault()
          setFulfill(it.id, true)
          // Przejdź do kolejnej pozycji bez decyzji.
          const next = ids.slice(idx + 1).find(id => isUndecided(items.find(x => x.id === id)))
          if (next != null) setFocusId(next)
        }
      } else if (key === 'o') {
        const it = items.find(x => x.id === focusId)
        if (isUndecided(it) && !Object.prototype.hasOwnProperty.call(denials, it.id)) {
          e.preventDefault()
          toggleDeny(it.id)
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [canRealize, items, focusId, denials, denyBusy])

  const title = canRealize
    ? (isRevoke ? 'Odebranie uprawnień' : 'Realizacja wniosku')
    : `Wniosek #${r.id}`
  // Numeracja sekcji 01, 02, … — liczone tylko sekcje faktycznie widoczne.
  let _sec = 0
  const sec = () => ++_sec

  const _steps = buildWorkflowSteps({
    sent: true, nodeType: r.current_node_type, status: r.status,
    requiresHigher: r.requires_higher_approval, kind: r.kind,
  })
  const _summary = [
    { label: 'Pracownik', value: r.worker_name },
    { label: 'Stanowisko', value: r.worker_position || '—' },
    { label: 'Komórka', value: `${r.department_name || '—'} · ${r.unit_name || '—'}` },
  ]

  return (
    <RequestViewShell
      icon={Wrench} kind={['revoke', 'change'].includes(r.kind) ? r.kind : 'grant'} kindLabel={kindLabel(r.kind)}
      perspective={canRealize ? perspectiveLabel('it_execute') : null}
      waiting={!canRealize ? waitingText(r) : null}
      statusText={`Wniosek #${r.id}${r.created_at ? ` · złożony ${fmtDate(r.created_at)}` : ''}`} title={title}
      subtitle="Wykonaj zmiany w systemach i oznacz każdą pozycję — decyzje zapisują się od razu."
      backLabel="← Wróć do listy" onBack={guardedClose}
      steps={_steps} summary={_summary} historyRequestId={r.id}
      historyCreatedBy={r.created_by_name}
      footerLeft={canRealize && grantProgress.total > 0
        ? (grantProgress.pending > 0
            ? <>Zostało <strong>{grantProgress.pending}</strong> bez decyzji</>
            : 'Wszystkie pozycje mają decyzję')
        : null}
      footerActions={<>
        <button className="btn btn--ghost" onClick={guardedClose} disabled={busy}>
          {canRealize || canLink ? 'Anuluj' : 'Zamknij'}
        </button>
        {canRealize && (
          <button className="btn btn--success" onClick={realize}
                  disabled={busy || (needsAd && !adUsername.trim())}>
            <CheckCircle size={14} /> {busy ? 'Zapisywanie…' : (isRevoke ? 'Potwierdź odebranie' : 'Potwierdź realizację')}
          </button>
        )}
        {canLink && (
          <button className="btn btn--action" onClick={link} disabled={busy || !adUsername.trim()}>
            <Link2 size={14} /> {busy ? 'Zapisywanie…' : 'Dowiąż'}
          </button>
        )}
      </>}>
      <Section n={sec()} title="Pracownik">
        <WorkerCard name={r.worker_name}
          sub={[r.worker_username, r.worker_email].filter(Boolean).join(' · ') || null}
          cols={[
            { label: 'Wydział', value: deptFull(r.department_name, r.department_description) },
            { label: 'Jednostka', value: r.unit_name },
            { label: 'Stanowisko', value: r.worker_position },
          ]} />
      </Section>

      <Section n={sec()} title={isRevoke ? 'Uprawnienia do odebrania' : 'Zmiany do wykonania'}>
        {canRealize && grantProgress.total > 0 && (
          <div style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12,
                          fontSize: 13, marginBottom: 5 }}>
              <span>
                <span style={{ color: 'var(--color-success-text)', fontWeight: 700 }}>
                  zrobione: {grantProgress.done}/{grantProgress.total}
                </span>
                {grantProgress.denied > 0 && (
                  <span style={{ color: 'var(--color-error-text)', fontWeight: 700 }}>
                    {' · '}odmowy: {grantProgress.denied}
                  </span>
                )}
              </span>
              <span style={{ color: 'var(--color-text-muted)' }}>
                bez decyzji: {grantProgress.pending}
              </span>
            </div>
            <div aria-hidden="true" style={{ display: 'flex', height: 6, borderRadius: 3, overflow: 'hidden',
                          background: 'var(--color-border)' }}>
              <div style={{ width: `${grantProgress.done / grantProgress.total * 100}%`,
                            background: 'var(--color-success)' }} />
              <div style={{ width: `${grantProgress.denied / grantProgress.total * 100}%`,
                            background: 'var(--color-error)' }} />
            </div>
          </div>
        )}
        {canRealize && !isRevoke && grantProgress.total > 0 && (
          <div aria-hidden="true" style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 8 }}>
            Skróty: <kbd>Z</kbd> zrobione · <kbd>O</kbd> odmów · <kbd>↑</kbd><kbd>↓</kbd> pozycja
          </div>
        )}
        <div ref={changesRef}>
          <PermissionChanges items={items} focusId={canRealize ? focusId : null}
            deny={{ can: canRealize, map: denials, toggle: toggleDeny, setComment: setDenyComment,
                    save: saveDeny, remove: removeDeny, busyId: denyBusy }}
            fulfill={canRealize
              ? { can: true, set: setFulfill, busyId: denyBusy }
              : undefined} />
        </div>
        {r.manager_comment && (
          <div style={{ marginTop: 14 }}>
            <div className="form-label">Komentarz kierownika</div>
            <div style={{ background: 'var(--bg-secondary)', padding: '10px 14px', borderRadius: 6, fontSize: 14 }}>{r.manager_comment}</div>
          </div>
        )}
      </Section>

      {/* Dokładanie uprawnień — tylko przy nadaniu/zmianie.
          Przy ustaniu stosunku pracy nie ma czego dokładać. */}
      {canRealize && !isRevoke && (
        <Section n={sec()} title="Uprawnienia techniczne" note="opcjonalne">
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 8 }}>
            Np. grupa AD potrzebna do działania nadanego systemu.
          </div>
          <button type="button" className="btn btn--ghost btn--sm"
                  onClick={() => setShowAdd(v => !v)}
                  style={{ marginBottom: showAdd ? 8 : 0 }}>
            <Plus size={13} /> Dołóż uprawnienia
            {addPicked.size > 0 && (
              <span className="badge badge--warning" style={{ fontSize: 11, marginLeft: 6 }}>
                {addPicked.size}
              </span>
            )}
          </button>
          {showAdd && (
            <>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 6 }}>
                Zaznacz uprawnienia, których wniosek nie obejmował, a są konieczne
                (np. moduł wymaga zależnego dostępu). Trafią do ewidencji pracownika,
                a Twoje uzasadnienie do śladu audytowego.
              </div>
              <AddPermissionsPicker
                unitId={r.unit_id}
                excludeKeys={existingKeys}
                picked={addPicked}
                onLoaded={(sys, perms) => setAddPerms(perms)}
                fieldValues={addFieldValues}
                onTogglePerm={toggleAddPerm}
                onFieldChange={setAddFieldValue}
              />
            </>
          )}
        </Section>
      )}

      {/* Nowy pracownik bez dowiązanego konta — login AD do założenia/dowiązania. */}
      {canRealize && needsAd && (
        <Section n={sec()} title="Konto pracownika">
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="it-ad-username">Login AD (sAMAccountName) pracownika *</label>
            <input id="it-ad-username" className="form-control" value={adUsername}
                   onChange={e => setAdUsername(e.target.value)}
                   placeholder="np. jkowalski" autoComplete="off" spellCheck={false} />
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              <UserPlus size={11} style={{ verticalAlign: 'middle', marginRight: 4 }} />
              Jeżeli konto nie istnieje w SZUP, zostanie założone automatycznie (typ LDAP).
            </div>
          </div>
        </Section>
      )}

      {canRealize && (
        <Section n={sec()} title="Uwagi" note={addPicked.size > 0 ? null : 'opcjonalne'}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label className="form-label" htmlFor="it-comment">
              {addPicked.size > 0
                ? 'Uzasadnienie dodanych uprawnień *'
                : 'Komentarz IT · widoczny w historii'}
            </label>
            <textarea id="it-comment" className="form-control" style={{ minHeight: 70 }}
                      placeholder={addPicked.size > 0
                        ? 'Dlaczego te uprawnienia są konieczne?' : ''}
                      value={comment} onChange={e => setComment(e.target.value)} />
          </div>
        </Section>
      )}

      {/* --- Przekazanie wniosku (kierownik IT) --- */}
      {canRealize && isItManager && (
        <Section n={sec()} title="Przekazanie do realizacji" note="opcjonalne">
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 10 }}>
            Możesz zrealizować wniosek samodzielnie (przycisk poniżej) albo przekazać go
            pracownikowi IT. Przekazanie jest oznaczeniem „kto się tym zajmuje" — nie blokuje
            realizacji przez innych.
          </p>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
              <label className="form-label" htmlFor="it-assignee">Pracownik IT</label>
              <select id="it-assignee" className="form-control" value={assignee}
                      onChange={e => setAssignee(e.target.value)}>
                <option value="">— nieprzypisany —</option>
                {itStaff.map(u => (
                  <option key={u.id} value={u.id}>
                    {u.full_name || u.username}{u.username ? ` (${u.username})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <button type="button" className="btn btn--action" onClick={assign} disabled={busy}>
              <UserPlus size={14} /> Przekaż
            </button>
          </div>
          {r.assigned_to_name && (
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 6 }}>
              Obecnie przypisany: <strong>{r.assigned_to_name}</strong>
            </div>
          )}
        </Section>
      )}

      {/* --- Akcja: dowiązanie konta (zrealizowany bez konta) --- */}
      {canLink && (
        <Section n={sec()} title="Dowiąż konto pracownika">
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 10 }}>
            Wniosek zrealizowano, ale nie dowiązano konta. Wpisz sAMAccountName, aby uprawnienia
            pojawiły się w profilu pracownika i w widoku struktury.
          </p>
          <div className="form-group">
            <label className="form-label" htmlFor="it-link-ad">Login AD (sAMAccountName) *</label>
            <input id="it-link-ad" className="form-control" value={adUsername}
                   onChange={e => setAdUsername(e.target.value)}
                   placeholder="np. jkowalski" autoComplete="off" spellCheck={false} />
          </div>
        </Section>
      )}

          {err && <div className="alert alert--error">{err}</div>}
    </RequestViewShell>
  )
}

