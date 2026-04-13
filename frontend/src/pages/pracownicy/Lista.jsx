import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api/axios';
import { useAuth } from '../../hooks/useAuth';

export default function PracownicyLista() {
  const { user } = useAuth();
  const [pracownicy, setPracownicy] = useState([]);
  const [q, setQ] = useState('');
  const [tenantId, setTenantId] = useState('');
  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const isIT = ['IT_ADMIN', 'SUPERADMIN'].includes(user?.rola);

  useEffect(() => {
    if (isIT) api.get('/tenants').then(r => setTenants(r.data));
  }, [isIT]);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ aktywny: 'true' });
    if (q) params.set('q', q);
    if (tenantId) params.set('tenant_id', tenantId);
    api.get(`/pracownicy?${params}`).then(r => { setPracownicy(r.data); setLoading(false); });
  }, [q, tenantId]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Pracownicy</h1>
        {isIT && <Link to="/pracownicy/nowy" className="btn-primary">+ Nowy pracownik</Link>}
      </div>

      <div className="flex gap-3">
        <input
          type="search"
          placeholder="Szukaj po nazwisku, emailu..."
          className="border border-gray-300 rounded-md px-3 py-2 text-sm flex-1 max-w-xs focus:ring-2 focus:ring-primary-500 focus:outline-none"
          value={q}
          onChange={e => setQ(e.target.value)}
        />
        {isIT && (
          <select
            className="border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
            value={tenantId}
            onChange={e => setTenantId(e.target.value)}
          >
            <option value="">Wszystkie jednostki</option>
            {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
          </select>
        )}
      </div>

      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200">
          <thead className="bg-gray-50">
            <tr>
              {['Imię i nazwisko', 'Stanowisko', 'Komórka', ...(isIT ? ['Jednostka'] : []), 'Przełożony', 'Akcje'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={10} className="py-8 text-center"><div className="inline-block animate-spin h-6 w-6 border-4 border-primary-500 border-t-transparent rounded-full" /></td></tr>
            ) : pracownicy.map(p => (
              <tr key={p.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 text-sm">
                  <div className="font-medium">{p.imie} {p.nazwisko}</div>
                  <div className="text-xs text-gray-400">{p.email}</div>
                </td>
                <td className="px-4 py-3 text-sm text-gray-600">{p.stanowisko || '—'}</td>
                <td className="px-4 py-3 text-sm text-gray-600">{p.komorka_nazwa || '—'}</td>
                {isIT && <td className="px-4 py-3 text-sm text-gray-500">{p.tenant_nazwa}</td>}
                <td className="px-4 py-3 text-sm text-gray-500">{p.przel_nazwa || '—'}</td>
                <td className="px-4 py-3">
                  <div className="flex gap-2">
                    <Link to={`/pracownicy/${p.id}`} className="text-xs text-primary-600 hover:underline">Profil</Link>
                    {['KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'].includes(user?.rola) && (
                      <Link to={`/wnioski/nowy?pracownik_id=${p.id}`} className="text-xs text-green-600 hover:underline">Wniosek</Link>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {!loading && pracownicy.length === 0 && (
              <tr><td colSpan={10} className="py-8 text-center text-sm text-gray-400">Brak pracowników.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
