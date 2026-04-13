import { useState, useRef, useEffect } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { usePowiadomienia } from '../hooks/usePowiadomienia';

const ROLE_LABELS = { SUPERADMIN: 'Super Admin', IT_ADMIN: 'Administrator IT', KADRY: 'Kadry', KIEROWNIK: 'Kierownik', PRACOWNIK: 'Pracownik' };

export default function Nav() {
  const { user, logout } = useAuth();
  const { nieprzeczytane, items, markRead, markAllRead } = usePowiadomienia();
  const [menuOpen, setMenuOpen] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const notifRef = useRef(null);
  const navigate = useNavigate();
  const loc = useLocation();

  const isIT = user && ['IT_ADMIN', 'SUPERADMIN'].includes(user.rola);
  const isKadry = user && user.rola === 'KADRY';
  const isKier = user && ['KIEROWNIK', 'PRACOWNIK'].includes(user.rola);

  useEffect(() => {
    function handle(e) {
      if (notifRef.current && !notifRef.current.contains(e.target)) setNotifOpen(false);
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, []);

  const link = (to, label) => (
    <Link
      to={to}
      className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
        loc.pathname.startsWith(to) && to !== '/'
          ? 'bg-primary-700 text-white'
          : 'text-primary-100 hover:bg-primary-700 hover:text-white'
      }`}
    >
      {label}
    </Link>
  );

  return (
    <nav className="bg-primary-800 shadow-lg sticky top-0 z-40">
      <div className="max-w-7xl mx-auto px-4">
        <div className="flex items-center justify-between h-14">
          {/* Logo */}
          <Link to="/" className="flex items-center gap-2">
            <div className="w-8 h-8 bg-white rounded flex items-center justify-center">
              <span className="text-primary-800 font-bold text-xs">ZUP</span>
            </div>
            <span className="text-white font-semibold text-sm hidden md:block">
              System Zarządzania Uprawnieniami
            </span>
          </Link>

          {/* Desktop nav */}
          <div className="hidden md:flex items-center gap-1">
            {link('/', 'Dashboard')}
            {link('/wnioski', 'Wnioski')}
            {(isIT || isKadry) && link('/pracownicy', 'Pracownicy')}
            {isKier && !isIT && link('/pracownicy', 'Pracownicy')}
            {isIT && link('/uprawnienia', 'Uprawnienia')}
            {isIT && link('/przeglady', 'Przeglądy')}
            {isIT && (
              <div className="relative group">
                <button className="px-3 py-2 rounded-md text-sm font-medium text-primary-100 hover:bg-primary-700 hover:text-white">
                  Rejestry ▾
                </button>
                <div className="absolute left-0 mt-0.5 w-48 bg-white rounded-md shadow-lg border border-gray-200 hidden group-hover:block z-50">
                  {[
                    ['/rejestry/systemy', 'Systemy IT'],
                    ['/rejestry/uprawnienia', 'Uprawnienia'],
                    ['/rejestry/uprzywilejowani', 'Uprzywilejowani'],
                    ['/rejestry/przeglady', 'Przeglądy'],
                    ['/rejestry/incydenty', 'Incydenty'],
                    ['/rejestry/audit', 'Audit Log'],
                  ].map(([to, lbl]) => (
                    <Link key={to} to={to} className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100">
                      {lbl}
                    </Link>
                  ))}
                </div>
              </div>
            )}
            {isIT && (
              <div className="relative group">
                <button className="px-3 py-2 rounded-md text-sm font-medium text-primary-100 hover:bg-primary-700 hover:text-white">
                  Admin ▾
                </button>
                <div className="absolute left-0 mt-0.5 w-48 bg-white rounded-md shadow-lg border border-gray-200 hidden group-hover:block z-50">
                  {[
                    ['/admin/jednostki', 'Jednostki'],
                    ['/admin/ldap', 'Domeny LDAP'],
                    ['/admin/struktura', 'Struktura org.'],
                    ['/admin/systemy-it', 'Systemy IT'],
                    ['/admin/uzytkownicy', 'Użytkownicy'],
                    ['/workflow', 'Szablony workflow'],
                    ['/admin/numeracja', 'Numeracja'],
                  ].map(([to, lbl]) => (
                    <Link key={to} to={to} className="block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100">
                      {lbl}
                    </Link>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right side */}
          <div className="flex items-center gap-3">
            {/* Notifications */}
            <div className="relative" ref={notifRef}>
              <button
                onClick={() => setNotifOpen(!notifOpen)}
                className="relative p-2 text-primary-100 hover:text-white rounded-full hover:bg-primary-700"
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
                </svg>
                {nieprzeczytane > 0 && (
                  <span className="absolute top-0 right-0 block h-4 w-4 rounded-full bg-red-500 text-white text-xs text-center leading-4">
                    {nieprzeczytane > 9 ? '9+' : nieprzeczytane}
                  </span>
                )}
              </button>
              {notifOpen && (
                <div className="absolute right-0 mt-1 w-80 bg-white rounded-md shadow-xl border border-gray-200 z-50">
                  <div className="flex items-center justify-between px-4 py-2 border-b">
                    <span className="font-semibold text-sm">Powiadomienia</span>
                    {nieprzeczytane > 0 && (
                      <button onClick={markAllRead} className="text-xs text-primary-600 hover:underline">
                        Oznacz wszystkie
                      </button>
                    )}
                  </div>
                  <div className="max-h-64 overflow-y-auto">
                    {items.length === 0 ? (
                      <p className="text-sm text-gray-500 text-center py-6">Brak nowych powiadomień</p>
                    ) : items.map(n => (
                      <div
                        key={n.id}
                        className={`px-4 py-3 border-b last:border-0 cursor-pointer hover:bg-gray-50 ${!n.przeczytane ? 'bg-blue-50' : ''}`}
                        onClick={() => { markRead(n.id); if (n.link) navigate(n.link); setNotifOpen(false); }}
                      >
                        <p className="text-sm text-gray-800">{n.tresc}</p>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {new Date(n.data_utworzenia).toLocaleString('pl-PL')}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* User menu */}
            {user && (
              <div className="relative">
                <button
                  onClick={() => setMenuOpen(!menuOpen)}
                  className="flex items-center gap-2 text-primary-100 hover:text-white"
                >
                  <div className="w-8 h-8 rounded-full bg-primary-600 flex items-center justify-center text-white text-sm font-medium">
                    {user.imie?.[0]}{user.nazwisko?.[0]}
                  </div>
                  <span className="hidden md:block text-sm">{user.imie} {user.nazwisko}</span>
                </button>
                {menuOpen && (
                  <div className="absolute right-0 mt-1 w-48 bg-white rounded-md shadow-lg border border-gray-200 z-50">
                    <div className="px-4 py-2 border-b">
                      <p className="text-sm font-medium text-gray-900">{user.imie} {user.nazwisko}</p>
                      <p className="text-xs text-gray-500">{ROLE_LABELS[user.rola]}</p>
                    </div>
                    <button
                      onClick={() => { logout(); setMenuOpen(false); }}
                      className="block w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                    >
                      Wyloguj
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
