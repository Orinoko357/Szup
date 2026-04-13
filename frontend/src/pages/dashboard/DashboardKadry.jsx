import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api/axios';

export default function DashboardKadry() {
  const [stats, setStats] = useState({});
  const [nowyPrac, setNowyPrac] = useState([]);

  useEffect(() => {
    api.get('/konfiguracja/dashboard').then(r => setStats(r.data));
    api.get('/pracownicy?aktywny=true').then(r => {
      const cutoff = new Date();
      cutoff.setDate(cutoff.getDate() - 30);
      setNowyPrac(r.data.filter(p => p.data_zatrudnienia && new Date(p.data_zatrudnienia) >= cutoff).slice(0, 10));
    });
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Dashboard – Kadry</h1>

      <div className="grid grid-cols-2 gap-4">
        <div className="card p-5">
          <p className="text-sm text-gray-500">Nowi pracownicy (30 dni)</p>
          <p className="text-3xl font-bold text-green-600 mt-1">{stats.nowi_pracownicy_30d ?? 0}</p>
        </div>
        <div className="card p-5">
          <p className="text-sm text-gray-500">Wnioski w toku</p>
          <p className="text-3xl font-bold text-blue-600 mt-1">{stats.wnioski_w_toku ?? 0}</p>
        </div>
      </div>

      <div className="card">
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <h2 className="font-semibold">Nowi pracownicy (ostatnie 30 dni)</h2>
          <Link to="/pracownicy" className="text-sm text-primary-600 hover:underline">Wszyscy →</Link>
        </div>
        {nowyPrac.length === 0 ? (
          <p className="px-5 py-8 text-center text-sm text-gray-400">Brak nowych pracowników</p>
        ) : (
          <ul className="divide-y divide-gray-100">
            {nowyPrac.map(p => (
              <li key={p.id} className="px-5 py-3 flex items-center justify-between hover:bg-gray-50">
                <div>
                  <p className="font-medium text-sm">{p.imie} {p.nazwisko}</p>
                  <p className="text-xs text-gray-500">{p.stanowisko || '—'} · {p.tenant_nazwa} · {p.komorka_nazwa || '—'}</p>
                </div>
                <Link to={`/pracownicy/${p.id}`} className="text-xs text-primary-600 hover:underline">Profil</Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
