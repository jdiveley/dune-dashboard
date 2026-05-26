"""Scheduled restart service - timed battlegroup restarts with in-game warnings."""

import logging
import shlex
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DAY_NAMES = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun']


class ScheduledRestartService:
    def __init__(self, ssh_service, chat_service, settings, audit_service=None):
        self.ssh = ssh_service
        self.chat = chat_service
        self.settings = settings
        self.audit = audit_service
        self._stop_event = threading.Event()
        # Track (sched_id, date_str, event_key) to prevent double-firing
        self._fired = set()

    def start(self):
        t = threading.Thread(target=self._loop, daemon=True, name='scheduled-restart')
        t.start()
        logger.info("Scheduled restart service started")

    def stop(self):
        self._stop_event.set()

    def _loop(self):
        while not self._stop_event.is_set():
            try:
                self._tick()
            except Exception as e:
                logger.error("Scheduled restart tick error: %s", e)
            self._stop_event.wait(30)

    def _tick(self):
        schedules = self.settings.get('battlegroup', {}).get('scheduled_restarts', [])
        if not schedules:
            return

        now = datetime.utcnow()
        today = now.strftime('%Y-%m-%d')

        # Prune fired entries older than today
        self._fired = {k for k in self._fired if k[1] >= today}

        for i, sched in enumerate(schedules):
            if not sched.get('enabled', True):
                continue

            sched_id = sched.get('id', str(i))
            time_str = sched.get('time', '00:00')

            try:
                hour, minute = map(int, time_str.split(':'))
            except ValueError:
                logger.warning("Invalid schedule time: %s", time_str)
                continue

            days = sched.get('days', DAY_NAMES)
            if DAY_NAMES[now.weekday()] not in days:
                continue

            restart_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            warn_minutes = sorted(sched.get('warn_minutes', [30, 15, 5, 1]), reverse=True)
            msg_template = sched.get('message_template', '[Server] Restarting in {minutes} minutes. Please prepare!')

            for warn_min in warn_minutes:
                event_key = f'warn_{warn_min}'
                fire_key = (sched_id, today, event_key)
                if fire_key in self._fired:
                    continue
                warn_dt = restart_dt - timedelta(minutes=warn_min)
                elapsed = (now - warn_dt).total_seconds()
                if 0 <= elapsed < 55:
                    self._fired.add(fire_key)
                    msg = msg_template.format(minutes=warn_min)
                    logger.info("Sending restart warning: %s", msg)
                    self._send_broadcast(msg)
                    break

            restart_key = (sched_id, today, 'restart')
            if restart_key not in self._fired:
                elapsed = (now - restart_dt).total_seconds()
                if 0 <= elapsed < 55:
                    self._fired.add(restart_key)
                    final_msg = sched.get('restart_message', '[Server] Restarting now. Back shortly!')
                    logger.info("Executing scheduled restart for schedule %s", sched_id)
                    self._send_broadcast(final_msg)
                    self._do_restart(sched_id)

    def _send_broadcast(self, message):
        """Save broadcast to chat history and optionally run configured SSH command."""
        try:
            self.chat.save_message(
                channel='System',
                sender='SYSTEM',
                message=message,
                is_admin=True,
            )
        except Exception as e:
            logger.error("Failed to save broadcast to chat history: %s", e)

        broadcast_cmd = self.settings.get('battlegroup', {}).get('broadcast_command', '')
        if not broadcast_cmd:
            return

        try:
            cmd = broadcast_cmd.replace('{message}', shlex.quote(message))
            out, err, rc = self.ssh.run(cmd, timeout=15)
            if rc != 0:
                logger.warning("Broadcast command failed (rc=%d): %s", rc, err)
            else:
                logger.info("In-game broadcast sent")
        except Exception as e:
            logger.error("Broadcast command error: %s", e)

    def _do_restart(self, sched_id):
        try:
            bg_script = self.settings.get('kubernetes', {}).get(
                'battlegroup_script', '/home/dune/.dune/bin/battlegroup'
            )
            out, err, rc = self.ssh.run(f'{bg_script} restart', timeout=120)
            logger.info("Scheduled restart result (rc=%d): %s", rc, (out or '')[:100])
            if self.audit:
                self.audit.log(
                    'battlegroup_scheduled_restart',
                    {'schedule_id': sched_id, 'result': rc},
                    user='scheduler',
                    severity='warning',
                )
        except Exception as e:
            logger.error("Scheduled restart failed: %s", e)

    def send_manual_broadcast(self, message):
        """Send a broadcast immediately (called from API)."""
        self._send_broadcast(message)

    def get_upcoming(self):
        """Return a list of upcoming restart times, sorted soonest first."""
        schedules = self.settings.get('battlegroup', {}).get('scheduled_restarts', [])
        now = datetime.utcnow()
        upcoming = []

        for i, sched in enumerate(schedules):
            if not sched.get('enabled', True):
                continue

            time_str = sched.get('time', '00:00')
            try:
                hour, minute = map(int, time_str.split(':'))
            except ValueError:
                continue

            days = sched.get('days', DAY_NAMES)

            for days_ahead in range(8):
                candidate = (now + timedelta(days=days_ahead)).replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                if candidate <= now:
                    continue
                if DAY_NAMES[candidate.weekday()] in days:
                    upcoming.append({
                        'id': sched.get('id', str(i)),
                        'label': sched.get('label', f'Schedule {i+1}'),
                        'next_utc': candidate.strftime('%Y-%m-%dT%H:%M:%SZ'),
                        'seconds_until': int((candidate - now).total_seconds()),
                    })
                    break

        upcoming.sort(key=lambda x: x['seconds_until'])
        return upcoming
