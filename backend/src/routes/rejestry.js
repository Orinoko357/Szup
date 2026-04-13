'use strict';
const express = require('express');
const db = require('../config/db');
const { authenticate } = require('../middleware/auth');
const { roleGuard } = require('../middleware/roleGuard');
const { sendXlsxResponse, sendCsvResponse } = require('../services/excelService');

const router = express.Router();

// 1. IT Systems register
router.get('/systemy', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { tenant_id, format } = req.query;
  let q = `SELECT s.id, s.nazwa, t.nazwa as tenant_nazwa, s.poziom_krytycznosci,
                  s.wlasciciel, s.aktywny, s.data_dodania,
                  COUNT(DISTINCT up.pracownik_id) FILTER (WHERE up.aktywne=TRUE) as aktywni_uzytkownicy,
                  MAX(pr.data_zakonczenia) as ostatni_przeglad
             FROM systemy_it s
             LEFT JOIN tenants t ON t.id = s.tenant_id
             LEFT JOIN uprawnienia up ON up.system_id = s.id
             LEFT JOIN przeglady pr ON pr.tenant_id = s.tenant_id AND pr.status='ZAKOŃCZONY'
            WHERE s.aktywny=TRUE`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND (s.tenant_id=$${params.length} OR s.tenant_id IS NULL)`; }
  q += ' GROUP BY s.id, t.nazwa ORDER BY s.poziom_krytycznosci DESC, s.nazwa';
  const { rows } = await db.query(q, params);

  const cols = [
    { header: 'System', key: 'nazwa', width: 25 },
    { header: 'Jednostka', key: 'tenant_nazwa', width: 20 },
    { header: 'Krytyczność', key: 'poziom_krytycznosci', width: 14 },
    { header: 'Właściciel', key: 'wlasciciel', width: 20 },
    { header: 'Aktywni użytkownicy', key: 'aktywni_uzytkownicy', width: 20 },
    { header: 'Ostatni przegląd', key: 'ostatni_przeglad', width: 18 },
    { header: 'Status', key: 'aktywny', width: 10 },
  ];
  if (format === 'xlsx') return sendXlsxResponse(res, cols, rows, 'Rejestr_systemow', 'Systemy IT');
  if (format === 'csv') return sendCsvResponse(res, cols, rows, 'Rejestr_systemow');
  res.json(rows);
});

// 2. Privileged users register
router.get('/uprzywilejowani', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { tenant_id, format } = req.query;
  let q = `SELECT up.id, up.data_od, up.aktywne,
                  u.imie || ' ' || u.nazwisko as pracownik_nazwa,
                  t.nazwa as tenant_nazwa,
                  s.nazwa as system_nazwa,
                  z.nazwa as zakres_nazwa,
                  w.numer
             FROM uprawnienia up
             JOIN pracownicy p ON p.id = up.pracownik_id
             JOIN uzytkownicy u ON u.id = p.uzytkownik_id
             JOIN tenants t ON t.id = up.tenant_id
             JOIN systemy_it s ON s.id = up.system_id
             JOIN zakres_uprawnien z ON z.id = up.zakres_id
             LEFT JOIN wnioski w ON w.id = up.wniosek_id
            WHERE z.uprzywilejowany=TRUE AND up.aktywne=TRUE`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND up.tenant_id=$${params.length}`; }
  q += ' ORDER BY t.nazwa, u.nazwisko';
  const { rows } = await db.query(q, params);

  const cols = [
    { header: 'Pracownik', key: 'pracownik_nazwa', width: 25 },
    { header: 'Jednostka', key: 'tenant_nazwa', width: 20 },
    { header: 'System', key: 'system_nazwa', width: 20 },
    { header: 'Zakres', key: 'zakres_nazwa', width: 18 },
    { header: 'Data nadania', key: 'data_od', width: 14 },
    { header: 'Nr wniosku', key: 'numer', width: 16 },
    { header: 'Aktywne', key: 'aktywne', width: 10 },
  ];
  if (format === 'xlsx') return sendXlsxResponse(res, cols, rows, 'Uprzywilejowani', 'Uprzywilejowani');
  if (format === 'csv') return sendCsvResponse(res, cols, rows, 'Uprzywilejowani');
  res.json(rows);
});

// 3. Reviews register
router.get('/przeglady', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { tenant_id, format } = req.query;
  let q = `SELECT pr.id, pr.typ, pr.status, pr.data_rozpoczecia, pr.data_zakonczenia,
                  t.nazwa as tenant_nazwa,
                  u.imie || ' ' || u.nazwisko as inicjujacy_nazwa,
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
  q += ' GROUP BY pr.id, t.nazwa, u.imie, u.nazwisko ORDER BY pr.data_rozpoczecia DESC';
  const { rows } = await db.query(q, params);

  const cols = [
    { header: 'Nr', key: 'id', width: 8 },
    { header: 'Jednostka', key: 'tenant_nazwa', width: 20 },
    { header: 'Typ', key: 'typ', width: 12 },
    { header: 'Status', key: 'status', width: 12 },
    { header: 'Data rozp.', key: 'data_rozpoczecia', width: 14 },
    { header: 'Data zak.', key: 'data_zakonczenia', width: 14 },
    { header: 'Inicjujący', key: 'inicjujacy_nazwa', width: 22 },
    { header: 'Pozostaw', key: 'pozostaw', width: 12 },
    { header: 'Cofnij', key: 'cofnij', width: 10 },
    { header: 'Zmodyfikuj', key: 'zmodyfikuj', width: 12 },
  ];
  if (format === 'xlsx') return sendXlsxResponse(res, cols, rows, 'Rejestr_przeglady', 'Przeglądy');
  if (format === 'csv') return sendCsvResponse(res, cols, rows, 'Rejestr_przeglady');
  res.json(rows);
});

// 4. Audit log
router.get('/audit', authenticate, roleGuard('IT_ADMIN', 'SUPERADMIN'), async (req, res) => {
  const { tenant_id, user_id, akcja, tabela, from, to, page = 1, limit = 50, format } = req.query;
  const offset = (parseInt(page) - 1) * parseInt(limit);

  let q = `SELECT al.id, al.timestamp, al.akcja, al.tabela_docelowa, al.rekord_id,
                  al.username, al.rola, al.ip_adres,
                  t.nazwa as tenant_nazwa,
                  al.stare_dane, al.nowe_dane
             FROM audit_log al
             LEFT JOIN tenants t ON t.id = al.tenant_id
            WHERE 1=1`;
  const params = [];
  if (tenant_id) { params.push(tenant_id); q += ` AND al.tenant_id=$${params.length}`; }
  if (user_id) { params.push(user_id); q += ` AND al.user_id=$${params.length}`; }
  if (akcja) { params.push(`%${akcja}%`); q += ` AND al.akcja ILIKE $${params.length}`; }
  if (tabela) { params.push(tabela); q += ` AND al.tabela_docelowa=$${params.length}`; }
  if (from) { params.push(from); q += ` AND al.timestamp>=$${params.length}`; }
  if (to) { params.push(to); q += ` AND al.timestamp<=$${params.length}`; }
  q += ' ORDER BY al.timestamp DESC';

  if (!format) {
    const cq = `SELECT COUNT(*) as cnt FROM (${q}) sub`;
    const { rows: cRows } = await db.query(cq, params);
    params.push(parseInt(limit)); q += ` LIMIT $${params.length}`;
    params.push(offset); q += ` OFFSET $${params.length}`;
    const { rows } = await db.query(q, params);
    return res.json({ data: rows, total: parseInt(cRows[0].cnt), page: parseInt(page), limit: parseInt(limit) });
  }

  const { rows } = await db.query(q, params);
  const cols = [
    { header: 'Timestamp', key: 'timestamp', width: 20 },
    { header: 'Akcja', key: 'akcja', width: 25 },
    { header: 'Użytkownik', key: 'username', width: 18 },
    { header: 'Rola', key: 'rola', width: 12 },
    { header: 'Tabela', key: 'tabela_docelowa', width: 18 },
    { header: 'Rekord ID', key: 'rekord_id', width: 12 },
    { header: 'Jednostka', key: 'tenant_nazwa', width: 20 },
    { header: 'IP', key: 'ip_adres', width: 15 },
  ];
  if (format === 'xlsx') return sendXlsxResponse(res, cols, rows, 'Audit_log', 'Audit Log');
  if (format === 'csv') return sendCsvResponse(res, cols, rows, 'Audit_log');
  res.json(rows);
});

module.exports = router;
