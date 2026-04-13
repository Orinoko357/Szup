import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router-dom';
import api from '../../api/axios';
import { useAuth } from '../../hooks/useAuth';

export default function PracownikProfil() {
  const { id } = useParams();
  const { user } = useAuth();
  const [prac, setPrac] = useState(null);
  const [uprawnienia, setUprawnienia] = useState([]);
  const [wnioski, setWnioski] = useState([]);
  const [podwladni, setPodwladni] = useState([]);
  const isIT = ['IT_ADMIN', 'SUPERADMIN'].includes(user?.rola);

  useEffect(() => {
    Promise.all([
      api.get(`/pracownicy/${id}`),
      api.get(`/uprawnienia?pracownik_id=${id}&aktywne=true`),
    ]).then(([p, u]) => {
      setPrac(p.data);
      setUprawnienia(u.data);
    });
    if (isIT || user?.rola === 'KIEROWNIK') {
      api.get(`/pracownicy/${id}/podwladni`).then(r => setPodwladni(r.data)).catch(() => {});
    }
  }, [id, isIT]);

  if (!prac) return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>;

  return (
    <div className="max-w-4xl space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">{prac.imie} {prac.nazwisko}</h1>
          <p className="text-gray-500">{prac.stanowisko || '—'} · {prac.komorka_nazwa || '—'} · {prac.tenant_nazwa}</p>
        </div>
        <div className="flex gap-2">
          {['KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'].includes(user?.rola) && (
            <Link to={`/wnioski/nowy?pracownik_id=${id}`} className="btn-primary">Złóż wniosek</Link>
          )}
          {isIT && <Link to={`/pracownicy/${id}/edytuj`} className="btn-secondary">Edytuj</Link>}
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: 'Email', val: prac.email },
          { label: 'Przełożony', val: prac.przel_nazwa || '—' },
          { label: 'Data zatrudnienia', val: prac.data_zatrudnienia ? new Date(prac.data_zatrudnienia).toLocaleDateString('pl-PL') : '—' },
          { label: 'Aktywne uprawnienia', val: prac.liczba_uprawnien ?? uprawnienia.length },
        ].map(({ label, val }) => (
          <div key={label} className="card p-4">
            <p className="text-xs text-gray-500">{label}</p>
            <p className="text-sm font-medium mt-1">{val}</p>
          </div>
        ))}
      </div>

      {/* Active permissions */}
      <div className="card">
        <div className="px-5 py-4 border-b flex items-center justify-between">
          <h2 className="font-semibold">Aktywne uprawnienia ({uprawnienia.length})</h2>
          {isIT && (
            <Link to={`/uprawnienia?pracownik_id=${id}`} className="text-sm text-primary-600 hover:underline">Zarządzaj →</Link>
          )}
        </div>
        {uprawnienia.length === 0 ? (
          <p className="px-5 py-6 text-sm text-gray-400 text-center">Brak aktywnych uprawnień.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-100 text-sm">
              <thead className="bg-gray-50">
                <tr>
                  {['System', 'Moduł', 'Zakres', 'Uprzyw.', 'Data nadania', 'Wniosek'].map(h => (
                    <th key={h} className="px-4 py-2 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {uprawnienia.map(u => (
                  <tr key={u.id}>
                    <td className="px-4 py-2 font-medium">{u.system_nazwa}</td>
                    <td className="px-4 py-2 text-gray-500">{u.modul_nazwa || '—'}</td>
                    <td className="px-4 py-2">{u.zakres_nazwa}</td>
                    <td className="px-4 py-2">{u.uprzywilejowany ? <span className="badge-red text-xs">TAK</span> : '—'}</td>
                    <td className="px-4 py-2 text-gray-500">{u.data_od ? new Date(u.data_od).toLocaleDateString('pl-PL') : '—'}</td>
                    <td className="px-4 py-2">
                      {u.numer ? <Link to={`/wnioski`} className="text-xs text-primary-600 hover:underline">{u.numer}</Link> : <span className="text-xs text-gray-400">Bezpośrednie</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {podwladni.length > 0 && (
        <div className="card">
          <div className="px-5 py-4 border-b"><h2 className="font-semibold">Podwładni ({podwladni.length})</h2></div>
          <ul className="divide-y divide-gray-100">
            {podwladni.map(p => (
              <li key={p.id} className="px-5 py-3 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">{p.imie} {p.nazwisko}</p>
                  <p className="text-xs text-gray-400">{p.stanowisko || '—'} · {p.komorka_nazwa || '—'}</p>
                </div>
                <div className="flex gap-3 items-center">
                  <span className="text-xs text-gray-500">{p.liczba_uprawnien} uprawnienia</span>
                  <Link to={`/pracownicy/${p.id}`} className="text-xs text-primary-600 hover:underline">Profil</Link>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      <Link to="/pracownicy" className="text-sm text-gray-500 hover:text-gray-700">← Powrót</Link>
    </div>
  );
}
