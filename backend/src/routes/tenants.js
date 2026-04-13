'use strict';
const express = require('express');
const { body, param } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { writeAudit } = require('../services/auditService');

const router = express.Router();
const IT = ['IT_ADMIN', 'SUPERADMIN'];

router.get('/', authenticate, async (req, res) => {
  const { rows } = await db.query('SELECT * FROM tenants ORDER BY nazwa');
  res.json(rows);
});

router.get('/:id', authenticate, async (req, res) => {
  const { rows } = await db.query('SELECT * FROM tenants WHERE id = $1', [req.params.id]);
  if (!rows.length) return res.status(404).json({ error: 'Nie znaleziono jednostki.' });
  res.json(rows[0]);
});

router.post('/', authenticate, roleGuard(...IT),
  [
    body('nazwa').notEmpty().trim(),
    body('skrot').notEmpty().trim().isLength({ max: 20 }),
    body('dni_do_przegladu').optional().isInt({ min: 30 }),
  ],
  validate,
  async (req, res) => {
    const { nazwa, skrot, regon, nip, dni_do_przegladu = 365 } = req.body;
    const { rows } = await db.query(
      `INSERT INTO tenants (nazwa, skrot, regon, nip, dni_do_przegladu)
       VALUES ($1,$2,$3,$4,$5) RETURNING *`,
      [nazwa, skrot, regon || null, nip || null, dni_do_przegladu]
    );
    await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'TENANT_CREATE', tabelaDocelowa: 'tenants', rekordId: rows[0].id, noweDane: rows[0] });
    res.status(201).json(rows[0]);
  }
);

router.put('/:id', authenticate, roleGuard(...IT),
  [body('nazwa').notEmpty().trim()],
  validate,
  async (req, res) => {
    const { nazwa, skrot, regon, nip, aktywny, dni_do_przegladu } = req.body;
    const { rows } = await db.query(
      `UPDATE tenants SET nazwa=$1, skrot=$2, regon=$3, nip=$4, aktywny=$5, dni_do_przegladu=$6
       WHERE id=$7 RETURNING *`,
      [nazwa, skrot, regon || null, nip || null, aktywny !== undefined ? aktywny : true, dni_do_przegladu || 365, req.params.id]
    );
    if (!rows.length) return res.status(404).json({ error: 'Nie znaleziono jednostki.' });
    await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'TENANT_UPDATE', tabelaDocelowa: 'tenants', rekordId: rows[0].id, noweDane: rows[0] });
    res.json(rows[0]);
  }
);

router.delete('/:id', authenticate, roleGuard('SUPERADMIN'), async (req, res) => {
  await db.query('UPDATE tenants SET aktywny=FALSE WHERE id=$1', [req.params.id]);
  await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'TENANT_DEACTIVATE', tabelaDocelowa: 'tenants', rekordId: req.params.id });
  res.json({ message: 'Jednostka dezaktywowana.' });
});

module.exports = router;
