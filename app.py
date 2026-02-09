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
    role = db.Column(db.String(20)) # 'admin' o 'tech'

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

class ServiceType(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    color = db.Column(db.String(7), default='#6c757d') # Hex code color

class Stock(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    quantity = db.Column(db.Integer, default=0)
    category = db.Column(db.String(50)) 

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

    status = db.Column(db.String(20), default='Completado')
    
    # Nuevos campos para archivos adjuntos
    attachments = db.Column(db.Text)  # JSON con lista de archivos adjuntos

    tech = db.relationship('User', backref='tasks')
    stock_item = db.relationship('Stock', backref='tasks')

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

# --- FUNCIONES AUXILIARES ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- CONTEXT PROCESSOR ---
@app.context_processor
def inject_globals():
    try:
        return {
            'all_service_types': ServiceType.query.order_by(ServiceType.name).all()
        }
    except Exception as e:
        print("ERROR context_processor:", e)
        return {
            'all_service_types': []
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
        inventory = Stock.query.order_by(Stock.name).all()
        clients = Client.query.order_by(Client.name).all()
        services = ServiceType.query.order_by(ServiceType.name).all() 
        return render_template('admin_panel.html', empleados=empleados, informes=informes, inventory=inventory, clients=clients, services=services)
    
    stock_items = Stock.query.all()
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
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    
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

@app.route('/save_report', methods=['POST'])
@login_required
def save_report():
    try:
        nueva_fecha = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        stock_id = request.form.get('stock_item')
        qty = int(request.form.get('stock_qty', 0))
        action = request.form.get('stock_action', 'used')
        
        # Procesar archivos adjuntos
        uploaded_files = []
        if 'attachments' in request.files:
            files = request.files.getlist('attachments')
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    # Añadir timestamp para evitar duplicados
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_')
                    filename = timestamp + filename
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(filepath)
                    uploaded_files.append(filename)
        
        # Verificar si estamos completando una tarea pendiente
        linked_task_id = request.form.get('linked_task_id')
        if linked_task_id and linked_task_id != 'none':
            # Actualizar tarea existente
            task = Task.query.get(int(linked_task_id))
            if task:
                task.description = request.form['description']
                task.start_time = request.form['entry_time']
                task.end_time = request.form['exit_time']
                task.parts_text = request.form.get('parts_text', '')
                task.stock_item_id = int(stock_id) if stock_id else None
                task.stock_quantity_used = qty
                task.stock_action = action
                task.status = 'Completado'
                
                # Añadir archivos adjuntos
                if uploaded_files:
                    existing_attachments = json.loads(task.attachments) if task.attachments else []
                    existing_attachments.extend(uploaded_files)
                    task.attachments = json.dumps(existing_attachments)
                
                if stock_id and qty > 0:
                    item = Stock.query.get(int(stock_id))
                    if item:
                        if action == 'used':
                            item.quantity -= qty
                        elif action == 'removed':
                            item.quantity -= qty
                
                db.session.commit()
                flash('Tarea completada y guardada correctamente.', 'success')
        else:
            # Crear nueva tarea
            nueva = Task(
                tech_id=current_user.id,
                client_name=request.form['client_name'],
                description=request.form['description'],
                date=nueva_fecha,
                start_time=request.form['entry_time'],
                end_time=request.form['exit_time'],
                service_type=request.form['service_type'],
                parts_text=request.form.get('parts_text', ''),
                stock_item_id=int(stock_id) if stock_id else None,
                stock_quantity_used=qty,
                stock_action=action,
                status='Completado',
                attachments=json.dumps(uploaded_files) if uploaded_files else None
            )
            
            if stock_id and qty > 0:
                item = Stock.query.get(int(stock_id))
                if item:
                    if action == 'used':
                        item.quantity -= qty
                    elif action == 'removed':
                        item.quantity -= qty
                        
            db.session.add(nueva)
            db.session.commit()
            flash('Informe guardado correctamente.', 'success')
            
    except Exception as e:
        flash(f'Error al guardar: {str(e)}', 'danger')
        
    return redirect(url_for('dashboard'))

@app.route('/schedule_appointment', methods=['POST'])
@login_required
def schedule_appointment():
    try:
        # Si es técnico, asignar a sí mismo
        if current_user.role == 'tech':
            tech_id = current_user.id
        else:
            # Si es admin, usar el tech_id del formulario
            tech_id = int(request.form['tech_id'])
            
        appt_date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        appt_time = request.form['time']
        
        nueva = Task(
            tech_id=tech_id,
            client_name=request.form['client_name'],
            description=request.form.get('notes', ''),
            date=appt_date,
            start_time=appt_time,
            service_type=request.form['service_type'],
            status='Pendiente'
        )
        
        db.session.add(nueva)
        db.session.commit()
        flash('Cita agendada correctamente.', 'success')
    except Exception as e:
        flash(f'Error al agendar: {str(e)}', 'danger')
        
    return redirect(url_for('dashboard'))

@app.route('/edit_appointment/<int:task_id>', methods=['POST'])
@login_required
def edit_appointment(task_id):
    task = Task.query.get_or_404(task_id)
    
    # Solo admin o el técnico asignado puede editar
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        flash('No tienes permisos para editar esta tarea.', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        task.client_name = request.form['client_name']
        task.date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        task.start_time = request.form['time']
        task.service_type = request.form['service_type']
        task.description = request.form.get('notes', '')
        
        db.session.commit()
        flash('Cita actualizada correctamente.', 'success')
    except Exception as e:
        flash(f'Error al actualizar: {str(e)}', 'danger')
        
    return redirect(url_for('dashboard'))

@app.route('/api/get_task/<int:task_id>')
@login_required
def get_task(task_id):
    task = Task.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'msg': 'Tarea no encontrada'})
    
    return jsonify({
        'success': True,
        'data': {
            'client_name': task.client_name,
            'date': task.date.strftime('%Y-%m-%d'),
            'time': task.start_time or '',
            'service_type': task.service_type,
            'notes': task.description or ''
        }
    })

@app.route('/api/get_task_full/<int:task_id>')
@login_required
def get_task_full(task_id):
    """Devuelve información completa de una tarea para sincronizar formularios"""
    task = Task.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'msg': 'Tarea no encontrada'})
    
    return jsonify({
        'success': True,
        'data': {
            'client_name': task.client_name,
            'date': task.date.strftime('%Y-%m-%d'),
            'start_time': task.start_time or '',
            'service_type': task.service_type,
            'description': task.description or ''
        }
    })

@app.route('/api/task_action/<int:task_id>/<action>', methods=['POST'])
@login_required
def task_action(task_id, action):
    task = Task.query.get(task_id)
    if not task:
        return jsonify({'success': False, 'msg': 'Tarea no encontrada'})
    
    if action == 'complete':
        task.status = 'Completado'
        db.session.commit()
        return jsonify({'success': True, 'msg': 'Tarea marcada como completada'})
        
    elif action == 'delete':
        # Eliminar archivos adjuntos si existen
        if task.attachments:
            try:
                attachments = json.loads(task.attachments)
                for filename in attachments:
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    if os.path.exists(filepath):
                        os.remove(filepath)
            except:
                pass
        
        db.session.delete(task)
        db.session.commit()
        return jsonify({'success': True, 'msg': 'Tarea eliminada'})
        
    return jsonify({'success': False, 'msg': 'Acción no válida'})

@app.route('/manage_stock', methods=['POST'])
@login_required
def manage_stock():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        existing = Stock.query.filter_by(name=request.form['name']).first()
        if not existing:
            db.session.add(Stock(
                name=request.form['name'],
                category=request.form['category'],
                quantity=int(request.form['quantity'])
            ))
            flash('Artículo añadido al inventario.', 'success')
        else:
            flash('Ese artículo ya existe en inventario.', 'warning')
            
    elif action == 'adjust':
        item = Stock.query.get(request.form['item_id'])
        if item:
            item.quantity += int(request.form['adjust_qty'])
            flash('Cantidad ajustada.', 'success')
            
    elif action == 'edit':
        item = Stock.query.get(request.form['item_id'])
        if item:
            item.name = request.form['name']
            item.category = request.form['category']
            item.quantity = int(request.form['quantity'])
            flash('Artículo actualizado.', 'success')
            
    elif action == 'delete':
        item = Stock.query.get(request.form['item_id'])
        if item:
            db.session.delete(item)
            flash('Artículo eliminado del inventario.', 'warning')
            
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/manage_clients', methods=['POST'])
@login_required
def manage_clients():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    
    action = request.form.get('action')
    
    if action == 'add':
        existing = Client.query.filter_by(name=request.form['name']).first()
        if not existing:
            db.session.add(Client(name=request.form['name']))
            flash('Cliente añadido.', 'success')
        else:
            flash('Ese cliente ya existe.', 'warning')
            
    elif action == 'edit':
        client = Client.query.get(request.form['client_id'])
        if client:
            client.name = request.form['name']
            flash('Cliente actualizado.', 'success')
            
    elif action == 'delete':
        client = Client.query.get(request.form['client_id'])
        if client:
            db.session.delete(client)
            flash('Cliente eliminado.', 'warning')
            
    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/export_clients')
@login_required
def export_clients():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    clients = Client.query.order_by(Client.name).all()
    data = [{'name': c.name} for c in clients]
    
    json_str = json.dumps(data, indent=2, ensure_ascii=False)
    buffer = io.BytesIO()
    buffer.write(json_str.encode('utf-8'))
    buffer.seek(0)
    
    return send_file(
        buffer,
        as_attachment=True,
        download_name='clientes_oslaprint.json',
        mimetype='application/json'
    )

@app.route('/import_clients', methods=['POST'])
@login_required
def import_clients():
    if current_user.role != 'admin':
        return redirect(url_for('dashboard'))
    
    if 'file' not in request.files:
        flash('No se seleccionó ningún archivo', 'danger')
        return redirect(url_for('dashboard'))
    
    file = request.files['file']
    
    if file.filename == '':
        flash('No se seleccionó ningún archivo', 'danger')
        return redirect(url_for('dashboard'))
    
    if not file.filename.endswith('.json'):
        flash('El archivo debe ser formato JSON', 'danger')
        return redirect(url_for('dashboard'))
    
    try:
        content = file.read().decode('utf-8')
        clients_data = json.loads(content)
        
        added = 0
        skipped = 0
        
        for client_info in clients_data:
            name = client_info.get('name', '').strip()
            if name:
                existing = Client.query.filter_by(name=name).first()
                if not existing:
                    db.session.add(Client(name=name))
                    added += 1
                else:
                    skipped += 1
        
        db.session.commit()
        flash(f'Importación completada: {added} clientes añadidos, {skipped} ya existían', 'success')
        
    except json.JSONDecodeError:
        flash('Error: El archivo JSON no es válido', 'danger')
    except Exception as e:
        flash(f'Error al importar: {str(e)}', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/api/clients_search')
@login_required
def search_clients():
    query = request.args.get('q', '')
    if len(query) < 2:
        return jsonify([])
    
    results = Client.query.filter(Client.name.ilike(f'%{query}%')).order_by(Client.name).limit(10).all()
    return jsonify([{'name': c.name} for c in results])

@app.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    """Servir archivos adjuntos"""
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/print_report/<int:task_id>')
@login_required
def print_report(task_id):
    task = Task.query.get_or_404(task_id)
    if current_user.role != 'admin' and current_user.id != task.tech_id:
        return "Acceso denegado", 403
    
    # Procesar archivos adjuntos
    attachments_html = ""
    if task.attachments:
        try:
            attachments = json.loads(task.attachments)
            if attachments:
                attachments_html = "<br><strong>Archivos adjuntos:</strong><br>"
                for filename in attachments:
                    attachments_html += f"- {filename}<br>"
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
            <div class="col-6">
                <div class="label">MATERIAL UTILIZADO/RETIRADO</div>
                <div class="box">
                    { f"Stock ({'USADO' if task.stock_action == 'used' else 'RETIRADO'}): {task.stock_quantity_used}x {task.stock_item.name}<br>" if task.stock_item else "" }
                    { f"Notas/Retirado: {task.parts_text}" if task.parts_text else "Sin notas adicionales" }
                    {attachments_html}
                </div>
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
                'service_type': t.service_type
            }
        })
    return jsonify(events)


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
            {'name': 'Revisión', 'color': '#0d6efd'},
            {'name': 'Instalación', 'color': '#6f42c1'},
            {'name': 'Urgencia', 'color': '#dc3545'},
            {'name': 'Avería', 'color': '#fd7e14'},
            {'name': 'Mantenimiento', 'color': '#20c997'},
            {'name': 'Otro', 'color': '#adb5bd'}
        ]
        for s in servicios:
            db.session.add(ServiceType(name=s['name'], color=s['color']))

    # 3. Datos de ejemplo
    if not Stock.query.first():
        db.session.add(Stock(name='Toner Genérico', category='Consumible', quantity=10))
    if not Client.query.first():
        db.session.add(Client(name='Cliente Ejemplo'))
        
    db.session.commit()

# --- ARRANQUE ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
