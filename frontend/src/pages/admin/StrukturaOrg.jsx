import { useState, useEffect } from 'react';
import api from '../../api/axios';
import { Building2, FolderOpen, Plus, Pencil, ChevronRight, ChevronDown, Loader2 } from 'lucide-react';

const INITIAL_FORM = { nazwa: '', typ_wezla: 'WYDZIAL', nadrzedny_id: null };
const INITIAL_KOMORKA = { nazwa: '', kod: '' };

function NodeForm({ title, form, setForm, onSave, onCancel, saving, error, showTyp }) {
  return (
    <div className="mt-2 ml-4 p-3 bg-navy-50 border border-navy-200 rounded-lg space-y-2" onClick={e => e.stopPropagation()}>
      {error && <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded p-2">{error}</div>}
      <div className="font-semibold text-xs text-navy-700 uppercase tracking-wide mb-1">{title}</div>
      <input
        autoFocus
        type="text"
        className="form-input text-sm"
        placeholder="Nazwa *"
        value={form.nazwa}
        onChange={e => setForm({ ...form, nazwa: e.target.value })}
        onKeyDown={e => { if (e.key === 'Enter') onSave(); if (e.key === 'Escape') onCancel(); }}
      />
      {showTyp && (
        <select className="form-input text-sm" value={form.typ_wezla} onChange={e => setForm({ ...form, typ_wezla: e.target.value })}>
          <option value="WYDZIAL">Wydział</option>
          <option value="BIURO">Biuro</option>
          <option value="REFERAT">Referat</option>
          <option value="SEKCJA">Sekcja</option>
          <option value="STANOWISKO">Samodzielne stanowisko</option>
        </select>
      )}
      <div className="flex gap-2 pt-1">
        <button onClick={onSave} disabled={saving || !form.nazwa.trim()} className="btn btn-primary btn-sm">
          {saving ? <Loader2 size={12} className="animate-spin" /> : 'Zapisz'}
        </button>
        <button onClick={onCancel} className="btn btn-secondary btn-sm">Anuluj</button>
      </div>
    </div>
  );
}

function KomorkaForm({ form, setForm, onSave, onCancel, saving, error }) {
  return (
    <div className="mt-1 ml-6 p-3 bg-gold-50 border border-gold-300 rounded-lg space-y-2" onClick={e => e.stopPropagation()}>
      {error && <div className="text-xs text-red-600 bg-red-50 border border-red-200 rounded p-2">{error}</div>}
      <div className="font-semibold text-xs text-gold-700 uppercase tracking-wide mb-1">Nowa komórka organizacyjna</div>
      <div className="flex gap-2">
        <input
          autoFocus
          type="text"
          className="form-input text-sm flex-1"
          placeholder="Nazwa komórki *"
          value={form.nazwa}
          onChange={e => setForm({ ...form, nazwa: e.target.value })}
          onKeyDown={e => { if (e.key === 'Enter') onSave(); if (e.key === 'Escape') onCancel(); }}
        />
        <input
          type="text"
          className="form-input text-sm w-24 font-mono"
          placeholder="Kod"
          value={form.kod}
          onChange={e => setForm({ ...form, kod: e.target.value })}
        />
      </div>
      <div className="flex gap-2 pt-1">
        <button onClick={onSave} disabled={saving || !form.nazwa.trim()} className="btn btn-action btn-sm">
          {saving ? <Loader2 size={12} className="animate-spin" /> : 'Dodaj komórkę'}
        </button>
        <button onClick={onCancel} className="btn btn-secondary btn-sm">Anuluj</button>
      </div>
    </div>
  );
}

const TYP_LABEL = { WYDZIAL: 'Wydział', BIURO: 'Biuro', REFERAT: 'Referat', SEKCJA: 'Sekcja', STANOWISKO: 'Stanowisko', undefined: 'Jednostka' };
const TYP_COLOR = { WYDZIAL: 'badge-navy', BIURO: 'badge-blue', REFERAT: 'badge-purple', SEKCJA: 'badge-gray', STANOWISKO: 'badge-gray' };

function TreeNode({ node, komorki, tenantId, allNodes, depth, onRefresh }) {
  const [open, setOpen] = useState(true);
  const [mode, setMode] = useState(null); // 'addChild' | 'addKomorka' | 'edit' | null
  const [form, setForm] = useState(INITIAL_FORM);
  const [kForm, setKForm] = useState(INITIAL_KOMORKA);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const myKomorki = komorki.filter(k => k.struktura_org_id === node.id);
  const hasChildren = node.children?.length > 0 || myKomorki.length > 0;

  function openMode(m) {
    setError('');
    if (m === 'addChild') setForm({ ...INITIAL_FORM, nadrzedny_id: node.id });
    if (m === 'edit') setForm({ nazwa: node.nazwa, typ_wezla: node.typ_wezla || 'WYDZIAL', nadrzedny_id: node.nadrzedny_id });
    if (m === 'addKomorka') setKForm(INITIAL_KOMORKA);
    setMode(m);
    setOpen(true);
  }

  async function saveNode() {
    setSaving(true); setError('');
    try {
      if (mode === 'addChild') {
        await api.post('/struktura-org', { ...form, tenant_id: parseInt(tenantId) });
      } else if (mode === 'edit') {
        await api.put(`/struktura-org/${node.id}`, { ...form, tenant_id: parseInt(tenantId) });
      }
      setMode(null); onRefresh();
    } catch (e) { setError(e.response?.data?.detail || e.response?.data?.error || 'Błąd zapisu.'); }
    finally { setSaving(false); }
  }

  async function saveKomorka() {
    setSaving(true); setError('');
    try {
      await api.post('/komorki', { ...kForm, struktura_org_id: node.id, tenant_id: parseInt(tenantId) });
      setMode(null); onRefresh();
    } catch (e) { setError(e.response?.data?.detail || e.response?.data?.error || 'Błąd zapisu.'); }
    finally { setSaving(false); }
  }

  return (
    <div className={depth > 0 ? 'ml-5 border-l-2 border-gray-100 pl-3' : ''}>
      {/* Node row */}
      <div className="group flex items-center gap-2 py-1.5 px-2 rounded-lg hover:bg-gray-50 cursor-pointer" onClick={() => hasChildren && setOpen(o => !o)}>
        {/* Chevron */}
        <span className="text-gray-300 w-4 flex-shrink-0">
          {hasChildren ? (open ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : null}
        </span>

        {/* Icon */}
        <Building2 size={15} className="text-navy-600 flex-shrink-0" />

        {/* Name */}
        <span className="font-semibold text-sm text-gray-800">{node.nazwa}</span>

        {/* Type badge */}
        <span className={`badge ${TYP_COLOR[node.typ_wezla] || 'badge-gray'} text-[10px] hidden sm:inline-flex`}>
          {TYP_LABEL[node.typ_wezla] || node.typ_wezla}
        </span>

        {/* Actions — visible on hover */}
        <div className="ml-auto flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity" onClick={e => e.stopPropagation()}>
          <button
            onClick={() => openMode(mode === 'addChild' ? null : 'addChild')}
            className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-navy-50 text-navy-700 hover:bg-navy-100 font-semibold"
            title="Dodaj podjednostkę"
          >
            <Plus size={11} /> Podjednostka
          </button>
          <button
            onClick={() => openMode(mode === 'addKomorka' ? null : 'addKomorka')}
            className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-gold-50 text-gold-700 hover:bg-gold-100 font-semibold"
            title="Dodaj komórkę organizacyjną"
          >
            <Plus size={11} /> Komórka
          </button>
          <button
            onClick={() => openMode(mode === 'edit' ? null : 'edit')}
            className="p-1 rounded text-gray-400 hover:text-gray-600 hover:bg-gray-100"
            title="Edytuj"
          >
            <Pencil size={12} />
          </button>
        </div>
      </div>

      {/* Inline forms */}
      {mode === 'edit' && (
        <NodeForm title="Edytuj jednostkę" form={form} setForm={setForm} onSave={saveNode} onCancel={() => setMode(null)} saving={saving} error={error} showTyp />
      )}
      {mode === 'addChild' && (
        <NodeForm title="Nowa podjednostka" form={form} setForm={setForm} onSave={saveNode} onCancel={() => setMode(null)} saving={saving} error={error} showTyp />
      )}
      {mode === 'addKomorka' && (
        <KomorkaForm form={kForm} setForm={setKForm} onSave={saveKomorka} onCancel={() => setMode(null)} saving={saving} error={error} />
      )}

      {/* Children */}
      {open && (
        <div>
          {/* Sub-nodes */}
          {node.children?.map(child => (
            <TreeNode key={child.id} node={child} komorki={komorki} tenantId={tenantId} allNodes={allNodes} depth={depth + 1} onRefresh={onRefresh} />
          ))}

          {/* Komórki of this node */}
          {myKomorki.map(k => (
            <KomorkaRow key={k.id} komorka={k} tenantId={tenantId} onRefresh={onRefresh} />
          ))}
        </div>
      )}
    </div>
  );
}

function KomorkaRow({ komorka, tenantId, onRefresh }) {
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ nazwa: komorka.nazwa, kod: komorka.kod || '' });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  async function save() {
    setSaving(true); setError('');
    try {
      await api.put(`/komorki/${komorka.id}`, { ...form, tenant_id: parseInt(tenantId), struktura_org_id: komorka.struktura_org_id });
      setEditing(false); onRefresh();
    } catch (e) { setError(e.response?.data?.detail || 'Błąd.'); }
    finally { setSaving(false); }
  }

  if (editing) {
    return (
      <div className="ml-8 mt-1">
        <div className="p-3 bg-gold-50 border border-gold-300 rounded-lg space-y-2">
          {error && <div className="text-xs text-red-600">{error}</div>}
          <div className="flex gap-2">
            <input autoFocus type="text" className="form-input text-sm flex-1" value={form.nazwa} onChange={e => setForm({ ...form, nazwa: e.target.value })} />
            <input type="text" className="form-input text-sm w-24 font-mono" placeholder="Kod" value={form.kod} onChange={e => setForm({ ...form, kod: e.target.value })} />
          </div>
          <div className="flex gap-2">
            <button onClick={save} disabled={saving} className="btn btn-action btn-sm">{saving ? '...' : 'Zapisz'}</button>
            <button onClick={() => setEditing(false)} className="btn btn-secondary btn-sm">Anuluj</button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="group ml-8 flex items-center gap-2 py-1 px-2 rounded hover:bg-gold-50">
      <FolderOpen size={13} className="text-gold-500 flex-shrink-0" />
      <span className="text-sm text-gray-700">{komorka.nazwa}</span>
      {komorka.kod && <span className="text-[11px] text-gray-400 font-mono">{komorka.kod}</span>}
      <button onClick={() => setEditing(true)} className="ml-auto opacity-0 group-hover:opacity-100 p-1 rounded text-gray-400 hover:text-gray-600">
        <Pencil size={11} />
      </button>
    </div>
  );
}

export default function AdminStrukturaOrg() {
  const [tenants, setTenants] = useState([]);
  const [tenantId, setTenantId] = useState('');
  const [struktura, setStruktura] = useState([]);
  const [komorki, setKomorki] = useState([]);
  const [loading, setLoading] = useState(false);
  const [addRoot, setAddRoot] = useState(false);
  const [rootForm, setRootForm] = useState(INITIAL_FORM);
  const [rootSaving, setRootSaving] = useState(false);
  const [rootError, setRootError] = useState('');

  useEffect(() => {
    api.get('/tenants').then(r => {
      setTenants(r.data);
      if (r.data.length === 1) setTenantId(String(r.data[0].id));
    });
  }, []);

  const load = async () => {
    if (!tenantId) return;
    setLoading(true);
    const [s, k] = await Promise.all([
      api.get(`/struktura-org?tenant_id=${tenantId}`).then(r => r.data).catch(() => []),
      api.get(`/komorki?tenant_id=${tenantId}`).then(r => r.data).catch(() => []),
    ]);
    setStruktura(s);
    setKomorki(k);
    setLoading(false);
  };

  useEffect(() => { if (tenantId) load(); else { setStruktura([]); setKomorki([]); } }, [tenantId]);

  function buildTree(nodes, parentId = null) {
    return nodes
      .filter(n => (n.nadrzedny_id ?? null) === parentId)
      .map(n => ({ ...n, children: buildTree(nodes, n.id) }));
  }

  async function saveRoot() {
    setRootSaving(true); setRootError('');
    try {
      await api.post('/struktura-org', { ...rootForm, tenant_id: parseInt(tenantId), nadrzedny_id: null });
      setAddRoot(false); setRootForm(INITIAL_FORM); load();
    } catch (e) { setRootError(e.response?.data?.detail || e.response?.data?.error || 'Błąd.'); }
    finally { setRootSaving(false); }
  }

  const tree = buildTree(struktura);
  const selectedTenant = tenants.find(t => String(t.id) === String(tenantId));

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="page-title">Struktura organizacyjna</h1>
      </div>

      {/* Tenant selector */}
      {tenants.length > 1 && (
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium text-gray-600">Jednostka:</label>
          <select
            className="form-input text-sm w-64"
            value={tenantId}
            onChange={e => setTenantId(e.target.value)}
          >
            <option value="">-- Wybierz jednostkę --</option>
            {tenants.map(t => <option key={t.id} value={t.id}>{t.nazwa}</option>)}
          </select>
        </div>
      )}

      {!tenantId && (
        <div className="card p-12 text-center text-gray-400">
          <Building2 size={40} className="mx-auto mb-3 text-gray-300" />
          <p className="text-sm">Wybierz jednostkę aby zobaczyć strukturę organizacyjną</p>
        </div>
      )}

      {tenantId && (
        <div className="card p-4">
          {/* Header */}
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="section-title">Drzewo organizacyjne</div>
              {selectedTenant && <div className="text-xs text-gray-500 mt-1 ml-4">{selectedTenant.nazwa}</div>}
            </div>
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <span className="flex items-center gap-1"><Building2 size={11} className="text-navy-600" /> Jednostki org.</span>
              <span className="flex items-center gap-1 ml-3"><FolderOpen size={11} className="text-gold-500" /> Komórki</span>
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12 text-gray-400">
              <Loader2 size={20} className="animate-spin mr-2" /> Ładowanie...
            </div>
          ) : (
            <div className="space-y-0.5">
              {tree.map(node => (
                <TreeNode
                  key={node.id}
                  node={node}
                  komorki={komorki}
                  tenantId={tenantId}
                  allNodes={struktura}
                  depth={0}
                  onRefresh={load}
                />
              ))}

              {/* Add root node */}
              {addRoot ? (
                <div className="mt-3">
                  <NodeForm
                    title="Nowa jednostka główna"
                    form={rootForm}
                    setForm={setRootForm}
                    onSave={saveRoot}
                    onCancel={() => { setAddRoot(false); setRootError(''); }}
                    saving={rootSaving}
                    error={rootError}
                    showTyp
                  />
                </div>
              ) : (
                <button
                  onClick={() => setAddRoot(true)}
                  className="mt-3 flex items-center gap-1.5 text-sm text-navy-600 hover:text-navy-800 font-medium px-2 py-1.5 rounded hover:bg-navy-50 transition-colors"
                >
                  <Plus size={15} /> Dodaj jednostkę główną
                </button>
              )}

              {tree.length === 0 && !addRoot && (
                <div className="text-center py-10 text-gray-400 text-sm">
                  Brak struktury. Kliknij „Dodaj jednostkę główną" aby rozpocząć.
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Legend */}
      {tenantId && (
        <div className="text-xs text-gray-400 flex gap-4">
          <span>💡 Najedź na element aby zobaczyć akcje</span>
          <span>• Enter — zapisz szybko</span>
          <span>• Escape — anuluj</span>
        </div>
      )}
    </div>
  );
}
