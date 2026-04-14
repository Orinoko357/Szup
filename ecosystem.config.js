module.exports = {
  apps: [
    {
      name: 'szup-backend',
      script: 'uvicorn',
      args: 'main:app --host 0.0.0.0 --port 40273 --workers 2 --loop asyncio',
      cwd: '/opt/szup/backend-py',
      interpreter: 'none',
      watch: false,
      max_memory_restart: '512M',
      env: {
        PYTHONUNBUFFERED: '1',
      },
      // Logging
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: '/var/log/szup/pm2-error.log',
      out_file: '/var/log/szup/pm2-out.log',
      merge_logs: true,
      // Graceful shutdown
      kill_timeout: 10000,
      // Restart policy
      max_restarts: 10,
      restart_delay: 5000,
      autorestart: true,
    },
  ],
};
