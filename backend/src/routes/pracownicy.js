'use strict';
const express = require('express');
const { body } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { writeAudit } = require('../services/auditService');

const router = express.Router();

router.get('/', authenticate, async (req, res) => {
  const { tenant_id, komorka_id, aktywny, q } = req.query;
  const { rola, tenantId } = req.user;
  let query = `SELECT p.id, p.uzytkownik_id, p.tenant_id, p.komorka_id,
                      p.stanowisko, p.data_zatrudnienia, p.data_zwolnienia, p.aktywny,
                      p.przelozony_id,
                      u.imie, u.nazwisko, u.email, u.username, u.rola,
                      k.nazwa as komorka_nazwa, t.nazwa as tenant_nazwa,
                      pr.id as przel_id,
                      pu.imie || ' ' || pu.nazwisko as przel_nazwa
                 FROM pracownicy p
                 JOIN uzytkownicy u ON u.id = p.uzytkownik_id
                 LEFT JOIN komorki_org k ON k.id = p.komorka_id
                 LEFT JOIN tenants t ON t.id = p.tenant_id
                 LEFT JOIN pracownicy pr ON pr.id = p.przelozony_id
                 LEFT JOIN uzytkownicy pu ON pu.id = pr.uzytkownik_id
                WHERE 1=1`;
  const params = [];

  // Tenant scope
  const effectiveTenantId = tenant_id || (['KIEROWNIK','PRACOWNIK'].includes(rola) ? tenantId : null);
  if (effectiveTenantId) { params.push(effectiveTenantId); query += ` AND p.tenant_id = $${params.length}`; }
  if (komorka_id) { params.push(komorka_id); query += ` AND p.komorka_id = $${params.length}`; }
  if (aktywny !== undefined) { params.push(aktywny === 'true'); query += ` AND p.aktywny = $${params.length}`; }
  if (q) { params.push(`%${q}%`); query += ` AND (u.imie ILIKE $${params.length} OR u.nazwisko ILIKE $${params.length} OR u.email ILIKE $${params.length})`; }

  query += ' ORDER BY u.nazwisko, u.imie';
  const { rows } = await db.query(query, params);
  res.json(rows);
});

router.get('/:id', authenticate, async (req, res) => {
  const { rows } = await db.query(
    `SELECT p.*, u.imie, u.nazwisko, u.email, u.username, u.rola,
            k.nazwa as komorka_nazwa, t.nazwa as tenant_nazwa,
            pu.imie || ' ' || pu.nazwisko as przel_nazwa,
            pr.stanowisko as przel_stanowisko
       FROM pracownicy p
       JOIN uzytkownicy u ON u.id = p.uzytkownik_id
       LEFT JOIN komorki_org k ON k.id = p.komorka_id
       LEFT JOIN tenants t ON t.id = p.tenant_id
       LEFT JOIN pracownicy pr ON pr.id = p.przelozony_id
       LEFT JOIN uzytkownicy pu ON pu.id = pr.uzytkownik_id
      WHERE p.id = $1`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Pracownik nie istnieje.' });

  // Get active permissions count
  const { rows: permRows } = await db.query(
    'SELECT COUNT(*) as cnt FROM uprawnienia WHERE pracownik_id=$1 AND aktywne=TRUE',
    [req.params.id]
  );
  res.json({ ...rows[0], liczba_uprawnien: parseInt(permRows[0].cnt) });
});

router.post('/', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN', 'KADRY'),
  [
    body('uzytkownik_id').isInt(),
    body('tenant_id').isInt(),
  ],
  validate,
  async (req, res) => {
    const { uzytkownik_id, tenant_id, komorka_id, stanowisko, data_zatrudnienia, przelozony_id } = req.body;
    const { rows } = await db.query(
      `INSERT INTO pracownicy (uzytkownik_id, tenant_id, komorka_id, stanowisko, data_zatrudnienia, przelozony_id)
       VALUES ($1,$2,$3,$4,$5,$6) RETURNING *`,
      [uzytkownik_id, tenant_id, komorka_id || null, stanowisko || null, data_zatrudnienia || null, przelozony_id || null]
    );
    await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'PRACOWNIK_CREATE', tabelaDocelowa: 'pracownicy', rekordId: rows[0].id, noweDane: req.body });
    res.status(201).json(rows[0]);
  }
);

router.put('/:id', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN', 'KADRY'), async (req, res) => {
  const { komorka_id, stanowisko, data_zatrudnienia, data_zwolnienia, aktywny, przelozony_id } = req.body;
  const { rows: old } = await db.query('SELECT * FROM pracownicy WHERE id=$1', [req.params.id]);
  if (!old.length) return res.status(404).json({ error: 'Pracownik nie istnieje.' });

  const { rows } = await db.query(
    `UPDATE pracownicy SET komorka_id=$1, stanowisko=$2, data_zatrudnienia=$3,
       data_zwolnienia=$4, aktywny=$5, przelozony_id=$6 WHERE id=$7 RETURNING *`,
    [komorka_id || null, stanowisko, data_zatrudnienia, data_zwolnienia || null, aktywny !== false, przelozony_id || null, req.params.id]
  );

  // If termination date set and newly set → initiate departure review
  if (data_zwolnienia && !old[0].data_zwolnienia) {
    // This would trigger an ODEJSCIE review in a production system
    await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'PRACOWNIK_ODEJSCIE', tabelaDocelowa: 'pracownicy', rekordId: req.params.id, noweDane: { data_zwolnienia } });
  }

  await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'PRACOWNIK_UPDATE', tabelaDocelowa: 'pracownicy', rekordId: req.params.id, noweDane: req.body, stareDane: old[0] });
  res.json(rows[0]);
});

// Get subordinates
router.get('/:id/podwladni', authenticate, async (req, res) => {
  const { rows } = await db.query(
    `SELECT p.id, u.imie, u.nazwisko, u.email, p.stanowisko, k.nazwa as komorka_nazwa,
            p.aktywny,
            (SELECT COUNT(*) FROM uprawnienia up WHERE up.pracownik_id = p.id AND up.aktywne = TRUE) as liczba_uprawnien
       FROM pracownicy p
       JOIN uzytkownicy u ON u.id = p.uzytkownik_id
       LEFT JOIN komorki_org k ON k.id = p.komorka_id
      WHERE p.przelozony_id = $1 AND p.aktywny = TRUE
      ORDER BY u.nazwisko`,
    [req.params.id]
  );
  res.json(rows);
});

module.exports = router;
