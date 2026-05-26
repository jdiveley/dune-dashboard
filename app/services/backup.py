"""Database backup service - creates pg_dump backups stored locally"""

import gzip
import logging
import os
import subprocess
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_BACKUPS = 10


class BackupService:
    def __init__(self, db_config, backup_dir):
        self.db_config = db_config
        self.backup_dir = backup_dir
        self._in_progress = False
        self._last_status = None
        os.makedirs(backup_dir, exist_ok=True)

    @property
    def in_progress(self):
        return self._in_progress

    @property
    def last_status(self):
        return self._last_status

    def create_backup_async(self):
        if self._in_progress:
            return False, "Backup already in progress"
        threading.Thread(target=self._run_backup, daemon=True).start()
        return True, "Backup started"

    def _run_backup(self):
        self._in_progress = True
        self._last_status = None
        timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        filename = f"dune_{timestamp}.sql.gz"
        filepath = os.path.join(self.backup_dir, filename)

        try:
            env = os.environ.copy()
            env['PGPASSWORD'] = self.db_config.get('password', '')

            cmd = [
                'pg_dump',
                '-h', str(self.db_config.get('host', 'localhost')),
                '-p', str(self.db_config.get('port', 15433)),
                '-U', self.db_config.get('user', 'dune'),
                self.db_config.get('database', 'dune'),
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=600,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.decode().strip())

            with gzip.open(filepath, 'wb') as gz:
                gz.write(result.stdout)

            size = os.path.getsize(filepath)
            self._last_status = {'success': True, 'filename': filename, 'size': size}
            logger.info(f"Backup created: {filename} ({size:,} bytes)")
            self._cleanup_old_backups()

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            self._last_status = {'success': False, 'error': str(e)}
            if os.path.exists(filepath):
                os.remove(filepath)
        finally:
            self._in_progress = False

    def _cleanup_old_backups(self):
        backups = self.list_backups()
        for old in backups[MAX_BACKUPS:]:
            try:
                os.remove(os.path.join(self.backup_dir, old['filename']))
                logger.info(f"Removed old backup: {old['filename']}")
            except Exception as e:
                logger.warning(f"Failed to remove old backup {old['filename']}: {e}")

    def list_backups(self):
        backups = []
        try:
            for fname in os.listdir(self.backup_dir):
                if not (fname.startswith('dune_') and fname.endswith('.sql.gz')):
                    continue
                fpath = os.path.join(self.backup_dir, fname)
                stat = os.stat(fpath)
                backups.append({
                    'filename': fname,
                    'size': stat.st_size,
                    'created_at': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
        return sorted(backups, key=lambda x: x['created_at'], reverse=True)

    def delete_backup(self, filename):
        if '/' in filename or '..' in filename or not filename.endswith('.sql.gz'):
            return False, "Invalid filename"
        filepath = os.path.join(self.backup_dir, filename)
        if not os.path.exists(filepath):
            return False, "Backup not found"
        os.remove(filepath)
        return True, "Backup deleted"
