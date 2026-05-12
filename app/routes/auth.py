"""Authentication routes - login, logout"""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = 'Please log in to access the dashboard.'


class AdminUser(UserMixin):
    def __init__(self, username):
        self.id = username


def init_auth(app, settings):
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        auth_settings = settings.get('auth', {})
        if auth_settings.get('username') == user_id:
            return AdminUser(user_id)
        return None

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('overview'))

        if request.method == 'POST':
            username = request.form.get('username', '')
            password = request.form.get('password', '')
            auth_settings = settings.get('auth', {})

            if username == auth_settings.get('username') and password == auth_settings.get('password'):
                user = AdminUser(username)
                login_user(user)
                next_page = request.args.get('next')
                return redirect(next_page or url_for('overview'))
            else:
                flash('Invalid username or password', 'error')

        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))
