import { useEffect, useState } from 'react'
import {
  Truck, Plus, Trash2, Edit2, Save, X, RefreshCw, FileText, AlertTriangle,
} from 'lucide-react'
import {
  listVendors, createVendor, updateVendor, deleteVendor,
  listContracts, addContract, updateContract, deleteContract,
} from '../api'
import { fmtDate } from '../serverTime'

/**
 * Słownik dostawców oprogramowania.
 *
 * Status umowy serwisowej NIE jest polem do zaznaczenia — backend wylicza go
 * z dat umów (`status`, `active_until`, `days_left`), więc nie da się go
 * rozjechać z rzeczywistością. Tutaj wyłącznie go prezentujemy.
 */

const STATUS_BADGE = {
  active:   { cls: 'badge--success', label: 'umowa aktualna' },
  expiring: { cls: 'badge--warning', label: 'umowa wygasa' },
  expired:  { cls: 'badge--error',   label: 'umowa wygasła' },
  none:     { cls: 'badge--neutral', label: 'brak umowy' },
}

function StatusBadge({ v }) {
  const s = STATUS_BADGE[v.status] || STATUS_BADGE.none
  let text = s.label
  if (v.status === 'expiring') text = `umowa wygasa za ${v.days_left} dni`
  if (v.status === 'active' && v.active_until) text = `umowa do ${fmtDate(v.active_until)}`
  if (v.status === 'expired' && v.active_until) text = `umowa wygasła ${fmtDate(v.active_until)}`
  return <span className={`badge ${s.cls}`} style={{ fontSize: 10 }}>{text}</span>
}

export default function Vendors() {
  const [vendors, setVendors] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [showAdd, setShowAdd] = useState(false)

  async function load() {
    setLoading(true); setErr(null)
    try {
      const r = await listVendors()
      setVendors(r.data)
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się pobrać listy dostawców')
    } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const expired = vendors.filter(v => v.status === 'expired')

  return (
    <div>
      <div className="page-header">
        <div>
          <div className="page-header__title">Dostawcy oprogramowania</div>
          <div className="page-header__sub">
            Producenci, dane kontaktowe i umowy serwisowe
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
          <button className="btn btn--action btn--sm" onClick={() => setShowAdd(v => !v)}>
            <Plus size={14} /> Dodaj dostawcę
          </button>
        </div>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      {expired.length > 0 && (
        <div className="alert alert--error mb-4" style={{ fontSize: 13 }}>
          <AlertTriangle size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          <strong>Wygasłe umowy serwisowe: {expired.length}</strong>
          {' — '}{expired.map(v => v.name).join(', ')}
        </div>
      )}

      {showAdd && (
        <VendorForm
          onCancel={() => setShowAdd(false)}
          onSaved={() => { setShowAdd(false); load() }}
        />
      )}

      {loading ? (
        <div className="card" style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>
      ) : vendors.length === 0 ? (
        <div className="card" style={{ color: 'var(--color-text-muted)', padding: 16 }}>
          <Truck size={14} style={{ verticalAlign: 'middle', marginRight: 6 }} />
          Brak dostawców w słowniku.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {vendors.map(v => (
            <VendorRow key={v.id} vendor={v} onReload={load} />
          ))}
        </div>
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Formularz dostawcy — wspólny dla dodawania i edycji
// ---------------------------------------------------------------------------
function VendorForm({ vendor, onCancel, onSaved }) {
  const [f, setF] = useState({
    name: vendor?.name || '',
    nip: vendor?.nip || '',
    address: vendor?.address || '',
    postal_code: vendor?.postal_code || '',
    city: vendor?.city || '',
    contact_person: vendor?.contact_person || '',
    phone: vendor?.phone || '',
    email: vendor?.email || '',
    website: vendor?.website || '',
    notes: vendor?.notes || '',
  })
  const [err, setErr] = useState(null)
  const [saving, setSaving] = useState(false)
  const set = (k, val) => setF(prev => ({ ...prev, [k]: val }))

  async function submit(e) {
    e.preventDefault(); setErr(null); setSaving(true)
    try {
      const payload = Object.fromEntries(
        Object.entries(f).map(([k, val]) => [k, (val || '').trim() || null])
      )
      payload.name = (f.name || '').trim()
      if (!payload.name) { setErr('Nazwa dostawcy jest wymagana'); setSaving(false); return }
      if (vendor) await updateVendor(vendor.id, payload)
      else await createVendor(payload)
      onSaved()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Błąd zapisu')
    } finally { setSaving(false) }
  }

  return (
    <div className="card mb-4" style={{ borderTop: '3px solid var(--color-gold)' }}>
      <form onSubmit={submit}>
        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Nazwa producenta *</label>
            <input className="form-control" required value={f.name}
                   onChange={e => set('name', e.target.value)} autoFocus />
          </div>
          <div className="form-group">
            <label className="form-label">NIP</label>
            <input className="form-control" value={f.nip}
                   onChange={e => set('nip', e.target.value)} />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Ulica i numer</label>
            <input className="form-control" value={f.address}
                   onChange={e => set('address', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Kod pocztowy</label>
            <input className="form-control" style={{ maxWidth: 140 }} value={f.postal_code}
                   onChange={e => set('postal_code', e.target.value)} placeholder="00-000" />
          </div>
          <div className="form-group">
            <label className="form-label">Miejscowość</label>
            <input className="form-control" value={f.city}
                   onChange={e => set('city', e.target.value)} />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Osoba kontaktowa</label>
            <input className="form-control" value={f.contact_person}
                   onChange={e => set('contact_person', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Telefon</label>
            <input className="form-control" value={f.phone}
                   onChange={e => set('phone', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">E-mail</label>
            <input className="form-control" value={f.email}
                   onChange={e => set('email', e.target.value)} />
          </div>
        </div>

        <div className="form-row">
          <div className="form-group">
            <label className="form-label">Strona WWW</label>
            <input className="form-control" value={f.website}
                   onChange={e => set('website', e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label">Uwagi</label>
            <input className="form-control" value={f.notes}
                   onChange={e => set('notes', e.target.value)} />
          </div>
        </div>

        {err && <div className="alert alert--error mb-4">{err}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn--ghost btn--sm" onClick={onCancel}>
            <X size={13} /> Anuluj
          </button>
          <button type="submit" className="btn btn--primary btn--sm" disabled={saving}>
            <Save size={13} /> Zapisz
          </button>
        </div>
      </form>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Karta dostawcy
// ---------------------------------------------------------------------------
function VendorRow({ vendor: v, onReload }) {
  const [editing, setEditing] = useState(false)
  const [contractsOpen, setContractsOpen] = useState(false)

  async function del() {
    if (!confirm(`Usunąć dostawcę „${v.name}"? Jego umowy serwisowe też zostaną usunięte.`)) return
    try { await deleteVendor(v.id); onReload() }
    catch (ex) { alert(ex.response?.data?.detail || 'Nie można usunąć') }
  }

  const addr = [v.address, [v.postal_code, v.city].filter(Boolean).join(' ')]
    .filter(Boolean).join(', ')
  const contact = [v.contact_person, v.phone, v.email].filter(Boolean).join(' · ')

  return (
    <div className="card" style={{
      padding: 0,
      // v3.0: wygasła umowa — pasek u góry karty (zamiast lewej krawędzi).
      borderTop: v.status === 'expired' ? '3px solid var(--color-error)' : undefined,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 16px', gap: 10,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
            <Truck size={15} style={{ color: 'var(--color-gold)' }} />
            <span style={{ fontWeight: 700 }}>{v.name}</span>
            <StatusBadge v={v} />
            {v.contract_count > 0 && (
              <span className="badge badge--neutral" style={{ fontSize: 10 }}>
                {v.contract_count} {v.contract_count === 1 ? 'umowa' : 'umów'}
              </span>
            )}
            {!v.is_active && (
              <span className="badge badge--neutral" style={{ fontSize: 10 }}>nieaktywny</span>
            )}
          </div>
          {addr && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 12, marginTop: 4 }}>
              {addr}{v.nip ? ` · NIP ${v.nip}` : ''}
            </div>
          )}
          {contact && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 12, marginTop: 2 }}>
              {contact}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexShrink: 0 }}>
          <button className="btn btn--ghost btn--sm" onClick={() => setContractsOpen(true)}>
            <FileText size={12} /> Umowy serwisowe
          </button>
          <button className="btn btn--ghost btn--sm" onClick={() => setEditing(e => !e)}>
            <Edit2 size={12} /> Edytuj
          </button>
          <button className="btn btn--danger btn--sm" onClick={del}>
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {editing && (
        <div style={{ padding: '0 16px 16px' }}>
          <VendorForm
            vendor={v}
            onCancel={() => setEditing(false)}
            onSaved={() => { setEditing(false); onReload() }}
          />
        </div>
      )}

      {contractsOpen && (
        <ContractsModal
          vendor={v}
          onClose={() => setContractsOpen(false)}
          onChanged={onReload}
        />
      )}
    </div>
  )
}


// ---------------------------------------------------------------------------
// Modal umów serwisowych dostawcy
// ---------------------------------------------------------------------------
function ContractsModal({ vendor, onClose, onChanged }) {
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({
    contract_number: '', valid_from: '', valid_to: '', description: '',
  })
  const set = (k, v) => setForm(prev => ({ ...prev, [k]: v }))

  async function load() {
    setLoading(true); setErr(null)
    try {
      const r = await listContracts(vendor.id)
      setRows(r.data)
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się pobrać umów')
    } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [vendor.id])

  async function onAdd() {
    if (!form.valid_to) { setErr('Podaj datę końca umowy'); return }
    setBusy(true); setErr(null)
    try {
      await addContract(vendor.id, {
        contract_number: form.contract_number.trim() || null,
        description: form.description.trim() || null,
        valid_from: form.valid_from || null,
        valid_to: form.valid_to,
      })
      setForm({ contract_number: '', valid_from: '', valid_to: '', description: '' })
      await load(); onChanged?.()
    } catch (ex) {
      setErr(ex.response?.data?.detail || 'Nie udało się dodać umowy')
    } finally { setBusy(false) }
  }

  async function onDelete(row) {
    if (!confirm('Usunąć tę umowę serwisową?')) return
    try { await deleteContract(row.id); await load(); onChanged?.() }
    catch (ex) { alert(ex.response?.data?.detail || 'Błąd') }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 760 }}>
        <div className="modal__header">
          <span className="modal__title">
            <FileText size={15} style={{ marginRight: 8, verticalAlign: 'middle' }} />
            Umowy serwisowe — {vendor.name}
          </span>
          <button className="modal__close" onClick={onClose}>×</button>
        </div>

        <div className="modal__body">
          {err && <div className="alert alert--error" style={{ marginBottom: 12 }}>{err}</div>}

          <div style={{
            padding: 12, background: 'var(--bg-secondary)', borderRadius: 6, marginBottom: 14,
          }}>
            <div style={{
              fontSize: 11, fontWeight: 700, marginBottom: 8,
              color: 'var(--color-text-muted)', textTransform: 'uppercase',
            }}>
              Dodaj umowę
            </div>
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 150px 150px auto', gap: 8,
              alignItems: 'end',
            }}>
              <div>
                <label className="form-label" style={{ fontSize: 11 }}>Numer umowy</label>
                <input className="form-control" style={{ fontSize: 13 }}
                       value={form.contract_number}
                       onChange={e => set('contract_number', e.target.value)}
                       placeholder="np. UM/2026/14" />
              </div>
              <div>
                <label className="form-label" style={{ fontSize: 11 }}>Od</label>
                <input className="form-control" type="date" style={{ fontSize: 13 }}
                       value={form.valid_from}
                       onChange={e => set('valid_from', e.target.value)} />
              </div>
              <div>
                <label className="form-label" style={{ fontSize: 11 }}>Do *</label>
                <input className="form-control" type="date" style={{ fontSize: 13 }}
                       value={form.valid_to}
                       onChange={e => set('valid_to', e.target.value)} />
              </div>
              <button className="btn btn--action btn--sm" onClick={onAdd}
                      disabled={busy || !form.valid_to}>
                <Plus size={12} /> Dodaj
              </button>
            </div>
            <div style={{ marginTop: 8 }}>
              <input className="form-control" style={{ fontSize: 13 }}
                     value={form.description}
                     onChange={e => set('description', e.target.value)}
                     placeholder="Zakres umowy (opcjonalnie)" />
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 6 }}>
              Dzień końcowy liczy się włącznie. Status dostawcy wylicza się z dat —
              nie trzeba niczego odklikiwać po wygaśnięciu.
            </div>
          </div>

          <table className="data-table" style={{ fontSize: 13 }}>
            <thead>
              <tr>
                <th>Numer</th><th>Okres</th><th>Zakres</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={5} style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={5} style={{ color: 'var(--color-text-muted)', padding: 12 }}>
                  Brak umów serwisowych dla tego dostawcy.
                </td></tr>
              ) : rows.map(c => <ContractRow key={c.id} c={c} onDelete={onDelete} />)}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function ContractRow({ c, onDelete }) {
  // Ten sam próg co w backendzie (EXPIRY_WARN_DAYS) — wizualne wyprzedzenie.
  const end = c.valid_to ? new Date(c.valid_to) : null
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const daysLeft = end ? Math.round((end.setHours(0, 0, 0, 0) - today) / 86400000) : null
  let badge = { cls: 'badge--success', text: 'aktualna' }
  if (daysLeft == null) badge = { cls: 'badge--neutral', text: '—' }
  else if (daysLeft < 0) badge = { cls: 'badge--error', text: 'wygasła' }
  else if (daysLeft <= 30) badge = { cls: 'badge--warning', text: `za ${daysLeft} dni` }

  return (
    <tr>
      <td style={{ fontWeight: 600 }}>{c.contract_number || '—'}</td>
      <td style={{ color: 'var(--color-text-muted)' }}>
        {c.valid_from ? fmtDate(c.valid_from) : '—'} — {fmtDate(c.valid_to)}
      </td>
      <td style={{ color: 'var(--color-text-muted)' }}>{c.description || '—'}</td>
      <td><span className={`badge ${badge.cls}`} style={{ fontSize: 10 }}>{badge.text}</span></td>
      <td>
        <button className="btn btn--danger btn--sm" onClick={() => onDelete(c)}>
          <Trash2 size={12} />
        </button>
      </td>
    </tr>
  )
}
