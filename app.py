import os
import json
from datetime import datetime, date, timedelta
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
    supplier = db.Column(db.String(100))  # Proveedor del producto
    photo_filename = db.Column(db.String(200))  # Ruta a la foto del producto

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
    
    # Hora de inicio/fin real del trabajo (para tracking automático con cronómetro)
    actual_start_time = db.Column(db.DateTime)
    actual_end_time = db.Column(db.DateTime)
    
    # Tiempo total trabajado en segundos (para cronómetro)
    work_duration_seconds = db.Column(db.Integer, default=0)

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
            flash('El usuario ya existe.', 'danger')
        else:
            new_user = User(username=username, role=role, password_hash=generate_password_hash(password))
            db.session.add(new_user)
            db.session.commit()
            flash('Usuario creado.', 'success')
    
    elif action == 'delete':
        user_id = request.form['user_id']
        user = User.query.get(user_id)
        if user:
            # Eliminar todas las tareas asociadas
            Task.query.filter_by(tech_id=user.id).delete()
            db.session.delete(user)
            db.session.commit()
            flash('Usuario eliminado.', 'success')
    
    return redirect(url_for('dashboard'))

@app.route('/change_password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form['current_password']
    new_password = request.form['new_password']
    
    if check_password_hash(current_user.password_hash, current_password):
        current_user.password_hash = generate_password_hash(new_password)
        db.session.commit()
        flash('Contraseña actualizada.', 'success')
    else:
        flash('Contraseña actual incorrecta.', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/manage_stock', methods=['POST'])
@login_required
def manage_stock():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form['name']
        category = request.form['category']
        quantity = int(request.form.get('quantity', 0))
        min_stock = int(request.form.get('min_stock', 5))
        supplier = request.form.get('supplier', '')
        subcategory = request.form.get('subcategory', '')
        
        new_item = Stock(
            name=name, 
            category=category, 
            subcategory=subcategory,
            quantity=quantity,
            min_stock=min_stock,
            supplier=supplier
        )
        db.session.add(new_item)
        db.session.commit()
        
        # Verificar stock bajo después de añadir
        check_low_stock()
        
        flash('Artículo añadido.', 'success')
    
    elif action == 'edit':
        item_id = request.form['item_id']
        item = Stock.query.get(item_id)
        if item:
            item.name = request.form['name']
            item.category = request.form['category']
            item.subcategory = request.form.get('subcategory', '')
            item.quantity = int(request.form.get('quantity', item.quantity))
            item.min_stock = int(request.form.get('min_stock', item.min_stock))
            item.supplier = request.form.get('supplier', item.supplier)
            db.session.commit()
            
            # Verificar stock bajo después de editar
            check_low_stock()
            
            flash('Artículo actualizado.', 'success')
    
    elif action == 'adjust':
        item_id = request.form['item_id']
        adjust_qty = int(request.form['adjust_qty'])
        item = Stock.query.get(item_id)
        if item:
            item.quantity += adjust_qty
            db.session.commit()
            
            # Verificar stock bajo después de ajustar
            check_low_stock()
            
            flash('Cantidad ajustada.', 'success')
    
    elif action == 'delete':
        item_id = request.form['item_id']
        item = Stock.query.get(item_id)
        if item:
            db.session.delete(item)
            db.session.commit()
            flash('Artículo eliminado.', 'success')
    
    return redirect(url_for('dashboard'))

@app.route('/manage_clients', methods=['POST'])
@login_required
def manage_clients():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form['name']
        phone = request.form.get('phone', '')
        email = request.form.get('email', '')
        address = request.form.get('address', '')
        notes = request.form.get('notes', '')
        has_support = request.form.get('has_support') == 'on'
        support_monday_friday = request.form.get('support_monday_friday') == 'on'
        support_saturday = request.form.get('support_saturday') == 'on'
        support_sunday = request.form.get('support_sunday') == 'on'
        
        if Client.query.filter_by(name=name).first():
            flash('El cliente ya existe.', 'danger')
        else:
            new_client = Client(
                name=name, 
                phone=phone, 
                email=email, 
                address=address, 
                notes=notes,
                has_support=has_support,
                support_monday_friday=support_monday_friday,
                support_saturday=support_saturday,
                support_sunday=support_sunday
            )
            db.session.add(new_client)
            db.session.commit()
            flash('Cliente añadido.', 'success')
    
    elif action == 'edit':
        client_id = request.form['client_id']
        client = Client.query.get(client_id)
        if client:
            client.name = request.form['name']
            client.phone = request.form.get('phone', client.phone)
            client.email = request.form.get('email', client.email)
            client.address = request.form.get('address', client.address)
            client.notes = request.form.get('notes', client.notes)
            client.has_support = request.form.get('has_support') == 'on'
            client.support_monday_friday = request.form.get('support_monday_friday') == 'on'
            client.support_saturday = request.form.get('support_saturday') == 'on'
            client.support_sunday = request.form.get('support_sunday') == 'on'
            db.session.commit()
            flash('Cliente actualizado.', 'success')
    
    elif action == 'delete':
        client_id = request.form['client_id']
        client = Client.query.get(client_id)
        if client:
            db.session.delete(client)
            db.session.commit()
            flash('Cliente eliminado.', 'success')
    
    return redirect(url_for('dashboard'))

@app.route('/import_clients', methods=['POST'])
@login_required
def import_clients():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    if 'file' not in request.files:
        flash('No se ha enviado ningún archivo.', 'danger')
        return redirect(url_for('dashboard'))
    
    file = request.files['file']
    if file.filename == '':
        flash('Archivo vacío.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        data = json.load(file)
        imported = 0
        for item in data:
            name = item.get('name')
            if name and not Client.query.filter_by(name=name).first():
                new_client = Client(
                    name=name,
                    phone=item.get('phone', ''),
                    email=item.get('email', ''),
                    address=item.get('address', ''),
                    notes=item.get('notes', ''),
                    has_support=item.get('has_support', False),
                    support_monday_friday=item.get('support_monday_friday', False),
                    support_saturday=item.get('support_saturday', False),
                    support_sunday=item.get('support_sunday', False)
                )
                db.session.add(new_client)
                imported += 1
        db.session.commit()
        flash(f'Se importaron {imported} clientes.', 'success')
    except Exception as e:
        flash(f'Error al importar: {str(e)}', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/manage_services', methods=['POST'])
@login_required
def manage_services():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        name = request.form['name']
        color = request.form.get('color', '#6c757d')
        
        if ServiceType.query.filter_by(name=name).first():
            flash('El tipo de servicio ya existe.', 'danger')
        else:
            new_service = ServiceType(name=name, color=color)
            db.session.add(new_service)
            db.session.commit()
            flash('Tipo de servicio añadido.', 'success')
    
    elif action == 'edit':
        service_id = request.form['service_id']
        service = ServiceType.query.get(service_id)
        if service:
            service.name = request.form['name']
            service.color = request.form.get('color', service.color)
            db.session.commit()
            flash('Tipo de servicio actualizado.', 'success')
    
    elif action == 'delete':
        service_id = request.form['service_id']
        service = ServiceType.query.get(service_id)
        if service:
            db.session.delete(service)
            db.session.commit()
            flash('Tipo de servicio eliminado.', 'success')
    
    return redirect(url_for('dashboard'))

@app.route('/schedule_appointment', methods=['POST'])
@login_required
def schedule_appointment():
    """Agendar nueva cita - CORREGIDO"""
    try:
        tech_id = request.form.get('tech_id')
        client_name = request.form.get('client_name')
        date_str = request.form.get('date')
        time_str = request.form.get('time')
        service_type = request.form.get('service_type', 'Sin especificar')
        notes = request.form.get('notes', '')
        
        # Validación de campos requeridos
        if not all([tech_id, client_name, date_str, time_str]):
            flash('Todos los campos son obligatorios.', 'danger')
            return redirect(url_for('dashboard'))
        
        # Parsear fecha
        task_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Crear nueva tarea
        new_task = Task(
            tech_id=int(tech_id),
            client_name=client_name,
            date=task_date,
            start_time=time_str,
            end_time='',
            service_type=service_type,
            description=notes,
            status='Pendiente'
        )
        
        db.session.add(new_task)
        db.session.commit()
        
        flash('Cita agendada correctamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al agendar cita: {str(e)}', 'danger')
        print(f"Error en schedule_appointment: {e}")
    
    return redirect(url_for('dashboard'))

@app.route('/submit_part', methods=['POST'])
@login_required
def submit_part():
    """Enviar parte de trabajo - MEJORADO con soporte para fotos de stock"""
    try:
        client_name = request.form['client_name']
        service_type = request.form['service_type']
        description = request.form.get('description', '')
        date_str = request.form['date']
        start_time = request.form['start_time']
        end_time = request.form['end_time']
        parts_text = request.form.get('parts_text', '')
        
        # Duración del cronómetro si existe
        work_duration = int(request.form.get('work_duration_seconds', 0))
        
        task_date = datetime.strptime(date_str, '%Y-%m-%d').date()
        
        # Crear nueva tarea
        new_task = Task(
            tech_id=current_user.id,
            client_name=client_name,
            service_type=service_type,
            description=description,
            date=task_date,
            start_time=start_time,
            end_time=end_time,
            parts_text=parts_text,
            status='Completado',
            work_duration_seconds=work_duration
        )
        
        # Manejar stock si se añadió
        stock_item_id = request.form.get('stock_item_id')
        stock_quantity = request.form.get('stock_quantity_used', 0)
        stock_action = request.form.get('stock_action', 'used')
        
        if stock_item_id and int(stock_item_id) > 0:
            new_task.stock_item_id = int(stock_item_id)
            new_task.stock_quantity_used = int(stock_quantity)
            new_task.stock_action = stock_action
            
            # Actualizar inventario
            stock_item = Stock.query.get(int(stock_item_id))
            if stock_item:
                stock_item.quantity -= int(stock_quantity)
                
                # Verificar stock bajo
                check_low_stock()
        
        # Manejar archivos adjuntos
        uploaded_files = []
        if 'attachments' in request.files:
            files = request.files.getlist('attachments')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Añadir timestamp para evitar conflictos
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    filename = f"{timestamp}_{filename}"
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    uploaded_files.append(filename)
        
        if uploaded_files:
            new_task.attachments = json.dumps(uploaded_files)
        
        # Manejar firma digital
        signature = request.form.get('signature_data')
        if signature:
            new_task.signature_data = signature
        
        db.session.add(new_task)
        db.session.commit()
        
        flash('Parte guardado correctamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al guardar el parte: {str(e)}', 'danger')
        print(f"Error en submit_part: {e}")
    
    return redirect(url_for('dashboard'))

@app.route('/edit_appointment/<int:task_id>', methods=['POST'])
@login_required
def edit_appointment(task_id):
    """Editar cita existente"""
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        flash('No tienes permisos para editar esta cita.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        client_name = request.form.get('client_name')
        date_str = request.form.get('date')
        time_str = request.form.get('time')
        service_type = request.form.get('service_type')
        notes = request.form.get('notes', '')
        
        if client_name:
            task.client_name = client_name
        if date_str:
            task.date = datetime.strptime(date_str, '%Y-%m-%d').date()
        if time_str:
            task.start_time = time_str
        if service_type:
            task.service_type = service_type
        if notes:
            task.description = notes
        
        db.session.commit()
        flash('Cita actualizada correctamente.', 'success')
        
    except Exception as e:
        db.session.rollback()
        flash(f'Error al actualizar cita: {str(e)}', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    """Servir archivos subidos"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/print_report/<int:task_id>')
@login_required
def print_report(task_id):
    """Generar informe imprimible - MEJORADO"""
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        flash('No tienes permisos.', 'danger')
        return redirect(url_for('dashboard'))
    
    # Obtener información del cliente si existe
    client = Client.query.filter_by(name=task.client_name).first()
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <title>Informe - {task.client_name}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; }}
            .header {{ text-align: center; margin-bottom: 30px; border-bottom: 3px solid #f37021; padding-bottom: 20px; }}
            .header h1 {{ color: #f37021; margin: 0; }}
            .section {{ margin: 20px 0; }}
            .section h3 {{ background: #f37021; color: white; padding: 10px; margin: 0; }}
            .section .content {{ padding: 15px; border: 1px solid #ddd; }}
            .info-row {{ margin: 10px 0; display: flex; }}
            .info-label {{ font-weight: bold; min-width: 150px; }}
            .signature-box {{ border: 2px solid #000; min-height: 100px; margin-top: 20px; padding: 10px; }}
            .footer {{ margin-top: 40px; text-align: center; font-size: 0.9em; color: #666; }}
            @media print {{
                body {{ margin: 20px; }}
                .no-print {{ display: none; }}
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>OSLAPRINT</h1>
            <p>Informe de Servicio</p>
        </div>
        
        <div class="section">
            <h3>Información del Cliente</h3>
            <div class="content">
                <div class="info-row">
                    <span class="info-label">Cliente:</span>
                    <span>{task.client_name}</span>
                </div>
                {f'<div class="info-row"><span class="info-label">Teléfono:</span><span>{client.phone}</span></div>' if client and client.phone else ''}
                {f'<div class="info-row"><span class="info-label">Email:</span><span>{client.email}</span></div>' if client and client.email else ''}
                {f'<div class="info-row"><span class="info-label">Dirección:</span><span>{client.address}</span></div>' if client and client.address else ''}
                {f'<div class="info-row"><span class="info-label">Soporte:</span><span>{"✓ Activo" if client and client.has_support else "✗ No activo"}</span></div>' if client else ''}
            </div>
        </div>
        
        <div class="section">
            <h3>Detalles del Servicio</h3>
            <div class="content">
                <div class="info-row">
                    <span class="info-label">Fecha:</span>
                    <span>{task.date.strftime('%d/%m/%Y')}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Horario:</span>
                    <span>{task.start_time or 'N/A'} - {task.end_time or 'N/A'}</span>
                </div>
                {f'<div class="info-row"><span class="info-label">Duración:</span><span>{task.work_duration_seconds // 3600}h {(task.work_duration_seconds % 3600) // 60}m</span></div>' if task.work_duration_seconds else ''}
                <div class="info-row">
                    <span class="info-label">Tipo de Servicio:</span>
                    <span>{task.service_type}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Técnico:</span>
                    <span>{task.tech.username if task.tech else 'N/A'}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Estado:</span>
                    <span>{task.status}</span>
                </div>
            </div>
        </div>
        
        <div class="section">
            <h3>Descripción del Trabajo</h3>
            <div class="content">
                <p>{task.description or 'Sin descripción'}</p>
            </div>
        </div>
        
        {f'''
        <div class="section">
            <h3>Material Utilizado</h3>
            <div class="content">
                <div class="info-row">
                    <span class="info-label">Artículo:</span>
                    <span>{task.stock_item.name}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Cantidad:</span>
                    <span>{task.stock_quantity_used} unidades</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Acción:</span>
                    <span>{"Usado" if task.stock_action == "used" else "Retirado"}</span>
                </div>
            </div>
        </div>
        ''' if task.stock_item else ''}
        
        {f'''
        <div class="section">
            <h3>Notas Adicionales</h3>
            <div class="content">
                <p>{task.parts_text}</p>
            </div>
        </div>
        ''' if task.parts_text else ''}
        
        <div class="section">
            <h3>Firma del Cliente</h3>
            <div class="content">
                {f'<img src="data:image/png;base64,{task.signature_data.split(",")[1] if "," in task.signature_data else task.signature_data}" style="max-width: 300px; border: 1px solid #ddd;" />' if task.signature_data else '<div class="signature-box"><p style="color: #999; text-align: center; margin-top: 40px;">Sin firma digital</p></div>'}
            </div>
        </div>
        
        <div class="footer">
            <p>OSLAPRINT - Informe generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}</p>
        </div>
        
        <div class="no-print" style="text-align: center; margin-top: 30px;">
            <button onclick="window.print()" style="background: #f37021; color: white; border: none; padding: 15px 30px; font-size: 1.1em; cursor: pointer; border-radius: 5px;">
                Imprimir Informe
            </button>
            <button onclick="window.close()" style="background: #666; color: white; border: none; padding: 15px 30px; font-size: 1.1em; cursor: pointer; border-radius: 5px; margin-left: 10px;">
                Cerrar
            </button>
        </div>
    </body>
    </html>
    """
    
    return html_content

# --- API ENDPOINTS ---
@app.route('/api/clients_search')
@login_required
def clients_search():
    """Búsqueda de clientes con autocompletado"""
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
    
    clients = Client.query.filter(Client.name.ilike(f'%{query}%')).limit(10).all()
    return jsonify([{
        'id': c.id,
        'name': c.name,
        'phone': c.phone,
        'email': c.email,
        'address': c.address,
        'has_support': c.has_support
    } for c in clients])

@app.route('/api/calendar_events')
@login_required
def calendar_events():
    """Obtener eventos del calendario - MEJORADO con información de cliente"""
    tech_id = request.args.get('tech_id', None)
    
    query = Task.query
    
    if tech_id:
        query = query.filter_by(tech_id=int(tech_id))
    elif current_user.role == 'tech':
        query = query.filter_by(tech_id=current_user.id)
    
    tasks = query.all()
    
    events = []
    for task in tasks:
        # Obtener información del cliente
        client = Client.query.filter_by(name=task.client_name).first()
        
        # Obtener color del tipo de servicio
        service = ServiceType.query.filter_by(name=task.service_type).first()
        color = service.color if service else '#6c757d'
        
        # Determinar color de borde según soporte del cliente
        border_color = '#28a745' if (client and client.has_support) else '#dc3545'
        
        event = {
            'id': task.id,
            'title': f"{task.client_name} - {task.service_type}",
            'start': task.date.isoformat(),
            'backgroundColor': color,
            'borderColor': border_color,
            'extendedProps': {
                'client': task.client_name,
                'service_type': task.service_type,
                'desc': task.description,
                'status': task.status,
                'tech_name': task.tech.username if task.tech else 'SIN TÉCNICO',
                'has_attachments': bool(task.attachments),
                'has_support': client.has_support if client else False,
                'client_phone': client.phone if client else '',
                'client_email': client.email if client else '',
                'client_address': client.address if client else '',
                'client_notes': client.notes if client else ''
            }
        }
        
        if task.start_time:
            event['start'] = f"{task.date.isoformat()}T{task.start_time}"
        if task.end_time:
            event['end'] = f"{task.date.isoformat()}T{task.end_time}"
        
        events.append(event)
    
    return jsonify(events)

@app.route('/api/task_action/<int:task_id>/<action>', methods=['POST'])
@login_required
def task_action(task_id, action):
    """Realizar acción sobre una tarea"""
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    try:
        if action == 'complete':
            task.status = 'Completado'
        elif action == 'reopen':
            task.status = 'Pendiente'
        elif action == 'delete':
            db.session.delete(task)
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'msg': str(e)}), 500

@app.route('/api/get_task/<int:task_id>')
@login_required
def get_task(task_id):
    """Obtener datos de una tarea para edición"""
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
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

@app.route('/api/task_details/<int:task_id>')
@login_required
def get_task_details(task_id):
    """Obtener detalles completos de una tarea - MEJORADO con info de cliente"""
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    # Obtener información del cliente
    client = Client.query.filter_by(name=task.client_name).first()
    
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
            'client_info': {
                'phone': client.phone if client else '',
                'email': client.email if client else '',
                'address': client.address if client else '',
                'notes': client.notes if client else '',
                'has_support': client.has_support if client else False,
                'support_monday_friday': client.support_monday_friday if client else False,
                'support_saturday': client.support_saturday if client else False,
                'support_sunday': client.support_sunday if client else False
            } if client else None,
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
            'work_duration_seconds': task.work_duration_seconds,
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
    """Análisis individual de trabajador - MEJORADO con más métricas"""
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
            'has_attachments': bool(task.attachments),
            'duration_seconds': task.work_duration_seconds
        })
        
        # Calcular tiempo total
        if task.work_duration_seconds:
            total_time += task.work_duration_seconds
    
    return jsonify({
        'success': True,
        'data': {
            'tech_name': tech.username,
            'total_completed': len(tasks),
            'total_hours': round(total_time / 3600, 2) if total_time else 0,
            'service_breakdown': service_stats
        }
    })

@app.route('/api/analytics_data')
@login_required
def get_analytics_data():
    """Obtener datos de analíticas para técnico o admin - MEJORADO"""
    tech_id = request.args.get('tech_id', None)
    period = request.args.get('period', '30')
    
    # Determinar el técnico a analizar
    if current_user.role == 'admin' and tech_id:
        target_tech_id = int(tech_id)
    elif current_user.role == 'tech':
        target_tech_id = current_user.id
    else:
        return jsonify({'success': False, 'msg': 'Parámetros inválidos'}), 400
    
    # Calcular fecha de inicio según período
    if period == 'all':
        start_date = date(2000, 1, 1)
    else:
        days = int(period)
        start_date = date.today() - timedelta(days=days)
    
    # Obtener tareas completadas
    tasks = Task.query.filter(
        Task.tech_id == target_tech_id,
        Task.status == 'Completado',
        Task.date >= start_date
    ).all()
    
    # Calcular estadísticas
    service_distribution = {}
    client_frequency = {}
    timeline_data = {}
    total_duration = 0
    
    for task in tasks:
        # Distribución por servicio
        service_type = task.service_type
        service_distribution[service_type] = service_distribution.get(service_type, 0) + 1
        
        # Frecuencia por cliente
        client_frequency[task.client_name] = client_frequency.get(task.client_name, 0) + 1
        
        # Datos temporales (por mes)
        month_key = task.date.strftime('%Y-%m')
        if month_key not in timeline_data:
            timeline_data[month_key] = {'services': 0, 'revenue': 0, 'maintenances': 0}
        
        timeline_data[month_key]['services'] += 1
        
        # Estimación de ingresos (ejemplo: 50€ por servicio)
        timeline_data[month_key]['revenue'] += 50
        
        # Contar mantenimientos
        if 'Mantenimiento' in service_type or 'Revisión' in service_type:
            timeline_data[month_key]['maintenances'] += 1
        
        # Duración total
        if task.work_duration_seconds:
            total_duration += task.work_duration_seconds
    
    # Top 5 clientes
    top_clients = sorted(client_frequency.items(), key=lambda x: x[1], reverse=True)[:5]
    
    # Top servicios
    top_services = sorted(service_distribution.items(), key=lambda x: x[1], reverse=True)
    
    # Calcular tiempo promedio
    avg_time = (total_duration / len(tasks)) if tasks else 0
    
    return jsonify({
        'success': True,
        'data': {
            'total_services': len(tasks),
            'total_maintenances': sum(1 for t in tasks if 'Mantenimiento' in t.service_type or 'Revisión' in t.service_type),
            'total_revenue': len(tasks) * 50,  # Estimación
            'avg_time_hours': round(avg_time / 3600, 2) if avg_time else 0,
            'service_distribution': service_distribution,
            'top_clients': [{'name': name, 'count': count} for name, count in top_clients],
            'top_services': [{'name': name, 'count': count} for name, count in top_services],
            'timeline': timeline_data
        }
    })

@app.route('/api/parts_list')
@login_required
def get_parts_list():
    """Obtener lista de partes completados - NUEVA FUNCIONALIDAD"""
    if current_user.role != 'admin':
        return jsonify({'success': False, 'msg': 'No autorizado'}), 403
    
    tech_id = request.args.get('tech_id', None)
    period = request.args.get('period', '30')
    
    # Calcular fecha de inicio
    if period == 'all':
        start_date = date(2000, 1, 1)
    else:
        days = int(period)
        start_date = date.today() - timedelta(days=days)
    
    # Query base
    query = Task.query.filter(
        Task.status == 'Completado',
        Task.date >= start_date
    )
    
    # Filtrar por técnico si se especifica
    if tech_id:
        query = query.filter_by(tech_id=int(tech_id))
    
    tasks = query.order_by(Task.date.desc()).all()
    
    parts_list = []
    for task in tasks:
        parts_list.append({
            'id': task.id,
            'date': task.date.strftime('%d/%m/%Y'),
            'client': task.client_name,
            'service_type': task.service_type,
            'tech_name': task.tech.username if task.tech else 'N/A',
            'duration_hours': round(task.work_duration_seconds / 3600, 2) if task.work_duration_seconds else 0,
            'has_attachments': bool(task.attachments),
            'has_stock': bool(task.stock_item_id)
        })
    
    return jsonify({
        'success': True,
        'data': parts_list
    })

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

# --- CRONÓMETRO API ---
@app.route('/api/timer/start', methods=['POST'])
@login_required
def timer_start():
    """Iniciar cronómetro de trabajo"""
    # Esta funcionalidad se maneja en el cliente, pero podríamos guardar el inicio aquí
    return jsonify({'success': True, 'timestamp': datetime.now().isoformat()})

@app.route('/api/timer/stop', methods=['POST'])
@login_required
def timer_stop():
    """Detener cronómetro y devolver duración"""
    data = request.get_json()
    duration_seconds = data.get('duration_seconds', 0)
    return jsonify({'success': True, 'duration': duration_seconds})

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

    # 3. Datos de ejemplo - AÑADIDO PRODUCTO "Dogo"
    if Stock.query.count() == 0:
        # Añadir productos de ejemplo con categorías y subcategorías
        stock_items = [
            {'name': 'Toner Genérico', 'category': 'Consumibles', 'subcategory': '', 'quantity': 10, 'min_stock': 5, 'supplier': 'Proveedor A'},
            {'name': 'Copiadora HP LaserJet', 'category': 'Copiadoras', 'subcategory': '', 'quantity': 3, 'min_stock': 1, 'supplier': 'HP'},
            {'name': 'Cajón Cashlogy 1500', 'category': 'Cajones', 'subcategory': 'Cashlogy', 'quantity': 5, 'min_stock': 2, 'supplier': 'Glory'},
            {'name': 'Cajón Cashkeeper Pro', 'category': 'Cajones', 'subcategory': 'Cashkeeper', 'quantity': 4, 'min_stock': 2, 'supplier': 'Cashkeeper'},
            {'name': 'Cajón ATCA Standard', 'category': 'Cajones', 'subcategory': 'ATCA', 'quantity': 3, 'min_stock': 1, 'supplier': 'ATCA'},
            {'name': 'TPV Táctil 15"', 'category': 'TPV', 'subcategory': '', 'quantity': 6, 'min_stock': 2, 'supplier': 'Proveedor B'},
            {'name': 'Reciclador 1', 'category': 'Recicladores', 'subcategory': '', 'quantity': 2, 'min_stock': 1, 'supplier': 'Glory'},
            {'name': 'Dogo', 'category': 'Accesorios', 'subcategory': '', 'quantity': 8, 'min_stock': 3, 'supplier': 'Proveedor C'}
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
    
    # Verificar stock bajo en el arranque
    check_low_stock()

# --- ARRANQUE ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)