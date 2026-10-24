import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Eye, EyeOff } from 'lucide-react'
import { loginLocal, loginLdap, loginTest, errorMessage } from '../api'
import { syncServerTime } from '../serverTime'
import WodsLogo from '../components/Layout/WodsLogo'
import { toast } from '../components/ui/feedback'
import '../styles/login.css'

// Ekran logowania (v3.0, wg projektu): karta na jasnym tle, herb + sygnet +
// nazwa w jednym rzędzie, [Windows] na górze (złoty CTA) → „— lub — logowanie
// klasyczne” (rozwijane) → login / hasło / domena. Nota RODO pod kartą.

const SSO_MESSAGES = {
  off:      'Logowanie poświadczeniami Windows jest wyłączone.',
  error:    'Logowanie poświadczeniami Windows nie powiodło się. Użyj loginu i hasła AD.',
  notfound: 'Nie znaleziono Twojego konta w Active Directory.',
  disabled: 'Twoje konto domenowe jest wyłączone w AD.',
  inactive: 'Twoje konto w aplikacji jest nieaktywne — skontaktuj się z IT.',
  expired:  'Logowanie trwało zbyt długo — spróbuj ponownie.',
}

export default function Login({ ldapEnabled, testMode, ssoEnabled, ssoAuto, onLogin }) {
  const startSso = () => {
    try { sessionStorage.setItem('szup_sso_tried', '1') } catch { /* ignore */ }
    window.location.href = '/api/auth/sso-login'
  }

  // Komunikat o nieudanym SSO (z ?sso=... albo po powrocie bez przekierowania).
  // Błąd (error/notfound/disabled/inactive/expired) → czerwony alert; brak
  // przekazanych poświadczeń → informacja.
  const ssoErrKey = new URLSearchParams(window.location.search).get('sso')
  const ssoIsError = !!ssoErrKey && ssoErrKey !== 'off'
  const [ssoInfo] = useState(() => {
    const ssoErr = ssoErrKey
    if (ssoErr && ssoErr !== 'off') return SSO_MESSAGES[ssoErr] || SSO_MESSAGES.error
    try {
      if (ssoEnabled && sessionStorage.getItem('szup_sso_tried') === '1') {
        return 'Ten komputer nie przekazał poświadczeń Windows — zaloguj się loginem i hasłem.'
      }
    } catch { /* ignore */ }
    return null
  })

  // Powód wylogowania (bezczynność / wygasła sesja) — jednorazowo, z sessionStorage
  // (AuthGate przekierowuje na /login bez parametrów, więc ?reason= bywa gubiony).
  const [sessionInfo] = useState(() => {
    let reason = new URLSearchParams(window.location.search).get('reason')
    try {
      reason = sessionStorage.getItem('szup_logout_reason') || reason
      sessionStorage.removeItem('szup_logout_reason')
    } catch { /* brak dostępu */ }
    if (reason === 'idle') return 'Wylogowano automatycznie po 30 minutach bezczynności. Zaloguj się ponownie.'
    if (reason === 'expired') return 'Sesja wygasła (np. po dłuższej bezczynności) — zaloguj się ponownie.'
    return null
  })

  const [mode, setMode] = useState(ldapEnabled ? 'ldap' : 'local')
  const [form, setForm] = useState({ username: '', password: '' })
  const [showPw, setShowPw] = useState(false)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  // Konta administracyjne (superadmin/admin) NIGDY nie logują się bez hasła —
  // w trybie testowym backend zwraca 403; wtedy przełączamy na logowanie hasłem.
  const [forcePassword, setForcePassword] = useState(false)
  const passwordless = testMode && !forcePassword

  // Bez SSO formularz jest zawsze widoczny; z SSO — zwinięty, chyba że SSO zawiodło.
  const collapsible = !!ssoEnabled
  const [open, setOpen] = useState(!collapsible || !!ssoInfo)
  const loginRef = useRef(null)

  // Automatyczne SSO raz na sesję przeglądarki (nie po ręcznym wylogowaniu/błędzie).
  useEffect(() => {
    const ssoErr = new URLSearchParams(window.location.search).get('sso')
    if (ssoErr) { window.history.replaceState(null, '', '/login'); return }
    if (ssoEnabled && ssoAuto) {
      let tried = false
      try { tried = sessionStorage.getItem('szup_sso_tried') === '1' } catch { /* ignore */ }
      if (!tried) startSso()
    }
  }, [ssoEnabled, ssoAuto])

  useEffect(() => { setMode(ldapEnabled ? 'ldap' : 'local') }, [ldapEnabled])

  function toggleClassic() {
    setOpen(o => {
      if (!o) setTimeout(() => loginRef.current?.focus(), 60)
      return !o
    })
  }

  async function submit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      let res
      if (passwordless) {
        res = await loginTest({ username: form.username })
      } else {
        const fn = mode === 'ldap' ? loginLdap : loginLocal
        res = await fn({ username: form.username, password: form.password })
      }
      localStorage.setItem('szup_token', res.data.access_token)
      localStorage.setItem('szup_user', JSON.stringify({
        username:            res.data.username,
        full_name:           res.data.full_name,
        roles:               res.data.roles,
        role:                res.data.role,
        auth_type:           res.data.auth_type,
        must_change_password: !!res.data.must_change_password,
        password_expired: !!res.data.password_expired,
      }))
      if (res.data.must_change_password) {
        toast('Twoje hasło musi zostać zmienione — za chwilę otworzy się formularz.', { tone: 'warning' })
      } else if (typeof res.data.password_expires_in_days === 'number'
                 && res.data.password_expires_in_days <= 7) {
        toast(`Twoje hasło wygaśnie za ${res.data.password_expires_in_days} dni — zmień je przyciskiem „Hasło” w belce.`, { tone: 'warning', timeout: 9000 })
      }
      await syncServerTime()
      onLogin()
    } catch (err) {
      const st = err.response?.status
      // errorMessage: detail z 422 to tablica obiektów — nie może trafić wprost do renderu.
      const detail = errorMessage(err, '')
      if (passwordless && st === 403 && /hasł/i.test(detail)) {
        setForcePassword(true)
        setOpen(true)
        setError('To konto wymaga logowania hasłem — wpisz hasło poniżej. '
          + 'Jeśli to konto domenowe, wybierz „Active Directory".')
      } else if (st === 429) {
        setError('Zbyt wiele prób logowania — poczekaj chwilę i spróbuj ponownie.')
      } else if (st === 423) {
        setError('Konto tymczasowo zablokowane z powodu wielokrotnych błędnych logowań. '
          + 'Spróbuj za 15 minut lub skontaktuj się z administratorem.')
      } else {
        setError(detail || 'Nieprawidłowy login lub hasło')
      }
      setOpen(true)
    } finally {
      setLoading(false)
    }
  }

  const loginLabel = passwordless
    ? 'Login (tryb testowy)'
    : (mode === 'ldap' ? 'Login AD (sAMAccountName)' : 'Login')
  const collapsed = collapsible && !open
  const tabIdx = collapsed ? -1 : undefined

  return (
    <div className="wl-page">
      <main className="wl-wrap">
      <section className="wl-card" aria-labelledby="wl-title">
        <div className="wl-lockup">
          <div className="wl-herbrow">
            <img className="wl-herb wl-herb--light" src="/img/herb-ciemny.png"
                 alt="Herb Miasta Wodzisławia Śląskiego" />
            <img className="wl-herb wl-herb--dark" src="/img/herb-bialy.png" alt="" aria-hidden="true" />
          </div>
          <div className="wl-brand">
            <WodsLogo size={44} />
            <div className="wl-names">
              <h1 id="wl-title" className="wl-name">szup<span className="wl-sr"> — logowanie</span></h1>
              <span className="wl-sub">WODS · URZĄD MIASTA WODZISŁAWIA ŚLĄSKIEGO</span>
            </div>
          </div>
        </div>

        <div className="wl-body">
          {testMode && (
            <div className="wl-testbanner">
              <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: 1 }} />
              <div>
                <strong>TRYB TESTOWY</strong> — logowanie samym loginem, bez hasła.
                {forcePassword && <> Konta administracyjne logują się normalnie — hasłem.</>}
                {' '}Powinien być WYŁĄCZONY na produkcji.
              </div>
            </div>
          )}

          {ssoEnabled && (
            <>
              <button type="button" className="wl-sso" onClick={startSso}>
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M3 5l8-1v8H3zM13 3.8L21 3v9h-8zM3 13h8v7l-8-1zM13 13h8v8l-8-1z" />
                </svg>
                Zaloguj poświadczeniami Windows
              </button>
              {ssoInfo && (ssoIsError
                ? <div className="wl-msg wl-msg--error" role="alert">{ssoInfo}</div>
                : <div className="wl-msg" role="status">{ssoInfo}</div>)}
              <button type="button" className={`wl-toggle${open ? ' is-open' : ''}`}
                      aria-expanded={open} aria-controls="wl-classic" onClick={toggleClassic}>
                <span className="wl-rule" aria-hidden="true" />
                <span><span className="wl-or">— lub —</span> logowanie klasyczne</span>
                <span className="wl-rule" aria-hidden="true" />
              </button>
            </>
          )}

          <div id="wl-classic"
               className={`wl-classic${collapsible ? (open ? ' is-open' : '') : ' wl-classic--static'}`}
               inert={collapsed} aria-hidden={collapsed}>
            <form onSubmit={submit}>
              <div className="wl-field">
                <label htmlFor="login">{loginLabel} <span className="wl-req" aria-hidden="true">*</span></label>
                <input id="login" ref={loginRef} className="wl-input"
                       value={form.username} required autoComplete="username"
                       autoFocus={!collapsible} tabIndex={tabIdx}
                       onChange={e => setForm(f => ({ ...f, username: e.target.value }))} />
              </div>

              {!passwordless && (
                <div className="wl-field">
                  <label htmlFor="password">Hasło <span className="wl-req" aria-hidden="true">*</span></label>
                  <div className="wl-pw">
                    <input id="password" className="wl-input" type={showPw ? 'text' : 'password'}
                           value={form.password} required autoComplete="current-password"
                           autoFocus={forcePassword} tabIndex={tabIdx}
                           onChange={e => setForm(f => ({ ...f, password: e.target.value }))} />
                    <button type="button" className="wl-eye" onClick={() => setShowPw(v => !v)}
                            tabIndex={tabIdx}
                            aria-label={showPw ? 'Ukryj hasło' : 'Pokaż hasło'}
                            title={showPw ? 'Ukryj hasło' : 'Pokaż hasło'}>
                      {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
                    </button>
                  </div>
                </div>
              )}

              {ldapEnabled && !passwordless && (
                <div className="wl-field">
                  <label htmlFor="domain">Domena</label>
                  <select id="domain" className="wl-select" value={mode} tabIndex={tabIdx}
                          onChange={e => { setMode(e.target.value); setError(null) }}>
                    <option value="ldap">Active Directory</option>
                    <option value="local">Konto lokalne (bez domeny)</option>
                  </select>
                </div>
              )}

              {sessionInfo && !error && <div className="wl-msg" role="status">{sessionInfo}</div>}
              {error && <div className="wl-msg wl-msg--error" role="alert">{error}</div>}

              <button type="submit" className="wl-submit"
                      disabled={loading} tabIndex={tabIdx}>
                {loading ? 'Logowanie…' : (passwordless ? 'Zaloguj się (tryb testowy)' : 'Zaloguj się')}
              </button>

              {testMode && forcePassword && (
                <button type="button" className="wl-link" tabIndex={tabIdx}
                        onClick={() => { setForcePassword(false); setError(null); setForm(f => ({ ...f, password: '' })) }}>
                  ← Wróć do logowania testowego (bez hasła)
                </button>
              )}
            </form>
          </div>
        </div>

      </section>

        <div className="wl-rodo">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <rect x="3" y="11" width="18" height="11" rx="2"></rect>
            <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
          </svg>
          <span>
            System przetwarza dane osobowe zgodnie z RODO oraz NIS2/KSC. Dostęp wyłącznie dla
            upoważnionych pracowników. Działania w systemie są rejestrowane.
          </span>
        </div>
      </main>
    </div>
  )
}
