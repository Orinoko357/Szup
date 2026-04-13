'use strict';
const express = require('express');
const bcrypt = require('bcrypt');
const crypto = require('crypto');
const { body } = require('express-validator');
const db = require('../config/db');
const { signAccess, signRefresh, verifyRefresh } = require('../config/jwt');
const { writeAudit } = require('../services/auditService');
const { ldapAuthenticate } = require('../services/ldapService');
const { validate } = require('../middleware/validate');
const { authLimiter } = require('../middleware/rateLimiter');
const { authenticate } = require('../middleware/auth');
const logger = require('../config/logger');

const router = express.Router();

function buildTokens(user) {
  const payload = {
    userId: user.id,
    username: user.username,
    email: user.email,
    rola: user.rola,
    tenantId: user.tenant_id || null,
  };
  return {
    accessToken: signAccess(payload),
    refreshPayload: payload,
  };
}

async function storeRefreshToken(userId, token) {
  const hash = crypto.createHash('sha256').update(token).digest('hex');
  const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);
  await db.query(
    `INSERT INTO refresh_tokens (user_id, token_hash, wygasa)
     VALUES ($1, $2, $3)`,
    [userId, hash, expiresAt]
  );
  return hash;
}

// POST /api/auth/login — local SUPERADMIN login
router.post('/login',
  authLimiter,
  [
    body('username').notEmpty().trim(),
    body('password').notEmpty(),
  ],
  validate,
  async (req, res) => {
    const { username, password } = req.body;
    const ip = req.ip;
    try {
      const { rows } = await db.query(
        `SELECT * FROM uzytkownicy WHERE username = $1 AND rola = 'SUPERADMIN'`,
        [username]
      );
      const user = rows[0];

      if (!user) {
        await writeAudit({ akcja: 'LOGIN_FAIL', noweDane: { username, reason: 'NOT_FOUND' }, ipAdres: ip });
        return res.status(401).json({ error: 'Nieprawidłowe dane logowania.' });
      }
      if (!user.aktywny) {
        return res.status(403).json({ error: 'Konto zablokowane.' });
      }
      if (user.zablokowany_do && new Date(user.zablokowany_do) > new Date()) {
        return res.status(403).json({ error: `Konto zablokowane do ${new Date(user.zablokowany_do).toLocaleString('pl-PL')}.` });
      }

      const valid = await bcrypt.compare(password, user.hash_hasla);
      if (!valid) {
        const fails = user.nieudane_logowania + 1;
        const updates = fails >= 5
          ? { nieudane_logowania: fails, zablokowany_do: new Date(Date.now() + 15 * 60 * 1000) }
          : { nieudane_logowania: fails };
        await db.query(
          `UPDATE uzytkownicy SET nieudane_logowania=$1, zablokowany_do=$2 WHERE id=$3`,
          [updates.nieudane_logowania, updates.zablokowany_do || null, user.id]
        );
        await writeAudit({ userId: user.id, username, akcja: 'LOGIN_FAIL', noweDane: { reason: 'WRONG_PASSWORD' }, ipAdres: ip });
        return res.status(401).json({ error: 'Nieprawidłowe dane logowania.' });
      }

      // Success
      await db.query(
        `UPDATE uzytkownicy SET nieudane_logowania=0, zablokowany_do=NULL, ostatnie_logowanie=NOW() WHERE id=$1`,
        [user.id]
      );

      const { accessToken, refreshPayload } = buildTokens(user);
      const refreshToken = signRefresh(refreshPayload);
      await storeRefreshToken(user.id, refreshToken);

      res.cookie('refreshToken', refreshToken, {
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'strict',
        maxAge: 7 * 24 * 60 * 60 * 1000,
      });

      await writeAudit({ userId: user.id, username, rola: user.rola, akcja: 'LOGIN_SUCCESS', ipAdres: ip });
      res.json({ accessToken, user: { id: user.id, username: user.username, rola: user.rola, imie: user.imie, nazwisko: user.nazwisko } });
    } catch (err) {
      logger.error('Login error', err);
      res.status(500).json({ error: 'Błąd serwera.' });
    }
  }
);

// POST /api/auth/ldap-login
router.post('/ldap-login',
  authLimiter,
  [
    body('username').notEmpty().trim(),
    body('password').notEmpty(),
  ],
  validate,
  async (req, res) => {
    const { username, password, domena_id } = req.body;
    const ip = req.ip;
    try {
      // Try LDAP auth
      let ldapResult;
      try {
        ldapResult = await ldapAuthenticate(username, password, domena_id || null);
      } catch (ldapErr) {
        // Find user for fail logging
        const { rows } = await db.query('SELECT id FROM uzytkownicy WHERE username=$1', [username]);
        if (rows.length > 0) {
          const u = rows[0];
          const fails = (await db.query('SELECT nieudane_logowania FROM uzytkownicy WHERE id=$1', [u.id])).rows[0].nieudane_logowania + 1;
          const lockUntil = fails >= 5 ? new Date(Date.now() + 15 * 60 * 1000) : null;
          await db.query(
            'UPDATE uzytkownicy SET nieudane_logowania=$1, zablokowany_do=$2 WHERE id=$3',
            [fails, lockUntil, u.id]
          );
        }
        await writeAudit({ akcja: 'LDAP_LOGIN_FAIL', noweDane: { username, reason: ldapErr.message }, ipAdres: ip });
        return res.status(401).json({ error: ldapErr.message || 'Błąd uwierzytelniania LDAP.' });
      }

      // Find user in DB by email or username
      const { rows: userRows } = await db.query(
        `SELECT * FROM uzytkownicy WHERE email = $1 OR username = $2 LIMIT 1`,
        [ldapResult.email, username]
      );
      const user = userRows[0];

      if (!user) {
        await writeAudit({ akcja: 'LDAP_LOGIN_FAIL', noweDane: { username, reason: 'NO_LOCAL_ACCOUNT' }, ipAdres: ip });
        return res.status(401).json({ error: 'Brak konta. Skontaktuj się z IT.' });
      }
      if (!user.aktywny) {
        return res.status(403).json({ error: 'Konto zablokowane.' });
      }
      if (user.zablokowany_do && new Date(user.zablokowany_do) > new Date()) {
        return res.status(403).json({ error: `Konto zablokowane do ${new Date(user.zablokowany_do).toLocaleString('pl-PL')}.` });
      }

      await db.query(
        'UPDATE uzytkownicy SET nieudane_logowania=0, zablokowany_do=NULL, ostatnie_logowanie=NOW() WHERE id=$1',
        [user.id]
      );

      const { accessToken, refreshPayload } = buildTokens(user);
      const refreshToken = signRefresh(refreshPayload);
      await storeRefreshToken(user.id, refreshToken);

      res.cookie('refreshToken', refreshToken, {
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        sameSite: 'strict',
        maxAge: 7 * 24 * 60 * 60 * 1000,
      });

      await writeAudit({ userId: user.id, username: user.username, rola: user.rola, akcja: 'LDAP_LOGIN_SUCCESS', ipAdres: ip });
      res.json({ accessToken, user: { id: user.id, username: user.username, rola: user.rola, imie: user.imie, nazwisko: user.nazwisko, tenantId: user.tenant_id } });
    } catch (err) {
      logger.error('LDAP login error', err);
      res.status(500).json({ error: 'Błąd serwera.' });
    }
  }
);

// POST /api/auth/refresh
router.post('/refresh', async (req, res) => {
  const token = req.cookies.refreshToken;
  if (!token) return res.status(401).json({ error: 'Brak refresh tokenu.' });
  try {
    const payload = verifyRefresh(token);
    const hash = crypto.createHash('sha256').update(token).digest('hex');
    const { rows } = await db.query(
      `SELECT rt.*, u.aktywny FROM refresh_tokens rt
         JOIN uzytkownicy u ON u.id = rt.user_id
       WHERE rt.token_hash = $1 AND rt.odwolany = FALSE AND rt.wygasa > NOW()`,
      [hash]
    );
    if (rows.length === 0) {
      res.clearCookie('refreshToken');
      return res.status(401).json({ error: 'Token nieważny lub wygasły.' });
    }
    if (!rows[0].aktywny) return res.status(403).json({ error: 'Konto zablokowane.' });

    const { rows: userRows } = await db.query('SELECT * FROM uzytkownicy WHERE id = $1', [payload.userId]);
    const user = userRows[0];
    const { accessToken, refreshPayload } = buildTokens(user);
    const newRefresh = signRefresh(refreshPayload);
    const newHash = crypto.createHash('sha256').update(newRefresh).digest('hex');
    const expiresAt = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000);

    await db.query('UPDATE refresh_tokens SET odwolany=TRUE WHERE token_hash=$1', [hash]);
    await db.query('INSERT INTO refresh_tokens (user_id, token_hash, wygasa) VALUES ($1,$2,$3)', [user.id, newHash, expiresAt]);

    res.cookie('refreshToken', newRefresh, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'strict',
      maxAge: 7 * 24 * 60 * 60 * 1000,
    });
    res.json({ accessToken });
  } catch (err) {
    res.clearCookie('refreshToken');
    res.status(401).json({ error: 'Token nieważny.' });
  }
});

// POST /api/auth/logout
router.post('/logout', authenticate, async (req, res) => {
  const token = req.cookies.refreshToken;
  if (token) {
    const hash = crypto.createHash('sha256').update(token).digest('hex');
    await db.query('UPDATE refresh_tokens SET odwolany=TRUE WHERE token_hash=$1', [hash]);
  }
  res.clearCookie('refreshToken');
  await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'LOGOUT', ipAdres: req.ip });
  res.json({ message: 'Wylogowano.' });
});

// GET /api/auth/me
router.get('/me', authenticate, async (req, res) => {
  const { rows } = await db.query(
    `SELECT u.id, u.username, u.imie, u.nazwisko, u.email, u.rola, u.tenant_id,
            p.id as pracownik_id, p.stanowisko, p.komorka_id, k.nazwa as komorka_nazwa
       FROM uzytkownicy u
       LEFT JOIN pracownicy p ON p.uzytkownik_id = u.id
       LEFT JOIN komorki_org k ON k.id = p.komorka_id
      WHERE u.id = $1`,
    [req.user.userId]
  );
  if (rows.length === 0) return res.status(404).json({ error: 'Użytkownik nie istnieje.' });
  res.json(rows[0]);
});

// GET /api/auth/ldap-domains — public list for login form
router.get('/ldap-domains', async (req, res) => {
  const { rows } = await db.query(
    'SELECT id, nazwa, domena FROM ldap_domeny WHERE aktywna = TRUE ORDER BY kolejnosc'
  );
  res.json(rows);
});

module.exports = router;
