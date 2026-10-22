import { Check, X } from 'lucide-react'
import useDialog from './ui/useDialog'

/**
 * v3.1 — krok PODSUMOWANIA przed wysłaniem wyboru uprawnień:
 * „Nadajesz:” / „Odbierasz:” (system › uprawnienie + wartości dodatkowe).
 * Używany w kroku wyboru u kierownika i we wniosku z „Moich pracowników”.
 */

/**
 * Dyf stanu docelowego względem tego, co pracownik ma obecnie (wspólny dla
 * kroku wyboru u kierownika i wniosku z „Moich pracowników”):
 *   toGrant      — zaznaczone, a nieposiadane
 *   toRevoke     — posiadane, a odznaczone
 *   scopeChanged — posiadane, którym zmieniono wartość pola (zakres) — idą
 *                  jako ponowne nadanie z nową wartością
 */
export function diffSelection(picked, held, permsBySys = {}, fieldValues = {}, heldValues = {}) {
  const toGrant  = [...picked].filter(k => !held.has(k))
  const toRevoke = [...held].filter(k => !picked.has(k))
  const scopeChanged = [...picked].filter(k => {
    if (!held.has(k)) return false
    const [sid, pid] = k.split(':').map(Number)
    const p = (permsBySys[sid] || []).find(x => x.id === pid)
    if (!p || (p.input_type || 'none') === 'none') return false
    const now = (fieldValues[k] || {})[p.permission_name] || ''
    const before = (heldValues[k] || {})[p.permission_name] || ''
    return now !== before
  })
  return { toGrant, toRevoke, scopeChanged }
}

/** Klucze "system_id:permission_id" → wiersze do podsumowania. */
export function describeKeys(keys, systems, permsBySys, fieldValues = {}) {
  const sysById = new Map((systems || []).map(s => [s.id, s]))
  return keys.map(k => {
    const [sid, pid] = k.split(':').map(Number)
    const s = sysById.get(sid)
    const p = (permsBySys?.[sid] || []).find(x => x.id === pid)
    const vals = Object.entries(fieldValues[k] || {}).filter(([, v]) => v)
    return {
      key: k,
      system: s?.name || `#${sid}`,
      perm: s?.access_only ? 'Dostęp' : (p?.permission_name || `#${pid}`),
      isAdmin: !!p?.is_admin_option,
      values: vals,
    }
  }).sort((a, b) => a.system.localeCompare(b.system, 'pl') || a.perm.localeCompare(b.perm, 'pl'))
}

function List({ title, rows, tone }) {
  if (!rows.length) return null
  const fg = tone === 'grant' ? 'var(--color-success-text)' : 'var(--color-error-text)'
  const bg = tone === 'grant' ? 'var(--color-success-bg)' : 'var(--color-error-bg)'
  return (
    <section style={{ marginTop: 14 }}>
      <h3 style={{ margin: '0 0 6px', fontSize: 13, fontWeight: 800, color: fg }}>
        {title} · {rows.length}
      </h3>
      <ul style={{ listStyle: 'none', margin: 0, padding: 0, border: '1px solid var(--color-border)',
                   borderRadius: 8, overflow: 'hidden' }}>
        {rows.map(r => (
          <li key={r.key} style={{ padding: '8px 12px', fontSize: 14, background: bg,
                                   borderTop: '1px solid var(--color-border)' }}>
            <span style={{ fontWeight: 700 }}>{r.system}</span>
            <span style={{ color: 'var(--color-text-muted)' }}> › </span>
            <span style={{ textDecoration: tone === 'revoke' ? 'line-through' : 'none' }}>{r.perm}</span>
            {r.isAdmin && (
              <span className="badge badge--error" style={{ fontSize: 11, marginLeft: 8 }}>administrator</span>
            )}
            {tone === 'grant' && r.values.map(([k, v]) => (
              <div key={k} style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 2 }}>
                <strong>{k}:</strong> <span style={{ whiteSpace: 'pre-wrap' }}>{v}</span>
              </div>
            ))}
          </li>
        ))}
      </ul>
    </section>
  )
}

/** Okno podsumowania. grants/revokes — wynik describeKeys (lub zgodne obiekty). */
export function ReviewDialog({ open, ...props }) {
  return open ? <ReviewBox {...props} /> : null
}

// Pułapka fokusu, Escape, zwrot fokusu i blokada przewijania — ui/useDialog.
function ReviewBox({ workerName, grants = [], revokes = [], target, note,
                     confirmLabel = 'Wyślij', busy, onBack, onConfirm }) {
  const ref = useDialog({ onClose: onBack, closable: !busy })
  return (
    <div role="presentation" style={{ position: 'fixed', inset: 0, zIndex: 2500, background: 'rgba(13,20,36,.5)',
                                      display: 'grid', placeItems: 'center', padding: 16 }}>
      <div role="dialog" aria-modal="true" aria-labelledby="rv-sum-title" aria-describedby="rv-sum-sub"
           tabIndex={-1} ref={ref}
           style={{ width: '100%', maxWidth: 640, maxHeight: 'calc(100vh - 32px)', display: 'flex',
                    flexDirection: 'column', background: 'var(--color-card)', color: 'var(--color-text)',
                    border: '1px solid var(--color-border)', borderRadius: 10,
                    boxShadow: '0 16px 40px rgba(13,20,36,.3)', outline: 'none' }}>
        <div style={{ padding: '18px 20px 0' }}>
          <h2 id="rv-sum-title" style={{ margin: 0, fontSize: 18, fontWeight: 800, color: 'var(--color-heading)' }}>
            Sprawdź przed wysłaniem
          </h2>
          <p id="rv-sum-sub" style={{ margin: '6px 0 0', fontSize: 14, color: 'var(--color-text-muted)' }}>
            {workerName ? <>Pracownik: <strong style={{ color: 'var(--color-text)' }}>{workerName}</strong>. </> : null}
            {target}
          </p>
        </div>
        <div style={{ padding: '0 20px', overflowY: 'auto' }}>
          {grants.length === 0 && revokes.length === 0 && (
            <p style={{ marginTop: 14, fontSize: 14 }}>Brak zmian względem obecnego stanu.</p>
          )}
          <List title="Nadajesz" rows={grants} tone="grant" />
          <List title="Odbierasz" rows={revokes} tone="revoke" />
          {note && <p style={{ margin: '14px 0 0', fontSize: 13, color: 'var(--color-text-muted)' }}>{note}</p>}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, flexWrap: 'wrap', padding: 20 }}>
          <button type="button" className="btn btn--ghost" style={{ minHeight: 44 }} onClick={onBack} disabled={busy}>
            <X size={14} aria-hidden="true" /> Wróć do edycji
          </button>
          <button type="button" className="btn btn--success" style={{ minHeight: 44 }} onClick={onConfirm}
                  disabled={busy || (grants.length === 0 && revokes.length === 0)}>
            <Check size={14} /> {busy ? 'Wysyłanie…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
