import { LogOut, KeyRound } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useState } from 'react'
import { logout as apiLogout, changePassword } from '../../api'

export default function Header() {
  const navigate = useNavigate()
  const userRaw = localStorage.getItem('szup_user')
  const user = userRaw ? JSON.parse(userRaw) : null
  const [showPw, setShowPw] = useState(false)

  async function handleLogout() {
    try { await apiLogout() } catch { /* ignore */ }
    localStorage.removeItem('szup_token')
    localStorage.removeItem('szup_user')
    navigate('/login')
  }

  const initials = (user?.full_name || user?.username || '?')
    .split(/\s+/).map(s => s[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()
  const roles = Array.isArray(user?.roles) ? user.roles : (user?.role ? [user.role] : [])
  const roleLabels = roles.map(r => ROLE_MAP[r]?.[1] || r).join(', ')

  return (
    // v3.0 — belka wg projektu: nazwa urzędu, użytkownik (inicjały + login
    // + role) jako jeden blok, „Hasło” (konta lokalne) i „Wyloguj” jako
    // przyciski tekstowe z ikoną.
    <header className="app-header" style={{ minHeight: 56, padding: '8px 32px', gap: 12, flexWrap: 'wrap' }}>
      <span className="app-header__org" style={{ fontSize: 14, color: 'var(--color-text-muted)' }}>
        Urząd Miasta Wodzisławia Śląskiego
      </span>
      <div className="app-header__spacer" />
      <div className="app-header__user" style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 14, minHeight: 44 }}>
        <span className="app-header__avatar" aria-hidden="true"
              style={{ width: 30, height: 30, fontSize: 11, fontWeight: 800 }}>{initials}</span>
        <span>
          <strong style={{ color: 'var(--color-heading)', fontWeight: 700 }}>{user?.username || 'Użytkownik'}</strong>
          {roleLabels && (
            <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}> · {roleLabels}</span>
          )}
        </span>
      </div>
      {user?.auth_type === 'local' && (
        <button className="app-header__logout" onClick={() => setShowPw(true)} title="Zmień hasło"
                style={HEADER_BTN}>
          <KeyRound size={15} aria-hidden="true" />
          Hasło
        </button>
      )}
      <button className="app-header__logout" onClick={handleLogout} title="Wyloguj" style={HEADER_BTN}>
        <LogOut size={15} aria-hidden="true" />
        Wyloguj
      </button>

      {showPw && <ChangePasswordModal onClose={() => setShowPw(false)} />}
    </header>
  )
}

const HEADER_BTN = {
  display: 'inline-flex', alignItems: 'center', gap: 6, minHeight: 44, padding: '0 8px',
  border: 0, background: 'transparent', fontSize: 13, fontWeight: 600,
  color: 'var(--color-text-muted)', textTransform: 'none', letterSpacing: 0,
}

const ROLE_MAP = {
  superadmin: ['badge--error',   'superadmin'],
  admin:      ['badge--warning', 'admin'],
  it_staff:   ['badge--info',    'IT'],
  manager:    ['badge--neutral', 'kierownik'],
  hr:         ['badge--success', 'HR'],
  viewer:     ['badge--neutral', 'przeglądający'],
}

function RoleBadges({ roles }) {
  if (!roles?.length) return null
  return (
    <>
      {roles.map(role => {
        const entry = ROLE_MAP[role]
        if (!entry) return null
        const [cls, label] = entry
        return (
          <span key={role} className={`badge ${cls}`} style={{ fontSize: 10, marginLeft: 4 }}>
            {label}
          </span>
        )
      })}
    </>
  )
}

function ChangePasswordModal({ onClose, forced = false }) {
  const [current, setCurrent] = useState('')
  const [next, setNext]       = useState('')
  const [next2, setNext2]     = useState('')
  const [err, setErr]         = useState(null)
  const [busy, setBusy]       = useState(false)

  async function submit(e) {
    e.preventDefault()
    setErr(null)
    if (next !== next2) { setErr('Hasła nie są identyczne'); return }
    setBusy(true)
    try {
      await changePassword({ current_password: forced ? undefined : current, new_password: next })
      localStorage.removeItem('szup_token')
      localStorage.removeItem('szup_user')
      alert('Hasło zostało zmienione. Zaloguj się ponownie.')
      window.location.href = '/login'
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się zmienić hasła')
      setBusy(false)
    }
  }

  // v3.0 — okno wg projektu: biała karta, nagłówek z kluczem, pola 44 px.
  const fieldLabel = { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 700, color: 'var(--color-text)' }
  const input = {
    minHeight: 44, padding: '0 12px', borderRadius: 8, border: '1px solid var(--color-input-border)',
    background: 'var(--color-card)', color: 'var(--color-text)', font: 'inherit', fontSize: 14, fontWeight: 400,
  }
  const req = <span style={{ color: 'var(--color-error-text)' }} aria-hidden="true">*</span>
  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && !forced && onClose()}
         style={{ background: 'rgba(20, 30, 50, .45)' }}>
      <section role="dialog" aria-modal="true" aria-label="Zmiana hasła"
               style={{ width: '100%', maxWidth: 440, background: 'var(--color-card)', borderRadius: 10,
                        boxShadow: '0 20px 50px rgba(15, 23, 42, .3)', overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '18px 22px',
                      borderBottom: '1px solid var(--color-border)' }}>
          <KeyRound size={18} color="var(--color-gold)" aria-hidden="true" />
          <h2 style={{ margin: 0, flex: 1, fontSize: 17, fontWeight: 800, color: 'var(--color-heading)' }}>Zmiana hasła</h2>
          {!forced && (
            <button type="button" onClick={onClose} aria-label="Zamknij"
                    style={{ width: 36, height: 36, border: 0, background: 'transparent', cursor: 'pointer',
                             fontSize: 22, lineHeight: 1, color: 'var(--color-text-muted)' }}>×</button>
          )}
        </div>
        <form onSubmit={submit} style={{ padding: '20px 22px', display: 'flex', flexDirection: 'column', gap: 14 }}>
          {!forced && (
            <label style={fieldLabel}>
              <span>Obecne hasło {req}</span>
              <input type="password" required autoComplete="current-password" style={input}
                     value={current} onChange={e => setCurrent(e.target.value)} />
            </label>
          )}
          <label style={fieldLabel}>
            <span>Nowe hasło {req}</span>
            <input type="password" required autoComplete="new-password" style={input}
                   value={next} onChange={e => setNext(e.target.value)} />
            <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--color-text-muted)' }}>
              Min. 12 znaków, co najmniej 3 z 4 klas: małe litery, wielkie, cyfry, specjalne.
            </span>
          </label>
          <label style={fieldLabel}>
            <span>Powtórz nowe hasło {req}</span>
            <input type="password" required autoComplete="new-password" style={input}
                   value={next2} onChange={e => setNext2(e.target.value)} />
          </label>
          {err && <div className="alert alert--error" role="alert">{err}</div>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', paddingTop: 6 }}>
            {!forced && (
              <button type="button" className="btn btn--ghost" onClick={onClose}
                      style={{ minHeight: 44, borderRadius: 8 }}>Anuluj</button>
            )}
            <button type="submit" className="btn btn--primary" disabled={busy}
                    style={{ minHeight: 44, padding: '0 20px', borderRadius: 8, fontSize: 14, fontWeight: 700 }}>
              {busy ? 'Zapisywanie…' : 'Zmień hasło'}
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}

export { ChangePasswordModal }
