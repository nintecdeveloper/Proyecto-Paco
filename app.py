import os
import json
import secrets
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import io
import re

basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)
app.config['SECRET_KEY'] = 'oslaprint_pro_2026_secure_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'oslaprint.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(basedir, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'doc', 'docx', 'txt'}

# Crear carpeta de uploads si no existe
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=True)  # Para recuperación de contraseña
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20))  # 'admin' o 'tech'
    reset_token = db.Column(db.String(100), unique=True, nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)  # OBLIGATORIO
    email = db.Column(db.String(100), nullable=False)  # OBLIGATORIO
    address = db.Column(db.String(250), nullable=False)  # OBLIGATORIO con Google Maps
    notes = db.Column(db.Text)  # Comentarios internos
    has_support = db.Column(db.Boolean, default=False)  # Verde=True, Rojo=False
    support_monday_friday = db.Column(db.Boolean, default=False)
    support_saturday = db.Column(db.Boolean, default=False)
    support_sunday = db.Column(db.Boolean, default=False)

class ServiceType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(7), default='#6c757d')  # Hex code color

class StockCategory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('stock_category.id'), nullable=True)
    parent = db.relationship('StockCategory', remote_side=[id], backref='subcategories')

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    category_id = db.Column(db.Integer, db.ForeignKey('stock_category.id'), nullable=True)
    category = db.relationship('StockCategory', backref='items')
    min_stock = db.Column(db.Integer, default=5)  # Para alarmas de stock bajo
    description = db.Column(db.Text)

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tech_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=True)
    client_name = db.Column(db.String(100))
    description = db.Column(db.Text)
    
    date = db.Column(db.Date, default=date.today)
    start_time = db.Column(db.String(10)) 
    end_time = db.Column(db.String(10))   
    
    service_type_id = db.Column(db.Integer, db.ForeignKey('service_type.id'))
    parts_text = db.Column(db.String(200))  
    
    stock_item_id = db.Column(db.Integer, db.ForeignKey('stock.id'), nullable=True)
    stock_quantity_used = db.Column(db.Integer, default=0)
    stock_action = db.Column(db.String(20))

    status = db.Column(db.String(20), default='Pendiente')  # Pendiente o Completado
    
    # Campos para firma digital
    signature_data = db.Column(db.Text)  # Base64 de la firma
    
    # Nuevos campos para archivos adjuntos
    attachments = db.Column(db.Text)  # JSON con lista de archivos adjuntos
    
    # Hora de inicio/fin real del trabajo (para tracking automático)
    actual_start_time = db.Column(db.DateTime)
    actual_end_time = db.Column(db.DateTime)

    tech = db.relationship('User', backref='tasks')
    client = db.relationship('Client', backref='tasks')
    service_type = db.relationship('ServiceType', backref='tasks')
    stock_item = db.relationship('Stock', backref='tasks')

class Alarm(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    alarm_type = db.Column(db.String(50))  # 'technical', 'maintenance', 'low_stock'
    title = db.Column(db.String(100))
    description = db.Column(db.Text)
    client_name = db.Column(db.String(100), nullable=True)
    stock_item_id = db.Column(db.Integer, db.ForeignKey('stock.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_read = db.Column(db.Boolean, default=False)
    priority = db.Column(db.String(20), default='normal')  # low, normal, high

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

# --- FUNCIONES AUXILIARES ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_password(password):
    """
    Validar que la contraseña cumpla los requisitos de seguridad:
    - Mínimo 6 caracteres
    - Al menos una mayúscula
    - Al menos una minúscula
    - Al menos un número
    - Al menos un carácter especial
    """
    if len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres"
    if not re.search(r'[A-Z]', password):
        return False, "La contraseña debe contener al menos una mayúscula"
    if not re.search(r'[a-z]', password):
        return False, "La contraseña debe contener al menos una minúscula"
    if not re.search(r'[0-9]', password):
        return False, "La contraseña debe contener al menos un número"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "La contraseña debe contener al menos un carácter especial (!@#$%^&*...)"
    return True, "Contraseña válida"

def check_low_stock():
    """Verificar stock bajo y crear alarmas"""
    low_items = Stock.query.filter(Stock.quantity <= Stock.min_stock).all()
    for item in low_items:
        # Verificar si ya existe una alarma activa para este item
        existing = Alarm.query.filter_by(
            alarm_type='low_stock',
            stock_item_id=item.id,
            is_read=False
        ).first()
        
        if not existing:
            alarm = Alarm(
                alarm_type='low_stock',
                title=f'Stock bajo: {item.name}',
                description=f'El stock de {item.name} está en {item.quantity} unidades (mínimo: {item.min_stock})',
                stock_item_id=item.id,
                priority='high'
            )
            db.session.add(alarm)
    db.session.commit()

# --- CONTEXT PROCESSOR ---
@app.context_processor
def inject_globals():
    try:
        unread_alarms = 0
        if current_user.is_authenticated and current_user.role == 'admin':
            unread_alarms = Alarm.query.filter_by(is_read=False).count()
        
        return {
            'all_service_types': ServiceType.query.order_by(ServiceType.name).all(),
            'unread_alarms_count': unread_alarms
        }
    except Exception as e:
        print("ERROR context_processor:", e)
        return {
            'all_service_types': [],
            'unread_alarms_count': 0
        }

# --- RUTAS PRINCIPALES ---
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
        flash('Credenciales incorrectas.', 'danger')
    return render_template('login.html')

@app.route('/forgot_password', methods=['POST'])
def forgot_password():
    email = request.form.get('email')
    user = User.query.filter_by(email=email).first()
    
    if not user:
        flash('No se encontró ningún usuario con ese correo electrónico.', 'danger')
        return redirect(url_for('login'))
    
    # Generar token único
    token = secrets.token_urlsafe(32)
    user.reset_token = token
    user.reset_token_expiry = datetime.now() + timedelta(hours=24)
    db.session.commit()
    
    # En producción, aquí enviarías un email con el enlace
    # Por ahora, mostraremos el enlace directamente
    reset_link = url_for('reset_password', token=token, _external=True)
    
    flash(f'Enlace de recuperación generado. En producción se enviaría por email. Link: {reset_link}', 'success')
    return redirect(url_for('login'))

@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    
    if not user or not user.reset_token_expiry or user.reset_token_expiry < datetime.now():
        flash('El enlace de recuperación no es válido o ha expirado.', 'danger')
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Las contraseñas no coinciden.', 'danger')
            return render_template('reset_password.html')
        
        # Validar contraseña
        is_valid, message = validate_password(password)
        if not is_valid:
            flash(message, 'danger')
            return render_template('reset_password.html')
        
        # Actualizar contraseña
        user.password_hash = generate_password_hash(password)
        user.reset_token = None
        user.reset_token_expiry = None
        db.session.commit()
        
        flash('Contraseña restablecida correctamente. Ya puedes iniciar sesión.', 'success')
        return redirect(url_for('login'))
    
    return render_template('reset_password.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        empleados = User.query.filter_by(role='tech').all()
        informes = Task.query.filter_by(status='Completado').order_by(Task.date.desc()).all()
        
        # Organizar inventario por categorías jerárquicas
        categories = StockCategory.query.filter_by(parent_id=None).all()
        inventory = Stock.query.order_by(Stock.name).all()
        
        clients = Client.query.order_by(Client.name).all()
        services = ServiceType.query.order_by(ServiceType.name).all()
        alarms = Alarm.query.order_by(Alarm.is_read.asc(), Alarm.created_at.desc()).all()
        
        return render_template('admin_panel.html', 
                             empleados=empleados, 
                             informes=informes, 
                             inventory=inventory,
                             stock_categories=categories,
                             clients=clients, 
                             services=services,
                             alarms=alarms)
    
    # Panel de técnico
    stock_items = Stock.query.order_by(Stock.name).all()
    pending_tasks = Task.query.filter_by(tech_id=current_user.id, status='Pendiente').order_by(Task.date).all()
    
    return render_template('tech_panel.html', 
                           today_date=date.today().strftime('%Y-%m-%d'), 
                           stock_items=stock_items,
                           pending_tasks=pending_tasks)

# --- GESTIÓN DE USUARIOS ---
@app.route('/manage_users', methods=['POST'])
@login_required
def manage_users():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'tech')
        
        if User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe.', 'danger')
            return redirect(url_for('dashboard'))
        
        if email and User.query.filter_by(email=email).first():
            flash('El correo electrónico ya está registrado.', 'danger')
            return redirect(url_for('dashboard'))
        
        # Validar contraseña
        is_valid, message = validate_password(password)
        if not is_valid:
            flash(message, 'danger')
            return redirect(url_for('dashboard'))
        
        new_user = User(
            username=username,
            email=email,
            password_hash=generate_password_hash(password),
            role=role
        )
        db.session.add(new_user)
        db.session.commit()
        flash(f'Usuario {username} creado correctamente.', 'success')
    
    elif action == 'delete':
        user_id = request.form.get('user_id')
        user = User.query.get(user_id)
        if user and user.id != current_user.id:
            db.session.delete(user)
            db.session.commit()
            flash(f'Usuario eliminado.', 'success')
    
    elif action == 'change_password':
        user_id = request.form.get('user_id')
        new_password = request.form.get('new_password')
        
        # Validar contraseña
        is_valid, message = validate_password(new_password)
        if not is_valid:
            flash(message, 'danger')
            return redirect(url_for('dashboard'))
        
        user = User.query.get(user_id)
        if user:
            user.password_hash = generate_password_hash(new_password)
            db.session.commit()
            flash('Contraseña actualizada correctamente.', 'success')
    
    return redirect(url_for('dashboard'))

# --- GESTIÓN DE CLIENTES ---
@app.route('/manage_clients', methods=['POST'])
@login_required
def manage_clients():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form.get('name')
        phone = request.form.get('phone')
        email = request.form.get('email')
        address = request.form.get('address')
        notes = request.form.get('notes', '')
        has_support = request.form.get('has_support') == 'true'
        support_mf = request.form.get('support_monday_friday') == 'true'
        support_sat = request.form.get('support_saturday') == 'true'
        support_sun = request.form.get('support_sunday') == 'true'
        
        # Validar campos obligatorios
        if not all([name, phone, email, address]):
            flash('Todos los campos obligatorios deben estar completos (Nombre, Teléfono, Email, Dirección).', 'danger')
            return redirect(url_for('dashboard'))
        
        if Client.query.filter_by(name=name).first():
            flash('Ya existe un cliente con ese nombre.', 'danger')
            return redirect(url_for('dashboard'))
        
        new_client = Client(
            name=name,
            phone=phone,
            email=email,
            address=address,
            notes=notes,
            has_support=has_support,
            support_monday_friday=support_mf,
            support_saturday=support_sat,
            support_sunday=support_sun
        )
        db.session.add(new_client)
        db.session.commit()
        flash('Cliente creado correctamente.', 'success')
    
    elif action == 'edit':
        client_id = request.form.get('client_id')
        client = Client.query.get(client_id)
        if client:
            client.name = request.form.get('name')
            client.phone = request.form.get('phone')
            client.email = request.form.get('email')
            client.address = request.form.get('address')
            client.notes = request.form.get('notes', '')
            client.has_support = request.form.get('has_support') == 'true'
            client.support_monday_friday = request.form.get('support_monday_friday') == 'true'
            client.support_saturday = request.form.get('support_saturday') == 'true'
            client.support_sunday = request.form.get('support_sunday') == 'true'
            db.session.commit()
            flash('Cliente actualizado correctamente.', 'success')
    
    elif action == 'delete':
        client_id = request.form.get('client_id')
        client = Client.query.get(client_id)
        if client:
            db.session.delete(client)
            db.session.commit()
            flash('Cliente eliminado.', 'success')
    
    return redirect(url_for('dashboard'))

# --- GESTIÓN DE STOCK ---
@app.route('/manage_stock_categories', methods=['POST'])
@login_required
def manage_stock_categories():
    if current_user.role != 'admin':
        return jsonify({'success': False}), 403
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form.get('name')
        parent_id = request.form.get('parent_id')
        
        if not name:
            return jsonify({'success': False, 'msg': 'El nombre es obligatorio'}), 400
        
        new_category = StockCategory(
            name=name,
            parent_id=int(parent_id) if parent_id and parent_id != '' else None
        )
        db.session.add(new_category)
        db.session.commit()
        return jsonify({'success': True, 'msg': 'Categoría creada correctamente'})
    
    elif action == 'delete':
        category_id = request.form.get('category_id')
        category = StockCategory.query.get(category_id)
        if category:
            db.session.delete(category)
            db.session.commit()
            return jsonify({'success': True})
    
    return jsonify({'success': False}), 400

@app.route('/manage_stock', methods=['POST'])
@login_required
def manage_stock():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form.get('name')
        category_id = request.form.get('category_id')
        quantity = int(request.form.get('quantity', 0))
        min_stock = int(request.form.get('min_stock', 5))
        description = request.form.get('description', '')
        
        new_item = Stock(
            name=name,
            category_id=int(category_id) if category_id and category_id != '' else None,
            quantity=quantity,
            min_stock=min_stock,
            description=description
        )
        db.session.add(new_item)
        db.session.commit()
        check_low_stock()
        flash('Producto añadido correctamente.', 'success')
    
    elif action == 'edit':
        item_id = request.form.get('item_id')
        item = Stock.query.get(item_id)
        if item:
            item.name = request.form.get('name')
            item.category_id = int(request.form.get('category_id')) if request.form.get('category_id') else None
            item.quantity = int(request.form.get('quantity', 0))
            item.min_stock = int(request.form.get('min_stock', 5))
            item.description = request.form.get('description', '')
            db.session.commit()
            check_low_stock()
            flash('Producto actualizado.', 'success')
    
    elif action == 'delete':
        item_id = request.form.get('item_id')
        item = Stock.query.get(item_id)
        if item:
            db.session.delete(item)
            db.session.commit()
            flash('Producto eliminado.', 'success')
    
    return redirect(url_for('dashboard'))

# --- GESTIÓN DE TIPOS DE SERVICIO ---
@app.route('/manage_services', methods=['POST'])
@login_required
def manage_services():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form.get('name')
        color = request.form.get('color', '#6c757d')
        
        if ServiceType.query.filter_by(name=name).first():
            flash('Ya existe un tipo de servicio con ese nombre.', 'danger')
            return redirect(url_for('dashboard'))
        
        new_service = ServiceType(name=name, color=color)
        db.session.add(new_service)
        db.session.commit()
        flash('Tipo de servicio creado.', 'success')
    
    elif action == 'edit':
        service_id = request.form.get('service_id')
        service = ServiceType.query.get(service_id)
        if service:
            service.name = request.form.get('name')
            service.color = request.form.get('color')
            db.session.commit()
            flash('Tipo de servicio actualizado.', 'success')
    
    elif action == 'delete':
        service_id = request.form.get('service_id')
        service = ServiceType.query.get(service_id)
        if service:
            db.session.delete(service)
            db.session.commit()
            flash('Tipo de servicio eliminado.', 'success')
    
    return redirect(url_for('dashboard'))

# --- GESTIÓN DE TAREAS ---
@app.route('/create_task', methods=['POST'])
@login_required
def create_task():
    try:
        data = request.get_json() if request.is_json else request.form
        
        tech_id = data.get('tech_id')
        client_name = data.get('client_name')
        task_date = datetime.strptime(data.get('date'), '%Y-%m-%d').date()
        start_time = data.get('start_time')
        end_time = data.get('end_time')
        service_type_id = data.get('service_type_id')
        description = data.get('description', '')
        
        # Obtener el cliente si existe
        client = Client.query.filter_by(name=client_name).first()
        
        new_task = Task(
            tech_id=int(tech_id) if tech_id else None,
            client_id=client.id if client else None,
            client_name=client_name,
            date=task_date,
            start_time=start_time,
            end_time=end_time,
            service_type_id=int(service_type_id),
            description=description,
            status='Pendiente'
        )
        
        db.session.add(new_task)
        db.session.commit()
        
        if request.is_json:
            return jsonify({
                'success': True,
                'task_id': new_task.id,
                'msg': 'Tarea creada correctamente'
            })
        else:
            flash('Tarea creada correctamente.', 'success')
            return redirect(url_for('dashboard'))
    
    except Exception as e:
        print(f"Error creating task: {e}")
        if request.is_json:
            return jsonify({'success': False, 'msg': str(e)}), 500
        else:
            flash(f'Error al crear la tarea: {str(e)}', 'danger')
            return redirect(url_for('dashboard'))

@app.route('/update_task/<int:task_id>', methods=['POST'])
@login_required
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        flash('No tienes permisos para editar esta tarea.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        data = request.get_json() if request.is_json else request.form
        
        if 'client_name' in data:
            task.client_name = data['client_name']
            # Actualizar cliente si existe
            client = Client.query.filter_by(name=data['client_name']).first()
            task.client_id = client.id if client else None
        
        if 'date' in data:
            task.date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        if 'start_time' in data:
            task.start_time = data['start_time']
        if 'end_time' in data:
            task.end_time = data['end_time']
        if 'service_type_id' in data:
            task.service_type_id = int(data['service_type_id'])
        if 'description' in data:
            task.description = data['description']
        if 'status' in data:
            task.status = data['status']
        if 'tech_id' in data and current_user.role == 'admin':
            task.tech_id = int(data['tech_id']) if data['tech_id'] else None
        
        db.session.commit()
        
        if request.is_json:
            return jsonify({'success': True, 'msg': 'Tarea actualizada'})
        else:
            flash('Tarea actualizada correctamente.', 'success')
            return redirect(url_for('dashboard'))
    
    except Exception as e:
        if request.is_json:
            return jsonify({'success': False, 'msg': str(e)}), 500
        else:
            flash(f'Error al actualizar tarea: {str(e)}', 'danger')
            return redirect(url_for('dashboard'))

@app.route('/delete_task/<int:task_id>', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    db.session.delete(task)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/start_task/<int:task_id>', methods=['POST'])
@login_required
def start_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    task.actual_start_time = datetime.now()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'start_time': task.actual_start_time.strftime('%H:%M')
    })

@app.route('/end_task/<int:task_id>', methods=['POST'])
@login_required
def end_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    task.actual_end_time = datetime.now()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'end_time': task.actual_end_time.strftime('%H:%M')
    })

@app.route('/complete_task/<int:task_id>', methods=['POST'])
@login_required
def complete_task(task_id):
    task = Task.query.get_or_404(task_id)
    
    if current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    data = request.get_json()
    
    # La firma es obligatoria
    if not data.get('signature'):
        return jsonify({'success': False, 'msg': 'La firma del cliente es obligatoria'}), 400
    
    task.signature_data = data['signature']
    task.parts_text = data.get('parts', '')
    task.description = data.get('description', task.description)
    
    # Manejo de stock
    if data.get('stock_item_id'):
        stock_item = Stock.query.get(int(data['stock_item_id']))
        if stock_item:
            quantity = int(data.get('stock_quantity', 0))
            action = data.get('stock_action', 'used')
            
            task.stock_item_id = stock_item.id
            task.stock_quantity_used = quantity
            task.stock_action = action
            
            if action == 'used':
                stock_item.quantity -= quantity
            elif action == 'removed':
                stock_item.quantity -= quantity
            elif action == 'added':
                stock_item.quantity += quantity
            
            db.session.commit()
            check_low_stock()
    
    # Procesar archivos adjuntos
    if 'attachments' in data:
        task.attachments = json.dumps(data['attachments'])
    
    task.status = 'Completado'
    if not task.actual_end_time:
        task.actual_end_time = datetime.now()
    
    db.session.commit()
    
    return jsonify({'success': True, 'msg': 'Parte completado correctamente'})

@app.route('/upload_task_file/<int:task_id>', methods=['POST'])
@login_required
def upload_task_file(task_id):
    task = Task.query.get_or_404(task_id)
    
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'msg': 'No se envió ningún archivo'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'msg': 'Nombre de archivo vacío'}), 400
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"task_{task_id}_{timestamp}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        # Añadir a la lista de adjuntos
        attachments = []
        if task.attachments:
            try:
                attachments = json.loads(task.attachments)
            except:
                pass
        
        attachments.append(filename)
        task.attachments = json.dumps(attachments)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'filename': filename,
            'msg': 'Archivo subido correctamente'
        })
    
    return jsonify({'success': False, 'msg': 'Tipo de archivo no permitido'}), 400

# --- API ENDPOINTS ---
@app.route('/api/tasks')
@login_required
def get_all_tasks():
    """Obtener todas las tareas para el calendario"""
    if current_user.role == 'admin':
        # Admin ve todas las tareas
        tech_id = request.args.get('tech_id')
        if tech_id:
            tasks = Task.query.filter_by(tech_id=int(tech_id)).all()
        else:
            tasks = Task.query.all()
    else:
        # Técnicos solo ven sus tareas
        tasks = Task.query.filter_by(tech_id=current_user.id).all()
    
    events = []
    for task in tasks:
        service_type = ServiceType.query.get(task.service_type_id) if task.service_type_id else None
        color = service_type.color if service_type else '#6c757d'
        
        events.append({
            'id': task.id,
            'title': f"{task.client_name} - {service_type.name if service_type else 'Sin tipo'}",
            'start': f"{task.date}T{task.start_time}:00" if task.start_time else str(task.date),
            'end': f"{task.date}T{task.end_time}:00" if task.end_time else str(task.date),
            'backgroundColor': color,
            'borderColor': color,
            'extendedProps': {
                'client': task.client_name,
                'service_type': service_type.name if service_type else 'Sin tipo',
                'status': task.status,
                'tech_id': task.tech_id,
                'tech_name': task.tech.username if task.tech else 'Sin asignar'
            }
        })
    
    return jsonify(events)

@app.route('/api/clients')
@login_required
def get_clients():
    """API para autocompletado de clientes"""
    query = request.args.get('q', '')
    clients = Client.query.filter(Client.name.contains(query)).limit(10).all()
    
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'phone': c.phone,
        'email': c.email,
        'address': c.address,
        'has_support': c.has_support
    } for c in clients])

@app.route('/api/task/<int:task_id>')
@login_required
def get_task_details(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    # Procesar archivos adjuntos
    attachments_list = []
    if task.attachments:
        try:
            attachments_list = json.loads(task.attachments)
        except:
            pass
    
    service_type = ServiceType.query.get(task.service_type_id) if task.service_type_id else None
    
    return jsonify({
        'success': True,
        'data': {
            'id': task.id,
            'client_name': task.client_name,
            'date': task.date.strftime('%Y-%m-%d'),
            'start_time': task.start_time,
            'end_time': task.end_time,
            'service_type': service_type.name if service_type else 'Sin tipo',
            'service_type_id': task.service_type_id,
            'description': task.description,
            'parts_text': task.parts_text,
            'status': task.status,
            'tech_name': task.tech.username if task.tech else 'SIN TÉCNICO',
            'tech_id': task.tech_id,
            'attachments': attachments_list,
            'has_signature': bool(task.signature_data),
            'actual_start_time': task.actual_start_time.strftime('%H:%M') if task.actual_start_time else None,
            'actual_end_time': task.actual_end_time.strftime('%H:%M') if task.actual_end_time else None,
            'stock_info': {
                'item_name': task.stock_item.name if task.stock_item else None,
                'quantity': task.stock_quantity_used,
                'action': task.stock_action
            } if task.stock_item else None
        }
    })

@app.route('/api/tech_stats/<int:tech_id>')
@login_required
def get_tech_stats(tech_id):
    """Análisis individual de trabajador"""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    tech = User.query.get_or_404(tech_id)
    tasks = Task.query.filter_by(tech_id=tech_id, status='Completado').all()
    
    # Estadísticas por tipo de servicio
    service_stats = {}
    total_time = 0
    
    for task in tasks:
        service_type = ServiceType.query.get(task.service_type_id) if task.service_type_id else None
        service_name = service_type.name if service_type else 'Sin tipo'
        
        if service_name not in service_stats:
            service_stats[service_name] = {
                'count': 0,
                'tasks': []
            }
        
        service_stats[service_name]['count'] += 1
        service_stats[service_name]['tasks'].append({
            'id': task.id,
            'client': task.client_name,
            'date': task.date.strftime('%d/%m/%Y'),
            'time': f"{task.start_time} - {task.end_time}" if task.start_time and task.end_time else 'No especificado',
            'has_attachments': bool(task.attachments)
        })
        
        # Calcular tiempo si está disponible
        if task.actual_start_time and task.actual_end_time:
            duration = (task.actual_end_time - task.actual_start_time).total_seconds() / 3600
            total_time += duration
    
    return jsonify({
        'success': True,
        'data': {
            'tech_name': tech.username,
            'total_completed': len(tasks),
            'total_hours': round(total_time, 2),
            'service_breakdown': service_stats
        }
    })

@app.route('/api/stock_categories')
@login_required
def get_stock_categories():
    """Obtener categorías de stock en formato jerárquico"""
    def build_tree(parent_id=None):
        categories = StockCategory.query.filter_by(parent_id=parent_id).all()
        result = []
        for cat in categories:
            result.append({
                'id': cat.id,
                'name': cat.name,
                'children': build_tree(cat.id),
                'items': [{'id': item.id, 'name': item.name, 'quantity': item.quantity} 
                         for item in cat.items]
            })
        return result
    
    return jsonify(build_tree())

# --- RUTAS DE ALARMAS ---
@app.route('/api/alarms')
@login_required
def get_alarms():
    if current_user.role != 'admin':
        return jsonify([])
    
    alarms = Alarm.query.order_by(Alarm.is_read.asc(), Alarm.created_at.desc()).all()
    return jsonify([{
        'id': a.id,
        'type': a.alarm_type,
        'title': a.title,
        'description': a.description,
        'client_name': a.client_name,
        'created_at': a.created_at.strftime('%d/%m/%Y %H:%M'),
        'is_read': a.is_read,
        'priority': a.priority
    } for a in alarms])

@app.route('/mark_alarm_read/<int:alarm_id>', methods=['POST'])
@login_required
def mark_alarm_read(alarm_id):
    if current_user.role != 'admin':
        return jsonify({'success': False}), 403
    
    alarm = Alarm.query.get_or_404(alarm_id)
    alarm.is_read = True
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/create_alarm', methods=['POST'])
@login_required
def create_alarm():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    alarm_type = request.form.get('alarm_type')
    title = request.form.get('title')
    description = request.form.get('description')
    client_name = request.form.get('client_name', None)
    priority = request.form.get('priority', 'normal')
    
    new_alarm = Alarm(
        alarm_type=alarm_type,
        title=title,
        description=description,
        client_name=client_name,
        priority=priority
    )
    db.session.add(new_alarm)
    db.session.commit()
    
    flash('Alarma creada correctamente.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- ARCHIVOS ESTÁTICOS ---
@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- BLOQUE DE INICIALIZACIÓN UNIFICADO ---
with app.app_context():
    # Primero creamos las tablas (la estructura)
    db.create_all()
    
    # 1. Usuarios
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(
            username='admin', 
            email='admin@oslaprint.com',
            role='admin', 
            password_hash=generate_password_hash('Admin123!')
        ))
    
    if not User.query.filter_by(username='paco').first():
        db.session.add(User(
            username='paco',
            email='paco@oslaprint.com', 
            role='admin', 
            password_hash=generate_password_hash('Paco123!')
        ))
        
    if not User.query.filter_by(username='tech').first():
        db.session.add(User(
            username='tech',
            email='tech@oslaprint.com', 
            role='tech', 
            password_hash=generate_password_hash('Tech123!')
        ))
    
    # 2. Tipos de Servicio y Colores
    if ServiceType.query.count() == 0:
        servicios = [
            {'name': 'Avería', 'color': '#fd7e14'},
            {'name': 'Revisión', 'color': '#0d6efd'},
            {'name': 'Instalación', 'color': '#6f42c1'},
            {'name': 'Otros servicios', 'color': '#20c997'}
        ]
        for s in servicios:
            db.session.add(ServiceType(name=s['name'], color=s['color']))
    
    # 3. Categorías de Stock (jerárquicas)
    if StockCategory.query.count() == 0:
        # Categorías principales
        copiadoras = StockCategory(name='Copiadoras')
        cajones = StockCategory(name='Cajones')
        tpv = StockCategory(name='TPV')
        recicladores = StockCategory(name='Recicladores')
        consumibles = StockCategory(name='Consumibles')
        
        db.session.add_all([copiadoras, cajones, tpv, recicladores, consumibles])
        db.session.commit()
        
        # Subcategorías de Cajones
        cashlogy = StockCategory(name='Cashlogy', parent_id=cajones.id)
        cashkeeper = StockCategory(name='Cashkeeper', parent_id=cajones.id)
        atca = StockCategory(name='ATCA', parent_id=cajones.id)
        
        db.session.add_all([cashlogy, cashkeeper, atca])
        db.session.commit()
    
    # 4. Productos de Stock
    if Stock.query.count() == 0:
        # Obtener categorías
        copiadoras_cat = StockCategory.query.filter_by(name='Copiadoras').first()
        tpv_cat = StockCategory.query.filter_by(name='TPV').first()
        recicladores_cat = StockCategory.query.filter_by(name='Recicladores').first()
        consumibles_cat = StockCategory.query.filter_by(name='Consumibles').first()
        cashlogy_cat = StockCategory.query.filter_by(name='Cashlogy').first()
        cashkeeper_cat = StockCategory.query.filter_by(name='Cashkeeper').first()
        atca_cat = StockCategory.query.filter_by(name='ATCA').first()
        
        stock_items = [
            {'name': 'Copiadora HP LaserJet Pro', 'category_id': copiadoras_cat.id if copiadoras_cat else None, 'quantity': 3, 'min_stock': 1},
            {'name': 'Copiadora Canon imageRUNNER', 'category_id': copiadoras_cat.id if copiadoras_cat else None, 'quantity': 2, 'min_stock': 1},
            {'name': 'Cajón Cashlogy 1500', 'category_id': cashlogy_cat.id if cashlogy_cat else None, 'quantity': 5, 'min_stock': 2},
            {'name': 'Cajón Cashlogy 2500', 'category_id': cashlogy_cat.id if cashlogy_cat else None, 'quantity': 3, 'min_stock': 1},
            {'name': 'Cajón Cashkeeper Pro', 'category_id': cashkeeper_cat.id if cashkeeper_cat else None, 'quantity': 4, 'min_stock': 2},
            {'name': 'Cajón Cashkeeper Lite', 'category_id': cashkeeper_cat.id if cashkeeper_cat else None, 'quantity': 2, 'min_stock': 1},
            {'name': 'Cajón ATCA Standard', 'category_id': atca_cat.id if atca_cat else None, 'quantity': 3, 'min_stock': 1},
            {'name': 'Cajón ATCA Pro', 'category_id': atca_cat.id if atca_cat else None, 'quantity': 2, 'min_stock': 1},
            {'name': 'TPV Táctil 15"', 'category_id': tpv_cat.id if tpv_cat else None, 'quantity': 6, 'min_stock': 2},
            {'name': 'TPV Táctil 17"', 'category_id': tpv_cat.id if tpv_cat else None, 'quantity': 4, 'min_stock': 2},
            {'name': 'Reciclador 1', 'category_id': recicladores_cat.id if recicladores_cat else None, 'quantity': 2, 'min_stock': 1},
            {'name': 'Toner Genérico Negro', 'category_id': consumibles_cat.id if consumibles_cat else None, 'quantity': 15, 'min_stock': 5},
            {'name': 'Toner Genérico Color', 'category_id': consumibles_cat.id if consumibles_cat else None, 'quantity': 10, 'min_stock': 5},
        ]
        for item in stock_items:
            db.session.add(Stock(**item))
    
    # 5. Cliente de ejemplo
    if Client.query.count() == 0:
        db.session.add(Client(
            name='Cliente Ejemplo',
            phone='900123456',
            email='ejemplo@cliente.com',
            address='Calle Ejemplo 1, Madrid',
            has_support=True,
            support_monday_friday=True
        ))
        
    db.session.commit()

# --- ARRANQUE ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
