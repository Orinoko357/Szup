/**
 * Wspólny szkielet PEŁNOEKRANOWEGO widoku wniosku — jeden wygląd dla wszystkich
 * etapów (nowy pracownik, ustanie, wybór uprawnień, realizacja IT):
 *   - nagłówek: kafel-ikona + badge rodzaju + status + tytuł + podtytuł + „Wróć"
 *   - stepper obiegu (5 kroków) ze stanami done / current / skipped / future
 *   - dwie kolumny: treść (lewo) + Podsumowanie i Historia (prawo)
 *   - pasek akcji na dole karty
 *
 * Widoki przekazują własną treść jako children; resztę składa ten komponent,
 * żeby wszystkie wnioski wyglądały jednakowo.
 */
import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'
import { getRequestWorkflow } from '../api'

// Etykiety akcji obiegu w historii.
const ACTION_VERB = {
  select:  'wybrał(a) uprawnienia',
  approve: 'zatwierdził(a)',
  execute: 'zrealizował(a)',
  reject:  'odrzucił(a)',
}
const NODE_WHO = {
  select_permissions: 'Kierownik', manager_approve: 'Kierownik',
  higher_manager_approve: 'Kierownik nadrzędny', it_execute: 'IT',
}

function fmtDT(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return isNaN(d) ? '' : d.toLocaleString('pl-PL', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

const KIND_TONE = {
  grant:  { bg: '#FEF3DC', fg: '#8A6D1B', bd: '#E6C34D' },   // zatrudnienie
  revoke: { bg: '#FBE4E2', fg: '#9A3227', bd: '#E7A79F' },   // odejście
  change: { bg: '#E6EEF9', fg: '#2B5591', bd: '#B9CDE8' },   // zmiana
}

export function KindBadge({ kind = 'grant', label }) {
  const t = KIND_TONE[kind] || KIND_TONE.grant
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
      background: t.bg, color: t.fg, border: `1px solid ${t.bd}`,
      fontSize: 10, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase',
    }}>{label}</span>
  )
}

/** Pełna nazwa komórki: „KOD · opis z AD” (np. „INF · Biuro Informatyki”);
 *  bez opisu (albo gdy opis = kod) — sam kod. */
export function deptFull(code, desc) {
  const c = (code || '').trim(), d = (desc || '').trim()
  if (!c) return d || '—'
  return d && d.toLowerCase() !== c.toLowerCase() ? `${c} · ${d}` : c
}

/** Karta „Pracownik” (wg makiety): inicjały + imię i nazwisko + podtytuł,
 *  po prawej kolumny typu WYDZIAŁ / JEDNOSTKA / STANOWISKO. */
export function WorkerCard({ name, sub, cols = [] }) {
  const initials = (name || '?').split(/\s+/).filter(Boolean).slice(0, 2)
    .map(w => w[0].toUpperCase()).join('')
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexWrap: 'wrap',
                  padding: '12px 16px', borderRadius: 8, border: '1px solid var(--color-border)',
                  background: 'var(--bg-secondary)' }}>
      <span style={{ flexShrink: 0, width: 38, height: 38, borderRadius: '50%',
                     display: 'grid', placeItems: 'center', fontSize: 13, fontWeight: 700,
                     background: 'var(--color-card)', color: 'var(--color-navy)',
                     border: '1px solid var(--color-border)' }}>{initials}</span>
      <div style={{ flex: '1 1 200px', minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--color-navy)' }}>{name || '—'}</div>
        {sub && (
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sub}</div>
        )}
      </div>
      {cols.map((c, i) => (
        <div key={i} style={{ minWidth: 70 }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '.06em',
                        color: 'var(--color-text-muted)', textTransform: 'uppercase' }}>{c.label}</div>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{c.value || '—'}</div>
        </div>
      ))}
    </div>
  )
}

/** Numerowany nagłówek sekcji: „01 Tytuł”. */
export function Section({ n, title, note, children }) {
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 10,
                    borderBottom: '1px solid var(--color-border)', paddingBottom: 6 }}>
        {n != null && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700,
                         color: 'var(--color-gold)' }}>{String(n).padStart(2, '0')}</span>
        )}
        <span style={{ fontWeight: 700, fontSize: 15, color: 'var(--color-navy)' }}>{title}</span>
        {note && <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{note}</span>}
      </div>
      {children}
    </div>
  )
}

// --- Stepper -----------------------------------------------------------------
function StepItem({ step }) {
  const { n, label, caption, state } = step
  const isCurrent = state === 'current'
  const isDone = state === 'done'
  const isSkipped = state === 'skipped'
  // v3.0: zakończone kroki z delikatnym zielonym tłem (wg projektu).
  const bg = isCurrent ? '#FEF6E3' : isDone ? 'var(--color-success-bg)' : 'var(--color-card)'
  const bd = isCurrent ? '#E6C34D' : 'var(--color-border)'
  return (
    <div style={{
      flex: 1, minWidth: 150, display: 'flex', alignItems: 'flex-start', gap: 8,
      padding: '10px 12px', borderRadius: 8, border: `1px solid ${bd}`,
      background: bg, borderStyle: isSkipped ? 'dashed' : 'solid',
      opacity: isSkipped ? 0.7 : 1,
    }}>
      <span style={{
        flexShrink: 0, width: 22, height: 22, borderRadius: '50%',
        display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 700,
        background: isDone ? 'var(--color-success)' : isCurrent ? 'var(--color-navy)' : 'transparent',
        color: (isDone || isCurrent) ? '#fff' : 'var(--color-text-muted)',
        border: (isDone || isCurrent) ? 'none' : '1.5px solid var(--color-border-strong, var(--color-border))',
      }}>
        {isDone ? <Check size={13} /> : isSkipped ? '–' : n}
      </span>
      <div style={{ lineHeight: 1.25 }}>
        <div style={{ fontSize: 12.5, fontWeight: 700,
                      textDecoration: isSkipped ? 'line-through' : 'none',
                      color: isCurrent ? 'var(--color-navy)' : 'var(--color-text)' }}>
          {label}
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{caption}</div>
      </div>
    </div>
  )
}

export function RequestStepper({ steps = [] }) {
  if (!steps.length) return null
  return (
    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 18 }}>
      {steps.map((s, i) => <StepItem key={i} step={s} />)}
    </div>
  )
}

/**
 * Buduje 5-krokowy obieg ze stanami na podstawie statusu/węzła wniosku.
 *   sent          — czy wniosek został już złożony (false = formularz tworzenia)
 *   nodeType      — bieżący węzeł obiegu (select_permissions / manager_approve /
 *                   higher_manager_approve / it_execute) lub null
 *   status        — RequestStatus (completed / rejected / …)
 *   requiresHigher— czy komórka wymaga akceptacji wyższego rzędu
 *   kind          — grant / revoke (wpływa na etykietę kroku 2)
 */
export function buildWorkflowSteps({ sent, nodeType, status, requiresHigher, kind }) {
  // Indeks bieżącego etapu 1..5
  let cur
  if (!sent) cur = 1
  else if (status === 'completed') cur = 5
  else if (nodeType === 'select_permissions' || nodeType === 'manager_approve' || status === 'pending_selection' || status === 'pending_manager') cur = 2
  else if (nodeType === 'higher_manager_approve') cur = 3
  else if (nodeType === 'it_execute' || status === 'pending_it') cur = 4
  else cur = 2

  const rejected = status === 'rejected'
  const step2Label = kind === 'revoke' ? 'Uprawnienia do odebrania' : 'Wybór uprawnień'

  function st(idx) {
    if (rejected) return idx < cur ? 'done' : idx === cur ? 'current' : 'future'
    if (idx === 3 && !requiresHigher) return cur > 3 ? 'skipped' : (cur === 3 ? 'current' : 'skipped')
    if (idx < cur) return 'done'
    if (idx === cur) return 'current'
    return 'future'
  }

  return [
    { n: 1, label: 'Zgłoszenie',       caption: 'Kadry / HR',             state: st(1) },
    { n: 2, label: step2Label,         caption: 'Kierownik komórki',      state: st(2) },
    { n: 3, label: 'Akceptacja wyższa', caption: requiresHigher ? 'Kierownik nadrzędny' : 'Pominięta',  state: st(3) },
    { n: 4, label: 'Realizacja',       caption: 'Biuro Informatyki',      state: st(4) },
    { n: 5, label: 'Zakończony',       caption: 'Powiadomienie HR',       state: st(5) },
  ]
}

// --- Prawa kolumna: Podsumowanie + Historia ---------------------------------
function SummaryBox({ rows = [] }) {
  if (!rows.length) return null
  return (
    <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ background: 'var(--color-navy)', color: '#fff', padding: '8px 12px',
                    fontSize: 11, fontWeight: 800, letterSpacing: '.06em' }}>
        PODSUMOWANIE
      </div>
      <div style={{ padding: '8px 12px' }}>
        {rows.map((r, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 12,
                                padding: '4px 0', fontSize: 13 }}>
            <span style={{ color: 'var(--color-text-muted)' }}>{r.label}</span>
            <span style={{ fontWeight: 600, textAlign: 'right' }}>{r.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function HistoryBox({ items = [], requestId, createdBy }) {
  // Gdy podano requestId — pobierz realną oś czasu kroków obiegu.
  const [steps, setSteps] = useState(null)
  useEffect(() => {
    if (!requestId) { setSteps(null); return }
    let alive = true
    getRequestWorkflow(requestId)
      .then(r => { if (alive) setSteps(r.data?.steps || []) })
      .catch(() => { if (alive) setSteps([]) })
    return () => { alive = false }
  }, [requestId])

  // Buduj wpisy: z kroków obiegu (gdy są) albo z przekazanych items.
  let rows = items
  if (requestId && steps) {
    rows = steps.map(s => {
      const sub = fmtDT(s.created_at)
      // Kroki systemowe silnika obiegu — opisane po ludzku, bez surowych nazw akcji.
      if (s.action === 'auto_advance' && s.node_type === 'start') {
        return { text: `${createdBy || 'Kadry / HR'} złożył(a) wniosek`, sub }
      }
      if (s.action === 'auto_advance' && s.node_type === 'end') {
        return { text: 'Obieg zakończony', sub }
      }
      if (s.action === 'auto_skip') {
        const text = s.node_type === 'higher_manager_approve'
          ? 'Akceptacja wyższa pominięta — nie wymaga jej szablon obiegu'
          : `${NODE_WHO[s.node_type] ? NODE_WHO[s.node_type] + ' — krok' : 'Krok'} pominięty (warunek obiegu)`
        return { text, sub, skipped: true }
      }
      const who = s.actor_name || NODE_WHO[s.node_type] || ''
      const verb = ACTION_VERB[s.action] || s.action
      return {
        text: `${who ? who + ' ' : ''}${verb}`,
        sub,
        comment: s.comment || null,
        muted: s.action === 'reject',
      }
    })
  }

  return (
    <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, padding: '10px 12px' }}>
      <div style={{ fontSize: 11, fontWeight: 800, letterSpacing: '.06em',
                    color: 'var(--color-text-muted)', marginBottom: 8 }}>HISTORIA</div>
      {requestId && steps === null ? (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Ładowanie…</div>
      ) : rows.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          {requestId ? 'Brak kroków w obiegu.' : 'Wniosek nie został jeszcze wysłany.'}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((it, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, fontSize: 12 }}>
              <span style={{ flexShrink: 0, width: 8, height: 8, borderRadius: '50%', marginTop: 4,
                             boxSizing: 'border-box',
                             border: it.skipped ? '1.5px dashed var(--color-text-muted)' : 'none',
                             background: it.skipped ? 'transparent'
                               : it.muted ? 'var(--color-error)' : 'var(--color-success)' }} />
              <div>
                <div style={{ color: (it.muted || it.skipped) ? 'var(--color-text-muted)' : 'inherit' }}>{it.text}</div>
                {it.sub && <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{it.sub}</div>}
                {it.comment && (
                  <div style={{ fontSize: 11, color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                    „{it.comment}"
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// --- Główny szkielet ---------------------------------------------------------
export default function RequestViewShell({
  icon: Icon, kind, kindLabel, statusText, title, subtitle,
  backLabel = '← Wróć', onBack, steps = [],
  summary = [], history = [], historyRequestId, historyCreatedBy, footerLeft, footerActions, children,
}) {
  return (
    <div>
      {/* Nagłówek */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 16, flexWrap: 'wrap' }}>
        {Icon && (
          <div style={{ flexShrink: 0, width: 44, height: 44, borderRadius: 10,
                        background: 'var(--color-navy)', color: 'var(--color-gold)',
                        display: 'grid', placeItems: 'center' }}>
            <Icon size={20} />
          </div>
        )}
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {kindLabel && <KindBadge kind={kind} label={kindLabel} />}
            {statusText && <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{statusText}</span>}
          </div>
          <div style={{ fontSize: 22, fontWeight: 800, color: 'var(--color-navy)', marginTop: 2 }}>{title}</div>
          {subtitle && <div style={{ fontSize: 13, color: 'var(--color-text-muted)', marginTop: 2 }}>{subtitle}</div>}
        </div>
        <button type="button" className="btn btn--ghost" onClick={onBack}>{backLabel}</button>
      </div>

      <RequestStepper steps={steps} />

      {/* Dwie kolumny */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        <div style={{ flex: '1 1 560px', minWidth: 0 }}>
          <div className="card">
            {children}
            {(footerLeft || footerActions) && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            gap: 12, flexWrap: 'wrap', marginTop: 20,
                            borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
                <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{footerLeft}</div>
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>{footerActions}</div>
              </div>
            )}
          </div>
        </div>
        {(summary.length > 0 || history.length >= 0) && (
          <aside style={{ flex: '0 0 300px', maxWidth: '100%', display: 'flex',
                          flexDirection: 'column', gap: 12 }}>
            <SummaryBox rows={summary} />
            <HistoryBox items={history} requestId={historyRequestId} createdBy={historyCreatedBy} />
          </aside>
        )}
      </div>
    </div>
  )
}
