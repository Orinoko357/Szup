'use strict';
const express = require('express');
const { body } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');

const router = express.Router();
const IT = ['IT_ADMIN', 'SUPERADMIN'];

router.get('/', authenticate, async (req, res) => {
  const { tenant_id, struktura_org_id } = req.query;
  let q = `SELECT k.*, s.nazwa as struktura_nazwa, t.nazwa as tenant_nazwa
             FROM komorki_org k
             LEFT JOIN struktura_org s ON s.id = k.struktura_org_id
             JOIN tenants t ON t.id = k.tenant_id
            WHERE 1=1`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND k.tenant_id = $${params.length}`; }
  if (struktura_org_id) { params.push(struktura_org_id); q += ` AND k.struktura_org_id = $${params.length}`; }
  q += ' ORDER BY k.nazwa';
  const { rows } = await db.query(q, params);
  res.json(rows);
});

router.get('/:id', authenticate, async (req, res) => {
  const { rows } = await db.query(
    `SELECT k.*, s.nazwa as struktura_nazwa FROM komorki_org k
       LEFT JOIN struktura_org s ON s.id = k.struktura_org_id WHERE k.id = $1`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Nie znaleziono komórki.' });
  res.json(rows[0]);
});

router.post('/', authenticate, roleGuard(...IT),
  [body('tenant_id').isInt(), body('nazwa').notEmpty().trim()],
  validate,
  async (req, res) => {
    const { tenant_id, struktura_org_id, nazwa, kod } = req.body;
    const { rows } = await db.query(
      `INSERT INTO komorki_org (tenant_id, struktura_org_id, nazwa, kod)
       VALUES ($1,$2,$3,$4) RETURNING *`,
      [tenant_id, struktura_org_id || null, nazwa, kod || null]
    );
    res.status(201).json(rows[0]);
  }
);

router.put('/:id', authenticate, roleGuard(...IT), async (req, res) => {
  const { nazwa, kod, struktura_org_id, aktywna } = req.body;
  const { rows } = await db.query(
    `UPDATE komorki_org SET nazwa=$1, kod=$2, struktura_org_id=$3, aktywna=$4 WHERE id=$5 RETURNING *`,
    [nazwa, kod || null, struktura_org_id || null, aktywna !== false, req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Nie znaleziono komórki.' });
  res.json(rows[0]);
});

router.delete('/:id', authenticate, roleGuard(...IT), async (req, res) => {
  await db.query('UPDATE komorki_org SET aktywna=FALSE WHERE id=$1', [req.params.id]);
  res.json({ message: 'Komórka dezaktywowana.' });
});

module.exports = router;
