import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Search, FileText, User, X, ClipboardList } from 'lucide-react'
import { searchUsers, listUsers, listRequests, getRequest, errorMessage } from '../api'
import { workRoles, hasAnyRole } from '../roles'
import { MANAGER_NODES, statusLabel } from '../labels'

/**
 * Wyszukiwarka globalna (v3.1) — Ctrl+K / „/” albo przycisk w belce.
 * Zależna od roli (korzysta wyłącznie z istniejących endpointów i ich zakresów):
 *  - wnioski: po numerze („#12” / „12”) oraz po nazwisku pracownika
 *    (kierownik/IT — lista wniosków w ich zakresie; kadry — własne zgłoszenia),
 *  - osoby: kierownik/kadry — /users/search (zakres jak w formularzach),
 *    administrator — lista użytkowników; IT — skrót do rejestru uprawnień.
 */
const SEARCH_CSS = `
.szup-search-btn {
  display: inline-flex; align-items: center; gap: 8px; min-height: 40px; padding: 0 10px 0 12px;
  border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-card);
  color: var(--color-text-muted); font: 500 13px var(--font-base); cursor: pointer; min-width: 200px;
  transition: border-color .15s, color .15s;
}
.szup-search-btn:hover, .szup-search-btn:focus-visible { border-color: var(--color-heading); color: var(--color-heading); outline: none; }
.szup-search-btn:focus-visible { box-shadow: 0 0 0 2px var(--color-focus-ring); }
.szup-search-btn__label { flex: 1; text-align: left; }
.szup-search-btn__kbd {
  font: 600 11px var(--font-mono); padding: 2px 6px; border-radius: 4px;
  border: 1px solid var(--color-border); background: var(--bg-secondary); color: var(--color-text-muted);
}
@media (max-width: 1200px) {
  .szup-search-btn { min-width: 150px; }
}
@media (max-width: 720px) {
  .szup-search-btn { min-width: 0; }
  .szup-search-btn__label, .szup-search-btn__kbd { display: none; }
}
`

export default function GlobalSearch() {
  const navigate = useNavigate()
  const roles = workRoles()   // superadmin — bez wniosków (tylko konfiguracja)
  const isManager = hasAnyRole(roles, ['manager'])
  const isIT      = hasAnyRole(roles, ['it_staff'])
  const isHR      = hasAnyRole(roles, ['hr'])
  const isAdmin   = hasAnyRole(roles, ['admin', 'superadmin'])
  const canSearchUsers = hasAnyRole(roles, ['manager', 'hr', 'superadmin'])
  const canSeeRequests = isManager || isIT || isHR

  const [open, setOpen]     = useState(false)
  const [q, setQ]           = useState('')
  const [active, setActive] = useState(0)
  const [people, setPeople] = useState([])
  const [byNumber, setByNumber] = useState(null)
  const [busy, setBusy]     = useState(false)
  const [searchErr, setSearchErr] = useState(null)
  const reqCache   = useRef(null)   // wnioski w zakresie — pobierane raz na otwarcie
  const usersCache = useRef(null)   // admin: lista użytkowników
  const inputRef   = useRef(null)
  const dialogRef  = useRef(null)
  const lastFocus  = useRef(null)

  // Skróty: Ctrl/Cmd+K wszędzie, „/” poza polami tekstowymi.
  useEffect(() => {
    function onKey(e) {
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName) || e.target?.isContentEditable
      if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); openSearch() }
      else if (e.key === '/' && !typing && !open) { e.preventDefault(); openSearch() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  function openSearch() {
    lastFocus.current = document.activeElement
    setQ(''); setPeople([]); setByNumber(null); setActive(0); setSearchErr(null)
    reqCache.current = null
    setOpen(true)
  }
  function close() {
    setOpen(false)
    setTimeout(() => lastFocus.current?.focus?.(), 0)
  }

  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 20) }, [open])

  // Lista wniosków w zakresie roli — raz na otwarcie okna.
  useEffect(() => {
    if (!open || !canSeeRequests || reqCache.current) return
    const params = (!isManager && !isIT && isHR) ? { scope: 'mine' } : {}
    listRequests(params).then(r => { reqCache.current = r.data || []; setActive(a => a) })
      .catch(ex => { reqCache.current = []; setSearchErr(errorMessage(ex, 'Nie udało się wczytać wniosków')) })
  }, [open])

  // Wyszukiwanie osób / wniosku po numerze (debounce).
  useEffect(() => {
    if (!open) return
    const term = q.trim()
    setActive(0)
    const num = term.replace(/^#/, '')
    const t = setTimeout(async () => {
      setBusy(true)
      try {
        if (/^\d+$/.test(num) && canSeeRequests) {
          try { const r = await getRequest(Number(num)); setByNumber(r.data) }
          catch { setByNumber(null) }
        } else setByNumber(null)

        if (term.length >= 2 && !/^#?\d+$/.test(term)) {
          if (canSearchUsers) {
            const r = await searchUsers(term).catch(ex => {
              setSearchErr(errorMessage(ex, 'Wyszukiwanie osób nie powiodło się')); return { data: [] }
            })
            setPeople((r.data || []).slice(0, 8))
          } else if (isAdmin) {
            if (!usersCache.current) {
              const r = await listUsers().catch(ex => {
                setSearchErr(errorMessage(ex, 'Nie udało się wczytać użytkowników')); return { data: [] }
              })
              usersCache.current = r.data || []
            }
            const f = fold(term)
            setPeople(usersCache.current
              .filter(u => fold(`${u.full_name || ''} ${u.username || ''}`).includes(f))
              .slice(0, 8))
          } else setPeople([])
        } else setPeople([])
      } finally { setBusy(false) }
    }, 200)
    return () => clearTimeout(t)
  }, [q, open])

  // Dokąd prowadzi wniosek — wg bieżącego kroku (current_node_type) i tego,
  // czy użytkownik może na nim działać (can_act; oba pola zwraca GET /requests/{id}
  // i lista bez scope):
  //  - krok kierowniczy z can_act → „Do obsługi”,
  //  - krok „it_execute” dla IT → „Realizacja IT”,
  //  - wszystko inne → podgląd: kierownik w „Moich wnioskach” (widok dociąga
  //    wniosek spoza listy jako podgląd), samo IT w „Realizacji IT”.
  // Gdy backend nie zwróci pól (starsza wersja) — dotychczasowe zachowanie.
  // Samo HR → Kartoteka.
  function requestTarget(r) {
    if (!isManager && !isIT) return '/hr'
    const node = r.current_node_type
    const known = node !== undefined || r.can_act !== undefined
    let tab
    if (!known) {
      tab = (isManager && !isIT) ? 'handle' : 'it'
    } else if (isManager && MANAGER_NODES.includes(node) && r.can_act) {
      tab = 'handle'
    } else if (isIT && node === 'it_execute' && r.can_act !== false) {
      tab = 'it'
    } else {
      tab = isManager ? 'mine' : 'it'
    }
    return `/requests?tab=${tab}&open=${r.id}`
  }
  function personTarget(p) {
    const name = encodeURIComponent(p.full_name || p.username || '')
    if (isManager) return `/my-team?q=${name}`
    if (isIT || isAdmin) return `/registry?q=${name}`
    return '/hr'
  }

  const results = useMemo(() => {
    const out = []
    const term = q.trim()
    if (byNumber) out.push({ key: `n${byNumber.id}`, type: 'request', r: byNumber })
    if (term.length >= 2 && reqCache.current) {
      const f = fold(term)
      reqCache.current
        .filter(r => fold(r.worker_name || '').includes(f) && r.id !== byNumber?.id)
        .slice(0, 6)
        .forEach(r => out.push({ key: `r${r.id}`, type: 'request', r }))
    }
    people.forEach(p => out.push({ key: `p${p.id}`, type: 'person', p }))
    if (term.length >= 2 && (isIT || isAdmin) && !/^#?\d+$/.test(term)) {
      out.push({ key: 'registry', type: 'registry', term })
    }
    return out
  }, [q, people, byNumber, open, busy])

  function choose(item) {
    if (!item) return
    close()
    if (item.type === 'request') navigate(requestTarget(item.r))
    else if (item.type === 'person') navigate(personTarget(item.p))
    else if (item.type === 'registry') navigate(`/registry?q=${encodeURIComponent(item.term)}`)
  }

  function onKeyDown(e) {
    if (e.key === 'Escape') { e.preventDefault(); close() }
    else if (e.key === 'ArrowDown') { e.preventDefault(); setActive(a => Math.min(a + 1, results.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(a => Math.max(a - 1, 0)) }
    else if (e.key === 'Enter') { e.preventDefault(); choose(results[active]) }
    else if (e.key === 'Tab') {
      // Pułapka fokusu w oknie: pole ↔ przycisk zamknięcia.
      const f = dialogRef.current?.querySelectorAll('input, button')
      if (!f?.length) return
      const first = f[0], last = f[f.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
  }

  const hint = canSeeRequests
    ? (canSearchUsers || isAdmin ? 'Nazwisko, login lub numer wniosku (#12)…' : 'Nazwisko pracownika lub numer wniosku (#12)…')
    : 'Nazwisko lub login…'

  return (
    <>
      <button type="button" className="szup-search-btn" onClick={openSearch}
              aria-label="Szukaj (Ctrl+K)" aria-haspopup="dialog">
        <Search size={15} aria-hidden="true" />
        <span className="szup-search-btn__label">Szukaj…</span>
        <kbd className="szup-search-btn__kbd">Ctrl K</kbd>
      </button>

      {open && (
        <div role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) close() }}
             style={{ position: 'fixed', inset: 0, zIndex: 2800, background: 'rgba(13,20,36,.45)',
                      display: 'flex', justifyContent: 'center', alignItems: 'flex-start', padding: '10vh 16px 16px' }}>
          <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Wyszukiwarka" onKeyDown={onKeyDown}
               style={{ width: '100%', maxWidth: 620, background: 'var(--color-card)', color: 'var(--color-text)',
                        border: '1px solid var(--color-border)', borderRadius: 10,
                        boxShadow: '0 20px 48px rgba(13,20,36,.35)', overflow: 'hidden' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 6px 6px 16px',
                          borderBottom: '1px solid var(--color-border)' }}>
              <Search size={18} aria-hidden="true" style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
              <input ref={inputRef} value={q} onChange={e => setQ(e.target.value)}
                     role="combobox" aria-expanded={results.length > 0} aria-controls="gs-list"
                     aria-autocomplete="list" aria-label="Szukaj"
                     aria-activedescendant={results[active] ? `gs-${results[active].key}` : undefined}
                     placeholder={hint} autoComplete="off" spellCheck={false}
                     style={{ flex: 1, minHeight: 48, border: 0, outline: 'none', background: 'transparent',
                              color: 'var(--color-text)', font: 'inherit', fontSize: 16 }} />
              <button type="button" aria-label="Zamknij wyszukiwarkę" onClick={close}
                      style={{ width: 44, height: 44, display: 'grid', placeItems: 'center', border: 0,
                               borderRadius: 6, background: 'transparent', color: 'var(--color-text-muted)', cursor: 'pointer' }}>
                <X size={18} />
              </button>
            </div>

            <ul id="gs-list" role="listbox" aria-label="Wyniki"
                style={{ listStyle: 'none', margin: 0, padding: results.length ? 6 : 0, maxHeight: '55vh', overflowY: 'auto' }}>
              {results.map((it, i) => {
                const sel = i === active
                const Icon = it.type === 'request' ? FileText : it.type === 'person' ? User : ClipboardList
                let title, sub
                if (it.type === 'request') {
                  title = `Wniosek #${it.r.id} · ${it.r.worker_name}`
                  sub = [statusLabel(it.r.status), it.r.department_name].filter(Boolean).join(' · ')
                } else if (it.type === 'person') {
                  title = it.p.full_name || it.p.username
                  sub = [it.p.title, it.p.username, it.p.department_name].filter(Boolean).join(' · ')
                } else {
                  title = `Szukaj „${it.term}” w rejestrze uprawnień`
                  sub = 'Kto co ma — stan bieżący'
                }
                return (
                  <li key={it.key} id={`gs-${it.key}`} role="option" aria-selected={sel}
                      onMouseEnter={() => setActive(i)} onMouseDown={e => { e.preventDefault(); choose(it) }}
                      style={{ display: 'flex', alignItems: 'center', gap: 12, minHeight: 52, padding: '6px 12px',
                               borderRadius: 8, cursor: 'pointer',
                               background: sel ? 'var(--bg-secondary)' : 'transparent',
                               outline: sel ? '2px solid var(--color-focus-ring)' : 'none', outlineOffset: -2 }}>
                    <span aria-hidden="true" style={{ width: 32, height: 32, flexShrink: 0, borderRadius: 8,
                          display: 'grid', placeItems: 'center', background: 'var(--bg-secondary)', color: 'var(--color-heading)' }}>
                      <Icon size={16} />
                    </span>
                    <span style={{ minWidth: 0 }}>
                      <span style={{ display: 'block', fontSize: 14, fontWeight: 700, color: 'var(--color-text)' }}>{title}</span>
                      {sub && <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)',
                                            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sub}</span>}
                    </span>
                  </li>
                )
              })}
            </ul>

            {searchErr && (
              <div role="alert" className="alert alert--error" style={{ margin: '8px 12px 0' }}>{searchErr}</div>
            )}
            {results.length === 0 && (
              <div role="status" style={{ padding: '18px 16px', fontSize: 14, color: 'var(--color-text-muted)' }}>
                {busy ? 'Szukam…'
                  : q.trim().length < 2 && !/^#?\d+$/.test(q.trim())
                    ? 'Wpisz co najmniej 2 znaki albo numer wniosku.'
                    : 'Brak wyników w Twoim zakresie.'}
              </div>
            )}
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', padding: '8px 16px', fontSize: 12,
                          color: 'var(--color-text-muted)', borderTop: '1px solid var(--color-border)', background: 'var(--bg-secondary)' }}>
              <span>↑ ↓ wybór</span><span>Enter otwórz</span><span>Esc zamknij</span>
            </div>
          </div>
        </div>
      )}

      <style>{SEARCH_CSS}</style>
    </>
  )
}

function fold(s) {
  return (s || '').toLowerCase().replace(/ł/g, 'l').normalize('NFKD').replace(/[̀-ͯ]/g, '')
}

