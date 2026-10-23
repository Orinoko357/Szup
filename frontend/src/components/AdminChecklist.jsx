import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, ChevronDown, Info } from 'lucide-react'
import { getAdminHealth } from '../api'

/**
 * Lista kontrolna konfiguracji + sygnały jakości danych (v3.1) — pulpit admina.
 * Dane: GET /api/settings/health →
 *   { checks: [{key, label, ok, detail, link, level?}], issues: [{key, label, count, link}] }
 * level: "recommendation" — zalecenie (np. szyfrowanie LDAP): łagodniejszy styl,
 * NIE liczy się do „Gotowe X z Y” ani nie blokuje stanu „Konfiguracja kompletna”.
 * level: "warning" (v3.10) — ostrzeżenie (np. superadmin z rolami operacyjnymi):
 * wyróżnione kolorem ostrzeżenia, ale — jak w backendzie — NIE jest wymagane
 * i nie blokuje „Konfiguracja kompletna”. Pozostałe pozycje (np. hr_department —
 * komórka kadrowa wyznaczona i ma członków) są wymagane.
 * Gdy wszystko gotowe i brak problemów — jedna kompaktowa linia z „Pokaż szczegóły”.
 * Błąd/ładowanie → nic nie renderujemy (pulpit ma działać bez tej karty).
 */
// Tekst tylko dla czytników ekranu (stan pozycji listy).
const SR_ONLY = { position: 'absolute', width: 1, height: 1, padding: 0, margin: -1, overflow: 'hidden',
                  clip: 'rect(0,0,0,0)', whiteSpace: 'nowrap', border: 0 }

export default function AdminChecklist() {
  const [data, setData] = useState(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    let alive = true
    getAdminHealth()
      .then(r => { if (alive) setData(r.data || null) })
      .catch(() => { if (alive) setData(null) })
    return () => { alive = false }
  }, [])

  if (!data) return null
  const checks = Array.isArray(data.checks) ? data.checks : []
  const issues = (Array.isArray(data.issues) ? data.issues : []).filter(i => (i.count || 0) > 0)
  const isRec = c => c.level === 'recommendation'
  const isWarn = c => c.level === 'warning'
  const required = checks.filter(c => !isRec(c) && !isWarn(c))
  const done = required.filter(c => c.ok).length
  const allGood = done === required.length && issues.length === 0
  const recPending = checks.filter(c => isRec(c) && !c.ok).length
  const warnPending = checks.filter(c => isWarn(c) && !c.ok).length
  const expanded = !allGood || open

  return (
    <section aria-label="Konfiguracja systemu" className="card" style={{ padding: 0, overflow: 'hidden', marginBottom: 18 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, padding: '14px 18px',
                    borderBottom: expanded ? '1px solid var(--color-border)' : 'none' }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: 'var(--color-heading)' }}>
          {allGood ? 'Konfiguracja kompletna' : 'Konfiguracja systemu'}
        </h2>
        {allGood ? (
          <span aria-hidden="true" style={{ width: 22, height: 22, borderRadius: '50%', display: 'grid', placeItems: 'center',
                                            background: 'var(--color-success-bg)', color: 'var(--color-success)' }}>
            <Check size={14} />
          </span>
        ) : (
          <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
            Gotowe <strong style={{ color: 'var(--color-text)' }}>{done}</strong> z {required.length}
          </span>
        )}
        {warnPending > 0 && (
          <span className="badge badge--warning" style={{ fontSize: 11 }}
                title="Ostrzeżenia nie blokują pracy systemu, ale warto je przejrzeć">
            ostrzeżenia: {warnPending}
          </span>
        )}
        {recPending > 0 && (
          <span className="badge badge--info" style={{ fontSize: 11 }}
                title="Zalecenia nie blokują pracy systemu">
            zalecenia: {recPending}
          </span>
        )}
        <div style={{ flex: 1 }} />
        {allGood && (
          <button type="button" className="btn btn--ghost btn--sm" aria-expanded={open}
                  onClick={() => setOpen(o => !o)}>
            {open ? 'Ukryj szczegóły' : 'Pokaż szczegóły'}
            <ChevronDown size={14} aria-hidden="true"
                         style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform .15s' }} />
          </button>
        )}
      </div>

      {expanded && (
        <>
          {checks.length > 0 && (
            <div style={{ padding: '6px 18px 4px' }}>
              {!allGood && (
                <div aria-hidden="true" style={{ height: 6, borderRadius: 3, background: 'var(--color-border)',
                                                 overflow: 'hidden', margin: '8px 0 6px' }}>
                  <div style={{ width: `${required.length ? (done / required.length) * 100 : 0}%`, height: '100%',
                                background: 'var(--color-success)' }} />
                </div>
              )}
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {checks.map((c, i) => {
                  const rec = isRec(c) && !c.ok
                  const warn = isWarn(c) && !c.ok
                  return (
                  <li key={c.key || i} style={{
                    display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10, minHeight: 44, padding: '6px 0',
                    borderBottom: i < checks.length - 1 ? '1px solid var(--color-border)' : 'none',
                  }}>
                    <span aria-hidden="true" style={{
                      width: 24, height: 24, flexShrink: 0, borderRadius: '50%', display: 'grid', placeItems: 'center',
                      fontSize: 13, fontWeight: 800,
                      background: c.ok ? 'var(--color-success-bg)' : rec ? 'var(--color-info-bg)' : 'var(--color-warning-bg)',
                      color: c.ok ? 'var(--color-success)' : rec ? 'var(--color-info)' : 'var(--color-warning-text)',
                    }}>{c.ok ? <Check size={14} /> : rec ? <Info size={14} /> : '!'}</span>
                    <span style={{ flex: '1 1 240px', fontSize: 14 }}>
                      <span style={SR_ONLY}>{c.ok ? 'Gotowe: ' : rec ? 'Zalecenie: ' : warn ? 'Ostrzeżenie: ' : 'Do zrobienia: '}</span>
                      <strong style={{ fontWeight: c.ok || rec || warn ? 600 : 700 }}>{c.label}</strong>
                      {warn && (
                        <span className="badge badge--warning" aria-hidden="true"
                              style={{ fontSize: 10, marginLeft: 6, verticalAlign: 'middle' }}>ostrzeżenie</span>
                      )}
                      {rec && (
                        <span className="badge badge--info" aria-hidden="true"
                              style={{ fontSize: 10, marginLeft: 6, verticalAlign: 'middle' }}>zalecenie</span>
                      )}
                      {c.detail && <span style={{ color: 'var(--color-text-muted)' }}> — {c.detail}</span>}
                    </span>
                    {!c.ok && c.link && (
                      <Link to={c.link} aria-label={`Przejdź: ${c.label}`}
                            style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-gold-dark)',
                                     textDecoration: 'none', whiteSpace: 'nowrap' }}>
                        Przejdź <span aria-hidden="true">→</span>
                      </Link>
                    )}
                  </li>
                  )
                })}
              </ul>
            </div>
          )}

          {issues.length > 0 && (
            <div style={{ padding: '10px 18px 14px', borderTop: '1px solid var(--color-border)' }}>
              <h3 style={{ margin: '4px 0 6px', fontSize: 11, fontWeight: 800, letterSpacing: '.08em',
                           textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>Jakość danych</h3>
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {issues.map((it, i) => (
                  <li key={it.key || i} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10,
                                                 minHeight: 40, fontSize: 14 }}>
                    <span style={{ flex: '1 1 240px' }}>{it.label}</span>
                    <span className="badge badge--warning">{it.count}</span>
                    {it.link && (
                      <Link to={it.link} aria-label={`Przejdź: ${it.label}`}
                            style={{ fontSize: 13, fontWeight: 700, color: 'var(--color-gold-dark)',
                                     textDecoration: 'none', whiteSpace: 'nowrap' }}>
                        Przejdź <span aria-hidden="true">→</span>
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  )
}
