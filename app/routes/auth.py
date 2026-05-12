"""Authentication routes - login, logout"""

from flask import render_template, request, redirect, url_for, flash
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in.'

class AdminUser(UserMixin):
    def __init__(self, username):
        self.id = username

def init_auth(app, settings):
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        auth = settings.get('auth', {})
        if str(auth.get('username')) == str(user_id):
            return AdminUser(user_id)
        return None

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('overview'))

        if request.method == 'POST':
            u = request.form.get('username', '')
            p = request.form.get('password', '')
            auth = settings.get('auth', {})
            
            cfg_u = str(auth.get('username', ''))
            cfg_p = str(auth.get('password', ''))

            if u == cfg_u and p == cfg_p:
                login_user(AdminUser(u))
                return redirect(url_for('overview'))
            else:
                flash('Invalid username or password')

        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        return redirect(url_for('login'))
