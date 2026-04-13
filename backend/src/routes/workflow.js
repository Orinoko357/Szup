'use strict';
const express = require('express');
const { body } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { resolveSzablon } = require('../services/workflowService');
const { writeAudit } = require('../services/auditService');

const router = express.Router();
const IT = ['IT_ADMIN', 'SUPERADMIN'];

// ===== SZABLONY =====

router.get('/szablony', authenticate, async (req, res) => {
  const { tenant_id } = req.query;
  let q = `SELECT ws.*, t.nazwa as tenant_nazwa,
                  COUNT(wp.id) as liczba_przypisań,
                  COUNT(wl.id) as liczba_poziomow
             FROM workflow_szablony ws
             LEFT JOIN tenants t ON t.id = ws.tenant_id
             LEFT JOIN workflow_przypisania wp ON wp.szablon_id = ws.id
             LEFT JOIN workflow_poziomy wl ON wl.szablon_id = ws.id
            WHERE ws.aktywny = TRUE`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND ws.tenant_id = $${params.length}`; }
  q += ' GROUP BY ws.id, t.nazwa ORDER BY ws.tenant_id, ws.nazwa';
  const { rows } = await db.query(q, params);
  res.json(rows);
});

router.get('/szablony/:id', authenticate, async (req, res) => {
  const { rows } = await db.query(
    `SELECT ws.*, t.nazwa as tenant_nazwa FROM workflow_szablony ws
       LEFT JOIN tenants t ON t.id = ws.tenant_id WHERE ws.id = $1`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Szablon nie istnieje.' });

  const { rows: poziomy } = await db.query(
    `SELECT wl.*,
            u.imie || ' ' || u.nazwisko as zatwierdzajacy_nazwa,
            p.stanowisko as zatwierdzajacy_stanowisko
       FROM workflow_poziomy wl
       LEFT JOIN pracownicy p ON p.id = wl.zatwierdzajacy_id
       LEFT JOIN uzytkownicy u ON u.id = p.uzytkownik_id
      WHERE wl.szablon_id = $1 ORDER BY wl.kolejnosc`,
    [req.params.id]
  );
  res.json({ ...rows[0], poziomy });
});

router.post('/szablony', authenticate, roleGuard(...IT),
  [body('tenant_id').isInt(), body('nazwa').notEmpty().trim()],
  validate,
  async (req, res) => {
    const { tenant_id, nazwa, opis } = req.body;
    const { rows } = await db.query(
      `INSERT INTO workflow_szablony (tenant_id, nazwa, opis, utworzony_przez)
       VALUES ($1,$2,$3,$4) RETURNING *`,
      [tenant_id, nazwa, opis || null, req.user.userId]
    );
    await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'WORKFLOW_SZABLON_CREATE', tabelaDocelowa: 'workflow_szablony', rekordId: rows[0].id, noweDane: rows[0] });
    res.status(201).json(rows[0]);
  }
);

router.put('/szablony/:id', authenticate, roleGuard(...IT), async (req, res) => {
  const { nazwa, opis, aktywny } = req.body;
  // Check for in-progress wnioski
  if (aktywny === false) {
    const { rows: inProg } = await db.query(
      `SELECT COUNT(*) as cnt FROM wnioski WHERE szablon_id=$1 AND status IN ('W_TOKU','OCZEKUJE_IT')`,
      [req.params.id]
    );
    if (parseInt(inProg[0].cnt) > 0) {
      return res.status(400).json({ error: 'Szablon jest używany przez wnioski w toku. Nie można dezaktywować.' });
    }
  }
  const { rows } = await db.query(
    'UPDATE workflow_szablony SET nazwa=$1, opis=$2, aktywny=$3 WHERE id=$4 RETURNING *',
    [nazwa, opis || null, aktywny !== false, req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Szablon nie istnieje.' });
  res.json(rows[0]);
});

router.delete('/szablony/:id', authenticate, roleGuard(...IT), async (req, res) => {
  // Check for assignments
  const { rows: assigned } = await db.query(
    'SELECT COUNT(*) as cnt FROM workflow_przypisania WHERE szablon_id=$1', [req.params.id]
  );
  if (parseInt(assigned[0].cnt) > 0) {
    return res.status(400).json({ error: `Szablon jest przypisany do ${assigned[0].cnt} komórek. Najpierw zmień przypisania.` });
  }
  const { rows: inProg } = await db.query(
    `SELECT COUNT(*) as cnt FROM wnioski WHERE szablon_id=$1 AND status IN ('W_TOKU','OCZEKUJE_IT')`,
    [req.params.id]
  );
  if (parseInt(inProg[0].cnt) > 0) {
    return res.status(400).json({ error: 'Szablon jest używany przez wnioski w toku.' });
  }
  await db.query('DELETE FROM workflow_szablony WHERE id=$1', [req.params.id]);
  res.json({ message: 'Szablon usunięty.' });
});

// ===== POZIOMY =====

router.get('/szablony/:id/poziomy', authenticate, async (req, res) => {
  const { rows } = await db.query(
    `SELECT wl.*,
            u.imie || ' ' || u.nazwisko as zatwierdzajacy_nazwa,
            p.stanowisko as zatwierdzajacy_stanowisko
       FROM workflow_poziomy wl
       LEFT JOIN pracownicy p ON p.id = wl.zatwierdzajacy_id
       LEFT JOIN uzytkownicy u ON u.id = p.uzytkownik_id
      WHERE wl.szablon_id = $1 ORDER BY wl.kolejnosc`,
    [req.params.id]
  );
  res.json(rows);
});

router.post('/szablony/:id/poziomy', authenticate, roleGuard(...IT),
  [body('kolejnosc').isInt({ min: 1 })],
  validate,
  async (req, res) => {
    const { kolejnosc, nazwa, zatwierdzajacy_id, opcjonalny, opis_warunku_pominiecia, przypomnienie_dni, eskalacja_dni } = req.body;
    if (eskalacja_dni && przypomnienie_dni && eskalacja_dni < przypomnienie_dni) {
      return res.status(422).json({ error: 'Dni eskalacji muszą być >= dni przypomnienia.' });
    }
    const { rows } = await db.query(
      `INSERT INTO workflow_poziomy (szablon_id, kolejnosc, nazwa, zatwierdzajacy_id,
         opcjonalny, opis_warunku_pominiecia, przypomnienie_dni, eskalacja_dni)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *`,
      [req.params.id, kolejnosc, nazwa || null, zatwierdzajacy_id || null,
        opcjonalny || false, opis_warunku_pominiecia || null, przypomnienie_dni || 3, eskalacja_dni || 7]
    );
    res.status(201).json(rows[0]);
  }
);

router.put('/poziomy/:id', authenticate, roleGuard(...IT), async (req, res) => {
  const { nazwa, zatwierdzajacy_id, opcjonalny, opis_warunku_pominiecia, przypomnienie_dni, eskalacja_dni } = req.body;
  if (eskalacja_dni && przypomnienie_dni && eskalacja_dni < przypomnienie_dni) {
    return res.status(422).json({ error: 'Dni eskalacji muszą być >= dni przypomnienia.' });
  }
  const { rows } = await db.query(
    `UPDATE workflow_poziomy SET nazwa=$1, zatwierdzajacy_id=$2, opcjonalny=$3,
       opis_warunku_pominiecia=$4, przypomnienie_dni=$5, eskalacja_dni=$6
     WHERE id=$7 RETURNING *`,
    [nazwa, zatwierdzajacy_id || null, opcjonalny || false, opis_warunku_pominiecia || null,
      przypomnienie_dni || 3, eskalacja_dni || 7, req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Poziom nie istnieje.' });
  res.json(rows[0]);
});

router.delete('/poziomy/:id', authenticate, roleGuard(...IT), async (req, res) => {
  await db.query('DELETE FROM workflow_poziomy WHERE id=$1', [req.params.id]);
  res.json({ message: 'Poziom usunięty.' });
});

// Reorder levels
router.patch('/szablony/:id/poziomy/reorder', authenticate, roleGuard(...IT),
  [body('kolejnosci').isArray({ min: 1 })],
  validate,
  async (req, res) => {
    const { kolejnosci } = req.body; // [{ id, kolejnosc }]
    const client = await db.getClient();
    try {
      await client.query('BEGIN');
      for (const item of kolejnosci) {
        await client.query(
          'UPDATE workflow_poziomy SET kolejnosc=$1 WHERE id=$2 AND szablon_id=$3',
          [item.kolejnosc, item.id, req.params.id]
        );
      }
      await client.query('COMMIT');
      res.json({ message: 'Kolejność zaktualizowana.' });
    } catch (err) {
      await client.query('ROLLBACK');
      res.status(500).json({ error: 'Błąd aktualizacji kolejności.' });
    } finally {
      client.release();
    }
  }
);

// ===== PRZYPISANIA =====

router.get('/przypisania', authenticate, async (req, res) => {
  const { tenant_id } = req.query;
  let q = `SELECT wp.*, ws.nazwa as szablon_nazwa,
                  k.nazwa as komorka_nazwa, t.nazwa as tenant_nazwa
             FROM workflow_przypisania wp
             JOIN workflow_szablony ws ON ws.id = wp.szablon_id
             LEFT JOIN komorki_org k ON k.id = wp.komorka_id
             LEFT JOIN tenants t ON t.id = wp.tenant_id
            WHERE 1=1`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND wp.tenant_id = $${params.length}`; }
  const { rows } = await db.query(q, params);
  res.json(rows);
});

router.put('/przypisania', authenticate, roleGuard(...IT), async (req, res) => {
  const { szablon_id, typ, komorka_id, tenant_id } = req.body;
  if (typ === 'KOMORKA' && komorka_id) {
    await db.query(
      `INSERT INTO workflow_przypisania (szablon_id, typ, komorka_id, tenant_id)
       VALUES ($1, 'KOMORKA', $2, $3)
       ON CONFLICT (komorka_id) DO UPDATE SET szablon_id=$1`,
      [szablon_id, komorka_id, tenant_id]
    );
  } else if (typ === 'TENANT_DEFAULT') {
    await db.query(
      `INSERT INTO workflow_przypisania (szablon_id, typ, tenant_id)
       VALUES ($1, 'TENANT_DEFAULT', $2)
       ON CONFLICT ON CONSTRAINT uniq_tenant_default DO UPDATE SET szablon_id=$1`,
      [szablon_id, tenant_id]
    );
  }
  res.json({ message: 'Przypisanie zaktualizowane.' });
});

// Resolve workflow for preview
router.get('/resolve/:pracownikId', authenticate, async (req, res) => {
  try {
    const result = await resolveSzablon(parseInt(req.params.pracownikId));
    res.json(result);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

module.exports = router;
