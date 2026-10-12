import { NavLink } from 'react-router-dom'
import {
  LayoutDashboard, FolderOpen, CheckSquare, Wrench,
  Building2, Settings, Users, ScrollText, AlertTriangle, UserCheck, Network, ShieldCheck,
  Package, GitBranch, ListFilter, Truck, ClipboardList,
} from 'lucide-react'
import WodsLogo from './WodsLogo'

const navSections = [
  {
    label: 'Workflow',
    items: [
      // Pulpit mają tylko role z kolejkami pracy: kierownik, IT, admin/superadmin.
      // HR startuje w Kartotece (/hr), przeglądający w Moich uprawnieniach —
      // przekierowania "/" robi App.jsx.
      { to: '/',         icon: LayoutDashboard, label: 'Pulpit',         roles: ['superadmin','admin','manager','it_staff'] },
      { to: '/hr',       icon: FolderOpen,      label: 'Kartoteka',      roles: ['hr'] },
      { to: '/manager',  icon: CheckSquare,     label: 'Moje wnioski',   roles: ['manager'] },
      { to: '/my-team',  icon: UserCheck,       label: 'Moi pracownicy', roles: ['manager'] },
      { to: '/structure',icon: Network,         label: 'Moja struktura', roles: ['manager'] },
      { to: '/it',       icon: Wrench,          label: 'Do realizacji',  roles: ['it_staff'] },
      { to: '/registry', icon: ClipboardList,   label: 'Rejestr uprawnień', roles: ['superadmin','admin','it_staff'] },
    ],
  },
  {
    label: 'Słowniki IT',
    items: [
      { to: '/software',          icon: Package,    label: 'Rejestr oprogramowania', roles: ['superadmin','admin','it_staff'] },
      { to: '/vendors',           icon: Truck,      label: 'Dostawcy oprogramowania', roles: ['superadmin','admin','it_staff'] },
    ],
  },
  {
    label: 'Administracja',
    items: [
      { to: '/units',              icon: Building2,  label: 'Jednostki',       roles: ['superadmin','admin'] },
      { to: '/workflow-templates', icon: GitBranch,  label: 'Szablony obiegu', roles: ['superadmin','admin'] },
      { to: '/request-types',      icon: ListFilter, label: 'Typy wniosków',   roles: ['superadmin','admin'] },
      { to: '/users',              icon: Users,      label: 'Użytkownicy',     roles: ['superadmin','admin'] },
      { to: '/audit',              icon: ScrollText, label: 'Audit log',       roles: ['superadmin','admin'] },
      { to: '/security',           icon: AlertTriangle, label: 'Bezpieczeństwo', roles: ['superadmin','admin'] },
      { to: '/settings',           icon: Settings,   label: 'Ustawienia',      roles: ['superadmin','admin'] },
    ],
  },
  {
    label: 'Moje',
    items: [
      { to: '/my-permissions', icon: ShieldCheck, label: 'Moje uprawnienia',
        roles: ['superadmin','admin','hr','manager','it_staff','viewer'] },
    ],
  },
]

export default function Sidebar() {
  const userRaw = localStorage.getItem('szup_user')
  const user = userRaw ? JSON.parse(userRaw) : null
  const userRoles = Array.isArray(user?.roles) ? user.roles : (user?.role ? [user.role] : [])

  return (
    <aside className="app-sidebar">
      <NavLink to="/" className="sidebar-brand">
        <WodsLogo size={32} onNavy />
        <div className="sidebar-brand__text">
          <span className="sidebar-brand__main">szup</span>
          <span className="sidebar-brand__sub">WODS · UM WODZISŁAW ŚL.</span>
        </div>
      </NavLink>

      <nav className="sidebar-nav">
        {navSections.map(section => {
          const visible = section.items.filter(item => {
            if (!item.roles) return true
            return item.roles.some(r => userRoles.includes(r))
          })
          if (visible.length === 0) return null
          return (
            <div className="sidebar-section" key={section.label}>
              <div className="sidebar-section__label">{section.label}</div>
              {visible.map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) => `sidebar-link${isActive ? ' active' : ''}`}
                >
                  <Icon size={17} className="sidebar-link__icon" />
                  {label}
                </NavLink>
              ))}
            </div>
          )
        })}
      </nav>

      <div className="sidebar-footer">v1.0.0 · NIS2/KSC</div>
    </aside>
  )
}
