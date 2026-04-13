'use strict';
const express = require('express');
const { body, query: qv } = require('express-validator');
const path = require('path');
const fs = require('fs');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { validate } = require('../middleware/validate');
const { writeAudit } = require('../services/auditService');
const wfService = require('../services/workflowService');
const { generateWniosekPdf } = require('../services/pdfService');

const router = express.Router();

// List wnioski
router.get('/', authenticate, async (req, res) => {
  const { rola, tenantId, userId } = req.user;
  const { status, tenant_id, pracownik_id, page = 1, limit = 20 } = req.query;
  const offset = (parseInt(page) - 1) * parseInt(limit);

  let q = `SELECT w.id, w.numer, w.status, w.data_utworzenia, w.data_ostatniej_zmiany,
                  w.aktualny_etap_kolejnosc, w.tenant_id,
                  u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                  ui.imie || ' ' || ui.nazwisko as inicjujacy_nazwa,
                  t.nazwa as tenant_nazwa, t.skrot as tenant_skrot,
                  COUNT(poz.id) as liczba_pozycji
             FROM wnioski w
             JOIN pracownicy p ON p.id = w.pracownik_id
             JOIN uzytkownicy u ON u.id = p.uzytkownik_id
             JOIN pracownicy pi ON pi.id = w.inicjujacy_id
             JOIN uzytkownicy ui ON ui.id = pi.uzytkownik_id
             JOIN tenants t ON t.id = w.tenant_id
             LEFT JOIN pozycje_wniosku poz ON poz.wniosek_id = w.id
            WHERE 1=1`;
  const params = [];

  if (rola === 'KIEROWNIK' || rola === 'PRACOWNIK') {
    // Get pracownik_id for current user
    const { rows: myPrac } = await db.query('SELECT id FROM pracownicy WHERE uzytkownik_id=$1', [userId]);
    if (myPrac.length > 0) {
      params.push(myPrac[0].id);
      q += ` AND (w.inicjujacy_id = $${params.length} OR w.pracownik_id = $${params.length})`;
    }
    params.push(tenantId); q += ` AND w.tenant_id = $${params.length}`;
  } else if (rola !== 'SUPERADMIN' && rola !== 'IT_ADMIN') {
    return res.status(403).json({ error: 'Brak uprawnień.' });
  }

  if (tenant_id && ['IT_ADMIN','SUPERADMIN'].includes(rola)) {
    params.push(tenant_id); q += ` AND w.tenant_id = $${params.length}`;
  }
  if (status) { params.push(status); q += ` AND w.status = $${params.length}`; }
  if (pracownik_id) { params.push(pracownik_id); q += ` AND w.pracownik_id = $${params.length}`; }

  q += ` GROUP BY w.id, u.imie, u.nazwisko, ui.imie, ui.nazwisko, t.nazwa, t.skrot`;
  q += ' ORDER BY w.data_ostatniej_zmiany DESC';

  const countQ = `SELECT COUNT(*) as cnt FROM (${q}) sub`;
  const { rows: countRows } = await db.query(countQ, params);
  const total = parseInt(countRows[0].cnt);

  params.push(parseInt(limit)); q += ` LIMIT $${params.length}`;
  params.push(offset); q += ` OFFSET $${params.length}`;

  const { rows } = await db.query(q, params);
  res.json({ data: rows, total, page: parseInt(page), limit: parseInt(limit) });
});

// Get single wniosek
router.get('/:id', authenticate, async (req, res) => {
  const { rows } = await db.query(
    `SELECT w.*, t.nazwa as tenant_nazwa,
            u.imie || ' ' || u.nazwisko as pracownik_nazwa,
            p.stanowisko, k.nazwa as komorka_nazwa,
            ui.imie || ' ' || ui.nazwisko as inicjujacy_nazwa
       FROM wnioski w
       JOIN pracownicy p ON p.id = w.pracownik_id
       JOIN uzytkownicy u ON u.id = p.uzytkownik_id
       LEFT JOIN komorki_org k ON k.id = p.komorka_id
       JOIN tenants t ON t.id = w.tenant_id
       JOIN pracownicy pi ON pi.id = w.inicjujacy_id
       JOIN uzytkownicy ui ON ui.id = pi.uzytkownik_id
      WHERE w.id = $1`,
    [req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Wniosek nie istnieje.' });
  const w = rows[0];

  const { rows: pozycje } = await db.query(
    `SELECT poz.*, s.nazwa as system_nazwa, m.nazwa as modul_nazwa,
            z.nazwa as zakres_nazwa, z.uprzywilejowany
       FROM pozycje_wniosku poz
       JOIN systemy_it s ON s.id = poz.system_id
       LEFT JOIN modul_systemu m ON m.id = poz.modul_id
       JOIN zakres_uprawnien z ON z.id = poz.zakres_id
      WHERE poz.wniosek_id = $1 ORDER BY s.nazwa`,
    [req.params.id]
  );

  const { rows: etapy } = await db.query(
    `SELECT we.*,
            u.imie || ' ' || u.nazwisko as zatwierdzajacy_nazwa,
            pz.stanowisko as zatwierdzajacy_stanowisko
       FROM wnioski_etapy we
       LEFT JOIN pracownicy pz ON pz.id = we.zatwierdzajacy_id
       LEFT JOIN uzytkownicy u ON u.id = pz.uzytkownik_id
      WHERE we.wniosek_id = $1 ORDER BY we.kolejnosc`,
    [req.params.id]
  );

  res.json({ ...w, pozycje, etapy });
});

// Create wniosek (SZKIC or submit)
router.post('/', authenticate, roleGuard('KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'),
  [
    body('pracownik_id').isInt(),
    body('pozycje').isArray({ min: 1 }),
  ],
  validate,
  async (req, res) => {
    const { pracownik_id, pozycje, uwagi_inicjujacego, zloz = false } = req.body;
    const { userId, tenantId, rola } = req.user;

    // Get inicjujacy pracownik
    const { rows: inicRows } = await db.query(
      'SELECT id, tenant_id FROM pracownicy WHERE uzytkownik_id=$1', [userId]
    );
    if (inicRows.length === 0) return res.status(403).json({ error: 'Nie masz profilu pracownika.' });
    const inicjujacy = inicRows[0];

    // Get pracownik tenant
    const { rows: pracRows } = await db.query('SELECT tenant_id FROM pracownicy WHERE id=$1', [pracownik_id]);
    if (pracRows.length === 0) return res.status(404).json({ error: 'Pracownik nie istnieje.' });
    const efectiveTenantId = pracRows[0].tenant_id;

    const client = await db.getClient();
    try {
      await client.query('BEGIN');

      const { rows: wRows } = await client.query(
        `INSERT INTO wnioski (tenant_id, pracownik_id, inicjujacy_id, status, uwagi_inicjujacego)
         VALUES ($1,$2,$3,'SZKIC',$4) RETURNING *`,
        [efectiveTenantId, pracownik_id, inicjujacy.id, uwagi_inicjujacego || null]
      );
      const wniosekId = wRows[0].id;

      // Insert positions
      for (const p of pozycje) {
        await client.query(
          `INSERT INTO pozycje_wniosku (wniosek_id, system_id, modul_id, zakres_id, uzasadnienie, dodana_przez)
           VALUES ($1,$2,$3,$4,$5,$6)`,
          [wniosekId, p.system_id, p.modul_id || null, p.zakres_id, p.uzasadnienie || null, userId]
        );
      }

      await client.query('COMMIT');

      await writeAudit({ tenantId: efectiveTenantId, userId, username: req.user.username, rola, akcja: 'WNIOSEK_UTWORZONO', tabelaDocelowa: 'wnioski', rekordId: wniosekId, noweDane: { pracownik_id, pozycje: pozycje.length } });

      // Submit immediately if requested
      if (zloz) {
        try {
          await wfService.submitWniosek(wniosekId, userId);
        } catch (err) {
          return res.status(err.status || 500).json({ error: err.message });
        }
      }

      const { rows: finalW } = await db.query('SELECT * FROM wnioski WHERE id=$1', [wniosekId]);
      res.status(201).json(finalW[0]);
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }
);

// Submit (change SZKIC → W_TOKU)
router.post('/:id/submit', authenticate, roleGuard('KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  try {
    const result = await wfService.submitWniosek(parseInt(req.params.id), req.user.userId);
    res.json(result);
  } catch (err) {
    res.status(err.status || 500).json({ error: err.message });
  }
});

// Approve stage
router.post('/:id/zatwierdz', authenticate, roleGuard('KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'),
  [body('etap_kolejnosc').isInt({ min: 1 })],
  validate,
  async (req, res) => {
    const { etap_kolejnosc, komentarz } = req.body;
    const { rows: pracRows } = await db.query('SELECT id FROM pracownicy WHERE uzytkownik_id=$1', [req.user.userId]);
    if (pracRows.length === 0) return res.status(403).json({ error: 'Brak profilu pracownika.' });

    try {
      const result = await wfService.zatwierdz(parseInt(req.params.id), etap_kolejnosc, pracRows[0].id, komentarz, req.user);
      res.json(result);
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  }
);

// Reject
router.post('/:id/odrzuc', authenticate, roleGuard('KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'),
  [body('etap_kolejnosc').isInt(), body('powod').notEmpty()],
  validate,
  async (req, res) => {
    const { etap_kolejnosc, powod } = req.body;
    const { rows: pracRows } = await db.query('SELECT id FROM pracownicy WHERE uzytkownik_id=$1', [req.user.userId]);
    if (pracRows.length === 0) return res.status(403).json({ error: 'Brak profilu pracownika.' });

    try {
      const result = await wfService.odrzuc(parseInt(req.params.id), etap_kolejnosc, pracRows[0].id, powod, req.user);
      res.json(result);
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  }
);

// Send back for corrections
router.post('/:id/odeslij', authenticate, roleGuard('KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'),
  [body('etap_kolejnosc').isInt(), body('komentarz').notEmpty()],
  validate,
  async (req, res) => {
    const { etap_kolejnosc, komentarz } = req.body;
    const { rows: pracRows } = await db.query('SELECT id FROM pracownicy WHERE uzytkownik_id=$1', [req.user.userId]);
    if (pracRows.length === 0) return res.status(403).json({ error: 'Brak profilu pracownika.' });

    try {
      const result = await wfService.odeslij(parseInt(req.params.id), etap_kolejnosc, pracRows[0].id, komentarz, req.user);
      res.json(result);
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  }
);

// Skip optional stage
router.post('/:id/pomin', authenticate, roleGuard('KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'),
  [body('etap_kolejnosc').isInt(), body('powod').notEmpty()],
  validate,
  async (req, res) => {
    const { etap_kolejnosc, powod } = req.body;
    const { rows: pracRows } = await db.query('SELECT id FROM pracownicy WHERE uzytkownik_id=$1', [req.user.userId]);
    if (pracRows.length === 0) return res.status(403).json({ error: 'Brak profilu pracownika.' });

    try {
      const result = await wfService.pominEtap(parseInt(req.params.id), etap_kolejnosc, pracRows[0].id, powod, req.user);
      res.json(result);
    } catch (err) {
      res.status(err.status || 500).json({ error: err.message });
    }
  }
);

// IT: Realize
router.post('/:id/zrealizuj', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'),
  [body('uwagi').optional()],
  async (req, res) => {
    const { uwagi } = req.body;
    const { rows: wRows } = await db.query('SELECT * FROM wnioski WHERE id=$1', [req.params.id]);
    if (!wRows.length) return res.status(404).json({ error: 'Wniosek nie istnieje.' });
    const w = wRows[0];
    if (w.status !== 'OCZEKUJE_IT') return res.status(400).json({ error: 'Wniosek nie oczekuje na realizację IT.' });

    const { rows: pozycje } = await db.query(
      `SELECT poz.*, z.uprzywilejowany FROM pozycje_wniosku poz
         JOIN zakres_uprawnien z ON z.id = poz.zakres_id WHERE poz.wniosek_id=$1`,
      [req.params.id]
    );

    const client = await db.getClient();
    try {
      await client.query('BEGIN');

      for (const p of pozycje) {
        const { rows: upRows } = await client.query(
          `INSERT INTO uprawnienia (tenant_id, pracownik_id, system_id, modul_id, zakres_id, wniosek_id, nadane_przez, data_od)
           VALUES ($1,$2,$3,$4,$5,$6,$7,CURRENT_DATE) RETURNING id`,
          [w.tenant_id, w.pracownik_id, p.system_id, p.modul_id, p.zakres_id, w.id, req.user.userId]
        );
        if (p.uprzywilejowany) {
          await writeAudit({ tenantId: w.tenant_id, userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'NADANIE_UPRZYWILEJOWANEGO', tabelaDocelowa: 'uprawnienia', rekordId: upRows[0].id });
        }
      }

      await client.query(
        `UPDATE wnioski SET status='ZREALIZOWANY', zrealizowal_it_id=$1, data_realizacji=NOW(),
           uwagi_realizacji=$2, data_ostatniej_zmiany=NOW() WHERE id=$3`,
        [req.user.userId, uwagi || null, req.params.id]
      );
      await client.query('COMMIT');

      // Notify initiator
      const { rows: inicRows } = await db.query(
        `SELECT u.id as uid FROM pracownicy p JOIN uzytkownicy u ON u.id=p.uzytkownik_id WHERE p.id=$1`,
        [w.inicjujacy_id]
      );
      if (inicRows.length > 0) {
        const notifSvc = require('../services/notificationService');
        await notifSvc.createNotification({
          userId: inicRows[0].uid,
          typ: 'WNIOSEK_ZREALIZOWANY',
          tresc: `Wniosek ${w.numer} został zrealizowany. Uprawnienia zostały nadane.`,
          link: `/wnioski/${w.id}`,
        });
      }

      await writeAudit({ tenantId: w.tenant_id, userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'WNIOSEK_REALIZACJA', tabelaDocelowa: 'wnioski', rekordId: w.id, noweDane: { uwagi } });

      res.json({ message: 'Wniosek zrealizowany. Uprawnienia nadane.' });
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }
);

// IT: Reject
router.post('/:id/it-odrzuc', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'),
  [body('powod').notEmpty()],
  validate,
  async (req, res) => {
    const { powod } = req.body;
    const { rows } = await db.query('SELECT * FROM wnioski WHERE id=$1', [req.params.id]);
    if (!rows.length) return res.status(404).json({ error: 'Wniosek nie istnieje.' });
    const w = rows[0];

    await db.query(
      `UPDATE wnioski SET status='ODRZUCONY', odrzucil_id=$1, data_odrzucenia=NOW(),
         powod_odrzucenia=$2, data_ostatniej_zmiany=NOW() WHERE id=$3`,
      [req.user.userId, powod, req.params.id]
    );

    await writeAudit({ tenantId: w.tenant_id, userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'WNIOSEK_IT_ODRZUCONY', tabelaDocelowa: 'wnioski', rekordId: w.id, noweDane: { powod } });
    res.json({ message: 'Wniosek odrzucony.' });
  }
);

// Download PDF
router.get('/:id/pdf', authenticate, async (req, res) => {
  const { rows } = await db.query('SELECT pdf_sciezka, numer, tenant_id FROM wnioski WHERE id=$1', [req.params.id]);
  if (!rows.length) return res.status(404).json({ error: 'Wniosek nie istnieje.' });

  let pdfPath = rows[0].pdf_sciezka;
  if (!pdfPath || !fs.existsSync(pdfPath)) {
    // Generate on demand
    try {
      pdfPath = await generateWniosekPdf(parseInt(req.params.id), req.user);
    } catch (err) {
      return res.status(500).json({ error: 'Nie można wygenerować PDF.' });
    }
  }

  res.setHeader('Content-Type', 'application/pdf');
  res.setHeader('Content-Disposition', `inline; filename="${rows[0].numer}.pdf"`);
  fs.createReadStream(pdfPath).pipe(res);
});

// Update positions (by approver during approval)
router.put('/:id/pozycje/:pozId', authenticate, roleGuard('KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { zakres_id, uzasadnienie } = req.body;
  const { rows } = await db.query(
    `UPDATE pozycje_wniosku SET zakres_id=$1, uzasadnienie=$2,
       zmodyfikowana_przez=$3, data_modyfikacji=NOW()
     WHERE id=$4 AND wniosek_id=$5 RETURNING *`,
    [zakres_id, uzasadnienie, req.user.userId, req.params.pozId, req.params.id]
  );
  if (!rows.length) return res.status(404).json({ error: 'Pozycja nie istnieje.' });

  await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'EDYCJA_POZYCJI_PRZEZ_ZATWIERDZAJACEGO', tabelaDocelowa: 'pozycje_wniosku', rekordId: rows[0].id, noweDane: req.body });
  res.json(rows[0]);
});

router.delete('/:id/pozycje/:pozId', authenticate, roleGuard('KIEROWNIK', 'IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { rows } = await db.query('DELETE FROM pozycje_wniosku WHERE id=$1 AND wniosek_id=$2 RETURNING id', [req.params.pozId, req.params.id]);
  if (!rows.length) return res.status(404).json({ error: 'Pozycja nie istnieje.' });
  await writeAudit({ userId: req.user.userId, username: req.user.username, rola: req.user.rola, akcja: 'USUNIECIE_POZYCJI_PRZEZ_ZATWIERDZAJACEGO', tabelaDocelowa: 'pozycje_wniosku', rekordId: req.params.pozId });
  res.json({ message: 'Pozycja usunięta.' });
});

// Pending approvals for current user
router.get('/moje/do-zatwierdzenia', authenticate, async (req, res) => {
  const { rows: pracRows } = await db.query('SELECT id FROM pracownicy WHERE uzytkownik_id=$1', [req.user.userId]);
  if (pracRows.length === 0) return res.json([]);

  const { rows } = await db.query(
    `SELECT w.id, w.numer, w.status, w.data_ostatniej_zmiany,
            we.kolejnosc as etap_kolejnosc, we.nazwa as etap_nazwa, we.data_przypisania,
            u.imie || ' ' || u.nazwisko as pracownik_nazwa,
            t.nazwa as tenant_nazwa, t.skrot
       FROM wnioski_etapy we
       JOIN wnioski w ON w.id = we.wniosek_id
       JOIN pracownicy p ON p.id = w.pracownik_id
       JOIN uzytkownicy u ON u.id = p.uzytkownik_id
       JOIN tenants t ON t.id = w.tenant_id
      WHERE we.zatwierdzajacy_id = $1 AND we.status = 'OCZEKUJE'
        AND w.status = 'W_TOKU'
      ORDER BY we.data_przypisania`,
    [pracRows[0].id]
  );
  res.json(rows);
});

module.exports = router;
