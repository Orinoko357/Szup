import { LogOut, KeyRound, Menu } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useEffect, useState } from 'react'
import { logout as apiLogout, changePassword, errorMessage } from '../../api'
import { toast } from '../ui/feedback'
import GlobalSearch from '../GlobalSearch'
import { getCurrentUser, getUserRoles, clearSession } from '../../roles'
import { ROLE_LABEL } from '../../labels'
import { setNavOpen } from './Sidebar'

// Inicjały do awatara (np. „Jan Kowalski” → „JK”).
export function initials(name) {
  return (name || '?').split(/\s+/).map(s => s[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()
}

export default function Header() {
  const navigate = useNavigate()
  const user = getCurrentUser()
  const [showPw, setShowPw] = useState(false)
  // Stan szuflady menu (wąskie ekrany) — synchronizowany z paskiem bocznym.
  const [navOpen, setNavOpenState] = useState(false)
  useEffect(() => {
    const onNav = (e) => setNavOpenState(!!e.detail?.open)
    window.addEventListener('szup:nav', onNav)
    return () => window.removeEventListener('szup:nav', onNav)
  }, [])

  async function handleLogout() {
    try { await apiLogout() } catch { /* ignore */ }
    clearSession()
    navigate('/login')
  }

  const avatar = initials(user?.full_name || user?.username)
  const roleLabels = getUserRoles().map(r => ROLE_LABEL[r] || r).join(', ')

  return (
    // Belka: [Menu — tylko wąskie ekrany] nazwa urzędu, wyszukiwarka,
    // użytkownik (inicjały + login + role), „Hasło” (konta lokalne), „Wyloguj”.
    <header className="app-header">
      <button type="button" className="szup-hdr-btn app-header__menu" aria-label="Menu"
              aria-controls="app-sidebar" aria-expanded={navOpen}
              onClick={() => setNavOpen(!navOpen)}>
        <Menu size={20} aria-hidden="true" />
      </button>
      <span className="app-header__org">
        Urząd Miasta Wodzisławia Śląskiego
      </span>
      <div className="app-header__spacer" />
      <GlobalSearch />
      <div className="app-header__user">
        <span className="app-header__avatar" aria-hidden="true">{avatar}</span>
        <span className="app-header__who">
          <strong>{user?.username || 'Użytkownik'}</strong>
          {roleLabels && <span> · {roleLabels}</span>}
        </span>
      </div>
      {user?.auth_type === 'local' && (
        <button type="button" className="szup-hdr-btn" onClick={() => setShowPw(true)}
                title="Zmień hasło" aria-label="Zmień hasło">
          <KeyRound size={15} aria-hidden="true" />
          <span className="szup-hdr-btn__text">Hasło</span>
        </button>
      )}
      <button type="button" className="szup-hdr-btn" onClick={handleLogout}
              title="Wyloguj" aria-label="Wyloguj">
        <LogOut size={15} aria-hidden="true" />
        <span className="szup-hdr-btn__text">Wyloguj</span>
      </button>

      {showPw && <ChangePasswordModal onClose={() => setShowPw(false)} />}
    </header>
  )
}


function ChangePasswordModal({ onClose, forced = false }) {
  const [current, setCurrent] = useState('')
  const [next, setNext]       = useState('')
  const [next2, setNext2]     = useState('')
  const [err, setErr]         = useState(null)
  const [busy, setBusy]       = useState(false)
  // Hasło wygasłe (a nie nadane przez administratora) — backend wymaga
  // podania obecnego hasła także w trybie wymuszonym.
  const askCurrent = !forced || !!getCurrentUser().password_expired

  async function submit(e) {
    e.preventDefault()
    setErr(null)
    if (next !== next2) { setErr('Hasła nie są identyczne'); return }
    setBusy(true)
    try {
      await changePassword({ current_password: askCurrent ? current : undefined, new_password: next })
      // Wyczyszczenie sesji usuwa też flagę must_change_password — po ponownym
      // logowaniu backend zwróci jej aktualny stan.
      clearSession()
      toast('Hasło zostało zmienione. Zaloguj się ponownie.')
      setTimeout(() => { window.location.href = '/login' }, 1500)
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się zmienić hasła'))
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
          {askCurrent && (
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
