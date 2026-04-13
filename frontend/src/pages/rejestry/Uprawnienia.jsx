import { useState, useEffect } from 'react';
import api from '../../api/axios';

export default function RejestrUprawnienia() {
  const [data, setData] = useState([]);
  const [tenants, setTenants] = useState([]);
  const [systemy, setSystemy] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [systemId, setSystemId] = useState('');
  const [aktywne, setAktywne] = useState('true');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    Promise.all([api.get('/tenants'), api.get('/systemy-it')]).then(([t, s]) => {
      setTenants(t.data);
      setSystemy(s.data);
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    const p = new URLSearchParams();
    if (tenantId) p.set('tenant_id', tenantId);
    if (systemId) p.set('system_id', systemId);
    if (aktywne) p.set('aktywne', aktywne);
    api.get(`/uprawnienia?${p}`).then(r => { setData(r.data); setLoading(false); });
  }, [tenantId, systemId, aktywne]);

  const exportData = (fmt) => {
    const p = new URLSearchParams();
    if (tenantId) p.set('tenant_id', tenantId);
    if (systemId) p.set('system_id', systemId);
    if (aktywne) p.set('aktywne', aktywne);
    p.set('format', fmt);
    window.open(`/api/uprawnienia?${p}`, '_blank');
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Rejestr uprawnień</h1>
        <div className="flex gap-2">
          <button onClick={() => exportData('xlsx')} className="btn-secondary btn-sm">XLSX</button>
          <button onClick={() => exportData('csv')} className="btn-secondary btn-sm">CSV</button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3">
        <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={tenantId} onChange={e => setTenantId(e.target.value)}>
          <option value="">Wszystkie jednostki</option>
          {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
        </select>
        <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={systemId} onChange={e => setSystemId(e.target.value)}>
          <option value="">Wszystkie systemy</option>
          {systemy.map(s => <option key={s.id} value={s.id}>{s.nazwa}</option>)}
        </select>
        <select className="border border-gray-300 rounded px-3 py-1.5 text-sm" value={aktywne} onChange={e => setAktywne(e.target.value)}>
          <option value="true">Aktywne</option>
          <option value="false">Cofnięte</option>
          <option value="">Wszystkie</option>
        </select>
      </div>

      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {['Pracownik', 'Jednostka', 'System', 'Zakres', 'Uprzyw.', 'Data nadania', 'Wniosek', 'Status'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={8} className="py-8 text-center"><div className="inline-block animate-spin h-6 w-6 border-4 border-primary-500 border-t-transparent rounded-full" /></td></tr>
            ) : data.map(u => (
              <tr key={u.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">{u.pracownik_nazwa}</td>
                <td className="px-4 py-3 text-gray-500">{u.tenant_nazwa}</td>
                <td className="px-4 py-3">{u.system_nazwa}</td>
                <td className="px-4 py-3">{u.zakres_nazwa}</td>
                <td className="px-4 py-3">{u.uprzywilejowany ? <span className="badge-red text-xs">TAK</span> : '—'}</td>
                <td className="px-4 py-3 text-gray-500">{u.data_od ? new Date(u.data_od).toLocaleDateString('pl-PL') : '—'}</td>
                <td className="px-4 py-3 text-xs text-gray-500">{u.numer || (u.nadane_bezposrednio ? 'Bezpośrednie' : '—')}</td>
                <td className="px-4 py-3">{u.aktywne ? <span className="badge-green">Aktywne</span> : <span className="badge-red">Cofnięte</span>}</td>
              </tr>
            ))}
            {!loading && data.length === 0 && (
              <tr><td colSpan={8} className="py-8 text-center text-gray-400">Brak uprawnień.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
