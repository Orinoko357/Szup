import { useEffect, useMemo, useState } from 'react'
import { Users, RefreshCw, FilePlus, Search, ListChecks, Send, ChevronDown, ChevronRight } from 'lucide-react'
import {
  listMyWorkers, listSystems, listPermissions, createRequest, listRequestTypes,
} from '../api'
import {
  permChangeState, changeStyle, ChangeBadge,
} from '../components/PermissionChanges'
import DeclarationModal from '../components/DeclarationModal'
import RequestViewShell, { buildWorkflowSteps, Section, WorkerCard } from '../components/RequestView'
import PermInput, {
  permInput, missingRequiredFields, splitAdminPerm, AdminPermRow,
  adminGrantNames, confirmAdminRights, ADMIN_CONFIRM_ABORTED,
  groupPerms, subgroupPerms, isPermVisible, PermGroupSection, SystemBlock,
  isScopeGated, missingScopeSystems,
} from '../components/ItemFields'

export default function MyTeam() {
  const [workers, setWorkers] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr]         = useState(null)
  const [search, setSearch]   = useState('')
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
      setErr(ex.response?.data?.detail || 'Nie udało się pobrać listy pracowników')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return workers
    return workers.filter(w =>
      [w.full_name, w.username, w.email, w.department_name, w.unit_name]
        .some(v => (v || '').toLowerCase().includes(q))
    )
  }, [workers, search])

  // Otwarty formularz wniosku = pełnoekranowy widok (zamiast listy).
  if (requestFor) {
    return <NewRequestModal worker={requestFor}
                            onClose={() => setRequestFor(null)}
                            onDone={() => { setRequestFor(null); load() }} />
  }

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Moi pracownicy</div>
          <div className="page-header__sub">
            Pracownicy, którymi kierujesz — możesz dla nich występować
            o nadanie lub zmianę uprawnień
          </div>
        </div>
        <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
          <RefreshCw size={14} /> Odśwież
        </button>
      </div>

      <div className="card" style={{ marginBottom: 12 }}>
        <div style={{ position: 'relative', maxWidth: 420 }}>
          <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
          <input
            className="form-input"
            style={{ paddingLeft: 30 }}
            placeholder="Szukaj: imię, login, e-mail, wydział…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      <div className="card">
        {loading ? (
          <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>
        ) : workers.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>
            <Users size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Nie kierujesz żadnym wydziałem albo nie ma przypisanych do
            niego aktywnych pracowników. Sprawdź konfigurację wydziałów
            w panelu administracyjnym.
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ color: 'var(--color-text-muted)', padding: 16 }}>
            <Search size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
            Brak wyników dla „{search}"
          </div>
        ) : (
          <table className="data-table">
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
                    <td style={{ fontWeight: 600 }}>
                      {w.full_name || '—'}
                      {w.is_self && (
                        <span className="badge badge--info" style={{ fontSize: 10, marginLeft: 8 }}
                              title="Możesz złożyć wniosek sam dla siebie">
                          Ja
                        </span>
                      )}
                    </td>
                    <td style={{ fontFamily: 'var(--font-mono)', fontSize: 12 }}>{w.username}</td>
                    <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{w.email || '—'}</td>
                    <td>{w.department_name || '—'}</td>
                    <td style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>{w.unit_name || '—'}</td>
                    <td>
                      {perms.length === 0 ? (
                        <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>brak</span>
                      ) : (
                        <button
                          className="btn btn--ghost btn--sm"
                          onClick={() => toggleExpand(w.id)}
                          title={open ? 'Zwiń' : 'Pokaż uprawnienia'}
                        >
                          {open ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                          <span className="badge badge--info" style={{ marginLeft: 4 }}>{perms.length}</span>
                        </button>
                      )}
                    </td>
                    <td>
                      <button className="btn btn--action btn--sm" onClick={() => setRequestFor(w)}>
                        <FilePlus size={13} /> Nowy wniosek
                      </button>
                    </td>
                  </tr>,
                  open && perms.length > 0 && (
                    <tr key={`${w.id}-perms`}>
                      <td colSpan={7} style={{ background: 'var(--bg-secondary)' }}>
                        <div style={{ padding: '8px 4px' }}>
                          <div className="form-label" style={{ marginBottom: 6 }}>
                            Aktualnie posiadane uprawnienia
                          </div>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                            {perms.map(p => (
                              <span key={`${p.system_id}:${p.permission_id}`}
                                    style={{
                                      fontSize: 12, padding: '4px 10px',
                                      border: '1px solid var(--color-border)',
                                      borderRadius: 'var(--radius-control)',
                                      background: 'var(--bg-primary)',
                                    }}>
                                <strong style={{ color: 'var(--color-navy)' }}>{p.system_name}</strong>
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
        )}
      </div>
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
        setErr('Nie udało się pobrać listy uprawnień')
      } finally {
        setLoading(false)
      }
    })()
  }, [w.unit_id])

  // Stan docelowy → dyf względem tego, co pracownik ma obecnie.
  const toGrant  = useMemo(() => [...picked].filter(k => !held.has(k)), [picked, held])
  const toRevoke = useMemo(() => [...held].filter(k => !picked.has(k)), [picked, held])

  // Posiadane pozycje, którym zmieniono ZAKRES (pola) — traktujemy jak ponowne
  // nadanie z nowym zakresem, żeby dało się zmienić sam zakres.
  const scopeChanged = useMemo(() => [...picked].filter(k => {
    if (!held.has(k)) return false
    const [sid, pid] = k.split(':').map(Number)
    const p = (permsBySys[sid] || []).find(x => x.id === pid)
    if (!p || (p.input_type || 'none') === 'none') return false
    const now = (fieldValues[k] || {})[p.permission_name] || ''
    const before = (heldValues[k] || {})[p.permission_name] || ''
    return now !== before
  }), [picked, held, permsBySys, fieldValues, heldValues])

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
  const StateBadge = ChangeBadge

  async function submit() {
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
    const admins = adminGrantNames([...toGrant, ...scopeChanged], systems, permsBySys)
    if (!confirmAdminRights(admins)) { setErr(ADMIN_CONFIRM_ABORTED); return }

    setBusy(true); setErr(null)
    const mk = (k, kind) => {
      const [sid, pid] = k.split(':').map(Number)
      const item = { system_id: sid, permission_id: pid, kind }
      if (kind === 'grant') {
        const vals = fieldValues[k]
        if (vals && Object.keys(vals).length) item.custom_values = vals
      }
      return item
    }
    // Stan docelowy: zaznaczone-nowe → nadanie, odznaczone-posiadane → odebranie,
    // posiadane ze zmienionym zakresem → ponowne nadanie z nowym zakresem.
    const items = [
      ...toGrant.map(k => mk(k, 'grant')),
      ...scopeChanged.map(k => mk(k, 'grant')),
      ...toRevoke.map(k => mk(k, 'revoke')),
    ]
    await sendRequest(items)
  }

  // Wyślij wniosek; `declaration` dokładane po zebraniu w modalu. W 1-stopniu
  // auto-select ląduje wprost na IT — backend zażąda oświadczenia (428), wtedy
  // pokazujemy modal i ponawiamy z podpisem.
  async function sendRequest(items, declaration = null) {
    const body = {
      kind:            'change',
      worker_name:     w.full_name || w.username,
      worker_email:    w.email || null,
      worker_position: null,
      worker_user_id:  w.id,
      unit_id:         w.unit_id,
      department_id:   w.department_id,
      items,
      request_type_id: requestTypeId || null,
    }
    if (declaration) body.declaration = declaration
    try {
      await createRequest(body)
      onDone()
    } catch (ex) {
      const st = ex.response?.status
      const det = ex.response?.data?.detail
      if (st === 428 && det?.code === 'DECLARATION_REQUIRED') {
        setDeclText(det.declaration_text || '')
        setDeclItems(items)
        setBusy(false)
        return
      }
      setErr((typeof det === 'string' ? det : det?.message) || 'Błąd składania wniosku')
      setBusy(false)
    }
  }

  const _steps = buildWorkflowSteps({
    sent: true, nodeType: 'select_permissions',
    requiresHigher: !!w.requires_higher_approval, kind: 'grant',
  })
  const _summary = [
    { label: 'Pracownik', value: w.full_name || w.username },
    { label: 'Komórka', value: `${w.department_name || '—'} · ${w.unit_name || '—'}` },
    { label: 'Zmiany', value: `+${toGrant.length} / −${toRevoke.length}` },
    { label: 'Akceptacja', value: w.requires_higher_approval ? 'wymagana' : 'nie wymagana' },
  ]

  return (
    <>
    <RequestViewShell
      icon={ListChecks} kind="grant" kindLabel="Zatrudnienie"
      statusText="Nowy wniosek · nie wysłany"
      title={`Wniosek o uprawnienia — ${w.full_name || w.username}`}
      subtitle="Zaznacz stan docelowy uprawnień — po wysłaniu wniosek trafi do kierownika nadrzędnego lub do IT."
      backLabel="← Wróć do moich pracowników" onBack={onClose}
      steps={_steps} summary={_summary} history={[]}
      footerLeft={<>+{toGrant.length} nadania · −{toRevoke.length} odebrania</>}
      footerActions={<>
        <button className="btn btn--ghost" onClick={onClose} disabled={busy}>Anuluj</button>
        <button className="btn btn--success" onClick={submit} disabled={busy || loading || noChange}>
          <Send size={13} /> Wyślij wniosek (+{toGrant.length} / −{toRevoke.length})
        </button>
      </>}>
          <Section n={1} title="Pracownik">
            <WorkerCard name={w.full_name || w.username}
              sub={[w.username, w.email].filter(Boolean).join(' · ') || null}
              cols={[
                { label: 'Wydział', value: w.department_name },
                { label: 'Jednostka', value: w.unit_name },
                { label: 'Stanowisko', value: w.title },
              ]} />
          </Section>

          <Section n={2} title="Uprawnienia — stan docelowy">
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 8 }}>
            Zaznaczone i oznaczone <span className="badge badge--success" style={{ fontSize: 9 }}>posiada</span>{' '}
            to uprawnienia, które pracownik ma obecnie. To <strong>stan docelowy</strong>:
            zaznacz dodatkowe, aby je <strong>nadać</strong>; odznacz posiadane, aby je <strong>odebrać</strong>.
          </div>
          {loading ? (
            <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie uprawnień…</div>
          ) : systems.length === 0 ? (
            <div className="alert alert--warning">
              Brak zdefiniowanych systemów — poproś administratora o konfigurację.
            </div>
          ) : (
            <div style={{ maxHeight: 'min(62vh, 640px)', overflowY: 'auto', border: '1px solid var(--color-border)', borderRadius: 6, padding: 8, background: 'var(--bg-secondary)' }}>
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
                        <span className="badge badge--info" style={{ fontSize: 9 }}>
                          dostęp
                        </span>
                        {s.default_checked && (
                          <span className="badge badge--warning" style={{ fontSize: 9 }}
                                title="Zaznaczone automatycznie — możesz odznaczyć">
                            domyślne
                          </span>
                        )}
                        <StateBadge st={permState(key)} />
                      </>}
                    >
                      <AdminPermRow
                        perm={admin} checked={picked.has(adminKey)} indent={0}
                        onToggle={() => togglePerm(s.id, admin.id)}
                        extra={<StateBadge st={permState(adminKey)} />}
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
                        <span className="badge badge--success" style={{ fontSize: 9 }}>
                          wybrano: {selHere}
                        </span>
                      )}
                      {gated && active && !anySel && (
                        <span className="badge badge--warning" style={{ fontSize: 9 }}
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
                              <StateBadge st={permState(key)} />
                              {p.is_active === false && (
                                <span className="badge badge--warning" style={{ fontSize: 9 }}
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
                          extra={<StateBadge st={permState(adminKey)} />}
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
            <div className={`alert ${noChange ? 'alert--info' : 'alert--success'}`}
                 style={{ fontSize: 12, marginTop: 12 }}>
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
              <label className="form-label">Komentarz · uzasadnienie wniosku</label>
              <textarea className="form-control" style={{ minHeight: 70 }}
                        value={comment} onChange={e => setComment(e.target.value)}
                        placeholder="Uzasadnienie / kontekst wniosku" />
            </div>
          </Section>

          {err && <div className="alert alert--error">{err}</div>}
    </RequestViewShell>

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
