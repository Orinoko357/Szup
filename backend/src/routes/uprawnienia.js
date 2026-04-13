'use strict';
const express = require('express');
const { body } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { writeAudit } = require('../services/auditService');
const { sendXlsxResponse, sendCsvResponse } = require('../services/excelService');

const router = express.Router();

const COLS = [
  { header: 'Pracownik', key: 'pracownik_nazwa', width: 25 },
  { header: 'Jednostka', key: 'tenant_nazwa', width: 20 },
  { header: 'System', key: 'system_nazwa', width: 20 },
  { header: 'Moduł', key: 'modul_nazwa', width: 18 },
  { header: 'Zakres', key: 'zakres_nazwa', width: 18 },
  { header: 'Uprzywilejowany', key: 'uprzywilejowany', width: 16 },
  { header: 'Data nadania', key: 'data_od', width: 14 },
  { header: 'Nr wniosku', key: 'numer', width: 16 },
  { header: 'Nadane bezpośrednio', key: 'nadane_bezposrednio', width: 20 },
  { header: 'Aktywne', key: 'aktywne', width: 10 },
  { header: 'Data cofnięcia', key: 'data_cofniecia', width: 16 },
];

async function fetchUprawnienia(filters) {
  const { tenant_id, pracownik_id, system_id, aktywne, uprzywilejowany } = filters;
  let q = `SELECT up.id, up.aktywne, up.nadane_bezposrednio, up.data_od, up.data_do,
                  up.data_cofniecia, up.powod_cofniecia, up.wymaga_przegladu,
                  up.data_ostatniego_przegladu, up.wynik_przegladu,
                  u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                  t.nazwa as tenant_nazwa,
                  s.nazwa as system_nazwa,
                  m.nazwa as modul_nazwa,
                  z.nazwa as zakres_nazwa, z.uprzywilejowany,
                  w.numer,
                  un.username as nadane_przez_nazwa
             FROM uprawnienia up
             JOIN pracownicy p ON p.id = up.pracownik_id
             JOIN uzytkownicy u ON u.id = p.uzytkownik_id
             JOIN tenants t ON t.id = up.tenant_id
             JOIN systemy_it s ON s.id = up.system_id
             LEFT JOIN modul_systemu m ON m.id = up.modul_id
             JOIN zakres_uprawnien z ON z.id = up.zakres_id
             LEFT JOIN wnioski w ON w.id = up.wniosek_id
             LEFT JOIN uzytkownicy un ON un.id = up.nadane_przez
            WHERE 1=1`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND up.tenant_id=$${params.length}`; }
  if (pracownik_id) { params.push(pracownik_id); q += ` AND up.pracownik_id=$${params.length}`; }
  if (system_id) { params.push(system_id); q += ` AND up.system_id=$${params.length}`; }
  if (aktywne !== undefined) { params.push(aktywne === 'true' || aktywne === true); q += ` AND up.aktywne=$${params.length}`; }
  if (uprzywilejowany === 'true') q += ` AND z.uprzywilejowany=TRUE`;
  q += ' ORDER BY t.nazwa, u.nazwisko, s.nazwa';
  const { rows } = await db.query(q, params);
  return rows;
}

router.get('/', authenticate, async (req, res) => {
  const { format } = req.query;
  const rows = await fetchUprawnienia(req.query);
  if (format === 'xlsx') return sendXlsxResponse(res, COLS, rows, 'Rejestr_uprawnien', 'Uprawnienia');
  if (format === 'csv') return sendCsvResponse(res, COLS, rows, 'Rejestr_uprawnien');
  res.json(rows);
});

router.get('/:id', authenticate, async (req, res) => {
  const { rows } = await db.query(
    `SELECT up.*, u.imie || ' ' || u.nazwisko as pracownik_nazwa,
            t.nazwa as tenant_nazwa, s.nazwa as system_nazwa,
            m.nazwa as modul_nazwa, z.nazwa as zakres_nazwa, z.uprzywilejowany,
            w.numer
       FROM uprawnienia up
       JOIN pracownicy p ON p.id = up.pracownik_id
       JOIN uzytkownicy u ON u.id = p.uzytkownik_id
       JOIN tenants t ON t.id = up.tenant_id
       JOIN systemy_it s ON s.id = up.system_id
       LEFT JOIN modul_systemu m ON m.id = up.modul_id
       JOIN zakres_uprawnien z ON z.id = up.zakres_id
       LEFT JOIN wnioski w ON w.id = up.wniosek_id
      WHERE up.id=$1`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Uprawnienie nie istnieje.' });
  res.json(rows[0]);
});

// Direct grant (SUPERADMIN or IT_ADMIN, no workflow)
router.post('/nadaj-bezposrednio', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'),
  [
    body('pracownik_id').isInt(),
    body('system_id').isInt(),
    body('zakres_id').isInt(),
  ],
  validate,
  async (req, res) => {
    const { pracownik_id, system_id, modul_id, zakres_id, uzasadnienie, data_od, data_do } = req.body;
    const { rows: pracRows } = await db.query('SELECT tenant_id FROM pracownicy WHERE id=$1', [pracownik_id]);
    if (!pracRows.length) return res.status(404).json({ error: 'Pracownik nie istnieje.' });

    const { rows } = await db.query(
      `INSERT INTO uprawnienia (tenant_id, pracownik_id, system_id, modul_id, zakres_id,
         nadane_bezposrednio, nadane_przez, data_od, data_do)
       VALUES ($1,$2,$3,$4,$5,TRUE,$6,$7,$8) RETURNING *`,
      [pracRows[0].tenant_id, pracownik_id, system_id, modul_id || null, zakres_id,
        req.user.userId, data_od || new Date().toISOString().split('T')[0], data_do || null]
    );

    await writeAudit({
      tenantId: pracRows[0].tenant_id, userId: req.user.userId, username: req.user.username, rola: req.user.rola,
      akcja: req.user.rola === 'SUPERADMIN' ? 'NADANIE_BEZPOSREDNIE_SUPERADMIN' : 'NADANIE_BEZPOSREDNIE_IT',
      tabelaDocelowa: 'uprawnienia', rekordId: rows[0].id,
      noweDane: { pracownik_id, system_id, zakres_id, uzasadnienie },
    });
    res.status(201).json(rows[0]);
  }
);

// Revoke permission
router.post('/:id/cofnij', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'),
  [body('powod').notEmpty()],
  validate,
  async (req, res) => {
    const { powod } = req.body;
    const { rows } = await db.query(
      `UPDATE uprawnienia SET aktywne=FALSE, data_cofniecia=NOW(),
         cofniete_przez=$1, powod_cofniecia=$2 WHERE id=$3 RETURNING *`,
      [req.user.userId, powod, req.params.id]
    );
    if (!rows.length) return res.status(404).json({ error: 'Uprawnienie nie istnieje.' });
    await writeAudit({
      tenantId: rows[0].tenant_id, userId: req.user.userId, username: req.user.username, rola: req.user.rola,
      akcja: 'UPRAWNIENIE_COFNIETE', tabelaDocelowa: 'uprawnienia', rekordId: rows[0].id, noweDane: { powod },
    });
    res.json({ message: 'Uprawnienie cofnięte.' });
  }
);

// Mass revoke on employee departure
router.post('/masowe-cofniecie', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'),
  [body('pracownik_id').isInt(), body('powod').notEmpty()],
  validate,
  async (req, res) => {
    const { pracownik_id, powod } = req.body;
    const { rowCount } = await db.query(
      `UPDATE uprawnienia SET aktywne=FALSE, data_cofniecia=NOW(),
         cofniete_przez=$1, powod_cofniecia=$2
       WHERE pracownik_id=$3 AND aktywne=TRUE`,
      [req.user.userId, powod, pracownik_id]
    );
    await writeAudit({
      userId: req.user.userId, username: req.user.username, rola: req.user.rola,
      akcja: 'MASOWE_COFNIECIE', tabelaDocelowa: 'uprawnienia',
      noweDane: { pracownik_id, powod, liczba: rowCount },
    });
    res.json({ message: `Cofnięto ${rowCount} uprawnień.` });
  }
);

module.exports = router;
