"""Database backup service - pg_dump via kubectl exec, streamed over SSH"""

import gzip
import logging
import os
import threading
from datetime import datetime

logger = logging.getLogger(__name__)

MAX_BACKUPS = 10


class BackupService:
    def __init__(self, ssh_service, k8s_service, db_config, backup_dir):
        self.ssh = ssh_service
        self.k8s = k8s_service
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
            pod = self.k8s.find_pod_by_pattern('db-dbdepl-sts')
            if not pod:
                raise RuntimeError("Could not find database pod")

            db_user = self.db_config.get('user', 'dune')
            db_name = self.db_config.get('database', 'dune')
            namespace = self.k8s.namespace
            cmd = f"sudo kubectl exec -n {namespace} {pod} -- pg_dump -U {db_user} {db_name}"

            with gzip.open(filepath, 'wb') as gz:
                err, rc = self.ssh.run_streaming(cmd, gz, timeout=600)

            if rc != 0:
                raise RuntimeError(err.strip() or f"pg_dump exited with code {rc}")

            size = os.path.getsize(filepath)
            if size == 0:
                raise RuntimeError("Backup produced an empty file")

            self._last_status = {'success': True, 'filename': filename, 'size': size}
            logger.info("Backup created: %s (%s bytes)", filename, f"{size:,}")
            self._cleanup_old_backups()

        except Exception as e:
            logger.error("Backup failed: %s", e)
            self._last_status = {'success': False, 'error': str(e)}
            if os.path.exists(filepath):
                os.remove(filepath)
        finally:
            self._in_progress = False

    def _cleanup_old_backups(self):
        for old in self.list_backups()[MAX_BACKUPS:]:
            try:
                os.remove(os.path.join(self.backup_dir, old['filename']))
                logger.info("Removed old backup: %s", old['filename'])
            except Exception as e:
                logger.warning("Failed to remove old backup %s: %s", old['filename'], e)

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
            logger.error("Failed to list backups: %s", e)
        return sorted(backups, key=lambda x: x['created_at'], reverse=True)

    def delete_backup(self, filename):
        if '/' in filename or '..' in filename or not filename.endswith('.sql.gz'):
            return False, "Invalid filename"
        filepath = os.path.join(self.backup_dir, filename)
        if not os.path.exists(filepath):
            return False, "Backup not found"
        os.remove(filepath)
        return True, "Backup deleted"
