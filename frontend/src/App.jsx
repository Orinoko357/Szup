import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom'
import { Moon, Sun } from 'lucide-react'
import Header from './components/Layout/Header'
import Sidebar from './components/Layout/Sidebar'
import Dashboard from './pages/Dashboard'
import HR from './pages/HR'
import Manager from './pages/Manager'
import MyTeam from './pages/MyTeam'
import Structure from './pages/Structure'
import MyPermissions from './pages/MyPermissions'
import IT from './pages/IT'
import SoftwareRegistry from './pages/SoftwareRegistry'
import Vendors from './pages/Vendors'
import PermissionRegistry from './pages/PermissionRegistry'
import Units from './pages/Units'
import Users from './pages/Users'
import AuditLog from './pages/AuditLog'
import SecurityEvents from './pages/SecurityEvents'
import Settings from './pages/Settings'
import Login from './pages/Login'
import SsoCallback from './pages/SsoCallback'
import Setup from './pages/Setup'
// Konfiguracja obiegu (administracja): szablony obiegu i typy wniosków
import WorkflowTemplates from './pages/WorkflowTemplates'
import RequestTypes from './pages/RequestTypes'
import { getAuthStatus } from './api'
import useIdleLogout from './hooks/useIdleLogout'
import { ChangePasswordModal } from './components/Layout/Header'
import { syncServerTime } from './serverTime'

function DarkModeToggle() {
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem('szup_theme')
    if (saved) return saved === 'dark'
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
    localStorage.setItem('szup_theme', dark ? 'dark' : 'light')
  }, [dark])

  return (
    <button className="dark-toggle" onClick={() => setDark(d => !d)}
            title={dark ? 'Tryb jasny' : 'Tryb ciemny'}
            aria-label={dark ? 'Włącz tryb jasny' : 'Włącz tryb ciemny'}>
      {dark ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  )
}

function AuthGate() {
  const [state, setState] = useState('loading')
  const [ldapEnabled, setLdapEnabled] = useState(false)
  const [testMode, setTestMode] = useState(false)
  const [ssoEnabled, setSsoEnabled] = useState(false)
  const [ssoAuto, setSsoAuto] = useState(false)
  const navigate = useNavigate()

  useIdleLogout(state === 'ok')

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
        const token = localStorage.getItem('szup_token')
        // Powrót z SSO (/sso-callback?code=...) — jeszcze bez tokena; nie
        // przekierowuj na /login, pozwól wyrenderować SsoCallback.
        const onSsoCallback = window.location.pathname === '/sso-callback'
        if (!token) {
          setState('login')
          if (!onSsoCallback) navigate('/login', { replace: true })
        } else {
          syncServerTime()   // synchronizuj zegar klient↔serwer
          setState('ok')
        }
      }
    }).catch(() => {
      setState('login')
      navigate('/login', { replace: true })
    })
  }, [])

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
      <Routes>
        <Route path="/setup" element={<Setup onSetup={() => setState('ok')} />} />
        <Route path="*" element={<Navigate to="/setup" replace />} />
      </Routes>
    )
  }

  if (state === 'login') {
    return (
      <Routes>
        <Route path="/sso-callback" element={<SsoCallback onLogin={() => setState('ok')} />} />
        <Route path="/login" element={<Login ldapEnabled={ldapEnabled} testMode={testMode}
                                             ssoEnabled={ssoEnabled} ssoAuto={ssoAuto}
                                             onLogin={() => setState('ok')} />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    )
  }

  const userRaw = localStorage.getItem('szup_user')
  const mustChangePw = (() => {
    try { return !!JSON.parse(userRaw || '{}').must_change_password } catch { return false }
  })()

  if (mustChangePw) {
    return (
      <div className="app-shell">
        <Header />
        <Sidebar />
        <main className="app-main">
          <div style={{ padding: 24 }}>
            <h2>Wymagana zmiana hasła</h2>
            <p style={{ color: 'var(--color-text-muted)' }}>
              Polityka bezpieczeństwa (NIS2/KSC) wymaga zmiany hasła przed dalszym korzystaniem z systemu.
            </p>
          </div>
          <ChangePasswordModal forced onClose={() => {}} />
        </main>
      </div>
    )
  }

  const roles = (() => {
    try {
      const u = JSON.parse(userRaw || '{}')
      return Array.isArray(u.roles) ? u.roles : (u.role ? [u.role] : [])
    } catch { return [] }
  })()

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
      <Header />
      <Sidebar />
      <main className="app-main">
        <Routes>
          {/* Wspólne */}
          <Route path="/" element={home} />
          <Route path="/my-permissions" element={<MyPermissions />} />
          {/* Operacyjne */}
          <Route path="/hr"        element={guard(<HR />,        ['hr'])} />
          <Route path="/manager"   element={guard(<Manager />,   ['manager'])} />
          <Route path="/my-team"   element={guard(<MyTeam />,    ['manager'])} />
          <Route path="/structure" element={guard(<Structure />, ['manager'])} />
          <Route path="/it"        element={guard(<IT />,        ['it_staff'])} />
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
