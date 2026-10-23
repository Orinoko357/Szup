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
import { useEffect, useRef, useState } from 'react'
import { Check } from 'lucide-react'
import { getRequestWorkflow } from '../api'
import { getUserRoles } from '../roles'
import { serverTs, fmtDateTimeShort } from '../serverTime'
import { daysSince, waitText, kindLabel as kindLabelOf, nodeLabel, statusLabel, NODE_WHO } from '../labels'

/** v3.1 — perspektywa dla osób z kilkoma rolami: „jako kierownik” / „jako IT”…
 *  Zwraca null, gdy użytkownik pełni tylko jedną funkcję operacyjną. */
export function perspectiveLabel(nodeType) {
  const roles = getUserRoles()
  const ops = ['manager', 'it_staff', 'hr'].filter(r => roles.includes(r))
  if (ops.length < 2 || !nodeType) return null
  if (nodeType === 'it_execute') return 'jako IT'
  if (nodeType === 'higher_manager_approve') return 'jako kierownik nadrzędny'
  if (nodeType === 'select_permissions' || nodeType === 'manager_approve') return 'jako kierownik'
  return null
}

/** v3.1 — „Czeka na: X · od N dni” (pola z backendu: waiting_for, step_since). */
export function waitingText(r) {
  if (!r || !r.waiting_for) return null
  const d = daysSince(serverTs(r.step_since))
  return `Czeka na: ${r.waiting_for}${d != null ? ` · od ${waitText(d)}` : ''}`
}

// Etykiety akcji obiegu w historii.
const ACTION_VERB = {
  select:  'wybrał(a) uprawnienia',
  approve: 'zatwierdził(a)',
  execute: 'zrealizował(a)',
  reject:  'odrzucił(a)',
  draft:     'zapisał(a) wersję roboczą',
  take_over: 'przejął(-ęła) wniosek',
  release:   'oddał(a) wniosek',
}

// Kolory odznaki rodzaju — tokeny motywu (działają w trybie ciemnym).
const KIND_TONE = {
  grant:  { bg: 'var(--color-warning-bg)', fg: 'var(--color-gold-dark)',   bd: 'var(--color-gold)' },    // zatrudnienie
  revoke: { bg: 'var(--color-error-bg)',   fg: 'var(--color-error-text)',  bd: 'var(--color-error)' },   // odejście
  change: { bg: 'var(--color-info-bg)',    fg: 'var(--color-info-text)',   bd: 'var(--color-info)' },    // zmiana
}

export function KindBadge({ kind = 'grant', label }) {
  const t = KIND_TONE[kind] || KIND_TONE.grant
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 4,
      background: t.bg, color: t.fg, border: `1px solid ${t.bd}`,
      fontSize: 10, fontWeight: 800, letterSpacing: '.07em', textTransform: 'uppercase',
    }}>{label || kindLabelOf(kind)}</span>
  )
}

/** Odznaka rodzaju wniosku w listach (nieznany rodzaj → zatrudnienie). */
export function KindPill({ kind }) {
  const k = ['revoke', 'change'].includes(kind) ? kind : 'grant'
  return <KindBadge kind={k} label={kindLabelOf(kind)} />
}

/** Zwrot fokusu po zamknięciu pełnoekranowego widoku wniosku: gdy `openKey`
 *  wraca do null, a lista jest już wyrenderowana (`ready`), fokus trafia na
 *  przycisk z atrybutem data-return-focus={openKey}, który widok otworzył.
 *  Gdy wiersza już nie ma (np. wniosek obsłużony) — fokus zostaje bez zmian. */
export function useReturnFocus(openKey, ready = true) {
  const last = useRef(null)
  useEffect(() => {
    if (openKey != null) { last.current = String(openKey); return }
    if (last.current == null || !ready) return
    const key = last.current
    last.current = null
    const sel = `[data-return-focus="${window.CSS?.escape ? window.CSS.escape(key) : key}"]`
    const el = document.querySelector(sel)
    if (el && typeof el.focus === 'function') el.focus()
  }, [openKey, ready])
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
                     display: 'grid', placeItems: 'center', fontSize: 13, fontWeight: 800,
                     background: 'var(--color-card)', color: 'var(--color-heading)',
                     border: '1px solid var(--color-border)' }}>{initials}</span>
      <div style={{ flex: '1 1 200px', minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--color-heading)' }}>{name || '—'}</div>
        {sub && (
          <div style={{ fontSize: 12, color: 'var(--color-text-muted)',
                        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{sub}</div>
        )}
      </div>
      {cols.map((c, i) => (
        <div key={i} style={{ minWidth: 80 }}>
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
    <section style={{ marginBottom: 22 }}>
      <h2 style={{ display: 'flex', alignItems: 'baseline', gap: 8, margin: '0 0 12px',
                   borderBottom: '1px solid var(--color-border)', paddingBottom: 8,
                   fontWeight: 700, fontSize: 16, color: 'var(--color-heading)' }}>
        {n != null && (
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700,
                         color: 'var(--color-gold-dark)' }}>{String(n).padStart(2, '0')}</span>
        )}
        {title}
        {note && <span style={{ fontSize: 12, fontWeight: 400, color: 'var(--color-text-muted)' }}>{note}</span>}
      </h2>
      {children}
    </section>
  )
}

// --- Stepper -----------------------------------------------------------------
function StepItem({ step }) {
  const { n, label, caption, state } = step
  const isCurrent = state === 'current'
  const isDone = state === 'done'
  const isSkipped = state === 'skipped'
  // v3.0: zakończone kroki z delikatnym zielonym tłem (wg projektu).
  const bg = isCurrent ? 'var(--color-warning-bg)' : isDone ? 'var(--color-success-bg)' : 'var(--color-card)'
  const bd = isCurrent ? 'var(--color-gold)' : isDone ? 'var(--color-border)'
    : isSkipped ? 'var(--color-border-strong, var(--color-border))' : 'var(--color-border)'
  return (
    <li style={{
      display: 'flex', alignItems: 'flex-start', gap: 8,
      padding: '10px 12px', borderRadius: 8, border: `1px solid ${bd}`,
      background: bg, borderStyle: isSkipped ? 'dashed' : 'solid',
    }}>
      <span style={{
        flexShrink: 0, width: 22, height: 22, borderRadius: '50%',
        display: 'grid', placeItems: 'center', fontSize: 11, fontWeight: 800, boxSizing: 'border-box',
        background: isDone ? 'var(--color-success)' : isCurrent ? 'var(--color-heading)' : 'transparent',
        color: isDone ? '#fff' : isCurrent ? 'var(--color-card)' : 'var(--color-text-muted)',
        border: (isDone || isCurrent) ? 'none' : '1.5px solid var(--color-border-strong, var(--color-border))',
      }}>
        {isDone ? <Check size={13} /> : isSkipped ? '–' : n}
      </span>
      <div style={{ lineHeight: 1.25, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 700,
                      textDecoration: isSkipped ? 'line-through' : 'none',
                      color: isSkipped ? 'var(--color-text-muted)' : isCurrent ? 'var(--color-heading)' : 'var(--color-text)' }}>
          {label}
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{caption}</div>
      </div>
    </li>
  )
}

function RequestStepper({ steps = [] }) {
  if (!steps.length) return null
  return (
    <ol aria-label="Etapy obiegu" style={{
      listStyle: 'none', margin: '0 0 18px', padding: 0, display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8,
    }}>
      {steps.map((s, i) => <StepItem key={i} step={s} />)}
    </ol>
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
    { n: 4, label: nodeLabel('it_execute'), caption: 'Biuro Informatyki',  state: st(4) },
    { n: 5, label: statusLabel('completed'), caption: 'Powiadomienie HR',  state: st(5) },
  ]
}

// --- Prawa kolumna: Podsumowanie + Historia ---------------------------------
function SummaryBox({ rows = [] }) {
  if (!rows.length) return null
  return (
    <section aria-label="Podsumowanie" style={{ border: '1px solid var(--color-border)', borderRadius: 10,
                                                overflow: 'hidden', background: 'var(--color-card)' }}>
      <h2 style={{ margin: 0, background: 'var(--color-navy)', color: '#fff', padding: '10px 14px',
                   fontSize: 11, fontWeight: 800, letterSpacing: '.08em' }}>
        PODSUMOWANIE
      </h2>
      <dl style={{ margin: 0, padding: '8px 14px 10px' }}>
        {rows.map((r, i) => (
          <div key={i} style={{ display: 'flex', justifyContent: 'space-between', gap: 12,
                                padding: '5px 0', fontSize: 13 }}>
            <dt style={{ color: 'var(--color-text-muted)' }}>{r.label}</dt>
            <dd style={{ margin: 0, fontWeight: 700, textAlign: 'right' }}>{r.value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

function HistoryBox({ items = [], requestId, createdBy }) {
  // Gdy podano requestId — pobierz realną oś czasu kroków obiegu.
  const [steps, setSteps] = useState(null)
  // Zdarzenia poza krokami obiegu: zapis roboczy, przejęcie, oddanie.
  const [events, setEvents] = useState([])
  useEffect(() => {
    if (!requestId) { setSteps(null); setEvents([]); return }
    let alive = true
    getRequestWorkflow(requestId)
      .then(r => {
        if (!alive) return
        setSteps(r.data?.steps || [])
        setEvents(Array.isArray(r.data?.events) ? r.data.events : [])
      })
      .catch(() => { if (alive) { setSteps([]); setEvents([]) } })
    return () => { alive = false }
  }, [requestId])

  // Wpis historii z kroku obiegu.
  function stepRow(s) {
    const sub = fmtDateTimeShort(s.created_at)
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
  }

  // Buduj wpisy: z kroków obiegu (gdy są) albo z przekazanych items.
  let rows = items
  if (requestId && steps) {
    const stepRows = steps.map(s => ({ at: s.created_at, row: stepRow(s) }))
    const eventRows = events.map(ev => ({
      at: ev.at,
      row: {
        text: `${ev.actor_name ? ev.actor_name + ' ' : ''}${ACTION_VERB[ev.action] || ev.action}`,
        sub: fmtDateTimeShort(ev.at),
      },
    }))
    // Jedna oś czasu; przy równym czasie (lub braku daty) zachowaj kolejność wejścia.
    const ts = (x) => serverTs(x)?.getTime() ?? Number.POSITIVE_INFINITY
    rows = [...stepRows, ...eventRows]
      .map((x, i) => ({ ...x, i }))
      .sort((a, b) => (ts(a.at) - ts(b.at)) || (a.i - b.i))
      .map(x => x.row)
  }


  return (
    <section aria-label="Historia" style={{ border: '1px solid var(--color-border)', borderRadius: 10,
                                            padding: '12px 14px', background: 'var(--color-card)' }}>
      <h2 style={{ margin: '0 0 10px', fontSize: 11, fontWeight: 800, letterSpacing: '.08em',
                   color: 'var(--color-text-muted)' }}>HISTORIA</h2>
      {requestId && steps === null ? (
        <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Ładowanie…</div>
      ) : rows.length === 0 ? (
        <div style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
          {requestId ? 'Brak kroków w obiegu.' : 'Wniosek nie został jeszcze wysłany.'}
        </div>
      ) : (
        <ol style={{ listStyle: 'none', margin: 0, padding: 0, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {rows.map((it, i) => (
            <li key={i} style={{ display: 'flex', gap: 9, fontSize: 13 }}>
              <span aria-hidden="true" style={{ flexShrink: 0, width: 9, height: 9, borderRadius: '50%', marginTop: 5,
                             boxSizing: 'border-box',
                             border: it.skipped ? '1.5px dashed var(--color-text-muted)' : 'none',
                             background: it.skipped ? 'transparent'
                               : it.muted ? 'var(--color-error)' : 'var(--color-success)' }} />
              <div style={{ minWidth: 0 }}>
                <div style={{ color: (it.muted || it.skipped) ? 'var(--color-text-muted)' : 'inherit' }}>{it.text}</div>
                {it.sub && <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-muted)' }}>{it.sub}</div>}
                {it.comment && (
                  <div style={{ fontSize: 12, color: 'var(--color-text-muted)', fontStyle: 'italic' }}>
                    „{it.comment}”
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

// --- Główny szkielet ---------------------------------------------------------
export default function RequestViewShell({
  icon: Icon, kind, kindLabel, statusText, title, subtitle,
  backLabel = '← Wróć', onBack, steps = [],
  summary = [], history = [], historyRequestId, historyCreatedBy, footerLeft, footerActions, children,
  waiting, perspective,
}) {
  // Otwarcie widoku: fokus na tytule (czytnik ekranu ogłasza nowy „ekran”),
  // chyba że widok sam ustawił go już w środku (np. autoFocus pola formularza).
  const rootRef = useRef(null)
  const titleRef = useRef(null)
  useEffect(() => {
    if (rootRef.current && !rootRef.current.contains(document.activeElement)) {
      titleRef.current?.focus({ preventScroll: true })
    }
  }, [])
  return (
    <div ref={rootRef}>
      {/* Przyciski w stopce karty wg projektu: wysokość 44 px, tekst 14 px. */}
      {/* Stopka przyklejona do dołu ekranu (zawsze widoczne akcje, także na telefonie). */}
      <style>{'.rv-footer .btn{min-height:44px;font-size:14px;padding:0 16px;border-radius:8px}'
        + '.rv-footer{position:sticky;bottom:0;z-index:5;background:var(--color-card);'
        + 'margin-left:-22px;margin-right:-22px;padding-left:22px;padding-right:22px;padding-bottom:14px;'
        + 'box-shadow:0 -6px 14px -10px rgba(13,20,36,.25)}'
        + '@media (max-width:600px){.rv-footer>div:last-child{width:100%}.rv-footer>div:last-child .btn{flex:1 1 auto}'
        + '.rv-head-back{width:100%}}'
        + '.rv-title{display:inline-block;max-width:100%}'
        + '.rv-title:focus{outline:none}.rv-title:focus-visible{outline:2px solid var(--color-focus-ring);outline-offset:2px;border-radius:4px}'}</style>
      {/* Nagłówek */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 16, flexWrap: 'wrap' }}>
        {Icon && (
          <div style={{ flexShrink: 0, width: 44, height: 44, borderRadius: 10,
                        background: 'var(--color-navy)', color: 'var(--color-gold)',
                        display: 'grid', placeItems: 'center' }}>
            <Icon size={20} aria-hidden="true" />
          </div>
        )}
        <div style={{ flex: 1, minWidth: 240 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            {kindLabel && <KindBadge kind={kind} label={kindLabel} />}
            {perspective && (
              <span style={{ padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 700,
                             background: 'var(--color-info-bg)', color: 'var(--color-info-text)' }}>{perspective}</span>
            )}
            {statusText && <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>{statusText}</span>}
          </div>
          <h1 ref={titleRef} tabIndex={-1} className="rv-title" style={{ margin: '2px 0 0', fontSize: 24, fontWeight: 800, color: 'var(--color-heading)' }}>{title}</h1>
          {subtitle && <p style={{ margin: '2px 0 0', fontSize: 14, color: 'var(--color-text-muted)' }}>{subtitle}</p>}
          {waiting && (
            <p style={{ margin: '6px 0 0', fontSize: 13, fontWeight: 600, color: 'var(--color-warning-text)' }}>{waiting}</p>
          )}
        </div>
        <button type="button" className="btn btn--ghost rv-head-back" style={{ minHeight: 44 }} onClick={onBack}>{backLabel}</button>
      </div>

      <RequestStepper steps={steps} />

      {/* Dwie kolumny */}
      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
        {/* Duży flex-grow treści: w jednym wierszu panel boczny zostaje ~300 px,
            a po zawinięciu (wąski ekran) rozciąga się na całą szerokość. */}
        <div style={{ flex: '999 1 560px', minWidth: 0 }}>
          <div className="card" style={{ padding: 22 }}>
            {children}
            {(footerLeft || footerActions) && (
              <div className="rv-footer" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                            gap: 10, flexWrap: 'wrap', marginTop: 22,
                            borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
                <div style={{ fontSize: 13, color: 'var(--color-text-muted)', flex: '1 1 auto' }}>{footerLeft}</div>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>{footerActions}</div>
              </div>
            )}
          </div>
        </div>
        {(summary.length > 0 || history.length >= 0) && (
          <aside style={{ flex: '1 1 300px', maxWidth: '100%', display: 'flex',
                          flexDirection: 'column', gap: 12 }}>
            <SummaryBox rows={summary} />
            <HistoryBox items={history} requestId={historyRequestId} createdBy={historyCreatedBy} />
          </aside>
        )}
      </div>
    </div>
  )
}
