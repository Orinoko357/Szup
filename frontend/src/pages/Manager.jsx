import { useEffect, useRef, useState } from 'react'
import { RefreshCw, Check, X, ListChecks, Search } from 'lucide-react'
import { listRequests, workflowAction, listSystems, listPermissions, userPermissions, denyRequestItem } from '../api'
import { fmtDate, serverTs } from '../serverTime'
import RequestViewShell, {
  buildWorkflowSteps, Section, WorkerCard, deptFull, KindBadge, perspectiveLabel, waitingText,
} from '../components/RequestView'
import { statusLabel, statusBadge, nodeLabel, kindLabel, daysSince, waitText } from '../labels'
import { toast, confirmDialog } from '../components/ui/feedback'
import { ReviewDialog, describeKeys } from '../components/ChangeSummary'
import CopyFromColleague, { buildCopiedSelection } from '../components/CopyFromColleague'
import DeclarationModal from '../components/DeclarationModal'
import PermissionChanges, {
  permChangeState, changeStyle, changeTextStyle, ChangeBadge,
} from '../components/PermissionChanges'
import PermInput, {
  permInput, missingRequiredFields, splitAdminPerm, AdminPermRow,
  adminGrantNames, confirmAdminRights, ADMIN_CONFIRM_ABORTED,
  groupPerms, subgroupPerms, isPermVisible, PermGroupSection, SystemBlock,
  isScopeGated, missingScopeSystems,
} from '../components/ItemFields'

const MANAGER_NODES = ['select_permissions', 'manager_approve', 'higher_manager_approve']
// Odznaka rodzaju wniosku (zatrudnienie / odejście / zmiana) — wspólny słownik.
const kindPill = (k) => <KindBadge kind={['revoke', 'change'].includes(k) ? k : 'grant'} label={kindLabel(k)} />

// Postęp realizacji pozycji NADANIA — do pokazania w „Moich wnioskach".
function grantProgressOf(r) {
  const g = (r.items || []).filter(it => (it.kind || 'grant') !== 'revoke')
  const done = g.filter(it => it.fulfilled && !it.denied).length
  const denied = g.filter(it => it.denied).length
  return { total: g.length, done, denied }
}

// Osadzony w stronie „Wnioski” (bez własnego nagłówka i zakładek; zakładkę
// wybiera `view`). openId — od razu otwórz wskazany wniosek (z pulpitu);
// onOpenConsumed — informuje stronę, że parametr został już użyty.
export default function Manager({ view, openId, onOpenConsumed, onViewChange, onChanged }) {
  const [tab, setTab]           = useState(view || 'handle')   // handle | mine
  useEffect(() => { if (view) setTab(view) }, [view])
  const [managerReqs, setManagerReqs] = useState([])   // wnioski z moich komórek (scope=manager)
  const [myReqs, setMyReqs]     = useState([])          // wnioski złożone przeze mnie (scope=mine)
  const [loading, setLoading]   = useState(true)
  const [err, setErr]           = useState(null)
  const [openReq, setOpenReq]   = useState(null)   // jeden wspólny widok: podgląd + akcja
  const openedRef = useRef(false)

  async function load({ silent = false } = {}) {
    if (!silent) setLoading(true)
    setErr(null)
    try {
      const [rMgr, rMine] = await Promise.all([
        listRequests({ scope: 'manager' }),
        listRequests({ scope: 'mine' }),
      ])
      setManagerReqs(rMgr.data || [])
      setMyReqs(rMine.data || [])
      // Po cichym odświeżeniu zsynchronizuj otwarty wniosek (badge odmów/realizacji).
      const all = [...(rMgr.data || []), ...(rMine.data || [])]
      setOpenReq(prev => (prev ? (all.find(x => x.id === prev.id) || prev) : prev))
      // Wejście z pulpitu: otwórz wskazany wniosek (jednorazowo).
      if (openId && !openedRef.current) {
        openedRef.current = true
        const hit = all.find(x => x.id === Number(openId))
        if (hit) setOpenReq(hit)
        else toast(`Wniosek #${openId} nie jest dostępny w Twoim zakresie albo został już obsłużony.`, { tone: 'info' })
        onOpenConsumed?.()
      }
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd ładowania')
    } finally {
      if (!silent) setLoading(false)
    }
  }

  useEffect(() => { load() }, [])
  useEffect(() => { onViewChange?.(!!openReq) }, [openReq])

  // Do obsługi: kroki, na których kierownik MUSI działać (wybór / akceptacja,
  // w tym jako kierownik wyższego rzędu) — np. nowy pracownik do obsłużenia.
  const toHandle = managerReqs.filter(
    x => x.can_act && MANAGER_NODES.includes(x.current_node_type))

  // Otwarty wniosek = pełnoekranowy widok (zamiast listy), spójnie z Kartoteką.
  if (openReq) {
    return <RequestModal request={openReq} onClose={() => setOpenReq(null)}
                         onDone={() => { setOpenReq(null); load(); onChanged?.() }}
                         onRefresh={() => load({ silent: true })} />
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}>
        <button className="btn btn--ghost btn--sm" onClick={() => { load(); onChanged?.() }} disabled={loading}>
          <RefreshCw size={14} /> Odśwież
        </button>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 18 }}>Ładowanie…</div>
        ) : tab === 'handle' ? (
          <HandleTable rows={toHandle} onOpen={setOpenReq} />
        ) : (
          <MineTable rows={myReqs} onOpen={setOpenReq} />
        )}
      </div>
    </div>
  )
}

// --- Zakładka „Wnioski do obsługi" -----------------------------------------
function HandleTable({ rows, onOpen }) {
  if (rows.length === 0) {
    return <div style={{ padding: 18 }}>
      <div style={{ fontWeight: 700 }}>Brak wniosków do obsługi — wszystko załatwione.</div>
      <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 4 }}>
        Nowy wniosek dla pracownika złożysz w „Moich pracownikach”. Jeśli spodziewasz się wniosku,
        a go tu nie ma — sprawdź z administratorem, czy jesteś przypisany(a) jako kierownik komórki.
      </div>
    </div>
  }
  return (
    <div style={{ overflowX: 'auto' }}>
    <table className="data-table" style={{ minWidth: 980 }}>
      <thead>
        <tr>
          <th>#</th><th>Pracownik</th><th>Stanowisko</th><th>Uprawnień</th>
          <th>Do zrobienia</th><th>Czeka</th><th>Złożył(a)</th><th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.id}>
            <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.id}</td>
            <td>
              <div style={{ fontWeight: 700 }}>{r.worker_name}</div>
              {kindPill(r.kind)}
            </td>
            <td style={{ color: 'var(--color-text-muted)' }}>{r.worker_position || '—'}</td>
            <td>{r.items?.length || 0}</td>
            <td>
              <span className="badge badge--warning" style={{ fontSize: 12 }}>
                {nodeLabel(r.current_node_type, statusLabel(r.status))}
              </span>
            </td>
            <td style={{ fontSize: 12 }}>
              {(() => {
                // Od kiedy wniosek czeka na tym kroku (step_since) — gdy brak, od złożenia.
                const d = daysSince(serverTs(r.step_since || r.created_at))
                return <span style={{ fontWeight: d >= 7 ? 700 : 400,
                                      color: d >= 7 ? 'var(--color-error-text)' : 'var(--color-text-muted)' }}>
                  {waitText(d)}
                </span>
              })()}
              <div style={{ color: 'var(--color-text-muted)' }}>złożono {fmtDate(r.created_at)}</div>
            </td>
            <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{r.requested_by_name || r.created_by_name}</td>
            <td>
              {r.status === 'pending_selection' ? (
                <button className="btn btn--action btn--sm" onClick={() => onOpen(r)}>
                  <ListChecks size={13} /> {r.kind === 'revoke' ? 'Wybierz do odebrania' : 'Wybierz uprawnienia'}
                </button>
              ) : (
                <button className="btn btn--action btn--sm" onClick={() => onOpen(r)}>
                  <Check size={13} /> Decyzja
                </button>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  )
}

// --- Zakładka „Moje wnioski" (złożone przeze mnie) -------------------------
function MineTable({ rows, onOpen }) {
  if (rows.length === 0) {
    return <div style={{ padding: 18 }}>
      <div style={{ fontWeight: 700 }}>Nie złożyłeś(aś) jeszcze żadnego wniosku.</div>
      <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 4 }}>
        Wniosek dla pracownika złożysz w „Moich pracownikach” — przycisk „Nowy wniosek” przy jego nazwisku.
      </div>
    </div>
  }
  return (
    <div style={{ overflowX: 'auto' }}>
    <table className="data-table" style={{ minWidth: 820 }}>
      <thead>
        <tr>
          <th>#</th><th>Pracownik</th><th>Status</th>
          <th>Etap / postęp</th><th>Data złożenia</th><th></th>
        </tr>
      </thead>
      <tbody>
        {rows.map(r => {
          const p = grantProgressOf(r)
          const inIt = r.status === 'pending_it' || r.current_node_type === 'it_execute'
          return (
            <tr key={r.id}>
              <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.id}</td>
              <td>
                <div style={{ fontWeight: 700 }}>{r.worker_name}</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginTop: 2 }}>
                  {kindPill(r.kind)}
                  <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                    {r.items?.length || 0} uprawnień
                  </span>
                </div>
              </td>
              <td>
                <span className={`badge ${statusBadge(r.status)}`}>
                  {statusLabel(r.status)}
                </span>
              </td>
              <td style={{ fontSize: 12 }}>
                <span style={{ color: 'var(--color-text-muted)' }}>
                  {r.status === 'completed' ? 'Zakończony'
                    : r.status === 'rejected' ? 'Odrzucony'
                    : nodeLabel(r.current_node_type, '—')}
                </span>
                {inIt && p.total > 0 && (
                  <span style={{ marginLeft: 8, display: 'inline-flex', gap: 8 }}>
                    <span style={{ color: 'var(--color-success)' }}>✓ {p.done}/{p.total}</span>
                    {p.denied > 0 && (
                      <span style={{ color: 'var(--color-error-text)' }}>odmowy: {p.denied}</span>
                    )}
                  </span>
                )}
                {waitingText(r) && (
                  <div style={{ color: 'var(--color-warning-text)', marginTop: 2 }}>{waitingText(r)}</div>
                )}
              </td>
              <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{fmtDate(r.created_at)}</td>
              <td>
                <button className="btn btn--ghost btn--sm" onClick={() => onOpen(r)}>Podgląd</button>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Jeden wspólny widok wniosku dla kierownika: podgląd (dane, uprawnienia,
// obieg) + akcja właściwa dla bieżącego kroku:
//   - pending_selection → wybór uprawnień (nadanie) / do odebrania (ustanie)
//   - pending_manager   → decyzja (zatwierdź / odrzuć)
// ---------------------------------------------------------------------------
function RequestModal({ request: r, onClose, onDone, onRefresh }) {
  const isRevoke   = r.kind === 'revoke'
  // Akcje tylko, gdy backend potwierdza, że TEN użytkownik może działać na
  // bieżącym kroku (can_act) — inaczej podgląd (bez przycisków kończących się 403).
  const isSelect   = !!r.can_act && r.status === 'pending_selection'
  const isDecision = !!r.can_act && r.status === 'pending_manager'
  // Dwie ścieżki zależne od flagi komórki „wymaga akceptacji wyższego rzędu":
  //  - 2-stopniowa: kierownik → kierownik nadrzędny → IT
  //  - 1-stopniowa: kierownik → IT (bez akceptacji wyższego rzędu)
  const twoStage = !!r.requires_higher_approval

  const [systems, setSystems]       = useState([])
  const [permsBySys, setPermsBySys] = useState({})   // systemId → [permissions] (nadanie/zmiana)
  const [revokeList, setRevokeList] = useState([])   // bieżące uprawnienia pracownika (ustanie)
  const [held, setHeld]             = useState(() => new Set())  // co pracownik ma OBECNIE
  const [picked, setPicked] = useState(() => new Set())
  // "system_id:permission_id" → { nazwaPola: wartość } (pola dodatkowe pozycji)
  const [fieldValues, setFieldValues] = useState({})
  // Zakres, który pracownik ma OBECNIE — do wykrycia, czy kierownik go zmienił.
  const [heldValues, setHeldValues] = useState({})
  const [comment, setComment] = useState('')
  // Odmowy pojedynczych pozycji (kierownik nadrzędny w obiegu 2-stopniowym):
  // { [item_id]: komentarz }.
  const [denials, setDenials] = useState({})
  const toggleDeny = (id) => setDenials(prev => {
    const next = { ...prev }
    if (Object.prototype.hasOwnProperty.call(next, id)) delete next[id]
    else next[id] = ''
    return next
  })
  const setDenyComment = (id, v) => setDenials(prev => ({ ...prev, [id]: v }))
  // Lokalna kopia pozycji — po natychmiastowym zapisie odmowy odświeżamy
  // pojedynczą pozycję w miejscu (badge „odmówiono"), bez zamykania okna.
  const [items, setItems] = useState(r.items || [])
  useEffect(() => { setItems(r.items || []) }, [r.id])
  const [denyBusy, setDenyBusy] = useState(null)
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
      setErr(ex.response?.data?.detail || 'Nie udało się zapisać odmowy')
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
      setErr(ex.response?.data?.detail || 'Nie udało się cofnąć odmowy')
    } finally { setDenyBusy(null) }
  }
  const [busy, setBusy]       = useState(false)
  const [err, setErr]         = useState(null)
  const [loading, setLoading] = useState(isSelect)
  // Oświadczenie wnioskującego — gdy backend zażąda go (428), pokazujemy modal
  // z jego treścią i ponawiamy akcję z podpisem. `declPending` = akcja do ponowienia.
  const [declText, setDeclText] = useState('')
  const [declPending, setDeclPending] = useState(null)

  useEffect(() => {
    if (!isSelect) return
    let alive = true
    ;(async () => {
      try {
        if (isRevoke) {
          // Ustanie: pokaż BIEŻĄCE uprawnienia pracownika; domyślnie
          // zaznacz wszystkie (typowe ustanie = odebranie całości).
          const res = await userPermissions(r.worker_user_id)
          const perms = res.data.permissions || []
          if (!alive) return
          setRevokeList(perms)
          setPicked(new Set(perms.map(p => `${p.system_id}:${p.permission_id}`)))
        } else {
          // Nadanie / zmiana — STAN DOCELOWY:
          // pre-zaznaczenie = obecne uprawnienia pracownika + pozycje „grant"
          // z wniosku − pozycje „revoke" z wniosku.
          const [sys, permsRes] = await Promise.all([
            listSystems({ unit_id: r.unit_id, active_only: true }),
            r.worker_user_id ? userPermissions(r.worker_user_id) : Promise.resolve({ data: { permissions: [] } }),
          ])
          const active = sys.data
          const byId = {}
          const results = await Promise.all(active.map(s => listPermissions(s.id)))
          results.forEach((res2, i) => { byId[active[i].id] = res2.data })
          if (!alive) return

          const heldSet = new Set(
            (permsRes.data.permissions || []).map(p => `${p.system_id}:${p.permission_id}`)
          )
          const target = new Set(heldSet)
          for (const it of r.items || []) {
            const key = `${it.system_id}:${it.permission_id}`
            if ((it.kind || 'grant') === 'revoke') target.delete(key)
            else target.add(key)
          }
          // Programy oznaczone „domyślnie zaznaczone" — dokładamy te, których
          // pracownik nie ma. Pozycje jawnie odebrane w TYM wniosku zostają
          // odznaczone (pętla wyżej ma pierwszeństwo nad domyślnymi).
          const revokedHere = new Set(
            (r.items || []).filter(it => (it.kind || 'grant') === 'revoke')
              .map(it => `${it.system_id}:${it.permission_id}`)
          )
          for (const s of active.filter(x => x.default_checked)) {
            for (const p of (byId[s.id] || [])) {
              // Uprawnienia administracyjne NIGDY nie są zaznaczane z automatu —
              // muszą być zawsze świadomą decyzją wnioskodawcy.
              if (p.is_admin_option) continue
              const key = `${s.id}:${p.id}`
              if (!heldSet.has(key) && !revokedHere.has(key)) target.add(key)
            }
          }
          setSystems(active)
          setPermsBySys(byId)
          setHeld(heldSet)
          setPicked(target)

          // Wartości kontrolek: najpierw OBECNY stan pracownika (dla pozycji
          // już posiadanych), potem to, co zapisano wcześniej w tym wniosku.
          const fv = {}
          const heldVals = {}
          for (const p of (permsRes.data.permissions || [])) {
            const k = `${p.system_id}:${p.permission_id}`
            if (p.custom_values && Object.keys(p.custom_values).length) {
              heldVals[k] = { ...p.custom_values }
              fv[k] = { ...(fv[k] || {}), ...p.custom_values }
            }
          }
          for (const it of r.items || []) {
            if (it.custom_values && Object.keys(it.custom_values).length) {
              const k = `${it.system_id}:${it.permission_id}`
              fv[k] = { ...(fv[k] || {}), ...it.custom_values }
            }
          }
          setHeldValues(heldVals)
          setFieldValues(fv)
        }
      } catch {
        if (alive) setErr('Nie udało się pobrać listy uprawnień')
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [isSelect, isRevoke, r.unit_id, r.worker_user_id])

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

  /** Zaznacz/odznacz program wymagający wyboru zakresu. Odznaczenie czyści też
   *  wszystkie jego wybrane poduprawnienia (żeby nie zostały „ukryte"). */
  function toggleScope(s) {
    const sid = s.id
    const perms = permsBySys[sid] || []
    const anySel = perms.some(p => picked.has(`${sid}:${p.id}`))
    const active = openSys.has(sid) || anySel
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
  // Filtr widoku uprawnień (jak w projekcie): wszystkie / posiadane / tylko zmiany.
  const [permFilter, setPermFilter] = useState('all')   // 'all' | 'held' | 'changes'
  const [sysQuery, setSysQuery] = useState('')

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

  // Wartości pól dodatkowych (poziom/zakres dostępu) — osobno dla KAŻDEJ
  // pozycji: klucz "system_id:permission_id" → { nazwaPola: wartość }.
  function setFieldValue(key, label, val) {
    setFieldValues(prev => ({ ...prev, [key]: { ...(prev[key] || {}), [label]: val } }))
  }

  // Krok wyboru: „select" = wybór i zatwierdzenie w jednym. Decyzja: approve/reject.
  const mkItem = (k, kind) => {
    const [sid, pid] = k.split(':').map(Number)
    const item = { system_id: sid, permission_id: pid, kind }
    // Pola dodatkowe dotyczą tylko nadawania — przy odbieraniu nie mają sensu.
    if (kind === 'grant') {
      const vals = fieldValues[k]
      if (vals && Object.keys(vals).length) item.custom_values = vals
    }
    return item
  }
  // Dyf stanu docelowego (dla nadania/zmiany).
  const toGrant  = [...picked].filter(k => !held.has(k))
  const toRevoke = [...held].filter(k => !picked.has(k))
  const changeCount = toGrant.length + toRevoke.length

  // Predykat filtra widoku (zakładki: wszystkie / posiadane / tylko zmiany).
  function passPermFilter(key) {
    if (permFilter === 'held') return held.has(key)
    if (permFilter === 'changes') {
      const st = permChangeState(key, held, picked)
      return st === 'grant' || st === 'revoke'
    }
    return true
  }
  const _sq = sysQuery.trim().toLowerCase()
  // Czy system pasuje do globalnej szukajki (po nazwie albo nazwie uprawnienia).
  function sysMatchesQuery(s) {
    if (!_sq) return true
    if ((s.name || '').toLowerCase().includes(_sq)) return true
    return (permsBySys[s.id] || []).some(
      p => (p.permission_name || '').toLowerCase().includes(_sq))
  }

  // Uprawnienia POSIADANE, którym zmieniono wartość kontrolki (np. inny zakres
  // rejestrów). Traktujemy je jak ponowne nadanie z nową wartością — inaczej
  // nie dałoby się zmienić samego zakresu bez odbierania i nadawania od nowa.
  const scopeChanged = [...picked].filter(k => {
    if (!held.has(k)) return false
    const [sid, pid] = k.split(':').map(Number)
    const p = (permsBySys[sid] || []).find(x => x.id === pid)
    if (!p || (p.input_type || 'none') === 'none') return false
    const now = (fieldValues[k] || {})[p.permission_name] || ''
    const before = (heldValues[k] || {})[p.permission_name] || ''
    return now !== before
  })

  // Sprawdź pola obowiązkowe nadawanych pozycji (backend waliduje to samo,
  // ale lepiej powiedzieć od razu, niż po odrzuconym zapisie).
  function missingRequired() {
    return missingRequiredFields([...toGrant, ...scopeChanged], systems,
                                fieldValues, permsBySys)
  }

  // Zbuduj payload akcji dla obiegu (bez oświadczenia — to dokłada się osobno).
  function buildActionBody(action) {
    if (isSelect) {
      const items = isRevoke
        ? [...picked].map(k => mkItem(k, 'revoke'))
        : [...toGrant.map(k => mkItem(k, 'grant')),
           ...scopeChanged.map(k => mkItem(k, 'grant')),
           ...toRevoke.map(k => mkItem(k, 'revoke'))]
      const wfAction = action === 'approve' ? 'select' : 'reject'
      // expected_node_id — jeśli przełożony wykonał już ten krok, backend zwróci
      // 409 zamiast zastosować ten wybór do kolejnego etapu obiegu.
      return { action: wfAction, comment, items,
               ...(r.current_node_id ? { expected_node_id: r.current_node_id } : {}) }
    }
    const body = { action, comment }
    if (r.current_node_id) body.expected_node_id = r.current_node_id
    // Odmowy pozycji dołączamy tylko przy zatwierdzaniu (kierownik nadrzędny).
    if (action === 'approve') {
      const ds = Object.entries(denials).map(([item_id, c]) => ({
        item_id: Number(item_id), comment: (c || '').trim() || null,
      }))
      if (ds.length) body.denials = ds
    }
    return body
  }

  // Wyślij akcję; `declaration` dokładane, gdy zebrane w modalu. Backend jest
  // twardą bramką: brak oświadczenia przy nadaniu → 428, wtedy otwieramy modal.
  async function sendAction(action, declaration = null) {
    const body = buildActionBody(action)
    if (declaration) body.declaration = declaration
    try {
      await workflowAction(r.id, body)
      toast(action === 'reject'
        ? `Odrzucono wniosek #${r.id}.`
        : isSelect
          ? (twoStage ? `Wybór wysłany do akceptacji kierownika wyższego rzędu (#${r.id}).`
                      : `Wybór zatwierdzony — wniosek #${r.id} trafił do realizacji przez IT.`)
          : `Zatwierdzono wniosek #${r.id}.`)
      setReviewOpen(false)
      onDone()
    } catch (ex) {
      const st = ex.response?.status
      const det = ex.response?.data?.detail
      if (st === 428 && det?.code === 'DECLARATION_REQUIRED') {
        // Zbierz oświadczenie i ponów TĘ akcję.
        setDeclText(det.declaration_text || '')
        setDeclPending(action)
        setReviewOpen(false)
        setBusy(false)
        return
      }
      setErr((typeof det === 'string' ? det : det?.message) || 'Błąd operacji')
      setReviewOpen(false)
      setBusy(false)
      // 409 = krok wykonała już inna osoba (np. przełożony) — odśwież dane
      // wniosku, żeby widok pokazał jego aktualny etap.
      if (st === 409) onRefresh?.()
    }
  }

  // v3.1 — wysłanie wyboru idzie przez krok PODSUMOWANIA (ReviewDialog).
  const [reviewOpen, setReviewOpen] = useState(false)

  async function submit(action) {
    if (action === 'reject') {
      const ok = await confirmDialog({
        title: `Odrzucić wniosek #${r.id}?`,
        message: 'Wniosek zostanie zamknięty bez realizacji. Powód wpisz w polu „Uwagi” — trafi do historii.',
        confirmLabel: 'Odrzuć wniosek', danger: true,
      })
      if (!ok) return
      setBusy(true); setErr(null)
      await sendAction('reject')
      return
    }
    if (isSelect && action === 'approve' && !isRevoke) {
      const noScope = missingScopeSystems(systems, openSys, picked, permsBySys)
      if (noScope.length) {
        setErr('Zaznaczono program bez wybranego zakresu uprawnień: '
               + noScope.join(', ') + '. Wybierz co najmniej jedno uprawnienie albo odznacz program.')
        return
      }
      const miss = missingRequired()
      if (miss.length) { setErr('Uzupełnij pola obowiązkowe: ' + miss.join('; ')); return }
    }
    if (isSelect && action === 'approve') { setErr(null); setReviewOpen(true); return }
    setBusy(true); setErr(null)
    await sendAction(action)
  }

  // Ostateczne wysłanie z okna podsumowania (po potwierdzeniu uprawnień admina).
  async function confirmFromReview() {
    if (!isRevoke) {
      // Nadanie uprawnień administracyjnych wymaga twardego potwierdzenia.
      const admins = adminGrantNames([...toGrant, ...scopeChanged], systems, permsBySys)
      if (!(await confirmAdminRights(admins))) { setErr(ADMIN_CONFIRM_ABORTED); setReviewOpen(false); return }
    }
    setBusy(true); setErr(null)
    await sendAction('approve')
  }

  // Kopiowanie uprawnień od współpracownika → nowy stan docelowy.
  function copyFrom(perms) {
    const res = buildCopiedSelection(perms, systems, permsBySys)
    setPicked(res.keys)
    setFieldValues(prev => ({ ...prev, ...res.values }))
    setPermFilter('changes')
    return { count: res.keys.size, skippedAdmin: res.skippedAdmin, skippedUnavailable: res.skippedUnavailable }
  }

  // Wiersze podsumowania.
  const reviewGrants = isRevoke ? [] : describeKeys([...toGrant, ...scopeChanged], systems, permsBySys, fieldValues)
  const reviewRevokes = isRevoke
    ? revokeList.filter(p => picked.has(`${p.system_id}:${p.permission_id}`)).map(p => ({
        key: `${p.system_id}:${p.permission_id}`, system: p.system_name, perm: p.permission_name, values: [],
      }))
    : describeKeys(toRevoke, systems, permsBySys)

  const title = isSelect
    ? (isRevoke ? 'Odebranie uprawnień' : 'Wybór uprawnień')
    : isDecision
      ? 'Decyzja'
      : `Wniosek #${r.id}`

  const _subtitle = isSelect
    ? 'Zaznacz stan docelowy uprawnień — po wysłaniu wniosek trafi do IT.'
    : isDecision ? 'Zatwierdź albo odrzuć wniosek.' : 'Podgląd wniosku i jego obiegu.'
  const _steps = buildWorkflowSteps({
    sent: true, nodeType: r.current_node_type, status: r.status,
    requiresHigher: r.requires_higher_approval, kind: r.kind,
  })
  const _summary = [
    { label: 'Pracownik', value: r.worker_name },
    { label: 'Stanowisko', value: r.worker_position || '—' },
    { label: 'Komórka', value: `${r.department_name || '—'} · ${r.unit_name || '—'}` },
    { label: 'Złożył(a)', value: r.requested_by_name || r.created_by_name || '—' },
  ]
  // Numeracja sekcji 01, 02, … — liczone tylko sekcje faktycznie widoczne.
  let _sec = 0
  const sec = () => ++_sec

  return (
    <>
    <RequestViewShell
      icon={ListChecks} kind={['revoke', 'change'].includes(r.kind) ? r.kind : 'grant'} kindLabel={kindLabel(r.kind)}
      statusText={`Wniosek #${r.id}${(isSelect || isDecision) ? ' · czeka na Ciebie' : ''}`}
      perspective={(isSelect || isDecision) ? perspectiveLabel(r.current_node_type) : null}
      waiting={!(isSelect || isDecision) ? waitingText(r) : null}
      title={title} subtitle={_subtitle}
      backLabel="← Wróć do listy" onBack={onClose}
      steps={_steps} summary={_summary} historyRequestId={r.id}
      historyCreatedBy={r.created_by_name}
      footerLeft={isSelect && !loading
        ? (isRevoke
            ? <>Do odebrania: <strong>{picked.size}</strong></>
            : <><strong style={{ color: 'var(--color-success-text)' }}>+{toGrant.length + scopeChanged.length}</strong> nadania
                {' · '}<strong style={{ color: 'var(--color-error-text)' }}>−{toRevoke.length}</strong> odebrania</>)
        : null}
      footerActions={<>
        <button className="btn btn--ghost" onClick={onClose} disabled={busy}>
          {(isSelect || isDecision) ? 'Anuluj' : 'Zamknij'}
        </button>
        {(isSelect || isDecision) && (
          <button className="btn btn--danger" onClick={() => submit('reject')} disabled={busy}>
            <X size={14} /> Odrzuć
          </button>
        )}
        {isSelect && (
          <button className="btn btn--success" onClick={() => submit('approve')}
                  disabled={busy || loading || (isRevoke
                    ? picked.size === 0
                    : (toGrant.length === 0 && toRevoke.length === 0 && scopeChanged.length === 0))}>
            <Check size={14} /> Sprawdź i wyślij
          </button>
        )}
        {isDecision && (
          <button className="btn btn--success" onClick={() => submit('approve')} disabled={busy}>
            <Check size={14} /> Zatwierdź
          </button>
        )}
      </>}>

          <Section n={sec()} title="Pracownik">
            <WorkerCard name={r.worker_name}
              sub={[r.worker_username, r.worker_email].filter(Boolean).join(' · ') || null}
              cols={[
                { label: 'Wydział', value: deptFull(r.department_name, r.department_description) },
                { label: 'Jednostka', value: r.unit_name },
                { label: r.employment_from ? 'Od dnia' : 'Stanowisko',
                  value: r.employment_from ? fmtDate(r.employment_from) : r.worker_position },
              ]} />
          </Section>

          {/* Zmiany uprawnień — poza krokiem wyboru (tam jest picker).
              Kierownik nadrzędny widzi tu jasno, co jest NADAWANE, a co ODBIERANE. */}
          {!isSelect && (
            <Section n={sec()} title="Zmiany uprawnień we wniosku">
              {isDecision && twoStage && (
                <p style={{ color: 'var(--color-text-muted)', fontSize: 12, margin: '4px 0 0' }}>
                  Możesz odmówić nadania pojedynczej pozycji (z komentarzem) — reszta wniosku przejdzie dalej.
                </p>
              )}
              <div style={{ marginTop: 8 }}>
                <PermissionChanges items={items}
                  deny={isDecision && twoStage
                    ? { can: true, map: denials, toggle: toggleDeny, setComment: setDenyComment,
                        save: saveDeny, remove: removeDeny, busyId: denyBusy }
                    : undefined} />
              </div>
            </Section>
          )}

          {r.manager_comment && (
            <Section n={sec()} title="Komentarz kierownika">
              <div style={{ background: 'var(--bg-secondary)', padding: '10px 14px', borderRadius: 6 }}>{r.manager_comment}</div>
            </Section>
          )}


          {/* --- Akcja: wybór uprawnień --- */}
          {isSelect && (
            <Section n={sec()} title={isRevoke ? 'Uprawnienia do odebrania' : 'Uprawnienia — stan docelowy'}>
              <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: '0 0 10px' }}>
                {isRevoke
                  ? 'Zaznacz uprawnienia do odebrania (domyślnie wszystkie).'
                  : <>Zaznacz nowe, aby je <strong>nadać</strong>; odznacz posiadane, aby je <strong>odebrać</strong>.</>}
              </p>
              {/* Jawna informacja, dokąd trafi wniosek po zatwierdzeniu. */}
              <div role="note" className={`alert ${twoStage ? 'alert--info' : 'alert--success'}`}
                   style={{ fontSize: 13, marginBottom: 12, border: 'none', borderRadius: 8, padding: '10px 14px' }}>
                {twoStage
                  ? 'Ścieżka dwustopniowa: po zatwierdzeniu wniosek trafi do akceptacji kierownika wyższego rzędu, a dopiero potem do realizacji przez IT.'
                  : 'Ścieżka jednostopniowa: po zatwierdzeniu wniosek trafi bezpośrednio do realizacji przez IT (bez akceptacji wyższego rzędu).'}
              </div>

              {/* Pasek filtrów + szukajka (jak w projekcie) — tylko ścieżka nadania. */}
              {!loading && !isRevoke && systems.length > 0 && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10,
                              flexWrap: 'wrap', marginBottom: 10 }}>
                  <div role="group" aria-label="Filtr" style={{ display: 'inline-flex', padding: 3, gap: 2,
                                borderRadius: 8, background: 'var(--color-neutral-bg)' }}>
                    {[
                      { id: 'all',     label: 'Wszystkie' },
                      { id: 'held',    label: 'Posiadane' },
                      { id: 'changes', label: `Tylko zmiany${changeCount ? ' · ' + changeCount : ''}` },
                    ].map(t => (
                      <button key={t.id} type="button" aria-pressed={permFilter === t.id}
                              onClick={() => setPermFilter(t.id)}
                              style={{
                                border: 'none', cursor: 'pointer', fontSize: 13, minHeight: 36,
                                padding: '0 14px', borderRadius: 6, font: 'inherit',
                                fontWeight: permFilter === t.id ? 700 : 600,
                                background: permFilter === t.id ? 'var(--color-card)' : 'transparent',
                                color: permFilter === t.id ? 'var(--color-heading)' : 'var(--color-text-muted)',
                              }}>
                        {t.label}
                      </button>
                    ))}
                  </div>
                  <div style={{ position: 'relative', flex: '1 1 240px', minWidth: 160 }}>
                    <Search size={15} aria-hidden="true" style={{
                      position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)',
                      color: 'var(--color-text-muted)', pointerEvents: 'none' }} />
                    <input className="form-control" value={sysQuery} aria-label="Szukaj systemu lub zakresu"
                           style={{ paddingLeft: 34, fontSize: 14, minHeight: 42, borderRadius: 8 }}
                           placeholder="Szukaj systemu lub zakresu…"
                           onChange={e => setSysQuery(e.target.value)} />
                  </div>
                  <CopyFromColleague excludeUserId={r.worker_user_id} onCopy={copyFrom} disabled={busy} />
                </div>
              )}

              {loading ? (
                <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie uprawnień…</div>
              ) : isRevoke ? (
                revokeList.length === 0 ? (
                  <div className="alert alert--warning">
                    Ten pracownik nie ma obecnie żadnych nadanych uprawnień do odebrania.
                  </div>
                ) : (
                  <div style={{ maxHeight: 'min(46vh, 420px)', overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 6, padding: 12, background: 'var(--bg-secondary)' }}>
                    {revokeList.map(p => {
                      const key = `${p.system_id}:${p.permission_id}`
                      return (
                        <label key={key} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer', padding: '4px 0' }}>
                          <input type="checkbox" checked={picked.has(key)}
                                 style={{ width: 16, height: 16, flexShrink: 0 }}
                                 onChange={() => togglePerm(p.system_id, p.permission_id)} />
                          <span style={{ fontWeight: 600, color: 'var(--color-heading)' }}>{p.system_name}</span>
                          <span style={{ color: 'var(--color-text-muted)' }}>›</span>
                          <span>{p.permission_name}</span>
                        </label>
                      )
                    })}
                  </div>
                )
              ) : systems.length === 0 ? (
                <div className="alert alert--warning">Brak zdefiniowanych systemów — poproś administratora o konfigurację.</div>
              ) : (
                <div style={{ maxHeight: 'min(46vh, 420px)', overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 6, padding: 12, background: 'var(--bg-secondary)' }}>
                  {systems.filter(sysMatchesQuery).map(s => {
                    const perms = permsBySys[s.id] || []
                    // „Tylko dostęp" = jedna pozycja na cały program.
                    const { main, admin } = splitAdminPerm(perms)
                    const adminKey = admin ? `${s.id}:${admin.id}` : null
                    if (s.access_only) {
                      const p = main[0]
                      if (!p) return null
                      const key = `${s.id}:${p.id}`
                      // Filtr zakładek: ukryj system, gdy jego pozycja nie pasuje.
                      if (!passPermFilter(key) && !(adminKey && passPermFilter(adminKey))) return null
                      return (
                        <SystemBlock
                          key={s.id} name={s.name} description={s.description}
                          checked={picked.has(key)}
                          onToggle={() => togglePerm(s.id, p.id)}
                          accent={permChangeState(key, held, picked)}
                          headerStyle={changeTextStyle(permChangeState(key, held, picked))}
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
                            <ChangeBadge st={permChangeState(key, held, picked)} />
                          </>}
                        >
                          <AdminPermRow
                            perm={admin} checked={picked.has(adminKey)} indent={0}
                            onToggle={() => togglePerm(s.id, admin.id)}
                            extra={<ChangeBadge st={permChangeState(adminKey, held, picked)} />}
                            disabled={!picked.has(key) && !(adminKey && picked.has(adminKey))}
                          />
                        </SystemBlock>
                      )
                    }
                    // Program z listą uprawnień. Domyślnie bez zbiorczego
                    // checkboxa (zaznaczanie per grupa). Jeśli program wymaga
                    // wyboru zakresu (require_scope) — dokładamy checkbox
                    // nagłówka: dopóki nieaktywny, treść jest wyszarzona.
                    const allKeys = main.map(x => `${s.id}:${x.id}`)
                    const selHere = allKeys.filter(k => picked.has(k)).length
                    const gated = isScopeGated(s)
                    const anySel = selHere > 0 || (adminKey && picked.has(adminKey))
                    const active = !gated || openSys.has(s.id) || anySel
                    // Pod filtrem „posiadane"/„tylko zmiany" ukryj system bez pasujących pozycji.
                    if (permFilter !== 'all') {
                      const anyMain = main.some(p => passPermFilter(`${s.id}:${p.id}`))
                      const adminOk = adminKey && passPermFilter(adminKey)
                      if (!anyMain && !adminOk) return null
                    }
                    return (
                      <SystemBlock
                        key={s.id} name={s.name} description={s.description}
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
                          <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Brak uprawnień</div>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                            {groupPerms(main).map(({ group, items }) => {
                              const gkey = `${s.id}|${group}`
                              const q = (groupQuery[gkey] || '').toLowerCase()
                              const sysHit = _sq && (s.name || '').toLowerCase().includes(_sq)
                              const visible = items
                                .filter(p => isPermVisible(p, `${s.id}:${p.id}`, held, picked))
                                .filter(p => passPermFilter(`${s.id}:${p.id}`))
                                .filter(p => !q || p.permission_name.toLowerCase().includes(q))
                                .filter(p => !_sq || sysHit
                                             || p.permission_name.toLowerCase().includes(_sq))
                              const selCount = items.filter(
                                p => picked.has(`${s.id}:${p.id}`)).length
                              return (
                                <PermGroupSection
                                  key={gkey} group={group} count={items.length}
                                  selectedCount={selCount}
                                  query={groupQuery[gkey] || ''}
                                  onQuery={v => setGroupQuery(x => ({ ...x, [gkey]: v }))}
                                  onToggleAll={() => toggleMany(
                                    visible.map(p => `${s.id}:${p.id}`))}
                                >
                                  {visible.length === 0 && (
                                    <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                                      Brak pozycji pasujących do wyszukiwania.
                                    </div>
                                  )}
                                  {subgroupPerms(visible).map(({ subgroup, items: subItems }) => (
                                    <div key={subgroup || '_nosub'}>
                                      {subgroup && (
                                        <div style={{
                                          fontSize: 12, fontStyle: 'italic', letterSpacing: '.02em',
                                          color: 'var(--color-text-muted)', margin: '4px 0 2px 2px',
                                        }}>
                                          ↳ {subgroup}
                                        </div>
                                      )}
                                      {subItems.map(p => {
                              const key = `${s.id}:${p.id}`
                              return (
                                <div key={p.id} style={subgroup ? { marginLeft: 14 } : undefined}>
                                <label style={{
                                  display: 'flex', alignItems: 'center', gap: 8, fontSize: 14,
                                  cursor: 'pointer', ...changeStyle(permChangeState(key, held, picked)),
                                }}>
                                  <input type="checkbox" checked={picked.has(key)}
                                         style={{ width: 16, height: 16, flexShrink: 0 }}
                                         onChange={() => togglePerm(s.id, p.id)} />
                                  <span style={changeTextStyle(permChangeState(key, held, picked))}>
                                    {p.permission_name}
                                  </span>
                                  <ChangeBadge st={permChangeState(key, held, picked)} />
                                  {p.is_active === false && (
                                    <span className="badge badge--warning" style={{ fontSize: 11 }}
                                          title="Pozycja wycofana w systemie źródłowym">
                                      wycofane
                                    </span>
                                  )}
                                  {p.description && <span style={{ color: 'var(--color-text-muted)' }}>— {p.description}</span>}
                                </label>
                                  <PermInput
                                    input={permInput(p)} name={p.permission_name}
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
                              extra={<ChangeBadge st={permChangeState(adminKey, held, picked)} />}
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
            </Section>
          )}

          {/* --- Komentarz (dla obu akcji) --- */}
          {(isSelect || isDecision) && (
            <Section n={sec()} title="Uwagi" note="opcjonalne">
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label className="form-label">{isSelect ? 'Informacja dla IT' : 'Komentarz · widoczny w historii'}</label>
                <textarea className="form-control" style={{ minHeight: 70 }}
                          value={comment} onChange={e => setComment(e.target.value)} />
              </div>
            </Section>
          )}

          {err && <div className="alert alert--error">{err}</div>}
    </RequestViewShell>

      <ReviewDialog
        open={reviewOpen}
        workerName={r.worker_name}
        grants={reviewGrants}
        revokes={reviewRevokes}
        target={isRevoke
          ? 'Po wysłaniu wniosek trafi do realizacji (odebranie uprawnień).'
          : twoStage
            ? 'Po wysłaniu wniosek trafi do akceptacji kierownika wyższego rzędu, potem do IT.'
            : 'Po wysłaniu wniosek trafi bezpośrednio do realizacji przez IT.'}
        confirmLabel={twoStage && !isRevoke ? 'Wyślij do akceptacji' : 'Zatwierdź i przekaż do realizacji'}
        busy={busy}
        onBack={() => setReviewOpen(false)}
        onConfirm={confirmFromReview}
      />

      {declPending && (
        <DeclarationModal
          text={declText}
          busy={busy}
          onClose={() => { setDeclPending(null); setBusy(false) }}
          onConfirm={(declaration) => {
            setBusy(true)
            const action = declPending
            setDeclPending(null)
            sendAction(action, declaration)
          }}
        />
      )}
    </>
  )
}
