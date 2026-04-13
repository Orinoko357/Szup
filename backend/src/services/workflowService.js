'use strict';
const db = require('../config/db');
const { generateNumer } = require('./numeracjaService');
const { createNotification } = require('./notificationService');
const { writeAudit } = require('./auditService');
const logger = require('../config/logger');

/**
 * Resolve the workflow template for a given employee.
 * Returns { szablon, poziomy } or throws 422.
 */
async function resolveSzablon(pracownikId) {
  // Get employee's komorka
  const { rows: pracRows } = await db.query(
    'SELECT komorka_id, tenant_id FROM pracownicy WHERE id = $1',
    [pracownikId]
  );
  if (pracRows.length === 0) throw { status: 404, message: 'Pracownik nie istnieje.' };
  const { komorka_id, tenant_id } = pracRows[0];

  // Look for komorka-specific assignment
  let szablon = null;
  if (komorka_id) {
    const { rows } = await db.query(
      `SELECT ws.* FROM workflow_przypisania wp
         JOIN workflow_szablony ws ON ws.id = wp.szablon_id
       WHERE wp.komorka_id = $1 AND ws.aktywny = TRUE`,
      [komorka_id]
    );
    if (rows.length > 0) szablon = rows[0];
  }

  // Fallback to tenant default
  if (!szablon) {
    const { rows } = await db.query(
      `SELECT ws.* FROM workflow_przypisania wp
         JOIN workflow_szablony ws ON ws.id = wp.szablon_id
       WHERE wp.typ = 'TENANT_DEFAULT' AND wp.tenant_id = $1 AND ws.aktywny = TRUE`,
      [tenant_id]
    );
    if (rows.length > 0) szablon = rows[0];
  }

  if (!szablon) {
    throw {
      status: 422,
      message: 'Brak skonfigurowanej ścieżki zatwierdzania dla tej komórki. Skontaktuj się z IT.',
    };
  }

  const { rows: poziomy } = await db.query(
    `SELECT wl.*, p.id as prac_id,
            u.imie || ' ' || u.nazwisko as zatwierdzajacy_nazwa,
            p.stanowisko as zatwierdzajacy_stanowisko
       FROM workflow_poziomy wl
       LEFT JOIN pracownicy p ON p.id = wl.zatwierdzajacy_id
       LEFT JOIN uzytkownicy u ON u.id = p.uzytkownik_id
      WHERE wl.szablon_id = $1
      ORDER BY wl.kolejnosc`,
    [szablon.id]
  );

  return { szablon, poziomy };
}

/**
 * Create a snapshot of workflow levels into wnioski_etapy.
 * Called inside a transaction.
 */
async function snapshotEtapy(client, wniosekId, poziomy) {
  for (const p of poziomy) {
    await client.query(
      `INSERT INTO wnioski_etapy
         (wniosek_id, kolejnosc, nazwa, zatwierdzajacy_id,
          opcjonalny, opis_warunku_pominiecia,
          przypomnienie_dni, eskalacja_dni, status, data_przypisania)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,
               CASE WHEN $2=1 THEN 'OCZEKUJE' ELSE 'OCZEKUJE' END,
               CASE WHEN $2=1 THEN NOW() ELSE NULL END)`,
      [
        wniosekId,
        p.kolejnosc,
        p.nazwa,
        p.zatwierdzajacy_id,
        p.opcjonalny,
        p.opis_warunku_pominiecia,
        p.przypomnienie_dni,
        p.eskalacja_dni,
      ]
    );
  }
  // Only first stage is active immediately; rest wait
  // Set data_przypisania only for level 1
  await client.query(
    `UPDATE wnioski_etapy
       SET data_przypisania = NOW()
     WHERE wniosek_id = $1 AND kolejnosc = 1`,
    [wniosekId]
  );
}

/**
 * Submit a SZKIC or WYMAGA_POPRAWY wniosek → W_TOKU.
 */
async function submitWniosek(wniosekId, inicjujacyUserId) {
  const client = await db.getClient();
  try {
    await client.query('BEGIN');

    const { rows: wRows } = await client.query(
      'SELECT * FROM wnioski WHERE id = $1 FOR UPDATE',
      [wniosekId]
    );
    if (wRows.length === 0) throw { status: 404, message: 'Wniosek nie istnieje.' };
    const wniosek = wRows[0];
    if (!['SZKIC', 'WYMAGA_POPRAWY'].includes(wniosek.status)) {
      throw { status: 400, message: 'Wniosek nie może być złożony w obecnym statusie.' };
    }

    // Generate numer if not set
    let numer = wniosek.numer;
    if (!numer) {
      numer = await generateNumer(client);
    }

    // Get szablon
    const { szablon, poziomy } = await resolveSzablon(wniosek.pracownik_id);

    // Delete existing etapy if re-submitting
    await client.query('DELETE FROM wnioski_etapy WHERE wniosek_id = $1', [wniosekId]);

    // Create snapshot
    await snapshotEtapy(client, wniosekId, poziomy);

    // Update wniosek
    await client.query(
      `UPDATE wnioski SET
         numer = $1,
         szablon_id = $2,
         status = 'W_TOKU',
         aktualny_etap_kolejnosc = 1,
         data_ostatniej_zmiany = NOW()
       WHERE id = $3`,
      [numer, szablon.id, wniosekId]
    );

    await client.query('COMMIT');

    // Notify first approver
    const firstEtap = poziomy[0];
    if (firstEtap && firstEtap.zatwierdzajacy_id) {
      const { rows: uRows } = await db.query(
        'SELECT uzytkownik_id FROM pracownicy WHERE id = $1',
        [firstEtap.zatwierdzajacy_id]
      );
      if (uRows.length > 0) {
        await createNotification({
          userId: uRows[0].uzytkownik_id,
          typ: 'WNIOSEK_DO_ZATWIERDZENIA',
          tresc: `Nowy wniosek ${numer} oczekuje na Twoją akceptację (Etap 1: ${firstEtap.nazwa || ''}).`,
          link: `/wnioski/${wniosekId}`,
        });
      }
    }

    return { numer, szablon, poziomy };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

/**
 * Approve etap N.
 */
async function zatwierdz(wniosekId, etapKolejnosc, zatwierdzajacyPracownikId, komentarz, userCtx) {
  const client = await db.getClient();
  try {
    await client.query('BEGIN');

    const { rows: wRows } = await client.query(
      'SELECT * FROM wnioski WHERE id = $1 FOR UPDATE',
      [wniosekId]
    );
    if (wRows.length === 0) throw { status: 404, message: 'Wniosek nie istnieje.' };
    const wniosek = wRows[0];
    if (wniosek.status !== 'W_TOKU') throw { status: 400, message: 'Wniosek nie jest w toku.' };

    const { rows: etapRows } = await client.query(
      `SELECT * FROM wnioski_etapy
       WHERE wniosek_id = $1 AND kolejnosc = $2 FOR UPDATE`,
      [wniosekId, etapKolejnosc]
    );
    if (etapRows.length === 0) throw { status: 404, message: 'Etap nie istnieje.' };
    const etap = etapRows[0];

    if (etap.status !== 'OCZEKUJE') throw { status: 400, message: 'Etap nie oczekuje na zatwierdzenie.' };
    if (etap.zatwierdzajacy_id !== zatwierdzajacyPracownikId) {
      throw { status: 403, message: 'Nie jesteś zatwierdzającym tego etapu.' };
    }

    // Mark etap as approved
    await client.query(
      `UPDATE wnioski_etapy
         SET status = 'ZATWIERDZONY', data_akcji = NOW(), komentarz = $1
       WHERE wniosek_id = $2 AND kolejnosc = $3`,
      [komentarz || null, wniosekId, etapKolejnosc]
    );

    // Check if there's a next etap
    const { rows: nextRows } = await client.query(
      `SELECT * FROM wnioski_etapy
       WHERE wniosek_id = $1 AND kolejnosc > $2
       ORDER BY kolejnosc LIMIT 1`,
      [wniosekId, etapKolejnosc]
    );

    if (nextRows.length > 0) {
      // Activate next etap
      const next = nextRows[0];
      await client.query(
        `UPDATE wnioski_etapy
           SET data_przypisania = NOW(), status = 'OCZEKUJE'
         WHERE id = $1`,
        [next.id]
      );
      await client.query(
        `UPDATE wnioski SET aktualny_etap_kolejnosc = $1, data_ostatniej_zmiany = NOW()
         WHERE id = $2`,
        [next.kolejnosc, wniosekId]
      );

      await client.query('COMMIT');

      // Notify next approver
      if (next.zatwierdzajacy_id) {
        const { rows: uRows } = await db.query(
          'SELECT uzytkownik_id FROM pracownicy WHERE id = $1',
          [next.zatwierdzajacy_id]
        );
        if (uRows.length > 0) {
          await createNotification({
            userId: uRows[0].uzytkownik_id,
            typ: 'WNIOSEK_DO_ZATWIERDZENIA',
            tresc: `Wniosek ${wniosek.numer} oczekuje na Twoją akceptację (Etap ${next.kolejnosc}: ${next.nazwa || ''}).`,
            link: `/wnioski/${wniosekId}`,
          });
        }
      }
    } else {
      // Last etap - generate PDF and move to OCZEKUJE_IT
      await client.query(
        `UPDATE wnioski
           SET status = 'OCZEKUJE_IT', aktualny_etap_kolejnosc = NULL,
               data_ostatniej_zmiany = NOW()
         WHERE id = $1`,
        [wniosekId]
      );
      await client.query('COMMIT');

      // Notify IT
      const { rows: itUsers } = await db.query(
        `SELECT id FROM uzytkownicy WHERE rola = 'IT_ADMIN' AND aktywny = TRUE`
      );
      for (const u of itUsers) {
        await createNotification({
          userId: u.id,
          typ: 'WNIOSEK_DO_REALIZACJI',
          tresc: `Wniosek ${wniosek.numer} oczekuje na realizację IT.`,
          link: `/wnioski/${wniosekId}`,
        });
      }

      // Trigger PDF generation asynchronously
      try {
        const pdfService = require('./pdfService');
        await pdfService.generateWniosekPdf(wniosekId, userCtx);
      } catch (pdfErr) {
        logger.error('PDF generation failed', { wniosekId, err: pdfErr.message });
      }
    }

    await writeAudit({
      tenantId: wniosek.tenant_id,
      userId: userCtx.userId,
      username: userCtx.username,
      rola: userCtx.rola,
      akcja: 'ZATWIERDZENIE_ETAPU',
      tabelaDocelowa: 'wnioski_etapy',
      rekordId: etap.id,
      noweDane: { komentarz, etapKolejnosc, wniosekId },
    });

    return { success: true };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

/**
 * Reject wniosek at etap N.
 */
async function odrzuc(wniosekId, etapKolejnosc, zatwierdzajacyPracownikId, powod, userCtx) {
  const client = await db.getClient();
  try {
    await client.query('BEGIN');

    const { rows: wRows } = await client.query(
      'SELECT * FROM wnioski WHERE id = $1 FOR UPDATE',
      [wniosekId]
    );
    if (wRows.length === 0) throw { status: 404, message: 'Wniosek nie istnieje.' };
    const wniosek = wRows[0];

    const { rows: etapRows } = await client.query(
      'SELECT * FROM wnioski_etapy WHERE wniosek_id = $1 AND kolejnosc = $2 FOR UPDATE',
      [wniosekId, etapKolejnosc]
    );
    if (etapRows.length === 0) throw { status: 404, message: 'Etap nie istnieje.' };
    const etap = etapRows[0];

    if (etap.zatwierdzajacy_id !== zatwierdzajacyPracownikId) {
      throw { status: 403, message: 'Nie jesteś zatwierdzającym tego etapu.' };
    }

    await client.query(
      `UPDATE wnioski_etapy
         SET status = 'ODRZUCONY', data_akcji = NOW(), komentarz = $1
       WHERE id = $2`,
      [powod, etap.id]
    );

    await client.query(
      `UPDATE wnioski
         SET status = 'ODRZUCONY',
             odrzucil_id = $1,
             data_odrzucenia = NOW(),
             powod_odrzucenia = $2,
             data_ostatniej_zmiany = NOW()
       WHERE id = $3`,
      [userCtx.userId, powod, wniosekId]
    );

    await client.query('COMMIT');

    // Notify initiator
    const { rows: inicRows } = await db.query(
      `SELECT u.id as uid FROM pracownicy p
         JOIN uzytkownicy u ON u.id = p.uzytkownik_id
       WHERE p.id = $1`,
      [wniosek.inicjujacy_id]
    );
    if (inicRows.length > 0) {
      await createNotification({
        userId: inicRows[0].uid,
        typ: 'WNIOSEK_ODRZUCONY',
        tresc: `Wniosek ${wniosek.numer} został odrzucony. Powód: ${powod}`,
        link: `/wnioski/${wniosekId}`,
      });
    }

    await writeAudit({
      tenantId: wniosek.tenant_id,
      userId: userCtx.userId,
      username: userCtx.username,
      rola: userCtx.rola,
      akcja: 'ODRZUCENIE_WNIOSKU',
      tabelaDocelowa: 'wnioski',
      rekordId: wniosekId,
      noweDane: { powod, etapKolejnosc },
    });

    return { success: true };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

/**
 * Send back for corrections.
 */
async function odeslij(wniosekId, etapKolejnosc, zatwierdzajacyPracownikId, komentarz, userCtx) {
  const client = await db.getClient();
  try {
    await client.query('BEGIN');

    const { rows: wRows } = await client.query(
      'SELECT * FROM wnioski WHERE id = $1 FOR UPDATE',
      [wniosekId]
    );
    if (wRows.length === 0) throw { status: 404, message: 'Wniosek nie istnieje.' };
    const wniosek = wRows[0];

    const { rows: etapRows } = await client.query(
      'SELECT * FROM wnioski_etapy WHERE wniosek_id = $1 AND kolejnosc = $2 FOR UPDATE',
      [wniosekId, etapKolejnosc]
    );
    const etap = etapRows[0];
    if (!etap) throw { status: 404, message: 'Etap nie istnieje.' };
    if (etap.zatwierdzajacy_id !== zatwierdzajacyPracownikId) {
      throw { status: 403, message: 'Nie jesteś zatwierdzającym tego etapu.' };
    }

    await client.query(
      `UPDATE wnioski_etapy
         SET status = 'ODESŁANY', data_akcji = NOW(), komentarz = $1
       WHERE id = $2`,
      [komentarz, etap.id]
    );

    if (etapKolejnosc > 1) {
      // Reactivate previous etap
      await client.query(
        `UPDATE wnioski_etapy
           SET status = 'OCZEKUJE', data_przypisania = NOW(),
               data_akcji = NULL, data_przypomnienia = NULL
         WHERE wniosek_id = $1 AND kolejnosc = $2`,
        [wniosekId, etapKolejnosc - 1]
      );
      await client.query(
        `UPDATE wnioski
           SET aktualny_etap_kolejnosc = $1, data_ostatniej_zmiany = NOW()
         WHERE id = $2`,
        [etapKolejnosc - 1, wniosekId]
      );
      await client.query('COMMIT');

      // Notify previous approver
      const { rows: prevEtap } = await db.query(
        'SELECT zatwierdzajacy_id FROM wnioski_etapy WHERE wniosek_id = $1 AND kolejnosc = $2',
        [wniosekId, etapKolejnosc - 1]
      );
      if (prevEtap.length > 0 && prevEtap[0].zatwierdzajacy_id) {
        const { rows: uRows } = await db.query(
          'SELECT uzytkownik_id FROM pracownicy WHERE id = $1',
          [prevEtap[0].zatwierdzajacy_id]
        );
        if (uRows.length > 0) {
          await createNotification({
            userId: uRows[0].uzytkownik_id,
            typ: 'WNIOSEK_ODESŁANY',
            tresc: `Wniosek ${wniosek.numer} został odesłany do poprawy. Proszę o ponowne zatwierdzenie.`,
            link: `/wnioski/${wniosekId}`,
          });
        }
      }
    } else {
      // Level 1 → requires initiator correction
      await client.query(
        `UPDATE wnioski
           SET status = 'WYMAGA_POPRAWY', aktualny_etap_kolejnosc = NULL,
               data_ostatniej_zmiany = NOW()
         WHERE id = $1`,
        [wniosekId]
      );
      await client.query('COMMIT');

      // Notify initiator
      const { rows: inicRows } = await db.query(
        `SELECT u.id as uid FROM pracownicy p
           JOIN uzytkownicy u ON u.id = p.uzytkownik_id
         WHERE p.id = $1`,
        [wniosek.inicjujacy_id]
      );
      if (inicRows.length > 0) {
        await createNotification({
          userId: inicRows[0].uid,
          typ: 'WNIOSEK_WYMAGA_POPRAWY',
          tresc: `Wniosek ${wniosek.numer} wymaga poprawy. Komentarz: ${komentarz}`,
          link: `/wnioski/${wniosekId}`,
        });
      }
    }

    await writeAudit({
      tenantId: wniosek.tenant_id,
      userId: userCtx.userId,
      username: userCtx.username,
      rola: userCtx.rola,
      akcja: 'ODESLANIE_DO_POPRAWY',
      tabelaDocelowa: 'wnioski',
      rekordId: wniosekId,
      noweDane: { komentarz, etapKolejnosc },
    });

    return { success: true };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

/**
 * Skip an optional etap.
 */
async function pominEtap(wniosekId, etapKolejnosc, zatwierdzajacyPracownikId, powod, userCtx) {
  const client = await db.getClient();
  try {
    await client.query('BEGIN');

    const { rows: wRows } = await client.query(
      'SELECT * FROM wnioski WHERE id = $1 FOR UPDATE',
      [wniosekId]
    );
    const wniosek = wRows[0];
    if (!wniosek) throw { status: 404, message: 'Wniosek nie istnieje.' };

    const { rows: etapRows } = await client.query(
      'SELECT * FROM wnioski_etapy WHERE wniosek_id = $1 AND kolejnosc = $2 FOR UPDATE',
      [wniosekId, etapKolejnosc]
    );
    const etap = etapRows[0];
    if (!etap) throw { status: 404, message: 'Etap nie istnieje.' };
    if (!etap.opcjonalny) throw { status: 400, message: 'Ten etap nie jest opcjonalny.' };

    await client.query(
      `UPDATE wnioski_etapy
         SET status = 'POMINIĘTY', pominiety = TRUE, powod_pominiecia = $1,
             data_akcji = NOW()
       WHERE id = $2`,
      [powod, etap.id]
    );

    // Activate next or OCZEKUJE_IT
    const { rows: nextRows } = await client.query(
      'SELECT * FROM wnioski_etapy WHERE wniosek_id = $1 AND kolejnosc > $2 ORDER BY kolejnosc LIMIT 1',
      [wniosekId, etapKolejnosc]
    );

    if (nextRows.length > 0) {
      const next = nextRows[0];
      await client.query(
        `UPDATE wnioski_etapy SET data_przypisania = NOW() WHERE id = $1`,
        [next.id]
      );
      await client.query(
        `UPDATE wnioski SET aktualny_etap_kolejnosc = $1, data_ostatniej_zmiany = NOW() WHERE id = $2`,
        [next.kolejnosc, wniosekId]
      );
      await client.query('COMMIT');
    } else {
      await client.query(
        `UPDATE wnioski SET status = 'OCZEKUJE_IT', aktualny_etap_kolejnosc = NULL,
                            data_ostatniej_zmiany = NOW() WHERE id = $1`,
        [wniosekId]
      );
      await client.query('COMMIT');
    }

    return { success: true };
  } catch (err) {
    await client.query('ROLLBACK');
    throw err;
  } finally {
    client.release();
  }
}

module.exports = {
  resolveSzablon,
  snapshotEtapy,
  submitWniosek,
  zatwierdz,
  odrzuc,
  odeslij,
  pominEtap,
};
