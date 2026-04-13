import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api/axios';

const STATUS_BADGE = {
  SZKIC:          'badge-gray',
  W_TOKU:         'badge-blue',
  WYMAGA_POPRAWY: 'badge-yellow',
  OCZEKUJE_IT:    'badge-purple',
  ZREALIZOWANY:   'badge-green',
  ODRZUCONY:      'badge-red',
};

const STATUS_LABEL = {
  SZKIC: 'Szkic', W_TOKU: 'W toku', WYMAGA_POPRAWY: 'Wymaga poprawy',
  OCZEKUJE_IT: 'Oczekuje IT', ZREALIZOWANY: 'Zrealizowany', ODRZUCONY: 'Odrzucony',
};

function StatCard({ label, value, color, to }) {
  const content = (
    <div className={`card p-5 flex items-center gap-4 ${to ? 'hover:shadow-md transition-shadow cursor-pointer' : ''}`}>
      <div className={`w-12 h-12 rounded-xl flex items-center justify-center text-white text-lg font-bold ${color}`}>
        {value}
      </div>
      <div>
        <p className="text-sm text-gray-500">{label}</p>
        <p className="text-xl font-bold text-gray-900">{value ?? '–'}</p>
      </div>
    </div>
  );
  return to ? <Link to={to}>{content}</Link> : content;
}

export default function DashboardIT() {
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/konfiguracja/dashboard').then(r => {
      setStats(r.data);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Dashboard – Administrator IT</h1>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-4">
        <StatCard label="Oczekujące IT" value={stats.wnioski_oczekujace_it} color="bg-purple-500" to="/wnioski?status=OCZEKUJE_IT" />
        <StatCard label="Uprawnienia aktywne" value={stats.uprawnienia_aktywne} color="bg-green-500" to="/uprawnienia" />
        <StatCard label="Przeglądy zaległe" value={stats.przeglady_zagle} color="bg-yellow-500" to="/przeglady" />
        <StatCard label="Incydenty otwarte" value={stats.incydenty_otwarte} color="bg-red-500" to="/rejestry/incydenty" />
        <StatCard label="Eskalacje aktywne" value={stats.eskalacje_aktywne} color="bg-orange-500" to="/wnioski" />
      </div>

      {stats.przeglady_zagle > 0 && (
        <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-4 flex items-center gap-3">
          <span className="text-yellow-600 text-lg">⚠</span>
          <span className="text-yellow-800 text-sm font-medium">
            {stats.przeglady_zagle} uprawnień wymaga przeglądu NIS2.
          </span>
          <Link to="/przeglady" className="ml-auto btn btn-warning btn-sm">Przejdź do przeglądów</Link>
        </div>
      )}
      {stats.eskalacje_aktywne > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-4 flex items-center gap-3">
          <span className="text-red-600 text-lg">🔔</span>
          <span className="text-red-800 text-sm font-medium">
            {stats.eskalacje_aktywne} eskalacji aktywnych – zatwierdzający nie reaguje.
          </span>
        </div>
      )}

      <div className="card">
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <h2 className="font-semibold text-gray-900">Ostatnie wnioski</h2>
          <Link to="/wnioski" className="text-sm text-primary-600 hover:underline">Zobacz wszystkie →</Link>
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-100">
            <thead className="bg-gray-50">
              <tr>
                {['Numer', 'Pracownik', 'Jednostka', 'Status', 'Data'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {(stats.ostatnie_wnioski || []).map(w => (
                <tr key={w.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm">
                    <Link to={`/wnioski/${w.id}`} className="text-primary-600 hover:underline font-medium">{w.numer || '(szkic)'}</Link>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-700">{w.pracownik_nazwa}</td>
                  <td className="px-4 py-3 text-sm text-gray-500">{w.tenant_skrot}</td>
                  <td className="px-4 py-3">
                    <span className={STATUS_BADGE[w.status]}>{STATUS_LABEL[w.status]}</span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {new Date(w.data_ostatniej_zmiany).toLocaleDateString('pl-PL')}
                  </td>
                </tr>
              ))}
              {(!stats.ostatnie_wnioski || stats.ostatnie_wnioski.length === 0) && (
                <tr><td colSpan={5} className="px-4 py-6 text-center text-sm text-gray-400">Brak wniosków</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
