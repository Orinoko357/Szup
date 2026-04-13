'use strict';
const crypto = require('crypto');

const ALGORITHM = 'aes-256-gcm';
const KEY_HEX = process.env.LDAP_ENCRYPTION_KEY;

function getKey() {
  if (!KEY_HEX || KEY_HEX.length !== 64) {
    throw new Error('LDAP_ENCRYPTION_KEY must be 32-byte hex (64 hex chars)');
  }
  return Buffer.from(KEY_HEX, 'hex');
}

/**
 * Encrypt plaintext using AES-256-GCM.
 * Returns base64-encoded string: iv(12B) + authTag(16B) + ciphertext
 */
function encrypt(plaintext) {
  const key = getKey();
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv);
  const encrypted = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  const authTag = cipher.getAuthTag();
  return Buffer.concat([iv, authTag, encrypted]).toString('base64');
}

/**
 * Decrypt base64 string produced by encrypt().
 */
function decrypt(encoded) {
  const key = getKey();
  const buf = Buffer.from(encoded, 'base64');
  const iv = buf.slice(0, 12);
  const authTag = buf.slice(12, 28);
  const ciphertext = buf.slice(28);
  const decipher = crypto.createDecipheriv(ALGORITHM, key, iv);
  decipher.setAuthTag(authTag);
  return Buffer.concat([decipher.update(ciphertext), decipher.final()]).toString('utf8');
}

module.exports = { encrypt, decrypt };
