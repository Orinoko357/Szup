'use strict';
const express = require('express');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');

const router = express.Router();

// GET unread (for badge)
router.get('/', authenticate, async (req, res) => {
  const { rows } = await db.query(
    `SELECT * FROM powiadomienia WHERE user_id=$1 AND przeczytane=FALSE
     ORDER BY data_utworzenia DESC LIMIT 20`,
    [req.user.userId]
  );
  const { rows: cnt } = await db.query(
    'SELECT COUNT(*) as cnt FROM powiadomienia WHERE user_id=$1 AND przeczytane=FALSE',
    [req.user.userId]
  );
  res.json({ items: rows, nieprzeczytane: parseInt(cnt[0].cnt) });
});

// GET all (paginated)
router.get('/wszystkie', authenticate, async (req, res) => {
  const { page = 1, limit = 30 } = req.query;
  const offset = (parseInt(page) - 1) * parseInt(limit);
  const { rows } = await db.query(
    `SELECT * FROM powiadomienia WHERE user_id=$1
     ORDER BY data_utworzenia DESC LIMIT $2 OFFSET $3`,
    [req.user.userId, parseInt(limit), offset]
  );
  const { rows: cnt } = await db.query(
    'SELECT COUNT(*) as cnt FROM powiadomienia WHERE user_id=$1',
    [req.user.userId]
  );
  res.json({ items: rows, total: parseInt(cnt[0].cnt) });
});

router.patch('/:id/przeczytaj', authenticate, async (req, res) => {
  await db.query(
    'UPDATE powiadomienia SET przeczytane=TRUE WHERE id=$1 AND user_id=$2',
    [req.params.id, req.user.userId]
  );
  res.json({ message: 'Oznaczono jako przeczytane.' });
});

router.patch('/przeczytaj-wszystkie', authenticate, async (req, res) => {
  const { rowCount } = await db.query(
    'UPDATE powiadomienia SET przeczytane=TRUE WHERE user_id=$1 AND przeczytane=FALSE',
    [req.user.userId]
  );
  res.json({ message: `Oznaczono ${rowCount} powiadomień jako przeczytane.` });
});

module.exports = router;
