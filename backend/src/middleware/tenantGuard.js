'use strict';
const db = require('../config/db');

/**
 * Ensure user belongs to the requested tenant or is cross-tenant (IT_ADMIN, KADRY, SUPERADMIN).
 * Attaches req.tenantId from param or user.
 */
function tenantGuard(req, res, next) {
  const { rola, tenantId: userTenantId } = req.user;
  const crossTenantRoles = ['SUPERADMIN', 'IT_ADMIN', 'KADRY'];

  if (crossTenantRoles.includes(rola)) {
    // Cross-tenant users can access any tenant via param or query
    const paramTenantId = req.params.tenantId || req.query.tenant_id || req.body.tenant_id;
    req.tenantId = paramTenantId ? parseInt(paramTenantId) : null;
    return next();
  }

  // Tenant-scoped users
  if (!userTenantId) {
    return res.status(403).json({ error: 'Brak przypisania do jednostki.' });
  }

  const paramTenantId = req.params.tenantId || req.query.tenant_id;
  if (paramTenantId && parseInt(paramTenantId) !== userTenantId) {
    return res.status(403).json({ error: 'Brak dostępu do tej jednostki.' });
  }

  req.tenantId = userTenantId;
  next();
}

module.exports = { tenantGuard };
