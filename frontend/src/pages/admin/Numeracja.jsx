import { useState, useEffect } from 'react';
import api from '../../api/axios';

export default function AdminNumeracja() {
  const [config, setConfig] = useState(null);
  const [form, setForm] = useState({ format_szablonu: '', prefix: '', seq_length: 4, reset: 'ROK' });
  const [preview, setPreview] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    api.get('/konfiguracja/numeracja').then(r => {
      const d = r.data;
      setConfig(d);
      setForm({ format_szablonu: d.format_szablonu, prefix: d.prefix || '', seq_length: d.seq_length || 4, reset: d.reset || 'ROK' });
    });
  }, []);

  useEffect(() => {
    if (!form.format_szablonu) return;
    const t = setTimeout(() => {
      api.get(`/konfiguracja/numeracja/podglad?format=${encodeURIComponent(form.format_szablonu)}&prefix=${form.prefix}&seq_length=${form.seq_length}`)
        .then(r => setPreview(r.data.preview || ''))
        .catch(() => setPreview(''));
    }, 500);
    return () => clearTimeout(t);
  }, [form.format_szablonu, form.prefix, form.seq_length]);

  async function submit(e) {
    e.preventDefault(); setSaving(true); setError(''); setSuccess('');
    try {
      await api.put('/konfiguracja/numeracja', form);
      setSuccess('Konfiguracja zapisana.');
    } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
    finally { setSaving(false); }
  }

  if (!config) return <div className="flex justify-center py-20"><div className="animate-spin h-8 w-8 border-4 border-primary-500 border-t-transparent rounded-full" /></div>;

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-2xl font-bold">Konfiguracja numeracji wniosków</h1>

      <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 text-sm text-blue-800 space-y-1">
        <div className="font-medium">Tokeny dostępne w szablonie:</div>
        <ul className="list-disc list-inside space-y-0.5 text-blue-700">
          <li><code className="font-mono">{'{PREFIX}'}</code> — wartość pola Prefix poniżej</li>
          <li><code className="font-mono">{'{SEQ}'}</code> lub <code className="font-mono">{'{SEQ:N}'}</code> — numer sekwencyjny (N = długość z zerami)</li>
          <li><code className="font-mono">{'{YEAR}'}</code> — rok (4 cyfry)</li>
          <li><code className="font-mono">{'{MONTH}'}</code> — miesiąc (2 cyfry)</li>
        </ul>
        <div className="mt-1">Przykład: <code className="font-mono">{'WNI/{YEAR}/{SEQ:4}'}</code> → <strong>WNI/2025/0001</strong></div>
      </div>

      {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">{error}</div>}
      {success && <div className="p-3 bg-green-50 border border-green-200 rounded text-sm text-green-700">{success}</div>}

      <form onSubmit={submit} className="card p-5 space-y-4">
        <div>
          <label className="form-label">Szablon numeracji *</label>
          <input required type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={form.format_szablonu} onChange={e => setForm({ ...form, format_szablonu: e.target.value })} placeholder="np. WNI/{YEAR}/{SEQ:4}" />
          {preview && (
            <div className="mt-1 text-sm text-gray-500">
              Podgląd: <span className="font-mono font-medium text-gray-800">{preview}</span>
            </div>
          )}
        </div>

        <div>
          <label className="form-label">Prefix</label>
          <input type="text" className="w-full border border-gray-300 rounded px-3 py-2 text-sm font-mono" value={form.prefix} onChange={e => setForm({ ...form, prefix: e.target.value })} placeholder="np. WNI" />
        </div>

        <div>
          <label className="form-label">Długość numeru sekwencyjnego (dopełnienie zerami)</label>
          <input type="number" min={1} max={10} className="w-32 border border-gray-300 rounded px-3 py-2 text-sm" value={form.seq_length} onChange={e => setForm({ ...form, seq_length: Number(e.target.value) })} />
        </div>

        <div>
          <label className="form-label">Reset licznika</label>
          <select className="w-full border border-gray-300 rounded px-3 py-2 text-sm" value={form.reset} onChange={e => setForm({ ...form, reset: e.target.value })}>
            <option value="ROK">Co rok (1 stycznia)</option>
            <option value="MIESIAC">Co miesiąc (1. każdego miesiąca)</option>
            <option value="NIGDY">Nigdy (licznik ciągły)</option>
          </select>
        </div>

        <div className="pt-2 border-t">
          <div className="text-sm text-gray-500 mb-3">
            <span className="font-medium">Aktualny licznik:</span> {config.biezacy_numer || 0} &nbsp;·&nbsp;
            <span className="font-medium">Ostatni reset:</span> {config.data_ostatniego_resetu ? new Date(config.data_ostatniego_resetu).toLocaleDateString('pl-PL') : '—'}
          </div>
          <button type="submit" disabled={saving} className="btn-primary">{saving ? 'Zapisywanie...' : 'Zapisz konfigurację'}</button>
        </div>
      </form>

      <div className="card p-5 space-y-3">
        <h2 className="font-semibold">Ręczny reset licznika</h2>
        <p className="text-sm text-gray-600">Resetuje bieżący licznik do 0. Następny wniosek otrzyma numer 1. Użyj ostrożnie — nie można cofnąć.</p>
        <button onClick={async () => {
          if (!confirm('Zresetować licznik do 0? Operacji nie można cofnąć.')) return;
          try {
            await api.post('/konfiguracja/numeracja/reset');
            setSuccess('Licznik zresetowany.');
            api.get('/konfiguracja/numeracja').then(r => setConfig(r.data));
          } catch (e) { setError(e.response?.data?.error || 'Błąd.'); }
        }} className="btn-danger btn-sm">Resetuj licznik teraz</button>
      </div>
    </div>
  );
}
