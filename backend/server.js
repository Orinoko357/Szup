'use strict';
require('dotenv').config();
const express = require('express');
const helmet = require('helmet');
const cors = require('cors');
const cookieParser = require('cookie-parser');
const logger = require('./src/config/logger');
const { globalLimiter } = require('./src/middleware/rateLimiter');

const app = express();

// Security
app.use(helmet());
app.use(cors({
  origin: process.env.ALLOWED_ORIGIN || 'http://localhost:5173',
  credentials: true,
  methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowedHeaders: ['Content-Type', 'Authorization'],
}));
app.use(cookieParser());
app.use(express.json({ limit: '2mb' }));
app.use(express.urlencoded({ extended: true }));
app.use(globalLimiter);

// Trust proxy for correct IP
app.set('trust proxy', 1);

// Routes
app.use('/api/auth',         require('./src/routes/auth'));
app.use('/api/tenants',      require('./src/routes/tenants'));
app.use('/api/struktura-org',require('./src/routes/strukturaOrg'));
app.use('/api/komorki',      require('./src/routes/komorki'));
app.use('/api/ldap-domeny',  require('./src/routes/ldapDomains'));
app.use('/api/systemy-it',   require('./src/routes/systemyIt'));
app.use('/api/uzytkownicy',  require('./src/routes/uzytkownicy'));
app.use('/api/pracownicy',   require('./src/routes/pracownicy'));
app.use('/api/workflow',     require('./src/routes/workflow'));
app.use('/api/wnioski',      require('./src/routes/wnioski'));
app.use('/api/uprawnienia',  require('./src/routes/uprawnienia'));
app.use('/api/przeglady',    require('./src/routes/przeglady'));
app.use('/api/rejestry',     require('./src/routes/rejestry'));
app.use('/api/incydenty',    require('./src/routes/incydenty'));
app.use('/api/powiadomienia',require('./src/routes/powiadomienia'));
app.use('/api/konfiguracja', require('./src/routes/konfiguracja'));

// Health check
app.get('/api/health', (req, res) => res.json({ status: 'ok', ts: new Date().toISOString() }));

// Serve React frontend (production build)
const path = require('path');
const publicDir = path.join(__dirname, 'public');
app.use(express.static(publicDir));
app.get('*', (req, res) => res.sendFile(path.join(publicDir, 'index.html')));

// Error handler
app.use((err, req, res, next) => {
  logger.error('Unhandled error', { err: err.message, stack: err.stack, path: req.path });
  res.status(err.status || 500).json({ error: err.message || 'Błąd serwera.' });
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, () => {
  logger.info(`Server running on port ${PORT} [${process.env.NODE_ENV}]`);

  // Start scheduler
  if (process.env.SCHEDULER_ENABLED === 'true') {
    require('./src/services/schedulerService').start();
  }
});

module.exports = app;
