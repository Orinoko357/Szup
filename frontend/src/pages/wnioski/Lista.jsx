import { useState, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import api from '../../api/axios';
import { useAuth } from '../../hooks/useAuth';
import Table from '../../components/Table';

const STATUS_BADGE = {
  SZKIC: 'badge-gray', W_TOKU: 'badge-blue', WYMAGA_POPRAWY: 'badge-yellow',
  OCZEKUJE_IT: 'badge-purple', ZREALIZOWANY: 'badge-green', ODRZUCONY: 'badge-red',
};
const STATUS_LABEL = {
  SZKIC: 'Szkic', W_TOKU: 'W toku', WYMAGA_POPRAWY: 'Wymaga poprawy',
  OCZEKUJE_IT: 'Oczekuje IT', ZREALIZOWANY: 'Zrealizowany', ODRZUCONY: 'Odrzucony',
};

export default function WnioskiLista() {
  const { user } = useAuth();
  const [sp] = useSearchParams();
  const [data, setData] = useState({ data: [], total: 0 });
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(sp.get('status') || '');

  const isIT = ['IT_ADMIN', 'SUPERADMIN'].includes(user?.rola);

  useEffect(() => {
    setLoading(true);
    const params = new URLSearchParams({ page, limit: 20 });
    if (status) params.set('status', status);
    api.get(`/wnioski?${params}`).then(r => { setData(r.data); setLoading(false); }).catch(() => setLoading(false));
  }, [page, status]);

  const cols = [
    { key: 'numer', label: 'Numer', render: (v, row) => <Link to={`/wnioski/${row.id}`} className="text-primary-600 hover:underline font-medium">{v || '(szkic)'}</Link> },
    { key: 'pracownik_nazwa', label: 'Pracownik' },
    ...(isIT ? [{ key: 'tenant_nazwa', label: 'Jednostka' }] : []),
    { key: 'status', label: 'Status', render: v => <span className={STATUS_BADGE[v]}>{STATUS_LABEL[v]}</span> },
    { key: 'aktualny_etap_kolejnosc', label: 'Etap', render: v => v ? `Etap ${v}` : '—' },
    { key: 'liczba_pozycji', label: 'Pozycji', render: v => v ?? 0 },
    { key: 'data_ostatniej_zmiany', label: 'Ostatnia zmiana', render: v => new Date(v).toLocaleDateString('pl-PL') },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Wnioski</h1>
        {['KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'].includes(user?.rola) && (
          <Link to="/wnioski/nowy" className="btn-primary">+ Nowy wniosek</Link>
        )}
      </div>

      <div className="flex gap-2 flex-wrap">
        {['', 'SZKIC', 'W_TOKU', 'WYMAGA_POPRAWY', 'OCZEKUJE_IT', 'ZREALIZOWANY', 'ODRZUCONY'].map(s => (
          <button
            key={s}
            onClick={() => { setStatus(s); setPage(1); }}
            className={`px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
              status === s ? 'bg-primary-600 text-white' : 'bg-white border border-gray-300 text-gray-600 hover:bg-gray-50'
            }`}
          >
            {s ? STATUS_LABEL[s] : 'Wszystkie'}
          </button>
        ))}
      </div>

      <Table
        columns={cols}
        data={data.data}
        loading={loading}
        total={data.total}
        page={page}
        limit={20}
        onPageChange={setPage}
      />
    </div>
  );
}
