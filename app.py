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
    
    if action == 'add':
        name = request.form['name']
        category = request.form.get('category', '')
        subcategory = request.form.get('subcategory', '')
        quantity = int(request.form.get('quantity', 0))
        min_stock = int(request.form.get('min_stock', 5))
        
        new_item = Stock(
            name=name,
            category=category,
            subcategory=subcategory,
            quantity=quantity,
            min_stock=min_stock
        )
        db.session.add(new_item)
        db.session.commit()
        
        # Verificar stock bajo
        check_low_stock()
        
        flash('Producto añadido al inventario.', 'success')
        
    elif action == 'edit':
        item = Stock.query.get(request.form['item_id'])
        if item:
            item.name = request.form['name']
            item.category = request.form.get('category', '')
            item.subcategory = request.form.get('subcategory', '')
            item.quantity = int(request.form.get('quantity', 0))
            item.min_stock = int(request.form.get('min_stock', 5))
            db.session.commit()
            
            # Verificar stock bajo
            check_low_stock()
            
            flash('Producto actualizado.', 'success')
            
    elif action == 'delete':
        item = Stock.query.get(request.form['item_id'])
        if item:
            db.session.delete(item)
            db.session.commit()
            flash('Producto eliminado.', 'warning')
    
    return redirect(url_for('dashboard'))

@app.route('/schedule_appointment', methods=['POST'])
@login_required
def schedule_appointment():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    try:
        tech_id = int(request.form['tech_id'])
        client_name = request.form['client_name']
        task_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        time = request.form.get('time', '')
        service_type = request.form['service_type']
        notes = request.form.get('notes', '')
        
        new_task = Task(
            tech_id=tech_id,
            client_name=client_name,
            date=task_date,
            start_time=time,
            service_type=service_type,
            description=notes,
            status='Pendiente'
        )
        db.session.add(new_task)
        db.session.commit()
        
        flash('Cita programada correctamente.', 'success')
    except Exception as e:
        flash(f'Error al programar cita: {str(e)}', 'danger')
    
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
        task.client_name = request.form['client_name']
        task.date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        task.start_time = request.form.get('time', '')
        task.service_type = request.form['service_type']
        task.description = request.form.get('notes', '')
        
        db.session.commit()
        flash('Cita actualizada correctamente.', 'success')
    except Exception as e:
        flash(f'Error al actualizar cita: {str(e)}', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/delete_appointment/<int:task_id>', methods=['POST'])
@login_required
def delete_appointment(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Verificar permisos
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        flash('No tienes permisos para eliminar esta cita.', 'danger')
        return redirect(url_for('dashboard'))
    
    db.session.delete(task)
    db.session.commit()
    flash('Cita eliminada.', 'warning')
    
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
    client = Client.query.get_or_404(client_id)
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
            'support_sunday': client.support_sunday
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
        </style>
    </head>
    <body onload="window.print()">
        <div class="header d-flex justify-content-between align-items-center">
            <div class="logo">OSLA<span style="color:#f37021">PRINT</span></div>
            <div class="text-end">
                <h4>PARTE DE TRABAJO</h4>
                <small>Ref: #{task.id} | Fecha: {task.date.strftime('%d/%m/%Y')}</small>
            </div>
        </div>
        
        <div class="row">
            <div class="col-6">
                <div class="label">CLIENTE</div>
                <div class="value">{task.client_name}</div>
            </div>
            <div class="col-6">
                <div class="label">TÉCNICO</div>
                <div class="value">{task.tech.username.upper() if task.tech else 'SIN TÉCNICO'}</div>
            </div>
        </div>
        
        <div class="row mt-3">
            <div class="col-4">
                <div class="label">SERVICIO</div>
                <div class="value">{task.service_type}</div>
            </div>
            <div class="col-4">
                <div class="label">HORA ENTRADA</div>
                <div class="value">{task.start_time}</div>
            </div>
            <div class="col-4">
                <div class="label">HORA SALIDA</div>
                <div class="value">{task.end_time}</div>
            </div>
        </div>
        
        <div class="mt-4">
            <div class="label">DESCRIPCIÓN DEL TRABAJO</div>
            <div class="box">{task.description}</div>
        </div>
        
        <div class="row mt-4">
            <div class="col-12">
                <div class="label">MATERIAL UTILIZADO/RETIRADO</div>
                <div class="box">
                    { f"Stock ({'USADO' if task.stock_action == 'used' else 'RETIRADO'}): {task.stock_quantity_used}x {task.stock_item.name}<br>" if task.stock_item else "" }
                    { f"Notas/Retirado: {task.parts_text}" if task.parts_text else "Sin notas adicionales" }
                    {attachments_html}
                </div>
            </div>
        </div>
        
        <div class="mt-4">
            <div class="label">FIRMA DEL CLIENTE</div>
            <div class="mt-2">
                {"<img src='" + task.signature_data + "' class='signature'>" if task.signature_data else "<div class='box'>Sin firma</div>"}
            </div>
        </div>
        
        <div class="mt-5 text-center text-muted small">
            <p>Documento generado electrónicamente por OSLAPRINT SYSTEM</p>
        </div>
    </body>
    </html>
    """
    return html

@app.route('/api/tasks')
@login_required
def my_tasks():
    tasks = Task.query.filter_by(tech_id=current_user.id).all()
    return format_events(tasks)

@app.route('/api/admin/tasks/<int:user_id>')
@login_required
def get_admin_tasks(user_id):
    tasks = Task.query.filter_by(tech_id=user_id).all()
    return format_events(tasks)

@app.route('/api/admin/all_tasks')
@login_required
def get_all_admin_tasks():
    if current_user.role != 'admin':
        return jsonify([])
    tasks = Task.query.all()
    return format_events(tasks)

def format_events(tasks):
    all_types = ServiceType.query.all()
    type_colors = {s.name: s.color for s in all_types}

    events = []
    for t in tasks:
        start = f"{t.date}T{t.start_time}" if t.start_time else str(t.date)
        
        # Procesar archivos adjuntos
        attachments_list = []
        if t.attachments:
            try:
                attachments_list = json.loads(t.attachments)
            except:
                pass

        events.append({
            'id': t.id,
            'title': f"{t.client_name} ({t.service_type})",
            'start': start,
            'color': type_colors.get(t.service_type, '#6c757d'),
            'allDay': False if t.start_time else True,
            'extendedProps': {
                'status': t.status,
                'client': t.client_name,
                'desc': t.description,
                'tech_name': t.tech.username.upper() if t.tech else 'SIN TÉCNICO',
                'service_type': t.service_type,
                'has_attachments': len(attachments_list) > 0
            }
        })
    return jsonify(events)

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

# --- BLOQUE DE INICIALIZACIÓN UNIFICADO ---
with app.app_context():
    # Primero creamos las tablas (la estructura)
    db.create_all()
    
    # Después llenamos los datos (el contenido)
    # 1. Usuarios
    if not User.query.filter_by(username='paco').first():
        db.session.add(User(username='paco', role='admin', password_hash=generate_password_hash('admin123')))
        db.session.add(User(username='tech', role='tech', password_hash=generate_password_hash('tech123')))
    
    # 2. Tipos de Servicio y Colores
    if not ServiceType.query.first():
        servicios = [
            {'name': 'Avería', 'color': '#fd7e14'},
            {'name': 'Revisión', 'color': '#0d6efd'},
            {'name': 'Instalación', 'color': '#6f42c1'},
            {'name': 'Otros servicios', 'color': '#20c997'}
        ]
        for s in servicios:
            db.session.add(ServiceType(name=s['name'], color=s['color']))

    # 3. Datos de ejemplo
    if not Stock.query.first():
        db.session.add(Stock(name='Toner Genérico', category='Consumibles', quantity=10, min_stock=5))
        
    if not Client.query.first():
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