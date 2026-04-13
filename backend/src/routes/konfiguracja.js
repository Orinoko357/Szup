'use strict';
const express = require('express');
const { body } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { writeAudit } = require('../services/auditService');

const router = express.Router();

// Numbering config
router.get('/numeracja', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { rows } = await db.query('SELECT * FROM konfiguracja_numeracji LIMIT 1');
  res.json(rows[0] || {});
});

router.put('/numeracja', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'),
  [
    body('format_szablonu').notEmpty().trim(),
    body('prefix').notEmpty().trim(),
    body('szerokosc_sekwencji').isInt({ min: 1, max: 10 }),
    body('reset_co').isIn(['ROK', 'MIESIAC']),
  ],
  validate,
  async (req, res) => {
    const { format_szablonu, prefix, szerokosc_sekwencji, reset_co } = req.body;
    const { rows } = await db.query(
      `UPDATE konfiguracja_numeracji
         SET format_szablonu=$1, prefix=$2, szerokosc_sekwencji=$3, reset_co=$4
       WHERE id=1 RETURNING *`,
      [format_szablonu, prefix, szerokosc_sekwencji, reset_co]
    );
    await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'NUMERACJA_AKTUALIZACJA', tabelaDocelowa: 'konfiguracja_numeracji', noweDane: req.body });
    res.json(rows[0]);
  }
);

router.post('/numeracja/reset', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  await db.query('UPDATE konfiguracja_numeracji SET ostatni_numer=0, ostatni_reset=CURRENT_DATE WHERE id=1');
  await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'NUMERACJA_RESET_RECZNY', tabelaDocelowa: 'konfiguracja_numeracji' });
  res.json({ message: 'Sekwencja numeracji zresetowana.' });
});

// Preview numbering
router.get('/numeracja/podglad', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { rows } = await db.query('SELECT * FROM konfiguracja_numeracji LIMIT 1');
  if (!rows.length) return res.json({ podglad: '' });
  const cfg = rows[0];
  const today = new Date();
  const seq = String(cfg.ostatni_numer + 1).padStart(cfg.szerokosc_sekwencji, '0');
  const year = String(today.getFullYear());
  const month = String(today.getMonth() + 1).padStart(2, '0');
  const podglad = cfg.format_szablonu
    .replace(/{PREFIX}/g, cfg.prefix)
    .replace(/{SEQ:\d+}/g, seq)
    .replace(/{SEQ}/g, seq)
    .replace(/{YEAR}/g, year)
    .replace(/{MONTH}/g, month);
  res.json({ podglad });
});

// Platform config (key-value)
router.get('/platforma', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { rows } = await db.query('SELECT * FROM konfiguracja_platformy ORDER BY klucz');
  res.json(rows);
});

router.put('/platforma/:klucz', authenticate, roleGuard('SUPERADMIN'), async (req, res) => {
  const { wartosc } = req.body;
  const { rows } = await db.query(
    `INSERT INTO konfiguracja_platformy (klucz, wartosc)
     VALUES ($1,$2)
     ON CONFLICT (klucz) DO UPDATE SET wartosc=$2
     RETURNING *`,
    [req.params.klucz, wartosc]
  );
  res.json(rows[0]);
});

// Dashboard stats
router.get('/dashboard', authenticate, async (req, res) => {
  const { rola, userId, tenantId } = req.user;
  const stats = {};

  if (['IT_ADMIN', 'SUPERADMIN'].includes(rola)) {
    const [wIT, upA, przZal, incO, esc] = await Promise.all([
      db.query("SELECT COUNT(*) as cnt FROM wnioski WHERE status='OCZEKUJE_IT'"),
      db.query("SELECT COUNT(*) as cnt FROM uprawnienia WHERE aktywne=TRUE"),
      db.query("SELECT COUNT(*) as cnt FROM uprawnienia WHERE wymaga_przegladu=TRUE"),
      db.query("SELECT COUNT(*) as cnt FROM rejestr_incydentow WHERE status IN ('OTWARTY','W_TRAKCIE')"),
      db.query("SELECT COUNT(*) as cnt FROM wnioski_etapy WHERE status='OCZEKUJE' AND data_eskalacji IS NOT NULL"),
    ]);
    stats.wnioski_oczekujace_it = parseInt(wIT.rows[0].cnt);
    stats.uprawnienia_aktywne = parseInt(upA.rows[0].cnt);
    stats.przeglady_zagle = parseInt(przZal.rows[0].cnt);
    stats.incydenty_otwarte = parseInt(incO.rows[0].cnt);
    stats.eskalacje_aktywne = parseInt(esc.rows[0].cnt);

    const lastWnioski = await db.query(
      `SELECT w.id, w.numer, w.status, w.data_ostatniej_zmiany, t.skrot as tenant_skrot,
              u.imie || ' ' || u.nazwisko as pracownik_nazwa
         FROM wnioski w JOIN pracownicy p ON p.id=w.pracownik_id
         JOIN uzytkownicy u ON u.id=p.uzytkownik_id
         JOIN tenants t ON t.id=w.tenant_id
        ORDER BY w.data_ostatniej_zmiany DESC LIMIT 10`
    );
    stats.ostatnie_wnioski = lastWnioski.rows;
  }

  if (rola === 'KIEROWNIK') {
    const { rows: pracRows } = await db.query('SELECT id FROM pracownicy WHERE uzytkownik_id=$1', [userId]);
    if (pracRows.length > 0) {
      const pracId = pracRows[0].id;
      const [doZatw, mojeW, podwl] = await Promise.all([
        db.query(
          `SELECT COUNT(*) as cnt FROM wnioski_etapy we
             JOIN wnioski w ON w.id=we.wniosek_id
           WHERE we.zatwierdzajacy_id=$1 AND we.status='OCZEKUJE' AND w.status='W_TOKU'`,
          [pracId]
        ),
        db.query(
          `SELECT COUNT(*) as cnt FROM wnioski WHERE inicjujacy_id=$1 AND status NOT IN ('ZREALIZOWANY','ODRZUCONY')`,
          [pracId]
        ),
        db.query('SELECT COUNT(*) as cnt FROM pracownicy WHERE przelozony_id=$1 AND aktywny=TRUE', [pracId]),
      ]);
      stats.do_zatwierdzenia = parseInt(doZatw.rows[0].cnt);
      stats.moje_wnioski_w_toku = parseInt(mojeW.rows[0].cnt);
      stats.liczba_podwladnych = parseInt(podwl.rows[0].cnt);
    }
  }

  if (rola === 'KADRY') {
    const [nowyP, wToku] = await Promise.all([
      db.query(
        `SELECT COUNT(*) as cnt FROM pracownicy WHERE data_zatrudnienia >= CURRENT_DATE - INTERVAL '30 days'`
      ),
      db.query("SELECT COUNT(*) as cnt FROM wnioski WHERE status IN ('W_TOKU','OCZEKUJE_IT')"),
    ]);
    stats.nowi_pracownicy_30d = parseInt(nowyP.rows[0].cnt);
    stats.wnioski_w_toku = parseInt(wToku.rows[0].cnt);
  }

  res.json(stats);
});

module.exports = router;
