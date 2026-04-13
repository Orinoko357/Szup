'use strict';
const db = require('../config/db');
const { authenticateAgainstDomain, testConnection } = require('../config/ldap');
const logger = require('../config/logger');

/**
 * Authenticate user via LDAP.
 * If domenoId is provided, only tries that domain.
 * Otherwise, tries all active domains by order.
 */
async function ldapAuthenticate(username, password, domenoId = null) {
  let domains;
  if (domenoId) {
    const { rows } = await db.query(
      'SELECT * FROM ldap_domeny WHERE id = $1 AND aktywna = TRUE',
      [domenoId]
    );
    domains = rows;
  } else {
    const { rows } = await db.query(
      'SELECT * FROM ldap_domeny WHERE aktywna = TRUE ORDER BY kolejnosc',
      []
    );
    domains = rows;
  }

  if (domains.length === 0) {
    throw { status: 400, message: 'Brak aktywnych domen LDAP.' };
  }

  let lastError = null;
  for (const domain of domains) {
    try {
      const result = await authenticateAgainstDomain(domain, username, password);
      return { ...result, domenoId: domain.id, domena: domain.domena };
    } catch (err) {
      logger.debug(`LDAP domain ${domain.domena} failed`, { err: err.message });
      lastError = err;
    }
  }

  throw { status: 401, message: lastError ? lastError.message : 'Błąd uwierzytelniania LDAP.' };
}

async function testDomain(domainId) {
  const { rows } = await db.query('SELECT * FROM ldap_domeny WHERE id = $1', [domainId]);
  if (rows.length === 0) throw { status: 404, message: 'Domena nie istnieje.' };
  return testConnection(rows[0]);
}

module.exports = { ldapAuthenticate, testDomain };
