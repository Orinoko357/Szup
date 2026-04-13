import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import api from '../../api/axios';

const STATUS_BADGE = { W_TOKU: 'badge-blue', 'ZAKOŃCZONY': 'badge-green', ANULOWANY: 'badge-gray' };

export default function PrzegladyLista() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [zagle, setZagle] = useState(0);

  useEffect(() => {
    Promise.all([
      api.get('/przeglady'),
      api.get('/uprawnienia?aktywne=true&wymaga_przegladu=true'),
    ]).then(([p, u]) => {
      setData(p.data);
      setZagle(u.data.length);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Przeglądy uprawnień NIS2</h1>
        <Link to="/przeglady/nowy" className="btn-primary">+ Nowy przegląd</Link>
      </div>

      {zagle > 0 && (
        <div className="bg-yellow-50 border border-yellow-300 rounded-lg p-4 text-sm text-yellow-800">
          ⚠ {zagle} uprawnień wymaga przeglądu (minął termin cykliczny NIS2).
        </div>
      )}

      <div className="card overflow-hidden">
        <table className="min-w-full divide-y divide-gray-200 text-sm">
          <thead className="bg-gray-50">
            <tr>
              {['Nr', 'Jednostka', 'Typ', 'Status', 'Data rozp.', 'Inicjujący', 'Pozostaw/Cofnij/Zmod.', 'Akcje'].map(h => (
                <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {loading ? (
              <tr><td colSpan={8} className="py-8 text-center"><div className="inline-block animate-spin h-6 w-6 border-4 border-primary-500 border-t-transparent rounded-full" /></td></tr>
            ) : data.map(p => (
              <tr key={p.id} className="hover:bg-gray-50">
                <td className="px-4 py-3 font-medium">#{p.id}</td>
                <td className="px-4 py-3 text-gray-600">{p.tenant_nazwa}</td>
                <td className="px-4 py-3">{p.typ}</td>
                <td className="px-4 py-3"><span className={STATUS_BADGE[p.status] || 'badge-gray'}>{p.status}</span></td>
                <td className="px-4 py-3 text-gray-500">{new Date(p.data_rozpoczecia).toLocaleDateString('pl-PL')}</td>
                <td className="px-4 py-3 text-gray-500">{p.inicjujacy_nazwa}</td>
                <td className="px-4 py-3 text-xs">
                  <span className="text-green-600">{p.pozostaw}</span> / <span className="text-red-600">{p.cofnij}</span> / <span className="text-yellow-600">{p.zmodyfikuj}</span>
                </td>
                <td className="px-4 py-3">
                  <Link to={`/przeglady/${p.id}`} className="text-primary-600 hover:underline text-xs">Otwórz</Link>
                </td>
              </tr>
            ))}
            {!loading && data.length === 0 && (
              <tr><td colSpan={8} className="py-8 text-center text-gray-400">Brak przeglądów.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
