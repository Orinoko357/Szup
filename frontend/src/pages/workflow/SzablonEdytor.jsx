import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import api from '../../api/axios';
import WorkflowDndEditor from '../../components/WorkflowDndEditor';

export default function SzablonEdytor() {
  const { id } = useParams();
  const navigate = useNavigate();
  const isNew = !id || id === 'nowy';

  const [tenants, setTenants] = useState([]);
  const [pracownicy, setPracownicy] = useState([]);
  const [form, setForm] = useState({ tenant_id: '', nazwa: '', opis: '' });
  const [levels, setLevels] = useState([]);
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    Promise.all([
      api.get('/tenants'),
      api.get('/pracownicy?aktywny=true'),
    ]).then(([t, p]) => {
      setTenants(t.data);
      setPracownicy(p.data.filter(p => ['KIEROWNIK', 'IT_ADMIN'].includes(p.rola)));
    });

    if (!isNew) {
      api.get(`/workflow/szablony/${id}`).then(r => {
        setForm({ tenant_id: r.data.tenant_id || '', nazwa: r.data.nazwa, opis: r.data.opis || '' });
        setLevels(r.data.poziomy.map(l => ({ ...l, _key: String(l.id) })));
        setLoading(false);
      });
    }
  }, [id, isNew]);

  async function save() {
    setError('');
    if (!form.nazwa.trim()) { setError('Nazwa jest wymagana.'); return; }
    if (!form.tenant_id) { setError('Wybierz jednostkę.'); return; }
    if (levels.length === 0) { setError('Szablon musi mieć co najmniej jeden poziom.'); return; }

    // Validate days
    for (const l of levels) {
      if (l.eskalacja_dni < l.przypomnienie_dni) {
        setError(`Etap ${l.kolejnosc}: dni eskalacji muszą być >= dni przypomnienia.`);
        return;
      }
    }

    setSaving(true);
    try {
      let szablonId = id;

      if (isNew) {
        const { data } = await api.post('/workflow/szablony', form);
        szablonId = data.id;
      } else {
        await api.put(`/workflow/szablony/${id}`, form);
        // Delete removed levels and reorder
        const existing = levels.filter(l => l.id);
        const existingIds = existing.map(l => l.id);
        // Get current from server to find deleted
        const { data: curr } = await api.get(`/workflow/szablony/${id}/poziomy`);
        for (const cl of curr) {
          if (!existingIds.includes(cl.id)) {
            await api.delete(`/workflow/poziomy/${cl.id}`);
          }
        }
      }

      // Save levels
      for (const l of levels) {
        const payload = {
          kolejnosc: l.kolejnosc,
          nazwa: l.nazwa || null,
          zatwierdzajacy_id: l.zatwierdzajacy_id || null,
          opcjonalny: l.opcjonalny || false,
          opis_warunku_pominiecia: l.opis_warunku_pominiecia || null,
          przypomnienie_dni: l.przypomnienie_dni || 3,
          eskalacja_dni: l.eskalacja_dni || 7,
        };
        if (l.id) {
          await api.put(`/workflow/poziomy/${l.id}`, payload);
        } else {
          await api.post(`/workflow/szablony/${szablonId}/poziomy`, payload);
        }
      }

      navigate('/workflow');
    } catch (e) {
      setError(e.response?.data?.error || 'Błąd zapisu.');
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>;

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">{isNew ? 'Nowy szablon' : 'Edytuj szablon'}</h1>

      {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}

      <div className="card p-5 space-y-4">
        <h2 className="font-semibold">Informacje ogólne</h2>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="form-label">Jednostka *</label>
            <select
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
              value={form.tenant_id}
              onChange={e => setForm({ ...form, tenant_id: e.target.value })}
            >
              <option value="">-- Wybierz --</option>
              {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
            </select>
          </div>
          <div>
            <label className="form-label">Nazwa szablonu *</label>
            <input
              type="text"
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
              value={form.nazwa}
              onChange={e => setForm({ ...form, nazwa: e.target.value })}
            />
          </div>
          <div className="col-span-2">
            <label className="form-label">Opis</label>
            <input
              type="text"
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:outline-none"
              value={form.opis}
              onChange={e => setForm({ ...form, opis: e.target.value })}
            />
          </div>
        </div>
      </div>

      <div className="card p-5">
        <h2 className="font-semibold mb-4">Poziomy zatwierdzania</h2>
        <p className="text-xs text-gray-500 mb-4">Przeciągaj poziomy, aby zmienić kolejność.</p>
        <WorkflowDndEditor
          levels={levels}
          onChange={setLevels}
          pracownicy={pracownicy}
        />
      </div>

      <div className="flex gap-3">
        <button onClick={save} disabled={saving} className="btn-primary">
          {saving ? 'Zapisywanie...' : 'Zapisz szablon'}
        </button>
        <button onClick={() => navigate('/workflow')} className="btn-secondary">Anuluj</button>
      </div>
    </div>
  );
}
