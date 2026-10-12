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
    <header className="app-header">
      <span className="app-header__org">
        Urząd Miasta Wodzisławia Śląskiego
      </span>
      <div className="app-header__spacer" />
      <div className="app-header__user">
        <span className="app-header__avatar">{initials}</span>
        <span>
          {user?.username || 'Użytkownik'}
          {roleLabels && (
            <span style={{ color: 'var(--color-text-muted)', marginLeft: 4 }}>· {roleLabels}</span>
          )}
        </span>
      </div>
      {user?.auth_type === 'local' && (
        <button className="app-header__logout" onClick={() => setShowPw(true)} title="Zmień hasło">
          <KeyRound size={14} />
          Hasło
        </button>
      )}
      <button className="app-header__logout" onClick={handleLogout} title="Wyloguj">
        <LogOut size={14} />
        Wyloguj
      </button>

      {showPw && <ChangePasswordModal onClose={() => setShowPw(false)} />}
    </header>
  )
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

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && !forced && onClose()}>
      <div className="modal modal--sm">
        <div className="modal__header">
          <span className="modal__title"><KeyRound size={15} style={{ marginRight: 8, verticalAlign: 'middle' }} />Zmiana hasła</span>
          {!forced && <button className="modal__close" onClick={onClose}>×</button>}
        </div>
        <form onSubmit={submit} className="modal__body">
          {!forced && (
            <div className="form-group">
              <label className="form-label">Obecne hasło</label>
              <input type="password" className="form-control" required autoComplete="current-password"
                     value={current} onChange={e => setCurrent(e.target.value)} />
            </div>
          )}
          <div className="form-group">
            <label className="form-label">Nowe hasło</label>
            <input type="password" className="form-control" required autoComplete="new-password"
                   value={next} onChange={e => setNext(e.target.value)} />
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              Min. 12 znaków, co najmniej 3 z 4 klas: małe litery, wielkie, cyfry, specjalne.
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">Powtórz nowe hasło</label>
            <input type="password" className="form-control" required autoComplete="new-password"
                   value={next2} onChange={e => setNext2(e.target.value)} />
          </div>
          {err && <div className="alert alert--error" style={{ marginBottom: 8 }}>{err}</div>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            {!forced && <button type="button" className="btn btn--ghost btn--sm" onClick={onClose}>Anuluj</button>}
            <button type="submit" className="btn btn--primary btn--sm" disabled={busy}>
              {busy ? 'Zapisywanie…' : 'Zmień hasło'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export { ChangePasswordModal }
