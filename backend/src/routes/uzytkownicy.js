'use strict';
const express = require('express');
const { body } = require('express-validator');
const crypto = require('crypto');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { writeAudit } = require('../services/auditService');

const router = express.Router();
const IT = ['IT_ADMIN', 'SUPERADMIN'];

router.get('/', authenticate, roleGuard(...IT), async (req, res) => {
  const { tenant_id, rola, aktywny } = req.query;
  let q = `SELECT u.id, u.username, u.imie, u.nazwisko, u.email, u.rola,
                  u.tenant_id, u.aktywny, u.data_utworzenia, u.ostatnie_logowanie,
                  u.nieudane_logowania, u.zablokowany_do,
                  t.nazwa as tenant_nazwa
             FROM uzytkownicy u
             LEFT JOIN tenants t ON t.id = u.tenant_id
            WHERE 1=1`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND u.tenant_id = $${params.length}`; }
  if (rola) { params.push(rola); q += ` AND u.rola = $${params.length}`; }
  if (aktywny !== undefined) { params.push(aktywny === 'true'); q += ` AND u.aktywny = $${params.length}`; }
  q += ' ORDER BY u.nazwisko, u.imie';
  const { rows } = await db.query(q, params);
  res.json(rows);
});

router.get('/:id', authenticate, roleGuard(...IT), async (req, res) => {
  const { rows } = await db.query(
    `SELECT u.*, t.nazwa as tenant_nazwa,
            p.id as pracownik_id, p.stanowisko, p.komorka_id
       FROM uzytkownicy u
       LEFT JOIN tenants t ON t.id = u.tenant_id
       LEFT JOIN pracownicy p ON p.uzytkownik_id = u.id
      WHERE u.id = $1`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Użytkownik nie istnieje.' });
  res.json(rows[0]);
});

router.post('/', authenticate, roleGuard(...IT),
  [
    body('username').notEmpty().trim(),
    body('imie').notEmpty().trim(),
    body('nazwisko').notEmpty().trim(),
    body('email').isEmail().normalizeEmail(),
    body('rola').isIn(['IT_ADMIN','KADRY','KIEROWNIK','PRACOWNIK']),
  ],
  validate,
  async (req, res) => {
    const { username, imie, nazwisko, email, rola, tenant_id } = req.body;
    const { rows } = await db.query(
      `INSERT INTO uzytkownicy (username, imie, nazwisko, email, rola, tenant_id)
       VALUES ($1,$2,$3,$4,$5,$6) RETURNING id, username, imie, nazwisko, email, rola, tenant_id`,
      [username, imie, nazwisko, email, rola, tenant_id || null]
    );
    await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'UZYTKOWNIK_CREATE', tabelaDocelowa: 'uzytkownicy', rekordId: rows[0].id, noweDane: { username, rola, tenant_id } });
    res.status(201).json(rows[0]);
  }
);

router.put('/:id', authenticate, roleGuard(...IT), async (req, res) => {
  const { imie, nazwisko, email, rola, tenant_id, aktywny } = req.body;
  const { rows } = await db.query(
    `UPDATE uzytkownicy SET imie=$1, nazwisko=$2, email=$3, rola=$4, tenant_id=$5, aktywny=$6
     WHERE id=$7 RETURNING id, username, imie, nazwisko, email, rola, tenant_id, aktywny`,
    [imie, nazwisko, email, rola, tenant_id || null, aktywny !== false, req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Użytkownik nie istnieje.' });
  await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'UZYTKOWNIK_UPDATE', tabelaDocelowa: 'uzytkownicy', rekordId: rows[0].id, noweDane: req.body });
  res.json(rows[0]);
});

// Block/unblock user
router.patch('/:id/blokada', authenticate, roleGuard(...IT), async (req, res) => {
  const { zablokowany } = req.body;
  if (zablokowany) {
    await db.query(
      `UPDATE uzytkownicy SET aktywny=FALSE, zablokowany_do=NULL WHERE id=$1`,
      [req.params.id]
    );
  } else {
    await db.query(
      `UPDATE uzytkownicy SET aktywny=TRUE, nieudane_logowania=0, zablokowany_do=NULL WHERE id=$1`,
      [req.params.id]
    );
  }
  await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: zablokowany ? 'UZYTKOWNIK_BLOCK' : 'UZYTKOWNIK_UNBLOCK', tabelaDocelowa: 'uzytkownicy', rekordId: req.params.id });
  res.json({ message: zablokowany ? 'Konto zablokowane.' : 'Konto odblokowane.' });
});

// Revoke all refresh tokens (force logout)
router.post('/:id/revoke-tokens', authenticate, roleGuard(...IT), async (req, res) => {
  await db.query('UPDATE refresh_tokens SET odwolany=TRUE WHERE user_id=$1', [req.params.id]);
  await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'TOKENY_UNIEWAZNIENIE', tabelaDocelowa: 'uzytkownicy', rekordId: req.params.id });
  res.json({ message: 'Tokeny unieważnione.' });
});

module.exports = router;
