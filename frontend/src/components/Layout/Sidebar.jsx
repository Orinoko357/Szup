import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import {
  LayoutDashboard, FolderOpen, CheckSquare,
  Building2, Settings, Users, ScrollText, AlertTriangle, UserCheck, ShieldCheck,
  Package, GitBranch, ListFilter, Truck, ClipboardList, ChevronRight,
} from 'lucide-react'
import WodsLogo from './WodsLogo'
import { getUserRoles } from '../../roles'
import { focusableIn, lockScroll } from '../ui/useDialog'

// v3.0 — pasek boczny służy WYŁĄCZNIE nawigacji (bez liczników — sprawy
// czekające pokazuje pulpit). Grupy: PRACA, REJESTRY, ADMINISTRACJA (zwijana),
// MOJE. „Do realizacji” jest zakładką strony Wnioski, struktura komórek —
// zakładką „Moich pracowników”.
const navSections = [
  {
    label: 'Praca',
    items: [
      { to: '/',         icon: LayoutDashboard, label: 'Pulpit',         roles: ['superadmin','admin','manager','it_staff'] },
      { to: '/requests', icon: CheckSquare,     label: 'Wnioski',        roles: ['manager','it_staff'] },
      { to: '/hr',       icon: FolderOpen,      label: 'Kartoteka',      roles: ['hr'] },
      { to: '/my-team',  icon: UserCheck,       label: 'Moi pracownicy', roles: ['manager'] },
    ],
  },
  {
    label: 'Rejestry',
    items: [
      { to: '/registry', icon: ClipboardList, label: 'Rejestr uprawnień', roles: ['superadmin','admin','it_staff'] },
      { to: '/software', icon: Package,       label: 'Oprogramowanie',    roles: ['superadmin','admin','it_staff'] },
      { to: '/vendors',  icon: Truck,         label: 'Dostawcy i umowy',  roles: ['superadmin','admin','it_staff'] },
    ],
  },
  {
    label: 'Administracja',
    collapsible: true,
    items: [
      { to: '/units',              icon: Building2,     label: 'Jednostki',       roles: ['superadmin','admin'] },
      { to: '/users',              icon: Users,         label: 'Użytkownicy',     roles: ['superadmin','admin'] },
      { to: '/workflow-templates', icon: GitBranch,     label: 'Szablony obiegu', roles: ['superadmin','admin'] },
      { to: '/request-types',      icon: ListFilter,    label: 'Typy wniosków',   roles: ['superadmin','admin'] },
      { to: '/audit',              icon: ScrollText,    label: 'Dziennik zdarzeń',     roles: ['superadmin','admin'] },
      { to: '/security',           icon: AlertTriangle, label: 'Bezpieczeństwo',  roles: ['superadmin','admin'] },
      { to: '/settings',           icon: Settings,      label: 'Ustawienia',      roles: ['superadmin','admin'] },
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

// Szuflada menu na wąskich ekranach (< 900 px): przycisk „Menu” w belce
// i pasek komunikują się zdarzeniem `szup:nav` ({ open }).
export function setNavOpen(open) {
  window.dispatchEvent(new CustomEvent('szup:nav', { detail: { open } }))
}

export default function Sidebar() {
  const userRoles = getUserRoles()
  const { pathname } = useLocation()
  const [drawerOpen, setDrawerOpen] = useState(false)
  const asideRef = useRef(null)
  useEffect(() => {
    const onNav = (e) => setDrawerOpen(!!e.detail?.open)
    window.addEventListener('szup:nav', onNav)
    return () => window.removeEventListener('szup:nav', onNav)
  }, [])
  // Zamknij szufladę po przejściu na inny ekran i klawiszem Escape.
  useEffect(() => { if (drawerOpen) setNavOpen(false) }, [pathname])
  useEffect(() => {
    if (!drawerOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') { setNavOpen(false); return }
      // Pułapka fokusu w otwartej szufladzie (treść pod nakładką jest niedostępna).
      if (e.key !== 'Tab' || !window.matchMedia('(max-width: 900px)').matches) return
      const items = focusableIn(asideRef.current)
      if (!items.length) return
      const first = items[0], last = items[items.length - 1]
      const inside = asideRef.current.contains(document.activeElement)
      if (e.shiftKey && (document.activeElement === first || !inside)) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && (document.activeElement === last || !inside)) { e.preventDefault(); first.focus() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [drawerOpen])
  // Fokus i przewijanie szuflady (tylko wąski ekran, gdy jest szufladą):
  // po otwarciu fokus na pierwszy link, po zamknięciu powrót na przycisk
  // „Menu” w belce; dokument pod szufladą się nie przewija.
  const wasOpen = useRef(false)
  useEffect(() => {
    const narrow = window.matchMedia('(max-width: 900px)').matches
    if (drawerOpen) {
      wasOpen.current = true
      if (!narrow) return
      const unlock = lockScroll()
      // visibility zmienia się w tej samej klatce — fokus po odmalowaniu.
      const t = requestAnimationFrame(() => {
        const nav = asideRef.current?.querySelector('.sidebar-nav')
        ;(nav?.querySelector('a') || nav?.querySelector('button'))?.focus()
      })
      return () => { cancelAnimationFrame(t); unlock() }
    }
    if (wasOpen.current) {
      wasOpen.current = false
      const inside = asideRef.current?.contains(document.activeElement)
      if (narrow && (inside || document.activeElement === document.body)) {
        document.querySelector('.app-header__menu')?.focus()
      }
    }
  }, [drawerOpen])
  // Zwijana grupa: domyślnie zwinięta, rozwinięta gdy jesteśmy na jej ekranie.
  const [openOverride, setOpenOverride] = useState({})
  // Po przejściu na inny ekran zapominamy ręczne zwinięcie — sekcja z aktywną
  // pozycją znów się rozwija (np. wejście z pulpitu w „Bezpieczeństwo”).
  useEffect(() => { setOpenOverride({}) }, [pathname])

  return (
    <>
    <div className={`sidebar-overlay${drawerOpen ? ' is-open' : ''}`} aria-hidden="true"
         onClick={() => setNavOpen(false)} />
    <aside id="app-sidebar" ref={asideRef} className={`app-sidebar${drawerOpen ? ' is-open' : ''}`}>
      <NavLink to="/" className="sidebar-brand">
        <WodsLogo size={32} onNavy />
        <div className="sidebar-brand__text">
          <span className="sidebar-brand__main">szup</span>
          <span className="sidebar-brand__sub">WODS · UM WODZISŁAW ŚL.</span>
        </div>
      </NavLink>

      <nav className="sidebar-nav" aria-label="Menu główne">
        {navSections.map(section => {
          const visible = section.items.filter(item =>
            !item.roles || item.roles.some(r => userRoles.includes(r)))
          if (visible.length === 0) return null
          const containsActive = visible.some(i => pathname.startsWith(i.to) && i.to !== '/')
          const open = !section.collapsible
            || (openOverride[section.label] ?? containsActive)
          return (
            <div className="sidebar-section" key={section.label}>
              {section.collapsible ? (
                <button type="button" className="sidebar-section__toggle" aria-expanded={open}
                        onClick={() => setOpenOverride(o => ({ ...o, [section.label]: !open }))}>
                  <span style={{ flex: 1 }}>{section.label}</span>
                  <ChevronRight size={12} aria-hidden="true" />
                </button>
              ) : (
                <div className="sidebar-section__label">{section.label}</div>
              )}
              {open && visible.map(({ to, icon: Icon, label }) => (
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

      <div className="sidebar-footer">v3.3 · NIS2/KSC</div>
    </aside>
    </>
  )
}
