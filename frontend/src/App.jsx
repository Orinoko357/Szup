import { Suspense, lazy, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate, useLocation } from 'react-router-dom'
import { Moon, Sun } from 'lucide-react'
import Header from './components/Layout/Header'
import Sidebar from './components/Layout/Sidebar'
// Ekrany startowe ładowane od razu (logowanie, pierwsze uruchomienie, SSO,
// pulpit); pozostałe strony — leniwie (osobne paczki JS), żeby skrócić start.
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import SsoCallback from './pages/SsoCallback'
import Setup from './pages/Setup'
import { getAuthStatus, getMe } from './api'
import useIdleLogout from './hooks/useIdleLogout'
import { ChangePasswordModal } from './components/Layout/Header'
import { syncServerTime } from './serverTime'
import { getCurrentUser, getUserRoles, updateCurrentUser } from './roles'

const HR                 = lazy(() => import('./pages/HR'))
const Requests           = lazy(() => import('./pages/Requests'))
const MyTeam             = lazy(() => import('./pages/MyTeam'))
const MyPermissions      = lazy(() => import('./pages/MyPermissions'))
const SoftwareRegistry   = lazy(() => import('./pages/SoftwareRegistry'))
const Vendors            = lazy(() => import('./pages/Vendors'))
const PermissionRegistry = lazy(() => import('./pages/PermissionRegistry'))
const Units              = lazy(() => import('./pages/Units'))
const Users              = lazy(() => import('./pages/Users'))
const AuditLog           = lazy(() => import('./pages/AuditLog'))
const SecurityEvents     = lazy(() => import('./pages/SecurityEvents'))
const Settings           = lazy(() => import('./pages/Settings'))
// Konfiguracja obiegu (administracja): szablony obiegu i typy wniosków
const WorkflowTemplates  = lazy(() => import('./pages/WorkflowTemplates'))
const RequestTypes       = lazy(() => import('./pages/RequestTypes'))

// Tytuł karty przeglądarki dla tras (nazwy jak w pasku bocznym).
const ROUTE_TITLES = {
  '/': 'Pulpit', '/requests': 'Wnioski', '/hr': 'Kartoteka', '/my-team': 'Moi pracownicy',
  '/my-permissions': 'Moje uprawnienia', '/registry': 'Rejestr uprawnień',
  '/software': 'Oprogramowanie', '/vendors': 'Dostawcy i umowy', '/units': 'Jednostki',
  '/users': 'Użytkownicy', '/workflow-templates': 'Szablony obiegu',
  '/request-types': 'Typy wniosków', '/audit': 'Dziennik zdarzeń',
  '/security': 'Bezpieczeństwo', '/settings': 'Ustawienia',
  '/login': 'Logowanie', '/setup': 'Pierwsze uruchomienie', '/sso-callback': 'Logowanie',
}

function RouteTitle({ override }) {
  const { pathname } = useLocation()
  useEffect(() => {
    const name = override || ROUTE_TITLES[pathname.replace(/\/+$/, '') || '/']
    document.title = name ? `${name} · SZUP` : 'SZUP'
  }, [pathname, override])
  return null
}

// Link „Przejdź do treści” — pierwszy element w kolejności Tab, widoczny
// dopiero po otrzymaniu fokusu. Styl inline (bez zależności od CSS); klasa
// `skip-link` pozwala go dostroić w theme.css.
function SkipLink() {
  const [focused, setFocused] = useState(false)
  const hidden = {
    position: 'absolute', width: 1, height: 1, padding: 0, margin: -1,
    overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap', border: 0,
  }
  const shown = {
    position: 'fixed', top: 8, left: 8, zIndex: 3000, padding: '10px 16px', borderRadius: 8,
    background: 'var(--color-card)', color: 'var(--color-heading)', fontWeight: 700,
    border: '2px solid var(--color-gold)', textDecoration: 'none',
  }
  return (
    <a href="#main-content" className="skip-link" style={focused ? shown : hidden}
       onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
       onClick={e => {
         // Przenieś fokus do treści (sam skok do kotwicy nie zawsze go przenosi).
         const main = document.getElementById('main-content')
         if (main) { e.preventDefault(); main.focus() }
       }}>
      Przejdź do treści
    </a>
  )
}

function PageLoading() {
  return <div style={{ color: 'var(--color-text-muted)', padding: 18 }}>Ładowanie…</div>
}

function DarkModeToggle() {
  const [dark, setDark] = useState(() => {
    // Zablokowany storage (tryb prywatny, polityka przeglądarki) nie może wywrócić aplikacji.
    let saved = null
    try { saved = localStorage.getItem('szup_theme') } catch { /* brak dostępu */ }
    if (saved) return saved === 'dark'
    return !!window.matchMedia?.('(prefers-color-scheme: dark)').matches
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
    try { localStorage.setItem('szup_theme', dark ? 'dark' : 'light') } catch { /* brak dostępu */ }
  }, [dark])

  return (
    <button className="dark-toggle" onClick={() => setDark(d => !d)}
            title={dark ? 'Tryb jasny' : 'Tryb ciemny'}
            aria-label={dark ? 'Włącz tryb jasny' : 'Włącz tryb ciemny'}>
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}

// v3.0 — stare adresy (zakładki w przeglądarce, linki z e-maili) prowadzą
// do nowych miejsc: dawne „Wnioski” kierownika i kolejka IT są jedną stroną
// /requests, „Moja struktura” to zakładka „Moich pracowników”.
// Przekierowania trzymać do v4.0 (stare linki w skrzynkach użytkowników).
function LegacyRedirect({ to }) {
  const { search } = useLocation()
  const tab = new URLSearchParams(search).get('tab')
  const target = to === 'it' ? `/requests?tab=${tab === 'names' ? 'names' : 'it'}`
    : to === 'manager' ? '/requests?tab=handle'
    : '/my-team?tab=structure'
  return <Navigate to={target} replace />
}

function AuthGate() {
  const [state, setState] = useState('loading')
  const [ldapEnabled, setLdapEnabled] = useState(false)
  const [testMode, setTestMode] = useState(false)
  const [ssoEnabled, setSsoEnabled] = useState(false)
  const [ssoAuto, setSsoAuto] = useState(false)
  const navigate = useNavigate()
  // Licznik zmian danych sesji — wymusza przerysowanie po odświeżeniu ról
  // (getMe) albo po 403 PASSWORD_CHANGE_REQUIRED z dowolnego zapytania.
  const [, setUserVersion] = useState(0)

  useIdleLogout(state === 'ok')

  useEffect(() => {
    const bump = () => setUserVersion(v => v + 1)
    window.addEventListener('szup:user', bump)
    window.addEventListener('szup:mustchange', bump)
    return () => {
      window.removeEventListener('szup:user', bump)
      window.removeEventListener('szup:mustchange', bump)
    }
  }, [])

  useEffect(() => {
    getAuthStatus().then(res => {
      if (res.data.first_run) {
        setState('setup')
        navigate('/setup', { replace: true })
      } else {
        setLdapEnabled(res.data.ldap_enabled)
        setTestMode(!!res.data.test_mode)
        setSsoEnabled(!!res.data.sso_enabled)
        setSsoAuto(!!res.data.sso_auto)
        let token = null
        try { token = localStorage.getItem('szup_token') } catch { /* brak dostępu */ }
        // Powrót z SSO (/sso-callback?code=...) — jeszcze bez tokena; nie
        // przekierowuj na /login, pozwól wyrenderować SsoCallback.
        const onSsoCallback = window.location.pathname === '/sso-callback'
        if (!token) {
          setState('login')
          if (!onSsoCallback) navigate('/login', { replace: true })
        } else {
          syncServerTime()   // synchronizuj zegar klient↔serwer
          refreshUser()      // role/flagi z serwera — sesja mogła się zdezaktualizować
          setState('ok')
        }
      }
    }).catch(() => {
      setState('login')
      navigate('/login', { replace: true })
    })
  }, [])

  // Odśwież dane sesji z /auth/me: role nadane lub odebrane po zalogowaniu
  // (np. nowy zastępca kierownika) i wymuszona zmiana hasła działają od razu,
  // bez ponownego logowania. 401 obsługuje interceptor (wylogowanie); inny
  // błąd zostawia dotychczasowe dane — to tylko odświeżenie.
  function refreshUser() {
    getMe().then(r => {
      const d = r.data || {}
      updateCurrentUser({
        id: d.id,
        username: d.username,
        full_name: d.full_name,
        roles: Array.isArray(d.roles) ? d.roles : getUserRoles(),
        role: d.role,
        must_change_password: !!d.must_change_password,
        password_expired: !!d.password_expired,
      })
    }).catch(() => { /* zostają dane z logowania */ })
  }

  if (state === 'loading') {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center',
                    height: '100vh', color: 'var(--text-muted)', fontSize: 14, gap: 10 }}>
        <span className="spinner" style={{ borderTopColor: 'var(--color-gold)', borderColor: 'var(--color-border)' }} />
        Ładowanie…
      </div>
    )
  }

  if (state === 'setup') {
    return (
      <>
      <RouteTitle />
      <Routes>
        <Route path="/setup" element={<Setup onSetup={() => setState('ok')} />} />
        <Route path="*" element={<Navigate to="/setup" replace />} />
      </Routes>
      </>
    )
  }

  if (state === 'login') {
    return (
      <>
      <RouteTitle />
      <Routes>
        <Route path="/sso-callback" element={<SsoCallback onLogin={() => setState('ok')} />} />
        <Route path="/login" element={<Login ldapEnabled={ldapEnabled} testMode={testMode}
                                             ssoEnabled={ssoEnabled} ssoAuto={ssoAuto}
                                             onLogin={() => setState('ok')} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
      </>
    )
  }

  const mustChangePw = !!getCurrentUser().must_change_password

  if (mustChangePw) {
    return (
      <div className="app-shell">
        <RouteTitle override="Wymagana zmiana hasła" />
        <SkipLink />
        <Header />
        <Sidebar />
        <main className="app-main" id="main-content" tabIndex={-1}>
          <div>
            <h2 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: 'var(--color-heading)' }}>
              Wymagana zmiana hasła
            </h2>
            <p style={{ margin: '6px 0 0', fontSize: 14, color: 'var(--color-text-muted)' }}>
              Polityka bezpieczeństwa (NIS2/KSC) wymaga zmiany hasła przed dalszym korzystaniem z systemu.
            </p>
          </div>
          <ChangePasswordModal forced onClose={() => {}} />
        </main>
      </div>
    )
  }

  const roles = getUserRoles()

  // Rozdział ról (Wariant A — czysty rozdział obowiązków):
  //  administrator KONFIGURUJE system, pracownik IT REALIZUJE wnioski.
  //  Panele operacyjne (HR / kierownik / IT) NIE są dostępne dla samego admina —
  //  kto ma je pełnić, dostaje właściwą rolę operacyjną.
  const guard = (el, allowed) =>
    (!allowed || allowed.some(r => roles.includes(r))) ? el : <Navigate to="/" replace />

  // Pulpit mają tylko role z kolejkami pracy: kierownik, IT, admin/superadmin.
  // Czysty HR startuje w Kartotece (/hr), przeglądający (viewer) w Moich
  // uprawnieniach. Role łączone (np. hr+manager) zachowują Pulpit.
  const DASHBOARD_ROLES = ['superadmin', 'admin', 'manager', 'it_staff']
  const hasDashboard = roles.some(r => DASHBOARD_ROLES.includes(r))
  const home = hasDashboard
    ? <Dashboard />
    : roles.includes('hr')
      ? <Navigate to="/hr" replace />
      : <Navigate to="/my-permissions" replace />

  return (
    <div className="app-shell">
      <RouteTitle />
      <SkipLink />
      <Header />
      <Sidebar />
      <main className="app-main" id="main-content" tabIndex={-1}>
        <Suspense fallback={<PageLoading />}>
        <Routes>
          {/* Wspólne */}
          <Route path="/" element={home} />
          <Route path="/my-permissions" element={<MyPermissions />} />
          {/* Operacyjne */}
          <Route path="/hr"        element={guard(<HR />,        ['hr'])} />
          <Route path="/requests"  element={guard(<Requests />,  ['manager','it_staff'])} />
          <Route path="/my-team"   element={guard(<MyTeam />,    ['manager'])} />
          <Route path="/manager"   element={guard(<LegacyRedirect to="manager" />, ['manager'])} />
          <Route path="/structure" element={guard(<LegacyRedirect to="structure" />, ['manager'])} />
          <Route path="/it"        element={guard(<LegacyRedirect to="it" />, ['it_staff'])} />
          <Route path="/registry"  element={guard(<PermissionRegistry />, ['it_staff','admin','superadmin'])} />
          {/* Słowniki IT — rejestr oprogramowania obsługuje IT oraz admin */}
          <Route path="/software"  element={guard(<SoftwareRegistry />, ['it_staff','admin','superadmin'])} />
          <Route path="/vendors"   element={guard(<Vendors />,          ['it_staff','admin','superadmin'])} />
          {/* Administracja — wyłącznie admin/superadmin */}
          <Route path="/units"     element={guard(<Units />,     ['admin','superadmin'])} />
          <Route path="/users"     element={guard(<Users />,     ['admin','superadmin'])} />
          <Route path="/audit"     element={guard(<AuditLog />,  ['admin','superadmin'])} />
          <Route path="/security"  element={guard(<SecurityEvents />, ['admin','superadmin'])} />
          <Route path="/settings"  element={guard(<Settings />,  ['admin','superadmin'])} />
          <Route path="/workflow-templates" element={guard(<WorkflowTemplates />, ['admin','superadmin'])} />
          <Route path="/request-types"      element={guard(<RequestTypes />,      ['admin','superadmin'])} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        </Suspense>
      </main>
    </div>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthGate />
      <DarkModeToggle />
    </BrowserRouter>
  )
}
