'use strict';
const winston = require('winston');
require('winston-daily-rotate-file');
const path = require('path');

const LOG_PATH = process.env.LOG_PATH || path.join(__dirname, '../../../logs');

const { combine, timestamp, json, printf, colorize } = winston.format;

const fileTransport = new winston.transports.DailyRotateFile({
  filename: path.join(LOG_PATH, 'app-%DATE%.log'),
  datePattern: 'YYYY-MM-DD',
  maxFiles: '30d',
  zippedArchive: true,
  format: combine(timestamp(), json()),
});

const errorTransport = new winston.transports.DailyRotateFile({
  filename: path.join(LOG_PATH, 'error-%DATE%.log'),
  datePattern: 'YYYY-MM-DD',
  maxFiles: '30d',
  level: 'error',
  zippedArchive: true,
  format: combine(timestamp(), json()),
});

const consoleTransport = new winston.transports.Console({
  format: combine(
    colorize(),
    timestamp({ format: 'HH:mm:ss' }),
    printf(({ level, message, timestamp: ts, ...meta }) => {
      const extra = Object.keys(meta).length ? ' ' + JSON.stringify(meta) : '';
      return `${ts} [${level}] ${message}${extra}`;
    })
  ),
});

const logger = winston.createLogger({
  level: process.env.NODE_ENV === 'production' ? 'info' : 'debug',
  transports: [
    fileTransport,
    errorTransport,
    ...(process.env.NODE_ENV !== 'test' ? [consoleTransport] : []),
  ],
});

module.exports = logger;
