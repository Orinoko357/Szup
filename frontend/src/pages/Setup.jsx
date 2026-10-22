import { useState } from 'react'
import WodsLogo from '../components/Layout/WodsLogo'
import { setupAdmin } from '../api'
import '../styles/login.css'

export default function Setup({ onSetup }) {
  const [username, setUsername] = useState('')
  const [fullName, setFullName] = useState('')
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setErr(null)
    if (password !== password2) { setErr('Hasła nie są identyczne'); return }
    setBusy(true)
    try {
      const res = await setupAdmin({ username, password, full_name: fullName })
      localStorage.setItem('szup_token', res.data.access_token)
      localStorage.setItem('szup_user', JSON.stringify({
        username: res.data.username,
        full_name: res.data.full_name,
        role: res.data.role,
        must_change_password: false,
      }))
      onSetup()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd konfiguracji')
      setBusy(false)
    }
  }

  // v3.0 — wygląd wg projektu (wspólne klasy z ekranem logowania).
  return (
    <div className="wl-page">
      <main className="wl-wrap wl-wrap--wide">
        <div className="wl-head">
          <WodsLogo size={56} onNavy />
          <h1>Pierwsze uruchomienie</h1>
          <p>Utwórz konto administratora systemu szup · WODS</p>
        </div>

        <form onSubmit={submit} className="wl-card wl-card--form">
          <div className="wl-field">
            <label htmlFor="setup-login">Login administratora <span className="wl-req" aria-hidden="true">*</span></label>
            <input id="setup-login" className="wl-input" type="text" required autoFocus
                   value={username} onChange={e => setUsername(e.target.value)} />
          </div>
          <div className="wl-field">
            <label htmlFor="setup-name">Imię i nazwisko (opcjonalne)</label>
            <input id="setup-name" className="wl-input" type="text"
                   value={fullName} onChange={e => setFullName(e.target.value)} />
          </div>
          <div className="wl-field">
            <label htmlFor="setup-pw">Hasło <span className="wl-req" aria-hidden="true">*</span></label>
            <input id="setup-pw" className="wl-input" type="password" required
                   autoComplete="new-password"
                   value={password} onChange={e => setPassword(e.target.value)} />
            <span className="wl-help">
              Min. 12 znaków, co najmniej 3 z 4 klas: małe litery, wielkie, cyfry, specjalne.
            </span>
          </div>
          <div className="wl-field">
            <label htmlFor="setup-pw2">Powtórz hasło <span className="wl-req" aria-hidden="true">*</span></label>
            <input id="setup-pw2" className="wl-input" type="password" required
                   autoComplete="new-password"
                   value={password2} onChange={e => setPassword2(e.target.value)} />
          </div>
          {err && <div className="wl-msg wl-msg--error" role="alert">{err}</div>}
          <button type="submit" className="wl-submit" disabled={busy}>
            {busy ? 'Tworzenie konta…' : 'Utwórz konto i zaloguj'}
          </button>
        </form>
      </main>
    </div>
  )
}
