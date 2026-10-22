import { useEffect, useId, useState } from 'react'
import {
  Truck, Plus, Trash2, Edit2, Save, RefreshCw, FileText,
} from 'lucide-react'
import {
  listVendors, createVendor, updateVendor, deleteVendor,
  listContracts, addContract, deleteContract,
 errorMessage} from '../api'
import { fmtDate } from '../serverTime'
import { toast, ask } from '../components/ui/feedback'
import Modal from '../components/ui/Modal'



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
  return <span className={`badge ${s.cls}`} style={{ fontSize: 11, fontWeight: 700 }}>{text}</span>
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
      setErr(errorMessage(ex, 'Nie udało się pobrać listy dostawców'))
    } finally { setLoading(false) }
  }
  useEffect(() => { load() }, [])

  const expired = vendors.filter(v => v.status === 'expired')

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header__title">Dostawcy i umowy</h1>
          <div className="page-header__sub">
            Producenci, dane kontaktowe i umowy serwisowe
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          <button type="button" className="btn btn--ghost" onClick={load} disabled={loading}>
            <RefreshCw size={14} /> Odśwież
          </button>
          <button type="button" className="btn btn--action" onClick={() => setShowAdd(v => !v)}>
            <Plus size={14} /> Dodaj dostawcę
          </button>
        </div>
      </div>

      {err && <div className="alert alert--error mb-4">{err}</div>}

      {expired.length > 0 && (
        <div role="alert" style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px', marginBottom: 16,
          borderRadius: 8, background: 'var(--color-error-bg)', color: 'var(--color-error-text)', fontSize: 14,
        }}>
          <span aria-hidden="true" style={{
            width: 22, height: 22, flexShrink: 0, borderRadius: '50%', background: 'var(--color-card)',
            display: 'grid', placeItems: 'center', fontWeight: 800, fontSize: 12,
          }}>!</span>
          <span>
            <strong>Wygasłe umowy serwisowe: {expired.length}</strong>
            {' — '}{expired.map(v => v.name).join(', ')}
          </span>
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
          Brak dostawców w słowniku. Dodaj pierwszego przyciskiem „Dodaj dostawcę” — potem przypiszesz go do programów w „Oprogramowaniu”.
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
  // Unikalne id pól per formularz — dodawanie i edycja mogą być otwarte naraz.
  const uid = useId()
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
      toast(vendor ? `Zapisano zmiany: ${payload.name}` : `Dodano dostawcę: ${payload.name}`)
      onSaved()
    } catch (ex) {
      setErr(errorMessage(ex, 'Nie udało się zapisać dostawcy'))
    } finally { setSaving(false) }
  }

  // Pola formularza — kolejność jak w projekcie (siatka 3 kolumny).
  const FIELDS = [
    ['name', 'Nazwa producenta *', {}],
    ['nip', 'NIP', {}],
    ['address', 'Ulica i numer', {}],
    ['postal_code', 'Kod pocztowy', { placeholder: '00-000' }],
    ['city', 'Miejscowość', {}],
    ['contact_person', 'Osoba kontaktowa', {}],
    ['phone', 'Telefon', {}],
    ['email', 'E-mail', {}],
    ['website', 'Strona WWW', {}],
  ]

  return (
    <section className="card mb-4" aria-label={vendor ? 'Edycja dostawcy' : 'Nowy dostawca'}
             style={{ border: '2px solid var(--color-selected)', padding: '18px 18px 16px' }}>
      <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <h2 style={{ margin: 0, fontSize: 16, fontWeight: 800, color: 'var(--color-heading)' }}>
          {vendor ? `Edycja: ${vendor.name}` : 'Nowy dostawca'}
        </h2>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 12 }}>
          {FIELDS.map(([k, label, extra]) => (
            <div key={k}>
              <label className="form-label" htmlFor={`${uid}-${k}`}>{label}</label>
              <input id={`${uid}-${k}`} className="form-control" style={{ minHeight: 44 }}
                     required={k === 'name'} autoFocus={k === 'name'}
                     value={f[k]} onChange={e => set(k, e.target.value)} {...extra} />
            </div>
          ))}
        </div>
        <div>
          <label className="form-label" htmlFor={`${uid}-notes`}>Uwagi</label>
          <textarea id={`${uid}-notes`} className="form-control" style={{ minHeight: 70 }}
                    value={f.notes} onChange={e => set('notes', e.target.value)} />
        </div>

        {err && <div className="alert alert--error">{err}</div>}
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn--ghost" onClick={onCancel}>
            Anuluj
          </button>
          <button type="submit" className="btn btn--primary" disabled={saving}>
            <Save size={13} /> Zapisz
          </button>
        </div>
      </form>
    </section>
  )
}


// ---------------------------------------------------------------------------
// Karta dostawcy
// ---------------------------------------------------------------------------
function VendorRow({ vendor: v, onReload }) {
  const [editing, setEditing] = useState(false)
  const [contractsOpen, setContractsOpen] = useState(false)

  async function del() {
    if (!await ask(`Usunąć dostawcę „${v.name}"? Jego umowy serwisowe też zostaną usunięte.`, { title: 'Potwierdź operację', confirmLabel: 'Usuń dostawcę', danger: true })) return
    try { await deleteVendor(v.id); onReload(); toast(`Usunięto dostawcę „${v.name}”`) }
    catch (ex) { toast(errorMessage(ex, 'Nie można usunąć'), { tone: 'error' }) }
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
        display: 'flex', alignItems: 'flex-start', flexWrap: 'wrap',
        padding: '14px 16px', gap: 12,
      }}>
        <span aria-hidden="true" style={{
          width: 34, height: 34, borderRadius: 8, flexShrink: 0, background: 'var(--bg-secondary)',
          color: 'var(--color-heading)', display: 'grid', placeItems: 'center',
        }}>
          <Truck size={17} />
        </span>
        <div style={{ flex: '1 1 360px', minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <strong style={{ fontSize: 15, color: 'var(--color-heading)' }}>{v.name}</strong>
            <StatusBadge v={v} />
            {v.contract_count > 0 && (
              <span className="badge badge--neutral" style={{ fontSize: 11, fontWeight: 700 }}>
                {v.contract_count} {v.contract_count === 1 ? 'umowa' : 'umów'}
              </span>
            )}
            {!v.is_active && (
              <span className="badge badge--neutral" style={{ fontSize: 11, fontWeight: 700 }}>nieaktywny</span>
            )}
          </div>
          {addr && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 13, marginTop: 4 }}>
              {addr}{v.nip ? ` · NIP ${v.nip}` : ''}
            </div>
          )}
          {contact && (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 13, marginTop: 2 }}>
              {contact}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
          <button type="button" className="btn btn--ghost btn--sm" style={{ minHeight: 36, fontWeight: 700 }} onClick={() => setContractsOpen(true)}>
            <FileText size={12} /> Umowy serwisowe
          </button>
          <button type="button" className="btn btn--ghost btn--sm" style={{ minHeight: 36 }} onClick={() => setEditing(e => !e)}>
            <Edit2 size={12} /> Edytuj
          </button>
          <button type="button" className="btn btn--ghost btn--sm" onClick={del} aria-label="Usuń dostawcę" title="Usuń dostawcę"
                  style={{ minHeight: 36, width: 36, padding: 0, justifyContent: 'center',
                           color: 'var(--color-error-text)', borderColor: 'var(--color-error)' }}>
            <Trash2 size={14} />
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
  const cid = useId()
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
      setErr(errorMessage(ex, 'Nie udało się pobrać umów'))
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
      setErr(errorMessage(ex, 'Nie udało się dodać umowy'))
    } finally { setBusy(false) }
  }

  async function onDelete(row) {
    if (!await ask('Usunąć tę umowę serwisową?', { title: 'Potwierdź operację', confirmLabel: 'Usuń umowę', danger: true })) return
    try { await deleteContract(row.id); await load(); onChanged?.(); toast('Usunięto umowę serwisową') }
    catch (ex) { toast(errorMessage(ex, 'Nie udało się usunąć umowy'), { tone: 'error' }) }
  }

  return (
    // Wspólne ui/Modal (pułapka fokusu, Escape, zwrot fokusu, blokada przewijania).
    <Modal title={`Umowy serwisowe — ${vendor.name}`} onClose={onClose} width={820}>
      {err && <div className="alert alert--error" role="alert" style={{ marginBottom: 12 }}>{err}</div>}

      <div style={{
        padding: 14, background: 'var(--bg-secondary)', border: '1px solid var(--color-border)', borderRadius: 8, marginBottom: 16,
      }}>
        <h3 style={{ margin: '0 0 10px', fontSize: 14, fontWeight: 800, color: 'var(--color-heading)' }}>
          Dodaj umowę
        </h3>
        <div style={{
          display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 150px 150px auto', gap: 10,
          alignItems: 'end',
        }}>
          <div>
            <label className="form-label" style={{ fontSize: 11 }} htmlFor={`${cid}-no`}>Numer umowy</label>
            <input id={`${cid}-no`} className="form-control" style={{ fontSize: 13 }}
                   value={form.contract_number}
                   onChange={e => set('contract_number', e.target.value)}
                   placeholder="np. UM/2026/14" />
          </div>
          <div>
            <label className="form-label" style={{ fontSize: 11 }} htmlFor={`${cid}-from`}>Od</label>
            <input id={`${cid}-from`} className="form-control" type="date" style={{ fontSize: 13 }}
                   value={form.valid_from}
                   onChange={e => set('valid_from', e.target.value)} />
          </div>
          <div>
            <label className="form-label" style={{ fontSize: 11 }} htmlFor={`${cid}-to`}>Do *</label>
            <input id={`${cid}-to`} required className="form-control" type="date" style={{ fontSize: 13 }}
                   value={form.valid_to}
                   onChange={e => set('valid_to', e.target.value)} />
          </div>
          <button type="button" className="btn btn--action" style={{ minHeight: 40 }} onClick={onAdd}
                  disabled={busy || !form.valid_to}>
            <Plus size={12} /> Dodaj
          </button>
        </div>
        <div style={{ marginTop: 8 }}>
          <input className="form-control" style={{ fontSize: 13 }} aria-label="Zakres umowy"
                 value={form.description}
                 onChange={e => set('description', e.target.value)}
                 placeholder="Zakres umowy (opcjonalnie)" />
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 6 }}>
          Dzień końcowy liczy się włącznie. Status dostawcy wylicza się z dat —
          nie trzeba niczego odklikiwać po wygaśnięciu.
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
      <table className="data-table" style={{ fontSize: 14, border: '1px solid var(--color-border)' }}>
        <thead>
          <tr>
            <th>Numer</th><th>Okres</th><th>Zakres</th><th>Status</th><th><span className="sr-only">Akcje</span></th>
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
    </Modal>
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
      <td><span className={`badge ${badge.cls}`} style={{ fontSize: 11, fontWeight: 700 }}>{badge.text}</span></td>
      <td style={{ textAlign: 'right' }}>
        <button type="button" className="btn btn--ghost btn--sm" onClick={() => onDelete(c)} aria-label="Usuń umowę" title="Usuń umowę"
                style={{ width: 34, padding: 0, justifyContent: 'center', color: 'var(--color-error-text)', borderColor: 'var(--color-error)' }}>
          <Trash2 size={13} />
        </button>
      </td>
    </tr>
  )
}
