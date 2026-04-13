'use strict';
require('dotenv').config({ path: require('path').join(__dirname, '../.env') });
const { Pool } = require('pg');
const bcrypt = require('bcrypt');

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

const USERNAME = process.argv[2] || process.env.INIT_SUPERADMIN_USERNAME;
const PASSWORD = process.argv[3] || process.env.INIT_SUPERADMIN_PASSWORD;

function validatePassword(pw) {
  if (!pw || pw.length < 16) return 'Hasło musi mieć min. 16 znaków.';
  if (!/[A-Z]/.test(pw)) return 'Hasło musi zawierać dużą literę.';
  if (!/[a-z]/.test(pw)) return 'Hasło musi zawierać małą literę.';
  if (!/[0-9]/.test(pw)) return 'Hasło musi zawierać cyfrę.';
  if (!/[^A-Za-z0-9]/.test(pw)) return 'Hasło musi zawierać znak specjalny.';
  return null;
}

async function main() {
  if (!USERNAME || !PASSWORD) {
    console.error('Użycie: node scripts/init-superadmin.js <username> <password>');
    console.error('Lub ustaw zmienne INIT_SUPERADMIN_USERNAME i INIT_SUPERADMIN_PASSWORD w .env');
    process.exit(1);
  }

  const validErr = validatePassword(PASSWORD);
  if (validErr) {
    console.error('Błąd walidacji hasła:', validErr);
    process.exit(1);
  }

  const client = await pool.connect();
  try {
    const { rows } = await client.query(
      "SELECT id FROM uzytkownicy WHERE rola='SUPERADMIN' LIMIT 1"
    );
    if (rows.length > 0) {
      console.error('SUPERADMIN już istnieje. Abort.');
      process.exit(1);
    }

    const hash = await bcrypt.hash(PASSWORD, 12);
    const { rows: inserted } = await client.query(
      `INSERT INTO uzytkownicy (username, imie, nazwisko, email, rola, hash_hasla)
       VALUES ($1, 'Administrator', 'Systemu', $2, 'SUPERADMIN', $3) RETURNING id, username`,
      [USERNAME, `${USERNAME}@localhost`, hash]
    );
    console.log(`SUPERADMIN utworzony: id=${inserted[0].id}, username=${inserted[0].username}`);
  } finally {
    client.release();
    await pool.end();
  }
}

main().catch(err => { console.error(err.message); process.exit(1); });
