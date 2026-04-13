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
  const { tenant_id } = req.query;
  const where = tenant_id ? 'WHERE s.tenant_id = $1' : '';
  const params = tenant_id ? [tenant_id] : [];
  const { rows } = await db.query(
    `SELECT s.*, t.nazwa as tenant_nazwa
       FROM struktura_org s
       JOIN tenants t ON t.id = s.tenant_id
     ${where}
     ORDER BY s.tenant_id, s.kolejnosc`,
    params
  );
  res.json(rows);
});

router.post('/', authenticate, roleGuard(...IT),
  [
    body('tenant_id').isInt(),
    body('nazwa').notEmpty().trim(),
  ],
  validate,
  async (req, res) => {
    const { tenant_id, nazwa, typ_wezla, nadrzedny_id, kolejnosc } = req.body;
    const { rows } = await db.query(
      `INSERT INTO struktura_org (tenant_id, nazwa, typ_wezla, nadrzedny_id, kolejnosc)
       VALUES ($1,$2,$3,$4,$5) RETURNING *`,
      [tenant_id, nazwa, typ_wezla || 'WYDZIAL', nadrzedny_id || null, kolejnosc || 0]
    );
    res.status(201).json(rows[0]);
  }
);

router.put('/:id', authenticate, roleGuard(...IT),
  [body('nazwa').notEmpty().trim()],
  validate,
  async (req, res) => {
    const { nazwa, typ_wezla, nadrzedny_id, kolejnosc, aktywna } = req.body;
    const { rows } = await db.query(
      `UPDATE struktura_org SET nazwa=$1, typ_wezla=$2, nadrzedny_id=$3,
         kolejnosc=$4, aktywna=$5 WHERE id=$6 RETURNING *`,
      [nazwa, typ_wezla || 'WYDZIAL', nadrzedny_id || null, kolejnosc || 0, aktywna !== false, req.params.id]
    );
    if (!rows.length) return res.status(404).json({ error: 'Nie znaleziono węzła.' });
    res.json(rows[0]);
  }
);

router.delete('/:id', authenticate, roleGuard(...IT), async (req, res) => {
  await db.query('UPDATE struktura_org SET aktywna=FALSE WHERE id=$1', [req.params.id]);
  res.json({ message: 'Węzeł dezaktywowany.' });
});

module.exports = router;
