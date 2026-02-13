import os
import json
from datetime import datetime, date
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import io

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
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20))  # 'admin' o 'tech'

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    phone = db.Column(db.String(20))  # OBLIGATORIO
    email = db.Column(db.String(100))  # OBLIGATORIO
    address = db.Column(db.String(250))  # OBLIGATORIO con Google Maps
    notes = db.Column(db.Text)  # Comentarios internos
    has_support = db.Column(db.Boolean, default=False)  # Verde=True, Rojo=False
    support_monday_friday = db.Column(db.Boolean, default=False)
    support_saturday = db.Column(db.Boolean, default=False)
    support_sunday = db.Column(db.Boolean, default=False)

class ServiceType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(7), default='#6c757d')  # Hex code color

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    category = db.Column(db.String(50))  # Copiadoras, Cajones, TPV
    subcategory = db.Column(db.String(50))  # Cashlogy, Cashkeeper, ATCA
    min_stock = db.Column(db.Integer, default=5)  # Para alarmas de stock bajo
    supplier = db.Column(db.String(100))  # NUEVO: Proveedor del producto

class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tech_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    client_name = db.Column(db.String(100))
    description = db.Column(db.Text)
    
    date = db.Column(db.Date, default=date.today)
    start_time = db.Column(db.String(10)) 
    end_time = db.Column(db.String(10))   
    
    service_type = db.Column(db.String(50)) 
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

@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        empleados = User.query.filter_by(role='tech').all()
        informes = Task.query.filter_by(status='Completado').order_by(Task.date.desc()).all()
        inventory = Stock.query.order_by(Stock.category, Stock.subcategory, Stock.name).all()
        clients = Client.query.order_by(Client.name).all()
        services = ServiceType.query.order_by(ServiceType.name).all()
        alarms = Alarm.query.order_by(Alarm.is_read.asc(), Alarm.created_at.desc()).all()
        
        return render_template('admin_panel.html', 
                             empleados=empleados, 
                             informes=informes, 
                             inventory=inventory, 
                             clients=clients, 
                             services=services,
                             alarms=alarms)
    
    stock_items = Stock.query.order_by(Stock.category, Stock.name).all()
    pending_tasks = Task.query.filter_by(tech_id=current_user.id, status='Pendiente').order_by(Task.date).all()
    
    return render_template('tech_panel.html', 
                           today_date=date.today().strftime('%Y-%m-%d'), 
                           stock_items=stock_items,
                           pending_tasks=pending_tasks)

@app.route('/manage_users', methods=['POST'])
@login_required
def manage_users():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        if User.query.filter_by(username=username).first():
            flash('El nombre de usuario ya existe.', 'danger')
        else:
            hashed_password = generate_password_hash(password)
            new_user = User(username=username, password_hash=hashed_password, role=role)
            db.session.add(new_user)
            db.session.commit()
            flash(f'Usuario {username} creado exitosamente.', 'success')
            
    elif action == 'delete':
        user_id = request.form.get('user_id')
        user = User.query.get(user_id)
        if user:
            if user.id == current_user.id:
                flash('No puedes eliminar tu propio usuario.', 'danger')
            else:
                Task.query.filter_by(tech_id=user.id).delete()
                db.session.delete(user)
                db.session.commit()
                flash('Usuario y sus tareas eliminados.', 'warning')
    
    return redirect(url_for('dashboard'))

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current_pass = request.form.get('current_password')
    new_pass = request.form.get('new_password')
    
    if check_password_hash(current_user.password_hash, current_pass):
        current_user.password_hash = generate_password_hash(new_pass)
        db.session.commit()
        flash('Contraseña actualizada correctamente.', 'success')
    else:
        flash('La contraseña actual es incorrecta.', 'danger')
        
    return redirect(url_for('dashboard'))

@app.route('/manage_services', methods=['POST'])
@login_required
def manage_services():
    if current_user.role != 'admin': 
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        existing = ServiceType.query.filter_by(name=request.form['name']).first()
        if not existing:
            db.session.add(ServiceType(name=request.form['name'], color=request.form['color']))
            flash('Tipo de servicio añadido.', 'success')
        else:
            flash('Ese servicio ya existe.', 'warning')
            
    elif action == 'edit':
        svc = ServiceType.query.get(request.form['service_id'])
        if svc:
            svc.name = request.form['name']
            svc.color = request.form['color']
            flash('Servicio actualizado.', 'success')
            
    elif action == 'delete':
        svc = ServiceType.query.get(request.form['service_id'])
        if svc:
            db.session.delete(svc)
            flash('Tipo de servicio eliminado.', 'warning')
            
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/manage_clients', methods=['POST'])
@login_required
def manage_clients():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        address = request.form.get('address', '').strip()
        
        # Validación de campos obligatorios
        if not name or not phone or not email or not address:
            flash('Nombre, teléfono, email y dirección son obligatorios.', 'danger')
            return redirect(url_for('dashboard'))
        
        if Client.query.filter_by(name=name).first():
            flash('Ya existe un cliente con ese nombre.', 'warning')
        else:
            new_client = Client(
                name=name,
                phone=phone,
                email=email,
                address=address,
                notes=request.form.get('notes', ''),
                has_support=request.form.get('has_support') == 'on',
                support_monday_friday=request.form.get('support_monday_friday') == 'on',
                support_saturday=request.form.get('support_saturday') == 'on',
                support_sunday=request.form.get('support_sunday') == 'on'
            )
            db.session.add(new_client)
            db.session.commit()
            flash('Cliente añadido correctamente.', 'success')
            
    elif action == 'edit':
        client = Client.query.get(request.form['client_id'])
        if client:
            phone = request.form.get('phone', '').strip()
            email = request.form.get('email', '').strip()
            address = request.form.get('address', '').strip()
            
            if not phone or not email or not address:
                flash('Teléfono, email y dirección son obligatorios.', 'danger')
                return redirect(url_for('dashboard'))
            
            client.name = request.form['name']
            client.phone = phone
            client.email = email
            client.address = address
            client.notes = request.form.get('notes', '')
            client.has_support = request.form.get('has_support') == 'on'
            client.support_monday_friday = request.form.get('support_monday_friday') == 'on'
            client.support_saturday = request.form.get('support_saturday') == 'on'
            client.support_sunday = request.form.get('support_sunday') == 'on'
            db.session.commit()
            flash('Cliente actualizado.', 'success')
            
    elif action == 'delete':
        client = Client.query.get(request.form['client_id'])
        if client:
            db.session.delete(client)
            db.session.commit()
            flash('Cliente eliminado.', 'warning')
    
    return redirect(url_for('dashboard'))

@app.route('/manage_stock', methods=['POST'])
@login_required
def manage_stock():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    try:
        if action == 'add':
            name = request.form.get('name', '').strip()
            category = request.form.get('category', '').strip()
            subcategory = request.form.get('subcategory', '').strip()
            supplier = request.form.get('supplier', '').strip()
            quantity = int(request.form.get('quantity', 0))
            min_stock = int(request.form.get('min_stock', 5))
            
            # Validación
            if not name:
                flash('El nombre del producto es obligatorio.', 'danger')
                return redirect(url_for('dashboard'))
            
            new_item = Stock(
                name=name,
                category=category,
                subcategory=subcategory,
                supplier=supplier,
                quantity=quantity,
                min_stock=min_stock
            )
            db.session.add(new_item)
            db.session.commit()
            
            # Verificar stock bajo
            check_low_stock()
            
            flash('Producto añadido al inventario.', 'success')
            
        elif action == 'edit':
            item_id = request.form.get('item_id')
            if not item_id:
                flash('ID de producto no válido.', 'danger')
                return redirect(url_for('dashboard'))
                
            item = Stock.query.get(int(item_id))
            if item:
                name = request.form.get('name', '').strip()
                if not name:
                    flash('El nombre del producto es obligatorio.', 'danger')
                    return redirect(url_for('dashboard'))
                    
                item.name = name
                item.category = request.form.get('category', '').strip()
                item.subcategory = request.form.get('subcategory', '').strip()
                item.supplier = request.form.get('supplier', '').strip()
                item.quantity = int(request.form.get('quantity', 0))
                item.min_stock = int(request.form.get('min_stock', 5))
                db.session.commit()
                
                # Verificar stock bajo
                check_low_stock()
                
                flash('Producto actualizado.', 'success')
            else:
                flash('Producto no encontrado.', 'danger')
            
        elif action == 'adjust':
            item_id = request.form.get('item_id')
            adjust_qty = int(request.form.get('adjust_qty', 0))
            
            if not item_id:
                flash('ID de producto no válido.', 'danger')
                return redirect(url_for('dashboard'))
                
            item = Stock.query.get(int(item_id))
            if item:
                item.quantity += adjust_qty
                if item.quantity < 0:
                    item.quantity = 0
                db.session.commit()
                check_low_stock()
                flash(f'Stock ajustado correctamente. Nueva cantidad: {item.quantity}', 'success')
            else:
                flash('Producto no encontrado.', 'danger')
                
        elif action == 'delete':
            item_id = request.form.get('item_id')
            if not item_id:
                flash('ID de producto no válido.', 'danger')
                return redirect(url_for('dashboard'))
                
            item = Stock.query.get(int(item_id))
            if item:
                db.session.delete(item)
                db.session.commit()
                flash('Producto eliminado.', 'warning')
            else:
                flash('Producto no encontrado.', 'danger')
    
    except ValueError as e:
        flash(f'Error en los datos proporcionados: {str(e)}', 'danger')
    except Exception as e:
        flash(f'Error al gestionar el stock: {str(e)}', 'danger')
        print(f"Error en manage_stock: {e}")
    
    return redirect(url_for('dashboard'))

@app.route('/schedule_appointment', methods=['POST'])
@login_required
def schedule_appointment():
    """
    MEJORADO: Ruta para agendar citas con validaciones robustas
    """
    if current_user.role != 'admin':
        flash('No tienes permisos para agendar citas.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        # Validación de campos requeridos
        tech_id = request.form.get('tech_id')
        client_name = request.form.get('client_name', '').strip()
        date_str = request.form.get('date', '').strip()
        time_str = request.form.get('time', '').strip()
        service_type = request.form.get('service_type', '').strip()
        
        # Validar campos obligatorios
        if not tech_id:
            flash('Debes seleccionar un técnico.', 'danger')
            return redirect(url_for('dashboard'))
            
        if not client_name:
            flash('El nombre del cliente es obligatorio.', 'danger')
            return redirect(url_for('dashboard'))
            
        if not date_str:
            flash('La fecha es obligatoria.', 'danger')
            return redirect(url_for('dashboard'))
            
        if not service_type:
            flash('El tipo de servicio es obligatorio.', 'danger')
            return redirect(url_for('dashboard'))
        
        # Convertir y validar tipos
        tech_id = int(tech_id)
        task_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Verificar que el técnico existe
        tech = User.query.get(tech_id)
        if not tech:
            flash('El técnico seleccionado no existe.', 'danger')
            return redirect(url_for('dashboard'))
        
        # Verificar que el tipo de servicio existe
        service = ServiceType.query.filter_by(name=service_type).first()
        if not service:
            flash('El tipo de servicio seleccionado no existe.', 'danger')
            return redirect(url_for('dashboard'))
        
        # Crear nueva tarea
        notes = request.form.get('notes', '').strip()
        
        new_task = Task(
            tech_id=tech_id,
            client_name=client_name,
            date=task_date,
            start_time=time_str if time_str else None,
            service_type=service_type,
            description=notes,
            status='Pendiente'
        )
        
        db.session.add(new_task)
        db.session.commit()
        
        flash(f'Cita programada correctamente para {client_name} el {task_date.strftime("%d/%m/%Y")}.', 'success')
        
    except ValueError as ve:
        db.session.rollback()
        flash(f'Error en el formato de datos: {str(ve)}', 'danger')
        print(f"ValueError en schedule_appointment: {ve}")
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al programar la cita: {str(e)}', 'danger')
        print(f"Error en schedule_appointment: {e}")
    
    return redirect(url_for('dashboard'))

@app.route('/create_appointment', methods=['POST'])
@login_required
def create_appointment():
    """
    MEJORADO: Ruta para que los técnicos creen sus propias citas
    """
    try:
        # Validación de campos
        client_name = request.form.get('client_name', '').strip()
        date_str = request.form.get('date', '').strip()
        time_str = request.form.get('time', '').strip()
        service_type = request.form.get('service_type', '').strip()
        
        if not client_name or not date_str or not service_type:
            flash('Cliente, fecha y tipo de servicio son obligatorios.', 'danger')
            return redirect(url_for('dashboard'))
        
        task_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        notes = request.form.get('notes', '').strip()
        
        new_task = Task(
            tech_id=current_user.id,
            client_name=client_name,
            date=task_date,
            start_time=time_str if time_str else None,
            service_type=service_type,
            description=notes,
            status='Pendiente'
        )
        
        db.session.add(new_task)
        db.session.commit()
        
        flash(f'Cita creada correctamente para {task_date.strftime("%d/%m/%Y")}.', 'success')
        
    except ValueError as ve:
        db.session.rollback()
        flash(f'Error en el formato de fecha: {str(ve)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al crear la cita: {str(e)}', 'danger')
        print(f"Error en create_appointment: {e}")
    
    return redirect(url_for('dashboard'))

@app.route('/edit_appointment/<int:task_id>', methods=['POST'])
@login_required
def edit_appointment(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        flash('No tienes permisos para editar esta cita.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        client_name = request.form.get('client_name', '').strip()
        date_str = request.form.get('date', '').strip()
        service_type = request.form.get('service_type', '').strip()
        
        if not client_name or not date_str or not service_type:
            flash('Cliente, fecha y tipo de servicio son obligatorios.', 'danger')
            return redirect(url_for('dashboard'))
        
        task.client_name = client_name
        task.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        task.start_time = request.form.get('time', '')
        task.service_type = service_type
        task.description = request.form.get('notes', '')
        
        db.session.commit()
        flash('Cita actualizada correctamente.', 'success')
        
    except ValueError as ve:
        db.session.rollback()
        flash(f'Error en el formato de fecha: {str(ve)}', 'danger')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar cita: {str(e)}', 'danger')
        print(f"Error en edit_appointment: {e}")
    
    return redirect(url_for('dashboard'))

@app.route('/delete_appointment/<int:task_id>', methods=['POST'])
@login_required
def delete_appointment(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        flash('No tienes permisos para eliminar esta cita.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        db.session.delete(task)
        db.session.commit()
        flash('Cita eliminada.', 'warning')
    except Exception as e:
        db.session.rollback()
        flash(f'Error al eliminar la cita: {str(e)}', 'danger')
        print(f"Error en delete_appointment: {e}")
    
    return redirect(url_for('dashboard'))

@app.route('/save_report', methods=['POST'])
@login_required
def save_report():
    try:
        # Obtener datos del formulario
        linked_task_id = request.form.get('linked_task_id')
        client_name = request.form['client_name']
        task_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        entry_time = request.form.get('entry_time', '')
        exit_time = request.form.get('exit_time', '')
        service_type = request.form['service_type']
        description = request.form.get('description', '')
        parts_text = request.form.get('parts_text', '')
        signature_data = request.form.get('signature_data', '')
        
        # Verificar si hay firma digital
        if not signature_data or signature_data == '':
            flash('La firma digital del cliente es obligatoria para cerrar el parte.', 'danger')
            return redirect(url_for('dashboard'))
        
        # Manejo de stock
        stock_item_id = request.form.get('stock_item')
        stock_quantity = request.form.get('stock_quantity', 0)
        stock_action = request.form.get('stock_action')
        
        if stock_item_id and stock_item_id != '':
            stock_item_id = int(stock_item_id)
            stock_quantity = int(stock_quantity)
            
            stock_item = Stock.query.get(stock_item_id)
            if stock_item:
                if stock_action == 'used':
                    stock_item.quantity -= stock_quantity
                elif stock_action == 'removed':
                    stock_item.quantity -= stock_quantity
        else:
            stock_item_id = None
            stock_quantity = 0
        
        # Manejo de archivos adjuntos
        attachments_list = []
        if 'files' in request.files:
            files = request.files.getlist('files')
            for file in files:
                if file and file.filename != '' and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Añadir timestamp para evitar colisiones
                    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                    filename = f"{timestamp}_{filename}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    attachments_list.append(filename)
        
        # Si está vinculado a una cita, actualizar esa tarea
        if linked_task_id and linked_task_id != 'none':
            task = Task.query.get(int(linked_task_id))
            if task:
                task.end_time = exit_time
                task.description = description
                task.parts_text = parts_text
                task.stock_item_id = stock_item_id
                task.stock_quantity_used = stock_quantity
                task.stock_action = stock_action
                task.status = 'Completado'
                task.signature_data = signature_data
                task.actual_end_time = datetime.now()
                
                if attachments_list:
                    existing_attachments = []
                    if task.attachments:
                        try:
                            existing_attachments = json.loads(task.attachments)
                        except:
                            pass
                    existing_attachments.extend(attachments_list)
                    task.attachments = json.dumps(existing_attachments)
                
                db.session.commit()
                check_low_stock()
                flash('Parte de trabajo guardado y vinculado a la cita.', 'success')
        else:
            # Crear nueva tarea (incidencia sin cita)
            new_task = Task(
                tech_id=current_user.id,
                client_name=client_name,
                date=task_date,
                start_time=entry_time,
                end_time=exit_time,
                service_type=service_type,
                description=description,
                parts_text=parts_text,
                stock_item_id=stock_item_id,
                stock_quantity_used=stock_quantity,
                stock_action=stock_action,
                status='Completado',
                signature_data=signature_data,
                attachments=json.dumps(attachments_list) if attachments_list else None,
                actual_start_time=datetime.now(),
                actual_end_time=datetime.now()
            )
            db.session.add(new_task)
            db.session.commit()
            check_low_stock()
            flash('Parte de trabajo guardado correctamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al guardar: {str(e)}', 'danger')
        print(f"Error saving report: {e}")
    
    return redirect(url_for('dashboard'))

@app.route('/start_task/<int:task_id>', methods=['POST'])
@login_required
def start_task(task_id):
    """Marcar inicio de trabajo en una tarea"""
    task = Task.query.get_or_404(task_id)
    
    if task.tech_id != current_user.id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    task.actual_start_time = datetime.now()
    task.start_time = datetime.now().strftime('%H:%M')
    db.session.commit()
    
    return jsonify({
        'success': True,
        'msg': 'Trabajo iniciado',
        'start_time': task.start_time
    })

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# --- API ENDPOINTS ---

@app.route('/api/clients')
@login_required
def get_clients():
    clients = Client.query.order_by(Client.name).all()
    return jsonify([{
        'id': c.id, 
        'name': c.name,
        'phone': c.phone,
        'email': c.email,
        'address': c.address,
        'has_support': c.has_support
    } for c in clients])

@app.route('/api/client/<int:client_id>')
@login_required
def get_client_details(client_id):
    """
    MEJORADO: Devuelve información completa del cliente
    """
    client = Client.query.get_or_404(client_id)
    
    # Obtener historial de servicios para este cliente
    tasks = Task.query.filter_by(client_name=client.name).order_by(Task.date.desc()).limit(10).all()
    
    tasks_history = [{
        'id': t.id,
        'date': t.date.strftime('%d/%m/%Y'),
        'service_type': t.service_type,
        'status': t.status,
        'tech_name': t.tech.username if t.tech else 'Sin asignar'
    } for t in tasks]
    
    return jsonify({
        'success': True,
        'data': {
            'id': client.id,
            'name': client.name,
            'phone': client.phone,
            'email': client.email,
            'address': client.address,
            'notes': client.notes,
            'has_support': client.has_support,
            'support_monday_friday': client.support_monday_friday,
            'support_saturday': client.support_saturday,
            'support_sunday': client.support_sunday,
            'tasks_history': tasks_history
        }
    })

@app.route('/api/client_by_name')
@login_required
def get_client_by_name():
    """
    NUEVO: Buscar cliente por nombre para mostrar información al hacer clic en tarea
    """
    client_name = request.args.get('name', '').strip()
    
    if not client_name:
        return jsonify({'success': False, 'msg': 'Nombre no proporcionado'}), 400
    
    client = Client.query.filter_by(name=client_name).first()
    
    if not client:
        return jsonify({
            'success': False,
            'msg': 'Cliente no encontrado en la base de datos',
            'data': {
                'name': client_name,
                'is_registered': False
            }
        })
    
    # Obtener historial de servicios
    tasks = Task.query.filter_by(client_name=client.name).order_by(Task.date.desc()).limit(10).all()
    
    tasks_history = [{
        'id': t.id,
        'date': t.date.strftime('%d/%m/%Y'),
        'service_type': t.service_type,
        'status': t.status,
        'tech_name': t.tech.username if t.tech else 'Sin asignar',
        'description': t.description or 'Sin descripción'
    } for t in tasks]
    
    return jsonify({
        'success': True,
        'data': {
            'id': client.id,
            'name': client.name,
            'phone': client.phone,
            'email': client.email,
            'address': client.address,
            'notes': client.notes,
            'has_support': client.has_support,
            'support_monday_friday': client.support_monday_friday,
            'support_saturday': client.support_saturday,
            'support_sunday': client.support_sunday,
            'is_registered': True,
            'tasks_history': tasks_history,
            'total_services': len(tasks_history)
        }
    })

@app.route('/api/clients_search')
@login_required
def search_clients():
    q = request.args.get('q', '').lower()
    clients = Client.query.filter(Client.name.ilike(f'%{q}%')).limit(10).all()
    return jsonify([{'id': c.id, 'name': c.name} for c in clients])

@app.route('/api/get_task/<int:task_id>')
@login_required
def get_task(task_id):
    task = Task.query.get_or_404(task_id)
    return jsonify({
        'success': True,
        'data': {
            'client_name': task.client_name,
            'date': task.date.strftime('%Y-%m-%d'),
            'time': task.start_time,
            'service_type': task.service_type,
            'notes': task.description
        }
    })

@app.route('/api/calendar_events')
@login_required
def get_calendar_events():
    """Obtener eventos del calendario"""
    tech_id = request.args.get('tech_id')
    
    query = Task.query
    
    # Filtrar por técnico si se especifica
    if tech_id and tech_id != 'all':
        query = query.filter_by(tech_id=int(tech_id))
    
    # Si es técnico, solo ver sus propias tareas
    if current_user.role == 'tech':
        query = query.filter_by(tech_id=current_user.id)
    
    tasks = query.all()
    
    events = []
    for task in tasks:
        # Obtener color del tipo de servicio
        service = ServiceType.query.filter_by(name=task.service_type).first()
        color = service.color if service else '#6c757d'
        
        event = {
            'id': task.id,
            'title': f"{task.client_name} - {task.service_type}",
            'start': task.date.strftime('%Y-%m-%d'),
            'backgroundColor': color,
            'borderColor': color,
            'extendedProps': {
                'client': task.client_name,
                'service_type': task.service_type,
                'status': task.status,
                'desc': task.description,
                'tech_name': task.tech.username if task.tech else 'Sin asignar',
                'has_attachments': bool(task.attachments)
            }
        }
        
        # Añadir hora si está disponible
        if task.start_time:
            event['start'] += f"T{task.start_time}:00"
        
        events.append(event)
    
    return jsonify(events)

@app.route('/api/task_action/<int:task_id>/<action>', methods=['POST'])
@login_required
def task_action(task_id, action):
    """Realizar acciones sobre tareas"""
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    try:
        if action == 'complete':
            task.status = 'Completado'
            task.actual_end_time = datetime.now()
            db.session.commit()
            return jsonify({'success': True, 'msg': 'Tarea completada'})
            
        elif action == 'delete':
            db.session.delete(task)
            db.session.commit()
            return jsonify({'success': True, 'msg': 'Tarea eliminada'})
            
        else:
            return jsonify({'success': False, 'msg': 'Acción no válida'}), 400
            
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'msg': str(e)}), 500

@app.route('/api/task_details/<int:task_id>')
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
    
    return jsonify({
        'success': True,
        'data': {
            'id': task.id,
            'client_name': task.client_name,
            'date': task.date.strftime('%Y-%m-%d'),
            'start_time': task.start_time,
            'end_time': task.end_time,
            'service_type': task.service_type,
            'description': task.description,
            'parts_text': task.parts_text,
            'status': task.status,
            'tech_name': task.tech.username if task.tech else 'SIN TÉCNICO',
            'attachments': attachments_list,
            'has_signature': bool(task.signature_data),
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
        service_type = task.service_type
        if service_type not in service_stats:
            service_stats[service_type] = {
                'count': 0,
                'tasks': []
            }
        
        service_stats[service_type]['count'] += 1
        service_stats[service_type]['tasks'].append({
            'id': task.id,
            'client': task.client_name,
            'date': task.date.strftime('%d/%m/%Y'),
            'time': f"{task.start_time} - {task.end_time}",
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

@app.route('/api/admin_analytics')
@login_required
def get_admin_analytics():
    """
    MEJORADO: Endpoint para estadísticas del administrador con mejor manejo de datos
    """
    if current_user.role != 'admin':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    try:
        tech_id = request.args.get('tech_id')
        period = request.args.get('period', '30')
        
        if not tech_id:
            return jsonify({'success': False, 'msg': 'ID de técnico requerido'}), 400
        
        # Construir query base
        query = Task.query.filter_by(tech_id=int(tech_id), status='Completado')
        
        # Aplicar filtro de período
        if period != 'all':
            days = int(period)
            cutoff_date = date.today() - timedelta(days=days)
            query = query.filter(Task.date >= cutoff_date)
        
        tasks = query.order_by(Task.date.desc()).all()
        
        # Calcular estadísticas
        total_services = len(tasks)
        service_distribution = {}
        total_revenue = 0
        total_time = 0
        clients_count = {}
        timeline_data = {}
        
        for task in tasks:
            # Distribución por tipo de servicio
            service_type = task.service_type or 'Sin especificar'
            service_distribution[service_type] = service_distribution.get(service_type, 0) + 1
            
            # Contar servicios por cliente
            client = task.client_name or 'Sin nombre'
            clients_count[client] = clients_count.get(client, 0) + 1
            
            # Timeline por fecha
            date_key = task.date.strftime('%Y-%m-%d')
            if date_key not in timeline_data:
                timeline_data[date_key] = {
                    'date': task.date.strftime('%d/%m'),
                    'services': 0,
                    'revenue': 0,
                    'maintenances': 0
                }
            timeline_data[date_key]['services'] += 1
            
            # Calcular tiempo
            if task.actual_start_time and task.actual_end_time:
                duration = (task.actual_end_time - task.actual_start_time).total_seconds() / 3600
                total_time += duration
        
        # Top 5 clientes
        top_clients = sorted(clients_count.items(), key=lambda x: x[1], reverse=True)[:5]
        
        # Convertir timeline a lista ordenada
        timeline_list = sorted(timeline_data.values(), key=lambda x: x['date'])
        
        return jsonify({
            'success': True,
            'total_services': total_services,
            'total_maintenances': service_distribution.get('Mantenimiento', 0),
            'total_revenue': total_services * 50,  # Estimación simple
            'avg_time': round(total_time / total_services, 2) if total_services > 0 else 0,
            'service_distribution': service_distribution,
            'timeline': timeline_list,
            'top_clients': [{'name': name, 'count': count} for name, count in top_clients]
        })
        
    except Exception as e:
        print(f"Error en admin_analytics: {e}")
        return jsonify({'success': False, 'msg': str(e)}), 500

@app.route('/api/admin_reports_list')
@login_required
def get_admin_reports_list():
    """
    NUEVO: Endpoint para obtener lista de partes filtrados por técnico(s)
    Mejora #5: Vista de lista de partes en estadísticas
    """
    if current_user.role != 'admin':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    try:
        # Obtener parámetros
        tech_ids = request.args.get('tech_ids', '')
        period = request.args.get('period', '30')
        
        # Construir query
        query = Task.query.filter_by(status='Completado')
        
        # Filtrar por técnicos si se especifica
        if tech_ids and tech_ids != 'all':
            tech_ids_list = [int(tid.strip()) for tid in tech_ids.split(',') if tid.strip()]
            if tech_ids_list:
                query = query.filter(Task.tech_id.in_(tech_ids_list))
        
        # Filtrar por período
        if period != 'all':
            days = int(period)
            from datetime import timedelta
            cutoff_date = date.today() - timedelta(days=days)
            query = query.filter(Task.date >= cutoff_date)
        
        # Ordenar por fecha descendente
        tasks = query.order_by(Task.date.desc()).all()
        
        # Formatear resultados
        reports_list = []
        for task in tasks:
            reports_list.append({
                'id': task.id,
                'date': task.date.strftime('%d/%m/%Y'),
                'client_name': task.client_name,
                'service_type': task.service_type,
                'tech_name': task.tech.username if task.tech else 'Sin asignar',
                'start_time': task.start_time or '--',
                'end_time': task.end_time or '--',
                'description': task.description[:100] + '...' if task.description and len(task.description) > 100 else task.description or 'Sin descripción',
                'has_attachments': bool(task.attachments),
                'has_signature': bool(task.signature_data)
            })
        
        return jsonify({
            'success': True,
            'total': len(reports_list),
            'reports': reports_list
        })
        
    except Exception as e:
        print(f"Error en admin_reports_list: {e}")
        return jsonify({'success': False, 'msg': str(e)}), 500

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

@app.route('/print_report/<int:task_id>')
@login_required
def print_report(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return "No autorizado", 403
    
    # Generar HTML de archivos adjuntos
    attachments_html = ""
    if task.attachments:
        try:
            files = json.loads(task.attachments)
            if files:
                attachments_html = "<div class='mt-2'><strong>Archivos adjuntos:</strong><br>"
                for f in files:
                    attachments_html += f"• {f}<br>"
                attachments_html += "</div>"
        except:
            pass
        
    html = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <title>Parte #{task.id}</title>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
        <style>
            body {{ font-family: Arial, sans-serif; padding: 40px; max-width: 800px; margin: auto; }}
            .header {{ border-bottom: 3px solid #f37021; padding-bottom: 20px; margin-bottom: 30px; }}
            .logo {{ font-size: 24px; font-weight: bold; }}
            .label {{ font-weight: bold; color: #666; font-size: 0.9em; }}
            .value {{ font-size: 1.1em; margin-bottom: 15px; }}
            .box {{ background: #f9f9f9; padding: 15px; border-radius: 5px; border: 1px solid #ddd; }}
            .signature {{ max-width: 300px; border: 1px solid #ddd; padding: 10px; }}
            @media print {{
                .no-print {{ display: none; }}
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <div class="logo">OSLA<span style="color:#f37021">PRINT</span></div>
            <div class="text-muted">Parte de Trabajo #{task.id}</div>
        </div>
        
        <div class="row mb-3">
            <div class="col-6">
                <div class="label">CLIENTE</div>
                <div class="value">{task.client_name}</div>
            </div>
            <div class="col-6">
                <div class="label">FECHA</div>
                <div class="value">{task.date.strftime('%d/%m/%Y')}</div>
            </div>
        </div>
        
        <div class="row mb-3">
            <div class="col-6">
                <div class="label">TÉCNICO</div>
                <div class="value">{task.tech.username if task.tech else 'Sin asignar'}</div>
            </div>
            <div class="col-6">
                <div class="label">TIPO DE SERVICIO</div>
                <div class="value">{task.service_type}</div>
            </div>
        </div>
        
        <div class="row mb-3">
            <div class="col-6">
                <div class="label">HORA ENTRADA</div>
                <div class="value">{task.start_time or '--'}</div>
            </div>
            <div class="col-6">
                <div class="label">HORA SALIDA</div>
                <div class="value">{task.end_time or '--'}</div>
            </div>
        </div>
        
        <div class="mb-3">
            <div class="label">DESCRIPCIÓN DEL TRABAJO</div>
            <div class="box">{task.description or 'Sin descripción'}</div>
        </div>
        
        {'<div class="mb-3"><div class="label">PIEZAS UTILIZADAS</div><div class="box">' + task.parts_text + '</div></div>' if task.parts_text else ''}
        
        {attachments_html}
        
        {'<div class="mt-4"><div class="label">FIRMA DEL CLIENTE</div><img src="' + task.signature_data + '" class="signature"></div>' if task.signature_data else ''}
        
        <div class="no-print mt-4">
            <button class="btn btn-primary" onclick="window.print()">Imprimir</button>
            <button class="btn btn-secondary" onclick="window.close()">Cerrar</button>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- BLOQUE DE INICIALIZACIÓN UNIFICADO ---
with app.app_context():
    # Primero creamos las tablas (la estructura)
    db.create_all()
    
    # Después llenamos los datos (el contenido)
    # 1. Usuarios - CORREGIDO: crear tanto admin como paco
    if not User.query.filter_by(username='admin').first():
        db.session.add(User(username='admin', role='admin', password_hash=generate_password_hash('admin123')))
    
    if not User.query.filter_by(username='paco').first():
        db.session.add(User(username='paco', role='admin', password_hash=generate_password_hash('admin123')))
        
    if not User.query.filter_by(username='tech').first():
        db.session.add(User(username='tech', role='tech', password_hash=generate_password_hash('tech123')))
    
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

    # 3. Datos de ejemplo
    if Stock.query.count() == 0:
        # Añadir productos de ejemplo con categorías y subcategorías
        stock_items = [
            {'name': 'Toner Genérico', 'category': 'Consumibles', 'subcategory': '', 'quantity': 10, 'min_stock': 5, 'supplier': ''},
            {'name': 'Copiadora HP LaserJet', 'category': 'Copiadoras', 'subcategory': '', 'quantity': 3, 'min_stock': 1, 'supplier': ''},
            {'name': 'Cajón Cashlogy 1500', 'category': 'Cajones', 'subcategory': 'Cashlogy', 'quantity': 5, 'min_stock': 2, 'supplier': ''},
            {'name': 'Cajón Cashkeeper Pro', 'category': 'Cajones', 'subcategory': 'Cashkeeper', 'quantity': 4, 'min_stock': 2, 'supplier': ''},
            {'name': 'Cajón ATCA Standard', 'category': 'Cajones', 'subcategory': 'ATCA', 'quantity': 3, 'min_stock': 1, 'supplier': ''},
            {'name': 'TPV Táctil 15"', 'category': 'TPV', 'subcategory': '', 'quantity': 6, 'min_stock': 2, 'supplier': ''},
            {'name': 'Reciclador 1', 'category': 'Recicladores', 'subcategory': '', 'quantity': 2, 'min_stock': 1, 'supplier': ''}
        ]
        for item in stock_items:
            db.session.add(Stock(**item))
        
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