import { useEffect, useState } from 'react'
import {
  ListFilter, Plus, Save, X, Trash2, RefreshCw, Edit2,
  UserPlus, Pencil, UserMinus, User as UserIcon, Package,
} from 'lucide-react'
import {
  listRequestTypes, createRequestType, updateRequestType, deleteRequestType,
  listWorkflowTemplates,
} from '../api'

const ICON_MAP = {
  'user-plus':  UserPlus,
  'pencil':     Pencil,
  'user-minus': UserMinus,
  'user':       UserIcon,
  'package':    Package,
}

export default function RequestTypes() {
  const [items, setItems] = useState([])
  const [templates, setTemplates] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [editing, setEditing] = useState(null)   // id lub 'new' lub null

  async function load() {
    setLoading(true); setErr(null)
    try {
      const [r, t] = await Promise.all([
        listRequestTypes({}),
        listWorkflowTemplates({ is_active: true }),
      ])
      setItems(r.data); setTemplates(t.data)
    } catch (ex) { setErr(ex.response?.data?.detail || 'Błąd ładowania') }
    finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Typy wniosków</div>
          <div className="page-header__sub">
            Każdy typ wniosku ma przypisany szablon obiegu. HR/kierownik wybiera typ przy tworzeniu wniosku.
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
          <button className="btn btn--action btn--sm" onClick={() => setEditing('new')}>
            <Plus size={14} /> Nowy typ
          </button>
        </div>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      {editing === 'new' && (
        <TypeForm templates={templates}
                  onCancel={() => setEditing(null)}
                  onSaved={() => { setEditing(null); load() }} />
      )}

      <div className="card" style={{ padding: 0 }}>
        <table className="table">
          <thead><tr>
            <th></th><th>Nazwa</th><th>Kod</th><th>Szablon obiegu</th>
            <th>Wnioski</th><th>Stan</th><th></th>
          </tr></thead>
          <tbody>
            {loading && <tr><td colSpan={7} style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</td></tr>}
            {!loading && items.length === 0 && editing !== 'new' && (
              <tr><td colSpan={7} style={{ color: 'var(--color-text-muted)', padding: 16 }}>
                <ListFilter size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
                Brak typów wniosków. Dodaj pierwszy.
              </td></tr>
            )}
            {items.map(t => editing === t.id ? (
              <tr key={t.id}><td colSpan={7} style={{ padding: 0 }}>
                <TypeForm type={t} templates={templates}
                          onCancel={() => setEditing(null)}
                          onSaved={() => { setEditing(null); load() }} />
              </td></tr>
            ) : (
              <TypeRow key={t.id} t={t}
                       onEdit={() => setEditing(t.id)}
                       onReload={load} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function TypeRow({ t, onEdit, onReload }) {
  const Icon = ICON_MAP[t.icon] || Package
  async function del() {
    if (!confirm(`Usunąć typ wniosku "${t.name}"?`)) return
    try { await deleteRequestType(t.id); onReload() }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd') }
  }
  return (
    <tr>
      <td><Icon size={16} style={{ color: 'var(--color-navy)' }} /></td>
      <td>
        <strong>{t.name}</strong>
        {t.description && (
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{t.description}</div>
        )}
      </td>
      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11 }}>{t.code || '—'}</td>
      <td style={{ fontSize: 12 }}>
        {t.workflow_template_name || '—'}
        {t.workflow_template_version && (
          <span style={{ fontSize: 10, color: 'var(--color-text-muted)', marginLeft: 4 }}>
            v{t.workflow_template_version}
          </span>
        )}
      </td>
      <td style={{ fontSize: 12 }}>{t.used_by_requests_count}</td>
      <td>
        {t.is_active
          ? <span className="badge badge--success" style={{ fontSize: 10 }}>aktywny</span>
          : <span className="badge badge--neutral" style={{ fontSize: 10 }}>nieaktywny</span>}
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
        <button className="btn btn--ghost btn--sm" onClick={onEdit}><Edit2 size={12} /></button>
        <button className="btn btn--ghost btn--sm" onClick={del}><Trash2 size={12} /></button>
      </td>
    </tr>
  )
}

function TypeForm({ type, templates, onCancel, onSaved }) {
  const isEdit = !!type
  const [form, setForm] = useState(() => ({
    name: type?.name || '',
    code: type?.code || '',
    description: type?.description || '',
    workflow_template_id: type?.workflow_template_id || (templates[0]?.id || ''),
    is_active: type?.is_active ?? true,
    icon: type?.icon || 'user-plus',
  }))
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState(null)
  function setF(k, v) { setForm(f => ({ ...f, [k]: v })) }

  async function save() {
    setErr(null); setSaving(true)
    try {
      if (!form.name.trim()) throw new Error('Nazwa wymagana')
      if (!form.workflow_template_id) throw new Error('Wybierz szablon obiegu')
      const payload = {
        ...form,
        workflow_template_id: Number(form.workflow_template_id),
        code: form.code.trim() || null,
      }
      if (isEdit) await updateRequestType(type.id, payload)
      else await createRequestType(payload)
      onSaved()
    } catch (ex) { setErr(ex.response?.data?.detail || ex.message || 'Błąd zapisu') }
    finally { setSaving(false) }
  }

  return (
    <div className="card" style={{ padding: 12, background: 'var(--bg-secondary)', margin: isEdit ? 0 : '0 0 10px 0' }}>
      <strong>{isEdit ? 'Edycja typu wniosku' : 'Nowy typ wniosku'}</strong>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8, marginTop: 8 }}>
        <Field label="Nazwa *">
          <input className="input input--sm" value={form.name} onChange={e => setF('name', e.target.value)} />
        </Field>
        <Field label="Kod (skrót)">
          <input className="input input--sm" value={form.code} onChange={e => setF('code', e.target.value)} placeholder="np. NEW_EMP" />
        </Field>
        <Field label="Szablon obiegu *">
          <select className="input input--sm" value={form.workflow_template_id} onChange={e => setF('workflow_template_id', e.target.value)}>
            <option value="">— wybierz —</option>
            {templates.map(t => <option key={t.id} value={t.id}>{t.name} (v{t.version})</option>)}
          </select>
        </Field>
        <Field label="Ikona">
          <select className="input input--sm" value={form.icon} onChange={e => setF('icon', e.target.value)}>
            {Object.keys(ICON_MAP).map(k => <option key={k} value={k}>{k}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Opis">
        <textarea className="input input--sm" rows={2}
                  value={form.description} onChange={e => setF('description', e.target.value)} />
      </Field>
      <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, marginTop: 6 }}>
        <input type="checkbox" checked={form.is_active} onChange={e => setF('is_active', e.target.checked)} />
        Aktywny — dostępny do wyboru przy tworzeniu wniosku
      </label>
      {err && <div className="alert alert--error mt-2">{err}</div>}
      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <button className="btn btn--action btn--sm" onClick={save} disabled={saving}>
          <Save size={12} /> Zapisz
        </button>
        <button className="btn btn--ghost btn--sm" onClick={onCancel}>
          <X size={12} /> Anuluj
        </button>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11, marginTop: 6 }}>
      <span style={{ color: 'var(--color-text-muted)' }}>{label}</span>
      {children}
    </label>
  )
}
