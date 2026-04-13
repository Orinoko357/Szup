import { useState, useEffect, useCallback } from 'react';
import api from '../../api/axios';

export default function AuditLog() {
  const [data, setData] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [filters, setFilters] = useState({ akcja: '', uzytkownik: '', tabela: '', od: '', do: '' });
  const limit = 50;

  const load = useCallback(() => {
    setLoading(true);
    const p = new URLSearchParams({ page, limit });
    if (filters.akcja) p.set('akcja', filters.akcja);
    if (filters.uzytkownik) p.set('uzytkownik', filters.uzytkownik);
    if (filters.tabela) p.set('tabela', filters.tabela);
    if (filters.od) p.set('od', filters.od);
    if (filters.do) p.set('do', filters.do);
    api.get(`/rejestry/audit?${p}`).then(r => {
      setData(r.data.rows || r.data);
      setTotal(r.data.total || 0);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [page, filters]);

  useEffect(() => { load(); }, [load]);

  const exportLog = (fmt) => {
    const p = new URLSearchParams({ format: fmt });
    if (filters.akcja) p.set('akcja', filters.akcja);
    if (filters.od) p.set('od', filters.od);
    if (filters.do) p.set('do', filters.do);
    window.open(`/api/rejestry/audit?${p}`, '_blank');
  };

  const pages = Math.ceil(total / limit);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dziennik audytowy</h1>
          <p className="text-sm text-gray-500 mt-0.5">Tamper-proof log wszystkich operacji w systemie</p>
        </div>
        <div className="flex gap-2">
          <button onClick={() => exportLog('xlsx')} className="btn-secondary btn-sm">XLSX</button>
          <button onClick={() => exportLog('csv')} className="btn-secondary btn-sm">CSV</button>
        </div>
      </div>

      <div className="card p-4 flex flex-wrap gap-3">
        <input
          type="text" placeholder="Akcja (np. ZATWIERDZENIE)" className="border border-gray-300 rounded px-3 py-1.5 text-sm w-52"
          value={filters.akcja} onChange={e => { setFilters({ ...filters, akcja: e.target.value }); setPage(1); }}
        />
        <input
          type="text" placeholder="Użytkownik" className="border border-gray-300 rounded px-3 py-1.5 text-sm w-40"
          value={filters.uzytkownik} onChange={e => { setFilters({ ...filters, uzytkownik: e.target.value }); setPage(1); }}
        />
        <input
          type="text" placeholder="Tabela" className="border border-gray-300 rounded px-3 py-1.5 text-sm w-40"
          value={filters.tabela} onChange={e => { setFilters({ ...filters, tabela: e.target.value }); setPage(1); }}
        />
        <input
          type="date" className="border border-gray-300 rounded px-3 py-1.5 text-sm"
          value={filters.od} onChange={e => { setFilters({ ...filters, od: e.target.value }); setPage(1); }}
        />
        <input
          type="date" className="border border-gray-300 rounded px-3 py-1.5 text-sm"
          value={filters.do} onChange={e => { setFilters({ ...filters, do: e.target.value }); setPage(1); }}
        />
        <button onClick={() => { setFilters({ akcja: '', uzytkownik: '', tabela: '', od: '', do: '' }); setPage(1); }} className="btn-secondary btn-sm">Wyczyść</button>
      </div>

      <div className="text-sm text-gray-500">Łącznie: {total} wpisów</div>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-gray-200 text-sm">
            <thead className="bg-gray-50">
              <tr>
                {['ID', 'Czas', 'Użytkownik', 'Akcja', 'Tabela', 'Rekord', 'IP', 'Szczegóły'].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loading ? (
                <tr><td colSpan={8} className="py-8 text-center"><div className="inline-block animate-spin h-6 w-6 border-4 border-primary-500 border-t-transparent rounded-full" /></td></tr>
              ) : data.map(entry => (
                <tr key={entry.id} className="hover:bg-gray-50">
                  <td className="px-4 py-2 text-gray-400 text-xs">{entry.id}</td>
                  <td className="px-4 py-2 text-gray-500 whitespace-nowrap text-xs">{new Date(entry.created_at).toLocaleString('pl-PL')}</td>
                  <td className="px-4 py-2 font-medium">{entry.uzytkownik_login || '—'}</td>
                  <td className="px-4 py-2">
                    <span className="font-mono text-xs bg-gray-100 px-1.5 py-0.5 rounded">{entry.akcja}</span>
                  </td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{entry.tabela || '—'}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{entry.rekord_id || '—'}</td>
                  <td className="px-4 py-2 text-gray-400 text-xs">{entry.ip_adres || '—'}</td>
                  <td className="px-4 py-2 text-xs max-w-xs">
                    {entry.nowe_dane && (
                      <details>
                        <summary className="cursor-pointer text-primary-600 hover:underline">Dane</summary>
                        <pre className="mt-1 text-xs bg-gray-50 p-2 rounded overflow-auto max-h-40">{JSON.stringify(entry.nowe_dane, null, 2)}</pre>
                      </details>
                    )}
                  </td>
                </tr>
              ))}
              {!loading && data.length === 0 && (
                <tr><td colSpan={8} className="py-8 text-center text-gray-400">Brak wpisów.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {pages > 1 && (
        <div className="flex items-center justify-center gap-2 text-sm">
          <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="btn-secondary btn-sm">Poprzednia</button>
          <span className="text-gray-600">Strona {page} z {pages}</span>
          <button onClick={() => setPage(p => Math.min(pages, p + 1))} disabled={page === pages} className="btn-secondary btn-sm">Następna</button>
        </div>
      )}
    </div>
  );
}
