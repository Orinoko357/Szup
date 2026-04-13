import { useState, useEffect } from 'react';
import api from '../../api/axios';

const KRYT_BADGE = { NISKI:'badge-green',SREDNI:'badge-blue',WYSOKI:'badge-yellow',KRYTYCZNY:'badge-red' };

export default function RejestrSystemy() {
  const [data, setData] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');

  useEffect(() => { api.get('/tenants').then(r => setTenants(r.data)); }, []);
  useEffect(() => {
    const p = tenantId ? `?tenant_id=${tenantId}` : '';
    api.get(`/rejestry/systemy${p}`).then(r => setData(r.data));
  }, [tenantId]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Rejestr systemów IT</h1>
        <div className="flex gap-2">
          <button onClick={() => window.open(`/api/rejestry/systemy?format=xlsx${tenantId ? `&tenant_id=${tenantId}` : ''}`, '_blank')} className="btn-secondary btn-sm">XLSX</button>
          <button onClick={() => window.open(`/api/rejestry/systemy?format=csv${tenantId ? `&tenant_id=${tenantId}` : ''}`, '_blank')} className="btn-secondary btn-sm">CSV</button>
        </div>
      </div>
      <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={tenantId} onChange={e => setTenantId(e.target.value)}>
        <option value="">Wszystkie jednostki</option>
        {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
      </select>
      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>{['Nazwa', 'Jednostka', 'Krytyczność', 'Właściciel', 'Użytkownicy', 'Ostatni przegląd'].map(h => <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {data.map(s => (
              <tr key={s.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{s.nazwa}</td>
                <td className="px-4 py-3 text-gray-500">{s.tenant_nazwa || 'Wspólny'}</td>
                <td className="px-4 py-3"><span className={KRYT_BADGE[s.poziom_krytycznosci]}>{s.poziom_krytycznosci}</span></td>
                <td className="px-4 py-3 text-gray-600">{s.wlasciciel || '—'}</td>
                <td className="px-4 py-3">{s.aktywni_uzytkownicy ?? 0}</td>
                <td className="px-4 py-3 text-gray-500">{s.ostatni_przeglad ? new Date(s.ostatni_przeglad).toLocaleDateString('pl-PL') : '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
