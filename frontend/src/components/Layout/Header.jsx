import { LogOut, KeyRound, Menu, Moon, Sun } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useEffect, useId, useState } from 'react'
import { logout as apiLogout, changePassword, errorMessage } from '../../api'
import { toast } from '../ui/feedback'
import Modal from '../ui/Modal'
import GlobalSearch from '../GlobalSearch'
import { getCurrentUser, getUserRoles, clearSession } from '../../roles'
import { ROLE_LABEL } from '../../labels'
import { setNavOpen } from './Sidebar'

// Inicjały do awatara (np. „Jan Kowalski” → „JK”).
export function initials(name) {
  return (name || '?').split(/\s+/).map(s => s[0]).filter(Boolean).slice(0, 2).join('').toUpperCase()
}

/** Przełącznik motywu w belce — widoczny tylko na wąskich ekranach (CSS), gdzie
 *  pływający przycisk z App.jsx jest ukryty. Stan motywu trzyma App
 *  (zdarzenia szup:theme / szup:theme-toggle). */
function ThemeButton() {
  const read = () => document.documentElement.getAttribute('data-theme') === 'dark'
  const [dark, setDark] = useState(read)
  useEffect(() => {
    const onTheme = (e) => setDark(!!e.detail?.dark)
    window.addEventListener('szup:theme', onTheme)
    setDark(read())   // motyw mógł zostać ustawiony, zanim podpięliśmy nasłuch
    return () => window.removeEventListener('szup:theme', onTheme)
  }, [])
  return (
    <button type="button" className="szup-hdr-btn app-header__theme"
            onClick={() => window.dispatchEvent(new Event('szup:theme-toggle'))}
            title={dark ? 'Tryb jasny' : 'Tryb ciemny'}
            aria-label={dark ? 'Włącz tryb jasny' : 'Włącz tryb ciemny'}>
      {dark ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
    </button>
  )
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
        {/* Role ucinane wielokropkiem, a poniżej 1200 px ukryte — pełna treść w podpowiedzi. */}
        <span className="app-header__who"
              title={roleLabels ? `${user?.username || 'Użytkownik'} · ${roleLabels}` : undefined}>
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
      <ThemeButton />
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
  const expired = !!getCurrentUser().password_expired
  const askCurrent = !forced || expired
  const reasonId = useId()

  // Wylogowanie z okna wymuszonej zmiany — jak w belce: koniec sesji i ekran logowania.
  async function forcedLogout() {
    setBusy(true)
    try { await apiLogout() } catch { /* ignore */ }
    clearSession()
    window.location.href = '/login'
  }

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

  // v3.0 — pola 44 px wg projektu.
  const fieldLabel = { display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13, fontWeight: 700, color: 'var(--color-text)' }
  const input = {
    minHeight: 44, padding: '0 12px', borderRadius: 8, border: '1px solid var(--color-input-border)',
    background: 'var(--color-card)', color: 'var(--color-text)', font: 'inherit', fontSize: 14, fontWeight: 400,
  }
  const req = <span style={{ color: 'var(--color-error-text)' }} aria-hidden="true">*</span>
  // Okno na wspólnym ui/Modal (pułapka fokusu, Escape, zwrot fokusu). W trybie
  // wymuszonym (forced) nie da się go zamknąć — ani Escape, ani kliknięciem obok.
  return (
    <Modal
      title={<><KeyRound size={18} color="var(--color-gold)" aria-hidden="true"
                         style={{ verticalAlign: '-3px', marginRight: 8 }} />Zmiana hasła</>}
      width={440} closable={!forced} onClose={forced ? undefined : onClose}
      onSubmit={submit} describedBy={forced ? reasonId : undefined}
      footer={<>
        {forced && (
          <button type="button" className="btn btn--ghost" onClick={forcedLogout} disabled={busy}
                  style={{ minHeight: 44, borderRadius: 8, marginRight: 'auto' }}>
            <LogOut size={14} aria-hidden="true" /> Wyloguj
          </button>
        )}
        {!forced && (
          <button type="button" className="btn btn--ghost" onClick={onClose}
                  style={{ minHeight: 44, borderRadius: 8 }}>Anuluj</button>
        )}
        <button type="submit" className="btn btn--primary" disabled={busy}
                style={{ minHeight: 44, padding: '0 20px', borderRadius: 8, fontSize: 14, fontWeight: 700 }}>
          {busy ? 'Zapisywanie…' : 'Zmień hasło'}
        </button>
      </>}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        {forced && (
          <p id={reasonId} style={{ margin: 0, fontSize: 13, color: 'var(--color-text-muted)' }}>
            {expired
              ? 'Twoje hasło wygasło. Podaj obecne hasło i ustaw nowe, aby dalej korzystać z systemu.'
              : 'Hasło zostało nadane lub zresetowane przez administratora. Ustaw własne hasło, aby dalej korzystać z systemu.'}
          </p>
        )}
        {askCurrent && (
          <label style={fieldLabel}>
            <span>Obecne hasło {req}</span>
            <input type="password" required autoComplete="current-password" style={input} data-autofocus
                   value={current} onChange={e => setCurrent(e.target.value)} />
          </label>
        )}
        <label style={fieldLabel}>
          <span>Nowe hasło {req}</span>
          <input type="password" required autoComplete="new-password" style={input}
                 data-autofocus={askCurrent ? undefined : true}
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
      </div>
    </Modal>
  )
}

export { ChangePasswordModal }
