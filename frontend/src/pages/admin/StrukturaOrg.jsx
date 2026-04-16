import { useState, useEffect, useCallback } from 'react';
import api from '../../api/axios';
import {
  ChevronRight, ChevronDown, Plus, Pencil, Trash2,
  Users, User, Building2, X, Check, Loader2,
} from 'lucide-react';

const TYP_OPTS = [
  { value: 'URZAD',      label: 'Urząd / Instytucja' },
  { value: 'WYDZIAL',    label: 'Wydział' },
  { value: 'REFERAT',    label: 'Referat' },
  { value: 'BIURO',      label: 'Biuro' },
  { value: 'ODDZIAL',    label: 'Oddział' },
  { value: 'SEKCJA',     label: 'Sekcja' },
  { value: 'STANOWISKO', label: 'Stanowisko' },
];

const TYP_COLOR = {
  URZAD:      { bg: '#1c355e', color: '#fff' },
  WYDZIAL:    { bg: '#2563eb', color: '#fff' },
  REFERAT:    { bg: '#0891b2', color: '#fff' },
  BIURO:      { bg: '#7c3aed', color: '#fff' },
  ODDZIAL:    { bg: '#059669', color: '#fff' },
  SEKCJA:     { bg: '#d97706', color: '#fff' },
  STANOWISKO: { bg: '#c5a065', color: '#1c355e' },
};

function typLabel(typ) {
  return TYP_OPTS.find(o => o.value === typ)?.label || typ;
}

function buildTree(flat) {
  const map = {};
  flat.forEach(n => { map[n.id] = { ...n, children: [] }; });
  const roots = [];
  flat.forEach(n => {
    if (n.nadrzedny_id && map[n.nadrzedny_id]) {
      map[n.nadrzedny_id].children.push(map[n.id]);
    } else {
      roots.push(map[n.id]);
    }
  });
  const sort = arr => {
    arr.sort((a, b) => (a.kolejnosc ?? 0) - (b.kolejnosc ?? 0) || a.nazwa.localeCompare(b.nazwa));
    arr.forEach(n => sort(n.children));
  };
  sort(roots);
  return roots;
}

/* ─── Inline form ─────────────────────────────────────────────────────────── */
function NodeForm({ initial, tenantId, parentId, pracownicy, onSave, onCancel }) {
  const [form, setForm] = useState({
    nazwa: initial?.nazwa || '',
    typ: initial?.typ || 'WYDZIAL',
    kierownik_id: initial?.kierownik_id || '',
    kolejnosc: initial?.kolejnosc ?? 0,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function handleSave() {
    if (!form.nazwa.trim()) { setError('Nazwa jest wymagana.'); return; }
    setSaving(true);
    try {
      const payload = {
        tenant_id: tenantId,
        nadrzedny_id: parentId || null,
        nazwa: form.nazwa.trim(),
        typ: form.typ,
        kierownik_id: form.kierownik_id ? parseInt(form.kierownik_id) : null,
        kolejnosc: parseInt(form.kolejnosc) || 0,
      };
      if (initial?.id) {
        const { data } = await api.put(`/jednostki-org/${initial.id}`, payload);
        onSave(data);
      } else {
        const { data } = await api.post('/jednostki-org', payload);
        onSave(data);
      }
    } catch (e) {
      setError(e.response?.data?.detail || 'Błąd zapisu.');
    } finally {
      setSaving(false);
    }
  }

  function handleKey(e) {
    if (e.key === 'Enter') handleSave();
    if (e.key === 'Escape') onCancel();
  }

  const s = {
    box: { background: '#f8fafc', border: '1px solid #c5a065', borderRadius: 8,
           padding: '12px 14px', margin: '6px 0', display: 'flex', flexDirection: 'column', gap: 10 },
    row: { display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'flex-end' },
    label: { fontSize: 10, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em',
             color: '#6b7280', display: 'block', marginBottom: 3 },
    input: { border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px', fontSize: 13,
             outline: 'none', width: '100%', background: '#fff' },
    select: { border: '1px solid #d1d5db', borderRadius: 6, padding: '6px 10px',
              fontSize: 13, background: '#fff' },
    error: { fontSize: 12, color: '#dc2626' },
  };

  return (
    <div style={s.box} onKeyDown={handleKey}>
      {error && <div style={s.error}>{error}</div>}
      <div style={s.row}>
        <div style={{ flex: '2 1 180px' }}>
          <label style={s.label}>Nazwa</label>
          <input style={s.input} autoFocus value={form.nazwa}
            onChange={e => setForm(f => ({ ...f, nazwa: e.target.value }))}
            placeholder="np. Referat Edukacji" />
        </div>
        <div style={{ flex: '1 1 140px' }}>
          <label style={s.label}>Typ</label>
          <select style={s.select} value={form.typ}
            onChange={e => setForm(f => ({ ...f, typ: e.target.value }))}>
            {TYP_OPTS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div style={{ flex: '1 1 160px' }}>
          <label style={s.label}>Kierownik</label>
          <select style={s.select} value={form.kierownik_id}
            onChange={e => setForm(f => ({ ...f, kierownik_id: e.target.value }))}>
            <option value="">— brak —</option>
            {pracownicy.map(p => (
              <option key={p.id} value={p.id}>{p.nazwisko} {p.imie}</option>
            ))}
          </select>
        </div>
        <div style={{ flex: '0 1 70px' }}>
          <label style={s.label}>Kolejność</label>
          <input style={{ ...s.input, width: 60 }} type="number" value={form.kolejnosc}
            onChange={e => setForm(f => ({ ...f, kolejnosc: e.target.value }))} />
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <button onClick={handleSave} disabled={saving}
          style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '6px 14px',
                   background: '#1c355e', color: '#fff', border: 'none', borderRadius: 6,
                   fontSize: 13, cursor: 'pointer' }}>
          {saving ? <Loader2 size={13} className="spin" /> : <Check size={13} />}
          {initial?.id ? 'Zapisz' : 'Dodaj'}
        </button>
        <button onClick={onCancel}
          style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '6px 12px',
                   background: '#f3f4f6', border: '1px solid #d1d5db', borderRadius: 6,
                   fontSize: 13, cursor: 'pointer' }}>
          <X size={13} /> Anuluj
        </button>
      </div>
    </div>
  );
}

/* ─── Single tree node ────────────────────────────────────────────────────── */
function TreeNode({ node, tenantId, pracownicy, depth, onRefresh }) {
  const [open, setOpen] = useState(depth < 2);
  const [hover, setHover] = useState(false);
  const [mode, setMode] = useState(null); // 'add-child' | 'edit'
  const [employees, setEmployees] = useState(null);
  const [loadingEmp, setLoadingEmp] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const hasChildren = node.children.length > 0;
  const tc = TYP_COLOR[node.typ] || TYP_COLOR.WYDZIAL;

  async function toggleEmployees() {
    if (employees !== null) { setEmployees(null); return; }
    setLoadingEmp(true);
    try {
      const { data } = await api.get(`/jednostki-org/${node.id}/pracownicy`);
      setEmployees(data);
    } catch { setEmployees([]); }
    finally { setLoadingEmp(false); }
  }

  async function handleDelete() {
    if (!confirm(`Dezaktywować jednostkę "${node.nazwa}"?`)) return;
    setDeleting(true);
    try {
      await api.delete(`/jednostki-org/${node.id}`);
      onRefresh();
    } catch (e) {
      alert(e.response?.data?.detail || 'Błąd usuwania.');
    } finally { setDeleting(false); }
  }

  const indent = depth * 24;

  return (
    <div>
      {/* ── Node row ── */}
      <div
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '7px 12px',
                 borderRadius: 7, background: hover ? '#f8fafc' : 'transparent',
                 marginLeft: indent, transition: 'background 0.15s' }}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
      >
        <button onClick={() => setOpen(o => !o)}
          style={{ background: 'none', border: 'none',
                   cursor: hasChildren ? 'pointer' : 'default',
                   padding: 2, color: hasChildren ? '#6b7280' : 'transparent', flexShrink: 0 }}>
          {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        </button>

        <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 4,
                       background: tc.bg, color: tc.color, flexShrink: 0, letterSpacing: '0.04em' }}>
          {typLabel(node.typ)}
        </span>

        <span style={{ fontSize: 14, fontWeight: 600, color: '#111827', flex: 1 }}>{node.nazwa}</span>

        {(node.kier_imie || node.kier_nazwisko) && (
          <span style={{ fontSize: 12, color: '#6b7280', fontStyle: 'italic' }}>
            {node.kier_nazwisko} {node.kier_imie}
          </span>
        )}

        {node.liczba_pracownikow > 0 && (
          <button onClick={toggleEmployees}
            style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11,
                     color: '#6b7280', background: employees !== null ? '#e0e7ff' : '#f3f4f6',
                     border: 'none', borderRadius: 5, padding: '2px 8px', cursor: 'pointer' }}>
            <Users size={12} /> {node.liczba_pracownikow}
          </button>
        )}

        {hover && (
          <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
            <button onClick={() => setMode('add-child')}
              style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, padding: '3px 9px',
                       background: '#1c355e', color: '#fff', border: 'none', borderRadius: 5, cursor: 'pointer' }}>
              <Plus size={11} /> Podjednostka
            </button>
            <button onClick={() => setMode(mode === 'edit' ? null : 'edit')}
              style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, padding: '3px 8px',
                       background: '#f3f4f6', border: '1px solid #d1d5db', borderRadius: 5, cursor: 'pointer' }}>
              <Pencil size={11} />
            </button>
            <button onClick={handleDelete} disabled={deleting}
              style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 11, padding: '3px 8px',
                       background: '#fef2f2', border: '1px solid #fca5a5', color: '#dc2626',
                       borderRadius: 5, cursor: 'pointer' }}>
              <Trash2 size={11} />
            </button>
          </div>
        )}
      </div>

      {/* Edit form */}
      {mode === 'edit' && (
        <div style={{ marginLeft: indent + 24 }}>
          <NodeForm initial={node} tenantId={tenantId} parentId={node.nadrzedny_id}
            pracownicy={pracownicy}
            onSave={() => { setMode(null); onRefresh(); }}
            onCancel={() => setMode(null)} />
        </div>
      )}

      {/* Employees */}
      {employees !== null && (
        <div style={{ marginLeft: indent + 48, marginBottom: 4 }}>
          {loadingEmp && <span style={{ fontSize: 12, color: '#9ca3af' }}>Ładowanie...</span>}
          {employees.map(emp => (
            <div key={emp.id} style={{ display: 'flex', alignItems: 'center', gap: 6,
                                       padding: '3px 8px', fontSize: 12, color: '#374151' }}>
              <User size={12} color={emp.jest_kierownikiem ? '#c5a065' : '#9ca3af'} />
              <span>{emp.nazwisko} {emp.imie}</span>
              {emp.stanowisko && <span style={{ color: '#9ca3af' }}>— {emp.stanowisko}</span>}
              {emp.jest_kierownikiem && (
                <span style={{ fontSize: 10, background: '#fef3c7', color: '#92400e',
                               padding: '1px 6px', borderRadius: 4, fontWeight: 600 }}>kierownik</span>
              )}
            </div>
          ))}
          {employees.length === 0 && !loadingEmp && (
            <span style={{ fontSize: 12, color: '#9ca3af', paddingLeft: 8 }}>Brak pracowników</span>
          )}
        </div>
      )}

      {/* Add child form */}
      {mode === 'add-child' && (
        <div style={{ marginLeft: indent + 24 }}>
          <NodeForm tenantId={tenantId} parentId={node.id} pracownicy={pracownicy}
            onSave={() => { setMode(null); setOpen(true); onRefresh(); }}
            onCancel={() => setMode(null)} />
        </div>
      )}

      {/* Children */}
      {open && node.children.map(child => (
        <TreeNode key={child.id} node={child} tenantId={tenantId}
          pracownicy={pracownicy} depth={depth + 1} onRefresh={onRefresh} />
      ))}
    </div>
  );
}

/* ─── Main page ───────────────────────────────────────────────────────────── */
export default function StrukturaOrg() {
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [units, setUnits] = useState([]);
  const [pracownicy, setPracownicy] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showAddRoot, setShowAddRoot] = useState(false);

  useEffect(() => {
    api.get('/tenants').then(r => {
      setTenants(r.data);
      if (r.data.length === 1) setTenantId(String(r.data[0].id));
    }).catch(() => {});
  }, []);

  const loadUnits = useCallback(async () => {
    if (!tenantId) return;
    setLoading(true);
    try {
      const [uRes, pRes] = await Promise.all([
        api.get(`/jednostki-org?tenant_id=${tenantId}`),
        api.get(`/pracownicy?tenant_id=${tenantId}&aktywny=true`),
      ]);
      setUnits(uRes.data);
      setPracownicy(pRes.data);
    } catch { setUnits([]); }
    finally { setLoading(false); }
  }, [tenantId]);

  useEffect(() => { loadUnits(); }, [loadUnits]);

  const tree = buildTree(units);

  return (
    <div className="page-content">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div className="section-title">Struktura Organizacyjna</div>
        {tenantId && (
          <button onClick={() => setShowAddRoot(r => !r)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px',
                     background: '#1c355e', color: '#fff', border: 'none', borderRadius: 7,
                     fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>
            <Plus size={15} /> Dodaj jednostkę główną
          </button>
        )}
      </div>

      {tenants.length > 1 && (
        <div style={{ marginBottom: 20, display: 'flex', alignItems: 'center', gap: 10 }}>
          <label style={{ fontSize: 11, fontWeight: 700, textTransform: 'uppercase',
                          letterSpacing: '0.06em', color: '#6b7280' }}>Organizacja</label>
          <select className="form-input" style={{ width: 'auto', minWidth: 200 }}
            value={tenantId} onChange={e => setTenantId(e.target.value)}>
            <option value="">— wybierz —</option>
            {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
          </select>
        </div>
      )}

      {showAddRoot && tenantId && (
        <NodeForm tenantId={parseInt(tenantId)} parentId={null} pracownicy={pracownicy}
          onSave={() => { setShowAddRoot(false); loadUnits(); }}
          onCancel={() => setShowAddRoot(false)} />
      )}

      <div style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: 10, padding: '12px 8px' }}>
        {loading && (
          <div style={{ display: 'flex', justifyContent: 'center', padding: 32 }}>
            <Loader2 size={24} style={{ color: '#1c355e', animation: 'spin 1s linear infinite' }} />
          </div>
        )}
        {!loading && !tenantId && (
          <div style={{ textAlign: 'center', padding: 40, color: '#9ca3af', fontSize: 14 }}>
            <Building2 size={32} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
            Wybierz organizację
          </div>
        )}
        {!loading && tenantId && tree.length === 0 && (
          <div style={{ textAlign: 'center', padding: 40, color: '#9ca3af', fontSize: 14 }}>
            <Building2 size={32} style={{ margin: '0 auto 12px', opacity: 0.4 }} />
            Brak jednostek — kliknij „Dodaj jednostkę główną"
          </div>
        )}
        {!loading && tree.map(node => (
          <TreeNode key={node.id} node={node} tenantId={parseInt(tenantId)}
            pracownicy={pracownicy} depth={0} onRefresh={loadUnits} />
        ))}
      </div>

      <style>{`
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .spin { animation: spin 1s linear infinite; }
      `}</style>
    </div>
  );
}
