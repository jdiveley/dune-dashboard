"""Authentication routes - login, logout"""

import time
import threading
from flask import render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in.'

# In-memory failed login tracker: {ip: {"count": int, "first_attempt": float}}
_failed_attempts = {}
_failed_lock = threading.Lock()
_MAX_FAILED_ATTEMPTS = 5
_BLOCK_DURATION = 900  # 15 minutes


def _is_ip_blocked(ip):
    """Check if an IP is currently blocked due to too many failed logins."""
    with _failed_lock:
        record = _failed_attempts.get(ip)
        if record and record['count'] >= _MAX_FAILED_ATTEMPTS:
            elapsed = time.time() - record['first_attempt']
            if elapsed < _BLOCK_DURATION:
                return True
            del _failed_attempts[ip]
        return False


def _record_failed_attempt(ip):
    """Record a failed login attempt and return True if IP should now be blocked."""
    with _failed_lock:
        now = time.time()
        record = _failed_attempts.get(ip)
        if record:
            record['count'] += 1
        else:
            _failed_attempts[ip] = {'count': 1, 'first_attempt': now}
            record = _failed_attempts[ip]
        return record['count'] >= _MAX_FAILED_ATTEMPTS


def _clear_failed_attempts(ip):
    """Clear failed attempt records on successful login."""
    with _failed_lock:
        _failed_attempts.pop(ip, None)


class AdminUser(UserMixin):
    def __init__(self, username, role='admin'):
        self.id = username
        self.role = role


def _get_all_accounts(auth):
    """Return list of (username, password_hash, role) for all configured accounts."""
    accounts = []
    primary_user = str(auth.get('username', ''))
    primary_hash = auth.get('password_hash')
    if primary_user and primary_hash:
        accounts.append((primary_user, primary_hash, 'admin'))
    for extra in auth.get('accounts', []):
        u = str(extra.get('username', ''))
        h = extra.get('password_hash')
        r = extra.get('role', 'admin')
        if u and h:
            accounts.append((u, h, r))
    return accounts


def init_auth(app, settings, limiter=None, audit_svc=None):
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        auth = settings.get('auth', {})
        for username, _, role in _get_all_accounts(auth):
            if username == str(user_id):
                return AdminUser(user_id, role)
        return None

    @app.before_request
    def enforce_readonly():
        if not current_user.is_authenticated:
            return
        if getattr(current_user, 'role', 'admin') != 'readonly':
            return
        # Block shell page and password change entirely
        if request.path.startswith('/shell') or request.path == '/account/change-password':
            abort(403)
        # Block all mutating methods
        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            return jsonify({'error': 'Read-only account', 'success': False}), 403

    def _apply_rate_limit(f):
        return limiter.limit("10 per minute")(f) if limiter else f

    @app.route('/login', methods=['GET', 'POST'])
    @_apply_rate_limit
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('overview'))

        client_ip = request.remote_addr or 'unknown'

        if _is_ip_blocked(client_ip):
            flash('Too many failed attempts. Try again later.')
            return render_template('login.html')

        if request.method == 'POST':
            u = request.form.get('username', '')
            p = request.form.get('password', '')
            auth = settings.get('auth', {})

            accounts = _get_all_accounts(auth)
            matched_hash = None
            matched_role = 'admin'
            for acct_user, acct_hash, acct_role in accounts:
                if acct_user == u:
                    matched_hash = acct_hash
                    matched_role = acct_role
                    break

            if matched_hash is None:
                if audit_svc:
                    audit_svc.log('login_failed', {'username': u, 'reason': 'invalid_username'}, user='unknown', severity='warning')
                _record_failed_attempt(client_ip)
                flash('Invalid username or password')
                return render_template('login.html')

            if matched_hash:
                try:
                    from argon2 import PasswordHasher, exceptions
                    ph = PasswordHasher(time_cost=3, memory_cost=65536)
                    if ph.verify(matched_hash, p):
                        _clear_failed_attempts(client_ip)
                        login_user(AdminUser(u, matched_role))
                        if audit_svc:
                            audit_svc.log('login_success', {'username': u, 'role': matched_role}, user=u, severity='info')
                        return redirect(url_for('overview'))
                    else:
                        if audit_svc:
                            audit_svc.log('login_failed', {'username': u, 'reason': 'invalid_password'}, user=u, severity='warning')
                except exceptions.VerifyMismatchError:
                    if audit_svc:
                        audit_svc.log('login_failed', {'username': u, 'reason': 'invalid_password'}, user=u, severity='warning')
                    pass
                except Exception:
                    flash('Authentication error. Please try again.')
                    return render_template('login.html')
            else:
                flash('Authentication not configured. Please run setup.')
                return render_template('login.html')

            _record_failed_attempt(client_ip)
            flash('Invalid username or password')

        return render_template('login.html')

    @app.route('/account/change-password', methods=['GET', 'POST'])
    @login_required
    def change_password():
        if request.method == 'POST':
            current_pw = request.form.get('current_password', '')
            new_pw = request.form.get('new_password', '')
            confirm_pw = request.form.get('confirm_password', '')

            if not current_pw or not new_pw or not confirm_pw:
                flash('All fields are required.')
                return render_template('change_password.html')

            if new_pw != confirm_pw:
                flash('New passwords do not match.')
                return render_template('change_password.html')

            if len(new_pw) < 8:
                flash('Password must be at least 8 characters.')
                return render_template('change_password.html')

            username = current_user.id
            auth = settings.get('auth', {})

            matched_hash = None
            is_primary = str(auth.get('username', '')) == username
            if is_primary:
                matched_hash = auth.get('password_hash')
            else:
                for acct in auth.get('accounts', []):
                    if str(acct.get('username', '')) == username:
                        matched_hash = acct.get('password_hash')
                        break

            if not matched_hash:
                flash('Account configuration error.')
                return render_template('change_password.html')

            try:
                from argon2 import PasswordHasher, exceptions as argon_exc
                ph = PasswordHasher(time_cost=3, memory_cost=65536)
                ph.verify(matched_hash, current_pw)
            except Exception:
                if audit_svc:
                    audit_svc.log('password_change_failed', {'username': username, 'reason': 'invalid_current_password'}, user=username, severity='warning')
                flash('Current password is incorrect.')
                return render_template('change_password.html')

            from argon2 import PasswordHasher as _PH
            new_hash = _PH(time_cost=3, memory_cost=65536).hash(new_pw)

            if is_primary:
                settings['auth']['password_hash'] = new_hash
            else:
                for acct in settings['auth'].get('accounts', []):
                    if str(acct.get('username', '')) == username:
                        acct['password_hash'] = new_hash
                        break

            from app.config import save_settings
            save_settings(settings)

            if audit_svc:
                audit_svc.log('password_changed', {'username': username}, user=username, severity='info')

            flash('Password changed successfully.')
            return redirect(url_for('change_password'))

        return render_template('change_password.html')

    @app.route('/logout')
    @login_required
    def logout():
        user = current_user.id if current_user.is_authenticated else 'unknown'
        logout_user()
        if audit_svc:
            audit_svc.log('logout', {}, user=user, severity='info')
        return redirect(url_for('login'))
