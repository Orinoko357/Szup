import { useState, useEffect } from 'react';
import api from '../../api/axios';

export default function RejestrUprzywilejowani() {
  const [data, setData] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => { api.get('/tenants').then(r => setTenants(r.data)); }, []);

  useEffect(() => {
    setLoading(true);
    const p = tenantId ? `?tenant_id=${tenantId}` : '';
    api.get(`/rejestry/uprzywilejowani${p}`).then(r => { setData(r.data); setLoading(false); });
  }, [tenantId]);

  const exportData = (fmt) => {
    const p = new URLSearchParams();
    if (tenantId) p.set('tenant_id', tenantId);
    p.set('format', fmt);
    window.open(`/api/rejestry/uprzywilejowani?${p}`, '_blank');
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Rejestr kont uprzywilejowanych</h1>
        <div className="flex gap-2">
          <button onClick={() => exportData('xlsx')} className="btn-secondary btn-sm">XLSX</button>
          <button onClick={() => exportData('csv')} className="btn-secondary btn-sm">CSV</button>
        </div>
      </div>

      <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
        Lista aktywnych uprawnień o podwyższonym poziomie dostępu (konta uprzywilejowane). Wymóg art. 21 NIS2.
      </div>

      <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={tenantId} onChange={e => setTenantId(e.target.value)}>
        <option value="">Wszystkie jednostki</option>
        {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
      </select>

      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {['Pracownik', 'Jednostka', 'System', 'Zakres', 'Data nadania', 'Ostatni przegląd', 'Wynik przeglądu'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={7} className="py-8 text-center"><div className="inline-block animate-spin h-6 w-6 border-4 border-primary-500 border-t-transparent rounded-full" /></td></tr>
            ) : data.map(u => (
              <tr key={u.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{u.pracownik_nazwa}</td>
                <td className="px-4 py-3 text-gray-500">{u.tenant_nazwa}</td>
                <td className="px-4 py-3">{u.system_nazwa}</td>
                <td className="px-4 py-3">
                  <span className="font-medium">{u.zakres_nazwa}</span>
                  <span className="ml-2 badge-red text-xs">UPRZYW.</span>
                </td>
                <td className="px-4 py-3 text-gray-500">{u.data_od ? new Date(u.data_od).toLocaleDateString('pl-PL') : '—'}</td>
                <td className="px-4 py-3 text-gray-500">{u.data_przegladu ? new Date(u.data_przegladu).toLocaleDateString('pl-PL') : <span className="text-amber-600">Brak przeglądu</span>}</td>
                <td className="px-4 py-3">
                  {u.wynik_przegladu === 'POZOSTAW' && <span className="badge-green">Pozostaw</span>}
                  {u.wynik_przegladu === 'ZMODYFIKUJ' && <span className="badge-yellow">Zmodyfikuj</span>}
                  {!u.wynik_przegladu && <span className="badge-gray">—</span>}
                </td>
              </tr>
            ))}
            {!loading && data.length === 0 && (
              <tr><td colSpan={7} className="py-8 text-center text-gray-400">Brak kont uprzywilejowanych.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
