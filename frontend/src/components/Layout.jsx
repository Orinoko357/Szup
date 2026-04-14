import { useState } from 'react';
import { Outlet } from 'react-router-dom';
import Sidebar from './Nav';
import { useAuth } from '../hooks/useAuth';
import { usePowiadomienia } from '../hooks/usePowiadomienia';
import { useNavigate } from 'react-router-dom';
import { Bell, LogOut, Moon, Sun } from 'lucide-react';

export default function Layout() {
  const { user, logout } = useAuth();
  const { nieprzeczytane, items, markRead, markAllRead } = usePowiadomienia();
  const [notifOpen, setNotifOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const navigate = useNavigate();

  function toggleDark() {
    const next = !dark;
    setDark(next);
    document.documentElement.setAttribute('data-theme', next ? 'dark' : 'light');
  }

  return (
    <div className="app-grid">
      {/* ── Header ── */}
      <header className="app-header">
        <div className="header-logo-icon">ZUP</div>
        <span className="header-logo-text">System Zarządzania Uprawnieniami</span>

        <div className="ml-auto flex items-center gap-2">
          {/* Notifications */}
          <div className="relative">
            <button className="header-notif-btn" onClick={() => setNotifOpen(o => !o)}>
              <Bell size={18} />
              {nieprzeczytane > 0 && (
                <span className="absolute -top-0.5 -right-0.5 w-4 h-4 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center leading-none">
                  {nieprzeczytane > 9 ? '9+' : nieprzeczytane}
                </span>
              )}
            </button>
            {notifOpen && (
              <div className="absolute right-0 mt-2 w-80 bg-white rounded-lg shadow-xl border border-gray-200 z-50 overflow-hidden">
                <div className="flex items-center justify-between px-4 py-2.5 border-b bg-gray-50">
                  <span className="text-xs font-700 uppercase tracking-wider text-gray-600">Powiadomienia</span>
                  {nieprzeczytane > 0 && (
                    <button onClick={markAllRead} className="text-xs text-navy-600 hover:underline font-semibold">
                      Oznacz wszystkie
                    </button>
                  )}
                </div>
                <div className="max-h-72 overflow-y-auto divide-y divide-gray-100">
                  {items.length === 0
                    ? <p className="text-sm text-gray-500 text-center py-6">Brak nowych powiadomień</p>
                    : items.map(n => (
                      <div
                        key={n.id}
                        className={`px-4 py-3 cursor-pointer hover:bg-gray-50 transition-colors ${!n.przeczytane ? 'bg-blue-50' : ''}`}
                        onClick={() => { markRead(n.id); if (n.link) navigate(n.link); setNotifOpen(false); }}
                      >
                        <p className="text-sm text-gray-800">{n.tresc}</p>
                        <p className="text-xs text-gray-400 mt-0.5">{new Date(n.data_utworzenia).toLocaleString('pl-PL')}</p>
                      </div>
                    ))
                  }
                </div>
              </div>
            )}
          </div>

          {/* User info */}
          {user && (
            <div className="flex items-center gap-2 px-3 py-1">
              <div className="w-7 h-7 rounded-full bg-gold-500 flex items-center justify-center text-white text-xs font-bold">
                {user.imie?.[0]}{user.nazwisko?.[0]}
              </div>
              <span className="text-sm text-white/80 hidden md:block">{user.imie} {user.nazwisko}</span>
            </div>
          )}

          {/* Logout */}
          <button className="header-logout-btn" onClick={logout}>
            <LogOut size={14} className="inline mr-1" />
            Wyloguj
          </button>
        </div>
      </header>

      {/* ── Sidebar ── */}
      <aside className="app-sidebar">
        <Sidebar />
      </aside>

      {/* ── Main ── */}
      <main className="app-main">
        <Outlet />
      </main>

      {/* ── Dark mode toggle ── */}
      <button className="dark-mode-toggle" onClick={toggleDark} title="Przełącz motyw">
        {dark ? <Sun size={18} /> : <Moon size={18} />}
      </button>
    </div>
  );
}
