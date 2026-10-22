import { useEffect, useMemo, useRef, useState } from 'react'
import { Copy, Search, X } from 'lucide-react'
import { listMyWorkers, userPermissions, errorMessage } from '../api'
import { toast } from './ui/feedback'

/**
 * v3.1 — „Skopiuj uprawnienia od współpracownika”: kierownik wybiera osobę
 * ze swojego zespołu, a do stanu docelowego wniosku DOKŁADAMY jej obecne
 * uprawnienia (+ wartości pól). Wyłącznie frontend — istniejące endpointy
 * (my-workers, /users/{id}/permissions, oba z kontrolą zakresu kierownika).
 */

/** Dołóż uprawnienia współpracownika do bieżącego zaznaczenia.
 *  Wynik = bieżące zaznaczenie ∪ uprawnienia kolegi — NIC nie jest odbierane
 *  (także własne uprawnienia administracyjne i spoza jednostki pracownika
 *  zostają). Pomijamy: pozycje niedostępne w tej jednostce, wycofane
 *  (is_active === false), uprawnienia administracyjne (świadoma decyzja)
 *  oraz ZAPLANOWANE ODEBRANIA — posiadane, które użytkownik odznaczył
 *  (`held` bez `basePicked`), i pozycje „revoke” z wniosku (`revoked`).
 *  Kopiowanie nie może po cichu cofnąć decyzji o odebraniu. */
export function buildCopiedSelection(colleaguePerms, permsBySys, basePicked = new Set(), baseValues = {},
                                     { held = new Set(), revoked = new Set() } = {}) {
  const keys = new Set(basePicked)
  const values = { ...baseValues }
  let added = 0, skippedAdmin = 0, skippedUnavailable = 0, skippedRevoke = 0
  for (const p of colleaguePerms || []) {
    const k = `${p.system_id}:${p.permission_id}`
    const def = (permsBySys?.[p.system_id] || []).find(x => x.id === p.permission_id)
    if (!def || def.is_active === false) { skippedUnavailable++; continue }
    if (def.is_admin_option) { skippedAdmin++; continue }
    if (keys.has(k)) continue      // już zaznaczone — zostawiamy jego wartości
    if (held.has(k) || revoked.has(k)) { skippedRevoke++; continue }   // zaplanowane odebranie
    keys.add(k); added++
    if (p.custom_values && Object.keys(p.custom_values).length) values[k] = { ...p.custom_values }
  }
  return { keys, values, added, skippedAdmin, skippedUnavailable, skippedRevoke }
}

export default function CopyFromColleague({ excludeUserId, onCopy, disabled }) {
  const [open, setOpen]       = useState(false)
  const [workers, setWorkers] = useState(null)
  const [q, setQ]             = useState('')
  const [busyId, setBusyId]   = useState(null)
  const [err, setErr]         = useState(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (!open || workers) return
    listMyWorkers().then(r => setWorkers(r.data || []))
      .catch(ex => { setWorkers([]); setErr(errorMessage(ex, 'Nie udało się pobrać listy pracowników')) })
  }, [open, workers])
  useEffect(() => { if (open) setTimeout(() => inputRef.current?.focus(), 30) }, [open])

  const list = useMemo(() => {
    const ql = q.trim().toLowerCase()
    return (workers || [])
      .filter(w => w.id !== excludeUserId)
      .filter(w => !ql || [w.full_name, w.username, w.title, w.department_name]
        .some(v => (v || '').toLowerCase().includes(ql)))
  }, [workers, q, excludeUserId])

  async function pick(w) {
    setBusyId(w.id); setErr(null)
    try {
      const perms = Array.isArray(w.permissions)
        ? w.permissions
        : ((await userPermissions(w.id)).data?.permissions || [])
      const res = onCopy(perms, w)
      setOpen(false)
      const extra = []
      if (res?.skippedAdmin) extra.push(`pominięto uprawnienia administracyjne: ${res.skippedAdmin}`)
      if (res?.skippedUnavailable) extra.push(`niedostępne lub wycofane: ${res.skippedUnavailable}`)
      if (res?.skippedRevoke) extra.push(`pominięto pozycje zaplanowane do odebrania: ${res.skippedRevoke}`)
      const who = w.full_name || w.username
      toast((res?.count
              ? `Dodano ${res.count} uprawnień od ${who}. Obecne uprawnienia pracownika pozostają bez zmian — sprawdź przed wysłaniem.`
              : `${who} nie ma uprawnień, których brakuje temu pracownikowi.`)
            + (extra.length ? `\n(${extra.join('; ')})` : ''), { tone: 'info', timeout: 8000 })
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się pobrać uprawnień tej osoby'))
    } finally { setBusyId(null) }
  }

  return (
    <>
      <button type="button" className="btn btn--ghost" style={{ minHeight: 42 }} disabled={disabled}
              onClick={() => setOpen(true)}>
        <Copy size={14} aria-hidden="true" /> Skopiuj od współpracownika
      </button>
      {open && (
        <div role="presentation" onMouseDown={e => { if (e.target === e.currentTarget) setOpen(false) }}
             style={{ position: 'fixed', inset: 0, zIndex: 2500, background: 'rgba(13,20,36,.5)',
                      display: 'grid', placeItems: 'center', padding: 16 }}>
          <div role="dialog" aria-modal="true" aria-labelledby="copy-col-title"
               onKeyDown={e => { if (e.key === 'Escape') setOpen(false) }}
               style={{ width: '100%', maxWidth: 520, maxHeight: 'calc(100vh - 32px)', display: 'flex',
                        flexDirection: 'column', background: 'var(--color-card)', color: 'var(--color-text)',
                        border: '1px solid var(--color-border)', borderRadius: 10,
                        boxShadow: '0 16px 40px rgba(13,20,36,.3)' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: '18px 20px 0' }}>
              <div style={{ flex: 1 }}>
                <h2 id="copy-col-title" style={{ margin: 0, fontSize: 18, fontWeight: 800, color: 'var(--color-heading)' }}>
                  Skopiuj uprawnienia od współpracownika
                </h2>
                <p style={{ margin: '6px 0 0', fontSize: 13, color: 'var(--color-text-muted)' }}>
                  Do zaznaczenia zostaną dodane obecne uprawnienia wybranej osoby — nic nie zostanie odebrane,
                  a pozycje zaplanowane do odebrania pozostaną odznaczone.
                  Przed wysłaniem możesz je zmienić. Uprawnienia administracyjne nie są kopiowane.
                </p>
              </div>
              <button type="button" aria-label="Zamknij" onClick={() => setOpen(false)}
                      style={{ width: 44, height: 44, border: 0, background: 'transparent', cursor: 'pointer',
                               color: 'var(--color-text-muted)', display: 'grid', placeItems: 'center' }}>
                <X size={18} />
              </button>
            </div>
            <div style={{ padding: '12px 20px 0', position: 'relative' }}>
              <Search size={15} aria-hidden="true" style={{ position: 'absolute', left: 32, top: '50%', marginTop: 6,
                                                            transform: 'translateY(-50%)', color: 'var(--color-text-muted)' }} />
              <input ref={inputRef} className="form-control" aria-label="Szukaj współpracownika"
                     placeholder="Nazwisko, login, stanowisko, komórka…" value={q}
                     onChange={e => setQ(e.target.value)} style={{ paddingLeft: 34, minHeight: 44 }} />
            </div>
            <div style={{ padding: '10px 20px 20px', overflowY: 'auto' }}>
              {err && <div className="alert alert--error" style={{ marginBottom: 8 }}>{err}</div>}
              {workers === null ? (
                <div style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>Ładowanie…</div>
              ) : list.length === 0 ? (
                <div style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>
                  {workers.length === 0 ? 'Brak pracowników w Twoim zakresie.' : `Brak wyników dla „${q}”.`}
                </div>
              ) : (
                <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {list.map(w => (
                    <li key={w.id}>
                      <button type="button" disabled={busyId != null} onClick={() => pick(w)}
                              style={{ width: '100%', textAlign: 'left', display: 'flex', alignItems: 'center', gap: 10,
                                       minHeight: 52, padding: '8px 12px', borderRadius: 8, cursor: 'pointer',
                                       border: '1px solid var(--color-border)', background: 'var(--color-card)',
                                       color: 'inherit', font: 'inherit' }}>
                        <span style={{ flex: 1, minWidth: 0 }}>
                          <span style={{ display: 'block', fontWeight: 700 }}>{w.full_name || w.username}</span>
                          <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>
                            {[w.title, w.username, w.department_name].filter(Boolean).join(' · ')}
                          </span>
                        </span>
                        <span className="badge badge--neutral" style={{ fontSize: 11 }}>
                          {busyId === w.id ? 'Kopiuję…' : `${(w.permissions || []).length} upr.`}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
