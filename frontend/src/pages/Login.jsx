import { useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'
import { loginLocal, loginLdap, loginTest } from '../api'
import { syncServerTime } from '../serverTime'
import WodsLogo from '../components/Layout/WodsLogo'

// Komunikaty po nieudanym SSO (z ?sso=... w URL po powrocie z backendu).
const SSO_MESSAGES = {
  off:      'Logowanie poświadczeniami Windows jest wyłączone.',
  error:    'Nie udało się zalogować przez Windows. Spróbuj zwykłego logowania.',
  notfound: 'Twojego konta domenowego nie znaleziono w katalogu AD.',
  disabled: 'Twoje konto domenowe jest wyłączone w AD.',
  inactive: 'Twoje konto w aplikacji jest nieaktywne — skontaktuj się z IT.',
  expired:  'Sesja logowania Windows wygasła — spróbuj ponownie.',
}

export default function Login({ ldapEnabled, testMode, ssoEnabled, ssoAuto, onLogin }) {
  const startSso = () => { window.location.href = '/api/auth/sso-login' }
  // Gdy domena jest skonfigurowana, logowanie AD jest ścieżką domyślną —
  // większość pracowników używa konta domenowego, konta lokalne to wyjątek.
  const [tab, setTab]   = useState(ldapEnabled ? 'ldap' : 'local')
  const [form, setForm] = useState({ username: '', password: '' })
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  // Konta administracyjne (superadmin/admin) NIGDY nie logują się bez hasła —
  // nawet w trybie testowym backend zwraca 403 „użyj hasła". Wtedy przełączamy
  // formularz na logowanie hasłem (forcePassword), zamiast zostawić usera w kropce.
  const [forcePassword, setForcePassword] = useState(false)

  const passwordless = testMode && !forcePassword

  // Komunikat błędu SSO z URL + automatyczne SSO (gdy sso_auto). Flaga w
  // sessionStorage chroni przed pętlą (spróbuj raz, potem pokaż formularz).
  useEffect(() => {
    const ssoErr = new URLSearchParams(window.location.search).get('sso')
    if (ssoErr && ssoErr !== 'off') {
      setError(SSO_MESSAGES[ssoErr] || SSO_MESSAGES.error)
      window.history.replaceState(null, '', '/login')
      return
    }
    if (ssoAuto && ssoEnabled) {
      let tried = false
      try { tried = sessionStorage.getItem('szup_sso_tried') === '1' } catch { /* ignore */ }
      if (!tried) {
        try { sessionStorage.setItem('szup_sso_tried', '1') } catch { /* ignore */ }
        startSso()
      }
    }
  }, [ssoAuto, ssoEnabled])

  async function submit(e) {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      let res
      if (passwordless) {
        res = await loginTest({ username: form.username })
      } else {
        const fn = tab === 'ldap' ? loginLdap : loginLocal
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
      }))
      if (res.data.must_change_password) {
        alert('Twoje hasło musi zostać zmienione. Za chwilę otworzy się formularz.')
      } else if (typeof res.data.password_expires_in_days === 'number'
                 && res.data.password_expires_in_days <= 7) {
        alert(`Twoje hasło wygaśnie za ${res.data.password_expires_in_days} dni — zmień je w ustawieniach konta.`)
      }
      await syncServerTime()
      onLogin()
    } catch (err) {
      const st = err.response?.status
      const detail = err.response?.data?.detail || ''
      if (passwordless && st === 403 && /hasł/i.test(detail)) {
        // Konto administracyjne w trybie testowym → pokaż pole hasła
        setForcePassword(true)
        setError('To konto wymaga logowania hasłem — wpisz hasło poniżej. '
          + 'Jeśli to konto domenowe, wybierz zakładkę „LDAP / AD".')
      } else if (st === 429) {
        setError('Zbyt wiele prób logowania — poczekaj chwilę i spróbuj ponownie.')
      } else if (st === 423) {
        setError('Konto tymczasowo zablokowane z powodu wielokrotnych błędnych logowań. Spróbuj za 15 minut lub skontaktuj się z administratorem.')
      } else {
        setError(detail || 'Nieprawidłowy login lub hasło')
      }
    } finally {
      setLoading(false)
    }
  }

  const localLabel = passwordless
    ? 'Login (tryb testowy)'
    : (tab === 'ldap' ? 'Login AD (sAMAccountName)' : 'Login')

  return (
    <div className="szup-login">
      <main className="szup-login__card">
        <div className="szup-login__header">
          <img src="/img/herb-ciemny.png" alt="Herb Miasta Wodzisławia Śląskiego"
               className="login-herb login-herb--light szup-login__herb" />
          <img src="/img/herb-bialy.png" alt="" aria-hidden="true"
               className="login-herb login-herb--dark szup-login__herb" />
          <WodsLogo size={44} />
          <div>
            <div className="szup-login__name">szup</div>
            <div className="szup-login__sub">WODS · URZĄD MIASTA WODZISŁAWIA ŚLĄSKIEGO</div>
          </div>
        </div>

        {testMode && (
          <div className="szup-login__testbanner">
            <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: 1 }} />
            <div>
              <strong>TRYB TESTOWY</strong> — logowanie samym loginem, bez hasła.
              {forcePassword && <> Konta administracyjne logują się normalnie — hasłem.</>}
              {' '}Ten tryb powinien być WYŁĄCZONY w środowisku produkcyjnym.
            </div>
          </div>
        )}

        {/* Zakładki widoczne zawsze, gdy logujemy hasłem — także po wymuszeniu
            hasła w trybie testowym (konto AD musi móc wybrać LDAP / AD). */}
        {!passwordless && (
          <div className="szup-login__tabs">
            {/* Kolejność zależy od konfiguracji: gdy AD działa, jest pierwsze
                (domyślna ścieżka), konto lokalne schodzi na prawo. */}
            {(ldapEnabled
              ? [['ldap', 'LDAP / AD'], ['local', 'Konto lokalne']]
              : [['local', 'Konto lokalne'], ['ldap', 'LDAP / AD']]
            ).map(([val, lbl]) => (
              <button
                key={val}
                type="button"
                className={`szup-login__tab${tab === val ? ' szup-login__tab--active' : ''}`}
                onClick={() => { setTab(val); setError(null) }}
              >
                {lbl}
              </button>
            ))}
          </div>
        )}

        <form className="szup-login__form" onSubmit={submit}>
          <div className="szup-login__fields">
            <div className="szup-login__group">
              <label htmlFor="login">{localLabel}</label>
              <input
                id="login"
                value={form.username}
                onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                required
                autoFocus
                autoComplete="username"
              />
            </div>
            {!passwordless && (
              <div className="szup-login__group">
                <label htmlFor="password">Hasło</label>
                <input
                  id="password"
                  type="password"
                  value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  required
                  autoFocus={forcePassword}
                  autoComplete="current-password"
                />
              </div>
            )}

            {error && <div className="szup-login__error">{error}</div>}
          </div>

          <button className="szup-login__submit" type="submit" disabled={loading}>
            {loading ? 'Logowanie…' : (passwordless ? 'Zaloguj się (tryb testowy)' : 'Zaloguj się')}
          </button>

          {ssoEnabled && (
            <button type="button" className="szup-login__tab"
                    style={{ marginTop: 8, width: '100%' }}
                    onClick={startSso}>
              Zaloguj poświadczeniami Windows
            </button>
          )}

          {testMode && forcePassword && (
            <button
              type="button"
              className="szup-login__tab"
              style={{ marginTop: 8, width: '100%' }}
              onClick={() => { setForcePassword(false); setError(null); setForm(f => ({ ...f, password: '' })) }}
            >
              ← Wróć do logowania testowego (bez hasła)
            </button>
          )}
        </form>

        <div className="szup-login__rodo">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
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
