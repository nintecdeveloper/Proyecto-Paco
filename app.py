import os
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

# Configuración de rutas para evitar archivos "fantasmas"
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'oslaprint_pro_secure_2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'oslaprint.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELOS (Base de datos) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20)) # 'admin' o 'tech'

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tech_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    client_name = db.Column(db.String(100))
    description = db.Column(db.Text)
    date = db.Column(db.Date, default=date.today)
    start_time = db.Column(db.String(10))
    parts = db.Column(db.String(200))
    tech = db.relationship('User', backref='tasks')

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

# --- RUTAS ---
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Acceso denegado: Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        empleados = User.query.filter_by(role='tech').all()
        informes = Task.query.order_by(Task.date.desc()).all()
        return render_template('admin_panel.html', empleados=empleados, informes=informes)
    return render_template('tech_panel.html')

@app.route('/api/admin/tasks/<int:user_id>')
@login_required
def get_admin_tasks(user_id):
    if current_user.role != 'admin': return jsonify([])
    tasks = Task.query.filter_by(tech_id=user_id).all()
    return jsonify([{'title': t.client_name, 'start': f"{t.date}", 'color': '#f37021'} for t in tasks])

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- INICIO DEL SISTEMA ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Crear Admin por defecto (admin / admin123)
        if not User.query.filter_by(username='admin').first():
            db.session.add(User(username='admin', role='admin', password_hash=generate_password_hash('admin123')))
        # Crear un Técnico de prueba (tech / tech123)
        if not User.query.filter_by(username='tech').first():
            db.session.add(User(username='tech', role='tech', password_hash=generate_password_hash('tech123')))
        db.session.commit()
    app.run(debug=True)