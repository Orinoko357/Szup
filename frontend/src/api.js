import axios from 'axios'
import { clearSession, updateCurrentUser } from './roles'

const api = axios.create({ baseURL: '/api', timeout: 30000 })

api.interceptors.request.use(config => {
  let token = null
  try { token = localStorage.getItem('szup_token') } catch { /* zablokowany storage */ }
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  res => res,
  err => {
    // 401 na wygasłej sesji → wyloguj i wróć do logowania. ALE:
    //  - NIE dla samych endpointów logowania (błędne hasło ma pokazać komunikat
    //    w formularzu, a nie przeładować stronę i skasować jego stan),
    //  - NIE gdy już jesteśmy na /login (uniknij pętli przeładowań).
    const url = err.config?.url || ''
    const isAuthAttempt = url.includes('/auth/login') || url.includes('/auth/setup')
    const onLoginPage = window.location.pathname.startsWith('/login')
    if (err.response?.status === 401 && !isAuthAttempt && !onLoginPage) {
      clearSession()
      window.location.href = '/login'
    }
    // 403 PASSWORD_CHANGE_REQUIRED — hasło trzeba zmienić (np. wygasło w trakcie
    // sesji albo admin wymusił zmianę). Zapisz flagę w sesji i daj znać App,
    // która pokaże ekran wymuszonej zmiany hasła.
    if (err.response?.status === 403
        && err.response?.data?.detail?.code === 'PASSWORD_CHANGE_REQUIRED') {
      updateCurrentUser({ must_change_password: true })
      window.dispatchEvent(new Event('szup:mustchange'))
    }
    return Promise.reject(err)
  }
)

export default api

/** Czytelny komunikat błędu z odpowiedzi API. Obsługuje też 422 z Pydantic
 *  (lista błędów walidacji), które wcześniej pokazywało „[object Object]”. */
export function errorMessage(ex, fallback = 'Wystąpił błąd') {
  const det = ex?.response?.data?.detail
  if (typeof det === 'string' && det.trim()) return det
  if (Array.isArray(det) && det.length) {
    return det.map(d => {
      const field = Array.isArray(d.loc) ? d.loc.filter(x => x !== 'body').join('.') : ''
      return field ? `${field}: ${d.msg}` : d.msg
    }).join('; ')
  }
  if (det && typeof det === 'object' && det.message) return det.message
  if (ex?.response?.status === 403) return 'Brak uprawnień do tej operacji.'
  if (!ex?.response && ex?.message) return 'Brak połączenia z serwerem.'
  return fallback
}

// Wspólny budowniczy query-stringu (pomija puste wartości).
const toQs = (params) => new URLSearchParams(
  Object.entries(params || {}).filter(([, v]) => v !== '' && v != null)
).toString()

// --- Auth ---
export const getAuthStatus    = ()       => api.get('/auth/status')
export const setupAdmin       = (data)   => api.post('/auth/setup', data)
export const loginLocal       = (data)   => api.post('/auth/login', data)
export const loginLdap        = (data)   => api.post('/auth/login/ldap', data)
export const loginTest        = (data)   => api.post('/auth/login/test', data)
// SSO (Kerberos/Negotiate): /auth/sso-login (redirect z Apache) → kod → token.
export const ssoExchange      = (code)   => api.post('/auth/sso-exchange', { code })
export const getMe            = ()       => api.get('/auth/me')
export const logout           = ()       => api.post('/auth/logout')
export const changePassword   = (data)   => api.post('/auth/change-password', data)

// --- Users (superadmin) ---
export const listUsers        = ()              => api.get('/users/')
export const createUser       = (data)          => api.post('/users/', data)
export const updateUser       = (id, data)      => api.patch(`/users/${id}`, data)
export const deleteUser       = (id)            => api.delete(`/users/${id}`)
export const resetUserPassword = (id, pwd)      => api.post(`/users/${id}/reset-password`, { new_password: pwd })
export const unlockUser       = (id)            => api.post(`/users/${id}/unlock`)
export const listMyWorkers    = ()              => api.get('/users/my-workers')
export const getMySubtree     = ()              => api.get('/users/my-subtree')
export const getMyPermissions = ()              => api.get('/users/me/permissions')
export const usersByDepartment = (deptId)       => api.get(`/users/by-department/${deptId}`)
export const searchUsers        = (q)            => api.get('/users/search', { params: { q } })
export const userPermissions   = (userId)       => api.get(`/users/${userId}/permissions`)
export const listItStaff       = ()             => api.get('/users/it-staff')
export const assignRequest     = (id, userId)   => api.post(`/requests/${id}/assign`, { user_id: userId })

// --- Dziennik zdarzeń (audit log) ---
// Dziennik jest tylko do odczytu dla admina. Wyjątek: superadmin może go
// wyczyścić (hasło + powód); samo czyszczenie zostaje zapisane i nie da się go usunąć.
// data: { password, reason, mode: 'before'|'all', before?: 'YYYY-MM-DD' }
export const purgeAudit         = (data)   => api.post('/audit/purge', data, { timeout: 120000 })
export const listAudit          = (params) => api.get('/audit/', { params })
export const auditStats         = ()       => api.get('/audit/stats')
// Eksport CSV przez instancję `api` (token, obsługa 401) — odpowiedź jako Blob.
export const exportAuditCsv     = (since, until) => api.get('/audit/export.csv', {
  params: { ...(since ? { since } : {}), ...(until ? { until } : {}) },
  responseType: 'blob', timeout: 120000,
})

// --- Security events ---
export const listSecurityEvents    = (params) => api.get('/security/', { params })
export const securityEventsSummary = ()       => api.get('/security/summary')
export const resolveSecurityEvent  = (id, note) => api.post(`/security/${id}/resolve`, { note })
// Superadmin: czyszczenie zdarzeń bezpieczeństwa (jak purgeAudit).
export const purgeSecurity         = (data)   => api.post('/security/purge', data, { timeout: 120000 })

// --- Settings ---
export const getEmailSettings  = ()       => api.get('/settings/email')
export const updateEmailSettings = (data) => api.put('/settings/email', data)
export const testEmail         = ()       => api.post('/settings/email/test')
export const getLdapSettings   = ()       => api.get('/settings/ldap')
export const updateLdapSettings = (data)  => api.put('/settings/ldap', data)
export const testLdap          = ()       => api.post('/settings/ldap/test')
// Reset do ustawień fabrycznych — wyłącznie superadmin (operacja nieodwracalna)
export const factoryReset      = (data)   => api.post('/settings/factory-reset', data, { timeout: 120000 })
export const getAppSettings    = ()       => api.get('/settings/app')
export const updateAppSettings = (data)   => api.put('/settings/app', data)
// Szablony powiadomień e-mail (treść z makrami).
export const listNotificationTemplates = ()          => api.get('/settings/notifications')
export const saveNotificationTemplate  = (key, data) => api.put(`/settings/notifications/${key}`, data)
export const resetNotificationTemplate = (key)       => api.delete(`/settings/notifications/${key}`)
export const testNotificationTemplate  = (key)       => api.post(`/settings/notifications/${key}/test`)

// --- Jednostki i wydziały ---
export const listUnits         = ()              => api.get('/units/')
export const createUnit        = (data)          => api.post('/units/', data)
export const updateUnit        = (id, data)      => api.patch(`/units/${id}`, data)
export const deleteUnit        = (id)            => api.delete(`/units/${id}`)
export const listAllDepartments = ()             => api.get('/units/departments/all')
export const listActiveDepts   = (unitId)        => api.get('/units/departments/active', { params: unitId ? { unit_id: unitId } : {} })
export const listActiveUnits   = ()              => api.get('/units/active')
export const createDepartment  = (data)          => api.post('/units/departments', data)
export const updateDepartment  = (id, data)      => api.patch(`/units/departments/${id}`, data)
// Przypisz kierowników komórek wg stanowiska z AD (title: kierownik/dyrektor/naczelnik).
export const autoAssignManagers = (data = {})    => api.post('/units/departments/auto-managers', data)
// Usuń zduplikowane komórki (np. po ponownym imporcie struktury).
export const dedupeDepartments  = ()             => api.post('/units/departments/dedupe', {})
export const deleteDepartment  = (id)            => api.delete(`/units/departments/${id}`)
// Superadmin: usunięcie komórki mimo powiązań ({ reason, password }). Komórka
// z historią jest archiwizowana (backend ukrywa zarchiwizowane).
export const forceDeleteDepartment = (id, data)  => api.post(`/units/departments/${id}/force-delete`, data)
export const listDeputies      = (deptId)        => api.get(`/units/departments/${deptId}/deputies`)
export const addDeputy         = (deptId, data)  => api.post(`/units/departments/${deptId}/deputies`, data)
export const updateDeputy      = (deputyId, data) => api.patch(`/units/departments/deputies/${deputyId}`, data)
export const deleteDeputy      = (deputyId)      => api.delete(`/units/departments/deputies/${deputyId}`)
export const ldapPreviewUnits  = (search_base)   => api.post('/units/ldap/preview', { search_base: search_base || null }, { timeout: 15000 })
export const ldapImportUnits   = (items)         => api.post('/units/ldap/import', { items })
export const ldapPreviewUsers  = (search_base)   => api.post('/users/ldap/preview', { search_base: search_base || null }, { timeout: 30000 })
export const ldapImportUsers   = (usernames, search_base) => api.post('/users/ldap/import', { usernames, search_base: search_base || null }, { timeout: 30000 })

// --- Systemy IT / Rejestr oprogramowania ---
// params: { unit_id?: number, active_only?: boolean }
export const listSystems       = (params)        => api.get('/systems/', { params })
export const createSystem      = (data)          => api.post('/systems/', data)
export const updateSystem      = (id, data)      => api.patch(`/systems/${id}`, data)
export const deleteSystem      = (id)            => api.delete(`/systems/${id}`)
export const listPermissions   = (systemId)      => api.get(`/systems/${systemId}/permissions`)
// Skopiuj definicję uprawnień (pola wnioskodawcy albo listę) z innego programu
export const copySystemPermissions = (systemId, sourceSystemId) =>
  api.post(`/systems/${systemId}/copy-permissions`, { source_system_id: sourceSystemId })
// Ustaw domyślną definicję uprawnień („Zakres uprawnień" — pole opisowe, wymagane)
export const setSystemDefaultPermissions = (systemId) =>
  api.post(`/systems/${systemId}/copy-permissions`, { use_default: true })
export const createPermission  = (systemId, data) => api.post(`/systems/${systemId}/permissions`, data)
// Import listy uprawnień z pliku (CSV / TSV / Excel) albo wklejenia ze schowka.
// Dłuższy timeout niż domyślne 30 s — arkusz z setkami pozycji potrafi zejść wolniej.
export const previewPermissionImport = (systemId, formData) =>
  api.post(`/systems/${systemId}/permissions/import/preview`, formData, { timeout: 120000 })
export const commitPermissionImport  = (systemId, data) =>
  api.post(`/systems/${systemId}/permissions/import/commit`, data, { timeout: 120000 })
// Wygaszenie / przywrócenie całej grupy uprawnień
export const setPermissionGroupState = (systemId, groupName, isActive) =>
  api.post(`/systems/${systemId}/permissions/group-state`,
           { group_name: groupName, is_active: isActive })
export const renamePermissionGroup = (systemId, groupName, newName) =>
  api.post(`/systems/${systemId}/permissions/group-rename`,
           { group_name: groupName, new_name: newName })
// reason — wymagany przez backend, gdy grupa jest komuś przyznana (tylko superadmin).
export const deletePermissionGroup = (systemId, groupName, reason) =>
  api.post(`/systems/${systemId}/permissions/group-delete`,
           { group_name: groupName, ...(reason ? { reason } : {}) })
// Kto ma przyznane uprawnienia z grupy + wnioski w toku, które jej dotyczą.
export const getPermissionGroupUsage = (systemId, groupName) =>
  api.get(`/systems/${systemId}/permissions/group-usage`, { params: { group_name: groupName } })
// Ustaw kolejność grup (pełna lista nazw w żądanej kolejności).
export const setPermissionGroupOrder = (systemId, groups) =>
  api.post(`/systems/${systemId}/permissions/group-order`, { groups })
// Masowe przypisanie zaznaczonych uprawnień do podgrupy (albo wyjęcie z niej).
export const assignPermissionSubgroup = (systemId, permissionIds, subgroupName) =>
  api.post(`/systems/${systemId}/permissions/subgroup-assign`,
           { permission_ids: permissionIds, subgroup_name: subgroupName })
// Skopiuj JEDNĄ grupę uprawnień z innego programu do tego.
export const copyPermissionGroup = (systemId, data) =>
  api.post(`/systems/${systemId}/copy-group`, data)

// --- Dostawcy oprogramowania (słownik) + umowy serwisowe ---
export const listVendors       = ()               => api.get('/vendors/')
export const createVendor      = (data)           => api.post('/vendors/', data)
export const updateVendor      = (id, data)       => api.patch(`/vendors/${id}`, data)
export const deleteVendor      = (id)             => api.delete(`/vendors/${id}`)
export const listContracts     = (vendorId)       => api.get(`/vendors/${vendorId}/contracts`)
export const addContract       = (vendorId, data) => api.post(`/vendors/${vendorId}/contracts`, data)
export const deleteContract    = (contractId)     => api.delete(`/vendors/contracts/${contractId}`)
// Alerty o umowach na pulpit IT (endpoint wymaga roli IT/admin)
export const vendorContractAlerts = ()            => api.get('/vendors/contract-alerts')
export const updatePermission  = (permId, data)  => api.patch(`/systems/permissions/${permId}`, data)
export const deletePermission  = (permId)        => api.delete(`/systems/permissions/${permId}`)

// --- Wnioski ---
export const listRequests      = (params)        => api.get('/requests/', { params })
export const getRequest        = (id)            => api.get(`/requests/${id}`)
export const createRequest     = (data)          => api.post('/requests/', data)
// Wersja robocza wyboru kierownika (bez wysyłania) — pozycje jak w akcji „select”.
export const saveRequestDraft  = (id, data)      => api.post(`/requests/${id}/draft`, data)
// Przejęcie wniosku z podległej komórki przez przełożonego (bez treści).
export const takeOverRequest   = (id)            => api.post(`/requests/${id}/take-over`)
// „Oddaj” — przejmujący zwalnia przejęcie; wniosek wraca do kierownika komórki.
export const releaseRequest    = (id)            => api.post(`/requests/${id}/release`)
export const linkRequestWorker = (id, ad_username) => api.post(`/requests/${id}/link-worker`, { ad_username })

// --- Pulpit obiegu wniosków ---
export const workflowDashboard = () => api.get('/requests/dashboard')
// v3.1 — lista kontrolna konfiguracji + sygnały jakości danych (admin)
export const getAdminHealth    = () => api.get('/settings/health')

// --- Workflow — szablony obiegu i typy wniosków ---
export const listWorkflowTemplates  = (params) => api.get('/workflow-templates/', { params })
export const getWorkflowTemplate    = (id)     => api.get(`/workflow-templates/${id}`)
export const createWorkflowTemplate = (data)   => api.post('/workflow-templates/', data)
export const updateWorkflowTemplate = (id, d)  => api.patch(`/workflow-templates/${id}`, d)
export const deleteWorkflowTemplate = (id)     => api.delete(`/workflow-templates/${id}`)

export const listRequestTypes       = (params) => api.get('/request-types/', { params })
export const createRequestType      = (data)   => api.post('/request-types/', data)
export const updateRequestType      = (id, d)  => api.patch(`/request-types/${id}`, d)
export const deleteRequestType      = (id)     => api.delete(`/request-types/${id}`)

// --- Workflow — stan instancji dla wniosku ---
export const getRequestWorkflow     = (rid)    => api.get(`/requests/${rid}/workflow`)
export const workflowAction         = (rid, d) => api.post(`/requests/${rid}/workflow/action`, d)
// Odmowa POJEDYNCZEJ pozycji od ręki (bez kończenia wniosku). denied=false cofa.
export const denyRequestItem        = (rid, iid, d) => api.post(`/requests/${rid}/items/${iid}/deny`, d)
// Realizacja etapowa: odhaczenie pojedynczej pozycji przez IT. fulfilled=false cofa.
export const fulfillRequestItem     = (rid, iid, d) => api.post(`/requests/${rid}/items/${iid}/fulfill`, d)

// --- Rejestr nadanych uprawnień + oświadczenia ---
export const listGrantedRegistry = (params)        => api.get('/registry/granted', { params })
export const grantedRegistryCsvUrl = (params) => {
  const qs = toQs(params)
  return `/api/registry/granted.csv${qs ? `?${qs}` : ''}`
}
export const getDeclaration      = (code)          => api.get(`/registry/declarations/${encodeURIComponent(code)}`)
// Treść oświadczenia dla modala (dostępna każdemu zalogowanemu).
export const getDeclarationText  = ()              => api.get('/settings/declaration-text')

// --- Migawki uprawnień (nocne, 23:50) ---
export const listSnapshots       = ()              => api.get('/snapshots')
export const getSnapshot         = (date, params)  => api.get(`/snapshots/${date}`, { params })
export const snapshotCsvUrl      = (date, params) => {
  const qs = toQs(params)
  return `/api/snapshots/${date}.csv${qs ? `?${qs}` : ''}`
}
export const runSnapshot         = (force)         => api.post(`/snapshots/run${force ? '?force=true' : ''}`)

// --- Wnioski o zmianę nazwiska (pracownik → IT) ---
export const createNameChange    = (data)          => api.post('/name-changes', data)
export const myNameChanges       = ()              => api.get('/name-changes/mine')
export const listNameChanges     = (status)        => api.get('/name-changes', { params: status ? { status } : {} })
export const resolveNameChange   = (id, data)      => api.post(`/name-changes/${id}/resolve`, data)
