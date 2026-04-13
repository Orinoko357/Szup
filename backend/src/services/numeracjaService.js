'use strict';
const db = require('../config/db');
const logger = require('../config/logger');

/**
 * Generate the next request number using SELECT FOR UPDATE.
 * Handles reset by ROK or MIESIAC.
 */
async function generateNumer(client) {
  // Use provided client (for transaction context) or get from pool
  const useClient = client || await db.getClient();
  const shouldRelease = !client;

  try {
    if (!client) await useClient.query('BEGIN');

    const { rows } = await useClient.query(
      'SELECT * FROM konfiguracja_numeracji LIMIT 1 FOR UPDATE'
    );
    if (rows.length === 0) throw new Error('Brak konfiguracji numeracji');

    const cfg = rows[0];
    const today = new Date();
    const currentYear = today.getFullYear();
    const currentMonth = today.getMonth() + 1;
    const lastReset = new Date(cfg.ostatni_reset);

    let nextNum = cfg.ostatni_numer + 1;
    let newReset = cfg.ostatni_reset;

    // Check if reset is needed
    if (cfg.reset_co === 'ROK' && lastReset.getFullYear() < currentYear) {
      nextNum = 1;
      newReset = today;
    } else if (cfg.reset_co === 'MIESIAC') {
      if (
        lastReset.getFullYear() < currentYear ||
        (lastReset.getFullYear() === currentYear && lastReset.getMonth() + 1 < currentMonth)
      ) {
        nextNum = 1;
        newReset = today;
      }
    }

    // Apply format template
    const seq = String(nextNum).padStart(cfg.szerokosc_sekwencji, '0');
    const year = String(currentYear);
    const month = String(currentMonth).padStart(2, '0');

    let numer = cfg.format_szablonu
      .replace(/{PREFIX}/g, cfg.prefix)
      .replace(/{SEQ:\d+}/g, seq)
      .replace(/{SEQ}/g, seq)
      .replace(/{SEQ_TENANT}/g, seq)
      .replace(/{YEAR}/g, year)
      .replace(/{MONTH}/g, month);

    await useClient.query(
      `UPDATE konfiguracja_numeracji
         SET ostatni_numer = $1, ostatni_reset = $2
       WHERE id = $3`,
      [nextNum, newReset, cfg.id]
    );

    if (!client) await useClient.query('COMMIT');
    return numer;
  } catch (err) {
    if (!client) {
      await useClient.query('ROLLBACK');
    }
    logger.error('Numeracja error', { err: err.message });
    throw err;
  } finally {
    if (shouldRelease) useClient.release();
  }
}

module.exports = { generateNumer };
