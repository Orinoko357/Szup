'use strict';
const express = require('express');
const { body } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { writeAudit } = require('../services/auditService');
const { notifyIT } = require('../services/notificationService');
const { sendXlsxResponse, sendCsvResponse } = require('../services/excelService');

const router = express.Router();

router.get('/', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { tenant_id, status, format } = req.query;
  let q = `SELECT ri.*, t.nazwa as tenant_nazwa,
                  u.imie || ' ' || u.nazwisko as zglaszajacy_nazwa
             FROM rejestr_incydentow ri
             JOIN tenants t ON t.id = ri.tenant_id
             JOIN uzytkownicy u ON u.id = ri.zglaszajacy_id
            WHERE 1=1`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND ri.tenant_id=$${params.length}`; }
  if (status) { params.push(status); q += ` AND ri.status=$${params.length}`; }
  q += ' ORDER BY ri.data_zgloszenia DESC';
  const { rows } = await db.query(q, params);

  const cols = [
    { header: 'Tytuł', key: 'tytul', width: 30 },
    { header: 'Jednostka', key: 'tenant_nazwa', width: 20 },
    { header: 'Typ', key: 'typ', width: 22 },
    { header: 'Poziom', key: 'poziom', width: 10 },
    { header: 'Status', key: 'status', width: 12 },
    { header: 'Data zgłoszenia', key: 'data_zgloszenia', width: 18 },
    { header: 'NIS2', key: 'dotyczy_nis2', width: 8 },
    { header: 'Zgłaszający', key: 'zglaszajacy_nazwa', width: 22 },
  ];
  if (format === 'xlsx') return sendXlsxResponse(res, cols, rows, 'Rejestr_incydentow', 'Incydenty');
  if (format === 'csv') return sendCsvResponse(res, cols, rows, 'Rejestr_incydentow');
  res.json(rows);
});

router.get('/:id', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { rows } = await db.query(
    `SELECT ri.*, t.nazwa as tenant_nazwa, u.imie || ' ' || u.nazwisko as zglaszajacy_nazwa
       FROM rejestr_incydentow ri
       JOIN tenants t ON t.id = ri.tenant_id
       JOIN uzytkownicy u ON u.id = ri.zglaszajacy_id
      WHERE ri.id=$1`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Incydent nie istnieje.' });
  res.json(rows[0]);
});

router.post('/', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'),
  [
    body('tenant_id').isInt(),
    body('tytul').notEmpty().trim(),
    body('typ').isIn(['NIEAUTORYZOWANY_DOSTEP', 'NADUZYCIE_UPRAWNIEN', 'INNE']),
    body('poziom').isIn(['NISKI', 'SREDNI', 'WYSOKI', 'KRYTYCZNY']),
  ],
  validate,
  async (req, res) => {
    const { tenant_id, tytul, opis, typ, poziom, dotyczy_nis2 } = req.body;
    const { rows } = await db.query(
      `INSERT INTO rejestr_incydentow (tenant_id, tytul, opis, typ, poziom, zglaszajacy_id, dotyczy_nis2)
       VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *`,
      [tenant_id, tytul, opis || null, typ, poziom, req.user.userId, dotyczy_nis2 || false]
    );
    await notifyIT({ typ: 'NOWY_INCYDENT', tresc: `Nowy incydent: ${tytul} (${poziom})`, link: `/incydenty/${rows[0].id}` });
    await writeAudit({ tenantId: tenant_id, userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'INCYDENT_UTWORZONO', tabelaDocelowa: 'rejestr_incydentow', rekordId: rows[0].id, noweDane: rows[0] });
    res.status(201).json(rows[0]);
  }
);

router.put('/:id', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { tytul, opis, typ, poziom, status, dzialania_naprawcze, dotyczy_nis2 } = req.body;
  const dataZamkniecia = status === 'ZAMKNIETY' ? 'NOW()' : 'NULL';
  const { rows } = await db.query(
    `UPDATE rejestr_incydentow SET tytul=$1, opis=$2, typ=$3, poziom=$4, status=$5,
       dzialania_naprawcze=$6, dotyczy_nis2=$7,
       data_zamkniecia = CASE WHEN $5='ZAMKNIETY' THEN NOW() ELSE data_zamkniecia END
     WHERE id=$8 RETURNING *`,
    [tytul, opis || null, typ, poziom, status, dzialania_naprawcze || null, dotyczy_nis2 || false, req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Incydent nie istnieje.' });
  res.json(rows[0]);
});

router.delete('/:id', authenticate, roleGuard('SUPERADMIN'), async (req, res) => {
  await db.query('DELETE FROM rejestr_incydentow WHERE id=$1', [req.params.id]);
  res.json({ message: 'Incydent usunięty.' });
});

module.exports = router;
