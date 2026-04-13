'use strict';
const db = require('../config/db');
const logger = require('../config/logger');

/**
 * Insert a row into audit_log.
 */
async function writeAudit({
  tenantId, userId, username, rola,
  akcja, tabelaDocelowa, rekordId,
  stareDane, noweDane, ipAdres, userAgent,
}) {
  try {
    await db.query(
      `INSERT INTO audit_log
         (tenant_id, user_id, username, rola, akcja, tabela_docelowa,
          rekord_id, stare_dane, nowe_dane, ip_adres, user_agent)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)`,
      [
        tenantId || null,
        userId || null,
        username || null,
        rola || null,
        akcja,
        tabelaDocelowa || null,
        rekordId || null,
        stareDane ? JSON.stringify(stareDane) : null,
        noweDane ? JSON.stringify(noweDane) : null,
        ipAdres || null,
        userAgent || null,
      ]
    );
  } catch (err) {
    logger.error('Failed to write audit log', { err: err.message, akcja });
  }
}

/**
 * Express middleware that logs requests to audit_log.
 * Only logs mutating methods.
 */
function auditMiddleware(tabelaDocelowa, getRecordId) {
  return async (req, res, next) => {
    const methods = ['POST', 'PUT', 'PATCH', 'DELETE'];
    if (!methods.includes(req.method)) return next();

    const originalJson = res.json.bind(res);
    let responseBody = null;

    res.json = function (body) {
      responseBody = body;
      return originalJson(body);
    };

    res.on('finish', async () => {
      if (res.statusCode >= 200 && res.statusCode < 300 && req.user) {
        const recordId = getRecordId
          ? getRecordId(req, responseBody)
          : (responseBody && responseBody.id) || null;

        await writeAudit({
          tenantId: req.tenantId || req.user.tenantId,
          userId: req.user.userId,
          username: req.user.username,
          rola: req.user.rola,
          akcja: `${req.method}:${req.path}`,
          tabelaDocelowa,
          rekordId: recordId,
          noweDane: req.body,
          ipAdres: req.ip,
          userAgent: req.headers['user-agent'],
        });
      }
    });

    next();
  };
}

module.exports = { writeAudit, auditMiddleware };
