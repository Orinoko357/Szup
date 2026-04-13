'use strict';
const express = require('express');
const { body } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { encrypt } = require('../config/crypto');
const { testDomain } = require('../services/ldapService');

const router = express.Router();
const IT = ['IT_ADMIN', 'SUPERADMIN'];

router.get('/', authenticate, roleGuard(...IT), async (req, res) => {
  const { rows } = await db.query(
    `SELECT id, nazwa, domena, ldap_url, base_dn, bind_dn, user_filter,
            attr_email, attr_firstname, attr_lastname, attr_username,
            tls, aktywna, kolejnosc
       FROM ldap_domeny ORDER BY kolejnosc`
  );
  res.json(rows);
});

router.post('/', authenticate, roleGuard(...IT),
  [
    body('nazwa').notEmpty().trim(),
    body('domena').notEmpty().trim(),
    body('ldap_url').notEmpty().trim(),
    body('base_dn').notEmpty().trim(),
    body('bind_dn').notEmpty().trim(),
    body('bind_password').notEmpty(),
  ],
  validate,
  async (req, res) => {
    const { nazwa, domena, ldap_url, base_dn, bind_dn, bind_password,
      user_filter, attr_email, attr_firstname, attr_lastname, attr_username,
      tls, tls_ca_cert, kolejnosc } = req.body;

    const enc = encrypt(bind_password);
    const { rows } = await db.query(
      `INSERT INTO ldap_domeny (nazwa, domena, ldap_url, base_dn, bind_dn, bind_password_enc,
         user_filter, attr_email, attr_firstname, attr_lastname, attr_username,
         tls, tls_ca_cert, kolejnosc)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14) RETURNING id, nazwa, domena, aktywna`,
      [nazwa, domena, ldap_url, base_dn, bind_dn, enc,
        user_filter || '(&(objectClass=user)(sAMAccountName=%s))',
        attr_email || 'mail', attr_firstname || 'givenName',
        attr_lastname || 'sn', attr_username || 'sAMAccountName',
        tls || false, tls_ca_cert || null, kolejnosc || 0]
    );
    res.status(201).json(rows[0]);
  }
);

router.put('/:id', authenticate, roleGuard(...IT), async (req, res) => {
  const { rows: old } = await db.query('SELECT * FROM ldap_domeny WHERE id=$1', [req.params.id]);
  if (!old.length) return res.status(404).json({ error: 'Domena nie istnieje.' });

  const { nazwa, domena, ldap_url, base_dn, bind_dn, bind_password,
    user_filter, attr_email, attr_firstname, attr_lastname, attr_username,
    tls, tls_ca_cert, aktywna, kolejnosc } = req.body;

  const enc = bind_password ? encrypt(bind_password) : old[0].bind_password_enc;

  const { rows } = await db.query(
    `UPDATE ldap_domeny SET nazwa=$1, domena=$2, ldap_url=$3, base_dn=$4, bind_dn=$5,
       bind_password_enc=$6, user_filter=$7, attr_email=$8, attr_firstname=$9,
       attr_lastname=$10, attr_username=$11, tls=$12, tls_ca_cert=$13,
       aktywna=$14, kolejnosc=$15
     WHERE id=$16 RETURNING id, nazwa, domena, aktywna`,
    [nazwa, domena, ldap_url, base_dn, bind_dn, enc,
      user_filter, attr_email, attr_firstname, attr_lastname, attr_username,
      tls, tls_ca_cert, aktywna, kolejnosc, req.params.id]
  );
  res.json(rows[0]);
});

router.delete('/:id', authenticate, roleGuard('SUPERADMIN'), async (req, res) => {
  await db.query('DELETE FROM ldap_domeny WHERE id=$1', [req.params.id]);
  res.json({ message: 'Domena usunięta.' });
});

router.post('/:id/test', authenticate, roleGuard(...IT), async (req, res) => {
  try {
    await testDomain(parseInt(req.params.id));
    res.json({ success: true, message: 'Połączenie LDAP działa poprawnie.' });
  } catch (err) {
    res.status(400).json({ success: false, message: err.message || 'Błąd połączenia LDAP.' });
  }
});

module.exports = router;
