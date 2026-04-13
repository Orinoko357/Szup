'use strict';
const { verifyAccess } = require('../config/jwt');
const logger = require('../config/logger');

/**
 * Verify JWT access token from Authorization header.
 * Attaches req.user = { userId, username, email, rola, tenantId }
 */
function authenticate(req, res, next) {
  const header = req.headers['authorization'];
  if (!header || !header.startsWith('Bearer ')) {
    return res.status(401).json({ error: 'Brak tokenu autoryzacyjnego.' });
  }
  const token = header.slice(7);
  try {
    const payload = verifyAccess(token);
    req.user = {
      userId: payload.userId,
      username: payload.username,
      email: payload.email,
      rola: payload.rola,
      tenantId: payload.tenantId || null,
    };
    next();
  } catch (err) {
    logger.debug('JWT verify failed', { error: err.message });
    return res.status(401).json({ error: 'Token nieważny lub wygasły.' });
  }
}

module.exports = { authenticate };
