'use strict';
const express = require('express');
const { body } = require('express-validator');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { writeAudit } = require('../services/auditService');

const router = express.Router();

router.get('/', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { tenant_id, status } = req.query;
  let q = `SELECT pr.*, t.nazwa as tenant_nazwa,
                  u.imie || ' ' || u.nazwisko as inicjujacy_nazwa,
                  COUNT(pp.id) as liczba_pozycji,
                  COUNT(pp.id) FILTER (WHERE pp.decyzja='POZOSTAW') as pozostaw,
                  COUNT(pp.id) FILTER (WHERE pp.decyzja='COFNIJ') as cofnij,
                  COUNT(pp.id) FILTER (WHERE pp.decyzja='ZMODYFIKUJ') as zmodyfikuj
             FROM przeglady pr
             JOIN tenants t ON t.id = pr.tenant_id
             JOIN uzytkownicy u ON u.id = pr.inicjujacy_id
             LEFT JOIN pozycje_przegladu pp ON pp.przeglad_id = pr.id
            WHERE 1=1`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND pr.tenant_id=$${params.length}`; }
  if (status) { params.push(status); q += ` AND pr.status=$${params.length}`; }
  q += ' GROUP BY pr.id, t.nazwa, u.imie, u.nazwisko ORDER BY pr.data_rozpoczecia DESC';
  const { rows } = await db.query(q, params);
  res.json(rows);
});

router.get('/:id', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { rows } = await db.query(
    `SELECT pr.*, t.nazwa as tenant_nazwa,
            u.imie || ' ' || u.nazwisko as inicjujacy_nazwa
       FROM przeglady pr
       JOIN tenants t ON t.id = pr.tenant_id
       JOIN uzytkownicy u ON u.id = pr.inicjujacy_id
      WHERE pr.id=$1`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Przegląd nie istnieje.' });

  const { rows: pozycje } = await db.query(
    `SELECT pp.*,
            u.imie || ' ' || u.nazwisko as pracownik_nazwa,
            s.nazwa as system_nazwa, z.nazwa as zakres_nazwa, z.uprzywilejowany,
            ud.imie || ' ' || ud.nazwisko as decydent_nazwa
       FROM pozycje_przegladu pp
       JOIN uprawnienia up ON up.id = pp.uprawnienie_id
       JOIN pracownicy p ON p.id = pp.pracownik_id
       JOIN uzytkownicy u ON u.id = p.uzytkownik_id
       JOIN systemy_it s ON s.id = up.system_id
       JOIN zakres_uprawnien z ON z.id = up.zakres_id
       LEFT JOIN uzytkownicy ud ON ud.id = pp.decydent_id
      WHERE pp.przeglad_id=$1 ORDER BY u.nazwisko, s.nazwa`,
    [req.params.id]
  );

  res.json({ ...rows[0], pozycje });
});

// Initiate a review
router.post('/', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'),
  [
    body('tenant_id').isInt(),
    body('typ').isIn(['CYKLICZNY', 'DORAZNY', 'ODEJSCIE']),
  ],
  validate,
  async (req, res) => {
    const { tenant_id, typ, uwagi, pracownik_id, system_id, komorka_id } = req.body;

    const client = await db.getClient();
    try {
      await client.query('BEGIN');
      const { rows: prRows } = await client.query(
        `INSERT INTO przeglady (tenant_id, typ, inicjujacy_id, uwagi)
         VALUES ($1,$2,$3,$4) RETURNING *`,
        [tenant_id, typ, req.user.userId, uwagi || null]
      );
      const przeglad = prRows[0];

      // Collect permissions to review
      let q = `SELECT up.id, up.pracownik_id FROM uprawnienia up
                 JOIN pracownicy p ON p.id = up.pracownik_id
                WHERE up.aktywne=TRUE AND up.tenant_id=$1`;
      const params = [tenant_id];
      if (pracownik_id) { params.push(pracownik_id); q += ` AND up.pracownik_id=$${params.length}`; }
      if (system_id) { params.push(system_id); q += ` AND up.system_id=$${params.length}`; }
      if (komorka_id) { params.push(komorka_id); q += ` AND p.komorka_id=$${params.length}`; }

      const { rows: ups } = await client.query(q, params);
      for (const up of ups) {
        await client.query(
          `INSERT INTO pozycje_przegladu (przeglad_id, uprawnienie_id, pracownik_id)
           VALUES ($1,$2,$3)`,
          [przeglad.id, up.id, up.pracownik_id]
        );
      }

      await client.query('COMMIT');
      await writeAudit({
        tenantId: tenant_id, userId: req.user.userId, username: req.user.username, rola: req.user.rola,
        akcja: 'PRZEGLAD_INICJOWANY', tabelaDocelowa: 'przeglady', rekordId: przeglad.id,
        noweDane: { typ, liczba_pozycji: ups.length },
      });
      res.status(201).json({ ...przeglad, liczba_pozycji: ups.length });
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }
);

// Record decision for a review item
router.patch('/pozycje/:id/decyzja', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'),
  [body('decyzja').isIn(['POZOSTAW', 'COFNIJ', 'ZMODYFIKUJ']), body('uzasadnienie').notEmpty()],
  validate,
  async (req, res) => {
    const { decyzja, uzasadnienie } = req.body;
    const { rows } = await db.query(
      `UPDATE pozycje_przegladu SET decyzja=$1, uzasadnienie=$2,
         data_decyzji=NOW(), decydent_id=$3 WHERE id=$4 RETURNING *`,
      [decyzja, uzasadnienie, req.user.userId, req.params.id]
    );
    if (!rows.length) return res.status(404).json({ error: 'Pozycja nie istnieje.' });

    // Execute decision
    if (decyzja === 'COFNIJ') {
      await db.query(
        `UPDATE uprawnienia SET aktywne=FALSE, data_cofniecia=NOW(),
           cofniete_przez=$1, powod_cofniecia=$2
         WHERE id=$3`,
        [req.user.userId, uzasadnienie, rows[0].uprawnienie_id]
      );
      // Update permission review result
      await db.query(
        `UPDATE uprawnienia SET wynik_przegladu='COFNIJ', data_ostatniego_przegladu=CURRENT_DATE,
           wymaga_przegladu=FALSE WHERE id=$1`,
        [rows[0].uprawnienie_id]
      );
    } else {
      await db.query(
        `UPDATE uprawnienia SET wynik_przegladu=$1, data_ostatniego_przegladu=CURRENT_DATE,
           wymaga_przegladu=FALSE WHERE id=$2`,
        [decyzja, rows[0].uprawnienie_id]
      );
    }
    res.json(rows[0]);
  }
);

// Close review
router.post('/:id/zakoncz', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { rows } = await db.query(
    `UPDATE przeglady SET status='ZAKOŃCZONY', data_zakonczenia=NOW() WHERE id=$1 RETURNING *`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Przegląd nie istnieje.' });
  res.json(rows[0]);
});

// Cancel review
router.post('/:id/anuluj', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { rows } = await db.query(
    `UPDATE przeglady SET status='ANULOWANY', data_zakonczenia=NOW() WHERE id=$1 RETURNING *`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Przegląd nie istnieje.' });
  res.json(rows[0]);
});

module.exports = router;
