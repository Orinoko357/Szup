module.exports = {
  apps: [
    {
      name: 'szup-backend',
      script: './backend/server.js',
      cwd: '/opt/szup',
      instances: 2,
      exec_mode: 'cluster',
      watch: false,
      max_memory_restart: '512M',
      env: {
        NODE_ENV: 'production',
        PORT: 3001,
      },
      env_production: {
        NODE_ENV: 'production',
        PORT: 3001,
      },
      // Logging
      log_date_format: 'YYYY-MM-DD HH:mm:ss Z',
      error_file: '/var/log/szup/pm2-error.log',
      out_file: '/var/log/szup/pm2-out.log',
      merge_logs: true,
      // Graceful shutdown
      kill_timeout: 10000,
      wait_ready: true,
      listen_timeout: 10000,
      // Restart policy
      max_restarts: 10,
      restart_delay: 5000,
      autorestart: true,
      // Node.js flags for production
      node_args: '--max-old-space-size=512',
    },
  ],
};
