"""SSH service - remote command execution"""

import subprocess
import logging
import os

logger = logging.getLogger(__name__)


class SSHService:
    def __init__(self, host, user, ssh_key=None):
        self.host = host
        self.user = user
        self.ssh_key = ssh_key

    def run(self, command, timeout=30):
        args = [
            'ssh',
            '-i', self.ssh_key,
            '-o', 'StrictHostKeyChecking=accept-new',
            '-o', 'ConnectTimeout=10',
            '-o', 'BatchMode=yes',
            f'{self.user}@{self.host}',
            command
        ]
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            return result.stdout, result.stderr, result.returncode
        except FileNotFoundError:
            return '', 'ssh command not found', -1
        except subprocess.TimeoutExpired:
            return '', 'SSH command timed out', -1
        except Exception as ex:
            return '', str(ex), -1

    def check_connection(self):
        out, err, rc = self.run('echo ok', timeout=5)
        return rc == 0 and 'ok' in out
