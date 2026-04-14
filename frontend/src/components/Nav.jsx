import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import {
  LayoutDashboard, FileText, Users, Shield, ClipboardCheck,
  Star, Eye, AlertTriangle, ScrollText,
  Building2, Network, GitBranch, Monitor, UserCog, Hash,
  Workflow as WorkflowIcon
} from 'lucide-react';

const ROLE_LABELS = {
  SUPERADMIN: 'Super Admin',
  IT_ADMIN: 'Administrator IT',
  KADRY: 'Kadry',
  KIEROWNIK: 'Kierownik',
  PRACOWNIK: 'Pracownik',
};

function NavItem({ to, icon: Icon, label, badge }) {
  const loc = useLocation();
  const active = to === '/' ? loc.pathname === '/' : loc.pathname.startsWith(to);
  return (
    <Link to={to} className={`nav-link ${active ? 'active' : ''}`}>
      {Icon && <Icon size={15} />}
      <span>{label}</span>
      {badge > 0 && <span className="nav-badge">{badge}</span>}
    </Link>
  );
}

export default function Sidebar() {
  const { user } = useAuth();
  const isIT = user && ['IT_ADMIN', 'SUPERADMIN'].includes(user.rola);
  const isKadry = user && user.rola === 'KADRY';
  const isKier = user && ['KIEROWNIK', 'PRACOWNIK'].includes(user.rola);

  return (
    <nav>
      {/* User info */}
      {user && (
        <div className="px-4 pb-4 mb-2 border-b border-white/10">
          <div className="text-xs font-semibold text-white/80">{user.imie} {user.nazwisko}</div>
          <div className="text-[11px] text-white/40 mt-0.5">{ROLE_LABELS[user.rola]}</div>
        </div>
      )}

      {/* Dashboard */}
      <NavItem to="/" icon={LayoutDashboard} label="Dashboard" />

      <hr className="nav-separator" />

      {/* Wnioski */}
      <span className="nav-section-label">Wnioski</span>
      <NavItem to="/wnioski" icon={FileText} label="Wnioski" />

      {/* Pracownicy */}
      <hr className="nav-separator" />
      <span className="nav-section-label">Pracownicy</span>
      {(isIT || isKadry || isKier) && (
        <NavItem to="/pracownicy" icon={Users} label="Pracownicy" />
      )}

      {/* Uprawnienia */}
      {isIT && (
        <>
          <hr className="nav-separator" />
          <span className="nav-section-label">Uprawnienia</span>
          <NavItem to="/uprawnienia" icon={Shield} label="Matryca" />
          <NavItem to="/przeglady" icon={Eye} label="Przeglądy" />
        </>
      )}

      {/* Rejestry */}
      {isIT && (
        <>
          <hr className="nav-separator" />
          <span className="nav-section-label">Rejestry</span>
          <NavItem to="/rejestry/systemy"         icon={Monitor}       label="Systemy IT" />
          <NavItem to="/rejestry/uprawnienia"     icon={Shield}        label="Uprawnienia" />
          <NavItem to="/rejestry/uprzywilejowani" icon={Star}          label="Uprzywilejowani" />
          <NavItem to="/rejestry/przeglady"       icon={ClipboardCheck} label="Przeglądy" />
          <NavItem to="/rejestry/incydenty"       icon={AlertTriangle} label="Incydenty" />
          <NavItem to="/rejestry/audit"           icon={ScrollText}    label="Audit Log" />
        </>
      )}

      {/* Administracja */}
      {isIT && (
        <>
          <hr className="nav-separator" />
          <span className="nav-section-label">Administracja</span>
          <NavItem to="/admin/jednostki"   icon={Building2}  label="Jednostki" />
          <NavItem to="/admin/ldap"        icon={Network}    label="Domeny LDAP" />
          <NavItem to="/admin/struktura"   icon={GitBranch}  label="Struktura org." />
          <NavItem to="/admin/systemy-it"  icon={Monitor}    label="Systemy IT" />
          <NavItem to="/admin/uzytkownicy" icon={UserCog}    label="Użytkownicy" />
          <NavItem to="/workflow"          icon={WorkflowIcon}   label="Szablony workflow" />
          <NavItem to="/admin/numeracja"   icon={Hash}       label="Numeracja" />
        </>
      )}
    </nav>
  );
}
