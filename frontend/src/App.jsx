import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './hooks/useAuth';
import Layout from './components/Layout';

// Auth
import Login from './pages/auth/Login';

// Dashboards
import DashboardIT from './pages/dashboard/DashboardIT';
import DashboardKadry from './pages/dashboard/DashboardKadry';
import DashboardKier from './pages/dashboard/DashboardKier';

// Wnioski
import WnioskiLista from './pages/wnioski/Lista';
import WnioskiNowy from './pages/wnioski/Nowy';
import WnioskiSzczegoly from './pages/wnioski/Szczegoly';
import WnioskiZatwierdz from './pages/wnioski/Zatwierdz';

// Workflow
import SzablonyLista from './pages/workflow/SzablonyLista';
import SzablonEdytor from './pages/workflow/SzablonEdytor';
import PrzypisaniaSzablonow from './pages/workflow/PrzypisaniaSzablonow';

// Pracownicy
import PracownicyLista from './pages/pracownicy/Lista';
import PracownikProfil from './pages/pracownicy/Profil';
import PracownikFormularz from './pages/pracownicy/Formularz';

// Uprawnienia
import UprawnieniaMat from './pages/uprawnienia/Matryca';

// Przeglądy
import PrzegladyLista from './pages/przeglady/Lista';
import PrzegladFormularz from './pages/przeglady/Formularz';

// Rejestry
import RejestrSystemy from './pages/rejestry/Systemy';
import RejestrUprawnienia from './pages/rejestry/Uprawnienia';
import RejestrUprzywilejowani from './pages/rejestry/Uprzywilejowani';
import RejestrPrzeglady from './pages/rejestry/Przeglady';
import RejestrIncydenty from './pages/rejestry/Incydenty';
import RejestrAudit from './pages/rejestry/AuditLog';

// Admin
import AdminJednostki from './pages/admin/Jednostki';
import AdminLdap from './pages/admin/LdapDomeny';
import AdminStrukturaOrg from './pages/admin/StrukturaOrg';
import AdminSystemyIT from './pages/admin/SystemyIT';
import AdminUzytkownicy from './pages/admin/Uzytkownicy';
import AdminNumeracja from './pages/admin/Numeracja';

function DashboardRoute() {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" />;
  if (['IT_ADMIN', 'SUPERADMIN'].includes(user.rola)) return <DashboardIT />;
  if (user.rola === 'KADRY') return <DashboardKadry />;
  return <DashboardKier />;
}

function RequireAuth({ children, roles }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex items-center justify-center h-screen"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>;
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.rola)) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
            <Route index element={<DashboardRoute />} />

            {/* Wnioski */}
            <Route path="wnioski" element={<WnioskiLista />} />
            <Route path="wnioski/nowy" element={<RequireAuth roles={['KIEROWNIK','IT_ADMIN','SUPERADMIN']}><WnioskiNowy /></RequireAuth>} />
            <Route path="wnioski/:id" element={<WnioskiSzczegoly />} />
            <Route path="wnioski/:id/zatwierdz" element={<RequireAuth roles={['KIEROWNIK','IT_ADMIN','SUPERADMIN']}><WnioskiZatwierdz /></RequireAuth>} />

            {/* Workflow */}
            <Route path="workflow" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><SzablonyLista /></RequireAuth>} />
            <Route path="workflow/nowy" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><SzablonEdytor /></RequireAuth>} />
            <Route path="workflow/:id" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><SzablonEdytor /></RequireAuth>} />
            <Route path="workflow/przypisania" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><PrzypisaniaSzablonow /></RequireAuth>} />

            {/* Pracownicy */}
            <Route path="pracownicy" element={<PracownicyLista />} />
            <Route path="pracownicy/nowy" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN','KADRY']}><PracownikFormularz /></RequireAuth>} />
            <Route path="pracownicy/:id" element={<PracownikProfil />} />
            <Route path="pracownicy/:id/edytuj" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN','KADRY']}><PracownikFormularz /></RequireAuth>} />

            {/* Uprawnienia */}
            <Route path="uprawnienia" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><UprawnieniaMat /></RequireAuth>} />

            {/* Przeglądy */}
            <Route path="przeglady" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><PrzegladyLista /></RequireAuth>} />
            <Route path="przeglady/nowy" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><PrzegladFormularz /></RequireAuth>} />
            <Route path="przeglady/:id" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><PrzegladFormularz /></RequireAuth>} />

            {/* Rejestry */}
            <Route path="rejestry/systemy"         element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><RejestrSystemy /></RequireAuth>} />
            <Route path="rejestry/uprawnienia"     element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><RejestrUprawnienia /></RequireAuth>} />
            <Route path="rejestry/uprzywilejowani" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><RejestrUprzywilejowani /></RequireAuth>} />
            <Route path="rejestry/przeglady"       element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><RejestrPrzeglady /></RequireAuth>} />
            <Route path="rejestry/incydenty"       element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><RejestrIncydenty /></RequireAuth>} />
            <Route path="rejestry/audit"           element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><RejestrAudit /></RequireAuth>} />

            {/* Admin */}
            <Route path="admin/jednostki"  element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><AdminJednostki /></RequireAuth>} />
            <Route path="admin/ldap"       element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><AdminLdap /></RequireAuth>} />
            <Route path="admin/struktura"  element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><AdminStrukturaOrg /></RequireAuth>} />
            <Route path="admin/systemy-it" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><AdminSystemyIT /></RequireAuth>} />
            <Route path="admin/uzytkownicy" element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><AdminUzytkownicy /></RequireAuth>} />
            <Route path="admin/numeracja"  element={<RequireAuth roles={['IT_ADMIN','SUPERADMIN']}><AdminNumeracja /></RequireAuth>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
