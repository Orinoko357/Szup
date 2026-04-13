'use strict';
require('dotenv').config({ path: require('path').join(__dirname, '../.env') });
const { Pool } = require('pg');

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

async function seed() {
  const client = await pool.connect();
  try {
    await client.query('BEGIN');
    console.log('Seeding database...');

    // 1. Tenants
    const { rows: tenants } = await client.query(`
      INSERT INTO tenants (nazwa, skrot, regon, dni_do_przegladu) VALUES
        ('Urząd Miasta Wodzisławia Śląskiego', 'UM',   '271526024', 365),
        ('Miejski Ośrodek Pomocy Społecznej',  'MOPS', '003449876', 365),
        ('Miejski Ośrodek Sportu i Rekreacji', 'MOSiR','003512345', 365),
        ('Centrum Usług Wspólnych',            'CUW',  '380123456', 365)
      ON CONFLICT DO NOTHING RETURNING id, skrot
    `);
    const t = {};
    for (const r of tenants) t[r.skrot] = r.id;
    // Also fetch if already exist
    const { rows: allT } = await client.query('SELECT id, skrot FROM tenants');
    for (const r of allT) t[r.skrot] = r.id;
    console.log('Tenants:', t);

    // 2. Struktura org - UM (2 wydziały × 2 referaty)
    const { rows: [wyd1] } = await client.query(
      `INSERT INTO struktura_org (tenant_id, nazwa, typ_wezla, kolejnosc) VALUES ($1,'Wydział Organizacyjny','WYDZIAL',1) RETURNING id`,
      [t.UM]
    );
    const { rows: [wyd2] } = await client.query(
      `INSERT INTO struktura_org (tenant_id, nazwa, typ_wezla, kolejnosc) VALUES ($1,'Wydział Finansowy','WYDZIAL',2) RETURNING id`,
      [t.UM]
    );
    const { rows: [ref1] } = await client.query(
      `INSERT INTO struktura_org (tenant_id, nazwa, typ_wezla, nadrzedny_id, kolejnosc) VALUES ($1,'Referat Informatyki','REFERAT',$2,1) RETURNING id`,
      [t.UM, wyd1.id]
    );
    const { rows: [ref2] } = await client.query(
      `INSERT INTO struktura_org (tenant_id, nazwa, typ_wezla, nadrzedny_id, kolejnosc) VALUES ($1,'Referat Kadr i Płac','REFERAT',$2,2) RETURNING id`,
      [t.UM, wyd1.id]
    );
    const { rows: [ref3] } = await client.query(
      `INSERT INTO struktura_org (tenant_id, nazwa, typ_wezla, nadrzedny_id, kolejnosc) VALUES ($1,'Referat Budżetu','REFERAT',$2,1) RETURNING id`,
      [t.UM, wyd2.id]
    );
    const { rows: [ref4] } = await client.query(
      `INSERT INTO struktura_org (tenant_id, nazwa, typ_wezla, nadrzedny_id, kolejnosc) VALUES ($1,'Referat Podatków','REFERAT',$2,2) RETURNING id`,
      [t.UM, wyd2.id]
    );

    // 3. Komórki org
    const ins = (tid, sid, n, k) => client.query(
      `INSERT INTO komorki_org (tenant_id, struktura_org_id, nazwa, kod) VALUES ($1,$2,$3,$4) RETURNING id`,
      [tid, sid, n, k]
    );
    const { rows: [k_um_inf] }  = await ins(t.UM,  ref1.id, 'Komórka Informatyki',   'UM-INF');
    const { rows: [k_um_kadry]} = await ins(t.UM,  ref2.id, 'Komórka Kadr',          'UM-KAD');
    const { rows: [k_um_bud] }  = await ins(t.UM,  ref3.id, 'Komórka Budżetu',       'UM-BUD');
    const { rows: [k_um_pod] }  = await ins(t.UM,  ref4.id, 'Komórka Podatków',      'UM-POD');
    const { rows: [k_mops_1] }  = await ins(t.MOPS, null,   'Dział Świadczeń',       'MOPS-SW');
    const { rows: [k_mops_2] }  = await ins(t.MOPS, null,   'Dział Pracy Socjalnej', 'MOPS-PS');
    const { rows: [k_mosir_1] } = await ins(t.MOSiR,null,   'Dział Sportu',          'MOSIR-SP');
    const { rows: [k_cuw_1] }   = await ins(t.CUW,  null,   'Dział Finansowy CUW',   'CUW-FIN');
    const { rows: [k_cuw_2] }   = await ins(t.CUW,  null,   'Dział Kadr CUW',        'CUW-KAD');

    // 4. IT Systems
    const si = (tid, n, lvl, owner) => client.query(
      `INSERT INTO systemy_it (tenant_id, nazwa, poziom_krytycznosci, wlasciciel) VALUES ($1,$2,$3,$4) RETURNING id`,
      [tid, n, lvl, owner]
    );
    const { rows: [sys_efs]  } = await si(null,    'EFS – Elektroniczny Finan. Sys.', 'KRYTYCZNY',  'CUW');
    const { rows: [sys_sekr] } = await si(null,    'SEkretariat',                    'SREDNI',     'UM');
    const { rows: [sys_hr]   } = await si(null,    'System HR',                      'WYSOKI',     'CUW');
    const { rows: [sys_sport]} = await si(t.MOSiR, 'System rezerwacji obiektów',     'NISKI',      'MOSiR');
    const { rows: [sys_si]   } = await si(null,    'SI – System Informacyjny',       'WYSOKI',     'UM');

    // Modules & scopes
    const im = (sid, n) => client.query(`INSERT INTO modul_systemu (system_id, nazwa) VALUES ($1,$2) RETURNING id`, [sid, n]);
    const iz = (sid, mid, n, priv) => client.query(
      `INSERT INTO zakres_uprawnien (system_id, modul_id, nazwa, uprzywilejowany) VALUES ($1,$2,$3,$4) RETURNING id`,
      [sid, mid, n, priv || false]
    );

    const { rows: [m_efs_fin] } = await im(sys_efs.id, 'Moduł Finansowy');
    const { rows: [m_efs_adm] } = await im(sys_efs.id, 'Moduł Administracyjny');
    await iz(sys_efs.id, m_efs_fin.id, 'Odczyt',    false);
    await iz(sys_efs.id, m_efs_fin.id, 'Zapis',     false);
    await iz(sys_efs.id, m_efs_adm.id, 'Administrator', true);

    await iz(sys_hr.id, null, 'Podgląd danych pracowników', false);
    await iz(sys_hr.id, null, 'Edycja danych pracowników',  false);
    await iz(sys_hr.id, null, 'Pełny dostęp (Admin HR)',    true);

    await iz(sys_sekr.id, null, 'Obsługa korespondencji', false);
    await iz(sys_sport.id, null, 'Rezerwacje',             false);
    await iz(sys_si.id, null,    'Odczyt raportów',        false);

    // 5. Users & Employees
    const addUser = (username, imie, nazwisko, rola, tenantId) => client.query(
      `INSERT INTO uzytkownicy (username, imie, nazwisko, email, rola, tenant_id)
       VALUES ($1,$2,$3,$4,$5,$6) RETURNING id`,
      [username, imie, nazwisko, `${username}@szup.local`, rola, tenantId]
    );

    // IT_ADMIN (tenant=UM, cross-tenant)
    const { rows: [it1] } = await addUser('jkowalski_it', 'Jan',    'Kowalski',  'IT_ADMIN',  null);
    const { rows: [it2] } = await addUser('anowak_it',    'Anna',   'Nowak',     'IT_ADMIN',  null);

    // KADRY (tenant=CUW, cross-tenant)
    const { rows: [kad1] } = await addUser('mwisnia_kadry', 'Maria',   'Wiśniewska', 'KADRY', null);
    const { rows: [kad2] } = await addUser('tmazur_kadry',  'Tomasz',  'Mazur',      'KADRY', null);

    // UM employees
    const { rows: [u_um_kier1] } = await addUser('pkrzyz_um',   'Piotr',    'Krzyżanowski', 'KIEROWNIK', t.UM);
    const { rows: [u_um_kier2] } = await addUser('elublin_um',  'Elżbieta', 'Lublin',       'KIEROWNIK', t.UM);
    const { rows: [u_um_p1]   } = await addUser('ajanik_um',    'Aleksandra','Janik',        'PRACOWNIK', t.UM);
    const { rows: [u_um_p2]   } = await addUser('bwojcik_um',   'Bartosz',  'Wójcik',       'PRACOWNIK', t.UM);
    const { rows: [u_um_p3]   } = await addUser('czaplinska_um','Celina',   'Zapłińska',    'PRACOWNIK', t.UM);

    // MOPS employees
    const { rows: [u_mops_kier] } = await addUser('dgadulska_mops','Dorota','Gadulska','KIEROWNIK', t.MOPS);
    const { rows: [u_mops_p1]  } = await addUser('etomala_mops', 'Ewa',   'Tomała',   'PRACOWNIK', t.MOPS);
    const { rows: [u_mops_p2]  } = await addUser('fbroda_mops',  'Filip', 'Broda',    'PRACOWNIK', t.MOPS);

    // MOSiR
    const { rows: [u_mosir_kier] } = await addUser('gwybolt_mosir','Grzegorz','Wybolt','KIEROWNIK', t.MOSiR);
    const { rows: [u_mosir_p1]  } = await addUser('hstaniek_mosir','Helena','Staniek', 'PRACOWNIK', t.MOSiR);

    // CUW
    const { rows: [u_cuw_kier] } = await addUser('ilewicki_cuw','Igor','Lewicki','KIEROWNIK', t.CUW);
    const { rows: [u_cuw_p1]  } = await addUser('jpartyka_cuw', 'Jolanta','Partyka','PRACOWNIK', t.CUW);

    // 6. Pracownicy records
    const ap = (uid, tid, kid, stan, przelId) => client.query(
      `INSERT INTO pracownicy (uzytkownik_id, tenant_id, komorka_id, stanowisko, data_zatrudnienia, przelozony_id)
       VALUES ($1,$2,$3,$4,CURRENT_DATE,$5) RETURNING id`,
      [uid, tid, kid, stan, przelId || null]
    );

    const { rows: [p_it1]       } = await ap(it1.id,          t.UM,    k_um_inf.id,  'Inspektor ds. IT',       null);
    const { rows: [p_it2]       } = await ap(it2.id,          t.UM,    k_um_inf.id,  'Specjalista IT',         p_it1.id);
    const { rows: [p_kad1]      } = await ap(kad1.id,         t.CUW,   k_cuw_2.id,   'Inspektor Kadr',         null);
    const { rows: [p_kad2]      } = await ap(kad2.id,         t.CUW,   k_cuw_2.id,   'Referent Kadr',          p_kad1.id);
    const { rows: [p_um_kier1]  } = await ap(u_um_kier1.id,  t.UM,    k_um_inf.id,  'Naczelnik Wydziału Org.', null);
    const { rows: [p_um_kier2]  } = await ap(u_um_kier2.id,  t.UM,    k_um_bud.id,  'Kierownik Referatu Bud.',  p_um_kier1.id);
    const { rows: [p_um_p1]     } = await ap(u_um_p1.id,     t.UM,    k_um_kadry.id,'Referent',                p_um_kier1.id);
    const { rows: [p_um_p2]     } = await ap(u_um_p2.id,     t.UM,    k_um_bud.id,  'Podinspektor',            p_um_kier2.id);
    const { rows: [p_um_p3]     } = await ap(u_um_p3.id,     t.UM,    k_um_pod.id,  'Inspektor Podatkowy',     p_um_kier2.id);
    const { rows: [p_mops_kier] } = await ap(u_mops_kier.id, t.MOPS,  k_mops_1.id,  'Kierownik Działu',        null);
    const { rows: [p_mops_p1]   } = await ap(u_mops_p1.id,   t.MOPS,  k_mops_1.id,  'Pracownik Socjalny',      p_mops_kier.id);
    const { rows: [p_mops_p2]   } = await ap(u_mops_p2.id,   t.MOPS,  k_mops_2.id,  'Asystent Rodziny',        p_mops_kier.id);
    const { rows: [p_mosir_kier]} = await ap(u_mosir_kier.id,t.MOSiR, k_mosir_1.id, 'Dyrektor',                null);
    const { rows: [p_mosir_p1]  } = await ap(u_mosir_p1.id,  t.MOSiR, k_mosir_1.id, 'Instruktor Sportu',       p_mosir_kier.id);
    const { rows: [p_cuw_kier]  } = await ap(u_cuw_kier.id,  t.CUW,   k_cuw_1.id,   'Kierownik CUW',           null);
    const { rows: [p_cuw_p1]    } = await ap(u_cuw_p1.id,    t.CUW,   k_cuw_1.id,   'Referent Finansowy',      p_cuw_kier.id);

    // 7. Workflow Templates
    const addSzablon = (tid, nazwa, opis) => client.query(
      `INSERT INTO workflow_szablony (tenant_id, nazwa, opis, utworzony_przez)
       VALUES ($1,$2,$3,(SELECT id FROM uzytkownicy WHERE rola='IT_ADMIN' LIMIT 1)) RETURNING id`,
      [tid, nazwa, opis]
    );

    // Single-level for MOPS, MOSiR, CUW
    const { rows: [sz_prosta_mops]  } = await addSzablon(t.MOPS,  'Ścieżka prosta MOPS',  'Jedno zatwierdzenie – Kierownik Działu');
    const { rows: [sz_prosta_mosir] } = await addSzablon(t.MOSiR, 'Ścieżka prosta MOSiR', 'Jedno zatwierdzenie – Dyrektor');
    const { rows: [sz_prosta_cuw]   } = await addSzablon(t.CUW,   'Ścieżka prosta CUW',   'Jedno zatwierdzenie – Kierownik CUW');
    // 2-level for UM referats
    const { rows: [sz_wydz_um]      } = await addSzablon(t.UM,    'Ścieżka wydziałowa UM','Kier. Referatu → Naczelnik');
    // 3-level critical (no assignment)
    const { rows: [sz_kryt_um]      } = await addSzablon(t.UM,    'Ścieżka krytyczna UM', 'Kier. Referatu → Naczelnik → Sekretarz');

    // Workflow levels
    const addPoziom = (sid, kol, nazwa, zatw_id, opc, przyp, esk) => client.query(
      `INSERT INTO workflow_poziomy (szablon_id, kolejnosc, nazwa, zatwierdzajacy_id, opcjonalny, przypomnienie_dni, eskalacja_dni)
       VALUES ($1,$2,$3,$4,$5,$6,$7)`,
      [sid, kol, nazwa, zatw_id, opc || false, przyp || 3, esk || 7]
    );

    await addPoziom(sz_prosta_mops.id,  1, 'Zatwierdzenie Kierownika', p_mops_kier.id,  false, 3, 7);
    await addPoziom(sz_prosta_mosir.id, 1, 'Zatwierdzenie Dyrektora',  p_mosir_kier.id, false, 3, 7);
    await addPoziom(sz_prosta_cuw.id,   1, 'Zatwierdzenie Kierownika CUW', p_cuw_kier.id, false, 3, 7);
    await addPoziom(sz_wydz_um.id,      1, 'Zatwierdzenie Kier. Referatu', p_um_kier2.id, false, 3, 7);
    await addPoziom(sz_wydz_um.id,      2, 'Zatwierdzenie Naczelnika',     p_um_kier1.id, false, 5, 10);
    await addPoziom(sz_kryt_um.id,      1, 'Zatwierdzenie Kier. Referatu', p_um_kier2.id, false, 2, 5);
    await addPoziom(sz_kryt_um.id,      2, 'Zatwierdzenie Naczelnika',     p_um_kier1.id, false, 3, 7);
    await addPoziom(sz_kryt_um.id,      3, 'Zatwierdzenie Sekretarza',     p_um_kier1.id, true,  5, 10);

    // Workflow assignments
    await client.query(
      `INSERT INTO workflow_przypisania (szablon_id, typ, tenant_id) VALUES ($1,'TENANT_DEFAULT',$2)`,
      [sz_prosta_mops.id, t.MOPS]
    );
    await client.query(
      `INSERT INTO workflow_przypisania (szablon_id, typ, tenant_id) VALUES ($1,'TENANT_DEFAULT',$2)`,
      [sz_prosta_mosir.id, t.MOSiR]
    );
    await client.query(
      `INSERT INTO workflow_przypisania (szablon_id, typ, tenant_id) VALUES ($1,'TENANT_DEFAULT',$2)`,
      [sz_prosta_cuw.id, t.CUW]
    );
    await client.query(
      `INSERT INTO workflow_przypisania (szablon_id, typ, tenant_id) VALUES ($1,'TENANT_DEFAULT',$2)`,
      [sz_wydz_um.id, t.UM]
    );
    // Assign wydziałowa to UM referats
    for (const kid of [k_um_inf.id, k_um_kadry.id, k_um_bud.id, k_um_pod.id]) {
      await client.query(
        `INSERT INTO workflow_przypisania (szablon_id, typ, komorka_id, tenant_id) VALUES ($1,'KOMORKA',$2,$3)`,
        [sz_wydz_um.id, kid, t.UM]
      );
    }

    // 8. Inactive LDAP domain
    const { encrypt } = require('../src/config/crypto');
    await client.query(
      `INSERT INTO ldap_domeny (nazwa, domena, ldap_url, base_dn, bind_dn, bind_password_enc, aktywna, kolejnosc)
       VALUES ($1,$2,$3,$4,$5,$6,FALSE,0)`,
      [
        'Active Directory Wodzisław',
        'wodzislaw.local',
        'ldap://dc01.wodzislaw.local:389',
        'DC=wodzislaw,DC=local',
        'CN=ldap-bind,OU=ServiceAccounts,DC=wodzislaw,DC=local',
        encrypt('ChangeMeBeforeUse!1234'),
      ]
    );

    // 9. Sample wnioski
    const { rows: [zakresEfsOdczyt] } = await client.query(
      `SELECT id FROM zakres_uprawnien WHERE nazwa='Odczyt' AND system_id=$1 LIMIT 1`,
      [sys_efs.id]
    );
    const { rows: [zakresHrPodglad] } = await client.query(
      `SELECT id FROM zakres_uprawnien WHERE nazwa='Podgląd danych pracowników' AND system_id=$1 LIMIT 1`,
      [sys_hr.id]
    );

    // SZKIC
    const { rows: [w1] } = await client.query(
      `INSERT INTO wnioski (tenant_id, pracownik_id, inicjujacy_id, status, uwagi_inicjujacego)
       VALUES ($1,$2,$3,'SZKIC','Proszę o nadanie dostępu do EFS') RETURNING id`,
      [t.UM, p_um_p1.id, p_um_kier1.id]
    );
    await client.query(
      `INSERT INTO pozycje_wniosku (wniosek_id, system_id, zakres_id, uzasadnienie, dodana_przez)
       VALUES ($1,$2,$3,'Potrzebny do pracy bieżącej',$4)`,
      [w1.id, sys_efs.id, zakresEfsOdczyt.id, u_um_kier1.id]
    );

    // W_TOKU etap 1
    const { rows: [w2] } = await client.query(
      `INSERT INTO wnioski (tenant_id, pracownik_id, inicjujacy_id, status, numer, szablon_id, aktualny_etap_kolejnosc)
       VALUES ($1,$2,$3,'W_TOKU','INF.0001.2026',$4,1) RETURNING id`,
      [t.UM, p_um_p2.id, p_um_kier2.id, sz_wydz_um.id]
    );
    await client.query(
      `INSERT INTO pozycje_wniosku (wniosek_id, system_id, zakres_id, uzasadnienie, dodana_przez)
       VALUES ($1,$2,$3,'Praca z budżetem',$4)`,
      [w2.id, sys_efs.id, zakresEfsOdczyt.id, u_um_kier2.id]
    );
    await client.query(
      `INSERT INTO wnioski_etapy (wniosek_id, kolejnosc, nazwa, zatwierdzajacy_id, status, data_przypisania)
       VALUES ($1,1,'Zatwierdzenie Kier. Referatu',$2,'OCZEKUJE',NOW()),
              ($1,2,'Zatwierdzenie Naczelnika',$3,'OCZEKUJE',NULL)`,
      [w2.id, p_um_kier2.id, p_um_kier1.id]
    );

    // W_TOKU etap 2 (etap 1 zatwierdzony)
    const { rows: [w3] } = await client.query(
      `INSERT INTO wnioski (tenant_id, pracownik_id, inicjujacy_id, status, numer, szablon_id, aktualny_etap_kolejnosc)
       VALUES ($1,$2,$3,'W_TOKU','INF.0002.2026',$4,2) RETURNING id`,
      [t.UM, p_um_p3.id, p_um_kier2.id, sz_wydz_um.id]
    );
    await client.query(
      `INSERT INTO pozycje_wniosku (wniosek_id, system_id, zakres_id, uzasadnienie, dodana_przez)
       VALUES ($1,$2,$3,'Obsługa podatków',$4)`,
      [w3.id, sys_hr.id, zakresHrPodglad.id, u_um_kier2.id]
    );
    await client.query(
      `INSERT INTO wnioski_etapy (wniosek_id, kolejnosc, nazwa, zatwierdzajacy_id, status, data_przypisania, data_akcji)
       VALUES ($1,1,'Zatwierdzenie Kier. Referatu',$2,'ZATWIERDZONY',NOW() - INTERVAL '2 days',NOW() - INTERVAL '1 day'),
              ($1,2,'Zatwierdzenie Naczelnika',$3,'OCZEKUJE',NOW(),NULL)`,
      [w3.id, p_um_kier2.id, p_um_kier1.id]
    );

    // OCZEKUJE_IT
    const { rows: [w4] } = await client.query(
      `INSERT INTO wnioski (tenant_id, pracownik_id, inicjujacy_id, status, numer, szablon_id)
       VALUES ($1,$2,$3,'OCZEKUJE_IT','INF.0003.2026',$4) RETURNING id`,
      [t.MOPS, p_mops_p1.id, p_mops_kier.id, sz_prosta_mops.id]
    );
    await client.query(
      `INSERT INTO pozycje_wniosku (wniosek_id, system_id, zakres_id, uzasadnienie, dodana_przez)
       VALUES ($1,$2,$3,'Praca z klientami MOPS',$4)`,
      [w4.id, sys_hr.id, zakresHrPodglad.id, u_mops_kier.id]
    );
    await client.query(
      `INSERT INTO wnioski_etapy (wniosek_id, kolejnosc, nazwa, zatwierdzajacy_id, status, data_przypisania, data_akcji)
       VALUES ($1,1,'Zatwierdzenie Kierownika',$2,'ZATWIERDZONY',NOW() - INTERVAL '3 days',NOW() - INTERVAL '1 day')`,
      [w4.id, p_mops_kier.id]
    );

    // 10. Active permissions (for p_mops_p2)
    await client.query(
      `INSERT INTO uprawnienia (tenant_id, pracownik_id, system_id, zakres_id, wniosek_id, nadane_przez, data_od, aktywne)
       VALUES ($1,$2,$3,$4,NULL,(SELECT id FROM uzytkownicy WHERE rola='IT_ADMIN' LIMIT 1),CURRENT_DATE,TRUE)`,
      [t.MOPS, p_mops_p2.id, sys_hr.id, zakresHrPodglad.id]
    );

    // 11. Audit log entries
    const auditEntries = [
      { akcja: 'LOGIN_SUCCESS',    username: 'jkowalski_it',   rola: 'IT_ADMIN',  tabela: 'uzytkownicy',  tenant: t.UM },
      { akcja: 'TENANT_CREATE',    username: 'jkowalski_it',   rola: 'IT_ADMIN',  tabela: 'tenants',      tenant: null },
      { akcja: 'PRACOWNIK_CREATE', username: 'mwisnia_kadry',  rola: 'KADRY',     tabela: 'pracownicy',   tenant: t.UM },
      { akcja: 'WNIOSEK_UTWORZONO',username: 'pkrzyz_um',      rola: 'KIEROWNIK', tabela: 'wnioski',      tenant: t.UM },
      { akcja: 'ZATWIERDZENIE_ETAPU', username: 'elublin_um', rola: 'KIEROWNIK', tabela: 'wnioski_etapy', tenant: t.UM },
    ];
    for (const e of auditEntries) {
      await client.query(
        `INSERT INTO audit_log (tenant_id, username, rola, akcja, tabela_docelowa)
         VALUES ($1,$2,$3,$4,$5)`,
        [e.tenant, e.username, e.rola, e.akcja, e.tabela]
      );
    }

    await client.query('COMMIT');
    console.log('Seed complete!');
  } catch (err) {
    await client.query('ROLLBACK');
    console.error('Seed failed:', err.message);
    throw err;
  } finally {
    client.release();
    await pool.end();
  }
}

seed().catch(err => { console.error(err); process.exit(1); });
