'use strict';
const cron = require('node-cron');
const db = require('../config/db');
const { createNotification, notifyIT } = require('./notificationService');
const { writeAudit } = require('./auditService');
const logger = require('../config/logger');

/**
 * Task 1: Send reminders for pending stages past their reminder deadline.
 */
async function runReminders() {
  logger.debug('Scheduler: running reminders');
  const { rows } = await db.query(
    `SELECT we.id, we.wniosek_id, we.zatwierdzajacy_id, we.przypomnienie_dni,
            w.numer, p.uzytkownik_id
       FROM wnioski_etapy we
       JOIN wnioski w ON w.id = we.wniosek_id
       JOIN pracownicy p ON p.id = we.zatwierdzajacy_id
      WHERE we.status = 'OCZEKUJE'
        AND we.data_przypomnienia IS NULL
        AND we.data_przypisania + (we.przypomnienie_dni || ' days')::interval <= NOW()`,
    []
  );

  for (const row of rows) {
    try {
      await createNotification({
        userId: row.uzytkownik_id,
        typ: 'PRZYPOMNIENIE_ZATWIERDZENIA',
        tresc: `Przypomnienie: wniosek ${row.numer} oczekuje na Twoją akceptację.`,
        link: `/wnioski/${row.wniosek_id}`,
      });
      await db.query(
        'UPDATE wnioski_etapy SET data_przypomnienia = NOW() WHERE id = $1',
        [row.id]
      );
    } catch (err) {
      logger.error('Reminder error', { etapId: row.id, err: err.message });
    }
  }
  if (rows.length > 0) logger.info(`Reminders sent: ${rows.length}`);
}

/**
 * Task 2: Escalate overdue stages to the approver's supervisor.
 */
async function runEskalacje() {
  logger.debug('Scheduler: running escalations');
  const { rows } = await db.query(
    `SELECT we.id, we.wniosek_id, we.zatwierdzajacy_id, we.eskalacja_dni,
            w.numer, w.tenant_id,
            przel.uzytkownik_id as przel_user_id,
            przel.id as przel_prac_id
       FROM wnioski_etapy we
       JOIN wnioski w ON w.id = we.wniosek_id
       JOIN pracownicy p ON p.id = we.zatwierdzajacy_id
       LEFT JOIN pracownicy przel ON przel.id = p.przelozony_id
      WHERE we.status = 'OCZEKUJE'
        AND we.data_eskalacji IS NULL
        AND we.data_przypisania + (we.eskalacja_dni || ' days')::interval <= NOW()`,
    []
  );

  for (const row of rows) {
    try {
      if (row.przel_user_id) {
        await createNotification({
          userId: row.przel_user_id,
          typ: 'ESKALACJA',
          tresc: `ESKALACJA: Wniosek ${row.numer} nie został zatwierdzony w terminie. Proszę o interwencję.`,
          link: `/wnioski/${row.wniosek_id}`,
        });
      }
      await db.query(
        `UPDATE wnioski_etapy
           SET data_eskalacji = NOW(), eskalacja_do = $1
         WHERE id = $2`,
        [row.przel_prac_id || null, row.id]
      );
      await writeAudit({
        tenantId: row.tenant_id,
        akcja: 'ESKALACJA',
        tabelaDocelowa: 'wnioski_etapy',
        rekordId: row.id,
        noweDane: { wniosekId: row.wniosek_id, eskalacjaDo: row.przel_prac_id },
      });
    } catch (err) {
      logger.error('Escalation error', { etapId: row.id, err: err.message });
    }
  }
  if (rows.length > 0) logger.info(`Escalations processed: ${rows.length}`);
}

/**
 * Task 3: Mark permissions requiring NIS2 review.
 */
async function runNis2Reviews() {
  logger.debug('Scheduler: running NIS2 reviews');
  const { rows: tenants } = await db.query('SELECT id, dni_do_przegladu FROM tenants WHERE aktywny = TRUE');

  for (const tenant of tenants) {
    const { rowCount } = await db.query(
      `UPDATE uprawnienia
         SET wymaga_przegladu = TRUE
       WHERE aktywne = TRUE
         AND tenant_id = $1
         AND wymaga_przegladu = FALSE
         AND (
           data_ostatniego_przegladu IS NULL
           OR data_ostatniego_przegladu + ($2 || ' days')::interval <= CURRENT_DATE
         )`,
      [tenant.id, tenant.dni_do_przegladu]
    );
    if (rowCount > 0) {
      await notifyIT({
        typ: 'PRZEGLAD_WYMAGANY',
        tresc: `${rowCount} uprawnień w jednostce #${tenant.id} wymaga przeglądu NIS2.`,
        link: '/przeglady',
      });
      logger.info(`NIS2 review flagged: ${rowCount} for tenant ${tenant.id}`);
    }
  }
}

/**
 * Task 4: Reset numbering sequence.
 */
async function runResetNumeracji() {
  logger.debug('Scheduler: checking numbering reset');
  const { rows } = await db.query('SELECT * FROM konfiguracja_numeracji FOR UPDATE');
  if (rows.length === 0) return;

  const cfg = rows[0];
  const today = new Date();
  const lastReset = new Date(cfg.ostatni_reset);
  let needsReset = false;

  if (cfg.reset_co === 'ROK' && lastReset.getFullYear() < today.getFullYear()) needsReset = true;
  if (cfg.reset_co === 'MIESIAC') {
    if (lastReset.getFullYear() < today.getFullYear() ||
      (lastReset.getFullYear() === today.getFullYear() && lastReset.getMonth() < today.getMonth())) {
      needsReset = true;
    }
  }

  if (needsReset) {
    await db.query(
      'UPDATE konfiguracja_numeracji SET ostatni_numer = 0, ostatni_reset = $1 WHERE id = $2',
      [today, cfg.id]
    );
    logger.info('Numbering sequence reset');
  }
}

function start() {
  if (process.env.SCHEDULER_ENABLED !== 'true') {
    logger.info('Scheduler disabled (SCHEDULER_ENABLED != true)');
    return;
  }

  // Every hour: reminders and escalations
  cron.schedule('0 * * * *', async () => {
    await runReminders().catch(e => logger.error('Reminders failed', e));
    await runEskalacje().catch(e => logger.error('Escalations failed', e));
  });

  // Every day at 02:00: NIS2 reviews and numbering reset
  cron.schedule('0 2 * * *', async () => {
    await runNis2Reviews().catch(e => logger.error('NIS2 reviews failed', e));
    await runResetNumeracji().catch(e => logger.error('Numbering reset failed', e));
  });

  logger.info('Scheduler started');
}

module.exports = { start, runReminders, runEskalacje, runNis2Reviews, runResetNumeracji };
