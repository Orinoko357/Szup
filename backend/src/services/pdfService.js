'use strict';
const PDFDocument = require('pdfkit');
const fs = require('fs');
const path = require('path');
const db = require('../config/db');
const logger = require('../config/logger');

const PDF_STORAGE_PATH = process.env.PDF_STORAGE_PATH || path.join(__dirname, '../../../storage/pdf');

function ensureDir(dirPath) {
  if (!fs.existsSync(dirPath)) fs.mkdirSync(dirPath, { recursive: true });
}

async function generateWniosekPdf(wniosekId, userCtx) {
  const { rows: wRows } = await db.query(
    `SELECT w.*,
            t.nazwa as tenant_nazwa,
            u.imie || ' ' || u.nazwisko as pracownik_nazwa,
            p.stanowisko,
            k.nazwa as komorka_nazwa,
            p.data_zatrudnienia,
            ui.imie || ' ' || ui.nazwisko as inicjujacy_nazwa
       FROM wnioski w
       JOIN tenants t ON t.id = w.tenant_id
       JOIN pracownicy p ON p.id = w.pracownik_id
       JOIN uzytkownicy u ON u.id = p.uzytkownik_id
       LEFT JOIN komorki_org k ON k.id = p.komorka_id
       JOIN pracownicy pi ON pi.id = w.inicjujacy_id
       JOIN uzytkownicy ui ON ui.id = pi.uzytkownik_id
      WHERE w.id = $1`,
    [wniosekId]
  );
  if (wRows.length === 0) throw new Error('Wniosek not found');
  const w = wRows[0];

  const { rows: pozycje } = await db.query(
    `SELECT poz.*, s.nazwa as system_nazwa, m.nazwa as modul_nazwa,
            z.nazwa as zakres_nazwa, z.uprzywilejowany
       FROM pozycje_wniosku poz
       JOIN systemy_it s ON s.id = poz.system_id
       LEFT JOIN modul_systemu m ON m.id = poz.modul_id
       JOIN zakres_uprawnien z ON z.id = poz.zakres_id
      WHERE poz.wniosek_id = $1
      ORDER BY s.nazwa`,
    [wniosekId]
  );

  const { rows: etapy } = await db.query(
    `SELECT we.*,
            u.imie || ' ' || u.nazwisko as zatw_nazwa,
            p.stanowisko as zatw_stanowisko
       FROM wnioski_etapy we
       LEFT JOIN pracownicy p ON p.id = we.zatwierdzajacy_id
       LEFT JOIN uzytkownicy u ON u.id = p.uzytkownik_id
      WHERE we.wniosek_id = $1
      ORDER BY we.kolejnosc`,
    [wniosekId]
  );

  const dir = path.join(PDF_STORAGE_PATH, String(w.tenant_id));
  ensureDir(dir);
  const filename = `${w.numer.replace(/[\/\\]/g, '_')}.pdf`;
  const filePath = path.join(dir, filename);

  await new Promise((resolve, reject) => {
    const doc = new PDFDocument({ margin: 50, size: 'A4' });
    const stream = fs.createWriteStream(filePath);
    doc.pipe(stream);

    // Header
    doc.fontSize(16).font('Helvetica-Bold')
      .text(w.tenant_nazwa, { align: 'center' });
    doc.fontSize(13).font('Helvetica-Bold')
      .text('WNIOSEK O NADANIE UPRAWNIEŃ W SYSTEMACH TELEINFORMATYCZNYCH', { align: 'center' });
    doc.moveDown(0.5);
    doc.fontSize(11).font('Helvetica')
      .text(`Numer wniosku: ${w.numer}`, { align: 'right' })
      .text(`Data: ${new Date().toLocaleDateString('pl-PL')}`, { align: 'right' });
    doc.moveDown(1);

    // Employee data
    doc.fontSize(12).font('Helvetica-Bold').text('DANE PRACOWNIKA');
    doc.moveTo(50, doc.y).lineTo(545, doc.y).stroke();
    doc.moveDown(0.3);
    doc.fontSize(10).font('Helvetica');
    doc.text(`Imię i nazwisko: ${w.pracownik_nazwa}`);
    doc.text(`Stanowisko: ${w.stanowisko || '—'}`);
    doc.text(`Komórka organizacyjna: ${w.komorka_nazwa || '—'}`);
    doc.text(`Data zatrudnienia: ${w.data_zatrudnienia ? new Date(w.data_zatrudnienia).toLocaleDateString('pl-PL') : '—'}`);
    doc.moveDown(1);

    // Permissions table
    doc.fontSize(12).font('Helvetica-Bold').text('WNIOSKOWANE UPRAWNIENIA');
    doc.moveTo(50, doc.y).lineTo(545, doc.y).stroke();
    doc.moveDown(0.3);

    const colWidths = [120, 90, 100, 70, 115];
    const headers = ['System', 'Moduł', 'Zakres', 'Uprzywilejowany', 'Uzasadnienie'];
    let x = 50;
    doc.fontSize(9).font('Helvetica-Bold');
    headers.forEach((h, i) => {
      doc.text(h, x, doc.y, { width: colWidths[i], lineBreak: false });
      x += colWidths[i];
    });
    doc.moveDown(0.5);
    doc.moveTo(50, doc.y).lineTo(545, doc.y).stroke();
    doc.moveDown(0.2);

    doc.fontSize(9).font('Helvetica');
    for (const p of pozycje) {
      x = 50;
      const rowY = doc.y;
      const cols = [
        p.system_nazwa,
        p.modul_nazwa || '—',
        p.zakres_nazwa,
        p.uprzywilejowany ? 'TAK' : 'NIE',
        p.uzasadnienie || '—',
      ];
      cols.forEach((c, i) => {
        doc.text(c || '—', x, rowY, { width: colWidths[i] - 2, lineBreak: false });
        x += colWidths[i];
      });
      doc.moveDown(0.7);
    }
    doc.moveDown(0.5);

    // Approval history
    doc.fontSize(12).font('Helvetica-Bold').text('HISTORIA ZATWIERDZEŃ');
    doc.moveTo(50, doc.y).lineTo(545, doc.y).stroke();
    doc.moveDown(0.3);
    doc.fontSize(9).font('Helvetica');
    for (const e of etapy) {
      const status = e.status === 'ZATWIERDZONY' ? '✓' : e.status === 'ODRZUCONY' ? '✗' : '○';
      const data = e.data_akcji ? new Date(e.data_akcji).toLocaleDateString('pl-PL') : '—';
      doc.text(`${status} Etap ${e.kolejnosc}: ${e.nazwa || ''} | ${e.zatw_nazwa || '—'} (${e.zatw_stanowisko || '—'}) | ${data}${e.komentarz ? ' | ' + e.komentarz : ''}`);
    }
    doc.moveDown(1);

    // Signature section
    doc.fontSize(12).font('Helvetica-Bold').text('ZATWIERDZENIE KOŃCOWE');
    doc.moveTo(50, doc.y).lineTo(545, doc.y).stroke();
    doc.moveDown(0.5);
    doc.fontSize(10).font('Helvetica');
    const lastApproved = etapy.filter(e => e.status === 'ZATWIERDZONY').pop();
    doc.text(`Imię i nazwisko: ${lastApproved ? lastApproved.zatw_nazwa : '__________________________'}`);
    doc.text(`Stanowisko: ${lastApproved ? lastApproved.zatw_stanowisko : '__________________________'}`);
    doc.text('Data: __________________________');
    doc.moveDown(0.5);
    doc.text('Podpis kwalifikowany złożony poza systemem: □ TAK');
    doc.moveDown(1);
    doc.text('Podpis własnoręczny: ____________________________________________');
    doc.moveDown(1);

    // Footer
    const pageHeight = doc.page.height - doc.page.margins.bottom;
    doc.fontSize(8).font('Helvetica').fillColor('gray')
      .text(
        `Wniosek: ${w.numer} | Wygenerowano: ${new Date().toLocaleString('pl-PL')} | System ZUP v1.0.0`,
        50, pageHeight - 20,
        { align: 'center', width: 495 }
      );

    doc.end();
    stream.on('finish', resolve);
    stream.on('error', reject);
  });

  // Update wniosek with PDF path
  await db.query(
    `UPDATE wnioski
       SET pdf_sciezka = $1,
           pdf_wygenerowany_przez = $2,
           pdf_data_generowania = NOW()
     WHERE id = $3`,
    [filePath, userCtx ? userCtx.userId : null, wniosekId]
  );

  logger.info('PDF generated', { wniosekId, filePath });
  return filePath;
}

module.exports = { generateWniosekPdf };
