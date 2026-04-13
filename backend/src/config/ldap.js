'use strict';
const ldap = require('ldapjs');
const { decrypt } = require('./crypto');
const logger = require('./logger');

/**
 * Authenticate a user against a single LDAP domain config.
 * Returns { dn, email, firstname, lastname, username } or throws.
 */
async function authenticateAgainstDomain(domainCfg, username, password) {
  const bindPassword = decrypt(domainCfg.bind_password_enc);

  return new Promise((resolve, reject) => {
    const opts = {
      url: domainCfg.ldap_url,
      tlsOptions: domainCfg.tls && domainCfg.tls_ca_cert
        ? { ca: [domainCfg.tls_ca_cert] }
        : {},
    };

    const serviceClient = ldap.createClient(opts);

    serviceClient.on('error', (err) => {
      reject(new Error(`LDAP connection error: ${err.message}`));
    });

    // Step 1: service bind
    serviceClient.bind(domainCfg.bind_dn, bindPassword, (bindErr) => {
      if (bindErr) {
        serviceClient.destroy();
        return reject(new Error(`Service bind failed: ${bindErr.message}`));
      }

      const filter = domainCfg.user_filter.replace(/%s/g, ldap.escape(username));
      const searchOpts = {
        filter,
        scope: 'sub',
        attributes: [
          domainCfg.attr_email,
          domainCfg.attr_firstname,
          domainCfg.attr_lastname,
          domainCfg.attr_username,
          'dn',
        ],
      };

      serviceClient.search(domainCfg.base_dn, searchOpts, (searchErr, res) => {
        if (searchErr) {
          serviceClient.destroy();
          return reject(new Error(`LDAP search failed: ${searchErr.message}`));
        }

        const entries = [];
        res.on('searchEntry', (entry) => entries.push(entry));
        res.on('error', (err) => {
          serviceClient.destroy();
          reject(new Error(`LDAP search error: ${err.message}`));
        });
        res.on('end', () => {
          serviceClient.destroy();
          if (entries.length === 0) {
            return reject(new Error('User not found in LDAP'));
          }
          const entry = entries[0];
          const userDn = entry.dn.toString();
          const attrs = entry.pojo ? entry.pojo.attributes : entry.attributes;
          const getAttr = (name) => {
            const found = attrs.find(a => a.type === name);
            return found ? (found.values || found.vals || [])[0] || '' : '';
          };

          // Step 2: bind with user credentials
          const userClient = ldap.createClient(opts);
          userClient.on('error', (err2) => {
            reject(new Error(`User bind error: ${err2.message}`));
          });
          userClient.bind(userDn, password, (userBindErr) => {
            userClient.destroy();
            if (userBindErr) {
              return reject(new Error('Invalid credentials'));
            }
            resolve({
              dn: userDn,
              email: getAttr(domainCfg.attr_email),
              firstname: getAttr(domainCfg.attr_firstname),
              lastname: getAttr(domainCfg.attr_lastname),
              username: getAttr(domainCfg.attr_username) || username,
            });
          });
        });
      });
    });
  });
}

/**
 * Test LDAP connection (service bind only).
 */
async function testConnection(domainCfg) {
  const bindPassword = decrypt(domainCfg.bind_password_enc);
  return new Promise((resolve, reject) => {
    const client = ldap.createClient({ url: domainCfg.ldap_url });
    client.on('error', (err) => reject(err));
    client.bind(domainCfg.bind_dn, bindPassword, (err) => {
      client.destroy();
      if (err) return reject(err);
      resolve(true);
    });
  });
}

module.exports = { authenticateAgainstDomain, testConnection };
