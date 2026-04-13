import { useState, useEffect } from 'react';
import api from '../../api/axios';

const STATUS_BADGE = { W_TOKU: 'badge-blue', 'ZAKOŃCZONY': 'badge-green', ANULOWANY: 'badge-gray' };

export default function RejestrPrzeglady() {
  const [data, setData] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => { api.get('/tenants').then(r => setTenants(r.data)); }, []);

  useEffect(() => {
    setLoading(true);
    const p = tenantId ? `?tenant_id=${tenantId}` : '';
    api.get(`/rejestry/przeglady${p}`).then(r => { setData(r.data); setLoading(false); });
  }, [tenantId]);

  const exportData = (fmt) => {
    const p = new URLSearchParams();
    if (tenantId) p.set('tenant_id', tenantId);
    p.set('format', fmt);
    window.open(`/api/rejestry/przeglady?${p}`, '_blank');
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Rejestr przeglądów uprawnień NIS2</h1>
        <div className="flex gap-2">
          <button onClick={() => exportData('xlsx')} className="btn-secondary btn-sm">XLSX</button>
          <button onClick={() => exportData('csv')} className="btn-secondary btn-sm">CSV</button>
        </div>
      </div>

      <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={tenantId} onChange={e => setTenantId(e.target.value)}>
        <option value="">Wszystkie jednostki</option>
        {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
      </select>

      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {['Nr', 'Jednostka', 'Typ', 'Status', 'Data rozp.', 'Data zak.', 'Inicjujący', 'Pozostaw', 'Cofnij', 'Zmod.'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={10} className="py-8 text-center"><div className="inline-block animate-spin h-6 w-6 border-4 border-primary-500 border-t-transparent rounded-full" /></td></tr>
            ) : data.map(p => (
              <tr key={p.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">#{p.id}</td>
                <td className="px-4 py-3 text-gray-600">{p.tenant_nazwa}</td>
                <td className="px-4 py-3 text-gray-500">{p.typ}</td>
                <td className="px-4 py-3"><span className={STATUS_BADGE[p.status] || 'badge-gray'}>{p.status}</span></td>
                <td className="px-4 py-3 text-gray-500">{new Date(p.data_rozpoczecia).toLocaleDateString('pl-PL')}</td>
                <td className="px-4 py-3 text-gray-500">{p.data_zakonczenia ? new Date(p.data_zakonczenia).toLocaleDateString('pl-PL') : '—'}</td>
                <td className="px-4 py-3 text-gray-500">{p.inicjujacy_nazwa}</td>
                <td className="px-4 py-3 text-green-600 font-medium">{p.pozostaw ?? 0}</td>
                <td className="px-4 py-3 text-red-600 font-medium">{p.cofnij ?? 0}</td>
                <td className="px-4 py-3 text-yellow-600 font-medium">{p.zmodyfikuj ?? 0}</td>
              </tr>
            ))}
            {!loading && data.length === 0 && (
              <tr><td colSpan={10} className="py-8 text-center text-gray-400">Brak przeglądów.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
