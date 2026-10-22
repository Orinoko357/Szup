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
          <button className="btn btn--ghost" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
          <button className="btn btn--action" onClick={() => setEditing('new')}>
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

      <section aria-label="Typy wniosków" className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div style={{ overflowX: 'auto' }}>
        <table className="table" style={{ minWidth: 900 }}>
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
      </section>
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
      <td style={{ width: 48 }}>
        <span aria-hidden="true" style={{ width: 34, height: 34, borderRadius: 8, background: 'var(--bg-secondary)',
                                          color: 'var(--color-heading)', display: 'grid', placeItems: 'center' }}>
          <Icon size={17} />
        </span>
      </td>
      <td>
        <span style={{ display: 'block', fontWeight: 700, color: 'var(--color-heading)' }}>{t.name}</span>
        {t.description && (
          <span style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)' }}>{t.description}</span>
        )}
      </td>
      <td style={{ fontFamily: 'var(--font-mono)', fontSize: 13 }}>{t.code || '—'}</td>
      <td style={{ fontSize: 13 }}>
        {t.workflow_template_name || '—'}
        {t.workflow_template_version && (
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-text-muted)', marginLeft: 6 }}>
            v{t.workflow_template_version}
          </span>
        )}
      </td>
      <td style={{ fontSize: 13 }}>{t.used_by_requests_count}</td>
      <td>
        {t.is_active
          ? <span className="badge badge--success">aktywny</span>
          : <span className="badge badge--neutral">nieaktywny</span>}
      </td>
      <td style={{ whiteSpace: 'nowrap', textAlign: 'right' }}>
        <button className="btn btn--ghost btn--sm" onClick={onEdit} aria-label="Edytuj" title="Edytuj"
                style={{ border: 0 }}><Edit2 size={15} /></button>
        <button className="btn btn--ghost btn--sm" onClick={del} aria-label="Usuń" title="Usuń"
                style={{ border: 0, color: 'var(--color-error-text)' }}><Trash2 size={15} /></button>
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
    <section aria-label={isEdit ? 'Edycja typu wniosku' : 'Nowy typ wniosku'} className="card"
             style={{ padding: '18px 20px', borderTop: '3px solid var(--color-gold)',
                      margin: isEdit ? 0 : '0 0 18px 0', display: 'flex', flexDirection: 'column', gap: 14 }}>
      <h2 style={{ margin: 0, fontSize: 17, fontWeight: 800, color: 'var(--color-heading)' }}>
        {isEdit ? 'Edycja typu wniosku' : 'Nowy typ wniosku'}
      </h2>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 14 }}>
        <Field label="Nazwa *">
          <input className="form-control" style={INP} value={form.name} onChange={e => setF('name', e.target.value)} />
        </Field>
        <Field label="Kod (skrót)">
          <input className="form-control" style={INP} value={form.code} onChange={e => setF('code', e.target.value)} placeholder="np. NEW_EMP" />
        </Field>
        <Field label="Szablon obiegu *">
          <select className="form-control" style={INP} value={form.workflow_template_id} onChange={e => setF('workflow_template_id', e.target.value)}>
            <option value="">— wybierz —</option>
            {templates.map(t => <option key={t.id} value={t.id}>{t.name} (v{t.version})</option>)}
          </select>
        </Field>
        <Field label="Ikona">
          <select className="form-control" style={INP} value={form.icon} onChange={e => setF('icon', e.target.value)}>
            {Object.keys(ICON_MAP).map(k => <option key={k} value={k}>{k}</option>)}
          </select>
        </Field>
      </div>
      <Field label="Opis">
        <textarea className="form-control" rows={2} style={{ minHeight: 70, fontSize: 14, fontWeight: 400, letterSpacing: 0, textTransform: 'none' }}
                  value={form.description} onChange={e => setF('description', e.target.value)} />
      </Field>
      {err && <div className="alert alert--error">{err}</div>}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
        <label className="form-check" style={{ flex: '1 1 360px', fontSize: 14 }}>
          <input type="checkbox" checked={form.is_active} onChange={e => setF('is_active', e.target.checked)}
                 style={{ width: 18, height: 18 }} />
          Aktywny — dostępny do wyboru przy tworzeniu wniosku
        </label>
        <button className="btn btn--ghost" onClick={onCancel}>
          <X size={14} /> Anuluj
        </button>
        <button className="btn btn--action" onClick={save} disabled={saving}>
          <Save size={14} /> Zapisz
        </button>
      </div>
    </section>
  )
}

const INP = { minHeight: 44, fontSize: 14, fontWeight: 400, letterSpacing: 0, textTransform: 'none' }

function Field({ label, children }) {
  return (
    <label style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11, fontWeight: 700,
                    letterSpacing: '.08em', textTransform: 'uppercase', color: 'var(--color-text-muted)' }}>
      {label}
      {children}
    </label>
  )
}
