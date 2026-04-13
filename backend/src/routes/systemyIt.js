'use strict';
const express = require('express');
const { body } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { writeAudit } = require('../services/auditService');

const router = express.Router();
const IT = ['IT_ADMIN', 'SUPERADMIN'];

router.get('/', authenticate, async (req, res) => {
  const { tenant_id } = req.query;
  let q = `SELECT s.*, u.imie || ' ' || u.nazwisko as dodany_przez_nazwa,
                  COUNT(DISTINCT z.id) as liczba_zakresow
             FROM systemy_it s
             LEFT JOIN uzytkownicy u ON u.id = s.dodany_przez
             LEFT JOIN zakres_uprawnien z ON z.system_id = s.id
            WHERE s.aktywny = TRUE`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND (s.tenant_id = $${params.length} OR s.tenant_id IS NULL)`; }
  q += ' GROUP BY s.id, u.imie, u.nazwisko ORDER BY s.nazwa';
  const { rows } = await db.query(q, params);
  res.json(rows);
});

router.get('/:id', authenticate, async (req, res) => {
  const { rows } = await db.query('SELECT * FROM systemy_it WHERE id=$1', [req.params.id]);
  if (!rows.length) return res.status(404).json({ error: 'System nie istnieje.' });

  const { rows: moduly } = await db.query('SELECT * FROM modul_systemu WHERE system_id=$1 ORDER BY nazwa', [req.params.id]);
  const { rows: zakresy } = await db.query(
    `SELECT z.*, m.nazwa as modul_nazwa FROM zakres_uprawnien z
       LEFT JOIN modul_systemu m ON m.id = z.modul_id
      WHERE z.system_id=$1 ORDER BY z.nazwa`,
    [req.params.id]
  );
  res.json({ ...rows[0], moduly, zakresy });
});

router.post('/', authenticate, roleGuard(...IT),
  [body('nazwa').notEmpty().trim(), body('poziom_krytycznosci').isIn(['NISKI','SREDNI','WYSOKI','KRYTYCZNY'])],
  validate,
  async (req, res) => {
    const { tenant_id, nazwa, opis, wlasciciel, poziom_krytycznosci } = req.body;
    const { rows } = await db.query(
      `INSERT INTO systemy_it (tenant_id, nazwa, opis, wlasciciel, poziom_krytycznosci, dodany_przez)
       VALUES ($1,$2,$3,$4,$5,$6) RETURNING *`,
      [tenant_id || null, nazwa, opis || null, wlasciciel || null, poziom_krytycznosci, req.user.userId]
    );
    await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'SYSTEM_IT_CREATE', tabelaDocelowa: 'systemy_it', rekordId: rows[0].id, noweDane: rows[0] });
    res.status(201).json(rows[0]);
  }
);

router.put('/:id', authenticate, roleGuard(...IT), async (req, res) => {
  const { nazwa, opis, wlasciciel, poziom_krytycznosci, aktywny, tenant_id } = req.body;
  const { rows } = await db.query(
    `UPDATE systemy_it SET nazwa=$1, opis=$2, wlasciciel=$3, poziom_krytycznosci=$4,
       aktywny=$5, tenant_id=$6 WHERE id=$7 RETURNING *`,
    [nazwa, opis, wlasciciel, poziom_krytycznosci, aktywny !== false, tenant_id || null, req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'System nie istnieje.' });
  res.json(rows[0]);
});

// Modules CRUD
router.post('/:id/moduly', authenticate, roleGuard(...IT),
  [body('nazwa').notEmpty().trim()],
  validate,
  async (req, res) => {
    const { nazwa, opis } = req.body;
    const { rows } = await db.query(
      'INSERT INTO modul_systemu (system_id, nazwa, opis) VALUES ($1,$2,$3) RETURNING *',
      [req.params.id, nazwa, opis || null]
    );
    res.status(201).json(rows[0]);
  }
);

router.put('/moduly/:id', authenticate, roleGuard(...IT), async (req, res) => {
  const { nazwa, opis, aktywny } = req.body;
  const { rows } = await db.query(
    'UPDATE modul_systemu SET nazwa=$1, opis=$2, aktywny=$3 WHERE id=$4 RETURNING *',
    [nazwa, opis || null, aktywny !== false, req.params.id]
  );
  res.json(rows[0]);
});

// Scopes CRUD
router.post('/:id/zakresy', authenticate, roleGuard(...IT),
  [body('nazwa').notEmpty().trim()],
  validate,
  async (req, res) => {
    const { nazwa, opis, modul_id, uprzywilejowany } = req.body;
    const { rows } = await db.query(
      'INSERT INTO zakres_uprawnien (system_id, modul_id, nazwa, opis, uprzywilejowany) VALUES ($1,$2,$3,$4,$5) RETURNING *',
      [req.params.id, modul_id || null, nazwa, opis || null, uprzywilejowany || false]
    );
    res.status(201).json(rows[0]);
  }
);

router.put('/zakresy/:id', authenticate, roleGuard(...IT), async (req, res) => {
  const { nazwa, opis, modul_id, uprzywilejowany } = req.body;
  const { rows } = await db.query(
    'UPDATE zakres_uprawnien SET nazwa=$1, opis=$2, modul_id=$3, uprzywilejowany=$4 WHERE id=$5 RETURNING *',
    [nazwa, opis || null, modul_id || null, uprzywilejowany || false, req.params.id]
  );
  res.json(rows[0]);
});

module.exports = router;
