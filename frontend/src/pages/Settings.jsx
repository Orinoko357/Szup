import { useEffect, useId, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Mail, ShieldCheck, TestTube, AlertTriangle, FileText, Camera, Bell } from 'lucide-react'
import {
  getEmailSettings, updateEmailSettings, testEmail,
  getLdapSettings, updateLdapSettings, testLdap,
  getAppSettings, updateAppSettings, factoryReset,
  listNotificationTemplates, saveNotificationTemplate,
  resetNotificationTemplate, testNotificationTemplate,
 errorMessage} from '../api'
import { toast, ask } from '../components/ui/feedback'
import { getUserRoles } from '../roles'
import { ErrorAlert, LoadError } from '../components/ui/LoadState'


// v3.0 — sekcja ustawień jako karta z nagłówkiem-przyciskiem (ikona w kafelku,
// tytuł z odznaką stanu, opis pod spodem, strzałka). `danger` = strefa niebezpieczna.
function badgeTone(badge) {
  const b = String(badge)
  if (b === 'ON') return ['var(--color-success-bg)', 'var(--color-success-text)']
  if (b.includes('OFF') || b === 'domyślne') return ['var(--color-neutral-bg)', 'var(--color-neutral-text)']
  return ['var(--color-info-bg)', 'var(--color-info-text)']
}

function Accordion({ icon: Icon, title, sub, badge, defaultOpen = false, danger = false, children }) {
  const [open, setOpen] = useState(defaultOpen)
  const tone = badge != null ? badgeTone(badge) : null
  return (
    <section style={{ background: 'var(--color-card)', border: '1px solid var(--color-border)',
                      borderRadius: 10, overflow: 'hidden', marginBottom: 14 }}>
      <button type="button" aria-expanded={open} onClick={() => setOpen(v => !v)}
              style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 12, minHeight: 64,
                       padding: '10px 18px', border: 0, borderBottom: open ? '1px solid var(--color-border)' : 0,
                       background: 'var(--color-card)', font: 'inherit', color: 'inherit', cursor: 'pointer',
                       textAlign: 'left' }}>
        {Icon && (
          <span aria-hidden="true" style={{
            width: 34, height: 34, flexShrink: 0, borderRadius: 8, display: 'grid', placeItems: 'center',
            background: danger ? 'var(--color-error-bg)' : 'var(--bg-secondary)',
            color: danger ? 'var(--color-error-text)' : 'var(--color-heading)',
          }}>
            <Icon size={17} />
          </span>
        )}
        <span style={{ flex: 1, minWidth: 0 }}>
          <span style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
            <strong style={{ fontSize: 16, color: danger ? 'var(--color-error-text)' : 'var(--color-heading)' }}>{title}</strong>
            {tone && (
              <span style={{ padding: '1px 8px', borderRadius: 10, fontSize: 11, fontWeight: 800,
                             background: tone[0], color: tone[1] }}>{badge}</span>
            )}
          </span>
          {sub && <span style={{ display: 'block', fontSize: 13, color: 'var(--color-text-muted)' }}>{sub}</span>}
        </span>
        {open
          ? <ChevronDown size={18} aria-hidden="true" style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
          : <ChevronRight size={18} aria-hidden="true" style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />}
      </button>
      {open && <div style={{ padding: '18px 20px' }}>{children}</div>}
    </section>
  )
}

export default function Settings() {
  const [email, setEmail] = useState(null)
  const [emailSaving, setEmailSaving] = useState(false)
  const [emailTestResult, setEmailTestResult] = useState(null)
  const [emailTesting, setEmailTesting] = useState(false)

  const [ldap, setLdap] = useState(null)
  const [ldapBindPassword, setLdapBindPassword] = useState('')
  const [ldapSaving, setLdapSaving] = useState(false)
  const [ldapTestResult, setLdapTestResult] = useState(null)
  const [ldapTesting, setLdapTesting] = useState(false)

  const [app, setApp] = useState(null)
  const [appSaving, setAppSaving] = useState(false)
  const [helpdesk, setHelpdesk] = useState('')
  const [declText, setDeclText] = useState('')
  const [declIsDefault, setDeclIsDefault] = useState(true)
  const [declSaving, setDeclSaving] = useState(false)
  const [snap, setSnap] = useState({ enabled: true, hour: 23, minute: 50, envDisabled: false })
  const [snapSaving, setSnapSaving] = useState(false)

  // Reset fabryczny widoczny WYŁĄCZNIE dla superadmina (backend i tak egzekwuje).
  const isSuperadmin = getUserRoles().includes('superadmin')

  // Błąd wczytania sekcji jest widoczny, a jej formularz się nie pokazuje —
  // nie da się więc zapisać wartości domyślnych na prawdziwą konfigurację.
  const [loadErr, setLoadErr] = useState({})
  const failLoad = (key) => (ex) =>
    setLoadErr(e => ({ ...e, [key]: errorMessage(ex, 'Nie udało się wczytać ustawień.') }))
  function loadAll() {
    setLoadErr({})
    getEmailSettings().then(r => setEmail({ ...r.data, smtp_password: '' })).catch(failLoad('email'))
    getLdapSettings().then(r => setLdap(r.data)).catch(failLoad('ldap'))
    getAppSettings().then(r => {
      setApp(r.data)
      setHelpdesk(r.data.helpdesk_email || '')
      setDeclText(r.data.declaration_text || '')
      setDeclIsDefault(!!r.data.declaration_is_default)
      setSnap({
        enabled: r.data.snapshot_enabled !== false,
        hour: r.data.snapshot_hour ?? 23,
        minute: r.data.snapshot_minute ?? 50,
        envDisabled: !!r.data.snapshot_env_disabled,
      })
    }).catch(failLoad('app'))
  }
  useEffect(() => { loadAll() }, [])
  const loadError = (k) => loadErr[k] ? (
    <div className="alert alert--error" role="alert" style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 10 }}>
      <span style={{ flex: 1 }}>{loadErr[k]} Zapis tej sekcji jest zablokowany do czasu wczytania danych.</span>
      <button type="button" className="btn btn--ghost btn--sm" onClick={loadAll}>Spróbuj ponownie</button>
    </div>
  ) : null

  async function saveSnapshotSchedule() {
    setSnapSaving(true)
    try {
      const r = await updateAppSettings({
        test_mode: !!app?.test_mode,
        helpdesk_email: app?.helpdesk_email || null,
        snapshot_enabled: snap.enabled,
        snapshot_hour: Number(snap.hour),
        snapshot_minute: Number(snap.minute),
      })
      setApp(r.data)
      setSnap(s => ({
        ...s,
        enabled: r.data.snapshot_enabled !== false,
        hour: r.data.snapshot_hour ?? 23,
        minute: r.data.snapshot_minute ?? 50,
      }))
      toast('Zapisano harmonogram migawek')
    } catch (ex) {
      toast(errorMessage(ex, 'Nie udało się zapisać harmonogramu migawek'), { tone: 'error' })
    } finally { setSnapSaving(false) }
  }

  async function saveDeclaration() {
    setDeclSaving(true)
    try {
      const r = await updateAppSettings({
        test_mode: !!app?.test_mode,
        helpdesk_email: app?.helpdesk_email || null,
        declaration_text: declText,
      })
      setApp(r.data)
      setDeclText(r.data.declaration_text || '')
      setDeclIsDefault(!!r.data.declaration_is_default)
      toast('Zapisano treść oświadczenia')
    } catch (ex) {
      toast(errorMessage(ex, 'Nie udało się zapisać treści oświadczenia'), { tone: 'error' })
    } finally { setDeclSaving(false) }
  }

  async function toggleTestMode(enabled) {
    if (enabled) {
      const ok = await ask(
        'UWAGA: Tryb testowy pozwala zalogować się DOWOLNEMU użytkownikowi bez podania hasła.\n\n' +
        'To jest WYŁĄCZNIE do testów przepływu wniosków na środowisku nieprodukcyjnym.\n' +
        'Każde takie logowanie jest rejestrowane jako security event.\n\n' +
        'Czy na pewno włączyć tryb testowy?',
        { title: 'Włączyć tryb testowy?', confirmLabel: 'Włącz tryb testowy', danger: true }
      )
      if (!ok) return
    }
    setAppSaving(true)
    try {
      // PUT zastępuje cały rekord — przekazujemy też adres helpdesku,
      // żeby przełącznik trybu testowego go nie skasował.
      const r = await updateAppSettings({
        test_mode: enabled,
        helpdesk_email: app?.helpdesk_email || null,
      })
      setApp(r.data)
      toast(enabled ? 'Tryb testowy włączony' : 'Tryb testowy wyłączony', { tone: enabled ? 'warning' : 'success' })
    } catch (ex) {
      toast(errorMessage(ex, 'Nie udało się zmienić trybu testowego'), { tone: 'error' })
    } finally { setAppSaving(false) }
  }

  async function saveHelpdesk() {
    setAppSaving(true)
    try {
      const r = await updateAppSettings({
        test_mode: !!app?.test_mode,
        helpdesk_email: (helpdesk || '').trim() || null,
      })
      setApp(r.data)
      setHelpdesk(r.data.helpdesk_email || '')
      toast('Zapisano adres helpdesku')
    } catch (ex) {
      toast(errorMessage(ex, 'Nie udało się zapisać adresu helpdesku'), { tone: 'error' })
    } finally { setAppSaving(false) }
  }

  async function saveEmail(e) {
    e.preventDefault()
    setEmailSaving(true); setEmailTestResult(null)
    try {
      const data = { ...email }
      if (!data.smtp_password) delete data.smtp_password
      const r = await updateEmailSettings(data)
      toast('Zapisano ustawienia e-mail')
      // Zmiana serwera lub użytkownika SMTP czyści zapisane hasło — backend
      // zwraca wtedy ostrzeżenie, że trzeba je wpisać ponownie.
      if (r.data?.warning) toast(r.data.warning, { tone: 'warning' })
    } catch (ex) { toast(errorMessage(ex, 'Nie udało się zapisać ustawień e-mail'), { tone: 'error' }) }
    finally { setEmailSaving(false) }
  }

  async function handleTestEmail() {
    setEmailTesting(true); setEmailTestResult(null)
    try {
      // Backend zwraca { ok, error } — mapujemy na { success, message },
      // których używa render (inaczej nawet sukces wyglądał jak pusty błąd).
      const r = await testEmail()
      setEmailTestResult({
        success: !!r.data?.ok,
        message: r.data?.ok
          ? (r.data?.sent_to ? `Wiadomość testowa wysłana na ${r.data.sent_to}.` : '')
          : (r.data?.error || ''),
      })
    } catch (ex) {
      setEmailTestResult({ success: false, message: errorMessage(ex, 'Błąd wysyłki') })
    } finally { setEmailTesting(false) }
  }

  async function saveLdap(e) {
    e.preventDefault()
    setLdapSaving(true); setLdapTestResult(null)
    try {
      const r = await updateLdapSettings({ ...ldap, bind_password: ldapBindPassword || null })
      setLdapBindPassword('')
      if (r.data) setLdap(l => ({ ...l, ...r.data }))
      toast('Zapisano ustawienia AD/LDAP')
      // Zmiana serwera lub konta usługowego czyści zapisane hasło bind.
      if (r.data?.warning) toast(r.data.warning, { tone: 'warning' })
    } catch (ex) { toast(errorMessage(ex, 'Nie udało się zapisać ustawień AD/LDAP'), { tone: 'error' }) }
    finally { setLdapSaving(false) }
  }

  async function handleTestLdap() {
    setLdapTesting(true); setLdapTestResult(null)
    try {
      const r = await testLdap(); setLdapTestResult(r.data)
      // np. połączenie bez weryfikacji certyfikatu — backend dokłada ostrzeżenie
      if (r.data?.warning) toast(r.data.warning, { tone: 'warning' })
    }
    catch (ex) { setLdapTestResult({ success: false, message: errorMessage(ex, 'Błąd połączenia') }) }
    finally { setLdapTesting(false) }
  }

  const setE = (k, v) => setEmail(em => ({ ...em, [k]: v }))
  const setL = (k, v) => setLdap(l => ({ ...l, [k]: v }))

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-header__title">Ustawienia</h1>
          <div className="page-header__sub">Konfiguracja powiadomień e-mail i integracji AD/LDAP</div>
        </div>
      </div>

      <Accordion icon={Mail} title="Powiadomienia e-mail" sub="Powiadomienia o wnioskach dla pracowników i kierowników"
                 badge={email?.enabled ? 'ON' : 'OFF'} defaultOpen>
        {loadError('email')}
        {email && (
          <form onSubmit={saveEmail}>
            <label className="form-check" style={{ marginBottom: 16 }}>
              <input type="checkbox" checked={email.enabled}
                     onChange={e => setE('enabled', e.target.checked)} />
              Włącz powiadomienia e-mail
            </label>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label" htmlFor="set-smtp-host">Serwer SMTP</label>
                <input id="set-smtp-host" className="form-control" value={email.smtp_host || ''}
                       onChange={e => setE('smtp_host', e.target.value)} placeholder="smtp.firma.local" />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="set-smtp-port">Port SMTP</label>
                <input id="set-smtp-port" className="form-control" type="number" value={email.smtp_port || 587}
                       onChange={e => setE('smtp_port', parseInt(e.target.value))} />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label" htmlFor="set-smtp-user">Użytkownik SMTP</label>
                <input id="set-smtp-user" className="form-control" value={email.smtp_user || ''}
                       onChange={e => setE('smtp_user', e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="set-smtp-pass">
                  Hasło SMTP {email.has_password && <span className="badge badge--neutral" style={{ fontSize: 10, marginLeft: 6 }}>Ustawione</span>}
                </label>
                <input id="set-smtp-pass" className="form-control" type="password" value={email.smtp_password || ''}
                       onChange={e => setE('smtp_password', e.target.value)}
                       placeholder={email.has_password ? 'Pozostaw puste, by nie zmieniać' : ''}
                       autoComplete="new-password" />
              </div>
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label" htmlFor="set-smtp-from">Nadawca (From)</label>
                <input id="set-smtp-from" className="form-control" type="email" value={email.from_address || ''}
                       onChange={e => setE('from_address', e.target.value)}
                       placeholder="szup@firma.local" />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="set-smtp-cc">Domyślny odbiorca CC (opcjonalny)</label>
                <input id="set-smtp-cc" className="form-control" type="email" value={email.to_address || ''}
                       onChange={e => setE('to_address', e.target.value)}
                       placeholder="it@firma.local" />
              </div>
            </div>
            <label className="form-check" style={{ marginBottom: 8 }}>
              <input type="checkbox" checked={email.use_tls ?? true}
                     onChange={e => setE('use_tls', e.target.checked)} />
              Użyj STARTTLS
            </label>
            <label className="form-check" style={{ marginBottom: 4 }}>
              <input type="checkbox" checked={email.sender_as_actor ?? true}
                     onChange={e => setE('sender_as_actor', e.target.checked)} />
              Pokazuj jako nadawcę osobę, która wywołała zdarzenie
            </label>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: '0 0 16px 26px' }}>
              Powiadomienie w skrzynce adresata wygląda, jakby przyszło od wnioskodawcy
              (nagłówek „Od" = jego adres z domeny), a odpowiedź trafia wprost do niego.
              Wysyłką technicznie zajmuje się serwer aplikacji. Wyłącz, jeśli serwer SMTP
              odrzuca wiadomości z cudzym adresem nadawcy.
            </div>
            {emailTestResult && (
              <div className="alert" style={{
                borderLeft: `4px solid ${emailTestResult.success ? 'var(--color-success)' : 'var(--color-error)'}`,
                background: emailTestResult.success ? 'var(--color-success-bg)' : 'var(--color-error-bg)',
                color: emailTestResult.success ? 'var(--color-success-text)' : 'var(--color-error)',
                marginBottom: 12,
              }}>
                {emailTestResult.success
                  ? (emailTestResult.message || 'Wiadomość testowa wysłana pomyślnie.')
                  : emailTestResult.message}
              </div>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" className="btn btn--primary" disabled={emailSaving}>
                {emailSaving ? 'Zapisywanie…' : 'Zapisz ustawienia e-mail'}
              </button>
              <button type="button" className="btn btn--ghost" onClick={handleTestEmail} disabled={emailTesting}>
                <TestTube size={14} /> {emailTesting ? 'Wysyłanie…' : 'Wyślij e-mail testowy'}
              </button>
            </div>
          </form>
        )}
      </Accordion>

      <Accordion icon={Mail} title="Powiadomienia obiegu"
                 sub="Skrzynka helpdesku IT — zgłoszenia wniosków do realizacji">
        {loadError('app')}
        {app && (
          <div>
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 10 }}>
              Gdy wniosek trafia do realizacji przez IT, system wysyła na ten adres
              zgłoszenie z informacją, kto i dla kogo wnioskuje o uprawnienia.
              Powiadomienia imienne do pracowników IT nie są wysyłane.
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="set-helpdesk">Adres e-mail helpdesku IT</label>
              <input id="set-helpdesk"
                className="form-control"
                type="email"
                placeholder={app.helpdesk_email_effective || 'helpdesk@…'}
                value={helpdesk}
                onChange={e => setHelpdesk(e.target.value)}
              />
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                Puste pole = adres domyślny z konfiguracji wdrożenia
                {app.helpdesk_email_effective && (
                  <> (<strong>{app.helpdesk_email_effective}</strong>)</>
                )}.
              </div>
            </div>
            <button className="btn btn--primary" onClick={saveHelpdesk} disabled={appSaving}>
              {appSaving ? 'Zapisywanie…' : 'Zapisz adres helpdesku'}
            </button>
          </div>
        )}
      </Accordion>

      <Accordion icon={Bell} title="Treść powiadomień (szablony)"
                 sub="Edytuj temat i treść e-maili; użyj makr w nawiasach klamrowych">
        <NotificationsSection />
      </Accordion>

      <Accordion icon={FileText} title="Oświadczenie wnioskującego"
                 sub="Treść podpisywana przy kierowaniu wniosku do realizacji IT"
                 badge={declIsDefault ? 'domyślne' : 'własne'}>
        {loadError('app')}
        {app && (
          <div>
            <div className="alert alert--info" style={{ fontSize: 12.5, marginBottom: 12 }}>
              Ta treść pojawia się do podpisania, gdy wniosek <strong>nadający uprawnienia</strong>
              {' '}trafia do realizacji IT. <strong>Zmiana nie działa wstecz</strong> — już
              złożone oświadczenia zachowują swoją pierwotną treść.
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="set-declaration">Treść oświadczenia</label>
              <textarea id="set-declaration" className="form-control"
                        style={{ minHeight: 320, fontSize: 13, lineHeight: 1.5,
                                 fontFamily: 'inherit' }}
                        value={declText}
                        onChange={e => setDeclText(e.target.value)} />
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                Puste pole = powrót do treści domyślnej. {declIsDefault
                  ? 'Obecnie używana jest treść domyślna.'
                  : 'Obecnie używana jest treść własna.'}
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button className="btn btn--primary" onClick={saveDeclaration} disabled={declSaving}>
                {declSaving ? 'Zapisywanie…' : 'Zapisz treść oświadczenia'}
              </button>
              {!declIsDefault && (
                <button className="btn btn--ghost" onClick={() => setDeclText('')} disabled={declSaving}
                        title="Wyczyść, aby wrócić do treści domyślnej (zapisz, by zatwierdzić)">
                  Przywróć domyślną
                </button>
              )}
            </div>
          </div>
        )}
      </Accordion>

      <Accordion icon={Camera} title="Migawki uprawnień (harmonogram)"
                 sub="Nocne zestawienie „kto co ma” — pora i włącznik"
                 badge={snap.envDisabled ? 'ENV OFF' : (snap.enabled ? `${String(snap.hour).padStart(2,'0')}:${String(snap.minute).padStart(2,'0')}` : 'OFF')}>
        {loadError('app')}
        {app && (
          <div>
            {snap.envDisabled && (
              <div className="alert alert--warning" style={{ fontSize: 12.5, marginBottom: 12 }}>
                Harmonogram jest wyłączony zmienną środowiskową <code>SZUP_SNAPSHOTS=0</code>
                {' '}(twardy wyłącznik). Ustawienia poniżej zapiszą się, ale zadziałają dopiero
                po usunięciu tej zmiennej i restarcie usługi. Ręczne „Generuj teraz" w rejestrze
                działa niezależnie.
              </div>
            )}
            <div className="alert alert--info" style={{ fontSize: 12.5, marginBottom: 12 }}>
              Codziennie o wybranej porze system zapisuje niezmienną migawkę stanu upoważnień
              wszystkich osób (retencja ≥ 5 lat). Zmiana działa <strong>bez restartu</strong>.
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 14, cursor: 'pointer', marginBottom: 12 }}>
              <input type="checkbox" checked={snap.enabled}
                     onChange={e => setSnap(s => ({ ...s, enabled: e.target.checked }))} />
              Harmonogram włączony
            </label>
            <div className="form-row" style={{ maxWidth: 320 }}>
              <div className="form-group">
                <label className="form-label" htmlFor="set-snap-hour">Godzina</label>
                <input id="set-snap-hour" className="form-control" type="number" min={0} max={23}
                       value={snap.hour} disabled={!snap.enabled}
                       onChange={e => setSnap(s => ({ ...s, hour: e.target.value }))} />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="set-snap-minute">Minuta</label>
                <input id="set-snap-minute" className="form-control" type="number" min={0} max={59}
                       value={snap.minute} disabled={!snap.enabled}
                       onChange={e => setSnap(s => ({ ...s, minute: e.target.value }))} />
              </div>
            </div>
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: '2px 0 12px' }}>
              Czas lokalny serwera. Migawka dotyczy dnia jej wykonania.
            </div>
            <button className="btn btn--primary" onClick={saveSnapshotSchedule} disabled={snapSaving}>
              {snapSaving ? 'Zapisywanie…' : 'Zapisz harmonogram'}
            </button>
          </div>
        )}
      </Accordion>

      <Accordion icon={AlertTriangle} title="Tryb testowy" sub="Logowanie samym loginem (bez hasła) — tylko do testów"
                 badge={app?.test_mode ? 'ON' : 'OFF'}>
        {loadError('app')}
        {app && (
          <div>
            <div className="alert" style={{
              borderLeft: '4px solid var(--color-error)',
              background: 'var(--color-error-bg)',
              color: 'var(--color-error)',
              marginBottom: 14,
              fontSize: 13,
            }}>
              <strong>Uwaga!</strong> Gdy tryb testowy jest włączony, każdy może zalogować się do systemu
              podając wyłącznie istniejący login — bez hasła i bez AD. Funkcja służy WYŁĄCZNIE do testów
              workflow na środowisku nieprodukcyjnym. Każde takie logowanie jest rejestrowane jako
              security event o wysokim priorytecie.
            </div>
            <label className="form-check" style={{ marginBottom: 12 }}>
              <input
                type="checkbox"
                checked={!!app.test_mode}
                onChange={e => toggleTestMode(e.target.checked)}
                disabled={appSaving}
              />
              Włącz tryb testowy (logowanie samym loginem)
            </label>
          </div>
        )}
      </Accordion>

      <Accordion icon={ShieldCheck} title="Active Directory / LDAP" sub="Logowanie przez konto domenowe"
                 badge={ldap?.enabled ? 'ON' : 'OFF'}>
        {loadError('ldap')}
        {ldap && (
          <form onSubmit={saveLdap}>
            <label className="form-check" style={{ marginBottom: 16 }}>
              <input type="checkbox" checked={ldap.enabled}
                     onChange={e => setL('enabled', e.target.checked)} />
              Włącz logowanie przez AD/LDAP
            </label>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label" htmlFor="set-ldap-host">Serwer LDAP / AD</label>
                <input id="set-ldap-host" className="form-control" value={ldap.host || ''}
                       onChange={e => setL('host', e.target.value)}
                       placeholder="192.168.1.10 lub dc.firma.local" />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="set-ldap-port">Port</label>
                <input id="set-ldap-port" className="form-control" type="number" value={ldap.port || 389}
                       onChange={e => setL('port', parseInt(e.target.value))} />
              </div>
            </div>
            <label className="form-check" style={{ marginBottom: 8 }}>
              <input type="checkbox" checked={ldap.use_ssl ?? false}
                     onChange={e => { setL('use_ssl', e.target.checked); if (e.target.checked) setL('use_starttls', false) }} />
              Użyj SSL (LDAPS, port 636)
            </label>
            {/* v3.8 — szyfrowanie i weryfikacja certyfikatu serwera AD. STARTTLS
                (port 389) i LDAPS wykluczają się. */}
            <label className="form-check" style={{ marginBottom: 8 }}>
              <input type="checkbox" checked={!!ldap.use_starttls} disabled={!!ldap.use_ssl}
                     aria-describedby="set-ldap-starttls-hint"
                     onChange={e => setL('use_starttls', e.target.checked)} />
              STARTTLS
            </label>
            <div id="set-ldap-starttls-hint" style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: '-4px 0 10px 24px' }}>
              Szyfrowanie zwykłego połączenia (port 389). Nie łączy się z LDAPS.
            </div>
            {/* Szyfrowanie jest zalecane, nie wymagane — połączenie bez LDAPS/STARTTLS
                jest dozwolone (lista kontrolna pokazuje je jako zalecenie). */}
            <div className="form-hint" style={{ margin: '0 0 10px' }}>
              Zalecane: LDAPS lub STARTTLS z weryfikacją certyfikatu
            </div>
            <label className="form-check" style={{ marginBottom: 8 }}>
              <input type="checkbox" checked={ldap.tls_verify ?? true}
                     onChange={e => setL('tls_verify', e.target.checked)} />
              Weryfikuj certyfikat serwera (zalecane)
            </label>
            {(ldap.tls_verify ?? true) === false && (
              <div className="alert alert--warning" role="status" style={{ marginBottom: 10, fontSize: 12 }}>
                Bez weryfikacji certyfikatu połączenie można przechwycić (podszycie się pod kontroler domeny)
                — hasła logujących się osób mogą wyciec. Wyłączaj tylko na czas diagnozy.
              </div>
            )}
            <div className="form-group">
              <label className="form-label" htmlFor="set-ldap-ca">Plik CA (ścieżka na serwerze)</label>
              <input id="set-ldap-ca" className="form-control" value={ldap.ca_cert_file || ''}
                     onChange={e => setL('ca_cert_file', e.target.value)}
                     aria-describedby="set-ldap-ca-hint"
                     placeholder="/etc/ssl/certs/urzad-ca.pem" />
              <div id="set-ldap-ca-hint" style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                Certyfikat urzędu certyfikacji domeny (PEM) — gdy serwer AD ma certyfikat z wewnętrznego CA.
                Puste = systemowy magazyn certyfikatów.
              </div>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="set-ldap-base">Kontener bazowy (Base DN)</label>
              <input id="set-ldap-base" className="form-control" value={ldap.base_dn || ''}
                     onChange={e => setL('base_dn', e.target.value)}
                     placeholder="DC=firma,DC=local" />
            </div>
            <div className="form-row">
              <div className="form-group">
                <label className="form-label" htmlFor="set-ldap-bind">Konto usługowe (Bind DN)</label>
                <input id="set-ldap-bind" className="form-control" value={ldap.bind_dn || ''}
                       onChange={e => setL('bind_dn', e.target.value)}
                       placeholder="CN=svc-szup,OU=Service,DC=firma,DC=local" />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="set-ldap-pass">
                  Hasło konta usługowego
                  {ldap.has_bind_password && <span className="badge badge--neutral" style={{ fontSize: 10, marginLeft: 6 }}>Ustawione</span>}
                </label>
                <input id="set-ldap-pass" className="form-control" type="password" value={ldapBindPassword}
                       onChange={e => setLdapBindPassword(e.target.value)}
                       placeholder={ldap.has_bind_password ? 'Pozostaw puste, by nie zmieniać' : ''}
                       autoComplete="new-password" />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="set-ldap-usersbase">Baza wyszukiwania użytkowników (opcjonalnie)</label>
              <input id="set-ldap-usersbase" className="form-control" value={ldap.user_search_base || ''}
                     onChange={e => setL('user_search_base', e.target.value)}
                     placeholder="OU=Users,DC=firma,DC=local (domyślnie: Base DN)" />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="set-ldap-filter">Filtr użytkownika</label>
              <input id="set-ldap-filter" className="form-control" value={ldap.user_filter || ''}
                     onChange={e => setL('user_filter', e.target.value)} />
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                {'{username}'} zostanie zastąpione loginem wpisanym przez użytkownika
              </div>
            </div>
            <div className="form-group" style={{ borderTop: '1px solid var(--color-border)', paddingTop: 12 }}>
              <label className="form-check" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="checkbox" checked={!!ldap.sso_enabled}
                       onChange={e => setL('sso_enabled', e.target.checked)} />
                Logowanie poświadczeniami Windows (SSO / Kerberos)
              </label>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
                Wymaga konfiguracji Apache (mod_auth_gssapi) + keytaba na serwerze.
                Nie włączaj, zanim Apache nie jest skonfigurowany — przycisk nie zadziała.
              </div>
              <label className="form-check" style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8 }}>
                <input type="checkbox" checked={!!ldap.sso_auto} disabled={!ldap.sso_enabled}
                       onChange={e => setL('sso_auto', e.target.checked)} />
                Próbuj SSO automatycznie przy wejściu (bez klikania)
              </label>
            </div>
            {ldapTestResult && (
              <div className="alert" style={{
                borderLeft: `4px solid ${ldapTestResult.success ? 'var(--color-success)' : 'var(--color-error)'}`,
                background: ldapTestResult.success ? 'var(--color-success-bg)' : 'var(--color-error-bg)',
                color: ldapTestResult.success ? 'var(--color-success-text)' : 'var(--color-error)',
                marginBottom: 12,
              }}>
                {ldapTestResult.success ? 'Połączono z domeną pomyślnie.' : ldapTestResult.message}
              </div>
            )}
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" className="btn btn--primary" disabled={ldapSaving}>
                {ldapSaving ? 'Zapisywanie…' : 'Zapisz ustawienia AD/LDAP'}
              </button>
              <button type="button" className="btn btn--ghost" onClick={handleTestLdap} disabled={ldapTesting}>
                <TestTube size={14} /> {ldapTesting ? 'Testowanie…' : 'Testuj połączenie z domeną'}
              </button>
            </div>
          </form>
        )}
      </Accordion>

      {isSuperadmin && <FactoryResetSection />}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Strefa niebezpieczna — reset do ustawień fabrycznych (tylko superadmin)
// ---------------------------------------------------------------------------

function FactoryResetSection() {
  const [opts, setOpts] = useState({
    wipe_requests: true, wipe_structure: true, wipe_users: true,
    wipe_software: false, wipe_audit: false,
  })
  const [password, setPassword] = useState('')
  const [confirm, setConfirm]   = useState('')
  const [busy, setBusy]         = useState(false)
  const [err, setErr]           = useState(null)
  const [result, setResult]     = useState(null)

  function setOpt(k, v) {
    setOpts(prev => {
      const next = { ...prev, [k]: v }
      // Zależności wymuszane też przez backend — pokaż je od razu w UI.
      if ((k === 'wipe_users' || k === 'wipe_software') && v) next.wipe_requests = true
      if (k === 'wipe_requests' && !v) { next.wipe_users = false; next.wipe_software = false }
      return next
    })
  }

  async function doReset() {
    setErr(null)
    if (confirm.trim() !== 'RESET') { setErr('Wpisz dokładnie: RESET'); return }
    if (!password) { setErr('Podaj swoje hasło.'); return }
    const ok = await ask(
      'OSTATNIE OSTRZEŻENIE\n\n' +
      'Ta operacja jest NIEODWRACALNA i usunie wybrane dane z systemu.\n' +
      'Twoje konto superadmina zostanie zachowane.\n\n' +
      'Upewnij się, że masz kopię bazy danych.\n\nKontynuować?',
      { title: 'Ostatnie ostrzeżenie', confirmLabel: 'Przywróć ustawienia fabryczne', danger: true }
    )
    if (!ok) return
    setBusy(true)
    try {
      const r = await factoryReset({ password, confirm: confirm.trim(), ...opts })
      setResult(r.data)
      setPassword(''); setConfirm('')
    } catch (ex) {
      setErr(errorMessage(ex, 'Reset nie powiódł się'))
    } finally { setBusy(false) }
  }

  const row = (k, label, hint) => (
    <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 8, cursor: 'pointer' }}>
      <input type="checkbox" checked={opts[k]} onChange={e => setOpt(k, e.target.checked)}
             style={{ marginTop: 3 }} />
      <span>
        <span style={{ fontWeight: 600, fontSize: 13 }}>{label}</span>
        {hint && <span style={{ display: 'block', fontSize: 11, color: 'var(--color-text-muted)' }}>{hint}</span>}
      </span>
    </label>
  )

  return (
    <Accordion
      icon={AlertTriangle}
      title="Strefa niebezpieczna — reset do ustawień fabrycznych"
      sub="tylko superadmin"
      danger
    >
      <div className="alert" style={{
        background: 'var(--color-error-bg)', borderLeft: '4px solid var(--color-error)',
        color: 'var(--color-error)', marginBottom: 14,
      }}>
        <strong>Operacja nieodwracalna.</strong> Usuwa wybrane dane z systemu.
        Twoje konto superadmina zostaje zachowane, dzięki czemu zalogujesz się po resecie.
        Domyślne szablony obiegu i typy wniosków odtworzą się przy starcie backendu.
        <br />Przed wykonaniem zrób kopię bazy: <code>cp /opt/szup/data/szup.db szup.db.bak</code>
      </div>

      <div style={{ marginBottom: 14 }}>
        {row('wipe_requests', 'Wnioski', 'Wnioski, pozycje uprawnień, instancje i kroki obiegu')}
        {row('wipe_structure', 'Struktura organizacyjna', 'Jednostki, wydziały, zastępcy, przypisania jednostek HR')}
        {row('wipe_users', 'Użytkownicy', 'Wszystkie konta OPRÓCZ Twojego (wymaga czyszczenia wniosków)')}
        {row('wipe_software', 'Rejestr oprogramowania', 'Systemy i ich uprawnienia (wymaga czyszczenia wniosków)')}
        {row('wipe_audit', 'Dziennik zdarzeń i zdarzenia bezpieczeństwa', 'Historia audytowa — usuwaj tylko świadomie')}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 12 }}>
        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label" htmlFor="set-reset-pass">Twoje hasło</label>
          <input id="set-reset-pass" className="form-control" type="password" value={password}
                 autoComplete="current-password"
                 onChange={e => setPassword(e.target.value)} />
        </div>
        <div className="form-group" style={{ margin: 0 }}>
          <label className="form-label" htmlFor="set-reset-confirm">Wpisz: RESET</label>
          <input id="set-reset-confirm" className="form-control" value={confirm}
                 onChange={e => setConfirm(e.target.value)} placeholder="RESET" />
        </div>
      </div>

      <ErrorAlert style={{ marginBottom: 12 }}>{err}</ErrorAlert>

      {result && (
        <div className="alert" style={{
          background: 'var(--color-success-bg)', borderLeft: '4px solid var(--color-success)',
          color: 'var(--color-success-text)', marginBottom: 12,
        }}>
          <strong>Reset zakończony.</strong>
          <div style={{ marginTop: 6, fontSize: 12, fontFamily: 'var(--font-mono)' }}>
            {result.details.map((d, i) => <div key={i}>{d}</div>)}
          </div>
        </div>
      )}

      <button type="button" className="btn btn--danger"
              onClick={doReset} disabled={busy}>
        {busy ? 'Czyszczenie…' : 'Przywróć ustawienia fabryczne'}
      </button>
    </Accordion>
  )
}


// ---------------------------------------------------------------------------
// Szablony powiadomień — edycja tematu i treści z makrami.
// ---------------------------------------------------------------------------
function NotificationsSection() {
  const [tpls, setTpls] = useState(null)
  const [err, setErr]   = useState(null)

  function load() {
    listNotificationTemplates()
      .then(r => setTpls(r.data))
      .catch(ex => setErr(errorMessage(ex, 'Nie udało się wczytać szablonów')))
  }
  useEffect(() => { load() }, [])

  if (err) return <LoadError message={err} onRetry={() => { setErr(null); load() }} />
  if (!tpls) return <div style={{ color: 'var(--color-text-muted)' }}>Ładowanie…</div>

  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 12 }}>
        Edytuj temat i treść powiadomień. W treści wstawiaj <strong>makra</strong> w nawiasach
        klamrowych (np. <code>{'{worker_name}'}</code>) — przy wysyłce zostaną podmienione na
        dane wniosku. Puste pole = tekst domyślny. Wyłączenie szablonu wstrzymuje dany e-mail.
      </div>
      {tpls.map(t => <TplEditor key={t.event_key} tpl={t} onSaved={load} />)}
    </div>
  )
}

function TplEditor({ tpl, onSaved }) {
  const fid = useId()   // id pól formularza (etykiety htmlFor)
  const [subject, setSubject] = useState(tpl.subject || '')
  const [body, setBody]       = useState(tpl.body || '')
  const [enabled, setEnabled] = useState(tpl.enabled !== false)
  const [open, setOpen]       = useState(false)
  const [busy, setBusy]       = useState(false)
  const [msg, setMsg]         = useState(null)
  const subjectRef = useRef(null)
  const bodyRef    = useRef(null)
  const activeRef  = useRef('body')

  function insertMacro(m) {
    const ref = activeRef.current === 'subject' ? subjectRef : bodyRef
    const el = ref.current
    const cur = activeRef.current === 'subject' ? subject : body
    const set = activeRef.current === 'subject' ? setSubject : setBody
    const pos = el && typeof el.selectionStart === 'number' ? el.selectionStart : cur.length
    set(cur.slice(0, pos) + m + cur.slice(pos))
    setTimeout(() => { if (el) { el.focus(); const p = pos + m.length; el.setSelectionRange(p, p) } }, 0)
  }

  async function save() {
    setBusy(true); setMsg(null)
    try {
      const r = await saveNotificationTemplate(tpl.event_key, { subject, body, enabled })
      setSubject(r.data.subject); setBody(r.data.body); setEnabled(r.data.enabled !== false)
      toast(`Zapisano szablon „${tpl.label}”`); onSaved?.()
    } catch (ex) {
      setMsg({ ok: false, text: errorMessage(ex, 'Nie udało się zapisać szablonu powiadomienia') })
    } finally { setBusy(false) }
  }
  async function reset() {
    if (!await ask('Przywrócić domyślną treść tego powiadomienia?', { title: 'Potwierdź', confirmLabel: 'Przywróć domyślną' })) return
    setBusy(true); setMsg(null)
    try {
      const r = await resetNotificationTemplate(tpl.event_key)
      setSubject(r.data.subject); setBody(r.data.body); setEnabled(true)
      toast('Przywrócono domyślny tekst'); onSaved?.()
    } catch (ex) {
      setMsg({ ok: false, text: errorMessage(ex, 'Nie udało się przywrócić domyślnej treści') })
    } finally { setBusy(false) }
  }
  async function test() {
    setBusy(true); setMsg(null)
    try {
      const r = await testNotificationTemplate(tpl.event_key)
      setMsg({ ok: true, text: `Test wysłany na ${r.data.sent_to}.` })
    } catch (ex) {
      setMsg({ ok: false, text: errorMessage(ex, 'Nie udało się wysłać testu') })
    } finally { setBusy(false) }
  }

  return (
    <div style={{ border: '1px solid var(--color-border)', borderRadius: 8, marginBottom: 10 }}>
      <button type="button" aria-expanded={open} onClick={() => setOpen(v => !v)}
              style={{ width: '100%', display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
                       minHeight: 44, cursor: 'pointer', flexWrap: 'wrap', border: 0, background: 'transparent',
                       font: 'inherit', color: 'inherit', textAlign: 'left' }}>
        {open ? <ChevronDown size={15} aria-hidden="true" /> : <ChevronRight size={15} aria-hidden="true" />}
        <strong style={{ fontSize: 13, color: 'var(--color-heading)' }}>{tpl.label}</strong>
        {!enabled && <span className="badge badge--warning" style={{ fontSize: 9 }}>wyłączone</span>}
        {tpl.is_custom && <span className="badge badge--info" style={{ fontSize: 9 }}>zmienione</span>}
      </button>
      {open && (
        <div style={{ padding: '0 12px 12px', borderTop: '1px solid var(--color-border)' }}>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', margin: '8px 0' }}>
            {tpl.description}
          </div>
          <label className="form-check" style={{ marginBottom: 10 }}>
            <input type="checkbox" checked={enabled} onChange={e => setEnabled(e.target.checked)} />
            Wysyłaj to powiadomienie
          </label>
          <div className="form-group">
            <label className="form-label" htmlFor={`${fid}-subject`}>Temat</label>
            <input id={`${fid}-subject`} ref={subjectRef} className="form-control" value={subject}
                   onFocus={() => { activeRef.current = 'subject' }}
                   onChange={e => setSubject(e.target.value)} />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor={`${fid}-body`}>Treść</label>
            <textarea id={`${fid}-body`} ref={bodyRef} className="form-control" style={{ minHeight: 160, fontFamily: 'var(--font-mono)', fontSize: 12 }}
                      value={body}
                      onFocus={() => { activeRef.current = 'body' }}
                      onChange={e => setBody(e.target.value)} />
          </div>
          {tpl.macros?.length > 0 && (
            <div style={{ margin: '4px 0 10px' }}>
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}>
                Dostępne makra (kliknij, aby wstawić):
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {tpl.macros.map(m => (
                  <button key={m} type="button" className="btn btn--ghost btn--sm"
                          style={{ fontSize: 11, fontFamily: 'var(--font-mono)' }}
                          onClick={() => insertMacro(m)}>{m}</button>
                ))}
              </div>
            </div>
          )}
          {msg && (
            <div className="alert" style={{
              background: msg.ok ? 'var(--color-success-bg)' : 'var(--color-error-bg)',
              borderLeft: `4px solid ${msg.ok ? 'var(--color-success)' : 'var(--color-error)'}`,
              color: msg.ok ? 'var(--color-success-text)' : 'var(--color-error-text)', marginBottom: 10, fontSize: 12,
            }}>{msg.text}</div>
          )}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button className="btn btn--primary btn--sm" onClick={save} disabled={busy}>
              {busy ? 'Zapisywanie…' : 'Zapisz'}
            </button>
            <button className="btn btn--ghost btn--sm" onClick={test} disabled={busy}>
              <TestTube size={12} /> Wyślij test
            </button>
            <button className="btn btn--ghost btn--sm" onClick={reset} disabled={busy}>
              Przywróć domyślny
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
