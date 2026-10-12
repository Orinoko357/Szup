import { useState } from 'react'
import WodsLogo from '../components/Layout/WodsLogo'
import { setupAdmin } from '../api'

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

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--color-bg)', padding: 20,
    }}>
      <div style={{ width: '100%', maxWidth: 460 }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 16 }}>
            <WodsLogo size={56} />
          </div>
          <div style={{ fontSize: 22, fontWeight: 700, color: 'var(--color-navy)' }}>
            Pierwsze uruchomienie
          </div>
          <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 4 }}>
            Utwórz konto administratora systemu szup · WODS
          </div>
        </div>

        <div className="card">
          <form onSubmit={submit}>
            <div className="form-group">
              <label className="form-label">Login administratora</label>
              <input className="form-control" type="text" required autoFocus
                     value={username} onChange={e => setUsername(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Imię i nazwisko (opcjonalne)</label>
              <input className="form-control" type="text"
                     value={fullName} onChange={e => setFullName(e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Hasło</label>
              <input className="form-control" type="password" required
                     autoComplete="new-password"
                     value={password} onChange={e => setPassword(e.target.value)} />
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                Min. 12 znaków, co najmniej 3 z 4 klas: małe litery, wielkie, cyfry, specjalne.
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">Powtórz hasło</label>
              <input className="form-control" type="password" required
                     autoComplete="new-password"
                     value={password2} onChange={e => setPassword2(e.target.value)} />
            </div>
            {err && <div className="alert alert--error" style={{ marginBottom: 16 }}>{err}</div>}
            <button type="submit" className="btn btn--primary w-full" disabled={busy}>
              {busy ? 'Tworzenie konta…' : 'Utwórz konto i zaloguj'}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
