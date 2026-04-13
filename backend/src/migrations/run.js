'use strict';
require('dotenv').config({ path: require('path').join(__dirname, '../../.env') });
const fs = require('fs');
const path = require('path');
const { Pool } = require('pg');

const pool = new Pool({ connectionString: process.env.DATABASE_URL });

const MIGRATIONS_TABLE = `
  CREATE TABLE IF NOT EXISTS _migrations (
    id        SERIAL PRIMARY KEY,
    filename  VARCHAR(200) NOT NULL UNIQUE,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
  );
`;

async function run() {
  const client = await pool.connect();
  try {
    await client.query(MIGRATIONS_TABLE);

    const dir = __dirname;
    const files = fs.readdirSync(dir)
      .filter(f => f.match(/^\d{3}_.*\.sql$/))
      .sort();

    for (const file of files) {
      const { rows } = await client.query(
        'SELECT id FROM _migrations WHERE filename = $1', [file]
      );
      if (rows.length > 0) {
        console.log(`[SKIP]  ${file}`);
        continue;
      }
      const sql = fs.readFileSync(path.join(dir, file), 'utf8');
      try {
        await client.query('BEGIN');
        await client.query(sql);
        await client.query('INSERT INTO _migrations (filename) VALUES ($1)', [file]);
        await client.query('COMMIT');
        console.log(`[OK]    ${file}`);
      } catch (err) {
        await client.query('ROLLBACK');
        console.error(`[ERROR] ${file}: ${err.message}`);
        process.exit(1);
      }
    }
    console.log('Migrations complete.');
  } finally {
    client.release();
    await pool.end();
  }
}

run().catch(err => { console.error(err); process.exit(1); });
