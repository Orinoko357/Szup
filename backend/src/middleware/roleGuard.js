'use strict';

/**
 * Require one of the specified roles.
 * Usage: roleGuard('IT_ADMIN', 'SUPERADMIN')
 */
function roleGuard(...roles) {
  return (req, res, next) => {
    if (!req.user) {
      return res.status(401).json({ error: 'Nieautoryzowany.' });
    }
    if (!roles.includes(req.user.rola)) {
      return res.status(403).json({ error: `Brak uprawnień. Wymagana rola: ${roles.join(' lub ')}.` });
    }
    next();
  };
}

module.exports = { roleGuard };
