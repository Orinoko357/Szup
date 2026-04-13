'use strict';
const db = require('../config/db');
const logger = require('../config/logger');

/**
 * Create an in-app notification for a user.
 */
async function createNotification({ userId, typ, tresc, link = null }) {
  if (!userId) return;
  try {
    await db.query(
      `INSERT INTO powiadomienia (user_id, typ, tresc, link)
       VALUES ($1, $2, $3, $4)`,
      [userId, typ, tresc, link]
    );
  } catch (err) {
    logger.error('Failed to create notification', { err: err.message, userId, typ });
  }
}

/**
 * Notify all users with a given role (optionally filtered by tenant).
 */
async function notifyRole({ rola, tenantId, typ, tresc, link }) {
  try {
    const { rows } = await db.query(
      `SELECT id FROM uzytkownicy WHERE rola = $1
       AND aktywny = TRUE
       AND ($2::int IS NULL OR tenant_id = $2)`,
      [rola, tenantId || null]
    );
    for (const u of rows) {
      await createNotification({ userId: u.id, typ, tresc, link });
    }
  } catch (err) {
    logger.error('Failed to notify role', { err: err.message, rola });
  }
}

/**
 * Notify IT_ADMIN users (cross-tenant).
 */
async function notifyIT({ typ, tresc, link }) {
  await notifyRole({ rola: 'IT_ADMIN', tenantId: null, typ, tresc, link });
}

module.exports = { createNotification, notifyRole, notifyIT };
