'use strict';
const jwt = require('jsonwebtoken');

const ACCESS_SECRET = process.env.JWT_SECRET;
const REFRESH_SECRET = process.env.JWT_REFRESH_SECRET;
const ACCESS_EXPIRES = '8h';
const REFRESH_EXPIRES = '7d';

function signAccess(payload) {
  return jwt.sign(payload, ACCESS_SECRET, { expiresIn: ACCESS_EXPIRES, algorithm: 'HS256' });
}

function signRefresh(payload) {
  return jwt.sign(payload, REFRESH_SECRET, { expiresIn: REFRESH_EXPIRES, algorithm: 'HS256' });
}

function verifyAccess(token) {
  return jwt.verify(token, ACCESS_SECRET, { algorithms: ['HS256'] });
}

function verifyRefresh(token) {
  return jwt.verify(token, REFRESH_SECRET, { algorithms: ['HS256'] });
}

module.exports = { signAccess, signRefresh, verifyAccess, verifyRefresh, ACCESS_EXPIRES, REFRESH_EXPIRES };
