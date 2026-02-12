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
    email = db.Column(db.String(100), unique=True, nullable=True)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20))  # 'admin' o 'tech'
    reset_token = db.Column(db.String(100), unique=True, nullable=True)
    reset_token_expiry = db.Column(db.DateTime, nullable=True)

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(100), nullable=False)
    address = db.Column(db.String(250), nullable=False)
    link = db.Column(db.String(500), nullable=True)  # Google Maps o URL
    notes = db.Column(db.Text)
    has_support = db.Column(db.Boolean, default=False)
    support_monday_friday = db.Column(db.Boolean, default=False)
    support_saturday = db.Column(db.Boolean, default=False)
    support_sunday = db.Column(db.Boolean, default=False)

class ServiceType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(7), default='#6c757d')
    
    def __repr__(self):
        return f"{self.name}"

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
    min_stock = db.Column(db.Integer, default=5)
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
    signature_data = db.Column(db.Text)
    signature_client_name = db.Column(db.String(100))
    signature_timestamp = db.Column(db.DateTime)
    
    # Archivos adjuntos
    attachments = db.Column(db.Text)  # JSON
    
    # Tiempo real de trabajo
    actual_start_time = db.Column(db.DateTime)
    actual_end_time = db.Column(db.DateTime)

    tech = db.relationship('User', backref='tasks')
    client = db.relationship('Client', backref='tasks')
    service_type = db.relationship('ServiceType', backref='tasks')
    stock_item = db.relationship('Stock', backref='tasks')

class Alarm(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    alarm_type = db.Column(db.String(50))
    title = db.Column(db.String(100))
    description = db.Column(db.Text)
    client_name = db.Column(db.String(100), nullable=True)
    stock_item_id = db.Column(db.Integer, db.ForeignKey('stock.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    is_read = db.Column(db.Boolean, default=False)
    priority = db.Column(db.String(20), default='normal')

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

# --- FUNCIONES AUXILIARES ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def validate_password(password):
    """Validar contraseña con requisitos de seguridad"""
    if len(password) < 6:
        return False, "La contraseña debe tener al menos 6 caracteres"
    if not re.search(r'[A-Z]', password):
        return False, "La contraseña debe contener al menos una mayúscula"
    if not re.search(r'[a-z]', password):
        return False, "La contraseña debe contener al menos una minúscula"
    if not re.search(r'[0-9]', password):
        return False, "La contraseña debe contener al menos un número"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "La contraseña debe contener al menos un carácter especial"
    return True, "Contraseña válida"

def check_low_stock():
    """Verificar stock bajo y crear alarmas"""
    low_items = Stock.query.filter(Stock.quantity <= Stock.min_stock).all()
    for item in low_items:
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
        
        employees = User.query.filter_by(role='tech').all() if current_user.is_authenticated and current_user.role == 'admin' else []
        
        return {
            'all_service_types': ServiceType.query.order_by(ServiceType.name).all(),
            'unread_alarms_count': unread_alarms,
            'employees': employees
        }
    except Exception as e:
        print("ERROR context_processor:", e)
        return {
            'all_service_types': [],
            'unread_alarms_count': 0,
            'employees': []
        }

# --- RUTAS PRINCIPALES ---
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Usuario o contraseña incorrectos', 'danger')
    
    return render_template('login.html')

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        empleados = User.query.filter_by(role='tech').all()
        clients = Client.query.order_by(Client.name).all()
        services = ServiceType.query.all()
        informes = Task.query.filter_by(status='Completado').order_by(Task.date.desc()).limit(50).all()
        stock_items = Stock.query.order_by(Stock.name).all()
        
        return render_template('admin_panel.html', 
                             empleados=empleados,
                             clients=clients,
                             services=services,
                             informes=informes,
                             stock_items=stock_items,
                             today_date=date.today().strftime('%Y-%m-%d'))
    else:
        pending_tasks = Task.query.filter_by(
            tech_id=current_user.id, 
            status='Pendiente'
        ).order_by(Task.date.asc()).all()
        
        stock_items = Stock.query.filter(Stock.quantity > 0).order_by(Stock.name).all()
        
        return render_template('tech_panel.html',
                             pending_tasks=pending_tasks,
                             stock_items=stock_items,
                             today_date=date.today().strftime('%Y-%m-%d'))

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    try:
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        
        if not check_password_hash(current_user.password_hash, current_password):
            flash('Contraseña actual incorrecta', 'danger')
            return redirect(url_for('dashboard'))
        
        is_valid, message = validate_password(new_password)
        if not is_valid:
            flash(message, 'danger')
            return redirect(url_for('dashboard'))
        
        current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        
        flash('✅ Contraseña actualizada correctamente', 'success')
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"Error changing password: {e}")
        flash('Error al cambiar la contraseña', 'danger')
        return redirect(url_for('dashboard'))

# --- GESTIÓN DE USUARIOS ---
@app.route('/manage_users', methods=['POST'])
@login_required
def manage_users():
    if current_user.role != 'admin':
        flash('No autorizado', 'danger')
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'tech')
        
        if User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe', 'danger')
            return redirect(url_for('dashboard'))
        
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
        flash(f'Usuario {username} creado correctamente', 'success')
    
    elif action == 'delete':
        user_id = request.form.get('user_id')
        user = User.query.get(user_id)
        
        if user and user.id != current_user.id:
            db.session.delete(user)
            db.session.commit()
            flash(f'Usuario {user.username} eliminado', 'success')
        else:
            flash('No puedes eliminar tu propio usuario', 'danger')
    
    return redirect(url_for('dashboard'))

# --- GESTIÓN DE CLIENTES ---
@app.route('/manage_clients', methods=['POST'])
@login_required
def manage_clients():
    if current_user.role != 'admin':
        flash('No autorizado', 'danger')
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form.get('name')
        phone = request.form.get('phone')
        email = request.form.get('email')
        address = request.form.get('address')
        link = request.form.get('link', '')
        notes = request.form.get('notes', '')
        has_support = request.form.get('has_support') == 'true'
        
        if Client.query.filter_by(name=name).first():
            flash('Ya existe un cliente con ese nombre', 'danger')
            return redirect(url_for('dashboard'))
        
        new_client = Client(
            name=name,
            phone=phone,
            email=email,
            address=address,
            link=link if link else None,
            notes=notes,
            has_support=has_support
        )
        db.session.add(new_client)
        db.session.commit()
        flash(f'Cliente {name} añadido correctamente', 'success')
    
    elif action == 'edit':
        client_id = request.form.get('client_id')
        client = Client.query.get(client_id)
        if client:
            client.name = request.form.get('name')
            client.phone = request.form.get('phone')
            client.email = request.form.get('email')
            client.address = request.form.get('address')
            client.link = request.form.get('link', '') or None
            client.notes = request.form.get('notes', '')
            client.has_support = request.form.get('has_support') == 'true'
            db.session.commit()
            flash('Cliente actualizado correctamente', 'success')
    
    elif action == 'delete':
        client_id = request.form.get('client_id')
        client = Client.query.get(client_id)
        if client:
            db.session.delete(client)
            db.session.commit()
            flash('Cliente eliminado', 'success')
    
    return redirect(url_for('dashboard'))

@app.route('/export_clients')
@login_required
def export_clients():
    if current_user.role != 'admin':
        flash('No autorizado', 'danger')
        return redirect(url_for('dashboard'))
    
    clients = Client.query.all()
    data = [{
        'name': c.name,
        'phone': c.phone,
        'email': c.email,
        'address': c.address,
        'link': c.link,
        'notes': c.notes,
        'has_support': c.has_support
    } for c in clients]
    
    json_data = json.dumps(data, indent=2, ensure_ascii=False)
    return send_file(
        io.BytesIO(json_data.encode('utf-8')),
        mimetype='application/json',
        as_attachment=True,
        download_name='clientes_oslaprint.json'
    )

@app.route('/import_clients', methods=['POST'])
@login_required
def import_clients():
    if current_user.role != 'admin':
        flash('No autorizado', 'danger')
        return redirect(url_for('dashboard'))
    
    if 'file' not in request.files:
        flash('No se seleccionó archivo', 'danger')
        return redirect(url_for('dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('Archivo vacío', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        data = json.load(file)
        imported = 0
        
        for item in data:
            if not Client.query.filter_by(name=item.get('name')).first():
                new_client = Client(
                    name=item.get('name'),
                    phone=item.get('phone', ''),
                    email=item.get('email', ''),
                    address=item.get('address', ''),
                    link=item.get('link'),
                    notes=item.get('notes', ''),
                    has_support=item.get('has_support', False)
                )
                db.session.add(new_client)
                imported += 1
        
        db.session.commit()
        flash(f'✅ Importados {imported} clientes correctamente', 'success')
    except Exception as e:
        print(f"Error importing clients: {e}")
        flash('Error al importar clientes. Verifica el formato JSON.', 'danger')
    
    return redirect(url_for('dashboard'))

# --- GESTIÓN DE SERVICIOS ---
@app.route('/manage_services', methods=['POST'])
@login_required
def manage_services():
    if current_user.role != 'admin':
        flash('No autorizado', 'danger')
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form.get('name')
        color = request.form.get('color', '#6c757d')
        
        if ServiceType.query.filter_by(name=name).first():
            flash('Ya existe un servicio con ese nombre', 'danger')
            return redirect(url_for('dashboard'))
        
        new_service = ServiceType(name=name, color=color)
        db.session.add(new_service)
        db.session.commit()
        flash(f'Tipo de servicio "{name}" añadido', 'success')
    
    elif action == 'edit':
        service_id = request.form.get('service_id')
        service = ServiceType.query.get(service_id)
        if service:
            service.name = request.form.get('name')
            service.color = request.form.get('color')
            db.session.commit()
            flash('Servicio actualizado', 'success')
    
    elif action == 'delete':
        service_id = request.form.get('service_id')
        service = ServiceType.query.get(service_id)
        if service:
            db.session.delete(service)
            db.session.commit()
            flash('Servicio eliminado', 'success')
    
    return redirect(url_for('dashboard'))

# --- GESTIÓN DE STOCK ---
@app.route('/manage_stock', methods=['POST'])
@login_required
def manage_stock():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form.get('name')
        category_id = request.form.get('category_id')
        quantity = int(request.form.get('quantity', 0))
        min_stock = int(request.form.get('min_stock', 5))
        
        new_item = Stock(
            name=name,
            category_id=int(category_id) if category_id else None,
            quantity=quantity,
            min_stock=min_stock
        )
        db.session.add(new_item)
        db.session.commit()
        check_low_stock()
        
        return jsonify({'success': True, 'msg': 'Artículo añadido correctamente'})
    
    elif action == 'adjust':
        item_id = request.form.get('item_id')
        adjustment = int(request.form.get('adjustment', 0))
        
        item = Stock.query.get(item_id)
        if item:
            item.quantity += adjustment
            db.session.commit()
            check_low_stock()
            return jsonify({'success': True, 'msg': 'Stock ajustado', 'new_quantity': item.quantity})
    
    elif action == 'delete':
        item_id = request.form.get('item_id')
        item = Stock.query.get(item_id)
        if item:
            db.session.delete(item)
            db.session.commit()
            return jsonify({'success': True, 'msg': 'Artículo eliminado'})
    
    return jsonify({'success': False, 'msg': 'Acción no válida'})

@app.route('/manage_stock_categories', methods=['POST'])
@login_required
def manage_stock_categories():
    if current_user.role != 'admin':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form.get('name')
        parent_id = request.form.get('parent_id')
        
        if StockCategory.query.filter_by(name=name).first():
            return jsonify({'success': False, 'msg': 'Ya existe una categoría con ese nombre'})
        
        new_category = StockCategory(
            name=name,
            parent_id=int(parent_id) if parent_id else None
        )
        db.session.add(new_category)
        db.session.commit()
        
        return jsonify({'success': True, 'msg': 'Categoría creada correctamente'})
    
    elif action == 'delete':
        category_id = request.form.get('category_id')
        category = StockCategory.query.get(category_id)
        
        if category:
            # Si tiene subcategorías, no permitir eliminar
            if category.subcategories:
                return jsonify({'success': False, 'msg': 'No se puede eliminar una categoría con subcategorías'})
            
            # Los productos se quedan sin categoría (category_id = None)
            for item in category.items:
                item.category_id = None
            
            db.session.delete(category)
            db.session.commit()
            
            return jsonify({'success': True, 'msg': 'Categoría eliminada'})
    
    return jsonify({'success': False, 'msg': 'Acción no válida'})

# --- GESTIÓN DE TAREAS Y CITAS ---
@app.route('/save_report', methods=['POST'])
@login_required
def save_report():
    """Guardar parte de trabajo desde el panel técnico"""
    try:
        linked_task_id = request.form.get('linked_task_id')
        client_name = request.form.get('client_name')
        service_type_name = request.form.get('service_type')
        task_date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        entry_time = request.form.get('entry_time')
        exit_time = request.form.get('exit_time')
        description = request.form.get('description')
        parts_text = request.form.get('parts_text', '')
        
        # Stock
        stock_item_id = request.form.get('stock_item')
        stock_qty = request.form.get('stock_qty', 0)
        stock_action = request.form.get('stock_action', 'used')
        
        # Firma digital
        signature_data = request.form.get('signature_data')
        signature_name = request.form.get('signature_client_name')
        
        if not signature_data:
            flash('⚠️ La firma del cliente es obligatoria', 'danger')
            return redirect(url_for('dashboard'))
        
        # Buscar cliente y servicio
        client = Client.query.filter_by(name=client_name).first()
        client_id = client.id if client else None
        
        service_type = ServiceType.query.filter_by(name=service_type_name).first()
        if not service_type:
            flash('Tipo de servicio no válido', 'danger')
            return redirect(url_for('dashboard'))
        
        # Si hay una cita vinculada, actualizar esa tarea
        if linked_task_id and linked_task_id != 'none':
            task = Task.query.get(int(linked_task_id))
            if task and task.tech_id == current_user.id:
                # Actualizar la tarea existente
                task.description = description
                task.parts_text = parts_text
                task.signature_data = signature_data
                task.signature_client_name = signature_name
                task.signature_timestamp = datetime.now()
                task.status = 'Completado'
                task.actual_end_time = datetime.now()
                
                # Manejar stock si aplica
                if stock_item_id and int(stock_item_id) > 0:
                    stock_item = Stock.query.get(int(stock_item_id))
                    if stock_item:
                        quantity = int(stock_qty)
                        task.stock_item_id = stock_item.id
                        task.stock_quantity_used = quantity
                        task.stock_action = stock_action
                        
                        if stock_action == 'used' or stock_action == 'removed':
                            stock_item.quantity -= quantity
                        elif stock_action == 'added':
                            stock_item.quantity += quantity
                
                db.session.commit()
                check_low_stock()
                
                flash('✅ Parte vinculado completado y firmado correctamente.', 'success')
                return redirect(url_for('dashboard'))
        
        # Si no hay cita vinculada, crear una nueva tarea completada
        new_task = Task(
            tech_id=current_user.id,
            client_id=client_id,
            client_name=client_name,
            date=task_date,
            start_time=entry_time,
            end_time=exit_time,
            service_type_id=service_type.id,
            description=description,
            parts_text=parts_text,
            signature_data=signature_data,
            signature_client_name=signature_name,
            signature_timestamp=datetime.now(),
            status='Completado',
            actual_end_time=datetime.now()
        )
        
        # Manejar stock
        if stock_item_id and int(stock_item_id) > 0:
            stock_item = Stock.query.get(int(stock_item_id))
            if stock_item:
                quantity = int(stock_qty)
                new_task.stock_item_id = stock_item.id
                new_task.stock_quantity_used = quantity
                new_task.stock_action = stock_action
                
                if stock_action == 'used' or stock_action == 'removed':
                    stock_item.quantity -= quantity
                elif stock_action == 'added':
                    stock_item.quantity += quantity
        
        db.session.add(new_task)
        db.session.commit()
        check_low_stock()
        
        # Manejar archivos adjuntos si los hay
        if 'attachments' in request.files:
            files = request.files.getlist('attachments')
            uploaded_filenames = []
            
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"task_{new_task.id}_{timestamp}_{filename}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    uploaded_filenames.append(filename)
            
            if uploaded_filenames:
                new_task.attachments = json.dumps(uploaded_filenames)
                db.session.commit()
        
        flash('✅ Parte de trabajo creado y firmado correctamente.', 'success')
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"Error en save_report: {e}")
        flash(f'Error al guardar el parte: {str(e)}', 'danger')
        return redirect(url_for('dashboard'))

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
        tech_id = request.args.get('tech_id')
        if tech_id:
            tasks = Task.query.filter_by(tech_id=int(tech_id)).all()
        else:
            tasks = Task.query.all()
    else:
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
                'tech_name': task.tech.username if task.tech else 'Sin asignar',
                'has_signature': bool(task.signature_data)
            }
        })
    
    return jsonify(events)

@app.route('/api/clients_search')
@login_required
def api_clients_search():
    """API para autocompletado de clientes"""
    query = request.args.get('q', '').strip()
    
    if len(query) < 2:
        return jsonify([])
    
    clients = Client.query.filter(
        Client.name.ilike(f'%{query}%')
    ).order_by(Client.name).limit(10).all()
    
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'phone': c.phone,
        'email': c.email,
        'address': c.address,
        'link': c.link,
        'has_support': c.has_support
    } for c in clients])

@app.route('/api/clients')
@login_required
def get_clients():
    """API para autocompletado de clientes (alias)"""
    return api_clients_search()

# ====== NUEVA RUTA: GET_TASK_FULL ======
@app.route('/api/get_task_full/<int:task_id>')
@login_required
def get_task_full(task_id):
    """
    API para obtener datos completos de una tarea
    Usado cuando se selecciona una cita en el formulario de parte
    """
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    service_type = ServiceType.query.get(task.service_type_id) if task.service_type_id else None
    
    return jsonify({
        'success': True,
        'data': {
            'id': task.id,
            'client_name': task.client_name,
            'date': task.date.strftime('%Y-%m-%d'),
            'start_time': task.start_time or '',
            'end_time': task.end_time or '',
            'service_type': service_type.name if service_type else '',
            'description': task.description or ''
        }
    })

@app.route('/api/task/<int:task_id>')
@login_required
def get_task_details(task_id):
    task = Task.query.get_or_404(task_id)
    
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
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
            'signature_client_name': task.signature_client_name,
            'signature_timestamp': task.signature_timestamp.strftime('%d/%m/%Y %H:%M') if task.signature_timestamp else None,
            'actual_start_time': task.actual_start_time.strftime('%H:%M') if task.actual_start_time else None,
            'actual_end_time': task.actual_end_time.strftime('%H:%M') if task.actual_end_time else None,
            'stock_info': {
                'item_name': task.stock_item.name if task.stock_item else None,
                'quantity': task.stock_quantity_used,
                'action': task.stock_action
            } if task.stock_item else None
        }
    })

# ====== NUEVA RUTA: TECH_ANALYTICS (CORREGIDA - SIN INGRESOS NI TOP CLIENTES) ======
@app.route('/api/tech_analytics')
@login_required
def get_tech_analytics():
    """Estadísticas del técnico actual (para panel técnico)"""
    period = request.args.get('period', '30')
    
    # Calcular fecha de inicio según período
    if period == 'all':
        start_date = date(2020, 1, 1)  # Fecha arbitraria en el pasado
    else:
        days = int(period)
        start_date = date.today() - timedelta(days=days)
    
    # Obtener tareas del técnico en el período
    tasks = Task.query.filter(
        Task.tech_id == current_user.id,
        Task.status == 'Completado',
        Task.date >= start_date
    ).all()
    
    # Calcular estadísticas
    total_services = len(tasks)
    total_maintenances = sum(1 for t in tasks if t.service_type and 'manten' in t.service_type.name.lower())
    
    # Tiempo promedio
    total_time = 0
    time_count = 0
    for task in tasks:
        if task.actual_start_time and task.actual_end_time:
            duration = (task.actual_end_time - task.actual_start_time).total_seconds() / 3600
            total_time += duration
            time_count += 1
    
    avg_time = round(total_time / time_count, 1) if time_count > 0 else 0
    
    # Distribución por tipo de servicio
    service_distribution = {}
    for task in tasks:
        service_name = task.service_type.name if task.service_type else 'Sin tipo'
        service_distribution[service_name] = service_distribution.get(service_name, 0) + 1
    
    # Timeline de los últimos meses
    timeline_data = []
    for i in range(5, -1, -1):
        month_date = date.today() - timedelta(days=i*30)
        month_start = month_date.replace(day=1)
        if i > 0:
            next_month = month_date + timedelta(days=30)
            month_end = next_month.replace(day=1)
        else:
            month_end = date.today()
        
        month_tasks = Task.query.filter(
            Task.tech_id == current_user.id,
            Task.date >= month_start,
            Task.date < month_end,
            Task.status == 'Completado'
        ).count()
        
        timeline_data.append({
            'month': month_start.strftime('%b'),
            'services': month_tasks,
            'maintenances': month_tasks // 3  # Estimación
        })
    
    return jsonify({
        'total_services': total_services,
        'total_maintenances': total_maintenances,
        'avg_time': avg_time,
        'service_distribution': service_distribution,
        'timeline_data': timeline_data
    })

@app.route('/api/tech_stats/<int:tech_id>')
@login_required
def get_tech_stats(tech_id):
    """Análisis individual de trabajador"""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    tech = User.query.get_or_404(tech_id)
    tasks = Task.query.filter_by(tech_id=tech_id, status='Completado').all()
    
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
            'has_attachments': bool(task.attachments),
            'has_signature': bool(task.signature_data)
        })
        
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

@app.route('/api/admin_analytics')
@login_required
def get_admin_analytics():
    """Estadísticas globales para el administrador"""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    tech_id = request.args.get('tech_id', type=int)
    period = request.args.get('period', 'all')
    
    query = Task.query
    
    if tech_id:
        query = query.filter_by(tech_id=tech_id)
    
    if period == 'week':
        week_ago = date.today() - timedelta(days=7)
        query = query.filter(Task.date >= week_ago)
    elif period == 'month':
        month_ago = date.today() - timedelta(days=30)
        query = query.filter(Task.date >= month_ago)
    
    all_tasks = query.all()
    completed_tasks = query.filter_by(status='Completado').all()
    pending_tasks = query.filter_by(status='Pendiente').all()
    
    task_types = {}
    total_for_percentage = len(completed_tasks) if completed_tasks else 1
    
    for task in completed_tasks:
        service_type = ServiceType.query.get(task.service_type_id) if task.service_type_id else None
        service_name = service_type.name if service_type else 'Sin tipo'
        service_color = service_type.color if service_type else '#6c757d'
        
        if service_name not in task_types:
            task_types[service_name] = {
                'count': 0,
                'color': service_color,
                'percentage': 0
            }
        
        task_types[service_name]['count'] += 1
    
    for service_name in task_types:
        count = task_types[service_name]['count']
        task_types[service_name]['percentage'] = round((count / total_for_percentage) * 100, 1)
    
    monthly_tasks = []
    for i in range(5, -1, -1):
        month_date = date.today() - timedelta(days=i*30)
        month_start = month_date.replace(day=1)
        if i > 0:
            next_month = month_date + timedelta(days=30)
            month_end = next_month.replace(day=1)
        else:
            month_end = date.today()
        
        month_tasks = Task.query.filter(
            Task.date >= month_start,
            Task.date < month_end,
            Task.status == 'Completado'
        )
        if tech_id:
            month_tasks = month_tasks.filter_by(tech_id=tech_id)
        
        monthly_tasks.append({
            'month': month_start.strftime('%b'),
            'count': month_tasks.count()
        })
    
    active_techs = User.query.filter_by(role='tech').count()
    
    return jsonify({
        'success': True,
        'data': {
            'total_tasks': len(all_tasks),
            'completed_tasks': len(completed_tasks),
            'pending_tasks': len(pending_tasks),
            'active_technicians': active_techs,
            'task_types': task_types,
            'monthly_tasks': monthly_tasks
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

@app.route('/print_report/<int:report_id>')
@login_required
def print_report(report_id):
    """Endpoint para imprimir/exportar reporte de trabajo"""
    try:
        task = Task.query.get_or_404(report_id)
        
        # Verificar permisos
        if current_user.role != 'admin' and task.tech_id != current_user.id:
            flash('No tienes permiso para ver este reporte', 'danger')
            return redirect(url_for('dashboard'))
        
        # Parsear archivos adjuntos si existen
        attachments = []
        if task.attachments:
            try:
                attachments = json.loads(task.attachments)
            except:
                attachments = []
        
        return render_template('print_report.html', 
                             task=task,
                             attachments=attachments)
    except Exception as e:
        print(f"Error printing report {report_id}: {str(e)}")
        flash('Error al cargar el reporte', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/api/task_action/<int:task_id>/<action>', methods=['POST'])
@login_required
def task_action(task_id, action):
    """Endpoint para acciones sobre tareas (completar, eliminar, cancelar)"""
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and task.tech_id != current_user.id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    try:
        if action == 'complete':
            task.status = 'Completado'
            if not task.actual_end_time:
                task.actual_end_time = datetime.now()
            db.session.commit()
            return jsonify({'success': True, 'msg': 'Tarea completada'})
        
        elif action == 'delete':
            db.session.delete(task)
            db.session.commit()
            return jsonify({'success': True, 'msg': 'Tarea eliminada'})
        
        elif action == 'cancel':
            task.status = 'Cancelado'
            db.session.commit()
            return jsonify({'success': True, 'msg': 'Tarea cancelada'})
        
        else:
            return jsonify({'success': False, 'msg': 'Acción no válida'}), 400
    
    except Exception as e:
        print(f"Error in task_action: {e}")
        db.session.rollback()
        return jsonify({'success': False, 'msg': 'Error al procesar la acción'}), 500

@app.route('/api/get_task/<int:task_id>')
@login_required
def get_task(task_id):
    """Obtener datos de una tarea específica"""
    task = Task.query.get_or_404(task_id)
    
    if current_user.role != 'admin' and task.tech_id != current_user.id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    service_type = ServiceType.query.get(task.service_type_id) if task.service_type_id else None
    
    return jsonify({
        'success': True,
        'data': {
            'id': task.id,
            'client_name': task.client_name,
            'date': task.date.strftime('%Y-%m-%d'),
            'time': task.start_time or '',
            'service_type': service_type.name if service_type else '',
            'notes': task.description or ''
        }
    })

@app.route('/api/task_details/<int:task_id>')
@login_required
def api_task_details(task_id):
    """Obtener detalles completos de una tarea"""
    task = Task.query.get_or_404(task_id)
    
    if current_user.role != 'admin' and task.tech_id != current_user.id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    service_type = ServiceType.query.get(task.service_type_id) if task.service_type_id else None
    
    # Parsear attachments
    attachments_list = []
    if task.attachments:
        try:
            attachments_list = json.loads(task.attachments)
        except:
            pass
    
    return jsonify({
        'success': True,
        'data': {
            'id': task.id,
            'client_name': task.client_name,
            'tech_name': task.tech.username if task.tech else 'Sin asignar',
            'date': task.date.strftime('%Y-%m-%d'),
            'start_time': task.start_time or '',
            'end_time': task.end_time or '',
            'service_type': service_type.name if service_type else 'Sin tipo',
            'status': task.status,
            'description': task.description or '',
            'parts_text': task.parts_text or '',
            'has_signature': bool(task.signature_data),
            'attachments': attachments_list,
            'stock_info': {
                'item_name': task.stock_item.name if task.stock_item else None,
                'quantity': task.stock_quantity_used,
                'action': task.stock_action
            } if task.stock_item else None
        }
    })

@app.route('/api/admin/all_tasks')
@login_required
def admin_all_tasks():
    """Endpoint para calendario global del admin"""
    if current_user.role != 'admin':
        return jsonify([])
    
    tasks = Task.query.all()
    events = []
    
    for task in tasks:
        service_type = ServiceType.query.get(task.service_type_id) if task.service_type_id else None
        color = service_type.color if service_type else '#6c757d'
        
        events.append({
            'id': task.id,
            'title': f"{task.client_name}",
            'start': f"{task.date}T{task.start_time}:00" if task.start_time else str(task.date),
            'end': f"{task.date}T{task.end_time}:00" if task.end_time else str(task.date),
            'backgroundColor': color,
            'borderColor': color,
            'extendedProps': {
                'client': task.client_name,
                'tech_name': task.tech.username if task.tech else 'Sin asignar',
                'service_type': service_type.name if service_type else 'Sin tipo',
                'status': task.status,
                'desc': task.description or '',
                'has_attachments': bool(task.attachments)
            }
        })
    
    return jsonify(events)

@app.route('/api/admin/tasks/<int:tech_id>')
@login_required
def admin_tech_tasks(tech_id):
    """Endpoint para calendario individual de un técnico desde admin"""
    if current_user.role != 'admin':
        return jsonify([])
    
    tasks = Task.query.filter_by(tech_id=tech_id).all()
    events = []
    
    for task in tasks:
        service_type = ServiceType.query.get(task.service_type_id) if task.service_type_id else None
        color = service_type.color if service_type else '#6c757d'
        
        events.append({
            'id': task.id,
            'title': f"{task.client_name}",
            'start': f"{task.date}T{task.start_time}:00" if task.start_time else str(task.date),
            'end': f"{task.date}T{task.end_time}:00" if task.end_time else str(task.date),
            'backgroundColor': color,
            'borderColor': color,
            'extendedProps': {
                'client': task.client_name,
                'service_type': service_type.name if service_type else 'Sin tipo',
                'status': task.status,
                'desc': task.description or ''
            }
        })
    
    return jsonify(events)

@app.route('/create_appointment', methods=['POST'])
@login_required
def create_appointment():
    """Endpoint para crear una nueva cita desde el panel técnico"""
    try:
        client_name = request.form.get('client_name')
        date_str = request.form.get('date')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        service_type_id = request.form.get('service_type_id')
        description = request.form.get('description', '')
        
        # Validaciones
        if not all([client_name, date_str, start_time, service_type_id]):
            return jsonify({'success': False, 'msg': 'Faltan campos obligatorios'}), 400
        
        # Buscar o crear cliente
        client = Client.query.filter_by(name=client_name).first()
        client_id = client.id if client else None
        
        # Convertir fecha
        task_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Crear tarea
        new_task = Task(
            tech_id=current_user.id,
            client_id=client_id,
            client_name=client_name,
            description=description,
            date=task_date,
            start_time=start_time,
            end_time=end_time,
            service_type_id=int(service_type_id),
            status='Pendiente'
        )
        
        db.session.add(new_task)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'msg': 'Cita creada correctamente',
            'task_id': new_task.id
        })
        
    except Exception as e:
        print(f"Error creating appointment: {str(e)}")
        db.session.rollback()
        return jsonify({'success': False, 'msg': 'Error al crear la cita'}), 500

@app.route('/edit_appointment/<int:task_id>', methods=['POST'])
@login_required
def edit_appointment(task_id):
    """Endpoint para editar una cita existente"""
    try:
        task = Task.query.get_or_404(task_id)
        
        # Verificar permisos
        if current_user.role != 'admin' and task.tech_id != current_user.id:
            flash('No autorizado', 'danger')
            return redirect(url_for('dashboard'))
        
        # Actualizar datos
        task.client_name = request.form.get('client_name')
        task.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()
        task.start_time = request.form.get('time')
        task.description = request.form.get('notes', '')
        
        # Actualizar tipo de servicio
        service_type_name = request.form.get('service_type')
        service_type = ServiceType.query.filter_by(name=service_type_name).first()
        if service_type:
            task.service_type_id = service_type.id
        
        db.session.commit()
        flash('Cita actualizada correctamente', 'success')
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"Error editing appointment: {str(e)}")
        db.session.rollback()
        flash('Error al editar la cita', 'danger')
        return redirect(url_for('dashboard'))

@app.route('/schedule_appointment', methods=['POST'])
@login_required
def schedule_appointment():
    """Endpoint para agendar nueva cita desde el panel admin"""
    try:
        if current_user.role != 'admin':
            flash('Solo administradores pueden agendar citas', 'danger')
            return redirect(url_for('dashboard'))
        
        tech_id = request.form.get('tech_id')
        client_name = request.form.get('client_name')
        date_str = request.form.get('date')
        time_str = request.form.get('time')
        service_type_name = request.form.get('service_type')
        notes = request.form.get('notes', '')
        
        # Validaciones
        if not all([tech_id, client_name, date_str, time_str, service_type_name]):
            flash('Todos los campos son obligatorios', 'danger')
            return redirect(url_for('dashboard'))
        
        # Buscar o crear cliente
        client = Client.query.filter_by(name=client_name).first()
        client_id = client.id if client else None
        
        # Buscar tipo de servicio
        service_type = ServiceType.query.filter_by(name=service_type_name).first()
        if not service_type:
            flash('Tipo de servicio no válido', 'danger')
            return redirect(url_for('dashboard'))
        
        # Convertir fecha
        task_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Crear tarea
        new_task = Task(
            tech_id=int(tech_id),
            client_id=client_id,
            client_name=client_name,
            description=notes,
            date=task_date,
            start_time=time_str,
            service_type_id=service_type.id,
            status='Pendiente'
        )
        
        db.session.add(new_task)
        db.session.commit()
        
        flash('Cita agendada correctamente', 'success')
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        print(f"Error scheduling appointment: {str(e)}")
        db.session.rollback()
        flash('Error al agendar la cita', 'danger')
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

# --- BLOQUE DE INICIALIZACIÓN ---
with app.app_context():
    db.create_all()
    
    # Migración: columna 'link'
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        columns = [col['name'] for col in inspector.get_columns('client')]
        if 'link' not in columns:
            with db.engine.connect() as conn:
                conn.execute(db.text('ALTER TABLE client ADD COLUMN link VARCHAR(500)'))
                conn.commit()
                print("✓ Columna 'link' añadida")
    except Exception as e:
        print(f"Nota: Migración de 'link': {e}")
    
    # Usuarios
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
    
    # Tipos de Servicio
    if ServiceType.query.count() == 0:
        servicios = [
            {'name': 'Avería', 'color': '#fd7e14'},
            {'name': 'Revisión', 'color': '#0d6efd'},
            {'name': 'Instalación', 'color': '#6f42c1'},
            {'name': 'Otros servicios', 'color': '#20c997'}
        ]
        for s in servicios:
            db.session.add(ServiceType(name=s['name'], color=s['color']))
    
    # Categorías de Stock
    if StockCategory.query.count() == 0:
        copiadoras = StockCategory(name='Copiadoras')
        cajones = StockCategory(name='Cajones')
        tpv = StockCategory(name='TPV')
        recicladores = StockCategory(name='Recicladores')
        consumibles = StockCategory(name='Consumibles')
        
        db.session.add_all([copiadoras, cajones, tpv, recicladores, consumibles])
        db.session.commit()
        
        cashlogy = StockCategory(name='Cashlogy', parent_id=cajones.id)
        cashkeeper = StockCategory(name='Cashkeeper', parent_id=cajones.id)
        atca = StockCategory(name='ATCA', parent_id=cajones.id)
        
        db.session.add_all([cashlogy, cashkeeper, atca])
        db.session.commit()
    
    # Productos de Stock
    if Stock.query.count() == 0:
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
    
    # Cliente de ejemplo
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