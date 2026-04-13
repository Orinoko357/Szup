import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api/axios';
import { useAuth } from '../../hooks/useAuth';

export default function DashboardKier() {
  const { user } = useAuth();
  const [stats, setStats] = useState({});
  const [pending, setPending] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get('/konfiguracja/dashboard'),
      api.get('/wnioski/moje/do-zatwierdzenia'),
    ]).then(([s, p]) => {
      setStats(s.data);
      setPending(p.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">
        Witaj, {user?.imie} {user?.nazwisko}
      </h1>

      <div className="grid grid-cols-3 gap-4">
        {[
          { label: 'Do zatwierdzenia', value: stats.do_zatwierdzenia, color: 'bg-yellow-500', to: '/wnioski' },
          { label: 'Moje wnioski w toku', value: stats.moje_wnioski_w_toku, color: 'bg-blue-500', to: '/wnioski' },
          { label: 'Podwładni', value: stats.liczba_podwladnych, color: 'bg-green-500', to: '/pracownicy' },
        ].map(({ label, value, color, to }) => (
          <Link key={label} to={to} className="card p-5 hover:shadow-md transition-shadow">
            <p className="text-sm text-gray-500">{label}</p>
            <p className={`text-3xl font-bold mt-1 ${color.replace('bg-', 'text-')}`}>{value ?? 0}</p>
          </Link>
        ))}
      </div>

      {pending.length > 0 && (
        <div className="card">
          <div className="px-5 py-4 border-b flex items-center justify-between">
            <h2 className="font-semibold text-gray-900 flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
              Wnioski oczekujące na moje zatwierdzenie ({pending.length})
            </h2>
            <Link to="/wnioski" className="text-sm text-primary-600 hover:underline">Wszystkie →</Link>
          </div>
          <div className="divide-y divide-gray-100">
            {pending.map(w => (
              <div key={w.id} className="px-5 py-4 flex items-center justify-between hover:bg-gray-50">
                <div>
                  <p className="font-medium text-sm text-gray-900">{w.numer || '(szkic)'} – {w.pracownik_nazwa}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {w.etap_nazwa || `Etap ${w.etap_kolejnosc}`} · {w.tenant_nazwa} ·{' '}
                    Oczekuje od {new Date(w.data_przypisania).toLocaleDateString('pl-PL')}
                  </p>
                </div>
                <Link to={`/wnioski/${w.id}/zatwierdz`} className="btn-primary btn-sm ml-4">
                  Rozpatrz
                </Link>
              </div>
            ))}
          </div>
        </div>
      )}

      {pending.length === 0 && (
        <div className="card p-8 text-center text-gray-400">
          <p className="text-lg">Brak wniosków oczekujących na zatwierdzenie.</p>
        </div>
      )}
    </div>
  );
}
