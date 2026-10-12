import { useEffect, useState } from 'react'
import { Wrench, RefreshCw, CheckCircle, Link2, UserPlus, Plus } from 'lucide-react'
import {
  listRequests, workflowAction, linkRequestWorker, listItStaff, assignRequest,
  listSystems,
} from '../api'

/** Kierownik IT = osoba mająca JEDNOCZEŚNIE rolę „manager" i „it_staff".
 *  TYLKO ona może przekazywać wnioski (admin/superadmin — nie).
 *  Może też zrealizować wniosek sama, bez przekazywania. */
function useIsItManager() {
  const raw = localStorage.getItem('szup_user')
  const u = raw ? JSON.parse(raw) : null
  const roles = Array.isArray(u?.roles) ? u.roles : (u?.role ? [u.role] : [])
  return roles.includes('manager') && roles.includes('it_staff')
}
import { fmtDate } from '../serverTime'
import WorkflowRibbon from '../components/WorkflowRibbon'
import PermissionChanges from '../components/PermissionChanges'
import AddPermissionsPicker from '../components/AddPermissionsPicker'
import NameChangeQueue from '../components/NameChangeQueue'
import {
  missingRequiredFields, adminGrantNames, confirmAdminRights, ADMIN_CONFIRM_ABORTED,
} from '../components/ItemFields'

export default function IT() {
  // Pozwól wejść wprost na zakładkę „Zmiany nazwiska" z pulpitu (?tab=names).
  const initialTab = new URLSearchParams(window.location.search).get('tab') === 'names'
    ? 'names' : 'requests'
  const [tab, setTab] = useState(initialTab)
  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Panel IT</div>
          <div className="page-header__sub">Realizacja wniosków o uprawnienia i zmian nazwiska</div>
        </div>
      </div>
      <div className="tabs" style={{ marginTop: 0 }}>
        <button className={`tab-btn${tab === 'requests' ? ' active' : ''}`}
                onClick={() => setTab('requests')}>Wnioski o uprawnienia</button>
        <button className={`tab-btn${tab === 'names' ? ' active' : ''}`}
                onClick={() => setTab('names')}>Zmiany nazwiska</button>
      </div>
      {tab === 'requests' ? <RequestsTab /> : <NameChangeQueue />}
    </div>
  )
}

function RequestsTab() {
  const [requests, setRequests] = useState([])
  const [loading, setLoading]   = useState(true)
  const [filter, setFilter]     = useState('pending_it')
  const [openReq, setOpenReq]   = useState(null)   // jeden wspólny widok: podgląd + realizacja

  async function load() {
    setLoading(true)
    try {
      const params = filter !== 'all' ? { status: filter } : {}
      const r = await listRequests(params)
      setRequests(r.data)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [filter])

  const STATUS_BADGE = { pending_selection: 'badge--warning', pending_it: 'badge--info', completed: 'badge--success', pending_manager: 'badge--warning', rejected: 'badge--error' }
  const STATUS_LABELS = { pending_selection: 'Wybór uprawnień', pending_it: 'Do realizacji', completed: 'Zrealizowany', pending_manager: 'Oczekuje kierownika', rejected: 'Odrzucony' }

  return (
    <>
      <div className="tabs" style={{ marginTop: 0 }}>
        {[['pending_it','Do realizacji'],['all','Wszystkie']].map(([v,l]) => (
          <button key={v} className={`tab-btn${filter===v?' active':''}`} onClick={() => setFilter(v)}>{l}</button>
        ))}
      </div>
      <div className="card">
        {loading ? <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div> : requests.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>Brak wniosków</div>
        ) : (
          <table className="data-table">
            <thead><tr><th>#</th><th>Pracownik</th><th>Wydział</th><th>Jednostka</th><th>Uprawnień</th><th>Status</th><th>Przypisany</th><th>Data</th><th></th></tr></thead>
            <tbody>
              {requests.map(r => (
                <tr key={r.id}>
                  <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{r.id}</td>
                  <td style={{ fontWeight: 600 }}>
                    {r.worker_name}
                    {r.kind === 'revoke' && (
                      <span className="badge badge--warning" style={{ fontSize: 10, marginLeft: 8 }}>ustanie</span>
                    )}
                  </td>
                  <td>{r.department_name || '—'}</td>
                  <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{r.unit_name || '—'}</td>
                  <td>{r.items?.length||0}</td>
                  <td><span className={`badge ${STATUS_BADGE[r.status]||'badge--neutral'}`}>{STATUS_LABELS[r.status]||r.status}</span></td>
                  <td style={{ fontSize: 12 }}>
                    {r.assigned_to_name
                      ? <span className="badge badge--info">{r.assigned_to_name}</span>
                      : <span style={{ color: 'var(--color-text-muted)' }}>nieprzypisany</span>}
                  </td>
                  <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{fmtDate(r.created_at)}</td>
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
        )}
      </div>
      {openReq && (
        <RequestModal request={openReq} onClose={() => setOpenReq(null)}
                      onDone={() => { setOpenReq(null); load() }} />
      )}
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
function RequestModal({ request: r, onClose, onDone }) {
  const isRevoke   = r.kind === 'revoke'
  const canRealize = r.status === 'pending_it'
  const canLink    = r.status === 'completed' && !r.worker_user_id
  // Login AD potrzebny tylko wtedy, gdy wniosek nie jest jeszcze dowiązany do
  // konta pracownika (nowy pracownik). Przy zmianie/ustaniu konto już istnieje.
  const needsAd = !r.worker_user_id

  // Pozycje wniosku — PermissionChanges rozbija je po kierunku (nadanie/odebranie).
  const items = r.items || []

  const isItManager = useIsItManager()
  const [comment, setComment]       = useState('')
  const [adUsername, setAdUsername] = useState(() => (needsAd ? _guessAdUsername(r) : ''))
  // Odmowy pojedynczych pozycji przez IT przy realizacji: { [item_id]: komentarz }.
  const [denials, setDenials] = useState({})
  const toggleDeny = (id) => setDenials(prev => {
    const next = { ...prev }
    if (Object.prototype.hasOwnProperty.call(next, id)) delete next[id]
    else next[id] = ''
    return next
  })
  const setDenyComment = (id, v) => setDenials(prev => ({ ...prev, [id]: v }))
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
      .catch(() => setAddSystems([]))
  }, [showAdd, r.unit_id, addSystems.length])

  // Przekazanie wniosku pracownikowi IT (tylko kierownik IT / admin).
  const [itStaff, setItStaff]   = useState([])
  const [assignee, setAssignee] = useState(r.assigned_to_user_id || '')
  useEffect(() => {
    if (!isItManager || !canRealize) return
    listItStaff().then(res => setItStaff(res.data)).catch(() => setItStaff([]))
  }, [isItManager, canRealize])

  async function assign() {
    setBusy(true); setErr(null)
    try {
      await assignRequest(r.id, assignee ? Number(assignee) : null)
      onDone()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się przekazać wniosku'); setBusy(false)
    }
  }

  async function realize() {
    const u = adUsername.trim()
    if (needsAd && !u) { setErr('Wpisz sAMAccountName pracownika (login AD)'); return }

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
      if (!confirmAdminRights(admins)) { setErr(ADMIN_CONFIRM_ABORTED); return }
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
      onDone()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd'); setBusy(false)
    }
  }

  async function link() {
    const u = adUsername.trim()
    if (!u) { setErr('Wpisz sAMAccountName pracownika'); return }
    setBusy(true); setErr(null)
    try {
      await linkRequestWorker(r.id, u)
      onDone()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd'); setBusy(false)
    }
  }

  const title = canRealize
    ? `${isRevoke ? 'Odebranie uprawnień' : 'Realizacja'} — wniosek #${r.id}`
    : `Wniosek #${r.id}`

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal__header">
          <span className="modal__title">
            {title}
            {isRevoke && <span className="badge badge--warning" style={{ fontSize: 10, marginLeft: 8 }}>ustanie</span>}
          </span>
          <button className="modal__close" onClick={onClose}>×</button>
        </div>
        <div className="modal__body">
          {/* --- Dane wniosku --- */}
          <div className="form-row mb-4">
            <div><div className="form-label">Pracownik</div><strong>{r.worker_name}</strong></div>
            <div><div className="form-label">Stanowisko</div>{r.worker_position || '—'}</div>
          </div>
          <div className="form-row mb-4">
            <div><div className="form-label">Wydział</div>{r.department_name || '—'}</div>
            <div><div className="form-label">Jednostka</div>{r.unit_name || '—'}</div>
          </div>

          <div className="mb-4">
            <div className="form-label">Zmiany uprawnień do wykonania</div>
            <p style={{ color: 'var(--color-text-muted)', fontSize: 12, margin: '4px 0 0' }}>
              Możesz odmówić realizacji pojedynczej pozycji (z komentarzem) — reszta zostanie nadana.
            </p>
            <div style={{ marginTop: 8 }}>
              <PermissionChanges items={items}
                deny={{ can: true, map: denials, toggle: toggleDeny, setComment: setDenyComment }} />
            </div>
          </div>

          {r.manager_comment && (
            <div className="mb-4">
              <div className="form-label">Komentarz kierownika</div>
              <div style={{ background: 'var(--bg-secondary)', padding: '10px 14px', borderRadius: 6 }}>{r.manager_comment}</div>
            </div>
          )}

          <div className="mb-4">
            <div className="form-label">Obieg wniosku</div>
            {/* Akcję obsługuje ten modal — ribbon pokazuje sam postęp i historię. */}
            <WorkflowRibbon requestId={r.id} unitId={r.unit_id} showActions={false} />
          </div>

          {/* --- Akcja: realizacja / odebranie --- */}
          {canRealize && (
            <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16, marginTop: 4 }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-navy)', marginBottom: 10 }}>
                {isRevoke ? 'Potwierdzenie odebrania' : 'Realizacja'}
              </div>
              {needsAd ? (
                <div className="form-group">
                  <label className="form-label">Login AD (sAMAccountName) pracownika *</label>
                  <input className="form-control" value={adUsername}
                         onChange={e => setAdUsername(e.target.value)}
                         placeholder="np. jkowalski" autoComplete="off" spellCheck={false} />
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                    <UserPlus size={11} style={{ verticalAlign: 'middle', marginRight: 4 }} />
                    Jeżeli konto nie istnieje w SZUP, zostanie założone automatycznie (typ LDAP).
                  </div>
                </div>
              ) : (
                <div className="alert alert--warning" style={{ fontSize: 12 }}>
                  Wykonaj w systemach powyższe zmiany (nadaj / odbierz), a następnie potwierdź.
                </div>
              )}
              {/* Dokładanie uprawnień — tylko przy nadaniu/zmianie.
                  Przy ustaniu stosunku pracy nie ma czego dokładać. */}
              {!isRevoke && (
                <div className="form-group">
                  <button
                    type="button"
                    className="btn btn--ghost btn--sm"
                    onClick={() => setShowAdd(v => !v)}
                    style={{ marginBottom: showAdd ? 8 : 0 }}
                  >
                    <Plus size={13} /> Dołóż uprawnienia (wymagane technicznie)
                    {addPicked.size > 0 && (
                      <span className="badge badge--warning" style={{ fontSize: 10, marginLeft: 6 }}>
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
                </div>
              )}

              <div className="form-group">
                <label className="form-label">
                  {addPicked.size > 0
                    ? 'Uzasadnienie dodanych uprawnień *'
                    : 'Komentarz IT (opcjonalny)'}
                </label>
                <textarea className="form-control" style={{ minHeight: 60 }}
                          placeholder={addPicked.size > 0
                            ? 'Dlaczego te uprawnienia są konieczne?' : ''}
                          value={comment} onChange={e => setComment(e.target.value)} />
              </div>
            </div>
          )}

          {/* --- Przekazanie wniosku (kierownik IT) --- */}
          {canRealize && isItManager && (
            <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16, marginTop: 4 }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-navy)', marginBottom: 6 }}>
                Przekazanie do realizacji
              </div>
              <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 10 }}>
                Możesz zrealizować wniosek samodzielnie (przycisk poniżej) albo przekazać go
                pracownikowi IT. Przekazanie jest oznaczeniem „kto się tym zajmuje" — nie blokuje
                realizacji przez innych.
              </p>
              <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
                <div className="form-group" style={{ flex: 1, marginBottom: 0 }}>
                  <label className="form-label">Pracownik IT</label>
                  <select className="form-control" value={assignee}
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
            </div>
          )}

          {/* --- Akcja: dowiązanie konta (zrealizowany bez konta) --- */}
          {canLink && (
            <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16, marginTop: 4 }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: 'var(--color-navy)', marginBottom: 6 }}>
                Dowiąż konto pracownika
              </div>
              <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 10 }}>
                Wniosek zrealizowano, ale nie dowiązano konta. Wpisz sAMAccountName, aby uprawnienia
                pojawiły się w profilu pracownika i w widoku struktury.
              </p>
              <div className="form-group">
                <label className="form-label">Login AD (sAMAccountName) *</label>
                <input className="form-control" value={adUsername}
                       onChange={e => setAdUsername(e.target.value)}
                       placeholder="np. jkowalski" autoComplete="off" spellCheck={false} />
              </div>
            </div>
          )}

          {err && <div className="alert alert--error">{err}</div>}
        </div>
        <div className="modal__footer">
          <button className="btn btn--ghost" onClick={onClose} disabled={busy}>
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
        </div>
      </div>
    </div>
  )
}

